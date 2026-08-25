import importlib.util
import unittest
from pathlib import Path

from runtime.local_ollama_executor import LocalOllamaSkillExecutor
from harness.interfaces import SkillExecutionError


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "s2_scope_validator",
    ROOT / "skills/provision_coverage_assessment/scripts/validate_output.py",
)
S2_VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(S2_VALIDATOR)


def assessment(evidence_id, provision_id, requirement_id):
    return {
        "evidence_item_id": evidence_id,
        "status": "covered",
        "partial_kind": "not_applicable",
        "linked_provision_ids": [provision_id],
        "rationale": "직접 근거",
        "satisfied_aspects": [requirement_id],
        "missing_aspects": [],
        "legal_status": "covered",
        "applicability_status": "direct",
        "gap_type": "none",
        "criterion_results": [{
            "requirement_id": requirement_id,
            "status": "satisfied",
            "linked_provision_ids": [provision_id],
            "rationale": "직접 근거",
        }],
    }


def covered_output(pairs):
    links, assessments = [], []
    for index, (evidence_id, provision_id, requirement_id) in enumerate(pairs, start=1):
        links.append({
            "link_id": "L%d" % index,
            "evidence_item_id": evidence_id,
            "provision_id": provision_id,
            "relation": "supports",
            "quoted_text": "[FULL_TEXT]",
            "rationale": "직접 근거",
        })
        assessments.append(assessment(evidence_id, provision_id, requirement_id))
    return {
        "schema_version": "1.0", "skill_id": "S2", "mode": "ASSESS_COVERAGE",
        "status": "ok", "run_id": "scope-fixture", "evidence_links": links,
        "coverage_assessments": assessments,
        "missing_evidence_items": [], "evidence_conflicts": [],
    }


