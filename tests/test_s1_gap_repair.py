import copy
import importlib.util
import json
from pathlib import Path
import unittest

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


class GapSpecificityRepairTests(unittest.TestCase):
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
        self.assertEqual(len(prompts), 2)
        self.assertIn("민법 제840조", prompts[1])
        self.assertIn("Previous JSON", prompts[1])

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
