"""Validated state transitions and progress accounting."""

from dataclasses import replace
from typing import Iterable, List, Sequence

from .contracts import (
    AnswerTarget,
    CandidateProvision,
    CandidateStageRecord,
    CoverageAssessment,
    CoverageStatus,
    CriterionStatus,
    EvidenceConflict,
    EvidenceLink,
    LegalStatus,
    LegalIssue,
    Phase,
    RequiredEvidenceItem,
    RetrievalRequest,
)
from .run_state import RunState


class StateInvariantError(ValueError):
    pass


def apply_initial_plan(
    state: RunState,
    legal_issues: Sequence[LegalIssue],
    required_evidence_items: Sequence[RequiredEvidenceItem],
    answer_targets: Sequence[AnswerTarget] = (),
) -> None:
    if state.legal_issues or state.required_evidence_items:
        raise StateInvariantError("initial plan can only be applied once")
    state.legal_issues = list(legal_issues)
    state.answer_targets = list(answer_targets)
    state.required_evidence_items = list(required_evidence_items)
    state.phase = Phase.PLANNING_INITIAL
    state.last_validated_event = "S1.INITIAL_PLAN"
    state.record("INITIAL_PLAN_VALIDATED", issue_count=len(legal_issues), evidence_count=len(required_evidence_items))


def _ordered_union(*groups: Sequence[str]) -> List[str]:
    return list(dict.fromkeys(value for group in groups for value in group))


def _best_optional_rank(*values):
    present = [value for value in values if value is not None]
    return min(present) if present else None


def _merge_candidate_provenance(
    previous: CandidateProvision,
    incoming: CandidateProvision,
) -> CandidateProvision:
    """Keep the first observation and merge origins without cross-query scores."""
    if (
        previous.statute_name != incoming.statute_name
        or previous.provision_text != incoming.provision_text
    ):
        raise StateInvariantError(
            "the same provision_id cannot identify different corpus snapshots"
        )
    previous_sources = previous.source_request_ids or [previous.source_request_id]
    incoming_sources = incoming.source_request_ids or [incoming.source_request_id]
    source_request_ids = _ordered_union(
        [previous.source_request_id], previous_sources, incoming_sources
    )
    return replace(
        previous,
        source_request_ids=source_request_ids,
        target_evidence_item_ids=_ordered_union(
            previous.target_evidence_item_ids,
            incoming.target_evidence_item_ids,
        ),
        alias_provision_ids=_ordered_union(
            previous.alias_provision_ids,
            incoming.alias_provision_ids,
        ),
        # Scalar rank/score fields describe the retained first observation.
        # Cross-round and cross-query comparison belongs in the immutable
        # stage sidecar, where each observation keeps its local rank.
        first_stage_rank=previous.first_stage_rank,
        fusion_rank=previous.fusion_rank,
        rerank_rank=previous.rerank_rank,
        selection_rank=previous.selection_rank,
    )


def register_retrieval_round(
    state: RunState,
    requests: Sequence[RetrievalRequest],
    candidates: Sequence[CandidateProvision],
    is_gap: bool,
    candidate_stage_records: Sequence[CandidateStageRecord] = (),
) -> None:
    if not requests:
        raise StateInvariantError("a retrieval round requires at least one request")
    if state.remaining_round_budget <= 0:
        raise StateInvariantError("retrieval round budget is exhausted")
    if len(requests) > state.remaining_request_budget:
        raise StateInvariantError("retrieval request budget is exhausted")
    expected_round = state.retrieval_rounds_used + 1
    if any(candidate.retrieval_round != expected_round for candidate in candidates):
        raise StateInvariantError("candidate retrieval_round does not match the state")

    existing = state.candidate_by_id()
    new_ids = {candidate.provision_id for candidate in candidates if candidate.provision_id not in existing}
    for candidate in candidates:
        previous = existing.get(candidate.provision_id)
        if previous is None:
            existing[candidate.provision_id] = candidate
        else:
            existing[candidate.provision_id] = _merge_candidate_provenance(previous, candidate)
        state.corpus_text_snapshots.setdefault(candidate.provision_id, candidate.provision_text)
    state.candidate_provisions = list(existing.values())
    state.retrieval_stage_records.extend(candidate_stage_records)
    state.seen_provision_ids.update(candidate.provision_id for candidate in candidates)
    state.query_history.extend(requests)
    state.remaining_round_budget -= 1
    state.remaining_request_budget -= len(requests)
    state.retrieval_rounds_used = expected_round
    state.last_retrieval_new_provision_count = len(new_ids)
    state.phase = Phase.RETRIEVING_GAP if is_gap else Phase.RETRIEVING_INITIAL
    state.last_validated_event = "D2.GAP_RETRIEVAL" if is_gap else "D2.INITIAL_RETRIEVAL"
    state.record(
        "GAP_RETRIEVAL_VALIDATED" if is_gap else "INITIAL_RETRIEVAL_VALIDATED",
        request_count=len(requests),
        candidate_count=len(candidates),
        new_provision_count=len(new_ids),
        retrieval_round=expected_round,
    )


_MONOTONIC_LEGAL_STATUS_RANK = {
    LegalStatus.UNCOVERED: 0,
    LegalStatus.PARTIALLY_COVERED: 1,
    LegalStatus.COVERED: 2,
}


