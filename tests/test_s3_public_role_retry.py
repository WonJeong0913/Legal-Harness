import copy
import importlib.util
import json
import unittest
from pathlib import Path

from harness.interfaces import SkillExecutionError
from runtime.local_ollama_executor import LocalOllamaSkillExecutor


ROOT = Path(__file__).resolve().parents[1]
S3_VALIDATOR_SPEC = importlib.util.spec_from_file_location(
    "s3_validator", ROOT / "skills/grounded_legal_answer_generation/scripts/validate_output.py"
)
S3_VALIDATOR = importlib.util.module_from_spec(S3_VALIDATOR_SPEC)
S3_VALIDATOR_SPEC.loader.exec_module(S3_VALIDATOR)


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


def qa430_qualifying_family_exception_output():
    output = qa430_hidden_family_exception_output()
    output["claim_citations"][-1]["provision_id"] = "Q1"
    return output


def qa430_qualifying_payload():
    result = multi_target_payload()
    qualifying = {
        "provision_id": "Q1",
        "statute_name": "예시법 단서",
        "provision_text": "가족 예외가 적용되는 경우를 정한다.",
        "supported_evidence_item_ids": ["E1"],
    }
    result["accepted_provisions"].append(qualifying)
    result["core_accepted_provisions"] = result["accepted_provisions"][:2]
    result["qualifying_provisions"] = [qualifying]
    return result


def qa401_redundant_rule_application_output():
    return raw_output(
        [
            ("T1", "제1조는 이 사안의 법률상 기준을 정합니다.", "conclusion", "legal_rule", "P1"),
            ("T1", "따라서 이 사안에는 제1조의 효과가 직접 적용됩니다.", "conclusion", "application", "P1"),
        ]
    )


def legal_conditions_payload():
    result = single_target_payload()
    result["answer_targets"][0]["answer_type"] = "legal_conditions"
    result["answer_targets"][0]["requested_output"] = "적법한 절차와 방식 및 공판기일 인정 요건"
    return result


def qa86_case_anchor_payload():
    result = single_target_payload()
    result["answer_targets"][0]["question_anchor"] = "업무상 재해 인정 여부"
    result["answer_targets"][0]["requested_output"] = (
        "산재 요양 중 산재보험 의료기관 내 의료사고로 인한 추가 상해의 "
        "업무상 재해 인정 여부"
    )
    return result


def qa86_case_anchor_output(application_text):
    return raw_output(
        [
            (
                "T1",
                "요양 관련 사고는 업무상 사고로 본다는 법률 규칙입니다.",
                "conclusion",
                "legal_rule",
                "P1",
            ),
            ("T1", application_text, "conclusion", "application", "P1"),
        ]
    )


