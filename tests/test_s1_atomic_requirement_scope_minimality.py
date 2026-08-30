import copy
import importlib.util
import json
import unittest
from pathlib import Path

from harness.interfaces import SkillExecutionError
from runtime.local_ollama_executor import LocalOllamaSkillExecutor


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "s1_atomic_requirement_scope_minimality_validator",
    PROJECT_ROOT / "skills/legal_issue_and_query_planning/scripts/validate_output.py",
)
S1_VALIDATOR = importlib.util.module_from_spec(VALIDATOR_SPEC)
VALIDATOR_SPEC.loader.exec_module(S1_VALIDATOR)


class S1AtomicRequirementScopeMinimalityTests(unittest.TestCase):
    QUESTION = (
        "갑은 을과 병의 동의 없이 토지를 매각하거나 변경할 수 있는가? "
        "갑은 자신의 지분을 매각할 수 있는가?"
    )
    ERROR = (
        "INITIAL_PLAN scope-expanding generic output descriptor absent from question: "
        "evidence_item_id=E2; requirement_id=E2-R2; descriptor=법적 효력"
    )

    def _input(self, question=None):
        question = question or self.QUESTION
        return {
            "run_id": "scope-minimality-run",
            "original_question": "[질문] " + question,
            "normalized_question": question,
            "mode": "INITIAL_PLAN",
            "constraints": {
                "allowed_query_channels": ["provision_style", "sparse_keywords"],
                "max_requests_per_issue": 3,
                "answer_target_contract": "required",
            },
            "query_history": [],
        }

    def _plan(self, include_scope_expansion=False):
        plan = {
            "schema_version": "1.0",
            "skill_id": "S1",
            "mode": "INITIAL_PLAN",
            "status": "ok",
            "run_id": "scope-minimality-run",
            "answer_targets": [
                {
                    "answer_target_id": "T1",
                    "question_anchor": "갑은 을과 병의 동의 없이 토지를 매각하거나 변경할 수 있는가",
                    "requested_output": "공동소유 토지의 매각 또는 변경에 필요한 법적 요건 및 그 법적 효력",
                    "answer_type": "legal_conclusion",
                },
                {
                    "answer_target_id": "T2",
                    "question_anchor": "갑은 자신의 지분을 매각할 수 있는가",
                    "requested_output": "공유지분의 개별 매각에 대한 법적 허용 여부 및 그 법적 효력",
                    "answer_type": "legal_conclusion",
                },
            ],
            "legal_issues": [
                {
                    "issue_id": "I1",
                    "issue_statement": "공유물 처분 또는 변경의 요건",
                    "decision_question": "공유물 처분에 동의가 필요한가",
                    "importance": "critical",
                },
                {
                    "issue_id": "I2",
                    "issue_statement": "공유지분 처분의 허용 여부",
                    "decision_question": "공유자는 자신의 지분을 처분할 수 있는가",
                    "importance": "critical",
                },
            ],
            "required_evidence_items": [
                {
                    "evidence_item_id": "E1",
                    "issue_id": "I1",
                    "evidence_type": "rule",
                    "description": "공유물 처분과 동의 요건",
                    "critical": True,
                    "completion_criteria": "처분의 동의 요건과 요건 미충족 행위를 확인한다.",
                    "necessity_reason": "동의 없이 처분할 수 있는지 판단하기 위해 필요하다.",
                    "answer_target_ids": ["T1"],
                    "scope_source": "explicit_question",
                    "completion_requirements": [
                        {
                            "requirement_id": "E1-R1",
                            "text": "공유물의 처분 또는 변경에 필요한 법적 요건(동의 등)을 규정하는 조항",
                        },
                        {
                            "requirement_id": "E1-R2",
                            "text": "상기 요건을 충족하지 않은 행위의 법적 효력을 규정하는 조항",
                        },
                    ],
                },
                {
                    "evidence_item_id": "E2",
                    "issue_id": "I2",
                    "evidence_type": "rule",
                    "description": "공유지분 처분의 법적 규율",
                    "critical": True,
                    "completion_criteria": "공유자가 자신의 지분을 처분할 수 있는지 확인한다.",
                    "necessity_reason": "자신의 지분 매각 가능 여부를 판단하기 위해 필요하다.",
                    "answer_target_ids": ["T2"],
                    "scope_source": "explicit_question",
                    "completion_requirements": [
                        {
                            "requirement_id": "E2-R1",
                            "text": "공유지분의 처분(매각 포함)에 관한 법적 허용 여부 및 요건을 규정하는 조항",
                        }
                    ],
                },
            ],
            "retrieval_requests": [
                {
                    "request_id": "RQ1",
                    "issue_id": "I1",
                    "evidence_item_id": "E1",
                    "query_channel": "provision_style",
                    "query_text": "공유물 처분 변경 동의 요건",
                    "query_terms": ["공유물", "처분", "변경", "동의"],
                    "statute_hints": [],
                    "rationale": "공유물 처분과 변경의 동의 요건을 확인한다.",
                },
                {
                    "request_id": "RQ2",
                    "issue_id": "I2",
                    "evidence_item_id": "E2",
                    "query_channel": "provision_style",
                    "query_text": "공유지분 처분 매각 허용 요건",
                    "query_terms": ["공유지분", "처분", "매각", "요건"],
                    "statute_hints": [],
                    "rationale": "공유지분 처분의 허용 여부를 확인한다.",
                },
            ],
        }
        if include_scope_expansion:
            item = plan["required_evidence_items"][1]
            item["description"] = "공유지분 처분의 법적 규율 및 그 법적 효력"
            item["completion_criteria"] = "공유지분 처분의 법적 효력을 확인한다."
            item["completion_requirements"].append(
                {
                    "requirement_id": "E2-R2",
                    "text": "공유지분 처분의 법적 효력을 규정하는 조항",
                }
            )
            request = plan["retrieval_requests"][1]
            request["query_text"] = "공유지분 처분 매각 법적 효력"
            request["query_terms"] = ["공유지분", "처분", "매각", "법적 효력"]
            request["rationale"] = "공유지분 처분의 법적 효력을 확인한다."
        return plan

    def _executor_payload(self):
        return {
            "run_id": "scope-minimality-run",
            "question": "[질문] " + self.QUESTION,
            "normalized_question": self.QUESTION,
            "query_history": [],
        }

    def test_c36_saved_plan_shape_remains_valid_and_c37_shape_is_rejected(self):
        self.assertEqual(S1_VALIDATOR.validate(self._plan(), self._input()), [])
        self.assertEqual(
            S1_VALIDATOR.validate(self._plan(True), self._input()), [self.ERROR]
        )
        validity = self._plan(True)
        validity["required_evidence_items"][1]["completion_requirements"][1]["text"] = (
            "공유지분 처분의 유효성을 규정하는 조항"
        )
        self.assertEqual(
            S1_VALIDATOR.validate(validity, self._input()),
            [self.ERROR.replace("법적 효력", "유효성")],
        )

    def test_independent_condition_and_new_material_components_remain_valid(self):
        self.assertEqual(S1_VALIDATOR.validate(self._plan(), self._input()), [])
        for text in (
            "공유지분 처분을 제3자가 한 경우의 법적 효력을 규정하는 조항",
            "공유지분 처분 후 등기의 법적 효력을 규정하는 조항",
            "공유지분 처분의 예외 사유에 따른 법적 효력을 규정하는 조항",
            "공유지분 처분에 준용되는 별도 규정의 법적 효력을 규정하는 조항",
        ):
            with self.subTest(text=text):
                plan = self._plan(True)
                plan["required_evidence_items"][1]["completion_requirements"][1]["text"] = text
                self.assertEqual(S1_VALIDATOR.validate(plan, self._input()), [])

    def test_explicit_effect_different_object_evidence_and_mixed_text_remain_valid(self):
        explicit = self._plan(True)
        explicit_question = self.QUESTION + " 그 처분의 법적 효력은 무엇인가?"
        explicit["answer_targets"][1]["question_anchor"] = (
            "갑은 자신의 지분을 매각할 수 있는가? 그 처분의 법적 효력은 무엇인가?"
        )
        self.assertEqual(S1_VALIDATOR.validate(explicit, self._input(explicit_question)), [])

        different_object = self._plan(True)
        different_object["required_evidence_items"][1]["completion_requirements"][1]["text"] = (
            "다른 재산 처분의 법적 효력을 규정하는 조항"
        )
        self.assertEqual(S1_VALIDATOR.validate(different_object, self._input()), [])

        different_evidence = self._plan(True)
        different_evidence["required_evidence_items"][1]["completion_requirements"] = [
            different_evidence["required_evidence_items"][1]["completion_requirements"][1]
        ]
        self.assertEqual(S1_VALIDATOR.validate(different_evidence, self._input()), [])

        mixed = self._plan(True)
        mixed["required_evidence_items"][1]["completion_requirements"][1]["text"] += " validity"
        self.assertEqual(S1_VALIDATOR.validate(mixed, self._input()), [])

        requested_output_only = self._plan(True)
        requested_output_only["answer_targets"][1]["requested_output"] += "의 확인"
        self.assertEqual(
            S1_VALIDATOR.validate(requested_output_only, self._input()), [self.ERROR]
        )

        multiple_targets = self._plan(True)
        multiple_targets["required_evidence_items"][1]["answer_target_ids"] = ["T1", "T2"]
        self.assertEqual(S1_VALIDATOR.validate(multiple_targets, self._input()), [])

        nonexplicit_scope = self._plan(True)
        nonexplicit_scope["required_evidence_items"][1]["scope_source"] = "outcome_changing_condition"
        self.assertEqual(S1_VALIDATOR.validate(nonexplicit_scope, self._input()), [])

    def test_executor_retries_once_with_exact_scope_minimality_instruction(self):
        prompts = []
        bad = self._plan(True)
        bad["retrieval_requests"][1]["request_id"] = "raw-request-id"
        responses = iter([json.dumps(bad, ensure_ascii=False), json.dumps(self._plan(), ensure_ascii=False)])

        def generator(prompt):
            prompts.append(prompt)
            return next(responses)

        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills", "test-model", max_attempts=2, generator=generator
        )
        result = executor.execute(
            "legal_issue_and_query_planning", "INITIAL_PLAN", self._executor_payload()
        )

        self.assertEqual(len(result["required_evidence_items"][1]["completion_requirements"]), 1)
        self.assertEqual(len(prompts), 2)
        self.assertIn("INITIAL-PLAN REQUIREMENT-SCOPE-MINIMALITY RETRY", prompts[1])
        self.assertIn("evidence_item_id=E2; requirement_id=E2-R2; descriptor=법적 효력", prompts[1])
        self.assertIn('"request_id":"raw-request-id"', prompts[1])

    def test_repeated_scope_expansion_preserves_two_attempt_bound(self):
        prompts = []
        bad = self._plan(True)
        bad["retrieval_requests"][1]["request_id"] = "raw-request-id"
        bad_json = json.dumps(bad, ensure_ascii=False)

        def generator(prompt):
            prompts.append(prompt)
            return bad_json

        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills", "test-model", max_attempts=2, generator=generator
        )
        with self.assertRaisesRegex(SkillExecutionError, self.ERROR):
            executor.execute(
                "legal_issue_and_query_planning", "INITIAL_PLAN", self._executor_payload()
            )
        self.assertEqual(len(prompts), 2)
        self.assertIn("INITIAL-PLAN REQUIREMENT-SCOPE-MINIMALITY RETRY", prompts[1])
        self.assertIn('"request_id":"raw-request-id"', prompts[1])


if __name__ == "__main__":
    unittest.main()
