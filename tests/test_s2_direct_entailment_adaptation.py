import copy
import unittest
from pathlib import Path

from runtime.local_ollama_executor import LocalOllamaSkillExecutor


ROOT = Path(__file__).resolve().parents[1]


class S2DirectEntailmentAdaptationTests(unittest.TestCase):
    def setUp(self):
        self.executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture-model", generator=lambda _: "{}"
        )

    @staticmethod
    def _skill_input():
        return {
            "schema_version": "1.0",
            "mode": "ASSESS_COVERAGE",
            "run_id": "s2-adapt-fixture",
            "normalized_question": "책임의 법적 근거는 무엇인가",
            "legal_issues": [{"issue_id": "I1", "description": "책임"}],
            "answer_targets": [{"answer_target_id": "T1"}],
            "required_evidence_items": [
                {
                    "evidence_item_id": "E1",
                    "issue_id": "I1",
                    "critical": True,
                    "completion_criteria": "책임 근거",
                    "completion_requirements": [
                        {"requirement_id": "E1-R1", "text": "책임 근거 조문"}
                    ],
                }
            ],
            "candidate_provisions": [
                {
                    "provision_id": "C001",
                    "source_provision_id": "P1",
                    "text": "책임의 법적 근거를 정한다.",
                }
            ],
            "prior_coverage_assessments": [],
        }

    @staticmethod
    def _valid_audit():
        return {
            "regulated_subject_or_act": "matched",
            "outcome_changing_qualifiers": "matched",
            "legal_effect": "matched",
            "procedure_or_remedy_path": "not_applicable",
            "rationale": "공급된 책임 근거와 직접 일치한다.",
        }

    def _raw_direct_output(self):
        return {
            "schema_version": "1.0",
            "skill_id": "S2",
            "mode": "ASSESS_COVERAGE",
            "status": "ok",
            "evidence_links": [
                {
                    "evidence_item_id": "E1",
                    "provision_id": "C001",
                    "relation": "supports",
                    "rationale": "직접 근거",
                }
            ],
            "coverage_assessments": [
                {
                    "evidence_item_id": "E1",
                    "status": "covered",
                    "rationale": "직접 근거",
                    "legal_status": "covered",
                    "applicability_status": "direct",
                    "gap_type": "none",
                    "criterion_results": [
                        {
                            "requirement_id": "E1-R1",
                            "status": "satisfied",
                            "linked_provision_ids": ["C001"],
                            "rationale": "요건 충족",
                            "direct_entailment": self._valid_audit(),
                        }
                    ],
                }
            ],
        }

    def _canonical_direct_output(self):
        skill_input = self._skill_input()
        canonical = self.executor._normalize_harness_owned_fields(
            "provision_coverage_assessment",
            "ASSESS_COVERAGE",
            skill_input,
            self._raw_direct_output(),
        )
        self.assertEqual(
            self.executor._validators["provision_coverage_assessment"](
                canonical, skill_input
            ),
            [],
        )
        return canonical, skill_input

    def test_raw_to_canonical_valid_direct_audit_is_deep_copied_into_adapted_state(self):
        canonical, skill_input = self._canonical_direct_output()

        adapted = self.executor._adapt_s2(canonical, skill_input)
        canonical_audit = canonical["coverage_assessments"][0]["criterion_results"][0][
            "direct_entailment"
        ]
        adapted_audit = adapted["coverage_assessments"][0]["criterion_results"][0][
            "direct_entailment"
        ]

        self.assertEqual(adapted_audit, self._valid_audit())
        self.assertIsNot(adapted_audit, canonical_audit)
        canonical_audit["rationale"] = "원본 변경"
        self.assertEqual(adapted_audit["rationale"], self._valid_audit()["rationale"])

    def test_adapter_omits_malformed_or_non_direct_audit(self):
        malformed, skill_input = self._canonical_direct_output()
        malformed["coverage_assessments"][0]["criterion_results"][0][
            "direct_entailment"
        ]["legal_effect"] = "invalid"

        malformed_adapted = self.executor._adapt_s2(malformed, skill_input)
        self.assertNotIn(
            "direct_entailment",
            malformed_adapted["coverage_assessments"][0]["criterion_results"][0],
        )

        non_direct, skill_input = self._canonical_direct_output()
        non_direct["coverage_assessments"][0]["applicability_status"] = "conditional"
        non_direct["coverage_assessments"][0]["criterion_results"][0][
            "status"
        ] = "partially_satisfied"

        non_direct_adapted = self.executor._adapt_s2(non_direct, skill_input)
        self.assertNotIn(
            "direct_entailment",
            non_direct_adapted["coverage_assessments"][0]["criterion_results"][0],
        )


if __name__ == "__main__":
    unittest.main()
