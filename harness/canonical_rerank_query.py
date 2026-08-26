"""Harness-owned canonical rerank query construction.

This module deliberately consumes typed, already-validated S1 structures only.
It never reads the benchmark question/background or infers legal pinpoints.
"""

from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import re
import unicodedata
from typing import Dict, Iterable, List, Mapping, Tuple

from .contracts import AnswerTarget, RequiredEvidenceItem, RetrievalRequest
from .validation import ValidationError


CANONICAL_RERANK_QUERY_SCHEMA_VERSION = "1.0"
DEFAULT_CANONICAL_RERANK_QUERY_MAX_CHARACTERS = 512
DEFAULT_CANONICAL_RERANK_QUERY_MAX_TOKEN_LIKE_UNITS = 96


class CanonicalRerankQueryValidationError(ValidationError):
    """Raised rather than falling back to untrusted query material."""


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
        raise CanonicalRerankQueryValidationError(
            "%s exceeds canonical rerank character bound" % label
        )
    if _token_like_units(normalized) > max_token_like_units:
        raise CanonicalRerankQueryValidationError(
            "%s exceeds canonical rerank token-like bound" % label
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
    original_text = original or ""
    final_text = final_request.rerank_query_text or ""
    audit: Dict[str, object] = {
        "schema_version": CANONICAL_RERANK_QUERY_SCHEMA_VERSION,
        "request_id": request.request_id,
        "issue_id": request.issue_id,
        "evidence_item_id": request.evidence_item_id,
        "source": source,
        "original_rerank_query_present": original is not None,
        "original_rerank_query_sha256": _sha256(original_text),
        "original_rerank_query_characters": len(original_text),
        "original_rerank_query_utf8_bytes": len(original_text.encode("utf-8")),
        "original_rerank_query_token_like_units": _token_like_units(original_text),
        "final_rerank_query_sha256": _sha256(final_text),
        "final_rerank_query_characters": len(final_text),
        "final_rerank_query_utf8_bytes": len(final_text.encode("utf-8")),
        "final_rerank_query_token_like_units": _token_like_units(final_text),
        "max_characters": max_characters,
        "max_token_like_units": max_token_like_units,
        "canonical_output_within_bounds": (
            source != "canonical_missing_only"
            or (
                len(final_text) <= max_characters
                and _token_like_units(final_text) <= max_token_like_units
            )
        ),
        "raw_request": asdict(request),
        "final_request": asdict(final_request),
    }
    return final_request, audit