class SemanticScopeGuardTests(unittest.TestCase):
    def _range_input(self, root_article="제13조", shared_target=True):
        other_target = "T1" if shared_target else "T2"
        return {
            "schema_version": "1.0", "mode": "ASSESS_COVERAGE", "run_id": "scope-fixture",
            "normalized_question": "적용 범위와 법정 효과를 판단하라.",
            "legal_issues": [{"issue_id": "I1"}],
            "answer_targets": [{"answer_target_id": "T1"}, {"answer_target_id": "T2"}],
            "required_evidence_items": [
                {"evidence_item_id": "E1", "issue_id": "I1", "evidence_type": "rule", "critical": True,
                 "description": "범위 규정", "completion_criteria": "범위 규정", "answer_target_ids": ["T1"],
                 "completion_requirements": [{"requirement_id": "E1-R1", "text": "적용 범위"}]},
                {"evidence_item_id": "E2", "issue_id": "I1", "evidence_type": "rule", "critical": True,
                 "description": "법정 효과", "completion_criteria": "법정 효과", "answer_target_ids": [other_target],
                 "completion_requirements": [{"requirement_id": "E2-R1", "text": "법정 효과"}]},
            ],
            "candidate_provisions": [
                {"provision_id": "C001", "source_provision_id": "root-range",
                 "statute_name": "경계법 제2조", "article_label": "경계법 제2조",
                 "text": "제10조부터 제12조까지의 규정을 적용한다.", "source_snapshot_id": "sha256:range"},
                {"provision_id": "C002", "source_provision_id": "root-effect",
                 "statute_name": "경계법 %s" % root_article, "article_label": "경계법 %s" % root_article,
                 "text": "법정 효과를 정한다.", "source_snapshot_id": "sha256:effect"},
            ], "prior_coverage_assessments": [],
        }

    def test_explicit_same_law_range_blocks_direct_and_satisfied_only_for_shared_target_root_outside_range(self):
        input_data = self._range_input()
        output = covered_output([("E1", "C001", "E1-R1"), ("E2", "C002", "E2-R1")])
        mismatches = S2_VALIDATOR.semantic_scope_mismatches(output, input_data)
        self.assertEqual(mismatches[0]["kind"], "cross_reference_range_excludes_shared_target_root")
        self.assertEqual(mismatches[0]["violations"], ["direct", "satisfied:E1-R1"])
        errors = S2_VALIDATOR.validate(output, input_data)
        self.assertTrue(any("semantic scope mismatch" in error for error in errors))
        self.assertTrue(any("root_provision_id=C002" in error and "range_start=10" in error for error in errors))
        self.assertEqual(S2_VALIDATOR.validate(covered_output([("E1", "C001", "E1-R1"), ("E2", "C002", "E2-R1")]), self._range_input("제11조")), [])
        self.assertEqual(S2_VALIDATOR.semantic_scope_mismatches(output, self._range_input(shared_target=False)), [])

    def test_explicit_special_subtype_blocks_general_entity_but_not_text_absent_or_explicit_scope(self):
        input_data = {
            "schema_version": "1.0", "mode": "ASSESS_COVERAGE", "run_id": "scope-fixture",
            "normalized_question": "일반법인의 구성 요건을 판단하라.", "legal_issues": [{"issue_id": "I1"}],
            "answer_targets": [{"answer_target_id": "T1"}],
            "required_evidence_items": [{
                "evidence_item_id": "E1", "issue_id": "I1", "critical": True,
                "completion_criteria": "구성 요건", "answer_target_ids": ["T1"],
                "completion_requirements": [{"requirement_id": "E1-R1", "text": "일반법인 구성 요건"}],
            }],
            "candidate_provisions": [{
                "provision_id": "C001", "source_provision_id": "root-subtype",
                "statute_name": "일반법 제7조", "article_label": "일반법 제7조",
                "text": "일반법인(유한)은 구성원 수를 갖춘다.", "source_snapshot_id": "sha256:subtype",
            }], "prior_coverage_assessments": [],
        }
        output = covered_output([("E1", "C001", "E1-R1")])
        mismatches = S2_VALIDATOR.semantic_scope_mismatches(output, input_data)
        self.assertEqual(mismatches[0]["kind"], "general_entity_uses_explicit_special_subtype")
        self.assertTrue(any("semantic scope mismatch" in error for error in S2_VALIDATOR.validate(output, input_data)))
        input_data["normalized_question"] = "일반법인(유한)의 구성 요건을 판단하라."
        self.assertEqual(S2_VALIDATOR.semantic_scope_mismatches(output, input_data), [])
        input_data["normalized_question"] = "일반법인의 구성 요건을 판단하라."
        input_data["candidate_provisions"][0]["text"] = "일반법인은 구성원 수를 갖춘다."
        input_data["candidate_provisions"][0]["statute_name"] = "일반법인(유한)법 제7조"
        self.assertEqual(S2_VALIDATOR.semantic_scope_mismatches(output, input_data), [])

    def test_executor_records_scope_mismatch_before_validation_retry(self):
        diagnostics = []
        raw = covered_output([("E1", "C001", "E1-R1"), ("E2", "C002", "E2-R1")])
        raw.pop("run_id")
        raw["evidence_links"] = [
            {key: value for key, value in link.items() if key not in {"link_id", "quoted_text"}}
            for link in raw["evidence_links"]
        ]
        for item in raw["coverage_assessments"]:
            for key in ("partial_kind", "linked_provision_ids", "satisfied_aspects", "missing_aspects"):
                item.pop(key)
        executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture-model", max_attempts=1,
            generator=lambda _prompt: __import__("json").dumps(raw, ensure_ascii=False),
            diagnostic_sink=diagnostics.append,
        )
        payload = self._range_input()
        payload["candidate_provisions"] = [
            {"provision_id": item["source_provision_id"], "statute_name": item["statute_name"], "provision_text": item["text"]}
            for item in payload["candidate_provisions"]
        ]
        with self.assertRaises(SkillExecutionError):
            executor.execute("provision_coverage_assessment", "ASSESS_COVERAGE", payload)
        self.assertEqual(diagnostics[-1]["semantic_scope_mismatches"][0]["kind"], "cross_reference_range_excludes_shared_target_root")


if __name__ == "__main__":
    unittest.main()
