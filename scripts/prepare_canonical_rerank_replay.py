#!/usr/bin/env python3
"""Prepare an offline canonical-rerank replay from a receipt-bound result.

This tool only reads archived artifacts and writes a preparation JSON.  It
never loads a retriever, BGE, model, benchmark, or launcher.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PREPARATION_SCHEMA_VERSION = "1.0"


class ReplayPreparationError(RuntimeError):
    """Fail closed when archived replay inputs are not independently bound."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayPreparationError("invalid %s JSON: %s" % (label, path)) from exc
    if not isinstance(parsed, Mapping):
        raise ReplayPreparationError("%s must be a JSON object" % label)
    return parsed


def _require_allowlisted(path: Path, allowed: Iterable[str], label: str) -> str:
    if not path.is_file():
        raise ReplayPreparationError("%s is not a file: %s" % (label, path))
    digest = sha256_file(path)
    allowed_values = set(allowed)
    if not allowed_values or digest not in allowed_values:
        raise ReplayPreparationError("%s SHA256 is not allowlisted" % label)
    return digest


def verify_source_receipt(
    *,
    result_path: Path,
    trace_path: Path,
    manifest_path: Path,
    receipt_path: Path,
    result_allowlist: Iterable[str],
    trace_allowlist: Iterable[str],
    manifest_allowlist: Iterable[str],
    receipt_allowlist: Iterable[str],
    expected_source_git_commit: str,
    expected_source_git_tree: str,
) -> Dict[str, str]:
    """Verify every archived input before any state is parsed."""
    hashes = {
        "source_result_sha256": _require_allowlisted(
            result_path, result_allowlist, "source result"
        ),
        "source_trace_sha256": _require_allowlisted(
            trace_path, trace_allowlist, "source trace"
        ),
        "source_manifest_sha256": _require_allowlisted(
            manifest_path, manifest_allowlist, "source manifest"
        ),
        "source_receipt_sha256": _require_allowlisted(
            receipt_path, receipt_allowlist, "source receipt"
        ),
    }
    receipt = _read_json(receipt_path, "source receipt")
    # A receipt cannot contain its own file hash without a circular digest.
    # Its allowlist is independently verified above; the receipt itself binds
    # the result, trace, manifest, and source tree.
    receipt_bindings = {
        key: value for key, value in hashes.items()
        if key != "source_receipt_sha256"
    }
    expected = {
        **receipt_bindings,
        "source_git_commit": expected_source_git_commit,
        "source_git_tree": expected_source_git_tree,
    }
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ReplayPreparationError(
            "source receipt does not bind the exact allowlisted artifacts and tree"
        )
    return {
        **hashes,
        "source_git_commit": expected_source_git_commit,
        "source_git_tree": expected_source_git_tree,
    }


def _state_payload(result: Mapping[str, Any]) -> Dict[str, Any]:
    state = result.get("state")
    if not isinstance(state, Mapping):
        raise ReplayPreparationError("source result must contain a state object")
    legal_issues = state.get("legal_issues")
    answer_targets = state.get("answer_targets")
    evidence = state.get("required_evidence_items")
    requests = state.get("query_history")
    question = state.get("normalized_question")
    if not isinstance(question, str) or not question.strip():
        raise ReplayPreparationError("source state has no normalized_question")
    if not all(isinstance(value, list) for value in (
        legal_issues, answer_targets, evidence, requests
    )):
        raise ReplayPreparationError("source state has malformed structured S1 fields")
    return {
        "question": question,
        "payload": {
            "legal_issues": legal_issues,
            "answer_targets": answer_targets,
            "required_evidence_items": evidence,
            "retrieval_requests": requests,
        },
    }


def prepare_from_archived_result(
    result: Mapping[str, Any],
    *,
    max_characters: int,
    max_token_like_units: int,
) -> List[Dict[str, Any]]:
    """Revalidate typed archived S1 state and construct missing-only transforms."""
    # Imports are intentionally local: the tool has no retrieval/model imports.
    from harness.canonical_rerank_query import canonicalize_missing_rerank_query
    from harness.validation import validate_initial_plan

    source = _state_payload(result)
    try:
        _, targets, evidence, requests = validate_initial_plan(
            source["payload"],
            question=source["question"],
            include_answer_targets=True,
        )
    except Exception as exc:
        raise ReplayPreparationError(
            "archived S1 state failed current fail-closed validation"
        ) from exc
    evidence_by_id = {
        item.evidence_item_id: item for item in evidence
    }
    targets_by_id = {
        item.answer_target_id: item for item in targets
    }
    transforms: List[Dict[str, Any]] = []
    for request in requests:
        _, audit = canonicalize_missing_rerank_query(
            request,
            evidence_by_id,
            targets_by_id,
            max_characters=max_characters,
            max_token_like_units=max_token_like_units,
        )
        transforms.append(audit)
    return transforms


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="prepare an offline, receipt-bound canonical rerank replay"
    )
    parser.add_argument("--source-result", type=Path, required=True)
    parser.add_argument("--source-trace", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--source-receipt", type=Path, required=True)
    parser.add_argument("--allow-result-sha256", action="append", required=True)
    parser.add_argument("--allow-trace-sha256", action="append", required=True)
    parser.add_argument("--allow-manifest-sha256", action="append", required=True)
    parser.add_argument("--allow-receipt-sha256", action="append", required=True)
    parser.add_argument("--expected-source-git-commit", required=True)
    parser.add_argument("--expected-source-git-tree", required=True)
    parser.add_argument("--max-characters", type=int, default=512)
    parser.add_argument("--max-token-like-units", type=int, default=96)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bindings = verify_source_receipt(
        result_path=args.source_result,
        trace_path=args.source_trace,
        manifest_path=args.source_manifest,
        receipt_path=args.source_receipt,
        result_allowlist=args.allow_result_sha256,
        trace_allowlist=args.allow_trace_sha256,
        manifest_allowlist=args.allow_manifest_sha256,
        receipt_allowlist=args.allow_receipt_sha256,
        expected_source_git_commit=args.expected_source_git_commit,
        expected_source_git_tree=args.expected_source_git_tree,
    )
    result = _read_json(args.source_result, "source result")
    transforms = prepare_from_archived_result(
        result,
        max_characters=args.max_characters,
        max_token_like_units=args.max_token_like_units,
    )
    payload = {
        "schema_version": PREPARATION_SCHEMA_VERSION,
        "mode": "PREPARE_ONLY_NO_LIVE_RETRIEVAL",
        "source_bindings": bindings,
        "canonical_rerank_query": {
            "max_characters": args.max_characters,
            "max_token_like_units": args.max_token_like_units,
            "transform_count": len(transforms),
            "transforms": transforms,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
