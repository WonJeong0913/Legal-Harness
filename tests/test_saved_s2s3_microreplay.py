import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "replay_saved_s2s3.py"
SPEC = importlib.util.spec_from_file_location("saved_s2s3_microreplay", SCRIPT_PATH)
REPLAY = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = REPLAY
SPEC.loader.exec_module(REPLAY)


P1 = "P1"
P2 = "P2"
P1_TEXT = "육아휴직수당은 월 150만원까지 비과세한다."
P2_TEXT = (
    "국외에서 근로를 제공하여 받는 보수는 월 100만원까지 비과세한다. "
    "다만 원양어업 선박 또는 국외 건설현장에서 근로를 제공하는 경우 월 500만원까지 비과세한다."
)
COMMIT = "a" * 40
TREE = "b" * 40
MODEL = "fixture-qwen38"


class ScriptedExecutor:
    def __init__(self, *, diagnostic_sink, outputs, **_kwargs):
        self.diagnostic_sink = diagnostic_sink
        self.outputs = outputs
        self.calls = []

    def execute(self, skill_name, entry_point, payload):
        self.calls.append((skill_name, entry_point, copy.deepcopy(payload)))
        output = copy.deepcopy(self.outputs[(skill_name, entry_point)])
        response = json.dumps(output, ensure_ascii=False, sort_keys=True)
        encoded = response.encode("utf-8")
        self.diagnostic_sink({
            "schema_version": "1.2",
            "run_id": payload["run_id"],
            "skill_name": skill_name,
            "skill_id": "S2" if skill_name == "provision_coverage_assessment" else "S3",
            "generation_kind": "primary_skill_attempt",
            "entry_point": entry_point,
            "attempt": 1,
            "requested_max_tokens": 3072,
            "outcome": "valid",
            "response_text": response,
            "response_sha256": hashlib.sha256(encoded).hexdigest(),
            "response_utf8_bytes": len(encoded),
            "response_characters": len(response),
            "response_tail": response[-512:],
        })
        return output


def _candidate(provision_id, text, issue_id="I1"):
    return {
        "provision_id": provision_id,
        "statute_name": "소득세법 시행령",
        "provision_text": text,
        "issue_id": issue_id,
        "source_request_id": "RQ1" if issue_id == "I1" else "RQ2",
        "source_request_ids": ["RQ1" if issue_id == "I1" else "RQ2"],
        "target_evidence_item_ids": ["E1" if issue_id == "I1" else "E2"],
        "retrieval_round": 1,
        "first_stage_score": 1.0,
        "fusion_rank": 1,
        "rerank_score": 1.0,
        "first_stage_rank": 1,
        "rerank_rank": 1,
        "selection_rank": 1,
        "candidate_stage": "selected",
        "selection_reason": "fixture",
        "alias_provision_ids": [],
    }


def _s2_covered(*, include_card, include_second):
    links = [{
        "issue_id": "I1", "evidence_item_id": "E1", "provision_id": P1,
        "support_spans": [{"start_char": 0, "end_char": 5}], "assessment": "accepted",
        "role": "CORE", "condition": "", "rationale": "한도",
    }]
    assessments = [{
        "evidence_item_id": "E1", "status": "covered", "linked_provision_ids": [P1],
        "rationale": "직접 한도", "partial_kind": "not_applicable", "missing_aspects": [],
        "legal_status": "covered", "applicability_status": "direct", "gap_type": "none",
        "governing_legal_regime": "direct_entailment",
        "criterion_results": [{
            "requirement_id": "E1-R1", "status": "satisfied", "linked_provision_ids": [P1],
            "rationale": "월 150만원",
        }],
    }]
    if include_second:
        links.append({
            "issue_id": "I2", "evidence_item_id": "E2", "provision_id": P2,
            "support_spans": [{"start_char": 0, "end_char": 5}], "assessment": "accepted",
            "role": "CORE", "condition": "", "rationale": "특례 한도",
        })
        criterion = {
            "requirement_id": "E2-R1", "status": "satisfied", "linked_provision_ids": [P2],
            "rationale": "일반 및 특례 한도",
        }
        if include_card:
            criterion["public_material_conditions"] = [{
                "kind": "alternative_outcome", "answer_target_id": "T2",
                "condition_text": "원양어업 선박 또는 국외 건설현장에서 근로를 제공하는 경우",
                "outcome_text": "월 500만원", "source_provision_id": P2,
            }]
        assessments.append({
            "evidence_item_id": "E2", "status": "covered", "linked_provision_ids": [P2],
            "rationale": "직접 한도", "partial_kind": "not_applicable", "missing_aspects": [],
            "legal_status": "covered", "applicability_status": "direct", "gap_type": "none",
            "governing_legal_regime": "direct_entailment", "criterion_results": [criterion],
        })
    return {"evidence_links": links, "coverage_assessments": assessments, "evidence_conflicts": []}


