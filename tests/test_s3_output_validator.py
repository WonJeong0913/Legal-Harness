import importlib.util
import unittest
from pathlib import Path


def _load_validator():
    path = (
        Path(__file__).resolve().parents[1]
        / "skills"
        / "grounded_legal_answer_generation"
        / "scripts"
        / "validate_output.py"
    )
    spec = importlib.util.spec_from_file_location("s3_output_validator", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class S3OutputValidatorTest(unittest.TestCase):
    @staticmethod
    def _c32_input():
        provisions = {
            "P1": "핵심 규정입니다.",
            "Q1": "가족 예외 규정입니다.",
            "Q2": "관련 없는 다른 예외 규정입니다.",
            "S1": "보조 규정입니다.",
            "A1": "대안 규정입니다.",
        }
        accepted = [
            {"provision_id": provision_id, "text": text}
            for provision_id, text in provisions.items()
        ]
        return {
            "run_id": "c32-validator-fixture",
            "mode": "GENERATE_ANSWER",
            "authorization": {
                "action": "GENERATE",
                "authorized_by": "PROVISION_COVERAGE_POLICY",
            },
            "generation_purpose": "published_answer",
            "publishable": True,
            "candidate_answer_basis": "published_answer",
            "required_evidence_items": [],
            "coverage_assessments": [],
            "answer_targets": [],
            "answered_target_ids": [],
            "deferred_target_ids": [],
            "answer_mode": "full",
            "accepted_provisions": accepted,
            "core_accepted_provisions": [accepted[0]],
            "qualifying_provisions": [accepted[1], accepted[2]],
            "supplemental_provisions": [accepted[3]],
            "alternative_provisions": [accepted[4]],
            "generation_constraints": {
                "public_conclusion_contract": "required",
            },
        }

    @staticmethod
    def _c32_output(
        provision_id="Q1",
        text="가족 예외가 적용되는 경우입니다.",
        target_ids=None,
    ):
        target_ids = ["T1"] if target_ids is None else target_ids
        quoted_text = {
            "P1": "핵심 규정입니다.",
            "Q1": "가족 예외 규정입니다.",
            "Q2": "관련 없는 다른 예외 규정입니다.",
            "S1": "보조 규정입니다.",
            "A1": "대안 규정입니다.",
            "X1": "승인되지 않은 규정입니다.",
        }[provision_id]
        return {
            "schema_version": "1.0",
            "skill_id": "S3",
            "mode": "GENERATE_ANSWER",
            "status": "ok",
            "run_id": "c32-validator-fixture",
            "answer": text + "[CT1]",
            "claims": [
                {
                    "claim_id": "C1",
                    "text": text,
                    "claim_type": "exception",
                    "applicability": "conditional",
                    "answer_target_ids": target_ids,
                    "citation_required": True,
                    "public_role": "conclusion",
                }
            ],
            "claim_citations": [
                {
                    "citation_id": "CT1",
                    "claim_id": "C1",
                    "provision_id": provision_id,
                    "quoted_text": quoted_text,
                    "answer_marker": "[CT1]",
                }
            ],
            "assumptions": [],
            "limitations": [],
        }

    @staticmethod
    def _c39_input():
        provisions = {
            "P1": "핵심 규정입니다.",
            "Q1": "조건부 예외 규정입니다.",
            "S1": "보조 규정입니다.",
            "A1": "대안 규정입니다.",
        }
        accepted = [
            {"provision_id": provision_id, "text": text}
            for provision_id, text in provisions.items()
        ]
        return {
            "run_id": "c39-validator-fixture",
            "mode": "GENERATE_ANSWER",
            "authorization": {
                "action": "GENERATE",
                "authorized_by": "PROVISION_COVERAGE_POLICY",
            },
            "generation_purpose": "published_answer",
            "publishable": True,
            "candidate_answer_basis": "published_answer",
            "answer_targets": [{"answer_target_id": "T1"}],
            "answered_target_ids": ["T1"],
            "deferred_target_ids": [],
            "answer_mode": "full",
            "required_evidence_items": [{
                "evidence_item_id": "E1",
                "critical": True,
                "answer_target_ids": ["T1"],
            }],
            "coverage_assessments": [{
                "evidence_item_id": "E1", "status": "covered",
            }],
            "accepted_provisions": accepted,
            "core_accepted_provisions": [accepted[0]],
            "qualifying_provisions": [accepted[1]],
            "_harness_c39_qualifying_public_exception_links": [{
                "provision_id": "Q1", "evidence_item_id": "E1",
            }],
            "supplemental_provisions": [accepted[2]],
            "alternative_provisions": [accepted[3]],
            "generation_constraints": {
                "public_conclusion_contract": "required",
            },
        }

    @staticmethod
    def _c39_output(
        provision_id="Q1", claim_type="exception", applicability="conditional", target_ids=None
    ):
        quoted_text = {
            "P1": "핵심 규정입니다.",
            "Q1": "조건부 예외 규정입니다.",
            "S1": "보조 규정입니다.",
            "A1": "대안 규정입니다.",
            "X1": "알 수 없는 규정입니다.",
        }[provision_id]
        text = "조건부 예외를 공적으로 설명합니다."
        return {
            "schema_version": "1.0",
            "skill_id": "S3",
            "mode": "GENERATE_ANSWER",
            "status": "ok",
            "run_id": "c39-validator-fixture",
            "answer": text + "[CT1]",
            "claims": [{
                "claim_id": "C1", "text": text, "claim_type": claim_type,
                "applicability": applicability,
                "answer_target_ids": ["T1"] if target_ids is None else target_ids,
                "citation_required": True, "public_role": "conclusion",
            }],
            "claim_citations": [{
                "citation_id": "CT1", "claim_id": "C1",
                "provision_id": provision_id, "quoted_text": quoted_text,
                "answer_marker": "[CT1]",
            }],
            "assumptions": [], "limitations": [],
        }

    @staticmethod
    def _c32_obligation(
        text="가족 예외가 적용되는 경우입니다.",
        target_ids=None,
        provision_ids=None,
    ):
        return {
            "source_claim_id": "C5",
            "normalized_text": text,
            "answer_target_ids": ["T1"] if target_ids is None else target_ids,
            "provision_ids": ["Q1"] if provision_ids is None else provision_ids,
        }

    def test_success_without_input_reports_contract_error_instead_of_raising(self):
        validator = _load_validator()

        errors = validator.validate(
            {
                "schema_version": "1.0",
                "skill_id": "S3",
                "mode": "GENERATE_ANSWER",
                "status": "ok",
            },
            None,
        )

        self.assertEqual(errors, ["success validation requires --input"])

    def test_no_input_still_rejects_an_unknown_entry_point(self):
        validator = _load_validator()

        errors = validator.validate(
            {
                "schema_version": "1.0",
                "skill_id": "S3",
                "mode": "UNKNOWN",
                "status": "ok",
            },
            None,
        )

        self.assertEqual(
            errors,
            [
                "mode must be a supported S3 entry point",
                "success validation requires --input",
            ],
        )

    def test_c32_accepts_only_the_exact_frozen_qualifying_citation(self):
        validator = _load_validator()
        input_data = self._c32_input()
        input_data[
            "_harness_c32_conditional_exception_carry_forward_obligations"
        ] = [self._c32_obligation()]

        self.assertEqual(validator.validate(self._c32_output(), input_data), [])

    def test_c32_fails_closed_without_exact_obligation_coverage(self):
        validator = _load_validator()
        context_key = "_harness_c32_conditional_exception_carry_forward_obligations"
        cases = [
            ("no obligation", self._c32_output(), None),
            (
                "wrong normalized text",
                self._c32_output(text="전혀 다른 조건입니다."),
                self._c32_obligation(),
            ),
            (
                "wrong target",
                self._c32_output(target_ids=["T2"]),
                self._c32_obligation(),
            ),
            (
                "partial target and provision coverage",
                self._c32_output(),
                self._c32_obligation(target_ids=["T1", "T2"], provision_ids=["P1", "Q1"]),
            ),
            (
                "unrelated qualifying provision",
                self._c32_output(provision_id="Q2"),
                self._c32_obligation(),
            ),
            (
                "supplemental provision",
                self._c32_output(provision_id="S1"),
                self._c32_obligation(),
            ),
            (
                "alternative provision",
                self._c32_output(provision_id="A1"),
                self._c32_obligation(),
            ),
            (
                "unaccepted provision",
                self._c32_output(provision_id="X1"),
                self._c32_obligation(),
            ),
        ]
        for name, output, obligation in cases:
            with self.subTest(name=name):
                input_data = self._c32_input()
                if obligation is not None:
                    input_data[context_key] = [obligation]
                errors = validator.validate(output, input_data)
                self.assertIn(
                    "public conclusion may cite only core accepted provision: CT1",
                    errors,
                )
                if name == "unaccepted provision":
                    self.assertIn("citation uses non-accepted provision: CT1", errors)

    def test_c39_allows_only_private_target_linked_qualifying_conditional_exception(self):
        validator = _load_validator()
        self.assertEqual(
            validator.validate(self._c39_output(), self._c39_input()), []
        )

    def test_c39_rejects_nonexception_or_unlinked_auxiliary_public_citations(self):
        validator = _load_validator()
        cases = [
            ("non-exception qualifying", self._c39_output(claim_type="legal_rule"), None),
            ("supplemental", self._c39_output(provision_id="S1"), None),
            ("alternative", self._c39_output(provision_id="A1"), None),
            ("unknown", self._c39_output(provision_id="X1"), None),
            ("wrong target", self._c39_output(target_ids=["T2"]), None),
            ("unlinked qualifying", self._c39_output(), []),
        ]
        for name, output, links in cases:
            with self.subTest(name=name):
                input_data = self._c39_input()
                if links is not None:
                    input_data["_harness_c39_qualifying_public_exception_links"] = links
                errors = validator.validate(output, input_data)
                self.assertIn(
                    "public conclusion may cite only core accepted provision: CT1",
                    errors,
                )

    def test_c39_keeps_core_public_citations_valid(self):
        validator = _load_validator()
        self.assertEqual(
            validator.validate(
                self._c39_output(
                    provision_id="P1", claim_type="legal_rule", applicability="direct"
                ),
                self._c39_input(),
            ),
            [],
        )


if __name__ == "__main__":
    unittest.main()
