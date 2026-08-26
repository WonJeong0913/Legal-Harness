import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_canonical_rerank_replay import (
    ReplayPreparationError,
    prepare_from_archived_result,
    verify_source_receipt,
)


def file_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archived_result():
    return {
        "state": {
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
                "request_id": "RQ-I1-01",
                "issue_id": "I1",
                "evidence_item_id": "E1",
                "query_channel": "provision_style",
                "query_text": "배경 전문은 replay 질의에 쓰이지 않는다",
                "top_k": 100,
                "query_terms": ["요건"],
                "statute_hints": [],
                "first_stage_query_text": None,
                "rerank_query_text": None,
            }],
        }
    }


class ReplayPreparationTests(unittest.TestCase):
    def test_receipt_bound_archived_result_prepares_without_live_retrieval(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result_path = root / "result.json"
            trace_path = root / "events.jsonl"
            manifest_path = root / "manifest.json"
            receipt_path = root / "receipt.json"
            result_path.write_text(
                json.dumps(archived_result(), ensure_ascii=False), encoding="utf-8"
            )
            trace_path.write_text("{}\n", encoding="utf-8")
            manifest_path.write_text('{"name":"C02"}\n', encoding="utf-8")
            hashes = {
                "source_result_sha256": file_sha256(result_path),
                "source_trace_sha256": file_sha256(trace_path),
                "source_manifest_sha256": file_sha256(manifest_path),
            }
            receipt = {
                **hashes,
                "source_git_commit": "a" * 40,
                "source_git_tree": "b" * 40,
            }
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            hashes["source_receipt_sha256"] = file_sha256(receipt_path)

            bindings = verify_source_receipt(
                result_path=result_path,
                trace_path=trace_path,
                manifest_path=manifest_path,
                receipt_path=receipt_path,
                result_allowlist=[hashes["source_result_sha256"]],
                trace_allowlist=[hashes["source_trace_sha256"]],
                manifest_allowlist=[hashes["source_manifest_sha256"]],
                receipt_allowlist=[hashes["source_receipt_sha256"]],
                expected_source_git_commit="a" * 40,
                expected_source_git_tree="b" * 40,
            )
            transforms = prepare_from_archived_result(
                archived_result(), max_characters=512, max_token_like_units=96
            )

            self.assertEqual(bindings["source_git_commit"], "a" * 40)
            self.assertEqual(len(transforms), 1)
            self.assertEqual(transforms[0]["source"], "canonical_missing_only")
            self.assertNotIn(
                "배경 전문은 replay 질의에 쓰이지 않는다",
                transforms[0]["final_request"]["rerank_query_text"],
            )
            self.assertEqual(
                transforms[0]["raw_request"]["query_text"],
                "배경 전문은 replay 질의에 쓰이지 않는다",
            )

    def test_receipt_allowlist_and_tree_mismatches_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {
                name: root / name
                for name in ("result.json", "events.jsonl", "manifest.json", "receipt.json")
            }
            for name, path in paths.items():
                path.write_text('{"name":"%s"}\n' % name, encoding="utf-8")
            hashes = {
                "source_result_sha256": file_sha256(paths["result.json"]),
                "source_trace_sha256": file_sha256(paths["events.jsonl"]),
                "source_manifest_sha256": file_sha256(paths["manifest.json"]),
            }
            paths["receipt.json"].write_text(
                json.dumps({
                    **hashes,
                    "source_git_commit": "a" * 40,
                    "source_git_tree": "b" * 40,
                }),
                encoding="utf-8",
            )
            receipt_hash = file_sha256(paths["receipt.json"])
            arguments = {
                "result_path": paths["result.json"],
                "trace_path": paths["events.jsonl"],
                "manifest_path": paths["manifest.json"],
                "receipt_path": paths["receipt.json"],
                "result_allowlist": [hashes["source_result_sha256"]],
                "trace_allowlist": [hashes["source_trace_sha256"]],
                "manifest_allowlist": [hashes["source_manifest_sha256"]],
                "receipt_allowlist": [receipt_hash],
                "expected_source_git_commit": "a" * 40,
                "expected_source_git_tree": "b" * 40,
            }
            with self.assertRaisesRegex(
                ReplayPreparationError, "tree"
            ):
                verify_source_receipt(
                    **{**arguments, "expected_source_git_tree": "c" * 40}
                )
            with self.assertRaisesRegex(
                ReplayPreparationError, "allowlisted"
            ):
                verify_source_receipt(
                    **{**arguments, "result_allowlist": ["0" * 64]}
                )


if __name__ == "__main__":
    unittest.main()
