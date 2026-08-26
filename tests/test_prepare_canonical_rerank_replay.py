import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_canonical_rerank_replay import (
    C02_QA150_PROFILE,
    ReplayPreparationError,
    c02_paths_from_root,
    prepare_c02_qa150,
    preflight_initial_structured_transforms,
)


ACTUAL_C02_ROOT = Path(
    "/workspace/Legal-Harness/records/"
    "v2-kure-qwen38-offline-full226-c02e281-targeted-resume168-20260826"
)


def file_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def fixture_state():
    return {
        "normalized_question": "[질문]\n신청인이 충족해야 할 요건은 무엇인가",
        "legal_issues": [{"issue_id": "I1", "description": "요건"}],
        "answer_targets": [{
            "answer_target_id": "T1",
            "question_anchor": "신청인이 충족해야 할 요건은 무엇인가",
            "requested_output": "요건 목록",
            "answer_type": "legal_elements",
        }],
        "required_evidence_items": [{
            "evidence_item_id": "E1",
            "issue_id": "I1",
            "evidence_type": "application_requirement",
            "description": "요건",
            "critical": True,
            "completion_criteria": "요건",
            "necessity_reason": "답변에 필요",
            "answer_target_ids": ["T1"],
            "scope_source": "explicit_question",
            "completion_requirements": [{
                "requirement_id": "CR1",
                "text": "제출 기한",
            }],
        }],
        "query_history": [{
            "request_id": "RQ1",
            "issue_id": "I1",
            "evidence_item_id": "E1",
            "query_channel": "provision_style",
            "query_text": "배경 전체는 canonical BGE 질의에 포함되지 않는다",
            "top_k": 100,
            "query_terms": ["요건"],
            "statute_hints": [],
            "first_stage_query_text": None,
            "rerank_query_text": None,
        }, {
            "request_id": "GRQ-R2-1",
            "issue_id": "I1",
            "evidence_item_id": "E1",
            "query_channel": "statute_aware",
            "query_text": "갭 질의",
            "top_k": 100,
            "query_terms": ["갭"],
            "statute_hints": [],
            "first_stage_query_text": None,
            "rerank_query_text": None,
        }],
    }


def write_fixture(root):
    profile = copy.deepcopy(C02_QA150_PROFILE)
    paths = c02_paths_from_root(root, profile)
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)

    result = {
        "run_id": profile["run_id"],
        "state": fixture_state(),
        "retrieval_provenance": {
            "stage_file": "retrieval_stages.jsonl",
            "stage_record_counts": {
                "first_stage": 1,
                "request_rerank": 1,
                "round_selected": 1,
            },
        },
    }
    paths["result"].write_text(
        json.dumps(result, ensure_ascii=False), encoding="utf-8"
    )
    metadata = {
        "run_id": profile["run_id"],
        "question_id": profile["question_id"],
        "git_commit": profile["source_commit"],
        "source_snapshot": {
            "git_commit": profile["source_commit"],
            "git_tree": profile["source_tree"],
            "source_manifest_sha256": profile["source_manifest_sha256"],
        },
        "configuration": {
            "retriever": "kure",
            "model": "legal-harness-qwen38-q8",
            "rerank_query_mode": "per_request",
            "rerank_pool_k": 100,
            "final_top_k": 10,
            "source_manifest_sha256": profile["source_manifest_sha256"],
        },
    }
    paths["metadata"].write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
    )
    stages = [
        {
            "candidate_stage": "first_stage",
            "provision_id": "P-first",
            "source_request_ids": ["RQ1"],
            "retrieval_round": 1,
            "first_stage_rank": 1,
            "first_stage_score": 0.9,
        },
        {
            "candidate_stage": "request_rerank",
            "provision_id": "P-first",
            "source_request_ids": ["RQ1"],
            "retrieval_round": 1,
            "rerank_rank": 5,
            "rerank_score": 0.4,
        },
        {
            "candidate_stage": "round_selected",
            "provision_id": "P-other",
            "source_request_ids": ["RQ1"],
            "retrieval_round": 1,
            "selection_rank": 1,
        },
    ]
    paths["retrieval_stages"].write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in stages) + "\n",
        encoding="utf-8",
    )
    paths["events"].write_text(
        json.dumps({"run_id": profile["run_id"], "event": "RUN_STARTED"}) + "\n",
        encoding="utf-8",
    )
    batch_manifest = {
        "schema_version": "c02_targeted_resume_batch_manifest_v1",
        "parent_manifest_sha256": profile["primary_manifest_sha256"],
        "execution_policy": {
            "primary_retriever": "kure",
            "paired_bm25": "READ_ONLY_CONFIGURATION_GUARD_NEVER_EXECUTED",
        },
        "entries": [{
            key: profile[key]
            for key in ("sequence", "ordinal", "question_id", "n_hops", "retry")
        }],
    }
    paths["batch_manifest"].write_text(
        json.dumps(batch_manifest, ensure_ascii=False), encoding="utf-8"
    )
    summary_row = {
        key: profile[key]
        for key in ("sequence", "ordinal", "question_id", "n_hops", "retry", "run_id")
    }
    summary_row.update({
        "record_result_file": str(paths["result"]),
        "record_directory": str(paths["result"].parent),
    })
    receipt = {
        "schema_version": "c02_targeted_resume_task_receipt_v1",
        "task": {
            key: profile[key]
            for key in ("sequence", "ordinal", "question_id", "n_hops", "retry")
        },
        "summary_row": summary_row,
        "summary_sha256": canonical_sha256(summary_row),
        "record_directories_created": [str(paths["result"].parent)],
    }
    paths["task_receipt"].write_text(
        json.dumps(receipt, ensure_ascii=False), encoding="utf-8"
    )
    profile["sha256"] = {
        key: file_sha256(path) for key, path in paths.items()
    }
    return paths, profile


