import importlib.util
import json
import unittest
from pathlib import Path

from harness.interfaces import SkillExecutionError
from runtime.local_ollama_executor import LocalOllamaSkillExecutor


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "s1_initial_effect_neutrality_validator",
    PROJECT_ROOT / "skills/legal_issue_and_query_planning/scripts/validate_output.py",
)
S1_VALIDATOR = importlib.util.module_from_spec(VALIDATOR_SPEC)
VALIDATOR_SPEC.loader.exec_module(S1_VALIDATOR)


class S1InitialEffectNeutralityTests(unittest.TestCase):
    def _input(self, question="계약의 법적 효력은 무엇인가?"):
        return {
            "run_id": "run-c29b",
            "original_question": "[질문] " + question,
            "normalized_question": question,
            "mode": "INITIAL_PLAN",
            "constraints": {
                "allowed_query_channels": [
                    "provision_style",
                    "sparse_keywords",
                    "statute_aware",
                ],
                "max_requests_per_issue": 3,
                "answer_target_contract": "required",
            },
            "query_history": [],
        }

    def _output(self, effect, question="계약의 법적 효력은 무엇인가?"):
        return {
            "schema_version": "1.0",
            "skill_id": "S1",
            "mode": "INITIAL_PLAN",
            "status": "ok",
            "run_id": "run-c29b",
            "legal_issues": [
                {
                    "issue_id": "I1",
                    "issue_statement": "계약의 %s 여부" % effect,
                    "decision_question": "계약에 %s가 적용되는가?" % effect,
                }
            ],
            "answer_targets": [
                {
                    "answer_target_id": "T1",
                    "question_anchor": question,
                    "requested_output": "적용 법률상 효력",
                    "answer_type": "legal_effect",
                }
            ],
            "required_evidence_items": [
                {
                    "evidence_item_id": "E1",
                    "issue_id": "I1",
                    "evidence_type": "statutory_rule",
                    "description": "%s에 관한 적용 법령" % effect,
                    "critical": True,
                    "completion_criteria": "%s의 법정 요건과 효과 확인" % effect,
                    "necessity_reason": "%s 결론을 판단하기 위해 필요" % effect,
                    "answer_target_ids": ["T1"],
                    "scope_source": "explicit_question",
                    "completion_requirements": [
                        {
                            "requirement_id": "CR1",
                            "text": "%s의 적용 법정 효과를 정하는 규정" % effect,
                        }
                    ],
                }
            ],
            "retrieval_requests": [
                {
                    "request_id": "RQ1",
                    "issue_id": "I1",
                    "evidence_item_id": "E1",
                    "query_channel": "provision_style",
                    "query_text": "계약 %s 적용 법령" % effect,
                    "rationale": "%s의 법정 효과 확인" % effect,
                    "query_terms": [effect],
                    "statute_hints": ["계약 %s" % effect],
                }
            ],
        }

    def _executor_payload(self):
        return {
            "run_id": "run-c29b",
            "question": "[질문] 계약의 법적 효력은 무엇인가?",
            "normalized_question": "계약의 법적 효력은 무엇인가?",
            "query_history": [],
        }

    def test_validator_rejects_qa273_style_effect_from_background_not_question(self):
        inp = self._input()
        inp["original_question"] = (
            "[배경 시나리오] 상대방은 계약의 취소를 주장한다. "
            "[질문] 계약의 법적 효력은 무엇인가?"
        )
        errors = S1_VALIDATOR.validate(self._output("cancellation"), inp)
        self.assertEqual(
            errors,
            [
                "INITIAL_PLAN presupposes specific legal effect absent from question: "
                "cancellation"
            ],
        )

    def test_validator_allows_neutral_validity_terms(self):
        neutral_output = self._output("applicable statutory legal effect")
        neutral_output["legal_issues"][0]["issue_statement"] = "계약의 법적 효력"
        neutral_output["legal_issues"][0]["decision_question"] = "계약의 legal validity는 무엇인가?"
        neutral_output["required_evidence_items"][0]["completion_criteria"] = (
            "validity와 법적 효력에 관한 적용 법령 확인"
        )
        self.assertEqual(S1_VALIDATOR.validate(neutral_output, self._input()), [])

    def test_validator_allows_same_effect_explicitly_named_in_question(self):
        question = "계약의 rescission 효과는 무엇인가?"
        self.assertEqual(
            S1_VALIDATOR.validate(
                self._output("rescission", question), self._input(question)
            ),
            [],
        )

    def test_executor_retries_once_with_narrow_effect_instruction_and_accepts_neutral_plan(self):
        prompts = []
        bad_output = self._output("cancellation")
        bad_output["retrieval_requests"][0]["request_id"] = "raw-request-id"
        responses = iter(
            [
                json.dumps(bad_output, ensure_ascii=False),
                json.dumps(
                    self._output("applicable statutory legal effect"),
                    ensure_ascii=False,
                ),
            ]
        )

        def generator(prompt):
            prompts.append(prompt)
            return next(responses)

        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills", "test-model", max_attempts=2, generator=generator
        )
        result = executor.execute(
            "legal_issue_and_query_planning", "INITIAL_PLAN", self._executor_payload()
        )

        self.assertEqual(
            result["legal_issues"][0]["description"],
            "계약의 applicable statutory legal effect 여부",
        )
        self.assertEqual(len(prompts), 2)
        self.assertIn("INITIAL-PLAN EFFECT-NEUTRALITY RETRY", prompts[1])
        self.assertIn("Replace only each unsupported specific legal effect term", prompts[1])
        self.assertIn("Do not substitute another outcome, expand scope, add a conclusion", prompts[1])
        self.assertIn('"request_id":"raw-request-id"', prompts[1])

    def test_executor_repeated_bad_effect_raises_and_preserves_original_previous_json(self):
        prompts = []
        bad_output = self._output("cancellation")
        bad_output["retrieval_requests"][0]["request_id"] = "raw-request-id"
        bad_json = json.dumps(bad_output, ensure_ascii=False)

        def generator(prompt):
            prompts.append(prompt)
            return bad_json

        executor = LocalOllamaSkillExecutor(
            PROJECT_ROOT / "skills", "test-model", max_attempts=2, generator=generator
        )
        with self.assertRaisesRegex(
            SkillExecutionError,
            "INITIAL_PLAN presupposes specific legal effect absent from question: cancellation",
        ):
            executor.execute(
                "legal_issue_and_query_planning", "INITIAL_PLAN", self._executor_payload()
            )

        self.assertEqual(len(prompts), 2)
        self.assertIn("INITIAL-PLAN EFFECT-NEUTRALITY RETRY", prompts[1])
        self.assertIn('"request_id":"raw-request-id"', prompts[1])
        self.assertIn('"rationale":"cancellation의 법정 효과 확인"', prompts[1])


if __name__ == "__main__":
    unittest.main()
