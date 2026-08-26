import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from harness.contracts import (
    AnswerMode,
    CandidateAnswerStatus,
    CandidateAnswerBasis,
    CandidateStageRecord,
    OutcomeStatus,
    TerminationReason,
)
from harness.run_state import RunState
from harness.runner import HarnessOutcome
from runtime.experiment_record import (
    ExperimentRecord,
    _source_worktree_dirty_from_porcelain,
)


class ExperimentRecordTests(unittest.TestCase):
    def test_source_dirty_ignores_only_records_paths(self):
        self.assertFalse(_source_worktree_dirty_from_porcelain("?? records/runs/run-1/result.json\n"))
        self.assertTrue(_source_worktree_dirty_from_porcelain("?? scripts/run_local_harness.py\n"))

    def test_writes_distinct_metadata_trace_and_result_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project = root / "project"
            skills = project / "skills"
            skills.mkdir(parents=True)
            (skills / "planner.md").write_text("planner", encoding="utf-8")

            record = ExperimentRecord(
                record_root=root / "records",
                run_id="run-1",
                project_root=project,
                skills_root=skills,
                configuration={"condition": "M", "seed": 7},
                question="질문",
                question_id="qa_19_1hop_28",
                source_snapshot={
                    "git_commit": "a" * 40,
                    "git_tree": "b" * 40,
                    "source_manifest_sha256": "c" * 64,
                },
            )
            state = RunState(question="질문", normalized_question="질문", run_id="run-1")
            state.retrieval_stage_records = [
                CandidateStageRecord(
                    provision_id="P1",
                    retrieval_round=1,
                    candidate_stage="first_stage",
                    source_request_ids=["RQ1"],
                    target_evidence_item_ids=["E1"],
                    first_stage_rank=1,
                    first_stage_score=2.5,
                    selection_reason="request_top_k",
                )
            ]
            response_text = "첫 줄의 전체 응답🙂\n" + ("x" * 1024) + "\n마지막 줄"
            response_bytes = response_text.encode("utf-8")
            record.record_skill_attempt(
                {
                    "skill_id": "S1",
                    "generation_kind": "primary_skill_attempt",
                    "attempt": 1,
                    "done_reason": "length",
                    "eval_count": 4096,
                    "response_text": response_text,
                    "response_characters": len(response_text),
                    "response_utf8_bytes": len(response_bytes),
                    "response_sha256": hashlib.sha256(response_bytes).hexdigest(),
                    "response_tail": response_text[-512:],
                }
            )
            record.trace_sink.record("RUN_STARTED", state)
            result_path = record.finalize(
                HarnessOutcome(
                    status=OutcomeStatus.ABSTAIN,
                    state=state,
                    termination_reason=TerminationReason.MAX_RETRIEVAL_ROUNDS_REACHED,
                )
            )

            metadata = json.loads((record.directory / "metadata.json").read_text(encoding="utf-8"))
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(metadata["question_id"], "qa_19_1hop_28")
            self.assertIn("planner.md", metadata["skill_sha256"])
            self.assertIn("git_source_worktree_dirty", metadata)
            self.assertEqual(metadata["source_snapshot"]["git_commit"], "a" * 40)
            self.assertEqual(result["status"], "ABSTAIN")
            self.assertIsNone(result["answer_mode"])
            self.assertFalse(result["complete_answer"])
            self.assertTrue((record.directory / "events.jsonl").is_file())
            self.assertEqual(result["record_schema_version"], "1.4")
            diagnostics = result["skill_generation_diagnostics"]
            self.assertEqual(diagnostics["schema_version"], "1.2")
            self.assertEqual(diagnostics["attempt_file"], "skill_attempts.jsonl")
            self.assertEqual(diagnostics["attempt_count"], 1)
            self.assertEqual(
                diagnostics["response_retention"],
                {
                    "generation_kind": {
                        "field": "generation_kind",
                        "required": True,
                        "allowed_values": [
                            "primary_skill_attempt",
                            "neutral_semantic_gap_replan",
                        ],
                    },
                    "response_text": {
                        "retention": "full",
                        "encoding": "utf-8",
                        "sha256_field": "response_sha256",
                        "character_count_field": "response_characters",
                        "utf8_byte_count_field": "response_utf8_bytes",
                    },
                    "response_tail": {
                        "retention": "last_characters",
                        "character_limit": 512,
                    },
                },
            )
            attempts = (record.directory / "skill_attempts.jsonl").read_text(encoding="utf-8")
            attempt = json.loads(attempts)
            self.assertEqual(attempt["done_reason"], "length")
            self.assertEqual(
                attempt["generation_kind"], "primary_skill_attempt"
            )
            self.assertEqual(attempt["response_text"], response_text)
            self.assertEqual(attempt["response_characters"], len(response_text))
            self.assertEqual(attempt["response_utf8_bytes"], len(response_bytes))
            self.assertEqual(
                attempt["response_sha256"],
                hashlib.sha256(attempt["response_text"].encode("utf-8")).hexdigest(),
            )
            self.assertEqual(attempt["response_tail"], response_text[-512:])
            self.assertIsNone(result["candidate_answer"])
            self.assertIsNone(result["candidate_answer_status"])
            self.assertEqual(
                result["retrieval_provenance"]["stage_record_counts"],
                {"first_stage": 1},
            )
            self.assertNotIn("retrieval_stage_records", result["state"])
            self.assertTrue((record.directory / "retrieval_stages.jsonl").is_file())

    def test_writes_optional_answer_scope_without_changing_status(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project = root / "project"
            skills = project / "skills"
            skills.mkdir(parents=True)
            record = ExperimentRecord(
                record_root=root / "records",
                run_id="run-answer-scope",
                project_root=project,
                skills_root=skills,
                configuration={},
                question="질문",
                question_id=None,
            )
            state = RunState(question="질문", normalized_question="질문", run_id="run-answer-scope")
            result_path = record.finalize(
                HarnessOutcome(
                    status=OutcomeStatus.ANSWER,
                    state=state,
                    answer="제한 답변",
                    answer_mode=AnswerMode.LIMITED,
                    complete_answer=False,
                    answered_target_ids=["T1"],
                    deferred_target_ids=["T2"],
                    claims=[{"claim_id": "C1", "text": "제한 답변"}],
                    claim_citations=[{"citation_id": "CT1", "claim_id": "C1"}],
                    assumptions=[{"code": "A1", "message": "가정"}],
                    limitations=[{"code": "L1", "message": "한계"}],
                )
            )

            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "ANSWER")
            self.assertEqual(result["answer_mode"], "limited")
            self.assertEqual(result["answered_target_ids"], ["T1"])
            self.assertEqual(result["deferred_target_ids"], ["T2"])
            self.assertEqual(result["claims"][0]["claim_id"], "C1")
            self.assertEqual(result["claim_citations"][0]["citation_id"], "CT1")
            self.assertEqual(result["assumptions"][0]["code"], "A1")
            self.assertEqual(result["limitations"][0]["code"], "L1")

    def test_writes_abstain_candidate_without_changing_public_status(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project = root / "project"
            skills = project / "skills"
            skills.mkdir(parents=True)
            record = ExperimentRecord(
                record_root=root / "records",
                run_id="run-candidate",
                project_root=project,
                skills_root=skills,
                configuration={},
                question="질문",
                question_id="q1",
            )
            state = RunState(question="질문", normalized_question="질문", run_id="run-candidate")
            result_path = record.finalize(
                HarnessOutcome(
                    status=OutcomeStatus.ABSTAIN,
                    state=state,
                    candidate_claims=[{"claim_id": "C1", "text": "후보"}],
                    candidate_claim_citations=[{"citation_id": "CT1", "claim_id": "C1"}],
                    candidate_assumptions=[{"code": "A1", "message": "가정"}],
                    candidate_limitations=[{"code": "L1", "message": "한계"}],
                    candidate_answer="벤치마크 후보 답변",
                    candidate_answer_status=CandidateAnswerStatus.GENERATED,
                    candidate_answer_basis=CandidateAnswerBasis.RETRIEVED_CANDIDATES,
                )
            )

            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "ABSTAIN")
            self.assertEqual(result["candidate_answer"], "벤치마크 후보 답변")
            self.assertEqual(result["candidate_answer_status"], "GENERATED")
            self.assertEqual(result["candidate_answer_basis"], "retrieved_candidates")
            self.assertEqual(result["candidate_claims"][0]["claim_id"], "C1")
            self.assertEqual(result["candidate_claim_citations"][0]["citation_id"], "CT1")
            self.assertEqual(result["candidate_assumptions"][0]["code"], "A1")
            self.assertEqual(result["candidate_limitations"][0]["code"], "L1")


    def test_writes_canonical_rerank_query_transform_sidecar_and_contract(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            project = root / "project"
            skills = project / "skills"
            skills.mkdir(parents=True)
            record = ExperimentRecord(
                record_root=root / "records",
                run_id="run-canonical-rerank",
                project_root=project,
                skills_root=skills,
                configuration={
                    "canonical_rerank_query_missing_only": True,
                    "canonical_rerank_query_max_characters": 512,
                    "canonical_rerank_query_max_token_like_units": 96,
                },
                question="질문",
                question_id="qa150-shape",
            )
            state = RunState(
                question="질문",
                normalized_question="질문",
                run_id="run-canonical-rerank",
            )
            canonical_text = "원자 요건"
            raw_fallback_text = "배경 전체 원문"

            def metrics(value, prefix):
                encoded = value.encode("utf-8")
                return {
                    "%s_sha256" % prefix: hashlib.sha256(encoded).hexdigest(),
                    "%s_characters" % prefix: len(value),
                    "%s_utf8_bytes" % prefix: len(encoded),
                    "%s_token_like_units" % prefix: len(value.split()),
                }

            state.rerank_query_transforms = [{
                "schema_version": "1.1",
                "request_id": "RQ-I1-01",
                "source": "canonical_missing_only",
                "canonical_attempted": True,
                "fallback_applied": False,
                "fallback_reason_code": None,
                "original_rerank_query_present": False,
                "final_rerank_query_present": True,
                "effective_rerank_query_source": "rerank_query_text",
                "canonical_output_within_bounds": True,
                "max_characters": 512,
                "max_token_like_units": 96,
                **metrics("", "original_rerank_query"),
                **metrics(canonical_text, "final_rerank_query"),
                **metrics(canonical_text, "effective_rerank_query"),
            }, {
                "schema_version": "1.1",
                "request_id": "GRQ-I1-01",
                "source": "raw_query_text_fallback",
                "canonical_attempted": True,
                "fallback_applied": True,
                "fallback_reason_code": "canonical_output_character_bound",
                "original_rerank_query_present": False,
                "final_rerank_query_present": False,
                "effective_rerank_query_source": "query_text",
                "canonical_output_within_bounds": None,
                "max_characters": 512,
                "max_token_like_units": 96,
                **metrics("", "original_rerank_query"),
                **metrics("", "final_rerank_query"),
                **metrics(raw_fallback_text, "effective_rerank_query"),
            }]
            result_path = record.finalize(
                HarnessOutcome(status=OutcomeStatus.ABSTAIN, state=state)
            )

            result = json.loads(result_path.read_text(encoding="utf-8"))
            provenance = result["retrieval_provenance"]
            self.assertEqual(provenance["schema_version"], "1.1")
            contract = provenance["canonical_rerank_query"]
            self.assertEqual(contract["schema_version"], "1.1")
            self.assertEqual(
                contract["contract"]["allowed_sources"],
                [
                    "raw",
                    "canonical_missing_only",
                    "raw_query_text_fallback",
                ],
            )
            self.assertEqual(
                contract["contract"]["forbidden_fields"],
                ["raw_request", "final_request"],
            )
            self.assertEqual(contract["transform_file"], "canonical_rerank_query_transforms.jsonl")
            self.assertEqual(contract["transform_count"], 2)
            self.assertNotIn("rerank_query_transforms", result["state"])
            sidecar = record.directory / contract["transform_file"]
            sidecar_text = sidecar.read_text(encoding="utf-8")
            saved = [json.loads(line) for line in sidecar_text.splitlines()]
            self.assertEqual(
                [row["source"] for row in saved],
                ["canonical_missing_only", "raw_query_text_fallback"],
            )
            self.assertNotIn("raw_request", saved[0])
            self.assertNotIn("final_request", saved[0])
            self.assertNotIn(raw_fallback_text, sidecar_text)
            self.assertEqual(
                saved[0]["final_rerank_query_sha256"],
                hashlib.sha256(
                    canonical_text.encode("utf-8")
                ).hexdigest(),
            )
            self.assertEqual(
                saved[1]["effective_rerank_query_sha256"],
                hashlib.sha256(raw_fallback_text.encode("utf-8")).hexdigest(),
            )


if __name__ == "__main__":
    unittest.main()