_CRITERION_STATUS_RANK = {
    CriterionStatus.UNSATISFIED: 0,
    CriterionStatus.CONFLICTING: 0,
    CriterionStatus.PARTIALLY_SATISFIED: 1,
    CriterionStatus.SATISFIED: 2,
}


def _critical_criterion_improved(previous, current, critical_ids):
    for evidence_id in critical_ids:
        prior = previous.get(evidence_id)
        assessment = current.get(evidence_id)
        if prior is None or assessment is None:
            continue
        prior_results = {
            result.requirement_id: result.status
            for result in prior.criterion_results
        }
        for result in assessment.criterion_results:
            prior_status = prior_results.get(result.requirement_id)
            if (
                prior_status in _CRITERION_STATUS_RANK
                and result.status in _CRITERION_STATUS_RANK
                and _CRITERION_STATUS_RANK[result.status]
                > _CRITERION_STATUS_RANK[prior_status]
            ):
                return True
    return False


def apply_coverage_assessment(
    state: RunState,
    evidence_links: Sequence[EvidenceLink],
    coverage_assessments: Sequence[CoverageAssessment],
    evidence_conflicts: Sequence[EvidenceConflict],
) -> bool:
    previous = state.coverage_by_evidence_id()
    previous_unresolved_critical_conflict_ids = {
        conflict.evidence_item_id
        for conflict in state.unresolved_critical_conflicts()
    }
    previous_partially_citable_target_ids = set(
        state.partially_citable_answer_target_ids()
    )
    incoming = {
        assessment.evidence_item_id: assessment
        for assessment in coverage_assessments
    }
    unresolved_conflict_ids = {
        conflict.evidence_item_id
        for conflict in evidence_conflicts
        if not conflict.resolved
    }
    current = {}
    preserved_ids = set()
    for item in state.required_evidence_items:
        evidence_id = item.evidence_item_id
        assessment = incoming[evidence_id]
        prior = previous.get(evidence_id)
        if (
            prior is not None
            and evidence_id not in unresolved_conflict_ids
            and state.legal_status_for(prior) in _MONOTONIC_LEGAL_STATUS_RANK
            and state.legal_status_for(assessment) in _MONOTONIC_LEGAL_STATUS_RANK
            and _MONOTONIC_LEGAL_STATUS_RANK[state.legal_status_for(prior)]
            > _MONOTONIC_LEGAL_STATUS_RANK[state.legal_status_for(assessment)]
        ):
            current[evidence_id] = prior
            preserved_ids.add(evidence_id)
        else:
            current[evidence_id] = assessment
    critical_ids = {
        item.evidence_item_id
        for item in state.required_evidence_items
        if item.critical
    }
    incoming_links = list(evidence_links)
    retained_links = [
        link
        for link in state.evidence_links
        if link.evidence_item_id in preserved_ids
        and link.provision_id in current[link.evidence_item_id].linked_provision_ids
    ]
    link_by_key = {
        (link.evidence_item_id, link.provision_id, link.assessment): link
        for link in retained_links + incoming_links
        if link.evidence_item_id not in preserved_ids or link in retained_links
    }
    state.evidence_links = list(link_by_key.values())
    state.coverage_assessments = [
        current[item.evidence_item_id] for item in state.required_evidence_items
    ]
    state.evidence_conflicts = list(evidence_conflicts)
    state.refresh_derived_fields()
    status_improved = any(
        evidence_id in critical_ids
        and evidence_id in previous
        and state.legal_status_for(previous[evidence_id])
        in _MONOTONIC_LEGAL_STATUS_RANK
        and state.legal_status_for(assessment) in _MONOTONIC_LEGAL_STATUS_RANK
        and _MONOTONIC_LEGAL_STATUS_RANK[state.legal_status_for(assessment)]
        > _MONOTONIC_LEGAL_STATUS_RANK[state.legal_status_for(previous[evidence_id])]
        for evidence_id, assessment in current.items()
    )
    criterion_improved = _critical_criterion_improved(previous, current, critical_ids)
    resolved_critical_conflict = bool(
        previous_unresolved_critical_conflict_ids
        - {conflict.evidence_item_id for conflict in state.unresolved_critical_conflicts()}
    )
    newly_partially_citable_target = bool(
        set(state.partially_citable_answer_target_ids())
        - previous_partially_citable_target_ids
    )
    progress = (
        status_improved
        or criterion_improved
        or resolved_critical_conflict
        or newly_partially_citable_target
    )
    state.no_progress_rounds = 0 if progress else state.no_progress_rounds + 1
    state.phase = Phase.ASSESSING_COVERAGE
    state.last_validated_event = "S2.ASSESS_COVERAGE"
    state.record(
        "COVERAGE_ASSESSMENT_VALIDATED",
        progress=progress,
        no_progress_rounds=state.no_progress_rounds,
        missing_critical_count=len(state.missing_critical_items),
        unresolved_conflict_count=len(state.unresolved_critical_conflicts()),
        status_improved=status_improved,
        criterion_improved=criterion_improved,
        resolved_critical_conflict=resolved_critical_conflict,
        newly_partially_citable_target=newly_partially_citable_target,
    )
    return progress


def record_policy_decision(state: RunState, action: str, **details: object) -> None:
    state.record("POLICY_DECISION", action=action, **details)
