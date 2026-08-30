"""End-to-end deterministic orchestration around externally supplied skills."""

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .contracts import (
    AbstentionReason,
    AnswerMode,
    CandidateAnswerBasis,
    AnswerDraft,
    CandidateAnswerStatus,
    EvidenceRole,
    GapPlanRecovery,
    GapPlanRecoveryDisposition,
    OutcomeStatus,
    Phase,
    PolicyAction,
    PolicyDecision,
    S2LegacyProjectionDiagnostic,
    TerminationReason,
)
from .interfaces import CitationIntegrityValidator, ProvisionRetriever, SkillExecutor
from .policy import abstention_reason_for, decide_next_action
from .run_state import RunState
from .state_update import (
    StateInvariantError,
    apply_coverage_assessment,
    apply_initial_plan,
    record_policy_decision,
    register_retrieval_round,
)
from .tracing import NullTraceSink, TraceSink, to_primitive
from .validation import (
    ValidationError,
    normalize_question,
    validate_answer_draft,
    validate_benchmark_candidate_draft,
    validate_coverage_assessment,
    validate_gap_plan,
    validate_initial_plan,
    validate_retrieval_candidates,
    validate_retrieval_stage_records,
)


S1 = "legal_issue_and_query_planning"
S2 = "provision_coverage_assessment"
S3 = "grounded_legal_answer_generation"
SOURCE_REFERENCE_PATTERN = re.compile(
    r"제?([0-9]+)조(?:의([0-9]+))?(?:[ ]*제?([0-9]+)항)?"
)
QUALIFIED_REFERENCE_PATTERN = re.compile(
    r"(?:「(?P<quoted>[^」]+)」|(?P<plain>[가-힣A-Za-z0-9· ]{1,60}?(?:법률|법|시행령|시행규칙)))[ ]*제?(?P<article>[0-9]+)조(?:의(?P<subarticle>[0-9]+))?(?:[ ]*제?(?P<paragraph>[0-9]+)항)?(?:부터[ ]*제?(?P<range_article>[0-9]+)조(?:의(?P<range_subarticle>[0-9]+))?(?:[ ]*제?(?P<range_paragraph>[0-9]+)항)?까지)?"
)
RELATIVE_REFERENCE_PATTERN = re.compile(r"전[ ]*(조|항|[0-9]+조)")
RANGE_REFERENCE_PREFIX_PATTERN = re.compile(
    r"제?[0-9]+조(?:의[0-9]+)?(?:[ ]*제?[0-9]+항)?부터"
)
UNQUALIFIED_SOURCE_RANGE_PATTERN = re.compile(
    r"제?(?P<article>[0-9]+)조부터[ ]*제?(?P<range_article>[0-9]+)조까지"
)
METADATA_SOURCE_PATTERN = re.compile(
    r"^\s*(?P<statute>.+?)\s+제?(?P<article>[0-9]+)조(?P<tail>.*)\Z"
)
METADATA_LEADING_SUBARTICLE_PATTERN = re.compile(
    r"^\s+(?P<subarticle>[0-9]+)(?=\s|\Z)"
)
METADATA_PARAGRAPH_PATTERN = re.compile(
    r"(?:^|\s)(?P<paragraph>[0-9]+)항(?:\s|\Z)"
)
BODY_SOURCE_HEADING_PATTERN = re.compile(
    r"^\s*제?([0-9]+)조(?:의([0-9]+))?(?:[ ]*제?([0-9]+)항)?"
)
MAX_CANDIDATE_CROSS_REFERENCES_PER_PROVISION = 12



@dataclass(frozen=True)
class HarnessConfig:
    total_retrieval_rounds: int = 3
    total_retrieval_requests: int = 9

    def __post_init__(self) -> None:
        if self.total_retrieval_rounds < 1:
            raise ValueError("total_retrieval_rounds must include the initial round")
        if self.total_retrieval_requests < 1:
            raise ValueError("total_retrieval_requests must be positive")