def qa0_output_descriptor_payload():
    result = single_target_payload()
    result["answer_targets"][0]["question_anchor"] = "보험사의 조치"
    result["answer_targets"][0]["requested_output"] = (
        "보험사가 보험료 미납 시 취할 수 있는 법적 조치의 종류와 요건"
    )
    return result


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

    def test_qa460_five_public_conclusions_demote_redundant_rules(self):
        invalid = five_public_qa460_shape(["conclusion"] * 5)
        prompts, diagnostics = [], []

        def generator(prompt):
            prompts.append(prompt)
            return json.dumps(invalid, ensure_ascii=False)

        executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture-model", max_attempts=2,
            generator=generator, diagnostic_sink=diagnostics.append,
        )

        result = executor.execute(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", multi_target_payload()
        )

        self.assertEqual(len(prompts), 1)
        self.assertEqual(
            [claim["public_role"] for claim in result["claims"]],
            ["audit", "audit", "conclusion", "audit", "conclusion"],
        )
        self.assertEqual(result["answer"].count("\n"), 1)
        self.assertEqual(
            [repair["claim_id"] for repair in diagnostics[0]["deterministic_repairs"]],
            ["C1", "C2", "C4"],
        )

    def test_identical_invalid_public_role_hash_stops_before_extra_attempt(self):
        invalid = five_public_qa460_shape(["conclusion"] * 5)
        for index in (0, 1, 3):
            invalid["claims"][index]["claim_type"] = "procedure"
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

    def test_qa430_retry_allows_only_frozen_qualifying_exception_citation(self):
        initial_invalid = qa430_qualifying_family_exception_output()
        consolidated = copy.deepcopy(initial_invalid)
        consolidated["claims"][0]["text"] += " " + consolidated["claims"][4]["text"]
        consolidated["claims"] = consolidated["claims"][:4]
        qualifying_citation = copy.deepcopy(consolidated["claim_citations"][4])
        qualifying_citation["claim_id"] = "draft-1"
        consolidated["claim_citations"] = (
            consolidated["claim_citations"][:4] + [qualifying_citation]
        )
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
            "grounded_legal_answer_generation",
            "GENERATE_ANSWER",
            qa430_qualifying_payload(),
        )

        self.assertEqual(len(prompts), 2)
        self.assertIn("CONDITIONAL-EXCEPTION CARRY-FORWARD", prompts[1])
        self.assertNotIn(
            "_harness_c32_conditional_exception_carry_forward_obligations",
            prompts[1],
        )
        self.assertNotIn(
            "_harness_c32_conditional_exception_carry_forward_obligations",
            json.dumps(diagnostics, ensure_ascii=False),
        )
        self.assertEqual(
            diagnostics[0]["s3_conditional_exception_carry_forward_obligations"],
            [
                {
                    "source_claim_id": "C5",
                    "normalized_text": "공개 결론에 없는 별도 가족 예외입니다.",
                    "answer_target_ids": ["T1"],
                    "provision_ids": ["Q1"],
                }
            ],
        )
        self.assertNotIn(
            "s3_conditional_exception_carry_forward_failures", diagnostics[1]
        )
        self.assertIn("Q1", [citation["provision_id"] for citation in result["claim_citations"]])

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

    def test_qa401_redundant_public_rule_is_demoted_without_retry(self):
        output = qa401_redundant_rule_application_output()
        prompts, diagnostics = [], []

        def generator(prompt):
            prompts.append(prompt)
            return json.dumps(output, ensure_ascii=False)

        executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture-model", max_attempts=2,
            generator=generator, diagnostic_sink=diagnostics.append,
        )

        result = executor.execute(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", single_target_payload()
        )

        self.assertEqual(len(prompts), 1)
        self.assertEqual(
            [claim["public_role"] for claim in result["claims"]],
            ["audit", "conclusion"],
        )
        self.assertEqual(
            result["answer"], "따라서 이 사안에는 제1조의 효과가 직접 적용됩니다.[CT2]"
        )
        self.assertEqual(
            [citation["provision_id"] for citation in result["claim_citations"] if citation["claim_id"] == "C1"],
            ["P1"],
        )
        self.assertEqual(
            diagnostics[0]["deterministic_repairs"],
            [
                {
                    "kind": "s3_redundant_public_legal_rule_demoted",
                    "claim_id": "C1",
                    "matched_application_claim_id": "C2",
                    "answer_target_ids": ["T1"],
                    "provision_ids": ["P1"],
                }
            ],
        )

    def test_legal_conditions_demote_application_and_rebuild_answer(self):
        output = qa401_redundant_rule_application_output()
        prompts, diagnostics = [], []

        def generator(prompt):
            prompts.append(prompt)
            return json.dumps(output, ensure_ascii=False)

        executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture-model", max_attempts=2,
            generator=generator, diagnostic_sink=diagnostics.append,
        )
        result = executor.execute(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", legal_conditions_payload()
        )

        self.assertEqual(len(prompts), 1)
        self.assertEqual(
            [claim["public_role"] for claim in result["claims"]],
            ["conclusion", "audit"],
        )
        self.assertEqual(result["answer"], "제1조는 이 사안의 법률상 기준을 정합니다.[CT1]")
        self.assertEqual(
            diagnostics[0]["deterministic_repairs"],
            [{
                "kind": "s3_redundant_public_application_demoted_for_legal_conditions",
                "claim_id": "C2",
                "matched_legal_rule_claim_id": "C1",
                "answer_target_ids": ["T1"],
                "provision_ids": ["P1"],
            }],
        )
        repeated, repairs = executor._repair_s3_redundant_public_rule_application_projection(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", result,
            executor._build_skill_input(
                "grounded_legal_answer_generation", "GENERATE_ANSWER", legal_conditions_payload()
            ),
        )
        self.assertIs(repeated, result)
        self.assertEqual(repairs, [])

    def test_legal_conditions_multiple_pairs_demote_only_applications(self):
        output = raw_output([
            ("T1", "첫째 요건 규칙입니다.", "conclusion", "legal_rule", "P1"),
            ("T1", "첫째 요건 적용입니다.", "conclusion", "application", "P1"),
            ("T2", "둘째 요건 규칙입니다.", "conclusion", "legal_rule", "P2"),
            ("T2", "둘째 요건 적용입니다.", "conclusion", "application", "P2"),
        ])
        data = multi_target_payload()
        for target in data["answer_targets"]:
            target["answer_type"] = "legal_conditions"
        executor = LocalOllamaSkillExecutor(ROOT / "skills", "fixture-model")
        skill_input = executor._build_skill_input(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", data
        )
        repaired, repairs = executor._repair_s3_redundant_public_rule_application_projection(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", output, skill_input
        )
        self.assertEqual(
            [claim["public_role"] for claim in repaired["claims"]],
            ["conclusion", "audit", "conclusion", "audit"],
        )
        self.assertEqual([repair["claim_id"] for repair in repairs], ["draft-2", "draft-4"])

    def test_unknown_or_mixed_answer_types_keep_c33_rule_demotion(self):
        executor = LocalOllamaSkillExecutor(ROOT / "skills", "fixture-model")
        unknown = legal_conditions_payload()
        unknown["answer_targets"][0]["answer_type"] = "unknown"
        mixed = multi_target_payload()
        mixed["answer_targets"][0]["answer_type"] = "legal_conditions"
        outputs = [qa401_redundant_rule_application_output(), qa401_redundant_rule_application_output()]
        for claim in outputs[1]["claims"]:
            claim["answer_target_ids"] = ["T1", "T2"]
        for data, output in zip((unknown, mixed), outputs):
            with self.subTest(answer_types=[target["answer_type"] for target in data["answer_targets"]]):
                skill_input = executor._build_skill_input(
                    "grounded_legal_answer_generation", "GENERATE_ANSWER", data
                )
                repaired, repairs = executor._repair_s3_redundant_public_rule_application_projection(
                    "grounded_legal_answer_generation", "GENERATE_ANSWER", output, skill_input
                )
                self.assertEqual(
                    [claim["public_role"] for claim in repaired["claims"]],
                    ["audit", "conclusion"],
                )
                self.assertEqual(repairs[0]["kind"], "s3_redundant_public_legal_rule_demoted")

    def test_case_anchor_retry_preserves_requested_fact_before_rule_demotion(self):
        invalid = qa86_case_anchor_output("이 사안에는 위 법적 효과가 직접 적용됩니다.")
        corrected = qa86_case_anchor_output(
            "이 의료사고로 인한 추가 상해에는 위 법적 효과가 직접 적용됩니다."
        )
        prompts, diagnostics = [], []

        def generator(prompt):
            prompts.append(prompt)
            return json.dumps(invalid if len(prompts) == 1 else corrected, ensure_ascii=False)

        executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture-model", max_attempts=3,
            generator=generator, diagnostic_sink=diagnostics.append,
        )
        result = executor.execute(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", qa86_case_anchor_payload()
        )

        self.assertEqual(len(prompts), 2)
        self.assertIn(
            "public application lacks requested-output case-fact anchors before redundant-rule demotion",
            prompts[1],
        )
        self.assertIn("missing_anchors=추가 상해", prompts[1])
        self.assertIn("CASE-FACT APPLICATION ANCHOR RETRY", prompts[1])
        self.assertNotIn(
            "_harness_c32_conditional_exception_carry_forward_obligations", prompts[1]
        )
        self.assertIn("s3_public_role_contract", diagnostics[0])
        self.assertEqual(
            [claim["public_role"] for claim in result["claims"]],
            ["audit", "conclusion"],
        )
        self.assertEqual(
            result["answer"],
            "이 의료사고로 인한 추가 상해에는 위 법적 효과가 직접 적용됩니다.[CT2]",
        )

    def test_duplicate_case_anchor_failure_stops_with_existing_guard(self):
        invalid = qa86_case_anchor_output("이 사안에는 위 법적 효과가 직접 적용됩니다.")
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
                "grounded_legal_answer_generation", "GENERATE_ANSWER", qa86_case_anchor_payload()
            )
        self.assertEqual(len(prompts), 2)
        self.assertEqual(
            diagnostics[-1]["retry_aborted"], "duplicate_invalid_s3_public_role_response"
        )

    def test_output_descriptor_head_does_not_block_c33_rule_demotion(self):
        output = raw_output([
            ("T1", "보험료 미납에는 최고 후 해지 규칙이 적용됩니다.", "conclusion", "legal_rule", "P1"),
            ("T1", "보험사는 최고 후 보험계약을 해지할 수 있습니다.", "conclusion", "application", "P1"),
        ])
        prompts = []
        executor = LocalOllamaSkillExecutor(
            ROOT / "skills", "fixture-model", max_attempts=2,
            generator=lambda prompt: prompts.append(prompt) or json.dumps(output, ensure_ascii=False),
        )
        result = executor.execute(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", qa0_output_descriptor_payload()
        )
        self.assertEqual(len(prompts), 1)
        self.assertEqual([claim["public_role"] for claim in result["claims"]], ["audit", "conclusion"])
        self.assertEqual(result["answer"], "보험사는 최고 후 보험계약을 해지할 수 있습니다.[CT2]")

    def test_case_fact_anchor_keeps_concrete_facts_and_excludes_output_descriptors(self):
        self.assertEqual(
            S3_VALIDATOR._korean_case_fact_anchor_phrases(
                "보험사가 보험료 미납 시 취할 수 있는 법적 조치의 종류와 요건"
            ),
            set(),
        )
        self.assertEqual(
            S3_VALIDATOR._korean_case_fact_anchor_phrases(
                "의료사고로 인한 추가 상해의 업무상 재해 인정 여부"
            ),
            {"추가 상해"},
        )
        self.assertEqual(
            S3_VALIDATOR._korean_case_fact_anchor_phrases("개별 매각의 적법 여부"),
            {"개별 매각"},
        )

    def test_qa460_multiple_redundant_rules_are_demoted_and_answer_rebuilt(self):
        output = five_public_qa460_shape(["conclusion"] * 5)
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
        self.assertEqual(
            [claim["public_role"] for claim in result["claims"]],
            ["audit", "audit", "conclusion", "audit", "conclusion"],
        )
        self.assertEqual(
            result["answer"],
            "첫 대상에는 위 효력이 적용됩니다.[CT3]\n둘째 대상에는 소급효가 적용됩니다.[CT5]",
        )
        self.assertEqual(
            [repair["claim_id"] for repair in diagnostics[0]["deterministic_repairs"]],
            ["C1", "C2", "C4"],
        )

    def test_redundant_rule_projection_fails_closed_outside_exact_core_match(self):
        executor = LocalOllamaSkillExecutor(ROOT / "skills", "fixture-model")
        input_data = executor._build_skill_input(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", multi_target_payload()
        )
        mismatched_targets = raw_output(
            [
                ("T1", "첫 대상 규칙입니다.", "conclusion", "legal_rule", "P1"),
                ("T2", "둘째 대상 적용입니다.", "conclusion", "application", "P1"),
            ]
        )
        mismatched_provisions = raw_output(
            [
                ("T1", "첫 대상 규칙입니다.", "conclusion", "legal_rule", "P1"),
                ("T1", "첫 대상 적용입니다.", "conclusion", "application", "P2"),
            ]
        )
        empty_citations = qa401_redundant_rule_application_output()
        empty_citations["claim_citations"] = []
        non_core = qa401_redundant_rule_application_output()
        for citation in non_core["claim_citations"]:
            citation["provision_id"] = "Q1"
        exception = qa401_redundant_rule_application_output()
        exception["claims"][0]["claim_type"] = "exception"
        qualifying_input = executor._build_skill_input(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", qa430_qualifying_payload()
        )
        candidate_input = copy.deepcopy(input_data)
        candidate_input["mode"] = "GENERATE_BENCHMARK_CANDIDATE"
        legacy_input = copy.deepcopy(input_data)
        legacy_input["generation_constraints"]["public_conclusion_contract"] = "legacy"
        cases = [
            (mismatched_targets, "GENERATE_ANSWER", input_data),
            (mismatched_provisions, "GENERATE_ANSWER", input_data),
            (empty_citations, "GENERATE_ANSWER", input_data),
            (non_core, "GENERATE_ANSWER", qualifying_input),
            (exception, "GENERATE_ANSWER", input_data),
            (qa401_redundant_rule_application_output(), "GENERATE_BENCHMARK_CANDIDATE", candidate_input),
            (qa401_redundant_rule_application_output(), "GENERATE_ANSWER", legacy_input),
        ]

        for output, entry_point, skill_input in cases:
            with self.subTest(entry_point=entry_point, output=output):
                repaired, repairs = (
                    executor._repair_s3_redundant_public_rule_application_projection(
                        "grounded_legal_answer_generation", entry_point, output, skill_input
                    )
                )
                self.assertIs(repaired, output)
                self.assertEqual(repairs, [])
                self.assertEqual(
                    output["claims"][0]["public_role"], "conclusion"
                )


if __name__ == "__main__":
    unittest.main()
