import copy
import json
import unittest
from pathlib import Path

from runtime.local_ollama_executor import LocalOllamaSkillExecutor


ROOT = Path(__file__).resolve().parents[1]
S2 = "provision_coverage_assessment"


def payload():
    return {
        "run_id": "qa_273_2hop_431",
        "normalized_question": "두 계약의 법적 효력을 판단하라.",
        "legal_issues": [{"issue_id": "I1", "description": "계약의 법적 효력"}],
        "answer_targets": [{"answer_target_id": "T1"}],
        "required_evidence_items": [{
            "evidence_item_id": "E1",
            "issue_id": "I1",
            "evidence_type": "rule",
            "description": "궁박과 현저한 불공정의 법적 효과",
            "critical": True,
            "completion_criteria": "법적 효과와 요건을 확인한다.",
            "completion_requirements": [{
                "requirement_id": "E1-R1",
                "text": "궁박과 현저한 불공정의 법적 효과",
            }],
        }],
        "candidate_provisions": [
            {
                "provision_id": "P001",
                "statute_name": "민법 제1조",
                "provision_text": "일반 원칙이다.",
            },
            {
                "provision_id": "P002",
                "statute_name": "민법 제104조",
                "provision_text": (
                    "궁박, 경솔 또는 무경험으로 현저하게 공정을 잃은 "
                    "법률행위는 무효로 한다."
                ),
            },
        ],
    }


def compact_raw(criterion_status, criterion_links):
    return {
        "schema_version": "1.0",
        "skill_id": "S2",
        "mode": "ASSESS_COVERAGE",
        "status": "ok",
        "evidence_links": [{
            "evidence_item_id": "E1",
            "provision_id": "C002",
            "relation": "partially_supports",
            "role": "CORE",
            "rationale": "후보는 일부 요건만 뒷받침한다.",
        }],
        "coverage_assessments": [{
            "evidence_item_id": "E1",
            "rationale": "법적 효과가 요구된 범위와 일치하지 않는다.",
            "legal_status": "partially_covered",
            "applicability_status": "not_assessed",
            "gap_type": "missing_statute",
            "criterion_results": [{
                "requirement_id": "E1-R1",
                "status": criterion_status,
                "linked_provision_ids": criterion_links,
                "rationale": "후보가 일부만 뒷받침한다.",
            }],
        }],
    }


class C27S2PartialCoreRetryTests(unittest.TestCase):
    def setUp(self):
        self.executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture", generator=lambda _: "{}"
        )

    def normalize(self, raw):
        skill_input = self.executor._build_skill_input(
            S2, "ASSESS_COVERAGE", payload()
        )
        return (
            self.executor._normalize_harness_owned_fields(
                S2, "ASSESS_COVERAGE", skill_input, copy.deepcopy(raw)
            ),
            skill_input,
        )

    def test_qa273_bad_partial_tuple_suppresses_core_link_and_fails_closed(self):
        normalized, skill_input = self.normalize(compact_raw("unsatisfied", []))

        self.assertEqual(normalized["evidence_links"], [])
        assessment = normalized["coverage_assessments"][0]
        self.assertEqual(assessment["status"], "partially_covered")
        self.assertEqual(assessment["linked_provision_ids"], [])
        self.assertEqual(assessment["missing_aspects"], ["E1-R1"])
        self.assertEqual(
            self.executor._validators[S2](normalized, skill_input),
            ["partially_covered consistency failure: E1"],
        )

    def test_qa273_good_partial_tuple_preserves_core_link_and_validates(self):
        normalized, skill_input = self.normalize(
            compact_raw("partially_satisfied", ["C002"])
        )

        self.assertEqual(
            [link["provision_id"] for link in normalized["evidence_links"]],
            ["C002"],
        )
        assessment = normalized["coverage_assessments"][0]
        self.assertEqual(assessment["status"], "partially_covered")
        self.assertEqual(assessment["linked_provision_ids"], ["C002"])
        self.assertEqual(assessment["missing_aspects"], ["E1-R1"])
        self.assertEqual(self.executor._validators[S2](normalized, skill_input), [])

    def test_partial_core_retry_prompt_names_the_specific_contract(self):
        bad = compact_raw("unsatisfied", [])
        good = compact_raw("partially_satisfied", ["C002"])
        responses = iter((
            json.dumps(bad, ensure_ascii=False),
            json.dumps(good, ensure_ascii=False),
        ))
        prompts = []
        executor = LocalOllamaSkillExecutor(
            ROOT / "skills",
            "fixture",
            generator=lambda prompt: prompts.append(prompt) or next(responses),
        )

        result = executor.execute(S2, "ASSESS_COVERAGE", payload())

        self.assertEqual(len(prompts), 2)
        self.assertEqual(
            result["coverage_assessments"][0]["status"], "partially_covered"
        )
        self.assertIn("partially_covered consistency failure: E1", prompts[1])
        self.assertIn("PARTIAL-CORE LINK RETRY CONTRACT", prompts[1])
        self.assertIn("partially_satisfied", prompts[1])
        self.assertIn("uncovered/not_assessed/missing_statute", prompts[1])
        self.assertIn('"provision_id":"C002"', prompts[1])


if __name__ == "__main__":
    unittest.main()
