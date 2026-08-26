"""Deterministic input, schema-shape, and cross-reference validation."""

import math
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .contracts import (
    ApplicabilityStatus,
    AnswerTarget,
    AnswerDraft,
    ArticleFamilyExpansionRecord,
    CandidateProvision,
    CandidateStageRecord,
    Claim,
    ClaimCitation,
    CompletionRequirement,
    CoverageAssessment,
    CoverageStatus,
    CriterionResult,
    CriterionStatus,
    EvidenceConflict,
    EvidenceLink,
    EvidenceRole,
    GapType,
    GoverningLegalRegime,
    LegalStatus,
    LegalIssue,
    PublicMaterialCondition,
    QueryChannel,
    RequiredEvidenceItem,
    RetrievalRequest,
    SupportSpan,
)
from .run_state import RunState


class ValidationError(ValueError):
    pass


def normalize_question(question: str) -> str:
    """Apply only deterministic Unicode/whitespace normalization."""
    if not isinstance(question, str):
        raise ValidationError("question must be a string")
    normalized = unicodedata.normalize("NFC", question)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        raise ValidationError("question must not be empty")
    return normalized


def normalized_query(query: str) -> str:
    return normalize_question(query).casefold()


def normalize_material_text(value: str) -> str:
    """Compare statutory snippets after only Unicode/space/punctuation cleanup."""
    if not isinstance(value, str):
        raise ValidationError("material condition text must be a string")
    normalized = unicodedata.normalize("NFC", value)
    normalized = re.sub(r"[\s\W_]+", "", normalized, flags=re.UNICODE)
    if not normalized:
        raise ValidationError("material condition text must not be empty")
    return normalized


def answer_target_question_segment(question: str) -> str:
    """Return only the explicit question span when a scenario envelope is present."""
    normalized = normalize_question(question)
    marker = "[질문]"
    return normalized.split(marker, 1)[1].strip() if marker in normalized else normalized


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationError("%s must be an object" % label)
    return value


