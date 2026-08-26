import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "replay_saved_s1_minimality.py"
SPEC = importlib.util.spec_from_file_location("saved_s1_minimality_replay", SCRIPT_PATH)
REPLAY = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = REPLAY
SPEC.loader.exec_module(REPLAY)


MODEL = "fixture-qwen"
RETRIEVER = "fixture-retriever"
COMMIT = "a" * 40
TREE = "b" * 40
LINEAGE = "c" * 64

SHAPES = {
    "qa_145_2hop_559_rand": (1, 1, 1, 2),
    "qa_68_1hop_100": (1, 1, 1, 1),
    "qa_209_3hop_360": (1, 2, 2, 2),
    "qa_2_1hop_4": (1, 1, 1, 1),
    "qa_435_2hop_678": (2, 2, 2, 2),
    "qa_281_2hop_441": (1, 1, 2, 2),
    "qa_134_2hop_515_rand": (2, 2, 2, 2),
    "qa_366_3hop_580": (3, 3, 3, 3),
}


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _plan(question, shape):
    target_count, issue_count, evidence_count, requirement_count = shape
    anchors = ["answer-%d" % index for index in range(1, target_count + 1)]
    targets = [{
        "answer_target_id": "T%d" % index, "question_anchor": anchor,
        "requested_output": "requested output %d" % index, "answer_type": "legal_result",
    } for index, anchor in enumerate(anchors, 1)]
    issues = [{"issue_id": "I%d" % index, "description": "issue %d" % index, "importance": "critical"}
              for index in range(1, issue_count + 1)]
    evidence = []
    requests = []
    for index in range(1, evidence_count + 1):
        target_id = "T%d" % (((index - 1) % target_count) + 1)
        requirement_total = requirement_count if evidence_count == 1 else 1
        requirements = [{"requirement_id": "E%d-R%d" % (index, subindex), "text": "requirement %d-%d" % (index, subindex)}
                        for subindex in range(1, requirement_total + 1)]
        evidence.append({
            "evidence_item_id": "E%d" % index, "issue_id": "I%d" % (((index - 1) % issue_count) + 1),
            "evidence_type": "rule", "description": "evidence %d" % index, "critical": True,
            "completion_criteria": "criteria %d" % index, "necessity_reason": "explicit output",
            "answer_target_ids": [target_id], "scope_source": "explicit_question",
            "completion_requirements": requirements,
        })
        requests.append({
            "request_id": "RQ%d" % index, "issue_id": evidence[-1]["issue_id"], "evidence_item_id": "E%d" % index,
            "query_channel": "statute_aware", "query_text": "query %d" % index, "top_k": 100,
            "query_terms": ["term%d" % index], "statute_hints": [], "rationale": "focused",
        })
    return {
        "schema_version": "1.0", "skill_id": "S1", "mode": "INITIAL_PLAN", "status": "ok",
        "answer_targets": targets, "legal_issues": issues, "required_evidence_items": evidence,
        "retrieval_requests": requests, "question": "[질문] " + " ".join(anchors),
    }


class ScriptedExecutor:
    def __init__(self, *, diagnostic_sink, output, **_kwargs):
        self.diagnostic_sink = diagnostic_sink
        self.output = output
        self.calls = []

    def execute(self, skill_name, entry_point, payload):
        self.calls.append((skill_name, entry_point, copy.deepcopy(payload)))
        if (skill_name, entry_point) != (REPLAY.S1_SKILL, REPLAY.S1_ENTRY_POINT):
            raise AssertionError("blocked stage reached fake executor")
        value = copy.deepcopy(self.output)
        value["run_id"] = payload["run_id"]
        response = json.dumps(value, ensure_ascii=False, sort_keys=True)
        encoded = response.encode("utf-8")
        self.diagnostic_sink({
            "schema_version": "1.2", "run_id": payload["run_id"], "skill_name": skill_name,
            "skill_id": "S1", "generation_kind": "primary_skill_attempt", "entry_point": entry_point,
            "attempt": 1, "requested_max_tokens": 4096, "outcome": "valid", "response_text": response,
            "response_sha256": hashlib.sha256(encoded).hexdigest(), "response_utf8_bytes": len(encoded),
            "response_characters": len(response), "response_tail": response[-512:],
        })
        return value


