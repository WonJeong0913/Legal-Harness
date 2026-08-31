import copy
import json
import unittest
from pathlib import Path

from harness.interfaces import SkillExecutionError
from runtime.local_ollama_executor import LocalOllamaSkillExecutor


ROOT = Path(__file__).resolve().parents[1]
S2 = "provision_coverage_assessment"


def payload():
    return {
        "run_id": "covered-core-fixture",
        "normalized_question": "처분의 유효 기간을 판단하라.",
        "legal_issues": [{"issue_id": "I1", "description": "처분의 유효 기간"}],
        "answer_targets": [{"answer_target_id": "T1"}],
        "required_evidence_items": [{
            "evidence_item_id": "E1",
            "issue_id": "I1",
            "evidence_type": "rule",
            "description": "처분의 유효 기간과 종료 시점",
            "critical": True,
            "completion_criteria": "처분의 유효 기간과 종료 시점의 법적 근거",
            "completion_requirements": [{
                "requirement_id": "E1-R1",
                "text": "처분의 유효 기간과 종료 시점의 법적 근거",
            }],
        }],
        "candidate_provisions": [{
            "provision_id": "P001",
            "statute_name": "예시법 제1조",
            "provision_text": "처분은 기간의 경과로 소멸되기 전까지 유효하다.",
        }],
    }


def direct_entailment():
    return {
        "regulated_subject_or_act": "matched",
        "outcome_changing_qualifiers": "matched",
        "legal_effect": "matched",
        "procedure_or_remedy_path": "not_applicable",
        "rationale": "공급된 처분과 기간 경과의 효과가 요구사항과 일치한다.",
    }


def covered_raw(*, links, criterion_links):
    return {
        "schema_version": "1.0",
        "skill_id": "S2",
        "mode": "ASSESS_COVERAGE",
        "status": "ok",
        "evidence_links": links,
        "coverage_assessments": [{
            "evidence_item_id": "E1",
            "rationale": "후보가 처분의 유효 기간을 정한다.",
            "legal_status": "covered",
            "applicability_status": "direct",
            "gap_type": "none",
            "criterion_results": [{
                "requirement_id": "E1-R1",
                "status": "satisfied",
                "linked_provision_ids": criterion_links,
                "rationale": "후보가 요구된 기간과 종료 시점을 정한다.",
                "direct_entailment": direct_entailment(),
            }],
        }],
    }


def core_link(*, role="CORE"):
    return {
        "evidence_item_id": "E1",
        "provision_id": "C001",
        "relation": "supports",
        "role": role,
        "rationale": "후보가 공급된 요건을 직접 뒷받침한다.",
    }


def uncovered_raw():
    return {
        "schema_version": "1.0",
        "skill_id": "S2",
        "mode": "ASSESS_COVERAGE",
        "status": "ok",
        "evidence_links": [],
        "coverage_assessments": [{
            "evidence_item_id": "E1",
            "rationale": "직접 CORE 근거를 선택하지 않았다.",
            "legal_status": "uncovered",
            "applicability_status": "not_assessed",
            "gap_type": "missing_statute",
            "criterion_results": [{
                "requirement_id": "E1-R1",
                "status": "unsatisfied",
                "linked_provision_ids": [],
                "rationale": "직접 CORE 근거를 선택하지 않았다.",
            }],
        }],
    }


class C47S2CoveredCoreRetryTests(unittest.TestCase):
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

    def test_unsupported_covered_axis_is_not_deterministically_demoted_or_promoted(self):
        normalized, skill_input = self.normalize(
            covered_raw(links=[], criterion_links=["C001"])
        )

        self.assertEqual(normalized["evidence_links"], [])
        assessment = normalized["coverage_assessments"][0]
        self.assertEqual(assessment["status"], "covered")
        self.assertEqual(assessment["criterion_results"][0]["linked_provision_ids"], ["C001"])
        errors = self.executor._validators[S2](normalized, skill_input)
        self.assertIn("covered consistency failure: E1", errors)
        self.assertIn("criterion may use only accepted CORE provisions: E1", errors)

    def test_auxiliary_link_is_never_promoted_to_core_by_retry_normalization(self):
        normalized, skill_input = self.normalize(
            covered_raw(links=[core_link(role="SUPPLEMENTAL")], criterion_links=["C001"])
        )

        self.assertEqual(normalized["evidence_links"][0]["role"], "SUPPLEMENTAL")
        self.assertEqual(normalized["coverage_assessments"][0]["linked_provision_ids"], [])
        self.assertIn(
            "covered consistency failure: E1",
            self.executor._validators[S2](normalized, skill_input),
        )

    def test_covered_core_retry_accepts_explicit_core_or_conservative_uncovered_replacement(self):
        bad = covered_raw(links=[], criterion_links=["C001"])
        good = covered_raw(links=[core_link()], criterion_links=["C001"])
        prompts, responses = [], iter((
            json.dumps(bad, ensure_ascii=False),
            json.dumps(good, ensure_ascii=False),
        ))
        executor = LocalOllamaSkillExecutor(
            ROOT / "skills",
            "fixture",
            generator=lambda prompt: prompts.append(prompt) or next(responses),
        )

        result = executor.execute(S2, "ASSESS_COVERAGE", payload())

        self.assertEqual(len(prompts), 2)
        self.assertNotIn("COVERED-CORE LINK RETRY CONTRACT", prompts[0])
        self.assertIn("covered consistency failure: E1", prompts[1])
        self.assertIn("criterion may use only accepted CORE provisions: E1", prompts[1])
        self.assertIn("COVERED-CORE LINK RETRY CONTRACT", prompts[1])
        self.assertEqual(result["coverage_assessments"][0]["status"], "covered")
        self.assertEqual(result["coverage_assessments"][0]["linked_provision_ids"], ["P001"])

        fallback_prompts, fallback_responses = [], iter((
            json.dumps(bad, ensure_ascii=False),
            json.dumps(uncovered_raw(), ensure_ascii=False),
        ))
        fallback = LocalOllamaSkillExecutor(
            ROOT / "skills",
            "fixture",
            generator=lambda prompt: fallback_prompts.append(prompt) or next(fallback_responses),
        ).execute(S2, "ASSESS_COVERAGE", payload())
        self.assertEqual(len(fallback_prompts), 2)
        self.assertIn("COVERED-CORE LINK RETRY CONTRACT", fallback_prompts[1])
        self.assertEqual(fallback["coverage_assessments"][0]["status"], "uncovered")
        self.assertEqual(fallback["evidence_links"], [])

    def test_covered_core_retry_keeps_the_two_attempt_fail_closed_bound(self):
        bad = covered_raw(links=[], criterion_links=[])
        prompts, responses = [], iter((
            json.dumps(bad, ensure_ascii=False),
            json.dumps(bad, ensure_ascii=False),
        ))
        executor = LocalOllamaSkillExecutor(
            ROOT / "skills",
            "fixture",
            generator=lambda prompt: prompts.append(prompt) or next(responses),
        )

        with self.assertRaisesRegex(SkillExecutionError, "after 2 attempts"):
            executor.execute(S2, "ASSESS_COVERAGE", payload())
        self.assertEqual(len(prompts), 2)
        self.assertIn("COVERED-CORE LINK RETRY CONTRACT", prompts[1])


if __name__ == "__main__":
    unittest.main()
