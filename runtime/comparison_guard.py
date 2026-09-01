"""Fail-closed parity checks for paired BM25/KURE experiments."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from runtime.local_ollama_executor import (
    DEFAULT_S1_TRUNCATION_RETRY_MAX_TOKENS,
    DEFAULT_SKILL_MAX_TOKENS,
    PUBLIC_ANSWER_MAX_CHARACTERS,
    PUBLIC_ANSWER_MAX_CLAIMS,
)


ALLOWED_RETRIEVER_COMPARISON_DIFFERENCES = {
    "condition",
    "retriever",
    "retriever_provenance",
}

RUNTIME_CONFIGURATION_DEFAULTS = {
    "ollama_endpoint": "http://127.0.0.1:11434/api/generate",
    "rerank_pool_k": 100,
    "final_top_k": 10,
    "rerank_query_mode": "combined_issue",
    "candidate_selection": "global_top_k",
    "per_evidence_min_k": 1,
    "candidate_budget_scope": "per_issue",
    "round_merge_mode": "raw_score",
    "dedup_mode": "none",
    "rerank_document_mode": "body_only",
    "input_format": "koblex_background_plus_question",
    "s1_max_tokens": DEFAULT_SKILL_MAX_TOKENS["legal_issue_and_query_planning"],
    "s1_truncation_retry_max_tokens": DEFAULT_S1_TRUNCATION_RETRY_MAX_TOKENS,
    "skill_max_tokens": dict(DEFAULT_SKILL_MAX_TOKENS),
    "s3_public_answer_max_characters": PUBLIC_ANSWER_MAX_CHARACTERS,
    "s3_public_answer_max_claims": PUBLIC_ANSWER_MAX_CLAIMS,
    "s3_public_answer_format": "conclusion_first_1_to_3_short_sentences",
    "s3_audit_fields": [
        "assumptions",
        "limitations",
        "claims",
        "claim_citations",
    ],
    "retrieval_stage_provenance_required_for_evaluation": True,
}


def resolve_frozen_configuration(configuration: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(configuration, Mapping):
        raise RuntimeError("frozen_configuration must be an object")
    resolved = dict(configuration)
    for key, value in RUNTIME_CONFIGURATION_DEFAULTS.items():
        if key not in resolved:
            resolved[key] = list(value) if isinstance(value, list) else (
                dict(value) if isinstance(value, dict) else value
            )
    return resolved


def _entry_signature(entries: Any) -> Sequence[tuple[int, str, int]]:
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("comparison manifests must contain non-empty entries")
    signature = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise RuntimeError("comparison manifest entry must be an object")
        try:
            signature.append(
                (
                    int(entry["ordinal"]),
                    str(entry["question_id"]),
                    int(entry["n_hops"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("comparison manifest entry is invalid") from exc
    return tuple(signature)


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_retriever_comparison(
    manifest: Mapping[str, Any],
    reference_manifest: Mapping[str, Any],
    manifest_path: Path,
    reference_manifest_path: Path,
) -> Dict[str, Any]:
    source = manifest.get("source_dataset")
    reference_source = reference_manifest.get("source_dataset")
    if not isinstance(source, Mapping) or dict(source) != dict(reference_source or {}):
        raise RuntimeError("BM25/KURE source_dataset mismatch")

    entries = _entry_signature(manifest.get("entries"))
    reference_entries = _entry_signature(reference_manifest.get("entries"))
    if entries != reference_entries:
        raise RuntimeError(
            "BM25/KURE entry mismatch: both manifests must use the same ordered questions"
        )

    configuration = resolve_frozen_configuration(
        manifest.get("frozen_configuration", {})
    )
    reference_configuration = resolve_frozen_configuration(
        reference_manifest.get("frozen_configuration", {})
    )
    retrievers = {
        str(configuration.get("retriever") or ""),
        str(reference_configuration.get("retriever") or ""),
    }
    if retrievers != {"bm25", "kure"}:
        raise RuntimeError(
            "comparison pair must contain exactly one BM25 and one KURE retriever"
        )

    comparable = {
        key: value
        for key, value in configuration.items()
        if key not in ALLOWED_RETRIEVER_COMPARISON_DIFFERENCES
    }
    reference_comparable = {
        key: value
        for key, value in reference_configuration.items()
        if key not in ALLOWED_RETRIEVER_COMPARISON_DIFFERENCES
    }
    differing_keys = sorted(
        key
        for key in set(comparable) | set(reference_comparable)
        if comparable.get(key) != reference_comparable.get(key)
    )
    if differing_keys:
        raise RuntimeError(
            "BM25/KURE configuration mismatch outside allowed fields: %s"
            % ", ".join(differing_keys)
        )

    return {
        "status": "VALIDATED_IDENTICAL_EXCEPT_RETRIEVER",
        "allowed_differences": sorted(ALLOWED_RETRIEVER_COMPARISON_DIFFERENCES),
        "entry_count": len(entries),
        "primary_manifest": str(manifest_path),
        "primary_retriever": configuration["retriever"],
        "reference_manifest": str(reference_manifest_path),
        "reference_retriever": reference_configuration["retriever"],
        "comparable_configuration_sha256": _canonical_sha256(comparable),
    }


def validate_bm25s_first_stage_ablation(
    c02_manifest: Mapping[str, Any],
    ablation_manifest: Mapping[str, Any],
    c02_manifest_path: Path,
    ablation_manifest_path: Path,
) -> Dict[str, Any]:
    """Validate the separately named ParSeR-compatible bm25s C02 ablation.

    This is intentionally not an extension of the historical ``bm25``/KURE
    comparison path: ``bm25s_parser`` identifies the bm25s backend explicitly,
    so it cannot be mistaken for the protected FTS5 reference configuration.
    """
    source = c02_manifest.get("source_dataset")
    ablation_source = ablation_manifest.get("source_dataset")
    if not isinstance(source, Mapping) or dict(source) != dict(ablation_source or {}):
        raise RuntimeError("C02/bm25s source_dataset mismatch")
    c02_entries = _entry_signature(c02_manifest.get("entries"))
    ablation_entries = _entry_signature(ablation_manifest.get("entries"))
    if c02_entries != ablation_entries:
        raise RuntimeError("C02/bm25s entry mismatch")
    c02_configuration = resolve_frozen_configuration(
        c02_manifest.get("frozen_configuration", {})
    )
    ablation_configuration = resolve_frozen_configuration(
        ablation_manifest.get("frozen_configuration", {})
    )
    if c02_configuration.get("retriever") != "kure":
        raise RuntimeError("C02 bm25s ablation basis must use KURE")
    if ablation_configuration.get("retriever") != "bm25s_parser":
        raise RuntimeError("C02 bm25s ablation must declare retriever=bm25s_parser")
    comparable = {
        key: value
        for key, value in c02_configuration.items()
        if key not in ALLOWED_RETRIEVER_COMPARISON_DIFFERENCES
    }
    ablation_comparable = {
        key: value
        for key, value in ablation_configuration.items()
        if key not in ALLOWED_RETRIEVER_COMPARISON_DIFFERENCES
    }
    differing_keys = sorted(
        key
        for key in set(comparable) | set(ablation_comparable)
        if comparable.get(key) != ablation_comparable.get(key)
    )
    if differing_keys:
        raise RuntimeError(
            "C02 bm25s configuration mismatch outside allowed fields: %s"
            % ", ".join(differing_keys)
        )
    provenance = ablation_configuration.get("retriever_provenance")
    if not isinstance(provenance, Mapping) or provenance.get("backend") != "bm25s.BM25":
        raise RuntimeError("C02 bm25s ablation must declare backend=bm25s.BM25")
    if provenance.get("top_k") != 100:
        raise RuntimeError("C02 bm25s ablation must declare top_k=100")
    if provenance.get("query_tokenization") != "bm25s.tokenize([query])":
        raise RuntimeError("C02 bm25s ablation query tokenization is not ParSeR-compatible")
    return {
        "status": "VALIDATED_C02_BM25S_FIRST_STAGE_ABLATION",
        "entry_count": len(c02_entries),
        "c02_manifest": str(c02_manifest_path),
        "bm25s_manifest": str(ablation_manifest_path),
        "allowed_differences": sorted(ALLOWED_RETRIEVER_COMPARISON_DIFFERENCES),
        "comparable_configuration_sha256": _canonical_sha256(comparable),
    }
