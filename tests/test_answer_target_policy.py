import unittest

from harness.contracts import (
    ApplicabilityStatus,
    AnswerTarget,
    CandidateProvision,
    CompletionRequirement,
    CriterionResult,
    CriterionStatus,
    CoverageAssessment,
    CoverageStatus,
    EvidenceConflict,
    EvidenceLink,
    GapType,
    LegalIssue,
    LegalStatus,
    PolicyAction,
    TerminationReason,
    RequiredEvidenceItem,
    SupportSpan,
)
from harness.policy import decide_next_action
from harness.run_state import RunState
from harness.state_update import apply_coverage_assessment
from harness.validation import (
    ValidationError,
    validate_answer_draft,
    validate_coverage_assessment,
    validate_initial_plan,
)


def target_state(remaining_round_budget=0):
    state = RunState(
        question="보험자 대위권과 직접청구권이 있는가",
        normalized_question="보험자 대위권과 직접청구권이 있는가",
        run_id="answer-target-policy",
        remaining_round_budget=remaining_round_budget,
    )
    state.legal_issues = [LegalIssue("I1", "보험금 청구권")]
    state.answer_targets = [
        AnswerTarget("T1", "보험자 대위권", "대위권의 법적 근거", "yes_no"),
        AnswerTarget("T2", "직접청구권", "직접청구권의 법적 근거", "yes_no"),
    ]
    state.required_evidence_items = [
        RequiredEvidenceItem(
            "E1", "I1", "rule", "보험자 대위권", True,
            answer_target_ids=["T1"],
            scope_source="explicit_question",
        ),
        RequiredEvidenceItem(
            "E2", "I1", "rule", "직접청구권", True,
            answer_target_ids=["T2"],
            scope_source="explicit_question",
        ),
    ]
    return state


def assessment(evidence_id, legal_status, applicability, gap, provision_id=None):
    status = (
        CoverageStatus.PARTIALLY_COVERED
        if legal_status is LegalStatus.COVERED
        and applicability is ApplicabilityStatus.CONDITIONAL
        else CoverageStatus(legal_status.value)
    )
    return CoverageAssessment(
        evidence_id,
        status,
        [provision_id] if provision_id else [],
        "테스트 판정",
        partial_kind=(
            "factual_condition"
            if status is CoverageStatus.PARTIALLY_COVERED
            and applicability is ApplicabilityStatus.CONDITIONAL
            else "legal_support_gap"
            if status is CoverageStatus.PARTIALLY_COVERED
            else "not_applicable"
        ),
        legal_status=legal_status,
        applicability_status=applicability,
        gap_type=gap,
    )


