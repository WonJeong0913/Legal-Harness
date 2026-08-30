import copy
import hashlib
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
from harness.validation import ValidationError, validate_gap_plan
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
    @staticmethod
    def _single_initial_anchor_output(
        *, answer_target_id="T1", question_anchor="T1", requested_output="판단 결과"
    ):
        return {
            "schema_version": "1.0",
            "skill_id": "S1",
            "mode": "INITIAL_PLAN",
            "status": "ok",
            "run_id": "run-1",
            "answer_targets": [{
                "answer_target_id": answer_target_id,
                "question_anchor": question_anchor,
                "requested_output": requested_output,
                "answer_type": "requested_conclusion",
                "transport_metadata": {"preserve": ["target"]},
            }],
            "legal_issues": [{"issue_id": "I1", "preserve": {"issue": True}}],
            "required_evidence_items": [{
                "evidence_item_id": "E1",
                "issue_id": "I1",
                "evidence_type": "rule",
                "description": "검증 근거",
                "critical": True,
                "completion_criteria": "검증 기준",
                "necessity_reason": "질문 판단에 필요",
                "answer_target_ids": [answer_target_id],
                "scope_source": "explicit_question",
                "completion_requirements": [{
                    "requirement_id": "E1-R1",
                    "text": "검증 기준",
                }],
                "preserve": {"evidence": True},
            }],
            "retrieval_requests": [{
                "request_id": "RQ1",
                "issue_id": "I1",
                "evidence_item_id": "E1",
                "query_channel": "sparse_keywords",
                "query_text": "원래 검색어",
                "query_terms": ["원래", "검색어"],
                "statute_hints": [],
                "rationale": "검증 검색",
                "preserve": {"request": True},
            }],
        }

    @staticmethod
    def _repair_initial_anchor(output, skill_input):
        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills", "fixture-model", generator=lambda _prompt: "{}"
        )
        return executor._repair_s1_transport(
            "legal_issue_and_query_planning", "INITIAL_PLAN", output, skill_input
        )

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

    def _qa125_sibling_collision_fixture(self):
        question = (
            "갑은 1심 판결에 대해 항소를 제기하려고 합니다. "
            "항소 이유로 주장할 수 있는 사유 중 하나는 무엇인가?"
        )
        payload = gap_input()
        payload["normalized_question"] = question
        sibling = gap_request(
            "E1",
            "형사소송법 항소이유 판단의 이유의 불기재",
            request_id="GRQ-R1-1",
        )
        sibling.update({
            "query_channel": "sparse_keywords",
            "query_terms": ["항소이유", "판단의 이유", "불기재", "형사소송법"],
            "statute_hints": ["형사소송법"],
        })
        repaired_candidate = gap_request(
            "E1",
            "형사소송법 제361조 항소이유 판단의 이유의 불기재",
            request_id="GRQ-R1-2",
        )
        repaired_candidate.update({
            "query_channel": "statute_aware",
            "query_terms": ["제361조", "항소이유", "판단의 이유", "불기재"],
            "statute_hints": ["형사소송법 제361조"],
        })
        raw = gap_output([sibling, repaired_candidate])
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
        return {
            "executor": executor,
            "payload": payload,
            "raw": raw,
            "skill_input": skill_input,
            "unrepaired": unrepaired,
            "repaired": repaired,
            "repairs": repairs,
            "errors": errors,
        }

    def test_c24_qa125_article_repair_drops_only_duplicate_critical_sibling(self):
        fixture = self._qa125_sibling_collision_fixture()
        executor = fixture["executor"]
        unrepaired = fixture["unrepaired"]
        repaired = fixture["repaired"]
        repairs = fixture["repairs"]
        errors = fixture["errors"]
        question = fixture["payload"]["normalized_question"]
        sibling_query = (
            "형사소송법 항소이유 판단의 이유의 불기재\n[원문 맥락]\n"
            + question
        )
        repaired_duplicate_query = (
            "형사소송법 항소이유 판단의 이유의 불기재 [원문 맥락] "
            + question
        )
        article_query = (
            "형사소송법 제361조 항소이유 판단의 이유의 불기재"
            "\n[원문 맥락]\n"
            + question
        )

        self.assertEqual(
            [item["query_text"] for item in unrepaired["gap_retrieval_requests"]],
            [
                sibling_query,
                article_query,
            ],
        )
        self.assertEqual(
            [item["query_text"] for item in repaired["gap_retrieval_requests"]],
            [sibling_query, repaired_duplicate_query],
        )
        self.assertEqual(
            executor._normalized_query(sibling_query),
            executor._normalized_query(repaired_duplicate_query),
        )
        self.assertNotEqual(
            executor._normalized_query(
                unrepaired["gap_retrieval_requests"][0]["query_text"]
            ),
            executor._normalized_query(
                unrepaired["gap_retrieval_requests"][1]["query_text"]
            ),
        )
        self.assertEqual(
            errors,
            [
                "duplicate normalized query in output: %s"
                % repaired_duplicate_query
            ],
        )
        self.assertEqual(
            [
                item["request_id"]
                for item in repairs
                if item.get("field") == "query_text"
            ],
            ["GRQ-R2-2"],
        )
        self.assertEqual(
            [item["evidence_item_id"] for item in repaired["gap_retrieval_requests"]],
            ["E1", "E1"],
        )
        self.assertEqual(
            [item["query_terms"] for item in unrepaired["gap_retrieval_requests"]],
            [
                ["항소이유", "판단의 이유", "불기재", "형사소송법"],
                ["제361조", "항소이유", "판단의 이유", "불기재"],
            ],
        )
        self.assertEqual(
            [item["statute_hints"] for item in unrepaired["gap_retrieval_requests"]],
            [["형사소송법"], ["형사소송법 제361조"]],
        )
        self.assertEqual(
            [item["query_terms"] for item in repaired["gap_retrieval_requests"]],
            [
                ["항소이유", "판단의 이유", "불기재", "형사소송법"],
                ["항소이유", "판단의 이유", "불기재"],
            ],
        )
        self.assertEqual(
            [item["statute_hints"] for item in repaired["gap_retrieval_requests"]],
            [["형사소송법"], ["형사소송법"]],
        )
        self.assertEqual(
            repairs,
            [
                {
                    "kind": "neutralized_ungrounded_article_specificity",
                    "request_id": "GRQ-R2-2",
                    "field": "query_text",
                    "before": article_query,
                    "after": repaired_duplicate_query,
                },
                {
                    "kind": "neutralized_ungrounded_article_specificity",
                    "request_id": "GRQ-R2-2",
                    "field": "query_terms",
                    "before": ["제361조", "항소이유", "판단의 이유", "불기재"],
                    "after": ["항소이유", "판단의 이유", "불기재"],
                },
                {
                    "kind": "neutralized_ungrounded_article_specificity",
                    "request_id": "GRQ-R2-2",
                    "field": "statute_hints",
                    "before": ["형사소송법 제361조"],
                    "after": ["형사소송법"],
                },
            ],
        )

        recovered, recovery = executor._repair_induced_sibling_collision_recovery(
            "legal_issue_and_query_planning",
            "GAP_QUERY_PLAN",
            unrepaired,
            repaired,
            fixture["skill_input"],
            repairs,
            errors,
        )

        self.assertEqual(
            recovery.disposition,
            GapPlanRecoveryDisposition.REPAIR_INDUCED_SIBLING_COLLISION,
        )
        self.assertEqual(recovery.dropped_request_ids, ["GRQ-R2-2"])
        self.assertEqual(recovery.remaining_request_count, 1)
        self.assertEqual(
            recovered["gap_retrieval_requests"],
            [repaired["gap_retrieval_requests"][0]],
        )
        self.assertEqual(recovered["target_evidence_item_ids"], ["E1"])
        self.assertEqual(
            executor._validators["legal_issue_and_query_planning"](
                recovered, fixture["skill_input"]
            ),
            [],
        )

    def test_qa125_execute_uses_typed_fallback_when_neutral_replan_fails(self):
        fixture = self._qa125_sibling_collision_fixture()
        prompts = []
        diagnostics = []
        responses = iter([
            json.dumps(fixture["raw"], ensure_ascii=False),
            "not json",
        ])
        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills",
            "fixture-model",
            generator=lambda prompt: prompts.append(prompt) or next(responses),
            diagnostic_sink=diagnostics.append,
        )

        output = executor.execute(
            "legal_issue_and_query_planning",
            "GAP_QUERY_PLAN",
            fixture["payload"],
        )

        self.assertEqual(len(prompts), 2)
        self.assertIn("NEUTRAL_SEMANTIC_GAP_REPLAN", prompts[1])
        self.assertEqual(
            [item["request_id"] for item in output["gap_retrieval_requests"]],
            ["GRQ-R2-1"],
        )
        recovery = output["harness_gap_plan_recovery"]
        self.assertEqual(
            recovery.disposition,
            GapPlanRecoveryDisposition.REPAIR_INDUCED_SIBLING_COLLISION,
        )
        self.assertEqual(recovery.dropped_request_ids, ["GRQ-R2-2"])
        self.assertEqual(recovery.remaining_request_count, 1)
        outer = diagnostics[-1]
        self.assertEqual(outer["outcome"], "valid")
        self.assertEqual(
            outer["semantic_replan_events"][0]["reason"],
            GapPlanRecoveryDisposition.REPAIR_INDUCED_SIBLING_COLLISION.value,
        )
        self.assertEqual(
            outer["semantic_replan_events"][-1]["kind"],
            "neutral_semantic_gap_replan_fallback",
        )

    def test_qa125_execute_adopts_single_target_neutral_replan(self):
        fixture = self._qa125_sibling_collision_fixture()
        clean_replan = gap_output([
            gap_request(
                "E1",
                "형사소송법 판결 이유 불기재 항소이유 법정 근거",
                request_id="model-replan",
            )
        ])
        prompts = []
        diagnostics = []
        responses = iter([
            json.dumps(fixture["raw"], ensure_ascii=False),
            json.dumps(clean_replan, ensure_ascii=False),
        ])
        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills",
            "fixture-model",
            generator=lambda prompt: prompts.append(prompt) or next(responses),
            diagnostic_sink=diagnostics.append,
        )

        output = executor.execute(
            "legal_issue_and_query_planning",
            "GAP_QUERY_PLAN",
            fixture["payload"],
        )

        self.assertEqual(len(prompts), 2)
        self.assertEqual(
            [item["request_id"] for item in output["gap_retrieval_requests"]],
            ["GRQ-R2-1"],
        )
        self.assertEqual(
            [
                item["evidence_item_id"]
                for item in output["gap_retrieval_requests"]
            ],
            ["E1"],
        )
        self.assertIn(
            "형사소송법 판결 이유 불기재 항소이유 법정 근거",
            output["gap_retrieval_requests"][0]["query_text"],
        )
        self.assertNotIn("harness_gap_plan_recovery", output)
        outer = diagnostics[-1]
        self.assertEqual(
            [event["kind"] for event in outer["semantic_replan_events"]],
            [
                "neutral_semantic_gap_replan_attempted",
                "neutral_semantic_gap_replan_adopted",
            ],
        )

    def test_sibling_collision_recovery_fails_closed_outside_exact_guards(self):
        fixture = self._qa125_sibling_collision_fixture()
        executor = fixture["executor"]
        base = (
            fixture["unrepaired"],
            fixture["repaired"],
            fixture["skill_input"],
            fixture["repairs"],
            fixture["errors"],
        )
        cases = []

        raw_duplicate = copy.deepcopy(base[0])
        raw_duplicate["gap_retrieval_requests"][1]["query_text"] = (
            raw_duplicate["gap_retrieval_requests"][0]["query_text"]
        )
        cases.append(("raw_duplicate", raw_duplicate, *base[1:]))

        different_evidence_raw = copy.deepcopy(base[0])
        different_evidence_repaired = copy.deepcopy(base[1])
        different_evidence_raw["gap_retrieval_requests"][0][
            "evidence_item_id"
        ] = "E2"
        different_evidence_repaired["gap_retrieval_requests"][0][
            "evidence_item_id"
        ] = "E2"
        cases.append((
            "different_evidence",
            different_evidence_raw,
            different_evidence_repaired,
            base[2],
            base[3],
            base[4],
        ))

        noncritical_input = copy.deepcopy(base[2])
        noncritical_input["required_evidence_items"][0]["critical"] = False
        cases.append((
            "noncritical_evidence",
            base[0],
            base[1],
            noncritical_input,
            base[3],
            base[4],
        ))

        both_repaired = copy.deepcopy(base[3])
        both_repaired.append({
            "kind": "neutralized_ungrounded_article_specificity",
            "request_id": "GRQ-R2-1",
            "field": "query_text",
            "before": base[0]["gap_retrieval_requests"][0]["query_text"],
            "after": base[1]["gap_retrieval_requests"][0]["query_text"],
        })
        cases.append((
            "both_siblings_repaired",
            base[0],
            base[1],
            base[2],
            both_repaired,
            base[4],
        ))

        mismatched_raw_id = copy.deepcopy(base[0])
        mismatched_raw_id["gap_retrieval_requests"][1]["request_id"] = "other"
        cases.append((
            "raw_repaired_request_id_mismatch",
            mismatched_raw_id,
            base[1],
            base[2],
            base[3],
            base[4],
        ))

        distinct_scoring_raw = copy.deepcopy(base[0])
        distinct_scoring_repaired = copy.deepcopy(base[1])
        for output in (distinct_scoring_raw, distinct_scoring_repaired):
            request = output["gap_retrieval_requests"][1]
            request["first_stage_query_text"] = "별도의 1단계 검색"
            request["rerank_query_text"] = "별도의 재정렬 검색"
        cases.append((
            "distinct_scoring_queries",
            distinct_scoring_raw,
            distinct_scoring_repaired,
            base[2],
            base[3],
            base[4],
        ))

        cases.append((
            "additional_validator_error",
            base[0],
            base[1],
            base[2],
            base[3],
            list(base[4]) + ["unrelated validation error"],
        ))

        for name, unrepaired, repaired, skill_input, repairs, errors in cases:
            with self.subTest(name=name):
                recovered, recovery = (
                    executor._repair_induced_sibling_collision_recovery(
                        "legal_issue_and_query_planning",
                        "GAP_QUERY_PLAN",
                        unrepaired,
                        repaired,
                        skill_input,
                        repairs,
                        errors,
                    )
                )
                self.assertIsNone(recovered)
                self.assertIsNone(recovery)

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

    def test_raw_duplicates_survive_mixed_article_neutralization(self):
        cases = (
            ("statute_hints", ["소득세법", "소득세법", "소득세법 제65조"]),
            ("query_terms", ["소득세법 제65조", "소득세법", "소득세법"]),
        )
        for field, values in cases:
            with self.subTest(field=field):
                request = {
                    "request_id": "GRQ-R2-1",
                    "issue_id": "I1",
                    "evidence_item_id": "E1",
                    "query_channel": "statute_aware",
                    "query_text": "소득세법 제65조 중간예납추계액 미신고 처리",
                    "top_k": 100,
                    "query_terms": values if field == "query_terms" else ["중간예납추계액"],
                    "statute_hints": values if field == "statute_hints" else [],
                    "rationale": "미확인 법정 근거를 검색한다.",
                    "gap_reason": "중간예납추계액신고서 미제출의 처리 근거가 미확인이다.",
                    "source_assessment_status": "uncovered",
                }
                repaired, repairs = S1_VALIDATOR.neutralize_ungrounded_article_specificity(
                    [request], gap_input()
                )
                repaired_request = repaired[0]
                self.assertEqual(repaired_request[field], ["소득세법", "소득세법"])
                dedupe_repairs = [
                    repair
                    for repair in repairs
                    if repair["kind"] == "deduplicated_repair_induced_list_values"
                    and repair["field"] == field
                ]
                self.assertEqual(len(dedupe_repairs), 1)
                self.assertEqual(dedupe_repairs[0]["before"], ["소득세법"] * 3)
                self.assertEqual(dedupe_repairs[0]["after"], ["소득세법"] * 2)
                state = RunState(
                    question="중간예납추계액 미신고 처리",
                    normalized_question="중간예납추계액 미신고 처리",
                    run_id="mixed-raw-duplicates-" + field,
                )
                state.legal_issues = [LegalIssue("I1", "중간예납추계액 처리")]
                state.required_evidence_items = [RequiredEvidenceItem(
                    "E1", "I1", "rule", "관련 법정 근거와 적용 요건", True,
                )]
                with self.assertRaisesRegex(
                    ValidationError, field + " must not contain duplicates"
                ):
                    validate_gap_plan({"gap_retrieval_requests": repaired}, state)

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
        self.assertEqual(len(diagnostics), 2)
        replan_diagnostic = diagnostics[0]
        expected_replan_response = json.dumps(neutral_replan, ensure_ascii=False)
        self.assertEqual(
            replan_diagnostic["generation_kind"], "neutral_semantic_gap_replan"
        )
        self.assertEqual(replan_diagnostic["schema_version"], "1.2")
        self.assertEqual(
            replan_diagnostic["prompt_sha256"],
            hashlib.sha256(prompts[1].encode("utf-8")).hexdigest(),
        )
        self.assertEqual(len(replan_diagnostic["redacted_skill_input_sha256"]), 64)
        self.assertEqual(replan_diagnostic["response_text"], expected_replan_response)
        self.assertEqual(
            diagnostics[-1]["generation_kind"], "primary_skill_attempt"
        )
        self.assertEqual(
            replan_diagnostic["response_characters"], len(expected_replan_response)
        )
        self.assertEqual(
            replan_diagnostic["response_utf8_bytes"],
            len(expected_replan_response.encode("utf-8")),
        )
        self.assertEqual(
            replan_diagnostic["response_sha256"],
            hashlib.sha256(expected_replan_response.encode("utf-8")).hexdigest(),
        )
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

    def test_all_history_collision_replans_then_uses_trusted_completion_fallback(self):
        payload = gap_input()
        payload["normalized_question"] = "법인 구성원이 갖추어야 할 자격 요건을 설명하라."
        evidence = payload["required_evidence_items"][0]
        evidence.update({
            "description": "법인 구성원이 갖추어야 할 자격 요건 규정",
            "completion_criteria": "법인 구성원 자격 요건의 법적 근거가 확인되어야 함",
            "completion_requirements": [{
                "requirement_id": "E1-R1",
                "text": "법인 구성원의 자격 요건을 규정한 조항",
            }],
        })
        historic = (
            "법인 구성원 자격 요건\n[원문 맥락]\n"
            + payload["normalized_question"]
        )
        payload["query_history"] = [{"request_id": "RQ1", "query_text": historic}]
        raw = gap_output([
            gap_request("E1", "법인 구성원 자격 요건", request_id="model-owned")
        ])
        prompts, diagnostics = [], []
        responses = iter([
            json.dumps(raw, ensure_ascii=False),
            json.dumps(raw, ensure_ascii=False),
            "not json",
        ])
        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills",
            "fixture-model",
            generator=lambda prompt: prompts.append(prompt) or next(responses),
            diagnostic_sink=diagnostics.append,
        )

        output = executor.execute(
            "legal_issue_and_query_planning", "GAP_QUERY_PLAN", payload
        )

        self.assertEqual(len(prompts), 3)
        self.assertNotIn("NEUTRAL_SEMANTIC_GAP_REPLAN", prompts[1])
        self.assertIn("NEUTRAL_SEMANTIC_GAP_REPLAN", prompts[2])
        request = output["gap_retrieval_requests"][0]
        self.assertNotEqual(request["query_text"], historic)
        self.assertIn("법적 근거가 확인되어야 함 법률 조문", request["query_text"])
        primary = [
            item for item in diagnostics
            if item["generation_kind"] == "primary_skill_attempt"
        ]
        self.assertEqual([item["outcome"] for item in primary], ["validation_error", "valid"])
        fallback = primary[-1]["trusted_all_history_collision_fallback"]
        self.assertEqual(fallback["outcome"], "fallback_adopted")
        self.assertEqual(fallback["request_ids"], ["GRQ-R2-1"])
        self.assertEqual(len(fallback["replaced_query_sha256"][0]), 64)
        self.assertEqual(len(fallback["fallback_query_sha256"][0]), 64)

    def test_all_history_collision_fallback_rejects_stale_scoring_or_pinpoint_fields(self):
        for field, value in (
            ("first_stage_query_text", "별도 검색 질의"),
            ("rerank_query_text", "__same_as_historic_query__"),
            ("query_terms", ["법인 구성원 자격 요건", "제999조"]),
            ("statute_hints", ["예시법 제999조"]),
        ):
            with self.subTest(field=field):
                payload = gap_input()
                payload["normalized_question"] = "법인 구성원의 자격 요건을 설명하라."
                evidence = payload["required_evidence_items"][0]
                evidence.update({
                    "completion_criteria": "법인 구성원 자격 요건의 법적 근거가 확인되어야 함",
                    "completion_requirements": [{
                        "requirement_id": "E1-R1",
                        "text": "법인 구성원의 자격 요건을 규정한 조항",
                    }],
                })
                historic = "법인 구성원 자격 요건\n[원문 맥락]\n" + payload["normalized_question"]
                payload["query_history"] = [{"request_id": "RQ1", "query_text": historic}]
                raw = gap_output([
                    gap_request("E1", "법인 구성원 자격 요건", request_id="model-owned")
                ])
                request = raw["gap_retrieval_requests"][0]
                if value == "__same_as_historic_query__":
                    request["query_text"] = historic
                    request[field] = historic
                else:
                    request[field] = value
                prompts = []
                executor = LocalOllamaSkillExecutor(
                    PROJECT_ROOT / "skills",
                    "fixture-model",
                    max_attempts=2,
                    generator=lambda prompt: (
                        prompts.append(prompt) or json.dumps(raw, ensure_ascii=False)
                    ),
                )

                with self.assertRaisesRegex(SkillExecutionError, "query repeats query_history"):
                    executor.execute(
                        "legal_issue_and_query_planning", "GAP_QUERY_PLAN", payload
                    )
                self.assertEqual(len(prompts), 2)

    def test_all_history_collision_adopts_clean_neutral_replan_before_fallback(self):
        payload = gap_input()
        payload["normalized_question"] = "법인 구성원이 갖추어야 할 자격 요건을 설명하라."
        evidence = payload["required_evidence_items"][0]
        evidence.update({
            "completion_criteria": "법인 구성원 자격 요건의 법적 근거가 확인되어야 함",
            "completion_requirements": [{
                "requirement_id": "E1-R1",
                "text": "법인 구성원의 자격 요건을 규정한 조항",
            }],
        })
        historic = "법인 구성원 자격 요건\n[원문 맥락]\n" + payload["normalized_question"]
        payload["query_history"] = [{"request_id": "RQ1", "query_text": historic}]
        duplicate = gap_output([
            gap_request("E1", "법인 구성원 자격 요건", request_id="model-owned")
        ])
        clean_replan = gap_output([
            gap_request("E1", "법인 구성원 자격의 법적 근거", request_id="model-owned")
        ])
        diagnostics = []
        responses = iter([
            json.dumps(duplicate, ensure_ascii=False),
            json.dumps(duplicate, ensure_ascii=False),
            json.dumps(clean_replan, ensure_ascii=False),
        ])
        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills",
            "fixture-model",
            generator=lambda _prompt: next(responses),
            diagnostic_sink=diagnostics.append,
        )

        output = executor.execute(
            "legal_issue_and_query_planning", "GAP_QUERY_PLAN", payload
        )

        self.assertIn(
            "법인 구성원 자격의 법적 근거",
            output["gap_retrieval_requests"][0]["query_text"],
        )
        primary = [
            item for item in diagnostics
            if item["generation_kind"] == "primary_skill_attempt"
        ]
        self.assertEqual(
            primary[-1]["trusted_all_history_collision_fallback"]["outcome"],
            "replan_adopted",
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
        # The other two C02 history collisions had the same normalizer-induced
        # shape but different statutes and semantic retrieval anchors.
        for question_id, raw_query, prior_query in (
            (
                "qa_460_3hop_730",
                "민사조정법 제29조 이의신청 기한 경과 시 조정결정 확정 효력",
                "민사조정법 이의신청 기한 경과 시 조정결정 확정 효력",
            ),
            (
                "qa_273_2hop_431",
                "민법 제103조 궁박한 상태의 이용 취소",
                "민법 궁박한 상태의 이용 취소",
            ),
        ):
            with self.subTest(question_id=question_id):
                payload = gap_input()
                payload.update({
                    "next_retrieval_round": 3,
                    "query_history": [{
                        "request_id": "GRQ-R2-1",
                        "query_text": prior_query + " [원문 맥락] " + payload["normalized_question"],
                    }],
                })
                recovered, recovery = self._transcript_recovery(
                    payload,
                    gap_output([gap_request("E1", raw_query)]),
                )
                self.assertEqual(recovery.dropped_request_ids, ["GRQ-R3-1"])
                self.assertEqual(recovered["gap_retrieval_requests"], [])


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

    def test_single_target_placeholder_anchor_uses_marker_question_body_only(self):
        output = self._single_initial_anchor_output()
        before = copy.deepcopy(output)
        question_body = "T1 식별자가 본문에 있어도 계약 해제의 요건은 무엇인가?"
        repaired, audit = self._repair_initial_anchor(
            output,
            {
                "original_question": "배경 설명. [질문] " + question_body + "  ",
                "normalized_question": "다른 정규화 질문",
            },
        )

        expected = copy.deepcopy(before)
        expected["answer_targets"][0]["question_anchor"] = question_body
        self.assertEqual(repaired, expected)
        self.assertEqual(
            audit,
            [{
                "kind": "single_target_question_anchor_fallback",
                "answer_target_id": "T1",
                "before": "T1",
                "after": question_body,
                "reason": "single_target_placeholder_anchor_transport",
                "guards": {
                    "entry_point_is_initial_plan": True,
                    "single_answer_target": True,
                    "answer_target_id_nonempty_string": True,
                    "question_anchor_matches_answer_target_id": True,
                    "requested_output_nonempty_string": True,
                    "requested_output_substring_repair_applied": False,
                    "trusted_question_body_nonempty": True,
                    "trusted_question_body_source": "original_question_marker",
                },
            }],
        )

    def test_single_target_placeholder_anchor_uses_normalized_question_without_marker(self):
        output = self._single_initial_anchor_output()
        question_body = "정규화된 질문 본문에 T1 식별자가 있어도 무엇인가?"
        repaired, audit = self._repair_initial_anchor(
            output,
            {
                "original_question": "질문 표식이 없는 배경 설명",
                "normalized_question": "  " + question_body + "  ",
            },
        )

        self.assertEqual(repaired["answer_targets"][0]["question_anchor"], question_body)
        self.assertEqual(audit[0]["guards"]["trusted_question_body_source"], "normalized_question")

    def test_qa116_non_substring_anchor_variants_derive_marker_question_body(self):
        question_body = (
            "갑이 의뢰인 을에게 헌법재판소가 사건을 접수한 후 종국결정의 "
            "선고는 몇 일 이내에 이루어져야 한다고 설명해야 하는가?"
        )
        original_question = (
            "[배경 시나리오]\n"
            "갑은 대한민국의 변호사로서, 그의 의뢰인 을이 헌법 소원을 제기하여 "
            "헌법재판소에 사건을 접수하였다.\n\n[질문]\n"
            + question_body
        )
        anchors = (
            "헌법재판소가 사건을 접수한 후 종국결정의 선고는 몇 일 이내에 이루어져야 하는가",
            "종국결정의 선고는 몇 일 이내에 이루어져야 하는가",
        )
        for anchor in anchors:
            with self.subTest(anchor=anchor):
                output = self._single_initial_anchor_output(
                    question_anchor=anchor,
                    requested_output=(
                        "The statutory maximum number of days within which the "
                        "Constitutional Court must pronounce a final decision after "
                        "accepting a constitutional complaint."
                    ),
                )
                before = copy.deepcopy(output)
                repaired, audit = self._repair_initial_anchor(
                    output,
                    {
                        "original_question": original_question,
                        "normalized_question": question_body,
                    },
                )

                expected = copy.deepcopy(before)
                expected["answer_targets"][0]["question_anchor"] = question_body
                self.assertEqual(repaired, expected)
                self.assertEqual(len(audit), 1)
                self.assertEqual(
                    audit[0]["kind"],
                    "single_target_non_substring_anchor_fallback",
                )
                self.assertEqual(audit[0]["before"], anchor)
                self.assertEqual(audit[0]["after"], question_body)
                self.assertEqual(
                    audit[0]["reason"],
                    "single_target_non_substring_anchor_transport",
                )
                self.assertTrue(all(audit[0]["guards"].values()), audit)
                self.assertTrue(
                    audit[0]["guards"]
                    ["trusted_question_body_from_original_question_marker"]
                )

    def test_valid_single_target_anchor_never_uses_non_substring_fallback(self):
        question_body = "계약 해제의 요건은 무엇인가?"
        output = self._single_initial_anchor_output(
            question_anchor="계약 해제의 요건",
        )
        before = copy.deepcopy(output)
        repaired, audit = self._repair_initial_anchor(
            output,
            {"original_question": "[질문] " + question_body},
        )
        self.assertEqual(repaired, before)
        self.assertEqual(audit, [])

    def test_validator_trusted_question_source_matches_anchor_repair_contract(self):
        cases = [
            (
                {
                    "original_question": "배경 [질문] marker 본문 T1",
                    "normalized_question": "normalized 본문 T1",
                },
                "marker 본문 t1",
            ),
            (
                {
                    "original_question": "배경 [질문]   ",
                    "normalized_question": "normalized 본문 T1",
                },
                "",
            ),
            (
                {
                    "original_question": "marker 없는 배경 T1",
                    "normalized_question": "normalized 본문 T1",
                },
                "normalized 본문 t1",
            ),
            (
                {"original_question": "marker 없는 배경 T1", "normalized_question": " "},
                "",
            ),
        ]
        for skill_input, expected in cases:
            with self.subTest(skill_input=skill_input):
                self.assertEqual(
                    S1_VALIDATOR.trusted_answer_question_segment(skill_input),
                    expected,
                )

    def test_single_target_anchor_fallback_fails_closed_outside_guards(self):
        multiple_targets = self._single_initial_anchor_output()
        multiple_targets["answer_targets"].append({
            "answer_target_id": "T2",
            "question_anchor": "T2",
            "requested_output": "추가 결과",
            "answer_type": "requested_conclusion",
        })
        incomplete_evidence_target_linkage = self._single_initial_anchor_output(
            question_anchor="질문에 없는 앵커",
        )
        incomplete_evidence_target_linkage["required_evidence_items"][0][
            "answer_target_ids"
        ] = ["T2"]
        target_id_mismatch = self._single_initial_anchor_output(question_anchor="T2")
        target_id_mismatch["retrieval_requests"][0]["evidence_item_id"] = "E2"
        missing_evidence_id = self._single_initial_anchor_output(
            question_anchor="질문에 없는 앵커",
        )
        missing_evidence_id["required_evidence_items"][0]["evidence_item_id"] = ""
        missing_request_id = self._single_initial_anchor_output(
            question_anchor="질문에 없는 앵커",
        )
        missing_request_id["retrieval_requests"][0]["request_id"] = ""
        cases = [
            (
                "multiple_targets",
                multiple_targets,
                {"original_question": "[질문] T1이 포함된 하나의 질문 본문"},
            ),
            (
                "incomplete_evidence_target_linkage",
                incomplete_evidence_target_linkage,
                {"original_question": "[질문] T1이 포함된 하나의 질문 본문"},
            ),
            (
                "target_id_mismatch",
                target_id_mismatch,
                {"original_question": "[질문] 하나의 질문 본문"},
            ),
            (
                "missing_evidence_id",
                missing_evidence_id,
                {"original_question": "[질문] 하나의 질문 본문"},
            ),
            (
                "missing_request_id",
                missing_request_id,
                {"original_question": "[질문] 하나의 질문 본문"},
            ),
            (
                "empty_answer_target_id",
                self._single_initial_anchor_output(answer_target_id="", question_anchor=""),
                {"original_question": "[질문] 하나의 질문 본문"},
            ),
            (
                "empty_requested_output",
                self._single_initial_anchor_output(requested_output="  "),
                {"original_question": "[질문] 하나의 질문 본문"},
            ),
            (
                "malformed_requested_output",
                self._single_initial_anchor_output(requested_output=None),
                {"original_question": "[질문] 하나의 질문 본문"},
            ),
            (
                "empty_marker_question_body",
                self._single_initial_anchor_output(),
                {
                    "original_question": "배경 설명 [질문]   ",
                    "normalized_question": "정규화된 질문을 사용하면 안 된다",
                },
            ),
            (
                "background_only_without_normalized_question",
                self._single_initial_anchor_output(),
                {"original_question": "질문 표식이 없는 배경 설명", "normalized_question": " "},
            ),
            (
                "markerless_non_placeholder_anchor",
                self._single_initial_anchor_output(question_anchor="질문에 없는 앵커"),
                {
                    "original_question": "질문 표식이 없는 배경 설명",
                    "normalized_question": "하나의 질문 본문",
                },
            ),
        ]

        for name, output, skill_input in cases:
            with self.subTest(name=name):
                before = copy.deepcopy(output)
                repaired, audit = self._repair_initial_anchor(output, skill_input)
                self.assertEqual(repaired, before)
                self.assertEqual(audit, [])
                validation_input = {
                    "run_id": "run-1",
                    "mode": "INITIAL_PLAN",
                    "constraints": {
                        "answer_target_contract": "required",
                    },
                    **skill_input,
                }
                errors = S1_VALIDATOR.validate(repaired, validation_input)
                self.assertTrue(
                    any("question_anchor is not a question substring" in error for error in errors),
                    errors,
                )

    def test_requested_output_substring_repair_has_priority_over_single_target_fallback(self):
        requested_output = "계약을 해제할 수 있는지"
        output = self._single_initial_anchor_output(requested_output=requested_output)
        repaired, audit = self._repair_initial_anchor(
            output,
            {"original_question": "[질문] T1 및 " + requested_output + " 판단하라."},
        )

        self.assertEqual(repaired["answer_targets"][0]["question_anchor"], requested_output)
        self.assertEqual([item["kind"] for item in audit], ["normalized_question_anchor"])

    def test_c02_qa102_replay_removes_only_unanchored_standalone_paragraph(self):
        payload = gap_input()
        payload["normalized_question"] = (
            "대기오염경보 발령 시 자동차 정비소 조치와 대상 오염물질을 판단하라."
        )
        request = {
            "request_id": "GRQ-R2-1",
            "query_text": (
                "대기환경보전법 제8조제4항 대기오염경보 발령 시 "
                "사업장 조치 의무"
            ),
            "query_terms": ["대기오염경보", "제4항", "자동차 정비소", "조치"],
            "statute_hints": ["대기환경보전법"],
        }

        repaired, audit = S1_VALIDATOR.neutralize_ungrounded_article_specificity(
            [request], payload
        )

        self.assertEqual(
            repaired[0]["query_terms"], ["대기오염경보", "자동차 정비소", "조치"]
        )
        self.assertNotRegex(
            repaired[0]["query_text"], r"제8조|제4항"
        )
        self.assertIn("대기환경보전법", repaired[0]["query_text"])
        self.assertTrue(any(
            repair == {
                "kind": "neutralized_ungrounded_standalone_paragraph",
                "request_id": "GRQ-R2-1",
                "field": "query_terms",
                "before": ["대기오염경보", "제4항", "자동차 정비소", "조치"],
                "after": ["대기오염경보", "자동차 정비소", "조치"],
                "reason": "standalone_paragraph_lacks_request_scoped_grounded_article",
            }
            for repair in audit
        ))
        errors = []
        S1_VALIDATOR.validate_article_grounding(repaired, payload, errors)
        self.assertEqual(errors, [])

    def test_grounded_standalone_paragraph_is_preserved(self):
        payload = gap_input()
        payload["normalized_question"] = "대기환경보전법 제8조제4항의 내용은 무엇인가?"
        request = {
            "request_id": "GRQ-R2-1",
            "query_text": "대기환경보전법 제8조제4항 대기오염경보",
            "query_terms": ["제4항", "대기오염경보"],
            "statute_hints": ["대기환경보전법 제8조제4항"],
        }
        original = copy.deepcopy(request)

        repaired, audit = S1_VALIDATOR.neutralize_ungrounded_article_specificity(
            [request], payload
        )

        self.assertEqual(repaired, [original])
        self.assertEqual(request, original)
        self.assertFalse(any(
            repair["kind"] == "neutralized_ungrounded_standalone_paragraph"
            for repair in audit
        ))

    def test_standalone_paragraph_cleanup_fails_closed_without_anchor(self):
        request = {
            "request_id": "GRQ-R2-1",
            "query_text": "제4항",
            "query_terms": ["제4항"],
            "statute_hints": [],
        }

        repaired, audit = S1_VALIDATOR.neutralize_ungrounded_article_specificity(
            [request], gap_input()
        )

        self.assertEqual(repaired, [request])
        self.assertFalse(any(
            repair["kind"] == "neutralized_ungrounded_standalone_paragraph"
            for repair in audit
        ))
        errors = []
        S1_VALIDATOR.validate_article_grounding(repaired, gap_input(), errors)
        self.assertIn(
            "standalone paragraph lacks request-scoped grounded article provenance: 제4항",
            errors,
        )

    def test_standalone_paragraph_cleanup_fails_closed_for_connector_fragments(self):
        for fragment in ("제4항에 따른", "제4항 관련"):
            with self.subTest(fragment=fragment):
                request = {
                    "request_id": "GRQ-R2-1",
                    "query_text": fragment,
                    "query_terms": [fragment],
                    "statute_hints": [],
                }
                original = copy.deepcopy(request)

                repaired, audit = S1_VALIDATOR.neutralize_ungrounded_article_specificity(
                    [request], gap_input()
                )

                self.assertEqual(repaired, [original])
                self.assertEqual(request, original)
                self.assertFalse(any(
                    repair["kind"] == "neutralized_ungrounded_standalone_paragraph"
                    for repair in audit
                ))
                errors = []
                S1_VALIDATOR.validate_article_grounding(repaired, gap_input(), errors)
                self.assertIn(
                    "standalone paragraph lacks request-scoped grounded article provenance: 제4항",
                    errors,
                )

    def test_standalone_paragraph_repair_deduplicates_only_new_list_collision(self):
        request = {
            "request_id": "GRQ-R2-1",
            "query_text": "대기오염경보 사업장 조치",
            "query_terms": ["대기오염경보", "제4항 대기오염경보"],
            "statute_hints": [],
        }

        repaired, audit = S1_VALIDATOR.neutralize_ungrounded_article_specificity(
            [request], gap_input()
        )

        self.assertEqual(repaired[0]["query_terms"], ["대기오염경보"])
        self.assertTrue(any(
            repair == {
                "kind": "neutralized_ungrounded_standalone_paragraph",
                "request_id": "GRQ-R2-1",
                "field": "query_terms",
                "before": ["대기오염경보", "제4항 대기오염경보"],
                "after": ["대기오염경보"],
                "reason": "standalone_paragraph_lacks_request_scoped_grounded_article",
            }
            for repair in audit
        ))
        errors = []
        S1_VALIDATOR.validate_article_grounding(repaired, gap_input(), errors)
        self.assertEqual(errors, [])

    def test_standalone_paragraph_repair_preserves_raw_list_duplicates(self):
        request = {
            "request_id": "GRQ-R2-1",
            "query_text": "대기오염경보 사업장 조치",
            "query_terms": [
                "대기오염경보",
                "대기오염경보",
                "제4항 대기오염경보",
            ],
            "statute_hints": [],
        }

        repaired, _audit = S1_VALIDATOR.neutralize_ungrounded_article_specificity(
            [request], gap_input()
        )

        self.assertEqual(
            repaired[0]["query_terms"], ["대기오염경보", "대기오염경보"]
        )

    def test_standalone_paragraph_repair_is_recorded_by_executor(self):
        payload = gap_input()
        payload["normalized_question"] = "대기오염경보 발령 시 사업장 조치를 판단하라."
        raw = gap_output([gap_request(
            "E1", "대기환경보전법 제8조제4항 대기오염경보 사업장 조치"
        )])
        raw_request = raw["gap_retrieval_requests"][0]
        raw_request["query_terms"] = ["대기오염경보", "제4항", "사업장 조치"]
        raw_request["statute_hints"] = ["대기환경보전법"]
        diagnostics = []
        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills",
            "fixture-model",
            generator=lambda _prompt: json.dumps(raw, ensure_ascii=False),
            diagnostic_sink=diagnostics.append,
        )

        output = executor.execute(
            "legal_issue_and_query_planning", "GAP_QUERY_PLAN", payload
        )

        self.assertNotIn("제4항", output["gap_retrieval_requests"][0]["query_terms"])
        self.assertTrue(any(
            repair["kind"] == "neutralized_ungrounded_standalone_paragraph"
            and repair["field"] == "query_terms"
            and repair["before"] == ["대기오염경보", "제4항", "사업장 조치"]
            and repair["after"] == ["대기오염경보", "사업장 조치"]
            and repair["reason"]
            == "standalone_paragraph_lacks_request_scoped_grounded_article"
            for repair in diagnostics[-1]["deterministic_repairs"]
        ))


if __name__ == "__main__":
    unittest.main()
