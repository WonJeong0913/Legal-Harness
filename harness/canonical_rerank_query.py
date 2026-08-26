"""Harness-owned canonical rerank query construction.

This module deliberately consumes typed, already-validated S1 structures only.
It never reads the benchmark question/background or infers legal pinpoints.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import re
import unicodedata
from typing import Dict, Iterable, List, Mapping, Tuple

from .contracts import AnswerTarget, RequiredEvidenceItem, RetrievalRequest
from .validation import ValidationError


CANONICAL_RERANK_QUERY_SCHEMA_VERSION = "1.1"
DEFAULT_CANONICAL_RERANK_QUERY_MAX_CHARACTERS = 512
DEFAULT_CANONICAL_RERANK_QUERY_MAX_TOKEN_LIKE_UNITS = 96

CANONICAL_RERANK_QUERY_SOURCES = (
    "raw",
    "canonical_missing_only",
    "raw_query_text_fallback",
)
EFFECTIVE_RERANK_QUERY_SOURCES = ("rerank_query_text", "query_text")


class CanonicalRerankQueryValidationError(ValidationError):
    """Raised rather than falling back to untrusted query material."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str = "canonical_validation_error",
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def normalize_canonical_query_text(value: str) -> str:
    if not isinstance(value, str):
        raise CanonicalRerankQueryValidationError(
            "canonical rerank query source must be a string"
        )
    normalized = unicodedata.normalize("NFC", value)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        raise CanonicalRerankQueryValidationError(
            "canonical rerank query source must not be empty"
        )
    return normalized


def _token_like_units(value: str) -> int:
    return len(re.findall(r"\S+", value))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _query_metrics(value: str, prefix: str) -> Dict[str, object]:
    encoded = value.encode("utf-8")
    return {
        "%s_sha256" % prefix: _sha256(value),
        "%s_characters" % prefix: len(value),
        "%s_utf8_bytes" % prefix: len(encoded),
        "%s_token_like_units" % prefix: _token_like_units(value),
    }