class AnswerTargetPolicyTests(unittest.TestCase):
    def test_legacy_initial_plan_stays_three_tuple_compatible(self):
        payload = {
            "legal_issues": [{"issue_id": "I1", "description": "쟁점"}],
            "required_evidence_items": [{
                "evidence_item_id": "E1", "issue_id": "I1", "evidence_type": "rule",
                "description": "규칙", "critical": True,
            }],
            "retrieval_requests": [{
                "request_id": "RQ1", "issue_id": "I1", "evidence_item_id": "E1",
                "query_channel": "sparse_keyword", "query_text": "규칙", "top_k": 100,
            }],
        }

        issues, evidence, requests = validate_initial_plan(payload)

        self.assertEqual(issues[0].issue_id, "I1")
        self.assertEqual(evidence[0].completion_requirements, [])
        self.assertEqual(requests[0].request_id, "RQ1")

    def test_question_scoped_targets_require_atomic_critical_evidence(self):
        payload = {
            "answer_targets": [{
                "answer_target_id": "T1", "question_anchor": "승계할 수 있는가",
                "requested_output": "승계 가능 여부", "answer_type": "yes_no_with_conditions",
            }],
            "legal_issues": [{"issue_id": "I1", "description": "승계"}],
            "required_evidence_items": [{
                "evidence_item_id": "E1", "issue_id": "I1", "evidence_type": "rule",
                "description": "승계 효과", "critical": True,
                "answer_target_ids": ["T1"], "scope_source": "explicit_question",
                "necessity_reason": "가능 여부를 답하는 규칙이다",
                "completion_requirements": [{
                    "requirement_id": "E1-R1", "text": "양수인의 지위 승계 효과",
                }],
            }],
            "retrieval_requests": [{
                "request_id": "RQ1", "issue_id": "I1", "evidence_item_id": "E1",
                "query_channel": "sparse_keyword", "query_text": "영업자 지위 승계", "top_k": 100,
            }],
        }

        _, targets, evidence, _ = validate_initial_plan(
            payload, question="영업자 지위를 승계할 수 있는가", include_answer_targets=True
        )

        self.assertEqual(targets[0].answer_target_id, "T1")
        self.assertEqual(evidence[0].completion_requirements[0].requirement_id, "E1-R1")

    def test_supporting_context_cannot_be_critical(self):
        payload = {
            "answer_targets": [{
                "answer_target_id": "T1", "question_anchor": "승계할 수 있는가",
                "requested_output": "승계 가능 여부", "answer_type": "yes_no",
            }],
            "legal_issues": [{"issue_id": "I1", "description": "승계"}],
            "required_evidence_items": [{
                "evidence_item_id": "E1", "issue_id": "I1", "evidence_type": "procedure",
                "description": "제출 서류", "critical": True, "answer_target_ids": ["T1"],
                "scope_source": "supporting_context", "necessity_reason": "참고",
                "completion_requirements": [{"requirement_id": "E1-R1", "text": "서류"}],
            }],
            "retrieval_requests": [{
                "request_id": "RQ1", "issue_id": "I1", "evidence_item_id": "E1",
                "query_channel": "sparse_keyword", "query_text": "제출 서류", "top_k": 100,
            }],
        }

        with self.assertRaisesRegex(ValidationError, "supporting_context"):
            validate_initial_plan(
                payload, question="영업자 지위를 승계할 수 있는가", include_answer_targets=True
            )

    def test_answer_target_anchor_cannot_come_only_from_background_scenario(self):
        payload = {
            "answer_targets": [{
                "answer_target_id": "T1", "question_anchor": "상속인이 사망했다",
                "requested_output": "승계 가능 여부", "answer_type": "yes_no",
            }],
            "legal_issues": [{"issue_id": "I1", "description": "승계"}],
            "required_evidence_items": [{
                "evidence_item_id": "E1", "issue_id": "I1", "evidence_type": "rule",
                "description": "승계 효과", "critical": True, "answer_target_ids": ["T1"],
                "scope_source": "explicit_question", "necessity_reason": "승계 판단",
                "completion_requirements": [{"requirement_id": "E1-R1", "text": "승계 효과"}],
            }],
            "retrieval_requests": [{
                "request_id": "RQ1", "issue_id": "I1", "evidence_item_id": "E1",
                "query_channel": "sparse_keyword", "query_text": "영업자 지위 승계", "top_k": 100,
            }],
        }

        with self.assertRaisesRegex(ValidationError, "question substring"):
            validate_initial_plan(
                payload,
                question="[배경 시나리오] 상속인이 사망했다. [질문] 영업자 지위를 승계할 수 있는가",
                include_answer_targets=True,
            )

    def test_s2_accepts_legacy_evidence_status_without_atomic_requirements(self):
        state = RunState(question="q", normalized_question="q", run_id="legacy-s2")
        state.required_evidence_items = [
            RequiredEvidenceItem("E1", "I1", "rule", "기존 법리", True)
        ]
        state.candidate_provisions = [
            CandidateProvision("P1", "테스트법", "기존 법리 조문", "I1", "RQ1", 1, 1.0, 1, 1.0)
        ]
        payload = {
            "evidence_links": [{
                "issue_id": "I1", "evidence_item_id": "E1", "provision_id": "P1",
                "support_spans": [{"start_char": 0, "end_char": 2}], "assessment": "accepted",
            }],
            "coverage_assessments": [{
                "evidence_item_id": "E1", "evidence_status": "covered",
                "linked_provision_ids": ["P1"], "rationale": "기존 결과",
            }],
            "evidence_conflicts": [],
        }

        _, assessments, _ = validate_coverage_assessment(payload, state)

        self.assertEqual(assessments[0].legal_status, LegalStatus.COVERED)

    def test_atomic_s2_requires_axes_and_criterion_results(self):
        state = RunState(question="q", normalized_question="q", run_id="atomic-s2")
        state.required_evidence_items = [RequiredEvidenceItem(
            "E1", "I1", "rule", "새 법리", True,
            completion_requirements=[
                CompletionRequirement("E1-R1", "권리")
            ],
        )]
        state.candidate_provisions = [
            CandidateProvision("P1", "테스트법", "새 법리 조문", "I1", "RQ1", 1, 1.0, 1, 1.0)
        ]
        payload = {
            "evidence_links": [],
            "coverage_assessments": [{
                "evidence_item_id": "E1", "status": "uncovered",
                "linked_provision_ids": [], "rationale": "구식 출력",
            }],
            "evidence_conflicts": [],
        }

        with self.assertRaisesRegex(ValidationError, "atomic completion_requirements"):
            validate_coverage_assessment(payload, state)

    def test_missing_fact_generates_conditional_without_retrieval(self):
        state = target_state(remaining_round_budget=2)
        state.coverage_assessments = [
            assessment("E1", LegalStatus.COVERED, ApplicabilityStatus.CONDITIONAL, GapType.MISSING_FACT, "P1"),
            assessment("E2", LegalStatus.COVERED, ApplicabilityStatus.DIRECT, GapType.NONE, "P2"),
        ]
        state.evidence_links = [
            EvidenceLink("I1", "E1", "P1", [SupportSpan(0, 1)], "accepted"),
            EvidenceLink("I1", "E2", "P2", [SupportSpan(0, 1)], "accepted"),
        ]

        decision = decide_next_action(state)

        self.assertEqual(decision.action, PolicyAction.GENERATE)
        self.assertEqual(decision.answer_mode.value, "conditional")
        self.assertEqual(decision.answered_target_ids, ["T1", "T2"])

    def test_budget_exhaustion_generates_limited_for_only_covered_target(self):
        state = target_state()
        state.coverage_assessments = [
            assessment("E1", LegalStatus.COVERED, ApplicabilityStatus.DIRECT, GapType.NONE, "P1"),
            assessment("E2", LegalStatus.UNCOVERED, ApplicabilityStatus.NOT_ASSESSED, GapType.MISSING_STATUTE),
        ]
        state.evidence_links = [
            EvidenceLink("I1", "E1", "P1", [SupportSpan(0, 1)], "accepted"),
        ]

        decision = decide_next_action(state)

        self.assertEqual(decision.action, PolicyAction.GENERATE)
        self.assertEqual(decision.answer_mode.value, "limited")
        self.assertEqual(decision.answered_target_ids, ["T1"])
        self.assertEqual(decision.deferred_target_ids, ["T2"])

    def test_no_citable_target_or_conflict_remains_abstention(self):
        state = target_state()
        state.coverage_assessments = [
            assessment("E1", LegalStatus.UNCOVERED, ApplicabilityStatus.NOT_ASSESSED, GapType.MISSING_STATUTE),
            assessment("E2", LegalStatus.UNCOVERED, ApplicabilityStatus.NOT_ASSESSED, GapType.MISSING_STATUTE),
        ]
        self.assertEqual(decide_next_action(state).action, PolicyAction.ABSTAIN)

        state.evidence_conflicts = [EvidenceConflict("E1", ["P1", "P2"], "실질 충돌")]
        self.assertEqual(decide_next_action(state).action, PolicyAction.ABSTAIN)

    def test_deferred_target_claim_is_rejected(self):
        state = target_state()
        state.answered_target_ids = ["T1"]
        state.deferred_target_ids = ["T2"]
        payload = {
            "claims": [{"claim_id": "C1", "text": "직접청구권 결론", "answer_target_ids": ["T2"]}],
            "claim_citations": [{"claim_id": "C1", "provision_ids": ["P1"]}],
            "answer": "직접청구권 결론",
        }

        with self.assertRaisesRegex(ValidationError, "deferred"):
            validate_answer_draft(payload, state)

    def test_public_answer_cannot_append_audit_assumptions_or_limitations(self):
        state = target_state()
        state.answered_target_ids = ["T1"]
        state.deferred_target_ids = ["T2"]
        state.accepted_provision_ids = {"P1"}
        payload = {
            "claims": [
                {"claim_id": "C1", "text": "대위권이 인정됩니다.", "answer_target_ids": ["T1"]}
            ],
            "claim_citations": [{"claim_id": "C1", "provision_ids": ["P1"]}],
            "answer": "대위권이 인정됩니다.\n전제: 보험금이 지급되었습니다.",
            "assumptions": [
                {"code": "A1", "message": "보험금이 지급되었다고 가정합니다."}
            ],
            "limitations": [],
        }

        with self.assertRaisesRegex(ValidationError, "must not append audit"):
            validate_answer_draft(payload, state)

    def test_new_candidate_alone_is_not_progress(self):
        state = RunState(question="q", normalized_question="q", run_id="progress")
        state.required_evidence_items = [
            RequiredEvidenceItem("E1", "I1", "rule", "핵심 규칙", True)
        ]
        state.last_retrieval_new_provision_count = 7

        progress = apply_coverage_assessment(
            state,
            [],
            [assessment("E1", LegalStatus.UNCOVERED, ApplicabilityStatus.NOT_ASSESSED, GapType.MISSING_STATUTE)],
            [],
        )

        self.assertFalse(progress)
        self.assertEqual(state.no_progress_rounds, 1)


    def test_redundant_accepted_link_is_not_progress(self):
        state = RunState(question="q", normalized_question="q", run_id="redundant")
        state.required_evidence_items = [RequiredEvidenceItem("E1", "I1", "rule", "핵심 규칙", True)]
        state.coverage_assessments = [assessment("E1", LegalStatus.UNCOVERED, ApplicabilityStatus.NOT_ASSESSED, GapType.MISSING_STATUTE)]
        state.evidence_links = [EvidenceLink("I1", "E1", "P1", [SupportSpan(0, 1)], "accepted")]
        progress = apply_coverage_assessment(
            state,
            [EvidenceLink("I1", "E1", "P2", [SupportSpan(0, 1)], "accepted")],
            [assessment("E1", LegalStatus.UNCOVERED, ApplicabilityStatus.NOT_ASSESSED, GapType.MISSING_STATUTE)],
            [],
        )
        self.assertFalse(progress)
        self.assertEqual(state.no_progress_rounds, 1)

    def test_late_critical_criterion_improvement_resets_progress(self):
        state = RunState(question="q", normalized_question="q", run_id="criterion")
        state.required_evidence_items = [RequiredEvidenceItem(
            "E1", "I1", "rule", "핵심 규칙", True,
            completion_requirements=[CompletionRequirement("E1-R1", "법정 근거")]
        )]
        prior = assessment("E1", LegalStatus.PARTIALLY_COVERED, ApplicabilityStatus.NOT_ASSESSED, GapType.MISSING_STATUTE, "P1")
        prior = CoverageAssessment(
            **{**prior.__dict__, "criterion_results": [CriterionResult("E1-R1", CriterionStatus.UNSATISFIED, [], "미충족")]}
        )
        current = assessment("E1", LegalStatus.PARTIALLY_COVERED, ApplicabilityStatus.NOT_ASSESSED, GapType.MISSING_STATUTE, "P1")
        current = CoverageAssessment(
            **{**current.__dict__, "criterion_results": [CriterionResult("E1-R1", CriterionStatus.PARTIALLY_SATISFIED, ["P1"], "일부 근거")]}
        )
        state.coverage_assessments = [prior]
        state.no_progress_rounds = 1
        progress = apply_coverage_assessment(
            state, [EvidenceLink("I1", "E1", "P1", [SupportSpan(0, 1)], "accepted")], [current], []
        )
        self.assertTrue(progress)
        self.assertEqual(state.no_progress_rounds, 0)

    def test_initial_no_support_then_two_no_progress_assessments_stops_retrieval(self):
        state = RunState(question="q", normalized_question="q", run_id="stop", remaining_round_budget=2)
        state.legal_issues = [LegalIssue("I1", "핵심 쟁점")]
        state.required_evidence_items = [RequiredEvidenceItem("E1", "I1", "rule", "핵심 규칙", True)]
        uncovered = assessment("E1", LegalStatus.UNCOVERED, ApplicabilityStatus.NOT_ASSESSED, GapType.MISSING_STATUTE)
        self.assertFalse(apply_coverage_assessment(state, [], [uncovered], []))
        self.assertEqual(state.no_progress_rounds, 1)
        self.assertEqual(decide_next_action(state).action, PolicyAction.RETRIEVE_GAP)
        self.assertFalse(apply_coverage_assessment(state, [], [uncovered], []))
        decision = decide_next_action(state)
        self.assertEqual(state.no_progress_rounds, 2)
        self.assertEqual(decision.action, PolicyAction.ABSTAIN)
        self.assertEqual(decision.termination_reason, TerminationReason.NO_RETRIEVAL_PROGRESS)

    def test_partial_initial_no_progress_then_late_status_improvement_stays_allowed(self):
        state = RunState(question="q", normalized_question="q", run_id="late", remaining_round_budget=2)
        state.legal_issues = [LegalIssue("I1", "핵심 쟁점")]
        state.required_evidence_items = [RequiredEvidenceItem(
            "E1", "I1", "rule", "핵심 규칙", True,
            completion_requirements=[CompletionRequirement("E1-R1", "법정 근거")],
        )]
        partial = CoverageAssessment(
            **{**assessment("E1", LegalStatus.PARTIALLY_COVERED, ApplicabilityStatus.NOT_ASSESSED, GapType.MISSING_STATUTE, "P1").__dict__,
               "criterion_results": [CriterionResult("E1-R1", CriterionStatus.PARTIALLY_SATISFIED, ["P1"], "일부 근거")]}
        )
        state.coverage_assessments = [partial]
        self.assertFalse(apply_coverage_assessment(state, [], [partial], []))
        self.assertEqual(state.no_progress_rounds, 1)
        self.assertEqual(decide_next_action(state).action, PolicyAction.RETRIEVE_GAP)
        covered = CoverageAssessment(
            **{**assessment("E1", LegalStatus.COVERED, ApplicabilityStatus.DIRECT, GapType.NONE, "P1").__dict__,
               "criterion_results": [CriterionResult("E1-R1", CriterionStatus.SATISFIED, ["P1"], "완전 근거")]}
        )
        self.assertTrue(apply_coverage_assessment(state, [], [covered], []))
        self.assertEqual(state.no_progress_rounds, 0)
        self.assertEqual(decide_next_action(state).action, PolicyAction.GENERATE)

if __name__ == "__main__":
    unittest.main()
