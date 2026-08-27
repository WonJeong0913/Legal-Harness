import copy
import json
import unittest
from pathlib import Path

from harness.interfaces import SkillExecutionError
from runtime.local_ollama_executor import LocalOllamaSkillExecutor


ROOT = Path(__file__).resolve().parents[1]


def payload(answer_targets, required_evidence_items, accepted_provisions):
    return {
        "run_id": "s3-public-role-fixture",
        "normalized_question": "법적 결론을 답하라.",
        "legal_issues": [{"issue_id": "I1"}],
        "answer_targets": answer_targets,
        "required_evidence_items": required_evidence_items,
        "coverage_assessments": [
            {"evidence_item_id": item["evidence_item_id"], "status": "covered"}
            for item in required_evidence_items
        ],
        "accepted_provisions": accepted_provisions,
        "answer_mode": "full",
        "answered_target_ids": [
            target["answer_target_id"] for target in answer_targets
        ],
        "deferred_target_ids": [],
        "state_version": 1,
    }


def single_target_payload():
    return payload(
        [
            {
                "answer_target_id": "T1",
                "question_anchor": "유일한 결론",
                "requested_output": "유일한 결론",
                "answer_type": "legal_conclusion",
            }
        ],
        [
            {
                "evidence_item_id": "E1",
                "issue_id": "I1",
                "evidence_type": "rule",
                "description": "유일한 핵심 근거",
                "critical": True,
                "completion_criteria": "유일한 핵심 근거",
                "answer_target_ids": ["T1"],
            }
        ],
        [
            {
                "provision_id": "P1",
                "statute_name": "예시법 제1조",
                "provision_text": "첫째 법적 효과를 정한다.",
                "supported_evidence_item_ids": ["E1"],
            },
            {
                "provision_id": "P2",
                "statute_name": "예시법 제2조",
                "provision_text": "둘째 법적 효과를 정한다.",
                "supported_evidence_item_ids": ["E1"],
            },
        ],
    )


def multi_target_payload():
    return payload(
        [
            {
                "answer_target_id": "T1",
                "question_anchor": "첫 결론",
                "requested_output": "첫 결론",
                "answer_type": "legal_conclusion",
            },
            {
                "answer_target_id": "T2",
                "question_anchor": "둘째 결론",
                "requested_output": "둘째 결론",
                "answer_type": "legal_conclusion",
            },
        ],
        [
            {
                "evidence_item_id": "E1",
                "issue_id": "I1",
                "evidence_type": "rule",
                "description": "첫 근거",
                "critical": True,
                "completion_criteria": "첫 근거",
                "answer_target_ids": ["T1"],
            },
            {
                "evidence_item_id": "E2",
                "issue_id": "I1",
                "evidence_type": "rule",
                "description": "둘째 근거",
                "critical": True,
                "completion_criteria": "둘째 근거",
                "answer_target_ids": ["T2"],
            },
        ],
        [
            {
                "provision_id": "P1",
                "statute_name": "예시법 제1조",
                "provision_text": "첫째 법적 효과를 정한다.",
                "supported_evidence_item_ids": ["E1"],
            },
            {
                "provision_id": "P2",
                "statute_name": "예시법 제2조",
                "provision_text": "둘째 법적 효과를 정한다.",
                "supported_evidence_item_ids": ["E2"],
            },
        ],
    )


def raw_output(claim_specs):
    claims = []
    citations = []
    for index, (target_id, text, role, claim_type, provision_id) in enumerate(
        claim_specs, start=1
    ):
        claim_id = "draft-%d" % index
        claims.append(
            {
                "claim_id": claim_id,
                "text": text,
                "claim_type": claim_type,
                "applicability": "direct",
                "answer_target_ids": [target_id],
                "citation_required": True,
                "public_role": role,
            }
        )
        citations.append(
            {
                "claim_id": claim_id,
                "provision_id": provision_id,
                "support_description": "공급된 법적 근거",
            }
        )
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


def composite_invalid_output():
    return raw_output(
        [
            ("T1", "첫째 법률 규칙입니다.", "conclusion", "legal_rule", "P1"),
            ("T1", "둘째 법률 규칙입니다.", "conclusion", "legal_rule", "P2"),
        ]
    )


def multi_target_application_output(roles):
    return raw_output(
        [
            ("T1", "첫 대상의 첫 적용 결론입니다.", roles[0], "application", "P1"),
            ("T1", "첫 대상의 보조 적용 결론입니다.", roles[1], "application", "P1"),
            ("T2", "둘째 대상의 첫 적용 결론입니다.", roles[2], "application", "P2"),
            ("T2", "둘째 대상의 보조 적용 결론입니다.", roles[3], "application", "P2"),
        ]
    )


