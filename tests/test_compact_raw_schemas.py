import json
import unittest
from pathlib import Path

import jsonschema

from harness.interfaces import SkillExecutionError
from runtime.local_ollama_executor import LocalOllamaSkillExecutor


ROOT = Path(__file__).resolve().parents[1]


class CompactRawSchemaTests(unittest.TestCase):
    def setUp(self):
        self.executor = LocalOllamaSkillExecutor(ROOT / "skills", "test", generator=lambda _: "{}")

    def _schema(self, skill, name):
        return json.loads((ROOT / "skills" / skill / "references" / name).read_text(encoding="utf-8"))

    def test_s2_prompt_raw_schema_accepts_compact_transport_and_normalizes_to_canonical(self):
        skill_input = {
            "schema_version": "1.0", "mode": "ASSESS_COVERAGE", "run_id": "r",
            "normalized_question": "책임은 무엇인가", "legal_issues": [{"issue_id": "I1", "description": "책임"}],
            "answer_targets": [{"answer_target_id": "T1"}],
            "required_evidence_items": [{"evidence_item_id": "E1", "issue_id": "I1", "critical": True, "completion_criteria": "책임 근거", "completion_requirements": [{"requirement_id": "E1-R1", "text": "책임 근거 조문"}]}],
            "candidate_provisions": [{"provision_id": "C001", "source_provision_id": "P1", "text": "책임 조문"}],
            "prior_coverage_assessments": [],
        }
        raw = {
            "schema_version": "1.0", "skill_id": "S2", "mode": "ASSESS_COVERAGE", "status": "ok",
            "evidence_links": [{"evidence_item_id": "E1", "provision_id": "C001", "relation": "supports", "rationale": "직접 근거"}],
            "coverage_assessments": [{"evidence_item_id": "E1", "status": "covered", "rationale": "직접 근거", "legal_status": "covered", "applicability_status": "direct", "gap_type": "none", "criterion_results": [{"requirement_id": "E1-R1", "status": "satisfied", "linked_provision_ids": ["C001"], "rationale": "요건 충족", "direct_entailment": {"regulated_subject_or_act": "matched", "outcome_changing_qualifiers": "matched", "legal_effect": "matched", "procedure_or_remedy_path": "not_applicable", "rationale": "직접 근거"}}]}],
        }
        jsonschema.Draft202012Validator(self._schema("provision_coverage_assessment", "compact_output.schema.json")).validate(raw)
        prompt = self.executor._prompt("provision_coverage_assessment", "ASSESS_COVERAGE", skill_input, "")
        self.assertIn('"title": "S2 compact raw transport"', prompt)
        self.assertNotIn('"link_id"', self.executor._resources["provision_coverage_assessment"]["compact_output_schema"])
        normalized = self.executor._normalize_harness_owned_fields("provision_coverage_assessment", "ASSESS_COVERAGE", skill_input, raw)
        jsonschema.Draft202012Validator(self._schema("provision_coverage_assessment", "output.schema.json")).validate(normalized)
        self.assertEqual(self.executor._validators["provision_coverage_assessment"](normalized, skill_input), [])

    def test_s3_prompt_raw_schema_keeps_public_role_and_question_only_mode(self):
        payload = {
            "run_id": "retry-run-unique-001", "normalized_question": "책임은 무엇인가", "legal_issues": [{"issue_id": "I1", "description": "책임"}],
            "answer_targets": [{"answer_target_id": "T1", "question_anchor": "책임은 무엇인가", "requested_output": "책임", "answer_type": "legal_rule"}],
            "required_evidence_items": [{"evidence_item_id": "E1", "issue_id": "I1", "evidence_type": "rule", "description": "책임 근거", "critical": True, "completion_criteria": "책임 근거", "answer_target_ids": ["T1"]}],
            "coverage_assessments": [{"evidence_item_id": "E1", "status": "covered"}],
            "accepted_provisions": [{"provision_id": "P1", "statute_name": "예시법", "provision_text": "책임 조문", "supported_evidence_item_ids": ["E1"]}],
            "answer_mode": "full", "answered_target_ids": ["T1"], "deferred_target_ids": [], "state_version": 1,
        }
        skill_input = self.executor._build_skill_input("grounded_legal_answer_generation", "GENERATE_ANSWER", payload)
        raw = {
            "schema_version": "1.0", "skill_id": "S3", "mode": "GENERATE_ANSWER", "status": "ok",
            "claims": [{"claim_id": "draft", "text": "책임이 있습니다.", "claim_type": "application", "applicability": "direct", "answer_target_ids": ["T1"], "citation_required": True, "public_role": "conclusion"}],
            "claim_citations": [{"claim_id": "draft", "provision_id": "P1", "support_description": "직접 근거"}],
            "assumptions": [], "limitations": [],
        }
        raw_schema = self._schema("grounded_legal_answer_generation", "compact_output.schema.json")
        jsonschema.Draft202012Validator(raw_schema).validate(raw)
        question_only = {"schema_version": "1.0", "skill_id": "S3", "mode": "GENERATE_BENCHMARK_CANDIDATE", "status": "ok", "answer": "질문만으로 판단할 수 없습니다.", "claims": [], "claim_citations": [], "assumptions": [], "limitations": []}
        jsonschema.Draft202012Validator(raw_schema).validate(question_only)
        prompt = self.executor._prompt("grounded_legal_answer_generation", "GENERATE_ANSWER", skill_input, "")
        self.assertIn('"title": "S3 compact raw transport"', prompt)
        compact_schema_text = self.executor._resources["grounded_legal_answer_generation"]["compact_output_schema"]
        self.assertNotIn('"citation_id"', compact_schema_text)
        self.assertIn('"public_role"', compact_schema_text)
        normalized = self.executor._normalize_harness_owned_fields("grounded_legal_answer_generation", "GENERATE_ANSWER", skill_input, raw)
        jsonschema.Draft202012Validator(self._schema("grounded_legal_answer_generation", "output.schema.json")).validate(normalized)
        self.assertEqual(self.executor._validators["grounded_legal_answer_generation"](normalized, skill_input), [])


    def test_skill_prompts_do_not_reintroduce_canonical_or_stale_publication_rules(self):
        s2_skill = (ROOT / "skills" / "provision_coverage_assessment" / "SKILL.md").read_text(encoding="utf-8")
        s3_skill = (ROOT / "skills" / "grounded_legal_answer_generation" / "SKILL.md").read_text(encoding="utf-8")
        s3_contract = (ROOT / "skills" / "grounded_legal_answer_generation" / "references" / "contract.md").read_text(encoding="utf-8")
        self.assertNotIn("set `quoted_text`", s2_skill)
        self.assertIn("harness restores", s2_skill)
        self.assertNotIn("300--500", s3_skill)
        self.assertNotIn("prioritized claims", s3_skill)
        self.assertIn("public_role", s3_skill)
        self.assertNotIn("prioritized public-claim selection", s3_contract)
        self.assertNotIn("limitations after them", s3_contract)
        self.assertIn("only model-designated conclusion claims", s3_contract)

    def test_compact_validation_repair_replays_raw_not_normalized_output(self):
        def repair_prompt(skill_name, entry_point, payload, raw):
            prompts = []

            def generator(prompt):
                prompts.append(prompt)
                return json.dumps(raw, ensure_ascii=False)

            executor = LocalOllamaSkillExecutor(
                ROOT / "skills", "test", generator=generator, max_attempts=2
            )
            with self.assertRaises(SkillExecutionError):
                executor.execute(skill_name, entry_point, payload)
            self.assertEqual(len(prompts), 2)
            self.assertIn("Previous JSON:", prompts[1])
            return prompts[1].split("Previous JSON: ", 1)[1].split("\n\nINPUT:", 1)[0]

        s2_payload = {
            "run_id": "retry-run-unique-001", "normalized_question": "책임은 무엇인가",
            "legal_issues": [{"issue_id": "I1", "description": "책임"}],
            "answer_targets": [{"answer_target_id": "T1"}],
            "required_evidence_items": [{
                "evidence_item_id": "E1", "issue_id": "I1", "evidence_type": "rule",
                "description": "책임 근거", "critical": True, "completion_criteria": "책임 근거",
                "completion_requirements": [{"requirement_id": "E1-R1", "text": "책임 근거"}],
            }],
            "candidate_provisions": [{
                "provision_id": "P1", "statute_name": "예시법 제1조", "provision_text": "책임 조문",
                "issue_id": "I1", "source_request_id": "RQ1", "retrieval_round": 1,
                "first_stage_score": 1.0, "fusion_rank": 1, "rerank_score": 1.0,
            }],
            "prior_coverage_assessments": [],
        }
        invalid_s2_raw = {
            "schema_version": "1.0", "skill_id": "S2", "mode": "ASSESS_COVERAGE", "status": "ok",
            "evidence_links": [],
            "coverage_assessments": [{
                "evidence_item_id": "E1", "status": "covered", "rationale": "근거",
                "legal_status": "covered", "applicability_status": "direct", "gap_type": "none",
                "criterion_results": [{"requirement_id": "E1-R1", "status": "satisfied", "linked_provision_ids": [], "rationale": "근거"}],
            }],
        }
        s2_repair = repair_prompt(
            "provision_coverage_assessment", "ASSESS_COVERAGE", s2_payload, invalid_s2_raw
        )
        self.assertIn('"evidence_links":[]', s2_repair)
        self.assertNotIn('"link_id"', s2_repair)
        self.assertNotIn('"quoted_text"', s2_repair)
        self.assertNotIn('"missing_evidence_items"', s2_repair)

        s3_payload = {
            "run_id": "retry-run-unique-001", "normalized_question": "책임은 무엇인가",
            "legal_issues": [{"issue_id": "I1", "description": "책임"}],
            "answer_targets": [{"answer_target_id": "T1", "question_anchor": "책임은 무엇인가", "requested_output": "책임", "answer_type": "legal_rule"}],
            "required_evidence_items": [{"evidence_item_id": "E1", "issue_id": "I1", "evidence_type": "rule", "description": "책임 근거", "critical": True, "completion_criteria": "책임 근거", "answer_target_ids": ["T1"]}],
            "coverage_assessments": [{"evidence_item_id": "E1", "status": "covered"}],
            "accepted_provisions": [{"provision_id": "P1", "statute_name": "예시법", "provision_text": "책임 조문", "supported_evidence_item_ids": ["E1"]}],
            "answer_mode": "full", "answered_target_ids": ["T1"], "deferred_target_ids": [], "state_version": 1,
        }
        invalid_s3_raw = {
            "schema_version": "1.0", "skill_id": "S3", "mode": "GENERATE_ANSWER", "status": "ok",
            "claims": [{"claim_id": "draft", "text": "책임이 있습니다.", "claim_type": "application", "applicability": "direct", "answer_target_ids": ["T1"], "citation_required": True, "public_role": "conclusion"}],
            "claim_citations": [], "assumptions": [], "limitations": [],
        }
        s3_repair = repair_prompt(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", s3_payload, invalid_s3_raw
        )
        self.assertIn('"claim_citations":[]', s3_repair)
        self.assertNotIn('"answer"', s3_repair)
        self.assertNotIn('"citation_id"', s3_repair)
        self.assertNotIn('"quoted_text"', s3_repair)
        self.assertNotIn('"answer_marker"', s3_repair)


if __name__ == "__main__":
    unittest.main()
