import unittest
from pathlib import Path
from runtime.local_ollama_executor import LocalOllamaSkillExecutor
ROOT = Path(__file__).resolve().parents[1]
class CompactS2RawOutputTests(unittest.TestCase):
    def test_omitted_harness_fields_normalize_before_real_validator(self):
        executor = LocalOllamaSkillExecutor(ROOT / "skills", "test", generator=lambda _: "{}")
        skill_input = {"schema_version": "1.0", "mode": "ASSESS_COVERAGE", "run_id": "r", "normalized_question": "책임은 무엇인가", "legal_issues": [{"issue_id": "I1", "description": "책임"}], "answer_targets": [{"answer_target_id": "T1"}], "required_evidence_items": [{"evidence_item_id": "E1", "issue_id": "I1", "critical": True, "completion_criteria": "책임 근거", "completion_requirements": [{"requirement_id": "E1-R1", "text": "책임 근거 조문"}]}], "candidate_provisions": [{"provision_id": "C001", "source_provision_id": "P1", "text": "책임 조문"}], "prior_coverage_assessments": []}
        raw = {"schema_version": "1.0", "skill_id": "S2", "mode": "ASSESS_COVERAGE", "status": "ok", "evidence_links": [{"evidence_item_id": "E1", "provision_id": "C001", "relation": "supports", "rationale": "직접 근거"}], "coverage_assessments": [{"evidence_item_id": "E1", "status": "covered", "rationale": "직접 근거", "legal_status": "covered", "applicability_status": "direct", "gap_type": "none", "criterion_results": [{"requirement_id": "E1-R1", "status": "satisfied", "linked_provision_ids": ["C001"], "rationale": "요건 충족"}]}]}
        normalized = executor._normalize_harness_owned_fields("provision_coverage_assessment", "ASSESS_COVERAGE", skill_input, raw)
        self.assertEqual(executor._validators["provision_coverage_assessment"](normalized, skill_input), [])
        self.assertEqual(normalized["evidence_links"][0]["link_id"], "L1")
        self.assertEqual(normalized["evidence_links"][0]["quoted_text"], "[FULL_TEXT]")
        self.assertEqual(normalized["coverage_assessments"][0]["linked_provision_ids"], ["C001"])
        verbose_raw = {
            "schema_version": "1.0", "skill_id": "S2", "mode": "ASSESS_COVERAGE", "status": "ok", "run_id": "legacy",
            "evidence_links": [{"link_id": "L99", "evidence_item_id": "E1", "provision_id": "C001", "relation": "supports", "quoted_text": "책임 조문", "rationale": "직접 근거"}],
            "coverage_assessments": [{"evidence_item_id": "E1", "status": "covered", "partial_kind": "not_applicable", "linked_provision_ids": ["C001"], "rationale": "직접 근거", "legal_status": "covered", "applicability_status": "direct", "gap_type": "none", "satisfied_aspects": ["E1-R1"], "missing_aspects": [], "criterion_results": [{"requirement_id": "E1-R1", "status": "satisfied", "linked_provision_ids": ["C001"], "rationale": "요건 충족"}]}],
            "missing_evidence_items": [], "evidence_conflicts": []
        }
        verbose_normalized = executor._normalize_harness_owned_fields("provision_coverage_assessment", "ASSESS_COVERAGE", skill_input, verbose_raw)
        self.assertEqual(executor._validators["provision_coverage_assessment"](verbose_normalized, skill_input), [])
        self.assertNotEqual(raw, verbose_raw)
        self.assertEqual(executor._adapt_s2(normalized, skill_input), executor._adapt_s2(verbose_normalized, skill_input))
if __name__ == "__main__":
    unittest.main()
