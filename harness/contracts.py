"""Typed contracts shared by the harness, retrieval layer, and future skills."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Phase(str, Enum):
    INITIALIZING = "INITIALIZING"
    PLANNING_INITIAL = "PLANNING_INITIAL"
    RETRIEVING_INITIAL = "RETRIEVING_INITIAL"
    ASSESSING_COVERAGE = "ASSESSING_COVERAGE"
    PLANNING_GAP = "PLANNING_GAP"
    RETRIEVING_GAP = "RETRIEVING_GAP"
    GENERATING = "GENERATING"
    VALIDATING_CITATIONS = "VALIDATING_CITATIONS"
    COMPLETED = "COMPLETED"
    ABSTAINED = "ABSTAINED"
    EXECUTION_FAILURE = "EXECUTION_FAILURE"


class PolicyAction(str, Enum):
    RETRIEVE_GAP = "RETRIEVE_GAP"
    GENERATE = "GENERATE"
    ABSTAIN = "ABSTAIN"


class CoverageStatus(str, Enum):
    COVERED = "covered"
    PARTIALLY_COVERED = "partially_covered"
    UNCOVERED = "uncovered"
    CONFLICTING = "conflicting"


class LegalStatus(str, Enum):
    COVERED = "covered"
    PARTIALLY_COVERED = "partially_covered"
    UNCOVERED = "uncovered"
    CONFLICTING = "conflicting"


class ApplicabilityStatus(str, Enum):
    DIRECT = "direct"
    CONDITIONAL = "conditional"
    NOT_ASSESSED = "not_assessed"


class GapType(str, Enum):
    NONE = "none"
    MISSING_STATUTE = "missing_statute"
    MISSING_FACT = "missing_fact"
    SCOPE_EXCESS = "scope_excess"
    CONFLICT = "conflict"


class CriterionStatus(str, Enum):
    SATISFIED = "satisfied"
    PARTIALLY_SATISFIED = "partially_satisfied"
    UNSATISFIED = "unsatisfied"
    CONFLICTING = "conflicting"


class EvidenceRole(str, Enum):
    """The legal function a provision has for one evidence link.

    Only CORE evidence may establish a governing legal regime or support a
    public conclusion.  The three auxiliary roles remain authorized evidence
    for the structured audit trail, but cannot silently satisfy coverage.
    """

    CORE = "CORE"
    SUPPLEMENTAL = "SUPPLEMENTAL"
    QUALIFYING = "QUALIFYING"
    ALTERNATIVE = "ALTERNATIVE"


class GoverningLegalRegime(str, Enum):
    """Whether core evidence directly entails the governing legal regime."""

    DIRECT_ENTAILMENT = "direct_entailment"
    NOT_DIRECT_ENTAILMENT = "not_direct_entailment"
    NOT_ASSESSED = "not_assessed"


class AnswerMode(str, Enum):
    FULL = "full"
    CONDITIONAL = "conditional"
    LIMITED = "limited"


class CandidateAnswerStatus(str, Enum):
    PUBLISHED_ANSWER = "PUBLISHED_ANSWER"
    GENERATED = "GENERATED"
    EXECUTION_FAILURE = "EXECUTION_FAILURE"


class CandidateAnswerBasis(str, Enum):
    PUBLISHED_ANSWER = "published_answer"
    RETRIEVED_CANDIDATES = "retrieved_candidates"
    QUESTION_ONLY = "question_only"


class QueryChannel(str, Enum):
    PROVISION_STYLE = "provision_style"
    SPARSE_KEYWORD = "sparse_keyword"
    STATUTE_AWARE = "statute_aware"


class GapPlanRecoveryDisposition(str, Enum):
    """A harness-only disposition for a repaired S1 gap-plan collision."""

    REPAIR_INDUCED_HISTORY_COLLISION = "repair_induced_history_collision"
    REPAIR_INDUCED_SIBLING_COLLISION = (
        "repair_induced_intra_output_sibling_collision"
    )
    MODEL_MIXED_HISTORY_COLLISION = "model_mixed_history_collision_projection"


@dataclass(frozen=True)
class GapPlanRecovery:
    """Auditable recovery metadata that cannot originate in S1 JSON."""

    disposition: GapPlanRecoveryDisposition
    dropped_request_ids: List[str]
    repaired_query_sha256: List[str]
    dropped_request_count: int
    remaining_request_count: int


@dataclass(frozen=True)
class S2LegacyProjectionDiagnostic:
    """Bounded harness-owned audit of an S2 legacy projection.

    This record is created only after the raw atomic axes have passed the
    compact transport boundary.  It deliberately contains enum values, IDs,
    and bounded ledger counts only: no question, statute, source, or gold text
    may cross this diagnostic boundary.
    """

    evidence_item_id: str
    legal_status: str
    applicability_status: str
    gap_type: str
    derived_status: str
    derived_partial_kind: str
    derived_governing_legal_regime: str
    raw_projection_disposition: Dict[str, Any]


class AbstentionReason(str, Enum):
    INSUFFICIENT_CRITICAL_EVIDENCE = "INSUFFICIENT_CRITICAL_EVIDENCE"
    UNRESOLVED_EVIDENCE_CONFLICT = "UNRESOLVED_EVIDENCE_CONFLICT"


class TerminationReason(str, Enum):
    COMPLETED = "COMPLETED"
    RETRIEVAL_BUDGET_EXHAUSTED = "RETRIEVAL_BUDGET_EXHAUSTED"
    MAX_RETRIEVAL_ROUNDS_REACHED = "MAX_RETRIEVAL_ROUNDS_REACHED"
    NO_RETRIEVAL_PROGRESS = "NO_RETRIEVAL_PROGRESS"
    NO_VALID_GAP_QUERY = "NO_VALID_GAP_QUERY"
    INVALID_SKILL_OUTPUT = "INVALID_SKILL_OUTPUT"
    SKILL_EXECUTION_FAILED = "SKILL_EXECUTION_FAILED"
    RETRIEVER_FAILURE = "RETRIEVER_FAILURE"
    CITATION_INTEGRITY_FAILED = "CITATION_INTEGRITY_FAILED"


class OutcomeStatus(str, Enum):
    ANSWER = "ANSWER"
    ABSTAIN = "ABSTAIN"
    EXECUTION_FAILURE = "EXECUTION_FAILURE"


@dataclass(frozen=True)
class LegalIssue:
    issue_id: str
    description: str


@dataclass(frozen=True)
class RequiredEvidenceItem:
    evidence_item_id: str
    issue_id: str
    evidence_type: str
    description: str
    critical: bool

    completion_criteria: str = ""
    necessity_reason: str = ""
    answer_target_ids: List[str] = field(default_factory=list)
    scope_source: str = "legacy"
    completion_requirements: List["CompletionRequirement"] = field(default_factory=list)


@dataclass(frozen=True)
class AnswerTarget:
    answer_target_id: str
    question_anchor: str
    requested_output: str
    answer_type: str


@dataclass(frozen=True)
class CompletionRequirement:
    requirement_id: str
    text: str

@dataclass(frozen=True)
class RetrievalRequest:
    request_id: str
    issue_id: str
    evidence_item_id: str
    query_channel: QueryChannel
    query_text: str
    top_k: int = 100
    query_terms: List[str] = field(default_factory=list)
    statute_hints: List[str] = field(default_factory=list)
    first_stage_query_text: Optional[str] = None
    rerank_query_text: Optional[str] = None


@dataclass(frozen=True)
class CandidateProvision:
    provision_id: str
    statute_name: str
    provision_text: str
    issue_id: str
    source_request_id: str
    retrieval_round: int
    first_stage_score: float
    fusion_rank: int
    rerank_score: float
    source_request_ids: List[str] = field(default_factory=list)
    target_evidence_item_ids: List[str] = field(default_factory=list)
    first_stage_rank: Optional[int] = None
    rerank_rank: Optional[int] = None
    selection_rank: Optional[int] = None
    candidate_stage: str = "bge_rerank"
    selection_reason: str = "global_top_k"
    alias_provision_ids: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class CandidateStageRecord:
    """One immutable candidate observation at a retrieval pipeline stage."""

    provision_id: str
    retrieval_round: int
    candidate_stage: str
    source_request_ids: List[str]
    target_evidence_item_ids: List[str]
    first_stage_rank: Optional[int] = None
    fusion_rank: Optional[int] = None
    rerank_rank: Optional[int] = None
    selection_rank: Optional[int] = None
    first_stage_score: Optional[float] = None
    fusion_score: Optional[float] = None
    rerank_score: Optional[float] = None
    selection_reason: str = ""
    alias_provision_ids: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class SupportSpan:
    start_char: int
    end_char: int


@dataclass(frozen=True)
class EvidenceLink:
    issue_id: str
    evidence_item_id: str
    provision_id: str
    support_spans: List[SupportSpan]
    assessment: str = "accepted"
    role: EvidenceRole = EvidenceRole.CORE
    condition: str = ""
    rationale: str = ""


@dataclass(frozen=True)
class CoverageAssessment:
    evidence_item_id: str
    status: CoverageStatus
    linked_provision_ids: List[str]
    rationale: str
    partial_kind: str = "not_applicable"
    missing_aspects: List[str] = field(default_factory=list)
    legal_status: Optional[LegalStatus] = None
    applicability_status: Optional[ApplicabilityStatus] = None
    gap_type: Optional[GapType] = None
    governing_legal_regime: Optional[GoverningLegalRegime] = None
    criterion_results: List["CriterionResult"] = field(default_factory=list)


@dataclass(frozen=True)
class CriterionResult:
    requirement_id: str
    status: CriterionStatus
    linked_provision_ids: List[str]
    rationale: str


@dataclass(frozen=True)
class EvidenceConflict:
    evidence_item_id: str
    provision_ids: List[str]
    description: str
    resolved: bool = False


@dataclass(frozen=True)
class Claim:
    claim_id: str
    text: str
    answer_target_ids: List[str] = field(default_factory=list)
    public_role: str = "conclusion"


@dataclass(frozen=True)
class ClaimCitation:
    claim_id: str
    provision_ids: List[str]


@dataclass(frozen=True)
class AnswerDraft:
    claims: List[Claim]
    claim_citations: List[ClaimCitation]
    answer: str
    structured_claims: List[Dict[str, Any]] = field(default_factory=list)
    structured_claim_citations: List[Dict[str, Any]] = field(default_factory=list)
    assumptions: List[Dict[str, Any]] = field(default_factory=list)
    limitations: List[Dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class CitationIntegrityResult:
    passed: bool
    errors: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class PolicyDecision:
    action: PolicyAction
    termination_reason: Optional[TerminationReason] = None
    explanation: str = ""
    answer_mode: Optional[AnswerMode] = None
    answered_target_ids: List[str] = field(default_factory=list)
    deferred_target_ids: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class ActionTrace:
    event: str
    phase: Phase
    details: Dict[str, object] = field(default_factory=dict)