class S3PublicRoleRetryTests(unittest.TestCase):
    def test_composite_single_target_multi_rule_retries_as_application(self):
        invalid = composite_invalid_output()
        corrected = copy.deepcopy(invalid)
        corrected["claims"][0]["claim_type"] = "application"
        corrected["claims"][0]["text"] = (
            "첫째와 둘째 법률 규칙을 종합하면, 이 결론 대상에는 두 법적 효과가 함께 적용됩니다."
        )
        prompts, diagnostics = [], []

        def generator(prompt):
            prompts.append(prompt)
            return json.dumps(
                invalid if len(prompts) == 1 else corrected, ensure_ascii=False
            )

        executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture-model", max_attempts=2,
            generator=generator, diagnostic_sink=diagnostics.append,
        )

        result = executor.execute(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", single_target_payload()
        )

        self.assertEqual(len(prompts), 2)
        self.assertIn(
            '"missing_application_target_ids":["T1"]', prompts[1]
        )
        self.assertIn("do not merely relabel an abstract legal_rule", prompts[1])
        self.assertEqual(
            diagnostics[0]["s3_public_role_contract"]["missing_application_target_ids"],
            ["T1"],
        )
        self.assertEqual(result["claims"][0]["claim_type"], "application")
        self.assertEqual(
            result["claims"][0]["text"],
            "첫째와 둘째 법률 규칙을 종합하면, 이 결론 대상에는 두 법적 효과가 함께 적용됩니다.",
        )

    def test_duplicate_composite_missing_application_response_fails_closed(self):
        invalid = composite_invalid_output()
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
                "grounded_legal_answer_generation", "GENERATE_ANSWER", single_target_payload()
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
        self.assertIn(
            "legal-conclusion answer target lacks a public application claim: T1",
            str(raised.exception),
        )

    def test_field_level_public_role_diagnostic_is_injected_into_retry(self):
        invalid = multi_target_application_output(["conclusion"] * 4)
        corrected = multi_target_application_output(
            ["conclusion", "audit", "conclusion", "audit"]
        )
        prompts, diagnostics = [], []

        def generator(prompt):
            prompts.append(prompt)
            return json.dumps(
                invalid if len(prompts) == 1 else corrected, ensure_ascii=False
            )

        executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture-model", max_attempts=2,
            generator=generator, diagnostic_sink=diagnostics.append,
        )

        result = executor.execute(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", multi_target_payload()
        )

        self.assertEqual(len(prompts), 2)
        self.assertIn("PUBLIC-CONCLUSION ROLE REPAIR", prompts[1])
        self.assertIn('"public_conclusion_count":4', prompts[1])
        self.assertIn('"public_line_count":4', prompts[1])
        self.assertIn('"T1":["C1","C2"]', prompts[1])
        self.assertIn('"T2":["C3","C4"]', prompts[1])
        self.assertNotIn("missing_application_target_ids", prompts[1])
        self.assertEqual(
            diagnostics[0]["s3_public_role_contract"]["public_conclusion_count"], 4
        )
        self.assertEqual(
            diagnostics[0]["s3_public_role_contract"]["public_line_count"], 4
        )
        self.assertEqual(result["answer"].count("\n"), 1)

    def test_identical_invalid_public_role_hash_stops_before_extra_attempt(self):
        invalid = multi_target_application_output(["conclusion"] * 4)
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
                "grounded_legal_answer_generation", "GENERATE_ANSWER", multi_target_payload()
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

    def test_multi_target_legal_rules_do_not_retry_as_applications(self):
        legal_rules = raw_output(
            [
                ("T1", "첫째 법률 규칙입니다.", "conclusion", "legal_rule", "P1"),
                ("T2", "둘째 법률 규칙입니다.", "conclusion", "legal_rule", "P2"),
            ]
        )
        prompts, diagnostics = [], []

        def generator(prompt):
            prompts.append(prompt)
            return json.dumps(legal_rules, ensure_ascii=False)

        executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture-model", max_attempts=2,
            generator=generator, diagnostic_sink=diagnostics.append,
        )

        result = executor.execute(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", multi_target_payload()
        )

        self.assertEqual(len(prompts), 1)
        self.assertNotIn("s3_public_role_contract", diagnostics[0])
        self.assertEqual(
            [claim["claim_type"] for claim in result["claims"]],
            ["legal_rule", "legal_rule"],
        )

    def test_single_target_single_rule_does_not_retry_as_application(self):
        legal_rule = raw_output(
            [("T1", "유일한 법률 규칙입니다.", "conclusion", "legal_rule", "P1")]
        )
        prompts, diagnostics = [], []

        def generator(prompt):
            prompts.append(prompt)
            return json.dumps(legal_rule, ensure_ascii=False)

        executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture-model", max_attempts=2,
            generator=generator, diagnostic_sink=diagnostics.append,
        )

        result = executor.execute(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", single_target_payload()
        )

        self.assertEqual(len(prompts), 1)
        self.assertNotIn("s3_public_role_contract", diagnostics[0])
        self.assertEqual(result["claims"][0]["claim_type"], "legal_rule")

    def test_conditional_exception_audit_retries_as_public_conclusion(self):
        invalid = raw_output(
            [
                ("T1", "적용 결론입니다.", "conclusion", "application", "P1"),
                ("T1", "조건부 예외입니다.", "audit", "exception", "P2"),
            ]
        )
        invalid["claims"][1]["applicability"] = "conditional"
        corrected = copy.deepcopy(invalid)
        corrected["claims"][1]["public_role"] = "conclusion"
        prompts, diagnostics = [], []

        def generator(prompt):
            prompts.append(prompt)
            return json.dumps(
                invalid if len(prompts) == 1 else corrected, ensure_ascii=False
            )

        executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture-model", max_attempts=2,
            generator=generator, diagnostic_sink=diagnostics.append,
        )

        result = executor.execute(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", single_target_payload()
        )

        self.assertEqual(len(prompts), 2)
        self.assertIn(
            '"audit_only_conditional_exception_claim_ids":["C2"]', prompts[1]
        )
        self.assertIn("make the conditional exception a public conclusion", prompts[1])
        self.assertNotIn("missing_application_target_ids", prompts[1])
        self.assertEqual(
            diagnostics[0]["s3_public_role_contract"][
                "audit_only_conditional_exception_claim_ids"
            ],
            ["C2"],
        )
        self.assertEqual(result["claims"][1]["public_role"], "conclusion")


if __name__ == "__main__":
    unittest.main()
