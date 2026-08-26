import unittest
from pathlib import Path

from runtime.local_ollama_executor import LocalOllamaSkillExecutor


ROOT = Path(__file__).resolve().parents[1]
S2 = "provision_coverage_assessment"


def skill_input():
    return {
        "schema_version": "1.0",
        "mode": "ASSESS_COVERAGE",
        "run_id": "compact-core-boundary",
        "normalized_question": "일반 법률 요건은 충족되는가",
        "legal_issues": [{"issue_id": "I1", "description": "일반 법률 요건"}],
        "answer_targets": [{"answer_target_id": "T1"}],
        "required_evidence_items": [
            {
                "evidence_item_id": "E1",
                "issue_id": "I1",
                "critical": True,
                "completion_criteria": "일반 법률 요건",
                "completion_requirements": [
                    {"requirement_id": "E1-R1", "text": "일반 법률 요건"}
                ],
            }
        ],
        "candidate_provisions": [
            {"provision_id": "C001", "source_provision_id": "P001", "text": "일반 규정"}
        ],
        "prior_coverage_assessments": [],
    }


def compact_raw(*, legal_status, criterion_status, criterion_links):
    return {
        "schema_version": "1.0",
        "skill_id": "S2",
        "mode": "ASSESS_COVERAGE",
        "status": "ok",
        "evidence_links": [
            {
                "evidence_item_id": "E1",
                "provision_id": "C001",
                "relation": "partially_supports",
                "role": "CORE",
                "rationale": "일반 관련성",
            }
        ],
        "coverage_assessments": [
            {
                "evidence_item_id": "E1",
                "rationale": "일반 판정",
                "legal_status": legal_status,
                "applicability_status": "not_assessed",
                "gap_type": "missing_statute",
                "criterion_results": [
                    {
                        "requirement_id": "E1-R1",
                        "status": criterion_status,
                        "linked_provision_ids": criterion_links,
                        "rationale": "일반 요건 판정",
                    }
                ],
            }
        ],
    }


class CompactS2CoreBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture", generator=lambda _: "{}"
        )

    def normalize(self, raw):
        return self.executor._normalize_harness_owned_fields(
            S2, "ASSESS_COVERAGE", skill_input(), raw
        )

    def test_dangling_core_partial_link_is_not_promoted_into_uncovered_assessment(self):
        normalized = self.normalize(
            compact_raw(
                legal_status="uncovered",
                criterion_status="unsatisfied",
                criterion_links=[],
            )
        )

        self.assertEqual(normalized["evidence_links"], [])
        assessment = normalized["coverage_assessments"][0]
        self.assertEqual(assessment["linked_provision_ids"], [])
        self.assertEqual(assessment["missing_aspects"], ["E1-R1"])
        self.assertEqual(
            [item["evidence_item_id"] for item in normalized["missing_evidence_items"]],
            ["E1"],
        )
        self.assertEqual(self.executor._validators[S2](normalized, skill_input()), [])

    def test_core_partial_link_referenced_by_partially_satisfied_criterion_is_preserved(self):
        normalized = self.normalize(
            compact_raw(
                legal_status="partially_covered",
                criterion_status="partially_satisfied",
                criterion_links=["C001"],
            )
        )

        self.assertEqual(
            [item["provision_id"] for item in normalized["evidence_links"]], ["C001"]
        )
        assessment = normalized["coverage_assessments"][0]
        self.assertEqual(assessment["linked_provision_ids"], ["C001"])
        self.assertEqual(assessment["missing_aspects"], ["E1-R1"])
        self.assertEqual(self.executor._validators[S2](normalized, skill_input()), [])

    def test_legacy_non_atomic_covered_core_link_is_preserved(self):
        legacy_input = skill_input()
        legacy_input["required_evidence_items"][0].pop("completion_requirements")
        raw = compact_raw(
            legal_status="covered",
            criterion_status="satisfied",
            criterion_links=["C001"],
        )
        raw["evidence_links"][0]["relation"] = "supports"
        raw["coverage_assessments"][0].update(
            {"applicability_status": "direct", "gap_type": "none"}
        )
        raw["coverage_assessments"][0].pop("criterion_results")

        normalized = self.executor._normalize_harness_owned_fields(
            S2, "ASSESS_COVERAGE", legacy_input, raw
        )

        self.assertEqual(
            [item["provision_id"] for item in normalized["evidence_links"]], ["C001"]
        )
        self.assertEqual(
            normalized["coverage_assessments"][0]["linked_provision_ids"], ["C001"]
        )
        self.assertEqual(self.executor._validators[S2](normalized, legacy_input), [])


if __name__ == "__main__":
    unittest.main()
