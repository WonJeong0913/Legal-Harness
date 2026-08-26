"""Mutable run state and derived evidence-control fields."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .contracts import (
    ActionTrace,
    AnswerMode,
    AnswerTarget,
    CandidateProvision,
    CandidateStageRecord,
    CoverageAssessment,
    CoverageStatus,
    EvidenceRole,
    EvidenceConflict,
    EvidenceLink,
    GapType,
    GoverningLegalRegime,
    LegalIssue,
    LegalStatus,
    Phase,
    RequiredEvidenceItem,
    RetrievalRequest,
)


@dataclass
class RunState:
    question: str
    normalized_question: str
    run_id: str
    total_round_budget: int = 3
    remaining_round_budget: int = 3
    remaining_request_budget: int = 9
    phase: Phase = Phase.INITIALIZING
    legal_issues: List[LegalIssue] = field(default_factory=list)
    answer_targets: List[AnswerTarget] = field(default_factory=list)
    required_evidence_items: List[RequiredEvidenceItem] = field(default_factory=list)
    candidate_provisions: List[CandidateProvision] = field(default_factory=list)
    retrieval_stage_records: List[CandidateStageRecord] = field(default_factory=list)
    evidence_links: List[EvidenceLink] = field(default_factory=list)
    coverage_assessments: List[CoverageAssessment] = field(default_factory=list)
    missing_critical_items: List[RequiredEvidenceItem] = field(default_factory=list)
    evidence_conflicts: List[EvidenceConflict] = field(default_factory=list)
    # The authorized union is retained for auditability.  The role-specific
    # projections are derived from accepted links and must never be authored
    # independently.
    accepted_provision_ids: Set[str] = field(default_factory=set)
    core_accepted_provision_ids: Set[str] = field(default_factory=set)
    supplemental_provision_ids: Set[str] = field(default_factory=set)
    qualifying_provision_ids: Set[str] = field(default_factory=set)
    alternative_provision_ids: Set[str] = field(default_factory=set)
    seen_provision_ids: Set[str] = field(default_factory=set)
    query_history: List[RetrievalRequest] = field(default_factory=list)
    corpus_text_snapshots: Dict[str, str] = field(default_factory=dict)
    no_progress_rounds: int = 0
    retrieval_rounds_used: int = 0
    last_retrieval_new_provision_count: int = 0
    last_validated_event: Optional[str] = None
    answer_mode: Optional[AnswerMode] = None
    answered_target_ids: List[str] = field(default_factory=list)
    deferred_target_ids: List[str] = field(default_factory=list)
    action_trace: List[ActionTrace] = field(default_factory=list)
    # Harness-owned BGE-only request copies. Raw S1 requests remain unchanged.
    rerank_query_transforms: List[Dict[str, Any]] = field(default_factory=list)

    def candidate_by_id(self) -> Dict[str, CandidateProvision]:
        return {candidate.provision_id: candidate for candidate in self.candidate_provisions}

    def evidence_by_id(self) -> Dict[str, RequiredEvidenceItem]:
        return {
            item.evidence_item_id: item
            for item in self.required_evidence_items
        }

    def coverage_by_evidence_id(self) -> Dict[str, CoverageAssessment]:
        return {
            assessment.evidence_item_id: assessment
            for assessment in self.coverage_assessments
        }

    def answer_target_by_id(self) -> Dict[str, AnswerTarget]:
        return {
            target.answer_target_id: target for target in self.answer_targets
        }

    @staticmethod
    def legal_status_for(assessment: CoverageAssessment) -> LegalStatus:
        if assessment.legal_status is not None:
            return assessment.legal_status
        if (
            assessment.status is CoverageStatus.PARTIALLY_COVERED
            and assessment.partial_kind == "factual_condition"
        ):
            return LegalStatus.COVERED
        return LegalStatus(assessment.status.value)

    @staticmethod
    def governing_legal_regime_for(
        assessment: CoverageAssessment,
    ) -> GoverningLegalRegime:
        """Derive the pre-role meaning for legacy coverage assessments."""
        if assessment.governing_legal_regime is not None:
            return assessment.governing_legal_regime
        return (
            GoverningLegalRegime.DIRECT_ENTAILMENT
            if RunState.legal_status_for(assessment) is LegalStatus.COVERED
            else GoverningLegalRegime.NOT_DIRECT_ENTAILMENT
        )

    @staticmethod
    def gap_type_for(assessment: CoverageAssessment) -> GapType:
        if assessment.gap_type is not None:
            return assessment.gap_type
        if (
            assessment.status is CoverageStatus.PARTIALLY_COVERED
            and assessment.partial_kind == "factual_condition"
        ):
            return GapType.MISSING_FACT
        if assessment.status is CoverageStatus.CONFLICTING:
            return GapType.CONFLICT
        if assessment.status is CoverageStatus.COVERED:
            return GapType.NONE
        return GapType.MISSING_STATUTE

    def unresolved_critical_conflicts(self) -> List[EvidenceConflict]:
        evidence = self.evidence_by_id()
        return [
            conflict
            for conflict in self.evidence_conflicts
            if not conflict.resolved
            and evidence.get(conflict.evidence_item_id)
            and evidence[conflict.evidence_item_id].critical
        ]

    def has_critical_blockers(self) -> bool:
        coverage = self.coverage_by_evidence_id()
        for item in self.required_evidence_items:
            if not item.critical:
                continue
            assessment = coverage.get(item.evidence_item_id)
            if (
                assessment is None
                or self.legal_status_for(assessment) is not LegalStatus.COVERED
                or self.governing_legal_regime_for(assessment)
                is not GoverningLegalRegime.DIRECT_ENTAILMENT
            ):
                return True
        return False

    def _accepted_evidence_ids(self) -> Set[str]:
        return {
            link.evidence_item_id
            for link in self.evidence_links
            if link.assessment == "accepted" and link.role is EvidenceRole.CORE
        }

    def covered_answer_target_ids(self) -> List[str]:
        """Return targets whose complete critical legal support is citable."""
        if not self.answer_targets:
            return []
        coverage = self.coverage_by_evidence_id()
        accepted_evidence_ids = self._accepted_evidence_ids()
        covered = []
        for target in self.answer_targets:
            target_items = [
                item
                for item in self.required_evidence_items
                if item.critical and target.answer_target_id in item.answer_target_ids
            ]
            if target_items and all(
                coverage.get(item.evidence_item_id) is not None
                and self.legal_status_for(coverage[item.evidence_item_id])
                is LegalStatus.COVERED
                and self.governing_legal_regime_for(
                    coverage[item.evidence_item_id]
                )
                is GoverningLegalRegime.DIRECT_ENTAILMENT
                and item.evidence_item_id in accepted_evidence_ids
                for item in target_items
            ):
                covered.append(target.answer_target_id)
        return covered

    def all_answer_targets_legally_covered(self) -> bool:
        if not self.answer_targets:
            return not self.has_critical_blockers()
        return set(self.covered_answer_target_ids()) == {
            target.answer_target_id for target in self.answer_targets
        }

    def has_missing_fact(self) -> bool:
        coverage = self.coverage_by_evidence_id()
        return any(
            assessment is not None
            and self.gap_type_for(assessment) is GapType.MISSING_FACT
            for item in self.required_evidence_items
            if item.critical
            for assessment in [coverage.get(item.evidence_item_id)]
        )

    def has_retrievable_statute_gap(self) -> bool:
        coverage = self.coverage_by_evidence_id()
        return any(
            assessment is None
            or (
                self.legal_status_for(assessment) is not LegalStatus.COVERED
                and self.gap_type_for(assessment) is GapType.MISSING_STATUTE
            )
            for item in self.required_evidence_items
            if item.critical
            for assessment in [coverage.get(item.evidence_item_id)]
        )

    def has_any_citable_answer_target(self) -> bool:
        if self.answer_targets:
            return bool(self.covered_answer_target_ids())
        return bool(self.core_accepted_provision_ids)

    def partially_citable_answer_target_ids(self) -> List[str]:
        if not self.answer_targets:
            return []
        accepted_evidence_ids = self._accepted_evidence_ids()
        covered = set(self.covered_answer_target_ids())
        return [
            target.answer_target_id
            for target in self.answer_targets
            if target.answer_target_id not in covered
            and any(
                item.critical
                and target.answer_target_id in item.answer_target_ids
                and item.evidence_item_id in accepted_evidence_ids
                for item in self.required_evidence_items
            )
        ]

    def can_generate_conditionally(self) -> bool:
        """Compatibility helper for the factual-condition generation path."""
        return (
            not self.unresolved_critical_conflicts()
            and self.all_answer_targets_legally_covered()
            and self.has_missing_fact()
        )

    def refresh_derived_fields(self) -> None:
        """Rebuild fields that must never be independently authored."""
        evidence = self.evidence_by_id()
        coverage = self.coverage_by_evidence_id()
        candidate_ids = set(self.candidate_by_id())
        authorized_links = [
            link
            for link in self.evidence_links
            if link.assessment == "accepted"
            and link.provision_id in candidate_ids
            and link.evidence_item_id in evidence
        ]
        self.accepted_provision_ids = {
            link.provision_id
            for link in authorized_links
        }
        self.core_accepted_provision_ids = {
            link.provision_id
            for link in authorized_links
            if link.role is EvidenceRole.CORE
        }
        self.supplemental_provision_ids = {
            link.provision_id
            for link in authorized_links
            if link.role is EvidenceRole.SUPPLEMENTAL
        }
        self.qualifying_provision_ids = {
            link.provision_id
            for link in authorized_links
            if link.role is EvidenceRole.QUALIFYING
        }
        self.alternative_provision_ids = {
            link.provision_id
            for link in authorized_links
            if link.role is EvidenceRole.ALTERNATIVE
        }
        self.missing_critical_items = [
            item
            for item in self.required_evidence_items
            if item.critical
            and (
                item.evidence_item_id not in coverage
                or self.legal_status_for(coverage[item.evidence_item_id])
                is not LegalStatus.COVERED
                or self.governing_legal_regime_for(
                    coverage[item.evidence_item_id]
                )
                is not GoverningLegalRegime.DIRECT_ENTAILMENT
            )
        ]

    def record(self, event: str, **details: object) -> None:
        self.action_trace.append(
            ActionTrace(event=event, phase=self.phase, details=dict(details))
        )
