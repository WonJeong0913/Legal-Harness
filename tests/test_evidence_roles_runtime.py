import unittest
from pathlib import Path

from harness.contracts import (
    ApplicabilityStatus,
    AnswerTarget,
    CandidateProvision,
    CoverageAssessment,
    CoverageStatus,
    EvidenceLink,
    EvidenceRole,
    GapType,
    GoverningLegalRegime,
    LegalStatus,
    RequiredEvidenceItem,
    SupportSpan,
)
from harness.run_state import RunState
from harness.runner import HarnessRunner
from harness.state_update import apply_coverage_assessment
from harness.validation import ValidationError, validate_answer_draft, validate_coverage_assessment
from runtime.local_ollama_executor import LocalOllamaSkillExecutor


ROOT = Path(__file__).resolve().parents[1]


def candidate(provision_id):
    return CandidateProvision(
        provision_id=provision_id,
        statute_name="예시법 제1조",
        provision_text="예시 조문 본문",
        issue_id="I1",
        source_request_id="RQ1",
        retrieval_round=1,
        first_stage_score=1.0,
        fusion_rank=1,
        rerank_score=1.0,
    )


def state_with_candidates(*provision_ids):
    return RunState(
        question="질문",
        normalized_question="질문",
        run_id="roles-fixture",
        required_evidence_items=[
            RequiredEvidenceItem("E1", "I1", "rule", "책임 근거", True)
        ],
        candidate_provisions=[candidate(provision_id) for provision_id in provision_ids],
    )


def raw_link(provision_id, role=None, condition="", rationale="역할 근거"):
    link = {
        "issue_id": "I1",
        "evidence_item_id": "E1",
        "provision_id": provision_id,
        "support_spans": [{"start_char": 0, "end_char": 2}],
        "assessment": "accepted",
        "condition": condition,
        "rationale": rationale,
    }
    if role is not None:
        link["role"] = role
    return link


def raw_assessment(linked_ids, governing="direct_entailment"):
    return {
        "evidence_item_id": "E1",
        "status": "covered",
        "linked_provision_ids": list(linked_ids),
        "rationale": "핵심 법률근거가 직접 적용된다.",
        "partial_kind": "not_applicable",
        "missing_aspects": [],
        "legal_status": "covered",
        "applicability_status": "direct",
        "gap_type": "none",
        "governing_legal_regime": governing,
        "criterion_results": [],
    }