def _validate_bound(value: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("%s must be a positive integer" % label)


def _bounded_normalized(
    value: str,
    label: str,
    max_characters: int,
    max_token_like_units: int,
) -> str:
    normalized = normalize_canonical_query_text(value)
    if len(normalized) > max_characters:
        reason_scope = (
            "canonical_output"
            if label == "canonical rerank query"
            else "structured_input"
        )
        raise CanonicalRerankQueryValidationError(
            "%s exceeds canonical rerank character bound" % label,
            reason_code="%s_character_bound" % reason_scope,
        )
    if _token_like_units(normalized) > max_token_like_units:
        reason_scope = (
            "canonical_output"
            if label == "canonical rerank query"
            else "structured_input"
        )
        raise CanonicalRerankQueryValidationError(
            "%s exceeds canonical rerank token-like bound" % label,
            reason_code="%s_token_like_bound" % reason_scope,
        )
    return normalized


def _ordered_unique(
    values: Iterable[str],
    label: str,
    max_characters: int,
    max_token_like_units: int,
) -> List[str]:
    normalized_values: List[str] = []
    for value in values:
        normalized = _bounded_normalized(
            value, label, max_characters, max_token_like_units
        )
        if normalized not in normalized_values:
            normalized_values.append(normalized)
    return sorted(normalized_values)


def _required_evidence(
    request: RetrievalRequest,
    evidence_by_id: Mapping[str, RequiredEvidenceItem],
) -> RequiredEvidenceItem:
    evidence = evidence_by_id.get(request.evidence_item_id)
    if not isinstance(evidence, RequiredEvidenceItem):
        raise CanonicalRerankQueryValidationError(
            "canonical rerank request references an untrusted evidence item"
        )
    if evidence.issue_id != request.issue_id:
        raise CanonicalRerankQueryValidationError(
            "canonical rerank request evidence issue does not match request issue"
        )
    if not evidence.completion_requirements:
        raise CanonicalRerankQueryValidationError(
            "canonical rerank request requires atomic completion_requirements"
        )
    if not evidence.answer_target_ids:
        raise CanonicalRerankQueryValidationError(
            "canonical rerank request requires linked answer targets"
        )
    return evidence


def _linked_targets(
    evidence: RequiredEvidenceItem,
    answer_targets_by_id: Mapping[str, AnswerTarget],
    max_characters: int,
    max_token_like_units: int,
) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    for target_id in sorted(set(evidence.answer_target_ids)):
        target = answer_targets_by_id.get(target_id)
        if not isinstance(target, AnswerTarget):
            raise CanonicalRerankQueryValidationError(
                "canonical rerank evidence references an untrusted answer target"
            )
        anchor = _bounded_normalized(
            target.question_anchor,
            "answer target question_anchor",
            max_characters,
            max_token_like_units,
        )
        requested_output = _bounded_normalized(
            target.requested_output,
            "answer target requested_output",
            max_characters,
            max_token_like_units,
        )
        pairs.append((anchor, requested_output))
    if not pairs:
        raise CanonicalRerankQueryValidationError(
            "canonical rerank request has no linked answer target material"
        )
    return sorted(set(pairs))


def _request_values(
    values: object,
    label: str,
    max_characters: int,
    max_token_like_units: int,
) -> List[str]:
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise CanonicalRerankQueryValidationError(
            "%s must be a validated list of strings" % label
        )
    return _ordered_unique(
        values, label, max_characters, max_token_like_units
    )


def _canonical_query(
    request: RetrievalRequest,
    evidence_by_id: Mapping[str, RequiredEvidenceItem],
    answer_targets_by_id: Mapping[str, AnswerTarget],
    max_characters: int,
    max_token_like_units: int,
) -> str:
    if not isinstance(request, RetrievalRequest):
        raise CanonicalRerankQueryValidationError(
            "canonical rerank query requires a validated RetrievalRequest"
        )
    evidence = _required_evidence(request, evidence_by_id)
    requirements = _ordered_unique(
        (requirement.text for requirement in evidence.completion_requirements),
        "completion requirement",
        max_characters,
        max_token_like_units,
    )
    if not requirements:
        raise CanonicalRerankQueryValidationError(
            "canonical rerank request has no atomic completion requirement text"
        )
    targets = _linked_targets(
        evidence,
        answer_targets_by_id,
        max_characters,
        max_token_like_units,
    )
    statute_hints = _request_values(
        request.statute_hints,
        "statute_hints",
        max_characters,
        max_token_like_units,
    )
    query_terms = _request_values(
        request.query_terms,
        "query_terms",
        max_characters,
        max_token_like_units,
    )
    sections = [
        "[completion_requirements]\n" + "\n".join(requirements),
        "[answer_targets]\n" + "\n".join(
            "question_anchor: %s\nrequested_output: %s" % pair
            for pair in targets
        ),
        "[statute_hints]\n" + ("\n".join(statute_hints) or "-"),
        "[query_terms]\n" + ("\n".join(query_terms) or "-"),
    ]
    return _bounded_normalized(
        "\n\n".join(sections),
        "canonical rerank query",
        max_characters,
        max_token_like_units,
    )


def _audit(
    request: RetrievalRequest,
    final_request: RetrievalRequest,
    *,
    source: str,
    canonical_attempted: bool,
    fallback_reason_code: str | None = None,
    max_characters: int,
    max_token_like_units: int,
) -> Dict[str, object]:
    """Return bounded diagnostics without copying raw request/query text."""
    if source not in CANONICAL_RERANK_QUERY_SOURCES:
        raise ValueError("unknown canonical rerank query source")
    if (source == "raw_query_text_fallback") != (
        fallback_reason_code is not None
    ):
        raise ValueError("fallback source and reason must agree")

    original_text = request.rerank_query_text or ""
    final_text = final_request.rerank_query_text or ""
    # RetrievalPipeline uses rerank_query_text or query_text. Preserve that
    # exact truthiness contract in the audit, including an empty raw override.
    if final_request.rerank_query_text:
        effective_text = final_request.rerank_query_text
        effective_source = "rerank_query_text"
    else:
        effective_text = final_request.query_text
        effective_source = "query_text"
    if effective_source not in EFFECTIVE_RERANK_QUERY_SOURCES:
        raise ValueError("unknown effective rerank query source")

    audit: Dict[str, object] = {
        "schema_version": CANONICAL_RERANK_QUERY_SCHEMA_VERSION,
        "request_id": request.request_id,
        "issue_id": request.issue_id,
        "evidence_item_id": request.evidence_item_id,
        "source": source,
        "canonical_attempted": canonical_attempted,
        "fallback_applied": source == "raw_query_text_fallback",
        "fallback_reason_code": fallback_reason_code,
        "original_rerank_query_present": request.rerank_query_text is not None,
        "final_rerank_query_present": final_request.rerank_query_text is not None,
        "effective_rerank_query_source": effective_source,
        "max_characters": max_characters,
        "max_token_like_units": max_token_like_units,
        "canonical_output_within_bounds": (
            len(final_text) <= max_characters
            and _token_like_units(final_text) <= max_token_like_units
            if source == "canonical_missing_only"
            else None
        ),
    }
    audit.update(_query_metrics(original_text, "original_rerank_query"))
    audit.update(_query_metrics(final_text, "final_rerank_query"))
    audit.update(_query_metrics(effective_text, "effective_rerank_query"))
    return audit


def canonicalize_missing_rerank_query(
    request: RetrievalRequest,
    evidence_by_id: Mapping[str, RequiredEvidenceItem],
    answer_targets_by_id: Mapping[str, AnswerTarget],
    *,
    max_characters: int = DEFAULT_CANONICAL_RERANK_QUERY_MAX_CHARACTERS,
    max_token_like_units: int = DEFAULT_CANONICAL_RERANK_QUERY_MAX_TOKEN_LIKE_UNITS,
) -> Tuple[RetrievalRequest, Dict[str, object]]:
    """Return a copied request and immutable audit without touching recall fields."""
    _validate_bound(max_characters, "canonical rerank max_characters")
    _validate_bound(max_token_like_units, "canonical rerank max_token_like_units")
    if not isinstance(request, RetrievalRequest):
        raise CanonicalRerankQueryValidationError(
            "canonical rerank query requires a validated RetrievalRequest"
        )
    original = request.rerank_query_text
    if original is not None:
        final_request = request
        source = "raw"
    else:
        canonical = _canonical_query(
            request,
            evidence_by_id,
            answer_targets_by_id,
            max_characters,
            max_token_like_units,
        )
        final_request = replace(request, rerank_query_text=canonical)
        source = "canonical_missing_only"
    return final_request, _audit(
        request,
        final_request,
        source=source,
        canonical_attempted=original is None,
        max_characters=max_characters,
        max_token_like_units=max_token_like_units,
    )


def canonicalize_missing_rerank_query_or_preserve_raw(
    request: RetrievalRequest,
    evidence_by_id: Mapping[str, RequiredEvidenceItem],
    answer_targets_by_id: Mapping[str, AnswerTarget],
    *,
    max_characters: int = DEFAULT_CANONICAL_RERANK_QUERY_MAX_CHARACTERS,
    max_token_like_units: int = DEFAULT_CANONICAL_RERANK_QUERY_MAX_TOKEN_LIKE_UNITS,
) -> Tuple[RetrievalRequest, Dict[str, object]]:
    """Use canonical text when possible, otherwise preserve baseline BGE input.

    This is intentionally separate from the strict public canonicalizer above.
    It catches only the canonicalizer's typed validation error. Invalid config,
    unexpected failures, and an invalid request object still propagate.
    """
    try:
        return canonicalize_missing_rerank_query(
            request,
            evidence_by_id,
            answer_targets_by_id,
            max_characters=max_characters,
            max_token_like_units=max_token_like_units,
        )
    except CanonicalRerankQueryValidationError as error:
        if not isinstance(request, RetrievalRequest):
            raise
        # Do not set rerank_query_text to query_text: leaving it None causes the
        # existing RetrievalPipeline fallback to use the exact baseline value.
        return request, _audit(
            request,
            request,
            source="raw_query_text_fallback",
            canonical_attempted=True,
            fallback_reason_code=error.reason_code,
            max_characters=max_characters,
            max_token_like_units=max_token_like_units,
        )