class ReplayPreparationTests(unittest.TestCase):
    def test_real_receipt_schema_selects_only_rq_and_excludes_grq(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, profile = write_fixture(Path(temporary))
            payload = prepare_c02_qa150(paths, profile=profile)

        self.assertEqual(
            payload["initial_plan_reconstruction"]["selected_initial_request_ids"],
            ["RQ1"],
        )
        self.assertEqual(
            payload["initial_plan_reconstruction"]["excluded_gap_request_ids"],
            ["GRQ-R2-1"],
        )
        self.assertEqual(
            payload["canonical_rerank_query"]["transforms"][0]["source"],
            "canonical_missing_only",
        )
        self.assertNotIn(
            "배경 전체는 canonical BGE 질의에 포함되지 않는다",
            payload["canonical_rerank_query"]["transforms"][0]["final_request"][
                "rerank_query_text"
            ],
        )
        stage = payload["retrieval_stage_observation"]
        self.assertTrue(
            stage["observed_first_stage_top1_absent_from_round_selected"]
        )
        self.assertFalse(stage["uses_gold_or_benchmark_answer"])

    def test_receipt_coordinate_tampering_fails_after_hash_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, profile = write_fixture(Path(temporary))
            receipt = json.loads(
                paths["task_receipt"].read_text(encoding="utf-8")
            )
            receipt["task"]["ordinal"] = 87
            paths["task_receipt"].write_text(
                json.dumps(receipt, ensure_ascii=False), encoding="utf-8"
            )
            profile["sha256"]["task_receipt"] = file_sha256(
                paths["task_receipt"]
            )

            with self.assertRaisesRegex(
                ReplayPreparationError, "receipt task.ordinal"
            ):
                prepare_c02_qa150(paths, profile=profile)

    def test_unknown_saved_request_id_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, profile = write_fixture(Path(temporary))
            result = json.loads(paths["result"].read_text(encoding="utf-8"))
            result["state"]["query_history"].append({"request_id": "UNKNOWN-1"})
            paths["result"].write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8"
            )
            profile["sha256"]["result"] = file_sha256(paths["result"])

            with self.assertRaisesRegex(
                ReplayPreparationError, "non-initial, non-gap"
            ):
                prepare_c02_qa150(paths, profile=profile)

    def test_copied_or_renamed_source_paths_fail_before_content_parsing(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, profile = write_fixture(Path(temporary))
            paths["metadata"] = paths["result"]

            with self.assertRaisesRegex(
                ReplayPreparationError, "metadata path does not match"
            ):
                prepare_c02_qa150(paths, profile=profile)

    def test_preflight_reports_fail_closed_count_without_live_components(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths, _profile = write_fixture(root)
            report = preflight_initial_structured_transforms(root / "records" / "runs")

        self.assertEqual(report["record_directory_count"], 1)
        self.assertEqual(report["valid_transform_count"], 1)
        self.assertEqual(report["failure_count"], 0)

    @unittest.skipUnless(
        (ACTUAL_C02_ROOT / "records" / "runs" / C02_QA150_PROFILE["run_id"] / "result.json").is_file(),
        "real C02 qa150 artifacts are not mounted",
    )
    def test_actual_c02_qa150_profile_prepares_read_only(self):
        payload = prepare_c02_qa150(c02_paths_from_root(ACTUAL_C02_ROOT))

        self.assertEqual(
            payload["initial_plan_reconstruction"]["selected_initial_request_ids"],
            ["RQ1"],
        )
        self.assertEqual(
            payload["initial_plan_reconstruction"]["excluded_gap_request_ids"],
            ["GRQ-R2-1", "GRQ-R2-2"],
        )
        self.assertEqual(
            payload["canonical_rerank_query"]["transforms"][0][
                "final_rerank_query_characters"
            ],
            254,
        )
        self.assertEqual(
            payload["retrieval_stage_observation"]["first_stage_top1_bge"][
                "rerank_rank"
            ],
            96,
        )


if __name__ == "__main__":
    unittest.main()
