import copy
import importlib.util
import json
from pathlib import Path
import unittest

from harness.contracts import (
    GapPlanRecovery,
    GapPlanRecoveryDisposition,
    LegalIssue,
    RequiredEvidenceItem,
)
from harness.interfaces import SkillExecutionError
from harness.run_state import RunState
from harness.validation import validate_gap_plan
from runtime.local_ollama_executor import LocalOllamaSkillExecutor


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "s1_gap_repair_validator",
    PROJECT_ROOT / "skills/legal_issue_and_query_planning/scripts/validate_output.py",
)
S1_VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S1_VALIDATOR)


def gap_input():
    return {
        "run_id": "trace-fixture",
        "normalized_question": "관련 법정 근거의 적용 여부를 판단하라.",
        "next_retrieval_round": 2,
        "legal_issues": [{"issue_id": "I1"}],
        "answer_targets": [{"answer_target_id": "T1"}],
        "required_evidence_items": [{
            "evidence_item_id": "E1",
            "issue_id": "I1",
            "evidence_type": "rule",
            "description": "관련 법정 근거와 적용 요건",
            "critical": True,
        }],
        "coverage_assessments": [{"evidence_item_id": "E1", "status": "uncovered"}],
        "missing_evidence_items": [{"evidence_item_id": "E1"}],
        "evidence_conflicts": [],
        "query_history": [],
        "seen_provision_ids": [],
        "candidate_cross_references": [],
        "remaining_request_budget": 2,
    }


def gap_request(evidence_item_id, query_text, *, issue_id="I1", request_id="model-owned"):
    return {
        "request_id": request_id,
        "issue_id": issue_id,
        "evidence_item_id": evidence_item_id,
        "query_channel": "statute_aware",
        "query_text": query_text,
        "query_terms": [query_text],
        "statute_hints": [query_text.split()[0]],
        "rationale": "미확인 법정 근거를 검색한다.",
        "gap_reason": "법정 요건이 미확인이다.",
        "source_assessment_status": "uncovered",
    }


def gap_output(requests):
    return {
        "schema_version": "1.0",
        "skill_id": "S1",
        "mode": "GAP_QUERY_PLAN",
        "status": "ok",
        "run_id": "model-owned",
        "target_evidence_item_ids": [
            request["evidence_item_id"] for request in requests
        ],
        "gap_retrieval_requests": requests,
    }