def _s2_partial():
    return {
        "evidence_links": [],
        "coverage_assessments": [{
            "evidence_item_id": "E1", "status": "uncovered", "linked_provision_ids": [],
            "rationale": "근거 없음", "partial_kind": "not_applicable", "missing_aspects": ["E1-R1"],
            "legal_status": "uncovered", "applicability_status": "not_assessed",
            "gap_type": "missing_statute", "governing_legal_regime": "not_direct_entailment",
            "criterion_results": [{
                "requirement_id": "E1-R1", "status": "unsatisfied", "linked_provision_ids": [],
                "rationale": "근거 없음",
            }],
        }],
        "evidence_conflicts": [],
    }


def _s3(*, material):
    claims = [{
        "claim_id": "C1", "text": "육아휴직수당은 월 150만원까지 비과세입니다.",
        "claim_type": "legal_rule", "applicability": "direct", "answer_target_ids": ["T1"],
        "citation_required": True, "public_role": "conclusion",
    }]
    citations = [{
        "claim_id": "C1", "provision_id": P1, "support_description": "월 150만원",
    }]
    answer = claims[0]["text"]
    if material:
        claims.append({
            "claim_id": "C2",
            "text": "국외 근로 보수는 월 100만원까지이고, 원양어업 선박 또는 국외 건설현장에서 근로를 제공하는 경우 월 500만원까지 비과세입니다.",
            "claim_type": "legal_rule", "applicability": "direct", "answer_target_ids": ["T2"],
            "citation_required": True, "public_role": "conclusion",
            "public_material_condition_ids": ["E2-R1-M1"],
        })
        citations.append({"claim_id": "C2", "provision_id": P2, "support_description": "특례 한도"})
        answer += "\n" + claims[-1]["text"]
    return {
        "schema_version": "1.0", "skill_id": "S3", "mode": "GENERATE_ANSWER", "status": "ok",
        "answer": answer, "claims": claims, "claim_citations": citations,
        "assumptions": [], "limitations": [],
    }


def _saved_payload(question_id):
    has_second = question_id == "qa_180_2hop_689_rand"
    candidates = [_candidate(P1, P1_TEXT)]
    issues = [{"issue_id": "I1", "description": "육아휴직수당"}]
    targets = [{"answer_target_id": "T1", "question_anchor": "육아휴직수당 한도", "requested_output": "한도", "answer_type": "amount_or_limit"}]
    evidence = [{
        "evidence_item_id": "E1", "issue_id": "I1", "evidence_type": "rule", "description": "육아휴직수당 한도",
        "critical": True, "completion_criteria": "월 한도", "necessity_reason": "질문 대상",
        "answer_target_ids": ["T1"], "scope_source": "question",
        "completion_requirements": [{"requirement_id": "E1-R1", "text": "월 한도"}],
    }]
    history = [{
        "request_id": "RQ1", "issue_id": "I1", "evidence_item_id": "E1", "query_channel": "statute_aware",
        "query_text": "육아휴직수당 한도", "top_k": 10, "query_terms": ["육아휴직수당"],
        "statute_hints": ["소득세법"], "first_stage_query_text": "육아휴직수당", "rerank_query_text": "육아휴직수당 한도",
    }]
    if has_second:
        candidates.append(_candidate(P2, P2_TEXT, "I2"))
        issues.append({"issue_id": "I2", "description": "국외 근로소득"})
        targets.append({"answer_target_id": "T2", "question_anchor": "국외 근로소득 한도", "requested_output": "한도", "answer_type": "amount_or_limit"})
        evidence.append({
            "evidence_item_id": "E2", "issue_id": "I2", "evidence_type": "rule", "description": "국외 근로소득 한도",
            "critical": True, "completion_criteria": "특례 한도", "necessity_reason": "질문 대상",
            "answer_target_ids": ["T2"], "scope_source": "question",
            "completion_requirements": [{"requirement_id": "E2-R1", "text": "특례 한도"}],
        })
        history.append({
            "request_id": "RQ2", "issue_id": "I2", "evidence_item_id": "E2", "query_channel": "statute_aware",
            "query_text": "국외 근로소득 한도", "top_k": 10, "query_terms": ["국외근로소득"],
            "statute_hints": ["소득세법"], "first_stage_query_text": "국외근로소득", "rerank_query_text": "국외 근로소득 한도",
        })
    state = {
        "normalized_question": "질문의 한도는 무엇인가?", "total_round_budget": 3,
        "remaining_round_budget": 1, "remaining_request_budget": 2, "retrieval_rounds_used": 2 if has_second else 1,
        "no_progress_rounds": 0, "last_retrieval_new_provision_count": 1,
        "legal_issues": issues, "answer_targets": targets, "required_evidence_items": evidence,
        "candidate_provisions": candidates, "query_history": history,
        "corpus_text_snapshots": {candidate["provision_id"]: candidate["provision_text"] for candidate in candidates},
        "accepted_provision_ids": [candidate["provision_id"] for candidate in candidates],
    }
    return {
        "run_id": "baseline-run", "status": "ANSWER", "termination_reason": "COMPLETED",
        "answer": "baseline answer", "answer_mode": "full", "answered_target_ids": [target["answer_target_id"] for target in targets],
        "deferred_target_ids": [], "claims": [], "claim_citations": [], "assumptions": [], "limitations": [], "errors": [],
        "state": state,
    }


