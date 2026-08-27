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


def five_public_qa460_shape(roles):
    return raw_output(
        [
            ("T1", "첫 대상의 절차 규칙입니다.", roles[0], "legal_rule", "P1"),
            ("T1", "첫 대상의 일반 효력 규칙입니다.", roles[1], "legal_rule", "P1"),
            ("T1", "첫 대상에는 위 효력이 적용됩니다.", roles[2], "application", "P1"),
            ("T2", "둘째 대상의 추인 규칙입니다.", roles[3], "legal_rule", "P2"),
            ("T2", "둘째 대상에는 소급효가 적용됩니다.", roles[4], "application", "P2"),
        ]
    )


def qa430_hidden_family_exception_output():
    output = raw_output(
        [
            ("T1", "첫 대상의 직접 결론입니다.", "conclusion", "legal_rule", "P1"),
            ("T1", "첫 대상의 공개 조건입니다.", "conclusion", "exception", "P1"),
            ("T2", "둘째 대상의 직접 결론입니다.", "conclusion", "legal_rule", "P2"),
            ("T2", "둘째 대상의 공개 조건입니다.", "conclusion", "exception", "P2"),
            ("T1", "공개 결론에 없는 별도 가족 예외입니다.", "audit", "exception", "P1"),
        ]
    )
    for index in (1, 3, 4):
        output["claims"][index]["applicability"] = "conditional"
    return output


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

    def test_four_public_conclusions_are_valid_under_bounded_contract(self):
        valid = multi_target_application_output(["conclusion"] * 4)
        prompts, diagnostics = [], []

        def generator(prompt):
            prompts.append(prompt)
            return json.dumps(valid, ensure_ascii=False)

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
            len([claim for claim in result["claims"] if claim["public_role"] == "conclusion"]),
            4,
        )
        self.assertEqual(result["answer"].count("\n"), 3)

    def test_qa460_five_public_conclusions_retry_to_four(self):
        invalid = five_public_qa460_shape(["conclusion"] * 5)
        corrected = five_public_qa460_shape(
            ["conclusion", "audit", "conclusion", "conclusion", "conclusion"]
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
        self.assertIn("public_conclusion_count", prompts[1])
        self.assertIn("1 to 4 claims", prompts[1])
        self.assertEqual(
            diagnostics[0]["s3_public_role_contract"]["public_conclusion_count"], 5
        )
        self.assertEqual(
            len([claim for claim in result["claims"] if claim["public_role"] == "conclusion"]),
            4,
        )
        self.assertEqual(result["answer"].count("\n"), 3)

    def test_identical_invalid_public_role_hash_stops_before_extra_attempt(self):
        invalid = five_public_qa460_shape(["conclusion"] * 5)
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

    def test_qa435_duplicate_audit_exception_is_accepted_only_when_visible(self):
        output = raw_output(
            [
                ("T1", "기본 결론입니다. 조건부 예외입니다.", "conclusion", "legal_rule", "P1"),
                ("T1", "조건부 예외입니다.", "audit", "exception", "P1"),
                ("T2", "둘째 대상의 법적 기준입니다.", "conclusion", "legal_rule", "P2"),
                ("T2", "둘째 대상의 보조 근거입니다.", "audit", "legal_rule", "P2"),
            ]
        )
        output["claims"][1]["applicability"] = "conditional"
        prompts, diagnostics = [], []

        def generator(prompt):
            prompts.append(prompt)
            return json.dumps(output, ensure_ascii=False)

        executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture-model", max_attempts=2,
            generator=generator, diagnostic_sink=diagnostics.append,
        )

        result = executor.execute(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", multi_target_payload()
        )

        self.assertEqual(len(prompts), 1)
        self.assertNotIn("s3_public_role_contract", diagnostics[0])
        self.assertEqual(result["claims"][1]["public_role"], "audit")
        self.assertIn("조건부 예외입니다.", result["answer"])

    def test_audit_exception_with_partial_public_target_coverage_fails_closed(self):
        output = raw_output(
            [
                ("T1", "기본 결론입니다. 공동 조건부 예외입니다.", "conclusion", "legal_rule", "P1"),
                ("T1", "공동 조건부 예외입니다.", "audit", "exception", "P1"),
                ("T2", "둘째 대상의 법적 기준입니다.", "conclusion", "legal_rule", "P2"),
            ]
        )
        output["claims"][1]["applicability"] = "conditional"
        output["claims"][1]["answer_target_ids"] = ["T1", "T2"]
        prompts, diagnostics = [], []

        def generator(prompt):
            prompts.append(prompt)
            return json.dumps(output, ensure_ascii=False)

        executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture-model", max_attempts=2,
            generator=generator, diagnostic_sink=diagnostics.append,
        )

        with self.assertRaises(SkillExecutionError) as raised:
            executor.execute(
                "grounded_legal_answer_generation", "GENERATE_ANSWER", multi_target_payload()
            )

        self.assertEqual(len(prompts), 2)
        self.assertEqual(
            diagnostics[0]["s3_public_role_contract"][
                "audit_only_conditional_exception_claim_ids"
            ],
            ["C2"],
        )
        self.assertIn(
            "conditional exception for answered target must be a public conclusion: C2",
            str(raised.exception),
        )

    def test_audit_exception_with_partial_public_provision_coverage_fails_closed(self):
        output = raw_output(
            [
                ("T1", "기본 결론입니다. 복수 근거 조건부 예외입니다.", "conclusion", "legal_rule", "P1"),
                ("T1", "복수 근거 조건부 예외입니다.", "audit", "exception", "P1"),
                ("T2", "둘째 대상의 법적 기준입니다.", "conclusion", "legal_rule", "P2"),
            ]
        )
        output["claims"][1]["applicability"] = "conditional"
        output["claim_citations"].append(
            {
                "claim_id": "draft-2",
                "provision_id": "P2",
                "support_description": "추가 공급 법적 근거",
            }
        )
        prompts, diagnostics = [], []

        def generator(prompt):
            prompts.append(prompt)
            return json.dumps(output, ensure_ascii=False)

        executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture-model", max_attempts=2,
            generator=generator, diagnostic_sink=diagnostics.append,
        )

        with self.assertRaises(SkillExecutionError) as raised:
            executor.execute(
                "grounded_legal_answer_generation", "GENERATE_ANSWER", multi_target_payload()
            )

        self.assertEqual(len(prompts), 2)
        self.assertEqual(
            diagnostics[0]["s3_public_role_contract"][
                "audit_only_conditional_exception_claim_ids"
            ],
            ["C2"],
        )
        self.assertIn(
            "conditional exception for answered target must be a public conclusion: C2",
            str(raised.exception),
        )

    def test_retry_cannot_silently_drop_first_invalid_audit_exception(self):
        initial_invalid = qa430_hidden_family_exception_output()
        silently_dropped = copy.deepcopy(initial_invalid)
        silently_dropped["claims"] = silently_dropped["claims"][:4]
        silently_dropped["claim_citations"] = silently_dropped["claim_citations"][:4]
        prompts, diagnostics = [], []

        def generator(prompt):
            prompts.append(prompt)
            return json.dumps(
                initial_invalid if len(prompts) == 1 else silently_dropped,
                ensure_ascii=False,
            )

        executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture-model", max_attempts=2,
            generator=generator, diagnostic_sink=diagnostics.append,
        )

        with self.assertRaises(SkillExecutionError) as raised:
            executor.execute(
                "grounded_legal_answer_generation", "GENERATE_ANSWER", multi_target_payload()
            )

        expected_obligation = {
            "source_claim_id": "C5",
            "normalized_text": "공개 결론에 없는 별도 가족 예외입니다.",
            "answer_target_ids": ["T1"],
            "provision_ids": ["P1"],
        }
        self.assertEqual(len(prompts), 2)
        self.assertEqual(
            diagnostics[0]["s3_conditional_exception_carry_forward_obligations"],
            [expected_obligation],
        )
        self.assertEqual(
            diagnostics[1]["s3_conditional_exception_carry_forward_failures"],
            [expected_obligation],
        )
        self.assertIn("CONDITIONAL-EXCEPTION CARRY-FORWARD", prompts[1])
        self.assertIn(
            "conditional exception carry-forward obligation is not publicly covered",
            str(raised.exception),
        )

    def test_retry_accepts_consolidated_first_invalid_audit_exception(self):
        initial_invalid = qa430_hidden_family_exception_output()
        consolidated = copy.deepcopy(initial_invalid)
        consolidated["claims"][0]["text"] += " " + consolidated["claims"][4]["text"]
        consolidated["claims"] = consolidated["claims"][:4]
        consolidated["claim_citations"] = consolidated["claim_citations"][:4]
        prompts, diagnostics = [], []

        def generator(prompt):
            prompts.append(prompt)
            return json.dumps(
                initial_invalid if len(prompts) == 1 else consolidated,
                ensure_ascii=False,
            )

        executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture-model", max_attempts=2,
            generator=generator, diagnostic_sink=diagnostics.append,
        )

        result = executor.execute(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", multi_target_payload()
        )

        self.assertEqual(len(prompts), 2)
        self.assertIn(
            "s3_conditional_exception_carry_forward_obligations", diagnostics[0]
        )
        self.assertNotIn(
            "s3_conditional_exception_carry_forward_failures", diagnostics[1]
        )
        self.assertIn("공개 결론에 없는 별도 가족 예외입니다.", result["answer"])
        self.assertEqual(
            len([claim for claim in result["claims"] if claim["public_role"] == "conclusion"]),
            4,
        )

    def test_qa430_hidden_audit_exception_remains_invalid(self):
        invalid = raw_output(
            [
                ("T1", "첫 대상의 직접 결론입니다.", "conclusion", "legal_rule", "P1"),
                ("T1", "첫 대상의 공개 조건입니다.", "conclusion", "exception", "P1"),
                ("T2", "둘째 대상의 직접 결론입니다.", "conclusion", "legal_rule", "P2"),
                ("T2", "둘째 대상의 공개 조건입니다.", "conclusion", "exception", "P2"),
                ("T1", "공개 결론에 없는 별도 가족 예외입니다.", "audit", "exception", "P1"),
            ]
        )
        for index in (1, 3, 4):
            invalid["claims"][index]["applicability"] = "conditional"
        prompts, diagnostics = [], []

        def generator(prompt):
            prompts.append(prompt)
            return json.dumps(invalid, ensure_ascii=False)

        executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture-model", max_attempts=3,
            generator=generator, diagnostic_sink=diagnostics.append,
        )

        with self.assertRaises(SkillExecutionError):
            executor.execute(
                "grounded_legal_answer_generation", "GENERATE_ANSWER", multi_target_payload()
            )

        self.assertEqual(len(prompts), 2)
        self.assertEqual(
            diagnostics[0]["s3_public_role_contract"][
                "audit_only_conditional_exception_claim_ids"
            ],
            ["C5"],
        )
        self.assertIn("not an immutable claim-object template", prompts[1])

    def test_conditional_exception_audit_retries_as_public_conclusion(self):
        invalid = raw_output(
            [
                ("T1", "적용 결론입니다.", "conclusion", "application", "P1"),
                ("T1", "조건부 예외입니다.", "audit", "exception", "P2"),
            ]
        )
        invalid["claims"][0]["text"] = "적용 결론입니다. 조건부 예외입니다."
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
        self.assertIn("make its condition visible", prompts[1])
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
