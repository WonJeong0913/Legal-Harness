import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.evaluate_dev_runs import EvaluationError, load_lf_eval_scores
from scripts import v2_kure_orchestration as v2


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


adapted = load_module("adapted_local_lf_eval_test", "scripts/run_adapted_local_lf_eval.py")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FakeResponse:
    def __init__(self, value):
        self.value = value

    def read(self):
        return json.dumps(self.value, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False


def frozen_configuration():
    return {
        "condition": "fixture-full226+C36-prompt-stable-validator-only-C35",
        "retriever": "kure",
        "model": v2.EXPECTED_RUNTIME["model"],
        "ollama_endpoint": v2.EXPECTED_RUNTIME["endpoint"],
        "seed": 0,
        "model_provenance": dict(v2.QWEN_MODEL_PROVENANCE),
    }


def build_fixture(root, execution_failure=False):
    worktree = root / "frozen-worktree"
    qa_path = worktree / "data" / "fixture.jsonl"
    entries = [
        {"ordinal": ordinal, "question_id": "fixture_%03d" % ordinal, "n_hops": ((ordinal - 1) % 3) + 1}
        for ordinal in range(1, 227)
    ]
    gold_rows = [
        {
            "id": entry["question_id"],
            "background": "배경 %03d " % entry["ordinal"],
            "question": "질문 %03d" % entry["ordinal"],
            "answer": "정답 %03d" % entry["ordinal"],
            "contexts": [{"hierarchy": "법 %03d" % entry["ordinal"], "content": " 조문"}],
        }
        for entry in entries
    ]
    write_jsonl(qa_path, gold_rows)
    manifest = {
        "name": "C36 fixture full226",
        "entries": entries,
        "source_dataset": {"path": "data/fixture.jsonl", "sha256": digest(qa_path)},
        "frozen_configuration": frozen_configuration(),
    }
    manifest_path = worktree / "frozen_manifests" / "v2_kure_full226.json"
    write_json(manifest_path, manifest)
    output_root = root / "kure-output"
    mode = output_root / "full226"
    plan = {
        "mode": "full226",
        "entry_count": 226,
        "exec_root": str(worktree),
        "primary_manifest": str(manifest_path),
        "primary_manifest_sha256": digest(manifest_path),
        "frozen_configuration": frozen_configuration(),
        "execution_policy": {"bm25_execution": "FORBIDDEN", "lf_eval_score_injection": "FORBIDDEN"},
    }
    write_json(mode / "plan.json", plan)
    checkpoint_status = (
        v2.FULL226_COMPLETED_WITH_ERRORS if execution_failure else "PASS"
    )
    collection_status = (
        v2.FULL226_EXPLICIT_FAILURE_COLLECTION if execution_failure else "COMPLETE"
    )
    write_json(mode / "gate.json", {
        "status": checkpoint_status,
        "collection_status": collection_status,
    })
    batch = mode / "checkpoints" / "batch-226-attempt-fixture"
    summaries = []
    for entry in entries:
        ordinal, question_id = entry["ordinal"], entry["question_id"]
        status = "EXECUTION_FAILURE" if execution_failure and ordinal == 3 else "ANSWER" if ordinal == 1 else "ABSTAIN"
        run = mode / "records" / "runs" / ("run-%03d" % ordinal)
        candidate = "후보 답변" if ordinal == 2 else ("공개 답변" if ordinal == 1 else None)
        result = {
            "run_id": "run-%03d" % ordinal,
            "status": status,
            "answer": "공개 답변" if ordinal == 1 else None,
            "candidate_answer": candidate,
            "candidate_answer_status": "PUBLISHED_ANSWER" if ordinal == 1 else ("GENERATED" if ordinal == 2 else None),
            "candidate_answer_basis": "published_answer" if ordinal == 1 else ("retrieved_candidates" if ordinal == 2 else None),
        }
        write_json(run / "result.json", result)
        write_json(run / "metadata.json", {"question_id": question_id})
        summaries.append({
            "ordinal": ordinal,
            "question_id": question_id,
            "status": status,
            "record_directory": str(run),
            "run_id": "run-%03d" % ordinal,
        })
    write_jsonl(batch / "summary.jsonl", summaries)
    write_json(mode / "checkpoints" / "checkpoint-226.json", {
        "checkpoint_status": checkpoint_status,
        "collection_status": collection_status,
        "completed_questions": 226,
        "validation_errors": [],
        "execution_failure_question_ids": ["fixture_003"] if execution_failure else [],
        "execution_failure_count": 1 if execution_failure else 0,
        "batch_directory": str(batch),
        "bm25_execution": "FORBIDDEN",
        "lf_eval_score_injection": "FORBIDDEN",
    })
    parser_rows = []
    for entry, gold in zip(reversed(entries), reversed(gold_rows)):
        parser_rows.append({
            "question_id": entry["question_id"],
            "background": gold["background"],
            "question": gold["question"],
            "answer": "ParSeR 답변 %03d" % entry["ordinal"],
            "gold_answer": gold["answer"],
            "gold_contexts": [gold["contexts"][0]["hierarchy"] + gold["contexts"][0]["content"]],
            "error": "fixture failure" if entry["ordinal"] == 3 else None,
        })
    parser_path = root / "parser" / "final_results.jsonl"
    write_jsonl(parser_path, parser_rows)
    return output_root, parser_path, worktree, mode


class AdaptedLocalLFEvalTests(unittest.TestCase):
    def test_exact_official_projection_and_rubric_are_frozen(self):
        self.assertEqual(adapted.official_prediction("a" * 801), "a" * 800)
        # The official source has an accidental \t escape, so a literal <\\think>
        # marker is not stripped by its exact projection.
        self.assertEqual(adapted.official_prediction("x<\\think>y"), "x<\\think>y")
        prompt = adapted.build_prompt(
            {"input": "Q", "expected_output": "A", "context": ["C"]}, "P"
        )
        self.assertIn(adapted.OFFICIAL_CRITERIA, prompt)
        for step in adapted.OFFICIAL_EVALUATION_STEPS:
            self.assertIn(step, prompt)
        self.assertEqual(
            adapted.canonical_sha256(adapted.OFFICIAL_RUBRIC),
            adapted.canonical_sha256({
                "criteria": adapted.OFFICIAL_CRITERIA,
                "evaluation_steps": list(adapted.OFFICIAL_EVALUATION_STEPS),
                "evaluation_params": ("input", "actual_output", "expected_output", "context"),
            }),
        )

    def test_paired_output_is_isolated_noninjectable_and_preserves_policies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kure_root, parser_path, worktree, mode = build_fixture(root)
            inputs_before = {"manifest": digest(worktree / "frozen_manifests" / "v2_kure_full226.json"), "parser": digest(parser_path), "checkpoint": digest(mode / "checkpoints" / "checkpoint-226.json")}
            requests = []

            def fake_urlopen(request, timeout):
                requests.append(json.loads(request.data.decode("utf-8")))
                return FakeResponse({"response": '{"score": 7}'})

            output_dir = root / "adapted-output"
            with patch.object(adapted, "_verify_judge", return_value={"model_blob_sha256": "f" * 64}), patch.object(adapted, "urlopen", side_effect=fake_urlopen):
                result = adapted.run_adapted_local_lf_eval(kure_root, parser_path, output_dir, timeout_seconds=3)
            self.assertTrue((output_dir / "receipt.json").is_file())
            self.assertEqual(result["aggregate"]["evaluator_id"], adapted.EVALUATOR_ID)
            aggregate = json.loads((output_dir / "aggregate.json").read_text(encoding="utf-8"))
            self.assertEqual(aggregate["official_lf_eval"]["execution_status"], "NOT_EXECUTED_EXTERNAL_GPT4O_DEEPEVAL_FORBIDDEN")
            self.assertEqual(aggregate["official_lf_eval"]["score_equivalence"], "FORBIDDEN")
            self.assertEqual(aggregate["execution_prohibitions"]["kure_primary_score_injection"], "FORBIDDEN")
            self.assertEqual(aggregate["conditions"]["OUR_C36_KURE"]["public_answer"]["model_scored_count"], 1)
            self.assertEqual(aggregate["conditions"]["OUR_C36_KURE"]["public_answer"]["unjudged_zero_count"], 225)
            self.assertEqual(aggregate["conditions"]["OUR_C36_KURE"]["candidate_answer"]["model_scored_count"], 2)
            self.assertEqual(aggregate["conditions"]["PARSER_REPRODUCED"]["public_answer"]["model_scored_count"], 225)
            self.assertFalse(aggregate["input_provenance"]["parser_reproduced"]["source_order_matches_c36"])
            rows = [json.loads(line) for line in (output_dir / "per_question.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["ordinal"] for row in rows], list(range(1, 227)))
            self.assertEqual(rows[1]["kure"]["public_answer"]["end_to_end_score_0_to_10"], 0)
            self.assertEqual(rows[1]["kure"]["candidate_answer"]["score_1_to_10"], 7)
            self.assertEqual(rows[2]["parser_reproduced"]["public_answer"]["end_to_end_score_0_to_10"], 0)
            self.assertGreater(len(requests), 200)
            self.assertTrue(all(item["model"] == v2.EXPECTED_RUNTIME["model"] for item in requests))
            self.assertTrue(all(item["options"]["temperature"] == 0 and item["options"]["seed"] == 0 for item in requests))
            with self.assertRaises(EvaluationError):
                load_lf_eval_scores(output_dir / "aggregate.json")
            self.assertEqual(inputs_before["manifest"], digest(worktree / "frozen_manifests" / "v2_kure_full226.json"))
            self.assertEqual(inputs_before["parser"], digest(parser_path))
            self.assertEqual(inputs_before["checkpoint"], digest(mode / "checkpoints" / "checkpoint-226.json"))

    def test_completed_collection_with_explicit_failure_is_zero_scored_not_masked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kure_root, parser_path, unused_worktree, mode = build_fixture(root, execution_failure=True)
            requests = []

            def fake_urlopen(request, timeout):
                requests.append(json.loads(request.data.decode("utf-8")))
                return FakeResponse({"response": '{"score": 7}'})

            with patch.object(adapted, "_verify_judge", return_value={"model_blob_sha256": "f" * 64}), patch.object(adapted, "urlopen", side_effect=fake_urlopen):
                adapted.run_adapted_local_lf_eval(kure_root, parser_path, root / "adapted-output", timeout_seconds=3)
            rows = [json.loads(line) for line in (root / "adapted-output" / "per_question.jsonl").read_text(encoding="utf-8").splitlines()]
            failed = rows[2]["kure"]
            self.assertEqual(failed["status"], "EXECUTION_FAILURE")
            self.assertFalse(failed["public_answer"]["available"])
            self.assertEqual(failed["public_answer"]["end_to_end_score_0_to_10"], 0)
            self.assertFalse(failed["candidate_answer"]["available"])
            self.assertEqual(failed["candidate_answer"]["end_to_end_score_0_to_10"], 0)
            write_json(mode / "gate.json", {"status": "PASS", "collection_status": "COMPLETE"})
            with patch.object(adapted, "_verify_judge") as judge:
                with self.assertRaisesRegex(adapted.AdaptedLocalLFEvalError, "status mismatch"):
                    adapted.run_adapted_local_lf_eval(kure_root, parser_path, root / "rejected-output")
            judge.assert_not_called()

    def test_manifest_pinned_linked_dataset_allows_only_relative_exact_hash_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kure_root, unused_parser, worktree, unused_mode = build_fixture(root)
            dataset = worktree / "data" / "fixture.jsonl"
            linked_asset = root / "linked-assets" / "fixture.jsonl"
            linked_asset.parent.mkdir()
            linked_asset.write_bytes(dataset.read_bytes())
            expected_sha = digest(linked_asset)
            dataset.unlink()
            dataset.symlink_to(linked_asset)
            unused_entries, unused_outcome, provenance = adapted._load_kure_condition(kure_root)
            self.assertEqual(provenance["source_dataset"], str(linked_asset.resolve()))
            self.assertEqual(provenance["source_dataset_sha256"], expected_sha)
            self.assertTrue(provenance["source_dataset_linked_asset"])
            with self.assertRaisesRegex(adapted.AdaptedLocalLFEvalError, "traversal-free relative"):
                adapted._frozen_linked_dataset_path(worktree, "../linked-assets/fixture.jsonl", expected_sha)
            with self.assertRaisesRegex(adapted.AdaptedLocalLFEvalError, "traversal-free relative"):
                adapted._frozen_linked_dataset_path(worktree, str(linked_asset), expected_sha)
            linked_asset.write_text("different", encoding="utf-8")
            with self.assertRaisesRegex(adapted.AdaptedLocalLFEvalError, "hash mismatch"):
                adapted._load_kure_condition(kure_root)

    def test_mismatched_parser_roster_fails_before_judge_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kure_root, parser_path, unused_worktree, unused_mode = build_fixture(root)
            rows = [json.loads(line) for line in parser_path.read_text(encoding="utf-8").splitlines()]
            rows[-1]["question_id"] = "wrong_id"
            write_jsonl(parser_path, rows)
            with patch.object(adapted, "_verify_judge") as judge:
                with self.assertRaisesRegex(adapted.AdaptedLocalLFEvalError, "roster"):
                    adapted.run_adapted_local_lf_eval(kure_root, parser_path, root / "new-output")
            judge.assert_not_called()

    def test_existing_or_nested_output_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kure_root, parser_path, unused_worktree, unused_mode = build_fixture(root)
            existing = root / "existing"
            existing.mkdir()
            with self.assertRaisesRegex(adapted.AdaptedLocalLFEvalError, "overwrite"):
                adapted.run_adapted_local_lf_eval(kure_root, parser_path, existing)
            with self.assertRaisesRegex(adapted.AdaptedLocalLFEvalError, "inside an input"):
                adapted.run_adapted_local_lf_eval(kure_root, parser_path, kure_root / "full226" / "adapted")

    def test_malformed_local_judge_score_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            kure_root, parser_path, unused_worktree, unused_mode = build_fixture(root)
            with patch.object(adapted, "_verify_judge", return_value={"ready": True}), patch.object(adapted, "urlopen", return_value=FakeResponse({"response": "score: 7"})):
                with self.assertRaisesRegex(adapted.AdaptedLocalLFEvalError, "not JSON"):
                    adapted.run_adapted_local_lf_eval(kure_root, parser_path, root / "failed-output")

    def test_local_blob_hash_is_checked_after_alias_readiness(self):
        with tempfile.TemporaryDirectory() as temporary:
            blob = Path(temporary) / "qwen.gguf"
            blob.write_bytes(b"exact-blob")
            provenance = dict(v2.QWEN_MODEL_PROVENANCE)
            provenance.update({"ollama_model_blob": str(blob), "sha256": digest(blob)})
            with patch.object(adapted.v2, "QWEN_MODEL_PROVENANCE", provenance), patch.object(
                adapted.v2, "check_local_ollama_readiness", return_value={"resolved_model_name": "legal-harness-qwen38-q8:latest"}
            ) as readiness:
                verified = adapted._verify_judge({"model": provenance["alias"]}, 3)
            readiness.assert_called_once()
            self.assertEqual(verified["model_blob_sha256"], digest(blob))
            blob.write_bytes(b"different")
            with patch.object(adapted.v2, "QWEN_MODEL_PROVENANCE", provenance), patch.object(adapted.v2, "check_local_ollama_readiness"):
                with self.assertRaisesRegex(adapted.AdaptedLocalLFEvalError, "blob"):
                    adapted._verify_judge({"model": provenance["alias"]}, 3)


if __name__ == "__main__":
    unittest.main()