def _items(payload: Mapping[str, Any], key: str, allow_empty: bool = False) -> List[Mapping[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ValidationError("%s must be a list" % key)
    if not value and not allow_empty:
        raise ValidationError("%s must not be empty" % key)
    return [_mapping(item, "%s[]" % key) for item in value]


def _string(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("%s must be a non-empty string" % key)
    return value.strip()


def _optional_string(raw: Mapping[str, Any], key: str) -> Optional[str]:
    if key not in raw or raw[key] is None:
        return None
    return _string(raw, key)


def _boolean(raw: Mapping[str, Any], key: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise ValidationError("%s must be a boolean" % key)
    return value


def _string_list(raw: Mapping[str, Any], key: str) -> List[str]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ValidationError("%s must be a list of non-empty strings" % key)
    normalized = [normalize_question(item) for item in value]
    if len(normalized) != len(set(normalized)):
        raise ValidationError("%s must not contain duplicates" % key)
    return normalized


def _unique(values: Iterable[str], label: str) -> None:
    values = list(values)
    if len(values) != len(set(values)):
        raise ValidationError("%s contains duplicate IDs" % label)


def _parse_request(raw: Mapping[str, Any]) -> RetrievalRequest:
    try:
        channel = QueryChannel(_string(raw, "query_channel"))
    except ValueError as exc:
        raise ValidationError("query_channel is not a frozen allowed value") from exc
    top_k = raw.get("top_k")
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k != 100:
        raise ValidationError("top_k must be the frozen value 100")
    return RetrievalRequest(
        request_id=_string(raw, "request_id"),
        issue_id=_string(raw, "issue_id"),
        evidence_item_id=_string(raw, "evidence_item_id"),
        query_channel=channel,
        query_text=normalize_question(_string(raw, "query_text")),
        top_k=top_k,
        query_terms=_string_list(raw, "query_terms"),
        statute_hints=_string_list(raw, "statute_hints"),
        first_stage_query_text=_optional_string(raw, "first_stage_query_text"),
        rerank_query_text=_optional_string(raw, "rerank_query_text"),
    )


def _parse_answer_targets(raw_targets: Sequence[Mapping[str, Any]]) -> List[AnswerTarget]:
    targets = [
        AnswerTarget(
            answer_target_id=_string(raw, "answer_target_id"),
            question_anchor=normalize_question(_string(raw, "question_anchor")),
            requested_output=_string(raw, "requested_output"),
            answer_type=_string(raw, "answer_type"),
        )
        for raw in raw_targets
    ]
    _unique([target.answer_target_id for target in targets], "answer_targets")
    return targets


def _parse_completion_requirements(
    raw: Mapping[str, Any],
) -> List[CompletionRequirement]:
    requirements = raw.get("completion_requirements")
    if requirements is None:
        return []
    if not isinstance(requirements, list) or not requirements:
        raise ValidationError("completion_requirements must be a non-empty list when provided")
    parsed = [
        CompletionRequirement(
            requirement_id=_string(_mapping(item, "completion_requirements[]"), "requirement_id"),
            text=_string(_mapping(item, "completion_requirements[]"), "text"),
        )
        for item in requirements
    ]
    _unique([requirement.requirement_id for requirement in parsed], "completion_requirements")
    return parsed


def _parse_required_evidence(raw: Mapping[str, Any]) -> RequiredEvidenceItem:
    completion_requirements = _parse_completion_requirements(raw)
    scope_source = raw.get("scope_source", "legacy")
    if not isinstance(scope_source, str) or not scope_source.strip():
        raise ValidationError("scope_source must be a non-empty string")
    return RequiredEvidenceItem(
        evidence_item_id=_string(raw, "evidence_item_id"),
        issue_id=_string(raw, "issue_id"),
        evidence_type=_string(raw, "evidence_type"),
        description=_string(raw, "description"),
        critical=_boolean(raw, "critical"),
        completion_criteria=raw.get("completion_criteria", "") or _string(raw, "description"),
        necessity_reason=_optional_string(raw, "necessity_reason") or "",
        answer_target_ids=_string_list(raw, "answer_target_ids"),
        scope_source=scope_source.strip(),
        completion_requirements=completion_requirements,
    )


def validate_initial_plan(
    payload: Mapping[str, Any],
    question: Optional[str] = None,
    include_answer_targets: bool = False,
):
    issues = [
        LegalIssue(issue_id=_string(raw, "issue_id"), description=_string(raw, "description"))
        for raw in _items(payload, "legal_issues")
    ]
    _unique([issue.issue_id for issue in issues], "legal_issues")

    raw_answer_targets = payload.get("answer_targets", [])
    if not isinstance(raw_answer_targets, list):
        raise ValidationError("answer_targets must be a list")
    answer_targets = _parse_answer_targets(
        [_mapping(raw, "answer_targets[]") for raw in raw_answer_targets]
    )
    if answer_targets:
        if question is None:
            raise ValidationError("question is required to validate answer_targets")
        question_segment = answer_target_question_segment(question)
        if any(target.question_anchor not in question_segment for target in answer_targets):
            raise ValidationError("answer_target question_anchor must be a question substring")

    evidence_items = [_parse_required_evidence(raw) for raw in _items(payload, "required_evidence_items")]
    _unique([item.evidence_item_id for item in evidence_items], "required_evidence_items")
    issue_ids = {issue.issue_id for issue in issues}
    if any(item.issue_id not in issue_ids for item in evidence_items):
        raise ValidationError("required_evidence_items references an unknown issue_id")

    target_ids = {target.answer_target_id for target in answer_targets}
    requirement_ids = []
    allowed_scope_sources = {
        "explicit_question",
        "outcome_changing_condition",
        "supporting_context",
    }
    for item in evidence_items:
        if item.scope_source != "legacy" and item.scope_source not in allowed_scope_sources:
            raise ValidationError("scope_source is not a frozen allowed value")
        if item.scope_source == "supporting_context" and item.critical:
            raise ValidationError("supporting_context evidence must not be critical")
        if set(item.answer_target_ids) - target_ids:
            raise ValidationError("required evidence references an unknown answer_target_id")
        if answer_targets and item.scope_source == "legacy":
            raise ValidationError("answer-target plans must declare scope_source")
        if answer_targets and not item.necessity_reason:
            raise ValidationError("answer-target plans require necessity_reason")
        if answer_targets and not item.completion_requirements:
            raise ValidationError("answer-target plans require atomic completion_requirements")
        if item.critical and answer_targets and not item.answer_target_ids:
            raise ValidationError("critical evidence must reference an answer target")
        requirement_ids.extend(
            requirement.requirement_id for requirement in item.completion_requirements
        )
    _unique(requirement_ids, "completion_requirements")
    if answer_targets:
        critical_targets = {
            target_id
            for item in evidence_items
            if item.critical
            for target_id in item.answer_target_ids
        }
        if target_ids - critical_targets:
            raise ValidationError("every answer target must have critical evidence")

    requests = [_parse_request(raw) for raw in _items(payload, "retrieval_requests")]
    _validate_requests(requests, issue_ids, {item.evidence_item_id for item in evidence_items}, [])
    if include_answer_targets:
        return issues, answer_targets, evidence_items, requests
    return issues, evidence_items, requests


def validate_gap_plan(payload: Mapping[str, Any], state: RunState) -> List[RetrievalRequest]:
    raw_requests = payload.get("gap_retrieval_requests")
    if not isinstance(raw_requests, list):
        raise ValidationError("gap_retrieval_requests must be a list")
    requests = [_parse_request(_mapping(raw, "gap_retrieval_requests[]")) for raw in raw_requests]
    _validate_requests(
        requests,
        {issue.issue_id for issue in state.legal_issues},
        set(state.evidence_by_id()),
        state.query_history,
    )
    return requests


def _validate_requests(
    requests: Sequence[RetrievalRequest],
    issue_ids: Sequence[str],
    evidence_ids: Sequence[str],
    history: Sequence[RetrievalRequest],
) -> None:
    _unique([request.request_id for request in requests], "retrieval requests")
    issue_ids, evidence_ids = set(issue_ids), set(evidence_ids)
    seen_queries = {normalized_query(request.query_text) for request in history}
    seen_request_ids = {request.request_id for request in history}
    for request in requests:
        if request.request_id in seen_request_ids:
            raise ValidationError("retrieval request_id must not be reused across rounds")
        seen_request_ids.add(request.request_id)
        if request.issue_id not in issue_ids:
            raise ValidationError("retrieval request references an unknown issue_id")
        if request.evidence_item_id not in evidence_ids:
            raise ValidationError("retrieval request references an unknown evidence_item_id")
        query = normalized_query(request.query_text)
        if query in seen_queries:
            raise ValidationError("duplicate normalized retrieval query is forbidden")
        seen_queries.add(query)


def _legacy_axes(
    status: CoverageStatus,
    partial_kind: str,
) -> Tuple[LegalStatus, ApplicabilityStatus, GapType]:
    if status is CoverageStatus.COVERED:
        return LegalStatus.COVERED, ApplicabilityStatus.DIRECT, GapType.NONE
    if status is CoverageStatus.PARTIALLY_COVERED:
        if partial_kind == "factual_condition":
            return (
                LegalStatus.COVERED,
                ApplicabilityStatus.CONDITIONAL,
                GapType.MISSING_FACT,
            )
        return (
            LegalStatus.PARTIALLY_COVERED,
            ApplicabilityStatus.NOT_ASSESSED,
            GapType.MISSING_STATUTE,
        )
    if status is CoverageStatus.UNCOVERED:
        return (
            LegalStatus.UNCOVERED,
            ApplicabilityStatus.NOT_ASSESSED,
            GapType.MISSING_STATUTE,
        )
    return LegalStatus.CONFLICTING, ApplicabilityStatus.NOT_ASSESSED, GapType.CONFLICT


def _coverage_status_from_axes(
    legal_status: LegalStatus,
    applicability_status: ApplicabilityStatus,
) -> Tuple[CoverageStatus, str]:
    if legal_status is LegalStatus.COVERED:
        if applicability_status is ApplicabilityStatus.CONDITIONAL:
            return CoverageStatus.PARTIALLY_COVERED, "factual_condition"
        return CoverageStatus.COVERED, "not_applicable"
    if legal_status is LegalStatus.PARTIALLY_COVERED:
        return CoverageStatus.PARTIALLY_COVERED, "legal_support_gap"
    if legal_status is LegalStatus.UNCOVERED:
        return CoverageStatus.UNCOVERED, "not_applicable"
    return CoverageStatus.CONFLICTING, "not_applicable"


_ALLOWED_COVERAGE_AXIS_TUPLES = {
    (
        LegalStatus.COVERED,
        ApplicabilityStatus.DIRECT,
        GapType.NONE,
    ),
    (
        LegalStatus.COVERED,
        ApplicabilityStatus.CONDITIONAL,
        GapType.MISSING_FACT,
    ),
    (
        LegalStatus.PARTIALLY_COVERED,
        ApplicabilityStatus.NOT_ASSESSED,
        GapType.MISSING_STATUTE,
    ),
    (
        LegalStatus.UNCOVERED,
        ApplicabilityStatus.NOT_ASSESSED,
        GapType.MISSING_STATUTE,
    ),
    (
        LegalStatus.CONFLICTING,
        ApplicabilityStatus.NOT_ASSESSED,
        GapType.CONFLICT,
    ),
}


def _validate_coverage_axis_tuple(
    item: RequiredEvidenceItem,
    legal_status: LegalStatus,
    applicability_status: ApplicabilityStatus,
    gap_type: GapType,
) -> None:
    """Reject non-canonical S2 axes before deriving legacy projections."""
    axis_tuple = (legal_status, applicability_status, gap_type)
    if axis_tuple in _ALLOWED_COVERAGE_AXIS_TUPLES:
        return
    if (
        axis_tuple
        == (
            LegalStatus.UNCOVERED,
            ApplicabilityStatus.NOT_ASSESSED,
            GapType.SCOPE_EXCESS,
        )
        and item.critical is False
    ):
        return
    raise ValidationError("coverage axes are not an allowed tuple for this evidence item")


def _criterion_status_for_legacy(status: CoverageStatus) -> CriterionStatus:
    return {
        CoverageStatus.COVERED: CriterionStatus.SATISFIED,
        CoverageStatus.PARTIALLY_COVERED: CriterionStatus.PARTIALLY_SATISFIED,
        CoverageStatus.UNCOVERED: CriterionStatus.UNSATISFIED,
        CoverageStatus.CONFLICTING: CriterionStatus.CONFLICTING,
    }[status]


def _legacy_governing_legal_regime(
    legal_status: LegalStatus,
) -> GoverningLegalRegime:
    return (
        GoverningLegalRegime.DIRECT_ENTAILMENT
        if legal_status is LegalStatus.COVERED
        else GoverningLegalRegime.NOT_DIRECT_ENTAILMENT
    )


def _parse_public_material_conditions(
    raw_conditions: Any,
    *,
    item: RequiredEvidenceItem,
    requirement_id: str,
    linked_provision_ids: Sequence[str],
    candidate_by_id: Mapping[str, CandidateProvision],
) -> List[PublicMaterialCondition]:
    """Accept only target-scoped alternate outcomes quoted from a linked CORE rule."""
    if raw_conditions is None:
        return []
    if not isinstance(raw_conditions, list):
        raise ValidationError("public_material_conditions must be a list")
    parsed = []
    seen = set()
    for raw_condition in raw_conditions:
        condition = _mapping(raw_condition, "public_material_conditions[]")
        if condition.get("kind") != "alternative_outcome":
            raise ValidationError(
                "public material condition kind must be alternative_outcome"
            )
        answer_target_id = _string(condition, "answer_target_id")
        if answer_target_id not in item.answer_target_ids:
            raise ValidationError(
                "public material condition must target the evidence item target"
            )
        source_provision_id = _string(condition, "source_provision_id")
        if source_provision_id not in linked_provision_ids:
            raise ValidationError(
                "public material condition source must link the satisfied criterion"
            )
        source = candidate_by_id.get(source_provision_id)
        if source is None:
            raise ValidationError("public material condition source is outside candidates")
        condition_text = _string(condition, "condition_text")
        outcome_text = _string(condition, "outcome_text")
        normalized_condition = normalize_material_text(condition_text)
        normalized_outcome = normalize_material_text(outcome_text)
        if normalized_condition == normalized_outcome:
            raise ValidationError("public material condition and outcome must be distinct")
        normalized_source = normalize_material_text(source.provision_text)
        if (
            normalized_condition not in normalized_source
            or normalized_outcome not in normalized_source
        ):
            raise ValidationError(
                "public material condition must be an exact normalized CORE source substring"
            )
        key = (
            answer_target_id,
            source_provision_id,
            normalized_condition,
            normalized_outcome,
        )
        if key in seen:
            raise ValidationError("duplicate public material condition")
        seen.add(key)
        parsed.append((key, condition_text.strip(), outcome_text.strip()))
    parsed.sort(key=lambda entry: entry[0])
    return [
        PublicMaterialCondition(
            material_id="%s-M%d" % (requirement_id, index),
            evidence_item_id=item.evidence_item_id,
            requirement_id=requirement_id,
            answer_target_id=key[0],
            condition_text=condition_text,
            outcome_text=outcome_text,
            source_provision_id=key[1],
        )
        for index, (key, condition_text, outcome_text) in enumerate(parsed, start=1)
    ]


def _parse_criterion_results(
    raw: Mapping[str, Any],
    item: RequiredEvidenceItem,
    linked_ids: List[str],
    legacy_status: CoverageStatus,
    candidate_ids: Sequence[str],
    candidate_by_id: Mapping[str, CandidateProvision],
) -> List[CriterionResult]:
    raw_results = raw.get("criterion_results")
    if raw_results is None:
        if item.completion_requirements:
            raise ValidationError(
                "atomic completion_requirements require criterion_results"
            )
        return [
            CriterionResult(
                requirement_id=requirement.requirement_id,
                status=_criterion_status_for_legacy(legacy_status),
                linked_provision_ids=list(linked_ids),
                rationale=_string(raw, "rationale"),
            )
            for requirement in item.completion_requirements
        ]
    if not isinstance(raw_results, list):
        raise ValidationError("criterion_results must be a list")
    results = []
    for result in raw_results:
        result = _mapping(result, "criterion_results[]")
        try:
            result_status = CriterionStatus(_string(result, "status"))
        except ValueError as exc:
            raise ValidationError("criterion status is not a frozen allowed value") from exc
        result_linked_ids = result.get("linked_provision_ids")
        if not isinstance(result_linked_ids, list) or not all(
            isinstance(value, str) for value in result_linked_ids
        ):
            raise ValidationError("criterion linked_provision_ids must be a list of strings")
        if any(provision_id not in candidate_ids for provision_id in result_linked_ids):
            raise ValidationError("criterion result references provision outside candidates")
        requirement_id = _string(result, "requirement_id")
        results.append(
            CriterionResult(
                requirement_id=requirement_id,
                status=result_status,
                linked_provision_ids=list(result_linked_ids),
                rationale=_string(result, "rationale"),
                public_material_conditions=_parse_public_material_conditions(
                    result.get("public_material_conditions"),
                    item=item,
                    requirement_id=requirement_id,
                    linked_provision_ids=result_linked_ids,
                    candidate_by_id=candidate_by_id,
                ),
            )
        )
    _unique([result.requirement_id for result in results], "criterion_results")
    required_ids = {
        requirement.requirement_id for requirement in item.completion_requirements
    }
    if required_ids and {result.requirement_id for result in results} != required_ids:
        raise ValidationError("criterion_results must cover each completion requirement")
    if not required_ids and results:
        raise ValidationError("criterion_results require S1 completion_requirements")
    return results


def validate_coverage_assessment(
    payload: Mapping[str, Any],
    state: RunState,
) -> Tuple[List[EvidenceLink], List[CoverageAssessment], List[EvidenceConflict]]:
    candidate_by_id = state.candidate_by_id()
    evidence_by_id = state.evidence_by_id()
    links: List[EvidenceLink] = []
    for raw in _items(payload, "evidence_links", allow_empty=True):
        evidence_item_id = _string(raw, "evidence_item_id")
        provision_id = _string(raw, "provision_id")
        issue_id = _string(raw, "issue_id")
        if evidence_item_id not in evidence_by_id:
            raise ValidationError("evidence link references unknown evidence_item_id")
        if issue_id != evidence_by_id[evidence_item_id].issue_id:
            raise ValidationError("evidence link issue_id does not match evidence item")
        candidate = candidate_by_id.get(provision_id)
        if candidate is None:
            raise ValidationError("evidence link references provision outside candidates")
        raw_role = raw.get("role", EvidenceRole.CORE.value)
        try:
            role = EvidenceRole(raw_role)
        except (TypeError, ValueError) as exc:
            raise ValidationError("evidence link role is not a frozen allowed value") from exc
        condition = raw.get("condition", "")
        rationale = raw.get("rationale", "")
        if not isinstance(condition, str):
            raise ValidationError("evidence link condition must be a string")
        if not isinstance(rationale, str):
            raise ValidationError("evidence link rationale must be a string")
        # Role-less historical outputs are migrated as CORE.  Once a role is
        # authored, it must carry the decision context needed for audit.
        if "role" in raw and not rationale.strip():
            raise ValidationError("role-aware evidence link requires a rationale")
        if role in {EvidenceRole.QUALIFYING, EvidenceRole.ALTERNATIVE} and not condition.strip():
            raise ValidationError("qualifying or alternative evidence link requires a condition")
        spans: List[SupportSpan] = []
        for span_raw in _items(_mapping(raw, "evidence_link"), "support_spans"):
            start, end = span_raw.get("start_char"), span_raw.get("end_char")
            if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end <= len(candidate.provision_text)):
                raise ValidationError("support span is outside the cited provision text")
            spans.append(SupportSpan(start_char=start, end_char=end))
        links.append(
            EvidenceLink(
                issue_id=issue_id,
                evidence_item_id=evidence_item_id,
                provision_id=provision_id,
                support_spans=spans,
                assessment=_string(raw, "assessment"),
                role=role,
                condition=condition.strip(),
                rationale=rationale.strip(),
            )
        )

    accepted_core_by_evidence = {}
    for link in links:
        if link.assessment == "accepted" and link.role is EvidenceRole.CORE:
            accepted_core_by_evidence.setdefault(link.evidence_item_id, set()).add(
                link.provision_id
            )

    assessments: List[CoverageAssessment] = []
    for raw in _items(payload, "coverage_assessments"):
        evidence_item_id = _string(raw, "evidence_item_id")
        if evidence_item_id not in evidence_by_id:
            raise ValidationError("coverage assessment references unknown evidence_item_id")
        item = evidence_by_id[evidence_item_id]
        linked_ids = raw.get("linked_provision_ids")
        if not isinstance(linked_ids, list) or not all(isinstance(value, str) for value in linked_ids):
            raise ValidationError("linked_provision_ids must be a list of strings")
        if any(provision_id not in candidate_by_id for provision_id in linked_ids):
            raise ValidationError("coverage assessment references provision outside candidates")
        legacy_value = raw.get("status", raw.get("evidence_status"))
        legacy_status = None
        if legacy_value is not None:
            if not isinstance(legacy_value, str):
                raise ValidationError("coverage status must be a string")
            try:
                legacy_status = CoverageStatus(legacy_value)
            except ValueError as exc:
                raise ValidationError("coverage status is not a frozen allowed value") from exc
        partial_kind = raw.get(
            "partial_kind",
            "legal_support_gap"
            if legacy_status is CoverageStatus.PARTIALLY_COVERED
            else "not_applicable",
        )
        allowed_partial_kinds = {"factual_condition", "legal_support_gap"}
        if legacy_status is CoverageStatus.PARTIALLY_COVERED:
            if partial_kind not in allowed_partial_kinds:
                raise ValidationError("partial coverage requires a valid partial_kind")
        elif legacy_status is not None and partial_kind != "not_applicable":
            raise ValidationError("non-partial coverage must use partial_kind=not_applicable")
        axis_fields = ("legal_status", "applicability_status", "gap_type")
        has_axes = any(field in raw for field in axis_fields)
        if item.completion_requirements and not has_axes:
            raise ValidationError(
                "atomic completion_requirements require legal_status, applicability_status, and gap_type"
            )
        if has_axes:
            if not all(field in raw for field in axis_fields):
                raise ValidationError("legal_status, applicability_status, and gap_type must be supplied together")
            try:
                legal_status = LegalStatus(_string(raw, "legal_status"))
                applicability_status = ApplicabilityStatus(
                    _string(raw, "applicability_status")
                )
                gap_type = GapType(_string(raw, "gap_type"))
            except ValueError as exc:
                raise ValidationError("coverage axes are not frozen allowed values") from exc
            _validate_coverage_axis_tuple(
                item,
                legal_status,
                applicability_status,
                gap_type,
            )
            status, derived_partial_kind = _coverage_status_from_axes(
                legal_status, applicability_status
            )
            if legacy_status is not None and legacy_status is not status:
                raise ValidationError("legacy evidence_status conflicts with coverage axes")
            if "partial_kind" not in raw:
                partial_kind = derived_partial_kind
            if partial_kind != derived_partial_kind:
                raise ValidationError("partial_kind conflicts with coverage axes")
        else:
            if legacy_status is None:
                raise ValidationError("coverage assessment requires status or legal_status")
            status = legacy_status
            legal_status, applicability_status, gap_type = _legacy_axes(status, partial_kind)
        raw_governing_regime = raw.get("governing_legal_regime")
        if raw_governing_regime is None:
            governing_legal_regime = _legacy_governing_legal_regime(legal_status)
        else:
            try:
                governing_legal_regime = GoverningLegalRegime(
                    _string(raw, "governing_legal_regime")
                )
            except ValueError as exc:
                raise ValidationError(
                    "governing_legal_regime is not a frozen allowed value"
                ) from exc
        if (
            legal_status is LegalStatus.COVERED
            and governing_legal_regime is not GoverningLegalRegime.DIRECT_ENTAILMENT
        ):
            raise ValidationError(
                "covered legal status requires direct_entailment governing_legal_regime"
            )
        if (
            governing_legal_regime is GoverningLegalRegime.DIRECT_ENTAILMENT
            and legal_status is not LegalStatus.COVERED
        ):
            raise ValidationError(
                "direct_entailment governing_legal_regime requires covered legal status"
            )
        core_linked_ids = accepted_core_by_evidence.get(evidence_item_id, set())
        if set(linked_ids) - core_linked_ids:
            raise ValidationError(
                "coverage assessment may link only accepted CORE provisions"
            )
        if legal_status is LegalStatus.COVERED and not linked_ids:
            raise ValidationError("covered legal status requires an accepted CORE provision")
        missing_aspects = raw.get("missing_aspects", [])
        if not isinstance(missing_aspects, list) or not all(
            isinstance(value, str) and value.strip() for value in missing_aspects
        ):
            raise ValidationError("missing_aspects must be a list of non-empty strings")
        if has_axes and item.completion_requirements:
            requirement_ids = {
                requirement.requirement_id
                for requirement in item.completion_requirements
            }
            if set(missing_aspects) - requirement_ids:
                raise ValidationError("missing_aspects must reference existing requirement_id values")
        criterion_results = _parse_criterion_results(
            raw,
            item,
            list(linked_ids),
            status,
            list(candidate_by_id),
            candidate_by_id,
        )
        for result in criterion_results:
            if set(result.linked_provision_ids) - core_linked_ids:
                raise ValidationError(
                    "criterion result may link only accepted CORE provisions"
                )
            if (
                result.status is CriterionStatus.SATISFIED
                and not result.linked_provision_ids
            ):
                raise ValidationError(
                    "satisfied criterion requires an accepted CORE provision"
                )
            if result.public_material_conditions and (
                item.critical is not True
                or status is not CoverageStatus.COVERED
                or legal_status is not LegalStatus.COVERED
                or governing_legal_regime
                is not GoverningLegalRegime.DIRECT_ENTAILMENT
                or result.status is not CriterionStatus.SATISFIED
            ):
                raise ValidationError(
                    "public material conditions require critical direct covered satisfied criterion"
                )
        assessments.append(
            CoverageAssessment(
                evidence_item_id=evidence_item_id,
                status=status,
                linked_provision_ids=list(linked_ids),
                rationale=_string(raw, "rationale"),
                partial_kind=partial_kind,
                missing_aspects=list(missing_aspects),
                legal_status=legal_status,
                applicability_status=applicability_status,
                gap_type=gap_type,
                governing_legal_regime=governing_legal_regime,
                criterion_results=criterion_results,
            )
        )
    _unique([assessment.evidence_item_id for assessment in assessments], "coverage_assessments")
    if set(assessment.evidence_item_id for assessment in assessments) != set(evidence_by_id):
        raise ValidationError("S2 must assess every required evidence item")

    conflicts: List[EvidenceConflict] = []
    for raw in _items(payload, "evidence_conflicts", allow_empty=True):
        evidence_item_id = _string(raw, "evidence_item_id")
        provision_ids = raw.get("provision_ids")
        if evidence_item_id not in evidence_by_id:
            raise ValidationError("evidence conflict references unknown evidence_item_id")
        if not isinstance(provision_ids, list) or not all(isinstance(value, str) for value in provision_ids):
            raise ValidationError("evidence conflict provision_ids must be a list of strings")
        if any(provision_id not in candidate_by_id for provision_id in provision_ids):
            raise ValidationError("evidence conflict references provision outside candidates")
        conflicts.append(
            EvidenceConflict(
                evidence_item_id=evidence_item_id,
                provision_ids=list(provision_ids),
                description=_string(raw, "description"),
                resolved=raw.get("resolved", False) is True,
            )
        )
    unresolved_conflict_ids = {
        conflict.evidence_item_id for conflict in conflicts if not conflict.resolved
    }
    if any(
        assessment.status is CoverageStatus.CONFLICTING
        and assessment.evidence_item_id not in unresolved_conflict_ids
        for assessment in assessments
    ):
        raise ValidationError("conflicting coverage assessment requires an unresolved conflict")
    return links, assessments, conflicts


def _validate_answer_draft(
    payload: Mapping[str, Any],
    state: RunState,
    allowed_target_ids: Sequence[str],
    allowed_provision_ids: Sequence[str],
    scope_error: str,
    allow_empty: bool = False,
    core_conclusion_provision_ids: Optional[Sequence[str]] = None,
) -> AnswerDraft:
    raw_claims = _items(payload, "claims", allow_empty=allow_empty)
    claims = []
    allowed_targets = set(allowed_target_ids)
    for raw in raw_claims:
        target_ids = _string_list(raw, "answer_target_ids")
        if state.answer_targets:
            if not target_ids:
                raise ValidationError("answer claims must identify answer_target_ids")
            if set(target_ids) - allowed_targets:
                raise ValidationError(scope_error)
        public_role = raw.get("public_role", "conclusion")
        if public_role not in {"conclusion", "audit"}:
            raise ValidationError("claim public_role must be conclusion or audit")
        material_ids = raw.get("public_material_condition_ids", [])
        if (
            not isinstance(material_ids, list)
            or not all(isinstance(material_id, str) and material_id for material_id in material_ids)
            or len(material_ids) != len(set(material_ids))
        ):
            raise ValidationError("claim public_material_condition_ids must be unique strings")
        claims.append(
            Claim(
                claim_id=_string(raw, "claim_id"),
                text=_string(raw, "text"),
                answer_target_ids=target_ids,
                public_role=public_role,
                public_material_condition_ids=list(material_ids),
            )
        )
    _unique([claim.claim_id for claim in claims], "claims")

    raw_citations = _items(
        payload, "claim_citations", allow_empty=allow_empty
    )
    provision_ids_by_claim: Dict[str, List[str]] = {}
    for raw in raw_citations:
        claim_id = _string(raw, "claim_id")
        provision_ids = raw.get("provision_ids")
        if provision_ids is None and isinstance(raw.get("provision_id"), str):
            provision_ids = [raw["provision_id"]]
        if (
            not isinstance(provision_ids, list)
            or not provision_ids
            or not all(isinstance(value, str) and value for value in provision_ids)
        ):
            raise ValidationError(
                "claim citation must contain one or more provision IDs"
            )
        provision_ids_by_claim.setdefault(claim_id, []).extend(provision_ids)
    citations = [
        ClaimCitation(
            claim_id=claim_id,
            provision_ids=sorted(set(provision_ids)),
        )
        for claim_id, provision_ids in sorted(provision_ids_by_claim.items())
    ]
    if {claim.claim_id for claim in claims} != set(provision_ids_by_claim):
        raise ValidationError("every answer claim must have at least one claim citation")
    cited_ids = {
        provision_id
        for citation in citations
        for provision_id in citation.provision_ids
    }
    if not cited_ids.issubset(set(allowed_provision_ids)):
        raise ValidationError(
            "S3 cited a provision outside the authorized provision set"
        )
    if core_conclusion_provision_ids is not None:
        claim_by_id = {claim.claim_id: claim for claim in claims}
        core_ids = set(core_conclusion_provision_ids)
        for citation in citations:
            claim = claim_by_id[citation.claim_id]
            if (
                claim.public_role == "conclusion"
                and not set(citation.provision_ids).issubset(core_ids)
            ):
                raise ValidationError(
                    "S3 conclusion claim may cite only CORE accepted provisions"
                )

    audit_notes: Dict[str, List[Dict[str, Any]]] = {}
    for key in ("assumptions", "limitations"):
        value = payload.get(key, [])
        if not isinstance(value, list):
            raise ValidationError("%s must be a list" % key)
        notes: List[Dict[str, Any]] = []
        for raw in value:
            note = _mapping(raw, "%s[]" % key)
            _string(note, "code")
            _string(note, "message")
            notes.append(dict(note))
        audit_notes[key] = notes

    answer = _string(payload, "answer")
    answer_lines = [line.strip() for line in answer.splitlines() if line.strip()]
    if len(answer) > 800:
        raise ValidationError("public answer exceeds 800 characters")
    if not 1 <= len(answer_lines) <= 3:
        raise ValidationError("public answer must contain 1 to 3 short lines")
    if any(
        line.startswith(("전제:", "한계:")) for line in answer_lines
    ):
        raise ValidationError("public answer must not append audit assumptions or limitations")
    return AnswerDraft(
        claims=claims,
        claim_citations=citations,
        answer=answer,
        structured_claims=[dict(raw) for raw in raw_claims],
        structured_claim_citations=[dict(raw) for raw in raw_citations],
        assumptions=audit_notes["assumptions"],
        limitations=audit_notes["limitations"],
    )


def _active_public_material_conditions(
    state: RunState,
) -> List[PublicMaterialCondition]:
    active = []
    for assessment in state.coverage_assessments:
        if (
            assessment.status is not CoverageStatus.COVERED
            or assessment.legal_status is not LegalStatus.COVERED
            or assessment.governing_legal_regime
            is not GoverningLegalRegime.DIRECT_ENTAILMENT
        ):
            continue
        for criterion in assessment.criterion_results:
            if criterion.status is not CriterionStatus.SATISFIED:
                continue
            active.extend(
                condition
                for condition in criterion.public_material_conditions
                if (
                    condition.answer_target_id in state.answered_target_ids
                    and condition.source_provision_id
                    in state.core_accepted_provision_ids
                )
            )
    return active


def _validate_public_material_conditions_in_draft(
    draft: AnswerDraft, state: RunState
) -> None:
    active = {
        condition.material_id: condition
        for condition in _active_public_material_conditions(state)
    }
    citations_by_claim = {
        citation.claim_id: set(citation.provision_ids)
        for citation in draft.claim_citations
    }
    for claim in draft.claims:
        if claim.public_role != "conclusion" and claim.public_material_condition_ids:
            raise ValidationError(
                "only a public conclusion claim may name a material condition"
            )
        if set(claim.public_material_condition_ids) - set(active):
            raise ValidationError("claim names unknown public material condition")
    for material_id, condition in active.items():
        owners = [
            claim
            for claim in draft.claims
            if material_id in claim.public_material_condition_ids
        ]
        if len(owners) != 1:
            raise ValidationError(
                "public material condition must appear in exactly one conclusion claim"
            )
        claim = owners[0]
        if (
            claim.public_role != "conclusion"
            or condition.answer_target_id not in claim.answer_target_ids
            or normalize_material_text(condition.condition_text)
            not in normalize_material_text(claim.text)
            or normalize_material_text(condition.outcome_text)
            not in normalize_material_text(claim.text)
            or condition.source_provision_id
            not in citations_by_claim.get(claim.claim_id, set())
        ):
            raise ValidationError(
                "public material condition is not rendered by its CORE conclusion claim"
            )


def validate_answer_draft(payload: Mapping[str, Any], state: RunState) -> AnswerDraft:
    core_ids = state.core_accepted_provision_ids
    if not core_ids and not any(
        link.role is not EvidenceRole.CORE for link in state.evidence_links
    ):
        # Compatibility for legacy state fixtures and records that predate
        # role projections: their accepted set is semantically all CORE.
        core_ids = state.accepted_provision_ids
    draft = _validate_answer_draft(
        payload,
        state,
        state.answered_target_ids,
        state.accepted_provision_ids,
        "answer claim references deferred or unknown answer target",
        core_conclusion_provision_ids=core_ids,
    )
    _validate_public_material_conditions_in_draft(draft, state)
    return draft


def validate_benchmark_candidate_draft(
    payload: Mapping[str, Any], state: RunState
) -> AnswerDraft:
    return _validate_answer_draft(
        payload,
        state,
        [target.answer_target_id for target in state.answer_targets],
        [candidate.provision_id for candidate in state.candidate_provisions],
        "benchmark candidate claim references an unknown answer target",
        allow_empty=not state.candidate_provisions,
    )



def validate_retrieval_candidates(
    candidates: Sequence[CandidateProvision],
    requests: Sequence[RetrievalRequest],
    retrieval_round: int,
) -> None:
    """Check deterministic retrieval output before it enters RunState."""
    request_by_id = {request.request_id: request for request in requests}
    for candidate in candidates:
        if not isinstance(candidate, CandidateProvision):
            raise ValidationError("retriever must return CandidateProvision instances")
        request = request_by_id.get(candidate.source_request_id)
        if request is None:
            raise ValidationError("candidate source_request_id is not in this retrieval round")
        if candidate.issue_id != request.issue_id:
            raise ValidationError("candidate issue_id does not match source retrieval request")
        source_request_ids = candidate.source_request_ids or [candidate.source_request_id]
        if len(source_request_ids) != len(set(source_request_ids)):
            raise ValidationError("candidate source_request_ids must be unique")
        if candidate.source_request_ids and source_request_ids[0] != candidate.source_request_id:
            raise ValidationError("candidate primary source_request_id must be first")
        if any(source_id not in request_by_id for source_id in source_request_ids):
            raise ValidationError("candidate source_request_ids are not in this retrieval round")
        expected_targets = list(
            dict.fromkeys(request_by_id[source_id].evidence_item_id for source_id in source_request_ids)
        )
        if candidate.target_evidence_item_ids and candidate.target_evidence_item_ids != expected_targets:
            raise ValidationError("candidate target_evidence_item_ids do not match source requests")
        if candidate.retrieval_round != retrieval_round:
            raise ValidationError("candidate retrieval_round is invalid")
        if not candidate.provision_id or not candidate.provision_text:
            raise ValidationError("candidate provision_id and provision_text are required")
        if isinstance(candidate.fusion_rank, bool) or candidate.fusion_rank < 1:
            raise ValidationError("candidate fusion_rank must be positive")
        for label, rank in (
            ("first_stage_rank", candidate.first_stage_rank),
            ("rerank_rank", candidate.rerank_rank),
            ("selection_rank", candidate.selection_rank),
        ):
            if rank is not None and (isinstance(rank, bool) or not isinstance(rank, int) or rank < 1):
                raise ValidationError("candidate %s must be a positive integer" % label)
        if not candidate.candidate_stage or not candidate.selection_reason:
            raise ValidationError("candidate stage and selection reason are required")
        if not isinstance(candidate.alias_provision_ids, list) or not all(
            isinstance(provision_id, str) and provision_id
            for provision_id in candidate.alias_provision_ids
        ):
            raise ValidationError("candidate alias_provision_ids must be a list of non-empty strings")
        if len(candidate.alias_provision_ids) != len(set(candidate.alias_provision_ids)):
            raise ValidationError("candidate alias_provision_ids must be unique")


def validate_retrieval_stage_records(
    records: Sequence[CandidateStageRecord],
    requests: Sequence[RetrievalRequest],
    retrieval_round: int,
) -> None:
    """Validate the non-behavioral audit trail emitted by the retriever."""
    request_by_id = {request.request_id: request for request in requests}
    allowed_stages = {
        "first_stage", "rrf", "request_rerank", "bge_rerank", "selected",
        "round_selected", "dedup_collapse", "evidence_fusion",
        "article_family_expansion_trigger", "article_family_sibling_rerank",
    }
    expansion_stages = {
        "article_family_expansion_trigger", "article_family_sibling_rerank",
    }
    for record in records:
        if not isinstance(record, (CandidateStageRecord, ArticleFamilyExpansionRecord)):
            raise ValidationError("retrieval stage audit contains an unsupported record type")
        if record.retrieval_round != retrieval_round:
            raise ValidationError("retrieval stage record has the wrong round")
        if not record.provision_id or record.candidate_stage not in allowed_stages:
            raise ValidationError("retrieval stage record has invalid identity or stage")
        if not record.source_request_ids or len(record.source_request_ids) != len(set(record.source_request_ids)):
            raise ValidationError("retrieval stage source_request_ids must be non-empty and unique")
        if any(source_id not in request_by_id for source_id in record.source_request_ids):
            raise ValidationError("retrieval stage record references an unknown request")
        expected_targets = list(
            dict.fromkeys(
                request_by_id[source_id].evidence_item_id
                for source_id in record.source_request_ids
            )
        )
        if record.target_evidence_item_ids != expected_targets:
            raise ValidationError("retrieval stage target evidence does not match source requests")
        for label, rank in (
            ("first_stage_rank", record.first_stage_rank),
            ("fusion_rank", record.fusion_rank),
            ("rerank_rank", record.rerank_rank),
            ("selection_rank", record.selection_rank),
        ):
            if rank is not None and (isinstance(rank, bool) or not isinstance(rank, int) or rank < 1):
                raise ValidationError("retrieval stage %s must be a positive integer" % label)
        if record.candidate_stage == "first_stage" and record.first_stage_rank is None:
            raise ValidationError("first-stage audit requires first_stage_rank")
        if record.candidate_stage in {"rrf", "evidence_fusion"} and record.fusion_rank is None:
            raise ValidationError("fusion audit requires fusion_rank")
        if record.candidate_stage in {"request_rerank", "bge_rerank", "article_family_sibling_rerank"} and record.rerank_rank is None:
            raise ValidationError("rerank audit requires rerank_rank")
        if record.candidate_stage in expansion_stages:
            if not isinstance(record, ArticleFamilyExpansionRecord):
                raise ValidationError("article-family expansion requires dedicated audit provenance")
            if not record.article_family_key or not record.article_family_root_provision_id:
                raise ValidationError("article-family expansion audit requires family and root provenance")
            counts = (
                record.article_family_sibling_candidate_count,
                record.article_family_sibling_selected_count,
                record.article_family_sibling_dropped_count,
            )
            if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts):
                raise ValidationError("article-family expansion counts must be non-negative integers")
            if record.article_family_sibling_candidate_count != (
                record.article_family_sibling_selected_count
                + record.article_family_sibling_dropped_count
            ):
                raise ValidationError("article-family expansion counts must reconcile")
            if any(
                isinstance(value, bool) or not isinstance(value, int) or value < 1
                for value in (
                    record.article_family_sibling_per_root_cap,
                    record.article_family_sibling_per_request_cap,
                )
            ):
                raise ValidationError("article-family expansion caps must be positive integers")
        if record.candidate_stage in {"selected", "round_selected"} and record.selection_rank is None:
            raise ValidationError("selection audit requires selection_rank")
        for score in (
            record.first_stage_score,
            record.fusion_score,
            record.rerank_score,
        ):
            if score is not None and not math.isfinite(score):
                raise ValidationError("retrieval stage scores must be finite")
        if not record.selection_reason:
            raise ValidationError("retrieval stage selection_reason is required")
        if not isinstance(record.alias_provision_ids, list) or not all(
            isinstance(provision_id, str) and provision_id
            for provision_id in record.alias_provision_ids
        ):
            raise ValidationError("retrieval stage alias_provision_ids must be a list of non-empty strings")
        if len(record.alias_provision_ids) != len(set(record.alias_provision_ids)):
            raise ValidationError("retrieval stage alias_provision_ids must be unique")