@dataclass
class HarnessOutcome:
    status: OutcomeStatus
    state: RunState
    answer: Optional[str] = None
    answer_mode: Optional[AnswerMode] = None
    complete_answer: bool = False
    answered_target_ids: List[str] = field(default_factory=list)
    deferred_target_ids: List[str] = field(default_factory=list)
    abstention_reason: Optional[AbstentionReason] = None
    termination_reason: Optional[TerminationReason] = None
    candidate_answer: Optional[str] = None
    candidate_answer_status: Optional[CandidateAnswerStatus] = None
    candidate_answer_basis: Optional[CandidateAnswerBasis] = None
    candidate_answer_termination_reason: Optional[TerminationReason] = None
    candidate_answer_error: Optional[str] = None
    claims: List[Dict[str, Any]] = field(default_factory=list)
    claim_citations: List[Dict[str, Any]] = field(default_factory=list)
    assumptions: List[Dict[str, Any]] = field(default_factory=list)
    limitations: List[Dict[str, Any]] = field(default_factory=list)
    candidate_claims: List[Dict[str, Any]] = field(default_factory=list)
    candidate_claim_citations: List[Dict[str, Any]] = field(default_factory=list)
    candidate_assumptions: List[Dict[str, Any]] = field(default_factory=list)
    candidate_limitations: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class HarnessRunner:
    def __init__(
        self,
        skill_executor: SkillExecutor,
        retriever: ProvisionRetriever,
        citation_validator: CitationIntegrityValidator,
        config: HarnessConfig = HarnessConfig(),
        trace_sink: TraceSink = None,
    ):
        self.skill_executor = skill_executor
        self.retriever = retriever
        self.citation_validator = citation_validator
        self.config = config
        self.trace_sink = trace_sink or NullTraceSink()

    def run(self, question: str, run_id: Optional[str] = None) -> HarnessOutcome:
        try:
            normalized_question = normalize_question(question)
        except ValidationError as exc:
            state = RunState(
                question=question if isinstance(question, str) else "",
                normalized_question="",
                run_id=run_id or str(uuid.uuid4()),
                total_round_budget=self.config.total_retrieval_rounds,
                remaining_round_budget=self.config.total_retrieval_rounds,
                remaining_request_budget=self.config.total_retrieval_requests,
                phase=Phase.EXECUTION_FAILURE,
            )
            return HarnessOutcome(
                status=OutcomeStatus.EXECUTION_FAILURE,
                state=state,
                termination_reason=TerminationReason.INVALID_SKILL_OUTPUT,
                errors=[str(exc)],
            )

        state = RunState(
            question=question,
            normalized_question=normalized_question,
            run_id=run_id or str(uuid.uuid4()),
            total_round_budget=self.config.total_retrieval_rounds,
            remaining_round_budget=self.config.total_retrieval_rounds,
            remaining_request_budget=self.config.total_retrieval_requests,
            phase=Phase.PLANNING_INITIAL,
        )
        self._trace("RUN_STARTED", state)

        try:
            initial_raw = self._execute(
                S1,
                "INITIAL_PLAN",
                {
                    "run_id": state.run_id,
                    "question": state.question,
                    "normalized_question": state.normalized_question,
                    "query_history": [],
                },
            )
            issues, answer_targets, evidence_items, initial_requests = validate_initial_plan(
                initial_raw,
                question=state.normalized_question,
                include_answer_targets=True,
            )
            if len(initial_requests) > state.remaining_request_budget:
                raise ValidationError("initial retrieval requests exceed the frozen request budget")
            apply_initial_plan(state, issues, evidence_items, answer_targets)
            self._trace("INITIAL_PLAN_VALIDATED", state, retrieval_request_count=len(initial_requests))
        except (ValidationError, StateInvariantError, RuntimeError) as exc:
            return self._failure(state, TerminationReason.INVALID_SKILL_OUTPUT, exc)

        retrieval_error = self._retrieve(state, initial_requests, is_gap=False)
        if retrieval_error:
            return retrieval_error

        while True:
            assessment_error = self._assess_coverage(state)
            if assessment_error:
                return assessment_error

            decision = decide_next_action(state)
            record_policy_decision(
                state,
                decision.action.value,
                termination_reason=(decision.termination_reason.value if decision.termination_reason else None),
                explanation=decision.explanation,
                answer_mode=(decision.answer_mode.value if decision.answer_mode else None),
                answered_target_ids=decision.answered_target_ids,
                deferred_target_ids=decision.deferred_target_ids,
            )
            self._trace("POLICY_DECISION", state, action=decision.action.value, explanation=decision.explanation)

            if decision.action is PolicyAction.GENERATE:
                self._apply_generation_scope(state, decision)
                return self._generate_and_validate(state)
            if decision.action is PolicyAction.ABSTAIN:
                return self._abstain(state, decision.termination_reason)

            try:
                state.phase = Phase.PLANNING_GAP
                gap_raw = self._execute(S1, "GAP_QUERY_PLAN", self._gap_payload(state))
                gap_requests = validate_gap_plan(gap_raw, state)
                gap_recovery = self._validated_gap_plan_recovery(
                    gap_raw, len(gap_requests)
                )
            except (ValidationError, RuntimeError) as exc:
                return self._failure(state, TerminationReason.INVALID_SKILL_OUTPUT, exc)

            if gap_recovery is not None:
                recovery_details = {
                    "disposition": gap_recovery.disposition.value,
                    "dropped_request_ids": list(gap_recovery.dropped_request_ids),
                    "repaired_query_sha256": list(
                        gap_recovery.repaired_query_sha256
                    ),
                    "dropped_request_count": gap_recovery.dropped_request_count,
                    "remaining_request_count": gap_recovery.remaining_request_count,
                }
                state.record("GAP_PLAN_REPAIR_COLLISION_RECOVERED", **recovery_details)
                self._trace("GAP_PLAN_REPAIR_COLLISION_RECOVERED", state, **recovery_details)
            if not gap_requests:
                fallback = decide_next_action(state, can_attempt_gap_query=False)
                if gap_recovery is not None:
                    record_policy_decision(
                        state,
                        fallback.action.value,
                        termination_reason=(
                            fallback.termination_reason.value
                            if fallback.termination_reason
                            else None
                        ),
                        explanation=fallback.explanation,
                        answer_mode=(
                            fallback.answer_mode.value if fallback.answer_mode else None
                        ),
                        answered_target_ids=fallback.answered_target_ids,
                        deferred_target_ids=fallback.deferred_target_ids,
                    )
                    self._trace(
                        "POLICY_DECISION",
                        state,
                        action=fallback.action.value,
                        explanation=fallback.explanation,
                    )
                if fallback.action is PolicyAction.GENERATE:
                    if gap_recovery is not None:
                        self._apply_generation_scope(state, fallback)
                    else:
                        self._record_and_apply_generation_decision(state, fallback)
                    return self._generate_and_validate(state)
                return self._abstain(state, fallback.termination_reason)
            if len(gap_requests) > state.remaining_request_budget:
                if state.has_any_citable_answer_target():
                    limited = PolicyDecision(
                        action=PolicyAction.GENERATE,
                        explanation="The next gap plan exceeds the budget; answer only citable targets.",
                        answer_mode=AnswerMode.LIMITED,
                        answered_target_ids=state.covered_answer_target_ids(),
                        deferred_target_ids=[
                            target.answer_target_id
                            for target in state.answer_targets
                            if target.answer_target_id not in state.covered_answer_target_ids()
                        ],
                    )
                    self._record_and_apply_generation_decision(state, limited)
                    return self._generate_and_validate(state)
                if state.can_generate_conditionally():
                    record_policy_decision(
                        state,
                        PolicyAction.GENERATE.value,
                        explanation="The next gap plan exceeds the budget; generate a conditional answer from citable partial support.",
                    )
                    self._apply_generation_scope(
                        state,
                        PolicyDecision(
                            action=PolicyAction.GENERATE,
                            answer_mode=AnswerMode.CONDITIONAL,
                        ),
                    )
                    return self._generate_and_validate(state)
                return self._abstain(state, TerminationReason.RETRIEVAL_BUDGET_EXHAUSTED)
            retrieval_error = self._retrieve(state, gap_requests, is_gap=True)
            if retrieval_error:
                return retrieval_error

    def _retrieve(
        self,
        state: RunState,
        requests: Sequence,
        is_gap: bool,
    ) -> Optional[HarnessOutcome]:
        retrieval_round = state.retrieval_rounds_used + 1
        try:
            critical_evidence_item_ids = [
                item.evidence_item_id
                for item in state.required_evidence_items
                if item.critical
            ]
            candidates = self.retriever.retrieve(
                requests,
                retrieval_round,
                critical_evidence_item_ids=critical_evidence_item_ids,
            )
            validate_retrieval_candidates(candidates, requests, retrieval_round)
            stage_records = list(
                getattr(self.retriever, "last_stage_records", ())
            )
            unsatisfied_critical_evidence_item_ids = list(
                getattr(self.retriever, "last_unsatisfied_critical_evidence_item_ids", ())
            )
            dedup_removed_count = getattr(
                self.retriever, "last_dedup_removed_count", 0
            )
            if isinstance(dedup_removed_count, bool) or not isinstance(
                dedup_removed_count, int
            ):
                dedup_removed_count = 0
            validate_retrieval_stage_records(
                stage_records, requests, retrieval_round
            )
            register_retrieval_round(
                state,
                requests,
                candidates,
                is_gap=is_gap,
                candidate_stage_records=stage_records,
            )
            self._trace(
                "GAP_RETRIEVAL_VALIDATED" if is_gap else "INITIAL_RETRIEVAL_VALIDATED",
                state,
                request_count=len(requests),
                candidate_count=len(candidates),
                stage_record_count=len(stage_records),
                dedup_removed_count=dedup_removed_count,
                unsatisfied_critical_evidence_item_ids=unsatisfied_critical_evidence_item_ids,
            )
            return None
        except (ValidationError, StateInvariantError) as exc:
            return self._failure(state, TerminationReason.RETRIEVER_FAILURE, exc)
        except Exception as exc:
            return self._failure(state, TerminationReason.RETRIEVER_FAILURE, exc)

    def _assess_coverage(self, state: RunState) -> Optional[HarnessOutcome]:
        try:
            raw = self._execute(S2, "ASSESS_COVERAGE", self._coverage_payload(state))
            canonical_raw = dict(raw)
            encoded_diagnostics = canonical_raw.pop(
                "_harness_s2_projection_diagnostics", None
            )
            links, assessments, conflicts = validate_coverage_assessment(
                canonical_raw, state
            )
            projection_diagnostics = self._validated_s2_projection_diagnostics(
                encoded_diagnostics, assessments
            )
            for diagnostic in projection_diagnostics:
                details = {
                    "evidence_item_id": diagnostic.evidence_item_id,
                    "legal_status": diagnostic.legal_status,
                    "applicability_status": diagnostic.applicability_status,
                    "gap_type": diagnostic.gap_type,
                    "derived_status": diagnostic.derived_status,
                    "derived_partial_kind": diagnostic.derived_partial_kind,
                    "derived_governing_legal_regime": diagnostic.derived_governing_legal_regime,
                    "raw_projection_disposition": dict(
                        diagnostic.raw_projection_disposition
                    ),
                }
                self._trace("S2_LEGACY_PROJECTION_DERIVED", state, **details)
            apply_coverage_assessment(state, links, assessments, conflicts)
            self._trace("COVERAGE_ASSESSMENT_VALIDATED", state)
            return None
        except (ValidationError, StateInvariantError, RuntimeError) as exc:
            return self._failure(state, TerminationReason.INVALID_SKILL_OUTPUT, exc)

    @staticmethod
    def _validated_s2_projection_diagnostics(
        encoded: Any,
        assessments: Sequence,
    ) -> List[S2LegacyProjectionDiagnostic]:
        """Accept only the executor's bounded, complete S2 projection audit."""
        if encoded is None:
            # Non-local legacy executors have no c06 private transport field.
            return []
        if not isinstance(encoded, list):
            raise ValidationError("S2 projection diagnostics must be a list")
        expected = {
            assessment.evidence_item_id: assessment for assessment in assessments
        }
        if len(encoded) != len(expected):
            raise ValidationError("S2 projection diagnostics must cover each assessment once")
        diagnostics = []
        seen = set()
        for raw in encoded:
            if not isinstance(raw, Mapping):
                raise ValidationError("S2 projection diagnostic must be an object")
            evidence_item_id = raw.get("evidence_item_id")
            if not isinstance(evidence_item_id, str) or evidence_item_id not in expected:
                raise ValidationError("S2 projection diagnostic references unknown evidence")
            if evidence_item_id in seen:
                raise ValidationError("S2 projection diagnostic repeats evidence")
            seen.add(evidence_item_id)
            assessment = expected[evidence_item_id]
            expected_values = {
                "legal_status": assessment.legal_status.value,
                "applicability_status": assessment.applicability_status.value,
                "gap_type": assessment.gap_type.value,
                "derived_status": assessment.status.value,
                "derived_partial_kind": assessment.partial_kind,
                "derived_governing_legal_regime": assessment.governing_legal_regime.value,
            }
            if any(raw.get(key) != value for key, value in expected_values.items()):
                raise ValidationError("S2 projection diagnostic conflicts with canonical assessment")
            disposition = raw.get("raw_projection_disposition")
            if not isinstance(disposition, Mapping):
                raise ValidationError("S2 projection diagnostic disposition must be an object")
            if set(disposition) != {
                "disposition",
                "status",
                "partial_kind",
                "governing_legal_regime",
                "missing_evidence_items",
                "evidence_conflicts",
            }:
                raise ValidationError("S2 projection diagnostic disposition fields are invalid")
            disposition_name = disposition.get("disposition")
            if (
                not isinstance(disposition_name, str)
                or disposition_name not in {"omitted", "suppressed"}
            ):
                raise ValidationError("S2 projection diagnostic disposition is invalid")
            HarnessRunner._validate_s2_projection_value(
                disposition.get("status"),
                {"status", "evidence_status", "both", "omitted"},
                {"covered", "partially_covered", "uncovered", "conflicting"},
            )
            HarnessRunner._validate_s2_projection_value(
                disposition.get("partial_kind"),
                {"partial_kind", "omitted"},
                {"not_applicable", "factual_condition", "legal_support_gap"},
            )
            HarnessRunner._validate_s2_projection_value(
                disposition.get("governing_legal_regime"),
                {"governing_legal_regime", "omitted"},
                {"direct_entailment", "not_direct_entailment", "not_assessed"},
            )
            for key in ("missing_evidence_items", "evidence_conflicts"):
                ledger = disposition.get(key)
                if not isinstance(ledger, Mapping) or set(ledger) != {
                    "present",
                    "count",
                    "shape",
                }:
                    raise ValidationError("S2 projection diagnostic ledger disposition is invalid")
                count = ledger.get("count")
                if (
                    isinstance(count, bool)
                    or not isinstance(count, int)
                    or count < 0
                    or count > len(expected) + 1
                ):
                    raise ValidationError("S2 projection diagnostic ledger count is invalid")
                shape = ledger.get("shape")
                if (
                    not isinstance(ledger.get("present"), bool)
                    or not isinstance(shape, str)
                    or shape not in {"list", "invalid", "omitted"}
                ):
                    raise ValidationError("S2 projection diagnostic ledger shape is invalid")
            diagnostics.append(
                S2LegacyProjectionDiagnostic(
                    evidence_item_id=evidence_item_id,
                    legal_status=expected_values["legal_status"],
                    applicability_status=expected_values["applicability_status"],
                    gap_type=expected_values["gap_type"],
                    derived_status=expected_values["derived_status"],
                    derived_partial_kind=expected_values["derived_partial_kind"],
                    derived_governing_legal_regime=expected_values[
                        "derived_governing_legal_regime"
                    ],
                    raw_projection_disposition=dict(disposition),
                )
            )
        if seen != set(expected):
            raise ValidationError("S2 projection diagnostics omit an assessment")
        return diagnostics

    @staticmethod
    def _validate_s2_projection_value(
        value: Any,
        allowed_sources: set,
        allowed_values: set,
    ) -> None:
        if not isinstance(value, Mapping) or set(value) != {
            "present",
            "source",
            "value",
        }:
            raise ValidationError("S2 projection diagnostic value disposition is invalid")
        present = value.get("present")
        source = value.get("source")
        raw_value = value.get("value")
        if (
            not isinstance(present, bool)
            or not isinstance(source, str)
            or source not in allowed_sources
        ):
            raise ValidationError("S2 projection diagnostic value metadata is invalid")
        if not present and (source != "omitted" or raw_value is not None):
            raise ValidationError("S2 omitted projection diagnostic is inconsistent")
        if present and (
            source == "omitted"
            or not isinstance(raw_value, str)
            or raw_value not in allowed_values | {"invalid"}
        ):
            raise ValidationError("S2 projection diagnostic value is invalid")

    def _generate_and_validate(self, state: RunState) -> HarnessOutcome:
        try:
            state.phase = Phase.GENERATING
            raw = self._execute(S3, "GENERATE_ANSWER", self._answer_payload(state))
            answer = validate_answer_draft(raw, state)
            state.last_validated_event = "S3.GENERATE_ANSWER"
            state.record(
                "ANSWER_DRAFT_VALIDATED",
                claim_count=len(answer.claims),
                answer_mode=state.answer_mode.value if state.answer_mode else None,
                answered_target_ids=state.answered_target_ids,
                deferred_target_ids=state.deferred_target_ids,
            )
            state.phase = Phase.VALIDATING_CITATIONS
            citation_result = self.citation_validator.validate(state, answer)
        except (ValidationError, RuntimeError) as exc:
            return self._failure(state, TerminationReason.INVALID_SKILL_OUTPUT, exc)
        except Exception as exc:
            return self._failure(state, TerminationReason.CITATION_INTEGRITY_FAILED, exc)

        if not citation_result.passed:
            return self._failure(
                state,
                TerminationReason.CITATION_INTEGRITY_FAILED,
                RuntimeError("; ".join(citation_result.errors)),
            )
        state.phase = Phase.COMPLETED
        state.last_validated_event = "D4.CITATION_INTEGRITY_PASS"
        state.record("CITATION_INTEGRITY_PASS")
        self._trace("RUN_COMPLETED", state)
        return HarnessOutcome(
            status=OutcomeStatus.ANSWER,
            state=state,
            answer=answer.answer,
            answer_mode=state.answer_mode,
            complete_answer=state.answer_mode is AnswerMode.FULL,
            answered_target_ids=list(state.answered_target_ids),
            deferred_target_ids=list(state.deferred_target_ids),
            termination_reason=TerminationReason.COMPLETED,
            candidate_answer=answer.answer,
            candidate_answer_status=CandidateAnswerStatus.PUBLISHED_ANSWER,
            claims=answer.structured_claims,
            claim_citations=answer.structured_claim_citations,
            assumptions=answer.assumptions,
            limitations=answer.limitations,
            candidate_answer_basis=CandidateAnswerBasis.PUBLISHED_ANSWER,
        )

    def _abstain(
        self,
        state: RunState,
        termination_reason: Optional[TerminationReason],
    ) -> HarnessOutcome:
        state.phase = Phase.ABSTAINED
        state.last_validated_event = "RESPONSE_ASSEMBLY.ABSTAIN"
        reason = abstention_reason_for(state)
        state.record(
            "ABSTAIN",
            abstention_reason=reason.value,
            termination_reason=(termination_reason.value if termination_reason else None),
        )
        self._trace("RUN_ABSTAINED", state, reason=reason.value)
        (
            candidate,
            candidate_status,
            candidate_basis,
            candidate_termination_reason,
            candidate_error,
        ) = self._generate_benchmark_candidate(state)
        return HarnessOutcome(
            status=OutcomeStatus.ABSTAIN,
            state=state,
            abstention_reason=reason,
            termination_reason=termination_reason,
            candidate_answer=candidate.answer if candidate is not None else None,
            candidate_answer_status=candidate_status,
            candidate_answer_basis=candidate_basis,
            candidate_answer_termination_reason=candidate_termination_reason,
            candidate_answer_error=candidate_error,
            candidate_claims=(
                candidate.structured_claims if candidate is not None else []
            ),
            candidate_claim_citations=(
                candidate.structured_claim_citations if candidate is not None else []
            ),
            candidate_assumptions=candidate.assumptions if candidate is not None else [],
            candidate_limitations=candidate.limitations if candidate is not None else [],
        )

    def _generate_benchmark_candidate(
        self, state: RunState
    ) -> tuple[
        Optional[AnswerDraft],
        CandidateAnswerStatus,
        CandidateAnswerBasis,
        Optional[TerminationReason],
        Optional[str],
    ]:
        payload = self._benchmark_candidate_payload(state)
        basis = CandidateAnswerBasis(payload["candidate_answer_basis"])
        try:
            state.record(
                "BENCHMARK_CANDIDATE_GENERATION_STARTED",
                candidate_provision_count=len(payload["candidate_provisions"]),
                candidate_answer_basis=basis.value,
            )
            raw = self._execute(
                S3,
                "GENERATE_BENCHMARK_CANDIDATE",
                payload,
            )
            candidate = validate_benchmark_candidate_draft(raw, state)
            state.record(
                "BENCHMARK_CANDIDATE_VALIDATED",
                claim_count=len(candidate.claims),
                candidate_provision_count=len(payload["candidate_provisions"]),
                candidate_answer_basis=basis.value,
            )
            self._trace("BENCHMARK_CANDIDATE_VALIDATED", state)
            return candidate, CandidateAnswerStatus.GENERATED, basis, None, None
        except (ValidationError, RuntimeError) as exc:
            return self._benchmark_candidate_failure(state, basis, exc)
        except Exception as exc:
            return self._benchmark_candidate_failure(state, basis, exc)

    def _benchmark_candidate_failure(
        self, state: RunState, basis: CandidateAnswerBasis, error: Exception
    ) -> tuple[None, CandidateAnswerStatus, CandidateAnswerBasis, TerminationReason, str]:
        termination_reason = TerminationReason.INVALID_SKILL_OUTPUT
        state.record(
            "BENCHMARK_CANDIDATE_EXECUTION_FAILURE",
            termination_reason=termination_reason.value,
            error=str(error),
        )
        self._trace(
            "BENCHMARK_CANDIDATE_EXECUTION_FAILURE",
            state,
            error=str(error),
            termination_reason=termination_reason.value,
        )
        return (
            None,
            CandidateAnswerStatus.EXECUTION_FAILURE,
            basis,
            termination_reason,
            str(error),
        )

    def _failure(
        self,
        state: RunState,
        termination_reason: TerminationReason,
        error: Exception,
    ) -> HarnessOutcome:
        state.phase = Phase.EXECUTION_FAILURE
        state.record("EXECUTION_FAILURE", termination_reason=termination_reason.value, error=str(error))
        self._trace("RUN_EXECUTION_FAILURE", state, error=str(error), termination_reason=termination_reason.value)
        return HarnessOutcome(
            status=OutcomeStatus.EXECUTION_FAILURE,
            state=state,
            termination_reason=termination_reason,
            errors=[str(error)],
        )

    def _execute(self, skill_name: str, entry_point: str, payload: Dict[str, Any]) -> Mapping[str, Any]:
        result = self.skill_executor.execute(skill_name, entry_point, payload)
        if not isinstance(result, Mapping):
            raise ValidationError("%s must return an object" % skill_name)
        return result

    @staticmethod
    def _validated_gap_plan_recovery(
        payload: Mapping[str, Any], request_count: int
    ) -> Optional[GapPlanRecovery]:
        recovery = payload.get("harness_gap_plan_recovery")
        if recovery is None:
            return None
        if not isinstance(recovery, GapPlanRecovery):
            raise ValidationError("gap-plan recovery must be harness-owned")
        if recovery.disposition not in {
            GapPlanRecoveryDisposition.REPAIR_INDUCED_HISTORY_COLLISION,
            GapPlanRecoveryDisposition.REPAIR_INDUCED_SIBLING_COLLISION,
        }:
            raise ValidationError("gap-plan recovery disposition is invalid")
        if (
            isinstance(recovery.dropped_request_count, bool)
            or not isinstance(recovery.dropped_request_count, int)
            or recovery.dropped_request_count < 1
            or isinstance(recovery.remaining_request_count, bool)
            or not isinstance(recovery.remaining_request_count, int)
            or recovery.remaining_request_count != request_count
            or recovery.dropped_request_count != len(recovery.dropped_request_ids)
            or recovery.dropped_request_count != len(recovery.repaired_query_sha256)
            or len(recovery.dropped_request_ids) != len(set(recovery.dropped_request_ids))
            or not all(
                isinstance(request_id, str) and request_id
                for request_id in recovery.dropped_request_ids
            )
            or not all(
                isinstance(query_hash, str)
                and re.fullmatch(r"[0-9a-f]{64}", query_hash)
                for query_hash in recovery.repaired_query_sha256
            )
            or (
                recovery.disposition
                is GapPlanRecoveryDisposition.REPAIR_INDUCED_SIBLING_COLLISION
                and (
                    recovery.dropped_request_count != 1
                    or recovery.remaining_request_count < 1
                )
            )
        ):
            raise ValidationError("gap-plan recovery audit is invalid")
        return recovery

    @staticmethod
    def _compact_coverage_assessments(
        assessments: Sequence[Any],
        *,
        include_links: bool,
        include_criteria: bool,
    ) -> List[Dict[str, Any]]:
        """Keep S2/S3 decision fields while omitting replay-only audit prose."""
        compact: List[Dict[str, Any]] = []
        for raw in to_primitive(assessments):
            if not isinstance(raw, Mapping):
                continue
            item: Dict[str, Any] = {}
            for field in (
                "evidence_item_id",
                "status",
                "partial_kind",
                "legal_status",
                "applicability_status",
                "gap_type",
                "governing_legal_regime",
                "missing_aspects",
            ):
                if field in raw:
                    item[field] = raw[field]
            if include_links and "linked_provision_ids" in raw:
                item["linked_provision_ids"] = raw["linked_provision_ids"]
            if include_criteria and isinstance(raw.get("criterion_results"), list):
                item["criterion_results"] = [
                    {
                        field: result[field]
                        for field in (
                            "requirement_id",
                            "status",
                            "linked_provision_ids",
                        )
                        if field in result
                    }
                    for result in raw["criterion_results"]
                    if isinstance(result, Mapping)
                ]
            compact.append(item)
        return compact

    @staticmethod
    def _coverage_candidate_payload(state: RunState) -> List[Dict[str, Any]]:
        """S2 needs legal text and identity, not retriever diagnostics."""
        return [
            {
                "provision_id": candidate.provision_id,
                "statute_name": candidate.statute_name,
                "provision_text": candidate.provision_text,
            }
            for candidate in state.candidate_provisions
        ]

    @staticmethod
    def _metadata_source_reference(candidate: Any) -> Optional[Dict[str, str]]:
        """Return a consensus source label used only to resolve body references."""
        parsed = []
        for raw_label in (candidate.provision_id, candidate.statute_name):
            if not isinstance(raw_label, str):
                continue
            label = raw_label.split("#", 1)[0].strip()
            match = METADATA_SOURCE_PATTERN.match(label)
            if not match:
                continue
            statute = " ".join(match.group("statute").split())
            if not statute:
                continue
            tail = match.group("tail")
            subarticle = METADATA_LEADING_SUBARTICLE_PATTERN.match(tail)
            article = "제%s조%s" % (
                match.group("article"),
                ("의" + subarticle.group("subarticle")) if subarticle else "",
            )
            paragraph_values = {
                paragraph_match.group("paragraph")
                for paragraph_match in METADATA_PARAGRAPH_PATTERN.finditer(tail)
            }
            if len(paragraph_values) > 1:
                return None
            paragraph = (
                "제%s항" % next(iter(paragraph_values))
                if paragraph_values
                else None
            )
            parsed.append((statute, article, paragraph))
        if not parsed:
            return None
        statute_article_pairs = {(statute, article) for statute, article, _ in parsed}
        if len(statute_article_pairs) != 1:
            return None
        paragraphs = {paragraph for _, _, paragraph in parsed if paragraph}
        if len(paragraphs) > 1:
            return None
        statute, article = next(iter(statute_article_pairs))
        source = {"statute": statute, "article": article}
        if paragraphs:
            source["paragraph"] = next(iter(paragraphs))
        return source

    @staticmethod
    def _candidate_cross_references(state: RunState) -> List[Dict[str, Any]]:
        """Expose compact, text-backed target statute references for GAP S1."""
        references: List[Dict[str, Any]] = []
        seen = set()

        def statute_name(match) -> str:
            quoted = match.group("quoted")
            if quoted:
                return " ".join(quoted.split())
            plain = " ".join(match.group("plain").split())
            # The reference grammar permits descriptive Korean words before an
            # unquoted statute.  The target is the adjacent, rightmost
            # law-named token, not that descriptive prefix.
            words = plain.split()
            for index in range(len(words) - 1, -1, -1):
                word = words[index]
                if (
                    word in {"시행령", "시행규칙"}
                    and index > 0
                    and words[index - 1] not in {"법", "법률"}
                    and words[index - 1].endswith(("법률", "법"))
                ):
                    return words[index - 1] + " " + word
                if word not in {"법", "법률", "시행령", "시행규칙"} and word.endswith(
                    ("시행규칙", "시행령", "법률", "법")
                ):
                    return word
            return plain

        def article_name(number: str, subarticle: Optional[str] = None) -> str:
            return "제%s조%s" % (number, ("의" + subarticle) if subarticle else "")

        def paragraph_name(number: Optional[str]) -> Optional[str]:
            return "제%s항" % number if number else None

        for candidate in state.candidate_provisions:
            source = HarnessRunner._metadata_source_reference(candidate)
            source_statute = source.get("statute") if source else None
            source_article = source.get("article") if source else None
            source_paragraph = source.get("paragraph") if source else None
            heading = BODY_SOURCE_HEADING_PATTERN.match(candidate.provision_text)
            heading_is_consistent = False
            if heading and source_statute and source_article:
                body_article = article_name(heading.group(1), heading.group(2))
                body_paragraph = paragraph_name(heading.group(3))
                metadata_is_base_for_body_subarticle = (
                    "의" not in source_article
                    and body_article.startswith(source_article + "의")
                )
                if (body_article == source_article or metadata_is_base_for_body_subarticle) and (
                    not body_paragraph
                    or not source_paragraph
                    or body_paragraph == source_paragraph
                ):
                    source_article = body_article
                    source_paragraph = body_paragraph or source_paragraph
                    heading_is_consistent = True
                else:
                    # Conflicting metadata and body headings cannot resolve inherited references.
                    source_statute = None
                    source_article = None
                    source_paragraph = None
            count = 0

            def add(target_statute_name: str, target_article: str, target_paragraph: Optional[str], start: int, end: int) -> None:
                nonlocal count
                key = (candidate.provision_id, target_statute_name, target_article, target_paragraph, start, end)
                if key in seen or count >= MAX_CANDIDATE_CROSS_REFERENCES_PER_PROVISION:
                    return
                seen.add(key)
                item: Dict[str, Any] = {
                    "source_candidate_id": candidate.provision_id,
                    "target_statute_name": target_statute_name,
                    "target_article": target_article,
                    "excerpt": candidate.provision_text[start:end],
                    "start_char": start,
                    "end_char": end,
                }
                if target_paragraph:
                    item["target_paragraph"] = target_paragraph
                references.append(item)
                count += 1

            qualified_matches = list(
                QUALIFIED_REFERENCE_PATTERN.finditer(candidate.provision_text)
            )
            qualified_spans = [match.span() for match in qualified_matches]
            range_prefix_spans = [
                match.span()
                for match in RANGE_REFERENCE_PREFIX_PATTERN.finditer(candidate.provision_text)
            ]
            heading_span = heading.span() if heading_is_consistent else None

            def reserved_source_count_before(offset: int) -> int:
                """Conservatively reserve earlier bare references for range atomicity."""
                reserved = set()
                for direct_match in SOURCE_REFERENCE_PATTERN.finditer(
                    candidate.provision_text
                ):
                    if direct_match.start() >= offset:
                        continue
                    if any(
                        direct_match.start() < end and start < direct_match.end()
                        for start, end in qualified_spans + range_prefix_spans
                    ):
                        continue
                    if heading_span and direct_match.span() == heading_span:
                        continue
                    reserved.add(direct_match.span())
                return len(reserved)

            for match in qualified_matches:
                if candidate.provision_text[match.end():].lstrip().startswith("부터"):
                    continue
                target_statute = statute_name(match)
                start_number = int(match.group("article"))
                end_number = match.group("range_article")
                if end_number is None:
                    add(
                        target_statute,
                        article_name(match.group("article"), match.group("subarticle")),
                        paragraph_name(match.group("paragraph")),
                        match.start(),
                        match.end(),
                    )
                    continue
                end_value = int(end_number)
                if (
                    match.group("subarticle")
                    or match.group("paragraph")
                    or match.group("range_subarticle")
                    or match.group("range_paragraph")
                    or end_value < start_number
                    or end_value - start_number + 1 > MAX_CANDIDATE_CROSS_REFERENCES_PER_PROVISION
                    # Never emit only a prefix of an explicit range after
                    # earlier outbound references used this candidate's cap.
                    or end_value - start_number + 1
                    > MAX_CANDIDATE_CROSS_REFERENCES_PER_PROVISION
                    - count
                    - reserved_source_count_before(match.start())
                ):
                    continue
                for number in range(start_number, end_value + 1):
                    add(target_statute, article_name(str(number)), None, match.start(), match.end())

            # A bare range inherits the trusted source statute.  Process it
            # before direct references so neither endpoint leaks through as a
            # misleading one-article anchor when the range is invalid.
            unqualified_range_spans = []
            if source_statute:
                for range_match in UNQUALIFIED_SOURCE_RANGE_PATTERN.finditer(
                    candidate.provision_text
                ):
                    unqualified_range_spans.append(range_match.span())
                    if any(
                        range_match.start() < end and start < range_match.end()
                        for start, end in qualified_spans
                    ):
                        continue
                    start_value = int(range_match.group("article"))
                    end_value = int(range_match.group("range_article"))
                    if (
                        end_value < start_value
                        or end_value - start_value + 1
                        > MAX_CANDIDATE_CROSS_REFERENCES_PER_PROVISION
                        # A bounded range is an atomic provenance claim: do
                        # not leave a partial prefix when prior references
                        # already used the per-candidate cap.
                        or end_value - start_value + 1
                        > MAX_CANDIDATE_CROSS_REFERENCES_PER_PROVISION
                        - count
                        - reserved_source_count_before(range_match.start())
                    ):
                        continue
                    for number in range(start_value, end_value + 1):
                        add(
                            source_statute,
                            article_name(str(number)),
                            None,
                            range_match.start(),
                            range_match.end(),
                        )

            for match in SOURCE_REFERENCE_PATTERN.finditer(candidate.provision_text):
                if not source_statute:
                    continue
                if any(
                    match.start() < end and start < match.end()
                    for start, end in (
                        qualified_spans
                        + range_prefix_spans
                        + unqualified_range_spans
                    )
                ):
                    continue
                if heading_span and match.span() == heading_span:
                    continue
                add(
                    source_statute,
                    article_name(match.group(1), match.group(2)),
                    paragraph_name(match.group(3)),
                    match.start(),
                    match.end(),
                )

            if source_article and source_statute:
                source_number = re.fullmatch(r"제([0-9]+)조", source_article)
                source_paragraph_match = re.fullmatch(r"제([0-9]+)항", source_paragraph or "")
                for match in RELATIVE_REFERENCE_PATTERN.finditer(candidate.provision_text):
                    kind = match.group(1)
                    if kind == "항" and source_paragraph_match and int(source_paragraph_match.group(1)) > 1:
                        add(
                            source_statute, source_article,
                            paragraph_name(str(int(source_paragraph_match.group(1)) - 1)),
                            match.start(), match.end(),
                        )
                    elif source_number and kind.endswith("조"):
                        distance = 1 if kind == "조" else int(kind[:-1])
                        current_article = int(source_number.group(1))
                        if current_article > distance:
                            add(source_statute, article_name(str(current_article - distance)), None, match.start(), match.end())
        return references

    def _coverage_payload(self, state: RunState) -> Dict[str, Any]:
        return {
            "run_id": state.run_id,
            "normalized_question": state.normalized_question,
            "legal_issues": to_primitive(state.legal_issues),
            "answer_targets": to_primitive(state.answer_targets),
            "required_evidence_items": to_primitive(state.required_evidence_items),
            "candidate_provisions": self._coverage_candidate_payload(state),
            "prior_coverage_assessments": self._compact_coverage_assessments(
                state.coverage_assessments,
                include_links=True,
                include_criteria=True,
            ),
        }

    def _gap_payload(self, state: RunState) -> Dict[str, Any]:
        return {
            "run_id": state.run_id,
            "normalized_question": state.normalized_question,
            "next_retrieval_round": state.retrieval_rounds_used + 1,
            "legal_issues": to_primitive(state.legal_issues),
            "answer_targets": to_primitive(state.answer_targets),
            "required_evidence_items": to_primitive(state.required_evidence_items),
            "coverage_assessments": self._compact_coverage_assessments(
                state.coverage_assessments,
                include_links=True,
                include_criteria=True,
            ),
            "missing_evidence_items": to_primitive(state.missing_critical_items),
            "evidence_conflicts": to_primitive(state.unresolved_critical_conflicts()),
            "accepted_provision_ids": sorted(state.accepted_provision_ids),
            "query_history": to_primitive(state.query_history),
            "candidate_cross_references": self._candidate_cross_references(state),
            "seen_provision_ids": sorted(state.seen_provision_ids),
            "remaining_request_budget": state.remaining_request_budget,
        }

    def _answer_payload(self, state: RunState) -> Dict[str, Any]:
        supported_evidence_by_provision: Dict[str, List[str]] = {}
        roles_by_provision: Dict[str, List[str]] = {}
        for link in state.evidence_links:
            if link.assessment == "accepted":
                supported_evidence_by_provision.setdefault(link.provision_id, []).append(
                    link.evidence_item_id
                )
                roles_by_provision.setdefault(link.provision_id, []).append(
                    link.role.value
                )

        def provisions_for(provision_ids: Sequence[str]) -> List[Dict[str, Any]]:
            accepted = []
            for candidate in state.candidate_provisions:
                if candidate.provision_id not in provision_ids:
                    continue
                payload = to_primitive(candidate)
                payload["supported_evidence_item_ids"] = sorted(
                    set(supported_evidence_by_provision.get(candidate.provision_id, []))
                )
                payload["evidence_roles"] = sorted(
                    set(roles_by_provision.get(candidate.provision_id, []))
                )
                accepted.append(payload)
            return accepted

        accepted = provisions_for(state.accepted_provision_ids)
        core_accepted = provisions_for(state.core_accepted_provision_ids)
        supplemental = provisions_for(state.supplemental_provision_ids)
        qualifying = provisions_for(state.qualifying_provision_ids)
        alternative = provisions_for(state.alternative_provision_ids)
        qualifying_public_exception_links = [
            {
                "provision_id": link.provision_id,
                "evidence_item_id": link.evidence_item_id,
            }
            for link in state.evidence_links
            if link.assessment == "accepted" and link.role is EvidenceRole.QUALIFYING
        ]
        return {
            "run_id": state.run_id,
            "question": state.question,
            "normalized_question": state.normalized_question,
            "legal_issues": to_primitive(state.legal_issues),
            "answer_targets": to_primitive(state.answer_targets),
            "required_evidence_items": to_primitive(state.required_evidence_items),
            "coverage_assessments": HarnessRunner._compact_coverage_assessments(
                state.coverage_assessments,
                include_links=True,
                include_criteria=True,
            ),
            "accepted_provisions": to_primitive(accepted),
            "core_accepted_provisions": to_primitive(core_accepted),
            "supplemental_provisions": to_primitive(supplemental),
            "qualifying_provisions": to_primitive(qualifying),
            # C39: this accepted link proof is validator-only and must never
            # enter an S3 model prompt.
            "_harness_c39_qualifying_public_exception_links": qualifying_public_exception_links,
            "alternative_provisions": to_primitive(alternative),
            "answer_mode": state.answer_mode.value if state.answer_mode else AnswerMode.FULL.value,
            "answered_target_ids": list(state.answered_target_ids),
            "deferred_target_ids": list(state.deferred_target_ids),
            "state_version": len(state.action_trace),
        }

    def _benchmark_candidate_payload(self, state: RunState) -> Dict[str, Any]:
        requests_by_id = {
            request.request_id: request for request in state.query_history
        }
        candidates = []
        for candidate in state.candidate_provisions:
            payload = to_primitive(candidate)
            evidence_ids = list(candidate.target_evidence_item_ids)
            if not evidence_ids:
                source_ids = candidate.source_request_ids or [candidate.source_request_id]
                evidence_ids = [
                    requests_by_id[source_id].evidence_item_id
                    for source_id in source_ids
                    if source_id in requests_by_id
                ]
            if not evidence_ids:
                continue
            payload["supported_evidence_item_ids"] = list(dict.fromkeys(evidence_ids))
            candidates.append(payload)
        basis = (
            CandidateAnswerBasis.RETRIEVED_CANDIDATES.value
            if candidates
            else CandidateAnswerBasis.QUESTION_ONLY.value
        )
        return {
            "run_id": state.run_id,
            "question": state.question,
            "normalized_question": state.normalized_question,
            "legal_issues": to_primitive(state.legal_issues),
            "answer_targets": to_primitive(state.answer_targets),
            "required_evidence_items": to_primitive(state.required_evidence_items),
            "coverage_assessments": self._compact_coverage_assessments(
                state.coverage_assessments,
                include_links=True,
                include_criteria=True,
            ),
            "accepted_provisions": [],
            "candidate_provisions": candidates,
            "candidate_answer_basis": basis,
            "answer_mode": "abstain_candidate",
            "answered_target_ids": [
                target.answer_target_id for target in state.answer_targets
            ],
            "deferred_target_ids": [],
            "state_version": len(state.action_trace),
        }

    def _apply_generation_scope(
        self,
        state: RunState,
        decision: PolicyDecision,
    ) -> None:
        state.answer_mode = decision.answer_mode or AnswerMode.FULL
        state.answered_target_ids = list(decision.answered_target_ids)
        state.deferred_target_ids = list(decision.deferred_target_ids)

    def _record_and_apply_generation_decision(
        self, state: RunState, decision: PolicyDecision
    ) -> None:
        record_policy_decision(
            state,
            decision.action.value,
            termination_reason=(
                decision.termination_reason.value if decision.termination_reason else None
            ),
            explanation=decision.explanation,
            answer_mode=decision.answer_mode.value if decision.answer_mode else None,
            answered_target_ids=decision.answered_target_ids,
            deferred_target_ids=decision.deferred_target_ids,
        )
        self._apply_generation_scope(state, decision)

    def _trace(self, event: str, state: RunState, **details: object) -> None:
        self.trace_sink.record(event, state, **details)