class SavedS2S3MicroReplayTests(unittest.TestCase):
    def _write_source(self, directory, question_id):
        result = _saved_payload(question_id)
        metadata = {
            "question_id": question_id, "question": "[질문] 질문의 한도는 무엇인가?",
            "configuration": {"model": MODEL, "retriever": "kure", "num_ctx": 32768, "seed": 0},
            "source_snapshot": {"git_commit": COMMIT, "git_tree": TREE},
        }
        result_path = directory / "source-result.json"
        metadata_path = directory / "source-metadata.json"
        manifest_path = directory / "source-manifest.json"
        task_receipt_path = directory / "source-task-receipt.json"
        profile = REPLAY._profile_spec(question_id)
        entry = {"question_id": question_id, **{field: profile[field] for field in ("sequence", "ordinal", "n_hops")}}
        manifest = {"entries": [entry]}
        task_receipt = {
            "schema_version": "c02_targeted_resume_task_receipt_v1",
            "task": entry,
            "summary_row": {**entry, "record_result_file": str(result_path.resolve()), "run_id": result["run_id"],
                            "accepted_provision_ids": result["state"]["accepted_provision_ids"]},
        }
        result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        task_receipt_path.write_text(json.dumps(task_receipt, ensure_ascii=False), encoding="utf-8")
        expectations = REPLAY.ReplayExpectations(
            question_id, hashlib.sha256(result_path.read_bytes()).hexdigest(),
            hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
            hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            hashlib.sha256(task_receipt_path.read_bytes()).hexdigest(), COMMIT, TREE, MODEL, "kure",
        )
        return result_path, metadata_path, manifest_path, task_receipt_path, expectations

    def _run(self, directory, question_id, outputs):
        result_path, metadata_path, manifest_path, task_receipt_path, expectations = self._write_source(directory, question_id)
        executors = []

        def factory(**kwargs):
            executor = ScriptedExecutor(outputs=outputs, **kwargs)
            executors.append(executor)
            return executor

        replay = REPLAY.replay_saved_s2s3(
            source_result=result_path, source_metadata=metadata_path, source_manifest=manifest_path,
            source_task_receipt=task_receipt_path, output_root=directory / "out",
            expectations=expectations, model=MODEL, endpoint="http://never-used",
            executor_factory=factory, project_root=ROOT,
        )
        return replay, executors, result_path, metadata_path, manifest_path, task_receipt_path, expectations

    def test_positive_material_card_replay_retains_raw_and_comparison(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            replay, executors, *_ = self._run(directory, "qa_180_2hop_689_rand", {
                ("provision_coverage_assessment", "ASSESS_COVERAGE"): _s2_covered(include_card=True, include_second=True),
                ("grounded_legal_answer_generation", "GENERATE_ANSWER"): _s3(material=True),
            })
            self.assertEqual(replay.payload["replay_status"], "S2_S3_COMPLETED")
            audit = replay.payload["material_card_audit"]
            self.assertEqual(audit["claim_material_condition_ids"], ["E2-R1-M1"])
            self.assertEqual(audit["material_cards"][0]["material_id"], "E2-R1-M1")
            attempts = [json.loads(line) for line in (replay.output_directory / "skill_attempts.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([attempt["skill_id"] for attempt in attempts], ["S2", "S3"])
            for attempt in attempts:
                self.assertEqual(attempt["generation_kind"], "primary_skill_attempt")
                self.assertEqual(attempt["response_sha256"], hashlib.sha256(attempt["response_text"].encode("utf-8")).hexdigest())
            self.assertTrue((replay.output_directory / "comparison.json").is_file())
            self.assertEqual(len(executors[0].calls), 2)

    def test_no_card_concise_path_and_receipt_identical_resume(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            outputs = {
                ("provision_coverage_assessment", "ASSESS_COVERAGE"): _s2_covered(include_card=False, include_second=False),
                ("grounded_legal_answer_generation", "GENERATE_ANSWER"): _s3(material=False),
            }
            replay, executors, result_path, metadata_path, manifest_path, task_receipt_path, expectations = self._run(directory, "qa_26_1hop_39", outputs)
            self.assertEqual(replay.payload["material_card_audit"]["material_card_count"], 0)
            self.assertEqual(len(replay.payload["candidate"]["claims"]), 1)
            resumed = REPLAY.replay_saved_s2s3(
                source_result=result_path, source_metadata=metadata_path, source_manifest=manifest_path,
                source_task_receipt=task_receipt_path, output_root=directory / "out",
                expectations=expectations, model=MODEL, endpoint="http://never-used", resume=True,
                executor_factory=lambda **_kwargs: self.fail("resume must not construct an executor"), project_root=ROOT,
            )
            self.assertTrue(resumed.resumed)
            self.assertEqual(len(executors[0].calls), 2)

    def test_partial_no_rescue_never_invokes_s3_or_retrieval(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            replay, executors, *_ = self._run(directory, "qa_653_2hop_987", {
                ("provision_coverage_assessment", "ASSESS_COVERAGE"): _s2_partial(),
            })
            self.assertEqual(replay.payload["replay_status"], "OFFLINE_POLICY_BLOCKED_NO_RETRIEVAL")
            self.assertEqual(replay.payload["material_card_audit"]["material_card_count"], 0)
            self.assertEqual([call[0] for call in executors[0].calls], ["provision_coverage_assessment"])
            self.assertFalse((replay.output_directory / "skill_attempts.jsonl").read_text(encoding="utf-8").find('"skill_id": "S3"') >= 0)

    def test_hash_and_allowlist_fail_before_output_directory_creation(self):
        with tempfile.TemporaryDirectory() as raw_directory:
            directory = Path(raw_directory)
            result_path, metadata_path, manifest_path, task_receipt_path, expected = self._write_source(directory, "qa_26_1hop_39")
            bad = REPLAY.ReplayExpectations(
                expected.question_id, "0" * 64, expected.source_metadata_sha256,
                expected.source_manifest_sha256, expected.source_task_receipt_sha256,
                expected.source_commit, expected.source_tree, expected.source_model, expected.source_retriever,
            )
            with self.assertRaisesRegex(REPLAY.ReplayError, "SHA256 mismatch"):
                REPLAY.replay_saved_s2s3(
                    source_result=result_path, source_metadata=metadata_path, source_manifest=manifest_path,
                    source_task_receipt=task_receipt_path, output_root=directory / "out",
                    expectations=bad, model=MODEL, endpoint="http://never-used", project_root=ROOT,
                )
            self.assertFalse((directory / "out").exists())
            receipt = json.loads(task_receipt_path.read_text(encoding="utf-8"))
            receipt["summary_row"]["record_result_file"] = str(directory / "other-result.json")
            task_receipt_path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")
            receipt_mismatch = REPLAY.ReplayExpectations(
                expected.question_id, expected.source_result_sha256, expected.source_metadata_sha256,
                expected.source_manifest_sha256, hashlib.sha256(task_receipt_path.read_bytes()).hexdigest(),
                expected.source_commit, expected.source_tree, expected.source_model, expected.source_retriever,
            )
            with self.assertRaisesRegex(REPLAY.ReplayError, "does not bind the supplied result path"):
                REPLAY.replay_saved_s2s3(
                    source_result=result_path, source_metadata=metadata_path, source_manifest=manifest_path,
                    source_task_receipt=task_receipt_path, output_root=directory / "receipt-out",
                    expectations=receipt_mismatch, model=MODEL, endpoint="http://never-used", project_root=ROOT,
                )
            self.assertFalse((directory / "receipt-out").exists())
            with self.assertRaisesRegex(REPLAY.ReplayError, "allowlist"):
                REPLAY._profile("qa_other")


if __name__ == "__main__":
    unittest.main()
