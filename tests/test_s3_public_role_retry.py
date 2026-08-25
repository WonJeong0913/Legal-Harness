import json
import unittest
from pathlib import Path

from harness.interfaces import SkillExecutionError
from runtime.local_ollama_executor import LocalOllamaSkillExecutor


ROOT = Path(__file__).resolve().parents[1]


def payload():
    return {
        "run_id": "s3-public-role-fixture",
        "normalized_question": "두 법적 결론을 답하라.",
        "legal_issues": [{"issue_id": "I1"}],
        "answer_targets": [
            {"answer_target_id": "T1", "question_anchor": "첫 결론", "requested_output": "첫 결론", "answer_type": "legal_conclusion"},
            {"answer_target_id": "T2", "question_anchor": "둘째 결론", "requested_output": "둘째 결론", "answer_type": "legal_conclusion"},
        ],
        "required_evidence_items": [
            {"evidence_item_id": "E1", "issue_id": "I1", "evidence_type": "rule", "description": "첫 근거", "critical": True, "completion_criteria": "첫 근거", "answer_target_ids": ["T1"]},
            {"evidence_item_id": "E2", "issue_id": "I1", "evidence_type": "rule", "description": "둘째 근거", "critical": True, "completion_criteria": "둘째 근거", "answer_target_ids": ["T2"]},
        ],
        "coverage_assessments": [
            {"evidence_item_id": "E1", "status": "covered"},
            {"evidence_item_id": "E2", "status": "covered"},
        ],
        "accepted_provisions": [
            {"provision_id": "P1", "statute_name": "예시법 제1조", "provision_text": "첫째와 둘째 법적 효과를 정한다.", "supported_evidence_item_ids": ["E1", "E2"]},
        ],
        "answer_mode": "full",
        "answered_target_ids": ["T1", "T2"],
        "deferred_target_ids": [],
        "state_version": 1,
    }


def raw_output(roles):
    claims = []
    citations = []
    for index, (target_id, text, role) in enumerate(
        [
            ("T1", "첫 대상의 첫 법적 결론입니다.", roles[0]),
            ("T1", "첫 대상의 보조 법적 결론입니다.", roles[1]),
            ("T2", "둘째 대상의 첫 법적 결론입니다.", roles[2]),
            ("T2", "둘째 대상의 보조 법적 결론입니다.", roles[3]),
        ],
        start=1,
    ):
        claim_id = "draft-%d" % index
        claims.append({
            "claim_id": claim_id,
            "text": text,
            "claim_type": "legal_rule",
            "applicability": "direct",
            "answer_target_ids": [target_id],
            "citation_required": True,
            "public_role": role,
        })
        citations.append({
            "claim_id": claim_id,
            "provision_id": "P1",
            "support_description": "공급된 법적 근거",
        })
    return {
        "schema_version": "1.0",
        "skill_id": "S3",
        "mode": "GENERATE_ANSWER",
        "status": "ok",
        "claims": claims,
        "claim_citations": citations,
        "assumptions": [],
        "limitations": [],
    }


class S3PublicRoleRetryTests(unittest.TestCase):
    def test_field_level_public_role_diagnostic_is_injected_into_retry(self):
        invalid = raw_output(["conclusion"] * 4)
        corrected = raw_output(["conclusion", "audit", "conclusion", "audit"])
        prompts, diagnostics = [], []

        def generator(prompt):
            prompts.append(prompt)
            return json.dumps(invalid if len(prompts) == 1 else corrected, ensure_ascii=False)

        executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture-model", max_attempts=2,
            generator=generator, diagnostic_sink=diagnostics.append,
        )

        result = executor.execute(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", payload()
        )

        self.assertEqual(len(prompts), 2)
        self.assertIn("PUBLIC-CONCLUSION ROLE REPAIR", prompts[1])
        self.assertIn('"public_conclusion_count":4', prompts[1])
        self.assertIn('"public_line_count":4', prompts[1])
        self.assertIn('"T1":["C1","C2"]', prompts[1])
        self.assertIn('"T2":["C3","C4"]', prompts[1])
        self.assertEqual(diagnostics[0]["s3_public_role_contract"]["public_conclusion_count"], 4)
        self.assertEqual(diagnostics[0]["s3_public_role_contract"]["public_line_count"], 4)
        self.assertEqual(result["answer"].count("\n"), 1)

    def test_identical_invalid_public_role_hash_stops_before_extra_attempt(self):
        invalid = raw_output(["conclusion"] * 4)
        prompts, diagnostics = [], []

        def generator(prompt):
            prompts.append(prompt)
            return json.dumps(invalid, ensure_ascii=False)

        executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture-model", max_attempts=3,
            generator=generator, diagnostic_sink=diagnostics.append,
        )

        with self.assertRaises(SkillExecutionError) as raised:
            executor.execute(
                "grounded_legal_answer_generation", "GENERATE_ANSWER", payload()
            )

        self.assertEqual(len(prompts), 2)
        self.assertEqual(len(diagnostics), 2)
        self.assertEqual(
            diagnostics[-1]["retry_aborted"],
            "duplicate_invalid_s3_public_role_response",
        )
        self.assertEqual(
            diagnostics[-1]["duplicate_invalid_response_sha256"],
            diagnostics[0]["response_sha256"],
        )
        self.assertIn("duplicate invalid S3 public-role response", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