class SavedS1MinimalityReplayTests(unittest.TestCase):
    def _write_source(self, directory, question_id):
        plan = _plan("", SHAPES[question_id])
        question = plan.pop("question")
        profile = REPLAY._profile(question_id)
        state = {
            "normalized_question": question,
            "answer_targets": plan["answer_targets"], "legal_issues": plan["legal_issues"],
            "required_evidence_items": plan["required_evidence_items"], "query_history": plan["retrieval_requests"],
        }
        result = {"run_id": "baseline-%s" % question_id, "state": state}
        metadata = {
            "question_id": question_id, "question": question,
            "source_snapshot": {"git_commit": COMMIT, "git_tree": TREE, "source_manifest_sha256": LINEAGE},
            "configuration": {
                "model": MODEL, "retriever": RETRIEVER, "num_ctx": 32768, "seed": 0,
                "s1_max_tokens": 4096, "s1_truncation_retry_max_tokens": 8192,
                "ollama_endpoint": "http://fixture.invalid", "source_manifest_sha256": LINEAGE,
            },
        }
        result_path = directory / "result.json"
        metadata_path = directory / "metadata.json"
        manifest_path = directory / "manifest.json"
        receipt_path = directory / "receipt.json"
        entry = {"question_id": question_id, **{field: profile[field] for field in ("sequence", "ordinal", "n_hops")}}
        manifest = {"schema_version": "c02_targeted_resume_batch_manifest_v1", "parent_manifest": "/frozen/v2_kure_full226.json", "entries": [entry]}
        receipt = {"schema_version": "c02_targeted_resume_task_receipt_v1", "task": entry, "summary_row": {**entry, "record_result_file": str(result_path.resolve()), "run_id": result["run_id"]}}
        for path, value in ((result_path, result), (metadata_path, metadata), (manifest_path, manifest), (receipt_path, receipt)):
            path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        expected = REPLAY.ReplayExpectations(
            question_id, _hash(result_path), _hash(metadata_path), _hash(manifest_path), _hash(receipt_path),
            COMMIT, TREE, MODEL, RETRIEVER, LINEAGE,
        )
        return result_path, metadata_path, manifest_path, receipt_path, expected, plan

    def _run(self, directory, question_id, *, resume=False, factory=None, expected=None):
        result, metadata, manifest, receipt, generated_expected, plan = self._write_source(directory, question_id)
        executors = []
        def default_factory(**kwargs):
            executor = ScriptedExecutor(output=plan, **kwargs)
            executors.append(executor)
            return executor
        replay = REPLAY.replay_saved_s1_initial_plan(
            source_result=result, source_metadata=metadata, source_manifest=manifest, source_task_receipt=receipt,
            output_root=directory / "out", question_id=question_id, project_root=ROOT,
            executor_factory=factory or default_factory, expectations=expected or generated_expected, resume=resume,
        )
        return replay, executors, (result, metadata, manifest, receipt, generated_expected, plan)

    def test_all_profile_classes_execute_only_s1_and_pass_structural_assertions(self):
        for question_id in SHAPES:
            with self.subTest(question_id=question_id), tempfile.TemporaryDirectory() as raw:
                replay, executors, _ = self._run(Path(raw), question_id)
                self.assertEqual(replay.payload["replay_status"], "S1_INITIAL_PLAN_COMPLETED")
                self.assertEqual([(call[0], call[1]) for call in executors[0].calls], [(REPLAY.S1_SKILL, REPLAY.S1_ENTRY_POINT)])
                self.assertTrue(all(item["passed"] for item in replay.payload["comparison"]["assertions"]))
                self.assertEqual(replay.payload["scope"]["hard_blocked"], sorted(REPLAY.FORBIDDEN_STAGES))
                attempts = [json.loads(line) for line in (replay.output_directory / "skill_attempts.jsonl").read_text(encoding="utf-8").splitlines()]
                self.assertEqual([item["generation_kind"] for item in attempts], ["s1_initial_plan_minimality_probe"])
                self.assertEqual(attempts[0]["upstream_generation_kind"], "primary_skill_attempt")
                self.assertTrue((replay.output_directory / "comparison.json").is_file())

    def test_resume_revalidates_bindings_without_constructing_executor(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            replay, executors, paths = self._run(directory, "qa_435_2hop_678")
            result, metadata, manifest, receipt, expected, _ = paths
            resumed = REPLAY.replay_saved_s1_initial_plan(
                source_result=result, source_metadata=metadata, source_manifest=manifest, source_task_receipt=receipt,
                output_root=directory / "out", question_id=expected.question_id, project_root=ROOT,
                expectations=expected, resume=True,
                executor_factory=lambda **_kwargs: self.fail("resume must not construct an executor"),
            )
            self.assertTrue(resumed.resumed)
            self.assertEqual(len(executors[0].calls), 1)

    def test_hash_and_allowlist_reject_before_output_creation(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            result, metadata, manifest, receipt, expected, _ = self._write_source(directory, "qa_68_1hop_100")
            bad = REPLAY.ReplayExpectations(
                expected.question_id, "0" * 64, expected.source_metadata_sha256, expected.source_manifest_sha256,
                expected.source_task_receipt_sha256, COMMIT, TREE, MODEL, RETRIEVER, LINEAGE,
            )
            with self.assertRaisesRegex(REPLAY.ReplayError, "saved result SHA256 mismatch"):
                REPLAY.replay_saved_s1_initial_plan(
                    source_result=result, source_metadata=metadata, source_manifest=manifest, source_task_receipt=receipt,
                    output_root=directory / "out", question_id=expected.question_id, project_root=ROOT, expectations=bad,
                    executor_factory=lambda **_kwargs: self.fail("hash failure must not construct executor"),
                )
            self.assertFalse((directory / "out").exists())
            with self.assertRaisesRegex(REPLAY.ReplayError, "allowlist"):
                REPLAY._profile("qa_outside_allowlist")

    def test_no_overwrite_and_direct_blocked_stage_guard(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            replay, _, paths = self._run(directory, "qa_2_1hop_4")
            result, metadata, manifest, receipt, expected, _ = paths
            with self.assertRaisesRegex(REPLAY.ReplayError, "refusing to overwrite"):
                REPLAY.replay_saved_s1_initial_plan(
                    source_result=result, source_metadata=metadata, source_manifest=manifest, source_task_receipt=receipt,
                    output_root=directory / "out", question_id=expected.question_id, project_root=ROOT, expectations=expected,
                    executor_factory=lambda **_kwargs: self.fail("overwrite must not construct executor"),
                )
            with self.assertRaisesRegex(REPLAY.ReplayError, "blocks stage"):
                REPLAY.S1OnlyExecutor(object()).execute("provision_coverage_assessment", "ASSESS_COVERAGE", {})
            self.assertTrue(replay.output_directory.is_dir())

    def test_distinct_critical_obligations_allows_multiple_output_determinative_bridges(self):
        candidate = _plan("", (1, 3, 3, 3))
        outcome = REPLAY._assert_profile(
            {"assertions": [{"kind": "distinct_critical_obligations"}]}, candidate,
        )
        self.assertEqual(outcome, [{"kind": "distinct_critical_obligations", "duplicate_critical_evidence_item_ids": [], "passed": True}])

    def test_distinct_critical_obligations_rejects_a_duplicate_lane(self):
        candidate = _plan("", (1, 2, 2, 2))
        candidate["required_evidence_items"][1]["completion_requirements"][0]["text"] = "requirement 1-1"
        outcome = REPLAY._assert_profile(
            {"assertions": [{"kind": "distinct_critical_obligations"}]}, candidate,
        )
        self.assertEqual(outcome, [{
            "kind": "distinct_critical_obligations",
            "duplicate_critical_evidence_item_ids": [["E1", "E2"]],
            "passed": False,
        }])

    def test_unsupported_statute_substitution_is_blocked_before_comparison(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            result, metadata, manifest, receipt, expected, plan = self._write_source(directory, "qa_281_2hop_441")
            metadata_payload = json.loads(metadata.read_text(encoding="utf-8"))
            metadata_payload["question"] = "[질문] 특별규정법상 미수 처벌을 판단하라. answer-1"
            metadata.write_text(json.dumps(metadata_payload, ensure_ascii=False), encoding="utf-8")
            plan["retrieval_requests"][0]["statute_hints"] = ["일반규정법"]
            expected = REPLAY.ReplayExpectations(
                expected.question_id, expected.source_result_sha256, _hash(metadata),
                expected.source_manifest_sha256, expected.source_task_receipt_sha256,
                expected.source_commit, expected.source_tree, expected.source_model,
                expected.source_retriever, expected.source_manifest_lineage_sha256,
            )

            with self.assertRaisesRegex(REPLAY.ReplayError, "not directly supported"):
                REPLAY.replay_saved_s1_initial_plan(
                    source_result=result, source_metadata=metadata, source_manifest=manifest,
                    source_task_receipt=receipt, output_root=directory / "out",
                    question_id=expected.question_id, project_root=ROOT,
                    expectations=expected,
                    executor_factory=lambda **kwargs: ScriptedExecutor(output=plan, **kwargs),
                )

    def test_output_root_under_workspace_is_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            result, metadata, manifest, receipt, expected, _ = self._write_source(directory, "qa_281_2hop_441")
            source = REPLAY.load_saved_source(result, metadata, manifest, receipt, expected)
            with self.assertRaisesRegex(REPLAY.ReplayError, "must not be under /workspace"):
                REPLAY._output_directory(Path("/workspace/forbidden"), source, "d" * 40)


if __name__ == "__main__":
    unittest.main()