class GapSpecificityRepairTests(unittest.TestCase):
    def _transcript_recovery(self, payload, raw):
        """Exercise the repair path directly; no generator or model call occurs."""
        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills", "fixture-model", generator=lambda _prompt: "{}"
        )
        skill_input = executor._build_skill_input(
            "legal_issue_and_query_planning", "GAP_QUERY_PLAN", payload
        )
        unrepaired = executor._normalize_harness_owned_fields(
            "legal_issue_and_query_planning",
            "GAP_QUERY_PLAN",
            skill_input,
            copy.deepcopy(raw),
        )
        repaired, repairs = executor._repair_s1_transport(
            "legal_issue_and_query_planning",
            "GAP_QUERY_PLAN",
            unrepaired,
            skill_input,
        )
        errors = executor._validators["legal_issue_and_query_planning"](
            repaired, skill_input
        )
        return executor._repair_induced_history_collision_recovery(
            "legal_issue_and_query_planning",
            "GAP_QUERY_PLAN",
            unrepaired,
            repaired,
            skill_input,
            repairs,
            errors,
        )

    def test_persisted_failure_shapes_neutralize_unguarded_article_specificity(self):
        # These are retrieval traces only: statute/semantic text, no gold answer.
        for source in (
            "민법 제840조 재판상 이혼 청구권 소멸 기간",
            "지방세특례제한법 제70조 천연가스 버스 감면",
            "산업재해보상보험법 제37조 의료기관 치료 중 상해",
            "국민체육진흥법 제48조 제26조제1항 위반 벌칙",
        ):
            with self.subTest(source=source):
                request = {
                    "request_id": "GRQ-R2-1",
                    "query_text": source,
                    "query_terms": [source],
                    "statute_hints": [source],
                    "first_stage_query_text": source,
                    "rerank_query_text": source,
                }
                repaired, audit = S1_VALIDATOR.neutralize_ungrounded_article_specificity(
                    [request], gap_input()
                )
                self.assertTrue(audit)
                self.assertIn(source.split()[0], repaired[0]["query_text"])
                self.assertNotRegex(
                    " ".join(
                        [repaired[0]["query_text"]]
                        + repaired[0]["query_terms"]
                        + repaired[0]["statute_hints"]
                        + [repaired[0].get("first_stage_query_text", ""), repaired[0].get("rerank_query_text", "")]
                    ),
                    r"제?[0-9]+조",
                )
                errors = []
                S1_VALIDATOR.validate_article_grounding(repaired, gap_input(), errors)
                self.assertEqual(errors, [])

    def test_c02_statute_hint_collapse_is_deduplicated_after_neutralization(self):
        request = {
            "request_id": "GRQ-R2-1",
            "issue_id": "I1",
            "evidence_item_id": "E1",
            "query_channel": "statute_aware",
            "query_text": "소득세법 제65조 중간예납추계액 미신고 처리",
            "top_k": 100,
            "query_terms": ["중간예납추계액", "소득세법", "소득세법 제65조"],
            "statute_hints": ["소득세법", "소득세법 제65조"],
            "rationale": "미확인 법정 근거를 검색한다.",
            "gap_reason": "중간예납추계액신고서 미제출의 처리 근거가 미확인이다.",
            "source_assessment_status": "uncovered",
        }
        repaired, repairs = S1_VALIDATOR.neutralize_ungrounded_article_specificity(
            [request], gap_input()
        )
        repaired_request = repaired[0]
        self.assertEqual(repaired_request["statute_hints"], ["소득세법"])
        self.assertEqual(repaired_request["query_terms"], ["중간예납추계액", "소득세법"])
        self.assertNotRegex(json.dumps(repaired_request, ensure_ascii=False), r"제?65조")
        self.assertTrue(any(
            repair["kind"] == "deduplicated_repair_induced_list_values"
            and repair["field"] == "statute_hints"
            and repair["before"] == ["소득세법", "소득세법"]
            and repair["after"] == ["소득세법"]
            for repair in repairs
        ))
        self.assertTrue(any(
            repair["kind"] == "deduplicated_repair_induced_list_values"
            and repair["field"] == "query_terms"
            and repair["before"] == ["중간예납추계액", "소득세법", "소득세법"]
            and repair["after"] == ["중간예납추계액", "소득세법"]
            for repair in repairs
        ))
        state = RunState(
            question="중간예납추계액 미신고 처리",
            normalized_question="중간예납추계액 미신고 처리",
            run_id="c02-statute-hint-collapse",
        )
        state.legal_issues = [LegalIssue("I1", "중간예납추계액 처리")]
        state.required_evidence_items = [RequiredEvidenceItem(
            "E1", "I1", "rule", "관련 법정 근거와 적용 요건", True,
        )]
        validated = validate_gap_plan({"gap_retrieval_requests": repaired}, state)
        self.assertEqual(validated[0].statute_hints, ["소득세법"])
        self.assertEqual(validated[0].query_terms, ["중간예납추계액", "소득세법"])

    def test_anchored_cross_reference_is_not_neutralized(self):
        source = "형법 제333조 적용"
        payload = gap_input()
        payload.update({
            "seen_provision_ids": ["P1"],
            "candidate_cross_references": [{
                "source_candidate_id": "P1",
                "target_statute_name": "형법",
                "target_article": "제333조",
                "excerpt": "전조",
                "start_char": 0,
                "end_char": 2,
            }],
        })
        request = {"request_id": "GRQ-R2-1", "query_text": source, "query_terms": ["제333조"], "statute_hints": ["형법 제333조"]}
        repaired, audit = S1_VALIDATOR.neutralize_ungrounded_article_specificity([request], payload)
        self.assertEqual(repaired, [request])
        self.assertEqual(audit, [])

    def test_executor_records_raw_repair_and_adapts_semantic_gap_plan(self):
        raw = {
            "schema_version": "1.0", "skill_id": "S1", "mode": "GAP_QUERY_PLAN",
            "status": "ok", "run_id": "model-owned", "target_evidence_item_ids": ["E1"],
            "gap_retrieval_requests": [{
                "request_id": "model-owned",
                "issue_id": "I1",
                "evidence_item_id": "E1",
                "query_channel": "statute_aware",
                "query_text": "민법 제840조 재판상 이혼 청구권 소멸 기간",
                "query_terms": ["제840조", "이혼 청구권", "소멸 기간"],
                "statute_hints": ["민법 제840조"],
                "first_stage_query_text": "민법 제840조 이혼 청구권",
                "rerank_query_text": "민법 제840조 소멸 기간",
                "rationale": "미확인 법정 근거를 검색한다.",
                "gap_reason": "시간 요건이 미확인이다.",
                "source_assessment_status": "uncovered",
            }],
        }
        diagnostics = []
        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills",
            "fixture-model",
            generator=lambda _prompt: json.dumps(raw, ensure_ascii=False),
            diagnostic_sink=diagnostics.append,
        )
        output = executor.execute("legal_issue_and_query_planning", "GAP_QUERY_PLAN", gap_input())
        request = output["gap_retrieval_requests"][0]
        self.assertEqual(request["request_id"], "GRQ-R2-1")
        self.assertIn("민법", request["query_text"])
        self.assertNotRegex(json.dumps(request, ensure_ascii=False), r"제840조")
        self.assertTrue(diagnostics[-1]["deterministic_repairs"])
        errors = []
        S1_VALIDATOR.validate_article_grounding(
            [{
                "query_text": request["query_text"],
                "query_terms": request["query_terms"],
                "statute_hints": request["statute_hints"],
                "first_stage_query_text": request.get("first_stage_query_text", ""),
                "rerank_query_text": request.get("rerank_query_text", ""),
            }],
            gap_input(),
            errors,
        )
        self.assertEqual(errors, [])

    def test_raw_retry_replays_original_unrepaired_s1_json_when_other_validation_fails(self):
        raw = {
            "schema_version": "1.0", "skill_id": "S1", "mode": "GAP_QUERY_PLAN",
            "status": "ok", "run_id": "model-owned", "target_evidence_item_ids": ["E1"],
            "gap_retrieval_requests": [{
                "request_id": "model-owned", "issue_id": "I1", "evidence_item_id": "E1",
                "query_channel": "statute_aware",
                "query_text": "민법 제840조 재판상 이혼 청구권 소멸 기간",
                "query_terms": ["제840조"], "statute_hints": ["민법 제840조"],
                "rationale": "미확인 법정 근거를 검색한다.",
                "gap_reason": "시간 요건이 미확인이다.",
                "source_assessment_status": "uncovered",
            }],
        }
        invalid = copy.deepcopy(raw)
        invalid["gap_retrieval_requests"][0]["source_assessment_status"] = "not-a-status"
        prompts = []
        responses = iter([invalid, raw])
        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills", "fixture-model",
            generator=lambda prompt: (prompts.append(prompt) or json.dumps(next(responses), ensure_ascii=False)),
        )
        output = executor.execute("legal_issue_and_query_planning", "GAP_QUERY_PLAN", gap_input())
        self.assertEqual(output["gap_retrieval_requests"][0]["issue_id"], "I1")
        self.assertEqual(len(prompts), 3)
        self.assertIn("민법 제840조", prompts[1])
        self.assertIn("Previous JSON", prompts[1])
        self.assertIn("NEUTRAL_SEMANTIC_GAP_REPLAN", prompts[2])

    def test_material_scoring_repair_attempts_one_clean_neutral_replan_and_adopts_it(self):
        repaired_source = {
            "schema_version": "1.0", "skill_id": "S1", "mode": "GAP_QUERY_PLAN",
            "status": "ok", "run_id": "model-owned", "target_evidence_item_ids": ["E1"],
            "gap_retrieval_requests": [{
                "request_id": "model-owned", "issue_id": "I1", "evidence_item_id": "E1",
                "query_channel": "statute_aware",
                "query_text": "예시법 제999조 구성 요건",
                "query_terms": ["제999조", "구성 요건"],
                "statute_hints": ["예시법 제999조"],
                "first_stage_query_text": "예시법 제999조 넓은 검색",
                "rerank_query_text": "예시법 제999조 구성 요건",
                "rationale": "미확인 법정 근거를 검색한다.",
                "gap_reason": "법정 요건이 미확인이다.",
                "source_assessment_status": "uncovered",
            }],
        }
        neutral_replan = copy.deepcopy(repaired_source)
        request = neutral_replan["gap_retrieval_requests"][0]
        request.update({
            "query_text": "예시법 구성 요건",
            "query_terms": ["구성 요건", "법정 근거"],
            "statute_hints": ["예시법"],
            "first_stage_query_text": "예시법 적용 요건",
            "rerank_query_text": "예시법 구성 요건 법정 근거",
        })
        prompts, diagnostics = [], []
        responses = iter([repaired_source, neutral_replan])
        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills", "fixture-model",
            generator=lambda prompt: (prompts.append(prompt) or json.dumps(next(responses), ensure_ascii=False)),
            diagnostic_sink=diagnostics.append,
        )
        output = executor.execute(
            "legal_issue_and_query_planning", "GAP_QUERY_PLAN", gap_input()
        )
        request = output["gap_retrieval_requests"][0]
        self.assertEqual(len(prompts), 2)
        self.assertIn("NEUTRAL_SEMANTIC_GAP_REPLAN", prompts[1])
        self.assertIn("first_stage_query_text when provided, otherwise query_text", prompts[1])
        self.assertIn("rerank_query_text when provided, otherwise query_text", prompts[1])
        self.assertEqual(request["first_stage_query_text"], "예시법 적용 요건")
        self.assertEqual(request["rerank_query_text"], "예시법 구성 요건 법정 근거")
        self.assertEqual(
            [event["kind"] for event in diagnostics[-1]["semantic_replan_events"]],
            [
                "neutral_semantic_gap_replan_attempted",
                "neutral_semantic_gap_replan_adopted",
            ],
        )

    def test_failed_neutral_replan_keeps_the_valid_repaired_fallback(self):
        raw = {
            "schema_version": "1.0", "skill_id": "S1", "mode": "GAP_QUERY_PLAN",
            "status": "ok", "run_id": "model-owned", "target_evidence_item_ids": ["E1"],
            "gap_retrieval_requests": [{
                "request_id": "model-owned", "issue_id": "I1", "evidence_item_id": "E1",
                "query_channel": "statute_aware", "query_text": "예시법 제999조 구성 요건",
                "query_terms": ["제999조"], "statute_hints": ["예시법 제999조"],
                "rationale": "미확인 법정 근거를 검색한다.",
                "gap_reason": "법정 요건이 미확인이다.",
                "source_assessment_status": "uncovered",
            }],
        }
        prompts, diagnostics = [], []
        responses = iter([json.dumps(raw, ensure_ascii=False), "not json"])
        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills", "fixture-model",
            generator=lambda prompt: (prompts.append(prompt) or next(responses)),
            diagnostic_sink=diagnostics.append,
        )
        output = executor.execute(
            "legal_issue_and_query_planning", "GAP_QUERY_PLAN", gap_input()
        )
        self.assertEqual(len(prompts), 2)
        self.assertNotRegex(json.dumps(output, ensure_ascii=False), r"제999조")
        self.assertEqual(
            diagnostics[-1]["semantic_replan_events"][-1]["kind"],
            "neutral_semantic_gap_replan_fallback",
        )
        self.assertNotIn("INVALID_SKILL_OUTPUT", json.dumps(diagnostics, ensure_ascii=False))

    def test_list_or_hint_only_repair_does_not_replan_without_scoring_delta(self):
        raw = {
            "schema_version": "1.0", "skill_id": "S1", "mode": "GAP_QUERY_PLAN",
            "status": "ok", "run_id": "model-owned", "target_evidence_item_ids": ["E1"],
            "gap_retrieval_requests": [{
                "request_id": "model-owned", "issue_id": "I1", "evidence_item_id": "E1",
                "query_channel": "statute_aware", "query_text": "예시법 구성 요건",
                "query_terms": ["제999조", "구성 요건"], "statute_hints": ["예시법 제999조"],
                "rationale": "미확인 법정 근거를 검색한다.",
                "gap_reason": "법정 요건이 미확인이다.",
                "source_assessment_status": "uncovered",
            }],
        }
        prompts = []
        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills", "fixture-model",
            generator=lambda prompt: (prompts.append(prompt) or json.dumps(raw, ensure_ascii=False)),
        )
        output = executor.execute(
            "legal_issue_and_query_planning", "GAP_QUERY_PLAN", gap_input()
        )
        self.assertEqual(len(prompts), 1)
        self.assertEqual(output["gap_retrieval_requests"][0]["query_text"].splitlines()[0], "예시법 구성 요건")

    def test_clean_replan_without_effective_scoring_delta_keeps_repaired_fallback(self):
        raw = {
            "schema_version": "1.0", "skill_id": "S1", "mode": "GAP_QUERY_PLAN",
            "status": "ok", "run_id": "model-owned", "target_evidence_item_ids": ["E1"],
            "gap_retrieval_requests": [{
                "request_id": "model-owned", "issue_id": "I1", "evidence_item_id": "E1",
                "query_channel": "statute_aware", "query_text": "예시법 제999조 구성 요건",
                "query_terms": ["제999조"], "statute_hints": ["예시법 제999조"],
                "rationale": "미확인 법정 근거를 검색한다.",
                "gap_reason": "법정 요건이 미확인이다.",
                "source_assessment_status": "uncovered",
            }],
        }
        unchanged_replan = copy.deepcopy(raw)
        request = unchanged_replan["gap_retrieval_requests"][0]
        request.update({
            "query_text": "예시법 구성 요건",
            "query_terms": ["구성 요건"],
            "statute_hints": ["예시법"],
        })
        diagnostics = []
        responses = iter([raw, unchanged_replan])
        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills", "fixture-model",
            generator=lambda _prompt: json.dumps(next(responses), ensure_ascii=False),
            diagnostic_sink=diagnostics.append,
        )
        output = executor.execute(
            "legal_issue_and_query_planning", "GAP_QUERY_PLAN", gap_input()
        )
        self.assertNotRegex(json.dumps(output, ensure_ascii=False), r"제999조")
        event = diagnostics[-1]["semantic_replan_events"][-1]
        self.assertEqual(event["kind"], "neutral_semantic_gap_replan_fallback")
        self.assertEqual(event["reason"], "replan_no_scoring_delta")

    def test_all_repair_collisions_use_one_neutral_replan_then_return_typed_recovery(self):
        payload = gap_input()
        prior = "민법 재판상 이혼 청구권 소멸 기간 [원문 맥락] 관련 법정 근거의 적용 여부를 판단하라."
        payload["query_history"] = [{"request_id": "GRQ-R1-1", "query_text": prior}]
        raw = gap_output([
            gap_request("E1", "민법 제840조 재판상 이혼 청구권 소멸 기간"),
        ])
        prompts, diagnostics = [], []
        responses = iter([json.dumps(raw, ensure_ascii=False), "not json"])
        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills",
            "fixture-model",
            generator=lambda prompt: (prompts.append(prompt) or next(responses)),
            diagnostic_sink=diagnostics.append,
        )

        output = executor.execute(
            "legal_issue_and_query_planning", "GAP_QUERY_PLAN", payload
        )

        self.assertEqual(len(prompts), 2)
        self.assertIn("NEUTRAL_SEMANTIC_GAP_REPLAN", prompts[1])
        self.assertEqual(output["gap_retrieval_requests"], [])
        recovery = output["harness_gap_plan_recovery"]
        self.assertIsInstance(recovery, GapPlanRecovery)
        self.assertEqual(
            recovery.disposition,
            GapPlanRecoveryDisposition.REPAIR_INDUCED_HISTORY_COLLISION,
        )
        self.assertEqual(recovery.dropped_request_ids, ["GRQ-R2-1"])
        self.assertEqual(recovery.dropped_request_count, 1)
        self.assertEqual(recovery.remaining_request_count, 0)
        self.assertEqual(len(recovery.repaired_query_sha256[0]), 64)
        self.assertEqual(
            diagnostics[-1]["semantic_replan_events"][-1]["kind"],
            "neutral_semantic_gap_replan_fallback",
        )

    def test_mixed_repair_collision_keeps_only_novel_request_and_recomputes_targets(self):
        payload = gap_input()
        payload.update({
            "next_retrieval_round": 3,
            "legal_issues": [{"issue_id": "I1"}, {"issue_id": "I2"}],
            "required_evidence_items": [
                payload["required_evidence_items"][0],
                {
                    "evidence_item_id": "E2",
                    "issue_id": "I2",
                    "evidence_type": "remedy",
                    "description": "구제결정의 법적 효과",
                    "critical": True,
                },
            ],
            "coverage_assessments": [
                {"evidence_item_id": "E1", "status": "uncovered"},
                {"evidence_item_id": "E2", "status": "uncovered"},
            ],
            "missing_evidence_items": [
                {"evidence_item_id": "E1"},
                {"evidence_item_id": "E2"},
            ],
            "remaining_request_budget": 3,
            "query_history": [{
                "request_id": "GRQ-R2-1",
                "query_text": "근로기준법 부당해고 구제신청 기한 60일 관할 중앙노동위원회 [원문 맥락] 관련 법정 근거의 적용 여부를 판단하라.",
            }],
        })
        raw = gap_output([
            gap_request(
                "E1",
                "근로기준법 제28조 제1항 부당해고 구제신청 기한 60일 관할 중앙노동위원회",
                request_id="model-owned-1",
            ),
            gap_request(
                "E2",
                "근로기준법 제33조 부당해고 구제결정 확정 효력 이행 강제",
                issue_id="I2",
                request_id="model-owned-2",
            ),
        ])
        responses = iter([json.dumps(raw, ensure_ascii=False), "not json"])
        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills",
            "fixture-model",
            generator=lambda _prompt: next(responses),
        )

        output = executor.execute(
            "legal_issue_and_query_planning", "GAP_QUERY_PLAN", payload
        )

        self.assertEqual(
            [request["request_id"] for request in output["gap_retrieval_requests"]],
            ["GRQ-R3-2"],
        )
        self.assertEqual(
            [request["evidence_item_id"] for request in output["gap_retrieval_requests"]],
            ["E2"],
        )
        recovery = output["harness_gap_plan_recovery"]
        self.assertEqual(recovery.dropped_request_ids, ["GRQ-R3-1"])
        self.assertEqual(recovery.remaining_request_count, 1)

    def test_execute_rejects_raw_history_duplicate_without_fallback(self):
        payload = gap_input()
        raw_query = "민법 권리남용 원칙 [원문 맥락] 관련 법정 근거의 적용 여부를 판단하라."
        payload["query_history"] = [{"request_id": "GRQ-R1-1", "query_text": raw_query}]
        duplicate = gap_output([gap_request("E1", raw_query, request_id="GRQ-R2-1")])
        prompts, diagnostics = [], []
        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills",
            "fixture-model",
            max_attempts=2,
            generator=lambda prompt: (
                prompts.append(prompt) or json.dumps(duplicate, ensure_ascii=False)
            ),
            diagnostic_sink=diagnostics.append,
        )

        with self.assertRaisesRegex(
            SkillExecutionError, "query repeats query_history"
        ):
            executor.execute(
                "legal_issue_and_query_planning", "GAP_QUERY_PLAN", payload
            )

        self.assertEqual(len(prompts), 2)
        self.assertEqual(len(diagnostics), 2)
        self.assertEqual(
            [diagnostic["outcome"] for diagnostic in diagnostics],
            ["validation_error", "validation_error"],
        )
        self.assertEqual(
            [diagnostic["error"] for diagnostic in diagnostics],
            ["query repeats query_history: %s" % raw_query] * 2,
        )

    def test_c02_qa406_and_qa99_transcript_shapes_drop_only_repaired_history_collision(self):
        qa406_question = "갑이 을의 꽃 꺾기 행위에 대해 방해의 제거를 청구할 수 있는가? 또한, 갑에게 방해제거청구권이 인정되는 경우, 갑은 이를 남용할 수 있는가?"
        qa406_payload = gap_input()
        qa406_payload.update({
            "normalized_question": qa406_question,
            "next_retrieval_round": 3,
            "remaining_request_budget": 5,
            "query_history": [{
                "request_id": "GRQ-R2-2",
                "query_text": "민법 권리남용 금지 원칙 및 판단 기준 [원문 맥락] " + qa406_question,
            }],
        })
        qa406_recovered, qa406_audit = self._transcript_recovery(
            qa406_payload,
            gap_output([
                gap_request("E1", "민법 제214조 소유권 침해 방해의 유형 및 범위"),
                gap_request("E1", "민법 제2조 권리남용 금지 원칙 및 판단 기준"),
            ]),
        )
        self.assertEqual(qa406_audit.dropped_request_ids, ["GRQ-R3-2"])
        self.assertEqual(
            [request["request_id"] for request in qa406_recovered["gap_retrieval_requests"]],
            ["GRQ-R3-1"],
        )

        qa99_question = "을은 이 해고가 부당하다고 생각하여 자신의 권리를 찾고자 합니다. 을은 갑으로부터 부당해고를 당한 경우 어떤 조치를 취할 수 있는가?"
        qa99_payload = gap_input()
        qa99_payload.update({
            "normalized_question": qa99_question,
            "next_retrieval_round": 3,
            "legal_issues": [{"issue_id": "I1"}, {"issue_id": "I2"}],
            "required_evidence_items": [
                qa99_payload["required_evidence_items"][0],
                {
                    "evidence_item_id": "E2",
                    "issue_id": "I2",
                    "evidence_type": "remedy",
                    "description": "부당해고 구제결정의 법적 효과",
                    "critical": True,
                },
            ],
            "coverage_assessments": [
                {"evidence_item_id": "E1", "status": "partially_covered"},
                {"evidence_item_id": "E2", "status": "partially_covered"},
            ],
            "missing_evidence_items": [
                {"evidence_item_id": "E1"},
                {"evidence_item_id": "E2"},
            ],
            "remaining_request_budget": 4,
            "query_history": [{
                "request_id": "GRQ-R2-1",
                "query_text": "근로기준법 부당해고 구제신청 기한 60일 관할 중앙노동위원회 [원문 맥락] " + qa99_question,
            }],
        })
        qa99_recovered, qa99_audit = self._transcript_recovery(
            qa99_payload,
            gap_output([
                gap_request(
                    "E1",
                    "근로기준법 제28조 제1항 부당해고 구제신청 기한 60일 관할 중앙노동위원회",
                ),
                gap_request(
                    "E2",
                    "근로기준법 제33조 부당해고 구제결정 확정 효력 이행 강제",
                    issue_id="I2",
                ),
            ]),
        )
        self.assertEqual(qa99_audit.dropped_request_ids, ["GRQ-R3-1"])
        self.assertEqual(
            [request["request_id"] for request in qa99_recovered["gap_retrieval_requests"]],
            ["GRQ-R3-2"],
        )

    def test_question_anchor_placeholders_recover_only_from_requested_output_substrings(self):
        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills", "fixture-model", generator=lambda _prompt: "{}"
        )
        output = {
            "answer_targets": [
                {"answer_target_id": "T1", "question_anchor": "T1", "requested_output": "계약을 해제할 수 있는지"},
                {"answer_target_id": "T2", "question_anchor": "T2", "requested_output": "손해배상을 청구할 수 있는지"},
                {"answer_target_id": "T3", "question_anchor": "T3", "requested_output": "질문에 없는 내용"},
            ],
        }
        repaired, audit = executor._repair_s1_transport(
            "legal_issue_and_query_planning",
            "INITIAL_PLAN",
            output,
            {"original_question": "[질문] 계약을 해제할 수 있는지와 손해배상을 청구할 수 있는지 판단하라."},
        )
        self.assertEqual(
            [target["question_anchor"] for target in repaired["answer_targets"]],
            ["계약을 해제할 수 있는지", "손해배상을 청구할 수 있는지", "T3"],
        )
        self.assertEqual(len(audit), 2)


if __name__ == "__main__":
    unittest.main()