class EvidenceRoleRuntimeTests(unittest.TestCase):
    @staticmethod
    def _c38_state(qualifying_evidence_targets=("T1",)):
        state = state_with_candidates("P-core", "P-qual", "P-supp", "P-alt")
        state.answer_targets = [
            AnswerTarget("T1", "질문", "조건부 예외", "legal_conclusion"),
        ]
        state.answered_target_ids = ["T1"]
        state.required_evidence_items = [
            RequiredEvidenceItem(
                "E1", "I1", "rule", "핵심 및 예외 근거", True,
                answer_target_ids=list(qualifying_evidence_targets),
            ),
        ]
        state.evidence_links = [
            EvidenceLink("I1", "E1", "P-core", [SupportSpan(0, 2)], role=EvidenceRole.CORE),
            EvidenceLink("I1", "E1", "P-qual", [SupportSpan(0, 2)], role=EvidenceRole.QUALIFYING, condition="예외 조건"),
            EvidenceLink("I1", "E1", "P-supp", [SupportSpan(0, 2)], role=EvidenceRole.SUPPLEMENTAL),
            EvidenceLink("I1", "E1", "P-alt", [SupportSpan(0, 2)], role=EvidenceRole.ALTERNATIVE, condition="대체 조건"),
        ]
        state.refresh_derived_fields()
        return state

    @staticmethod
    def _c38_answer(provision_id="P-qual", claim_type="exception", applicability="conditional"):
        return {
            "claims": [{
                "claim_id": "C1", "text": "조건부 예외 결론",
                "claim_type": claim_type, "applicability": applicability,
                "answer_target_ids": ["T1"], "public_role": "conclusion",
            }],
            "claim_citations": [{"claim_id": "C1", "provision_ids": [provision_id]}],
            "answer": "조건부 예외 결론", "assumptions": [], "limitations": [],
        }

    def test_roleless_legacy_link_is_core_and_direct_regime_falls_back(self):
        state = state_with_candidates("P-core")
        links, assessments, conflicts = validate_coverage_assessment(
            {
                "evidence_links": [raw_link("P-core", role=None)],
                "coverage_assessments": [raw_assessment(["P-core"])],
                "evidence_conflicts": [],
            },
            state,
        )

        self.assertEqual(links[0].role, EvidenceRole.CORE)
        self.assertEqual(
            assessments[0].governing_legal_regime,
            GoverningLegalRegime.DIRECT_ENTAILMENT,
        )
        self.assertFalse(conflicts)

    def test_auxiliary_role_cannot_clear_coverage_or_governing_regime(self):
        state = state_with_candidates("P-aux")
        payload = {
            "evidence_links": [raw_link("P-aux", role="SUPPLEMENTAL")],
            "coverage_assessments": [raw_assessment(["P-aux"])],
            "evidence_conflicts": [],
        }

        with self.assertRaisesRegex(
            ValidationError, "accepted CORE provisions"
        ):
            validate_coverage_assessment(payload, state)

    def test_governing_regime_axis_rejects_non_direct_covered_status(self):
        state = state_with_candidates("P-core")
        payload = {
            "evidence_links": [raw_link("P-core", role="CORE")],
            "coverage_assessments": [
                raw_assessment(["P-core"], governing="not_direct_entailment")
            ],
            "evidence_conflicts": [],
        }

        with self.assertRaisesRegex(ValidationError, "covered legal status"):
            validate_coverage_assessment(payload, state)

    def test_role_projections_are_derived_union_and_may_overlap(self):
        state = state_with_candidates("P-core", "P-aux", "P-alt")
        links = [
            EvidenceLink(
                "I1", "E1", "P-core", [SupportSpan(0, 2)], role=EvidenceRole.CORE,
                rationale="직접 규율",
            ),
            EvidenceLink(
                "I1", "E1", "P-aux", [SupportSpan(0, 2)], role=EvidenceRole.SUPPLEMENTAL,
                rationale="보조 설명",
            ),
            EvidenceLink(
                "I1", "E1", "P-aux", [SupportSpan(0, 2)], role=EvidenceRole.QUALIFYING,
                condition="사실관계가 그 단서를 충족하는 경우", rationale="조건 한정",
            ),
            EvidenceLink(
                "I1", "E1", "P-alt", [SupportSpan(0, 2)], role=EvidenceRole.ALTERNATIVE,
                condition="별도 법적 경로가 선택되는 경우", rationale="대체 경로",
            ),
        ]
        assessment = CoverageAssessment(
            evidence_item_id="E1",
            status=CoverageStatus.COVERED,
            linked_provision_ids=["P-core"],
            rationale="핵심 근거",
            legal_status=LegalStatus.COVERED,
            applicability_status=ApplicabilityStatus.DIRECT,
            gap_type=GapType.NONE,
            governing_legal_regime=GoverningLegalRegime.DIRECT_ENTAILMENT,
        )

        apply_coverage_assessment(state, links, [assessment], [])

        self.assertEqual(state.accepted_provision_ids, {"P-core", "P-aux", "P-alt"})
        self.assertEqual(state.core_accepted_provision_ids, {"P-core"})
        self.assertEqual(state.supplemental_provision_ids, {"P-aux"})
        self.assertEqual(state.qualifying_provision_ids, {"P-aux"})
        self.assertEqual(state.alternative_provision_ids, {"P-alt"})
        self.assertTrue(state.core_accepted_provision_ids <= state.accepted_provision_ids)
        self.assertTrue(state.qualifying_provision_ids & state.supplemental_provision_ids)

    def test_conclusion_is_core_only_but_audit_may_cite_authorized_auxiliary(self):
        state = state_with_candidates("P-core", "P-aux")
        state.evidence_links = [
            EvidenceLink("I1", "E1", "P-core", [SupportSpan(0, 2)], role=EvidenceRole.CORE),
            EvidenceLink("I1", "E1", "P-aux", [SupportSpan(0, 2)], role=EvidenceRole.SUPPLEMENTAL),
        ]
        state.refresh_derived_fields()
        valid = {
            "claims": [
                {"claim_id": "C1", "text": "핵심 결론", "answer_target_ids": [], "public_role": "conclusion"},
                {"claim_id": "C2", "text": "보조 감사", "answer_target_ids": [], "public_role": "audit"},
            ],
            "claim_citations": [
                {"claim_id": "C1", "provision_ids": ["P-core"]},
                {"claim_id": "C2", "provision_ids": ["P-aux"]},
            ],
            "answer": "핵심 결론",
            "assumptions": [],
            "limitations": [],
        }
        self.assertEqual(validate_answer_draft(valid, state).claims[1].public_role, "audit")

        invalid = dict(valid)
        invalid["claim_citations"] = [
            {"claim_id": "C1", "provision_ids": ["P-aux"]},
            {"claim_id": "C2", "provision_ids": ["P-core"]},
        ]
        with self.assertRaisesRegex(ValidationError, "CORE accepted"):
            validate_answer_draft(invalid, state)

    def test_c38_final_validation_allows_target_linked_qualifying_conditional_exception(self):
        state = self._c38_state()
        self.assertEqual(
            validate_answer_draft(self._c38_answer(), state).claims[0].claim_id,
            "C1",
        )
        payload = HarnessRunner._answer_payload(None, state)
        self.assertEqual(
            payload["qualifying_public_exception_links"],
            [{"provision_id": "P-qual", "evidence_item_id": "E1"}],
        )
        executor = LocalOllamaSkillExecutor(ROOT / "skills", "test", generator=lambda _: "{}")
        skill_input = executor._build_skill_input(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", payload
        )
        self.assertEqual(
            skill_input["qualifying_public_exception_links"],
            [{"provision_id": "P-qual", "evidence_item_id": "E1"}],
        )

    def test_c38_final_validation_rejects_nonexception_or_unlinked_auxiliary_conclusions(self):
        cases = [
            (self._c38_state(), self._c38_answer(claim_type="legal_rule")),
            (self._c38_state(), self._c38_answer(provision_id="P-supp")),
            (self._c38_state(), self._c38_answer(provision_id="P-alt")),
            (self._c38_state(("T2",)), self._c38_answer()),
        ]
        for state, answer in cases:
            with self.subTest(answer=answer):
                with self.assertRaisesRegex(ValidationError, "CORE accepted"):
                    validate_answer_draft(answer, state)

    def test_c38_final_validation_keeps_core_public_conclusion_valid(self):
        state = self._c38_state()
        self.assertEqual(
            validate_answer_draft(
                self._c38_answer(
                    provision_id="P-core", claim_type="legal_rule", applicability="direct"
                ),
                state,
            ).claims[0].claim_id,
            "C1",
        )

    def test_runner_and_runtime_expose_core_and_auxiliary_views(self):
        state = state_with_candidates("P-core", "P-aux")
        state.evidence_links = [
            EvidenceLink("I1", "E1", "P-core", [SupportSpan(0, 2)], role=EvidenceRole.CORE),
            EvidenceLink("I1", "E1", "P-aux", [SupportSpan(0, 2)], role=EvidenceRole.SUPPLEMENTAL),
        ]
        state.refresh_derived_fields()
        payload = HarnessRunner._answer_payload(None, state)
        self.assertEqual(
            {item["provision_id"] for item in payload["accepted_provisions"]},
            {"P-core", "P-aux"},
        )
        self.assertEqual(
            [item["provision_id"] for item in payload["core_accepted_provisions"]],
            ["P-core"],
        )
        self.assertEqual(
            [item["provision_id"] for item in payload["supplemental_provisions"]],
            ["P-aux"],
        )
        executor = LocalOllamaSkillExecutor(ROOT / "skills", "test", generator=lambda _: "{}")
        skill_input = executor._build_skill_input(
            "grounded_legal_answer_generation", "GENERATE_ANSWER", payload
        )
        self.assertEqual(
            {item["provision_id"] for item in skill_input["accepted_provisions"]},
            {"P-core", "P-aux"},
        )
        self.assertEqual(
            [item["provision_id"] for item in skill_input["core_accepted_provisions"]],
            ["P-core"],
        )
        self.assertEqual(skill_input["qualifying_public_exception_links"], [])

    def test_s2_runtime_preserves_auxiliary_link_but_excludes_it_from_coverage(self):
        executor = LocalOllamaSkillExecutor(ROOT / "skills", "test", generator=lambda _: "{}")
        skill_input = {
            "schema_version": "1.0",
            "mode": "ASSESS_COVERAGE",
            "run_id": "roles-runtime",
            "normalized_question": "질문",
            "legal_issues": [{"issue_id": "I1", "description": "책임"}],
            "answer_targets": [],
            "required_evidence_items": [
                {
                    "evidence_item_id": "E1",
                    "issue_id": "I1",
                    "critical": True,
                    "completion_criteria": "책임 근거",
                    "completion_requirements": [],
                }
            ],
            "candidate_provisions": [
                {"provision_id": "C001", "source_provision_id": "P-core", "text": "예시 조문 본문"},
                {"provision_id": "C002", "source_provision_id": "P-aux", "text": "예시 조문 본문"},
            ],
            "prior_coverage_assessments": [],
        }
        raw = {
            "schema_version": "1.0",
            "skill_id": "S2",
            "mode": "ASSESS_COVERAGE",
            "status": "ok",
            "evidence_links": [
                {"evidence_item_id": "E1", "provision_id": "C001", "relation": "supports", "role": "CORE", "condition": "", "rationale": "직접 근거"},
                {"evidence_item_id": "E1", "provision_id": "C002", "relation": "supports", "role": "SUPPLEMENTAL", "condition": "", "rationale": "보조 설명"},
            ],
            "coverage_assessments": [
                {"evidence_item_id": "E1", "status": "covered", "rationale": "핵심 근거", "legal_status": "covered", "applicability_status": "direct", "gap_type": "none", "governing_legal_regime": "direct_entailment", "missing_aspects": [], "criterion_results": []}
            ],
            "missing_evidence_items": [],
            "evidence_conflicts": [],
        }
        normalized = executor._normalize_harness_owned_fields(
            "provision_coverage_assessment", "ASSESS_COVERAGE", skill_input, raw
        )
        self.assertEqual(
            normalized["coverage_assessments"][0]["linked_provision_ids"],
            ["C001"],
        )
        self.assertEqual(
            normalized["evidence_links"][1]["role"], "SUPPLEMENTAL"
        )
        self.assertEqual(
            executor._validators["provision_coverage_assessment"](normalized, skill_input),
            [],
        )
        adapted = executor._adapt_s2(normalized, skill_input)
        links, assessments, _ = validate_coverage_assessment(
            adapted, state_with_candidates("P-core", "P-aux")
        )
        self.assertEqual(assessments[0].linked_provision_ids, ["P-core"])
        self.assertEqual(links[1].role, EvidenceRole.SUPPLEMENTAL)

    def test_s3_runtime_validator_allows_auxiliary_only_for_audit_claim(self):
        executor = LocalOllamaSkillExecutor(ROOT / "skills", "test", generator=lambda _: "{}")
        core = {
            "provision_id": "P-core",
            "text": "핵심 조문",
            "supported_evidence_item_ids": ["E1"],
        }
        auxiliary = {
            "provision_id": "P-aux",
            "text": "보조 조문",
            "supported_evidence_item_ids": ["E1"],
        }
        skill_input = {
            "mode": "GENERATE_ANSWER",
            "run_id": "s3-roles",
            "required_evidence_items": [],
            "coverage_assessments": [],
            "accepted_provisions": [core, auxiliary],
            "core_accepted_provisions": [core],
            "supplemental_provisions": [auxiliary],
            "qualifying_provisions": [],
            "alternative_provisions": [],
            "answer_targets": [],
            "answered_target_ids": [],
            "deferred_target_ids": [],
            "answer_mode": "full",
            "authorization": {"action": "GENERATE", "authorized_by": "PROVISION_COVERAGE_POLICY"},
            "generation_purpose": "published_answer",
            "publishable": True,
            "candidate_answer_basis": "published_answer",
            "generation_constraints": {"max_answer_chars": 800, "public_conclusion_contract": "required"},
        }
        output = {
            "schema_version": "1.0",
            "skill_id": "S3",
            "mode": "GENERATE_ANSWER",
            "status": "ok",
            "run_id": "s3-roles",
            "answer": "핵심 결론[CT1]",
            "claims": [
                {"claim_id": "C1", "text": "핵심 결론", "answer_target_ids": [], "claim_type": "legal_rule", "applicability": "direct", "citation_required": True, "public_role": "conclusion"},
                {"claim_id": "C2", "text": "보조 감사", "answer_target_ids": [], "claim_type": "legal_rule", "applicability": "direct", "citation_required": True, "public_role": "audit"},
            ],
            "claim_citations": [
                {"citation_id": "CT1", "claim_id": "C1", "provision_id": "P-core", "quoted_text": "핵심 조문", "support_description": "핵심", "answer_marker": "[CT1]"},
                {"citation_id": "CT2", "claim_id": "C2", "provision_id": "P-aux", "quoted_text": "보조 조문", "support_description": "보조", "answer_marker": "[CT2]"},
            ],
            "assumptions": [],
            "limitations": [],
        }
        validator = executor._validators["grounded_legal_answer_generation"]
        self.assertEqual(validator(output, skill_input), [])
        output["claim_citations"][0]["provision_id"] = "P-aux"
        output["claim_citations"][0]["quoted_text"] = "보조 조문"
        self.assertTrue(
            any("core accepted provision" in error for error in validator(output, skill_input))
        )


if __name__ == "__main__":
    unittest.main()
