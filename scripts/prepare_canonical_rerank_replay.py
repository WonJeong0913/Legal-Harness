#!/usr/bin/env python3
"""Prepare a receipt-bound, no-live-call C02 qa150 rerank replay artifact.

The executable deliberately supports exactly the immutable C02 qa150 source
profile below. It reads prior artifacts, creates a canonical missing-only BGE
query preparation, and never loads a model, KURE, BGE, BM25, skills, S2, S3,
policy, evaluator, benchmark, or launcher.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Mapping, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
PREPARATION_SCHEMA_VERSION = "2.0"
C02_QA150_PROFILE: Dict[str, Any] = {
    "question_id": "qa_150_1hop_277",
    "sequence": 28,
    "ordinal": 86,
    "n_hops": 1,
    "retry": False,
    "run_id": "c9866ea5-9d23-45ee-b84d-6fead8e553b3",
    "receipt_filename": "028_ord086_qa_150_1hop_277.json",
    "batch_name": "c02e281-targeted-resume-ord042-054-061-226-20260826",
    "source_commit": "c02e2818ad54e9d5a1a9bd02b604e987192bb244",
    "source_tree": "9fcb0ebceb0b3d96955f1626f2c952a457be930f",
    "source_manifest_sha256": (
        "40591e4b6963abbe11b5b95e021c2abba9fb5b5bd7c8e2c379d04de9f6e41956"
    ),
    "primary_manifest_sha256": (
        "4e1109bb6930a96125ddcc3e26a16ff2f356438197a9d2e862e0bbec8a07ac61"
    ),
    "initial_request_ids": ["RQ1"],
    "sha256": {
        "result": (
            "22912649bd51dab2baa9dce0972bf66801a3117f1fbeb615f4b064a3f2ddc2eb"
        ),
        "metadata": (
            "10bde21ce80237dcab7e6af6796e20d926b2c03d49f2d5e12b08515d5d9848b0"
        ),
        "events": (
            "2d9484dda7e00b6d3d8af1e7ae39bec9f0388d19798ead42b968d8cb180fa5ed"
        ),
        "retrieval_stages": (
            "3f29ec9c10dd216e5504c0de2b64c8ee5e7355700332bb45ee0724e064c17385"
        ),
        "batch_manifest": (
            "74c61195e6ad5a63913106a33daa517b6bb2c0c6110dc513a23dc6e78b96f4c8"
        ),
        "task_receipt": (
            "c8cef3b5811e273d1045d29c3ef831664c623364902cf6688fce1e3574b7205a"
        ),
    },
}


class ReplayPreparationError(RuntimeError):
    """Fail closed when C02 qa150 provenance or structure differs."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _regular_file(path: Path, label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise ReplayPreparationError("%s must be a regular file: %s" % (label, path))


def _verify_hash(path: Path, expected: str, label: str) -> str:
    _regular_file(path, label)
    observed = sha256_file(path)
    if observed != expected:
        raise ReplayPreparationError("%s SHA256 does not match qa150 profile" % label)
    return observed


def _read_json(path: Path, label: str) -> Mapping[str, Any]:
    _regular_file(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayPreparationError("invalid %s JSON" % label) from exc
    if not isinstance(value, Mapping):
        raise ReplayPreparationError("%s must be a JSON object" % label)
    return value


def _read_jsonl(path: Path, label: str) -> List[Mapping[str, Any]]:
    _regular_file(path, label)
    rows: List[Mapping[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            raise ReplayPreparationError("%s contains blank line %d" % (label, line_number))
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReplayPreparationError(
                "invalid %s JSONL line %d" % (label, line_number)
            ) from exc
        if not isinstance(value, Mapping):
            raise ReplayPreparationError(
                "%s JSONL line %d must be an object" % (label, line_number)
            )
        rows.append(value)
    if not rows:
        raise ReplayPreparationError("%s must not be empty" % label)
    return rows


def c02_paths_from_root(root: Path, profile: Mapping[str, Any] = C02_QA150_PROFILE) -> Dict[str, Path]:
    root = root.resolve()
    run_directory = root / "records" / "runs" / str(profile["run_id"])
    batch = root / "batches" / str(profile["batch_name"])
    return {
        "result": run_directory / "result.json",
        "metadata": run_directory / "metadata.json",
        "events": run_directory / "events.jsonl",
        "retrieval_stages": run_directory / "retrieval_stages.jsonl",
        "batch_manifest": batch / "manifest.json",
        "task_receipt": batch / "task_receipts" / str(profile["receipt_filename"]),
    }


def _verify_path_geometry(
    paths: Mapping[str, Path], profile: Mapping[str, Any]
) -> None:
    """Reject artifact copies before their content is interpreted."""
    result = paths["result"]
    run_directory = result.parent
    if result.name != "result.json" or run_directory.name != profile["run_id"]:
        raise ReplayPreparationError("result path does not match qa150 run geometry")
    expected_run_files = {
        "metadata": "metadata.json",
        "events": "events.jsonl",
        "retrieval_stages": "retrieval_stages.jsonl",
    }
    for key, filename in expected_run_files.items():
        if paths[key].parent != run_directory or paths[key].name != filename:
            raise ReplayPreparationError("%s path does not match qa150 run geometry" % key)
    if run_directory.parent.name != "runs" or run_directory.parent.parent.name != "records":
        raise ReplayPreparationError("result path does not use C02 records/runs geometry")
    source_root = run_directory.parent.parent.parent
    manifest = paths["batch_manifest"]
    if (
        manifest.name != "manifest.json"
        or manifest.parent.name != profile["batch_name"]
        or manifest.parent.parent.name != "batches"
        or manifest.parent.parent.parent != source_root
    ):
        raise ReplayPreparationError("batch manifest path does not match qa150 batch geometry")
    receipt = paths["task_receipt"]
    if (
        receipt.name != profile["receipt_filename"]
        or receipt.parent.name != "task_receipts"
        or receipt.parent.parent != manifest.parent
    ):
        raise ReplayPreparationError("task receipt path does not match qa150 batch geometry")


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReplayPreparationError("%s must be an object" % label)
    return value


def _require_equal(value: Any, expected: Any, label: str) -> None:
    if value != expected:
        raise ReplayPreparationError("%s does not match qa150 profile" % label)


def _verify_receipt(
    receipt: Mapping[str, Any],
    result_path: Path,
    profile: Mapping[str, Any],
) -> None:
    _require_equal(
        receipt.get("schema_version"),
        "c02_targeted_resume_task_receipt_v1",
        "receipt schema_version",
    )
    task = _require_mapping(receipt.get("task"), "receipt task")
    for key in ("sequence", "ordinal", "question_id", "n_hops", "retry"):
        _require_equal(task.get(key), profile[key], "receipt task.%s" % key)
    summary_row = _require_mapping(receipt.get("summary_row"), "receipt summary_row")
    if receipt.get("summary_sha256") != canonical_sha256(summary_row):
        raise ReplayPreparationError("receipt summary_sha256 does not bind summary_row")
    for key in (
        "sequence",
        "ordinal",
        "question_id",
        "n_hops",
        "retry",
        "run_id",
    ):
        _require_equal(summary_row.get(key), profile[key], "receipt summary_row.%s" % key)
    _require_equal(summary_row.get("record_result_file"), str(result_path), "receipt result path")
    _require_equal(
        summary_row.get("record_directory"),
        str(result_path.parent),
        "receipt record directory",
    )
    created = receipt.get("record_directories_created")
    if created != [str(result_path.parent)]:
        raise ReplayPreparationError("receipt must bind exactly the qa150 record directory")
    if receipt.get("record_directories_created") != created:
        raise ReplayPreparationError("receipt created-directory copies disagree")


def _verify_metadata(metadata: Mapping[str, Any], profile: Mapping[str, Any]) -> None:
    _require_equal(metadata.get("run_id"), profile["run_id"], "metadata run_id")
    _require_equal(
        metadata.get("question_id"), profile["question_id"], "metadata question_id"
    )
    _require_equal(
        metadata.get("git_commit"), profile["source_commit"], "metadata git_commit"
    )
    snapshot = _require_mapping(metadata.get("source_snapshot"), "metadata source_snapshot")
    for key in ("git_commit", "git_tree", "source_manifest_sha256"):
        expected_key = {
            "git_commit": "source_commit",
            "git_tree": "source_tree",
            "source_manifest_sha256": "source_manifest_sha256",
        }[key]
        _require_equal(snapshot.get(key), profile[expected_key], "source_snapshot.%s" % key)
    configuration = _require_mapping(metadata.get("configuration"), "metadata configuration")
    required_configuration = {
        "retriever": "kure",
        "model": "legal-harness-qwen38-q8",
        "rerank_query_mode": "per_request",
        "rerank_pool_k": 100,
        "final_top_k": 10,
        "source_manifest_sha256": profile["source_manifest_sha256"],
    }
    for key, expected in required_configuration.items():
        _require_equal(configuration.get(key), expected, "metadata configuration.%s" % key)


def _verify_batch_manifest(
    manifest: Mapping[str, Any], profile: Mapping[str, Any]
) -> None:
    _require_equal(
        manifest.get("schema_version"),
        "c02_targeted_resume_batch_manifest_v1",
        "batch manifest schema_version",
    )
    _require_equal(
        manifest.get("parent_manifest_sha256"),
        profile["primary_manifest_sha256"],
        "batch parent_manifest_sha256",
    )
    policy = _require_mapping(manifest.get("execution_policy"), "batch execution_policy")
    _require_equal(policy.get("primary_retriever"), "kure", "batch primary retriever")
    _require_equal(
        policy.get("paired_bm25"),
        "READ_ONLY_CONFIGURATION_GUARD_NEVER_EXECUTED",
        "batch paired BM25 prohibition",
    )
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise ReplayPreparationError("batch manifest entries must be a list")
    matching = [
        entry
        for entry in entries
        if isinstance(entry, Mapping)
        and all(
            entry.get(key) == profile[key]
            for key in ("sequence", "ordinal", "question_id", "n_hops", "retry")
        )
    ]
    if len(matching) != 1:
        raise ReplayPreparationError("batch manifest does not bind exactly one qa150 task")


def _initial_payload(
    result: Mapping[str, Any],
    *,
    expected_request_ids: Sequence[str] | None = None,
) -> Tuple[str, Dict[str, Any], List[str]]:
    state = _require_mapping(result.get("state"), "result state")
    question = state.get("normalized_question")
    if not isinstance(question, str) or not question.strip():
        raise ReplayPreparationError("result state has no normalized_question")
    raw_history = state.get("query_history")
    if not isinstance(raw_history, list):
        raise ReplayPreparationError("result state query_history must be a list")
    selected = []
    excluded_gap_ids = []
    for request in raw_history:
        if not isinstance(request, Mapping):
            raise ReplayPreparationError("result query_history item must be an object")
        request_id = request.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise ReplayPreparationError("result query_history request_id is invalid")
        if request_id.startswith("RQ"):
            selected.append(dict(request))
        elif request_id.startswith("GRQ"):
            excluded_gap_ids.append(request_id)
        else:
            raise ReplayPreparationError(
                "result query_history contains non-initial, non-gap request ID"
            )
    selected_ids = [request["request_id"] for request in selected]
    if not selected or len(selected_ids) != len(set(selected_ids)):
        raise ReplayPreparationError("result has no unique initial RQ requests")
    if expected_request_ids is not None and selected_ids != list(expected_request_ids):
        raise ReplayPreparationError("initial RQ request IDs do not match qa150 profile")
    for key in ("legal_issues", "answer_targets", "required_evidence_items"):
        if not isinstance(state.get(key), list):
            raise ReplayPreparationError("result state %s must be a list" % key)
    return question, {
        "legal_issues": state["legal_issues"],
        "answer_targets": state["answer_targets"],
        "required_evidence_items": state["required_evidence_items"],
        "retrieval_requests": selected,
    }, excluded_gap_ids


def _validate_initial_and_transform(
    result: Mapping[str, Any],
    *,
    max_characters: int,
    max_token_like_units: int,
    expected_request_ids: Sequence[str] | None = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    # These imports are intentionally the only harness imports: no retriever,
    # model, skill executor, policy, coverage, or answer code is imported.
    from harness.canonical_rerank_query import canonicalize_missing_rerank_query
    from harness.validation import validate_initial_plan

    question, payload, excluded_gap_ids = _initial_payload(
        result, expected_request_ids=expected_request_ids
    )
    try:
        _, targets, evidence, requests = validate_initial_plan(
            payload, question=question, include_answer_targets=True
        )
    except Exception as exc:
        raise ReplayPreparationError(
            "initial RQ-only reconstruction failed fail-closed validation"
        ) from exc
    evidence_by_id = {item.evidence_item_id: item for item in evidence}
    targets_by_id = {item.answer_target_id: item for item in targets}
    audits: List[Dict[str, Any]] = []
    try:
        for request in requests:
            _, audit = canonicalize_missing_rerank_query(
                request,
                evidence_by_id,
                targets_by_id,
                max_characters=max_characters,
                max_token_like_units=max_token_like_units,
            )
            audits.append(audit)
    except Exception as exc:
        raise ReplayPreparationError(
            "initial RQ-only canonical transform failed fail-closed validation"
        ) from exc
    return audits, excluded_gap_ids


def _stage_observation(
    stage_rows: Sequence[Mapping[str, Any]],
    initial_request_id: str,
) -> Dict[str, Any]:
    request_rows = [
        row
        for row in stage_rows
        if initial_request_id in row.get("source_request_ids", [])
        and row.get("retrieval_round") == 1
    ]
    first_stage = [
        row for row in request_rows if row.get("candidate_stage") == "first_stage"
    ]
    request_rerank = [
        row for row in request_rows if row.get("candidate_stage") == "request_rerank"
    ]
    round_selected = [
        row for row in request_rows if row.get("candidate_stage") == "round_selected"
    ]
    if not first_stage or not request_rerank:
        raise ReplayPreparationError("retrieval stages lack initial first-stage/BGE rows")
    rank_one = [
        row for row in first_stage if row.get("first_stage_rank") == 1
    ]
    if len(rank_one) != 1:
        raise ReplayPreparationError("retrieval stages lack a unique initial first-stage rank one")
    first = rank_one[0]
    provision_id = first.get("provision_id")
    if not isinstance(provision_id, str) or not provision_id:
        raise ReplayPreparationError("first-stage rank one has no provision ID")
    rerank_rows = [
        row for row in request_rerank if row.get("provision_id") == provision_id
    ]
    if len(rerank_rows) != 1:
        raise ReplayPreparationError("initial first-stage rank one lacks one BGE observation")
    if any(row.get("provision_id") == provision_id for row in round_selected):
        raise ReplayPreparationError(
            "qa150 source no longer demonstrates first-stage top-one loss after BGE"
        )
    return {
        "source_request_id": initial_request_id,
        "retrieval_round": 1,
        "request_stage_counts": dict(
            sorted(Counter(str(row.get("candidate_stage")) for row in request_rows).items())
        ),
        "first_stage_top1": {
            "provision_id": provision_id,
            "first_stage_rank": first.get("first_stage_rank"),
            "first_stage_score": first.get("first_stage_score"),
        },
        "first_stage_top1_bge": {
            "rerank_rank": rerank_rows[0].get("rerank_rank"),
            "rerank_score": rerank_rows[0].get("rerank_score"),
        },
        "round_selected_count": len(round_selected),
        "observed_first_stage_top1_absent_from_round_selected": True,
        "uses_gold_or_benchmark_answer": False,
    }


def prepare_c02_qa150(
    paths: Mapping[str, Path],
    *,
    max_characters: int = 512,
    max_token_like_units: int = 96,
    profile: Mapping[str, Any] = C02_QA150_PROFILE,
) -> Dict[str, Any]:
    """Create a static-profile preparation; this function has no live calls."""
    if (
        isinstance(max_characters, bool)
        or not isinstance(max_characters, int)
        or max_characters < 1
        or isinstance(max_token_like_units, bool)
        or not isinstance(max_token_like_units, int)
        or max_token_like_units < 1
    ):
        raise ReplayPreparationError("canonical bounds must be positive integers")
    path_keys = (
        "result",
        "metadata",
        "events",
        "retrieval_stages",
        "batch_manifest",
        "task_receipt",
    )
    if set(paths) != set(path_keys):
        raise ReplayPreparationError("qa150 preparation paths must be exact")
    _verify_path_geometry(paths, profile)
    profile_hashes = _require_mapping(profile.get("sha256"), "qa150 hash profile")
    bindings = {
        key + "_sha256": _verify_hash(
            paths[key], str(profile_hashes[key]), key.replace("_", " ")
        )
        for key in path_keys
    }
    result = _read_json(paths["result"], "result")
    metadata = _read_json(paths["metadata"], "metadata")
    receipt = _read_json(paths["task_receipt"], "task receipt")
    manifest = _read_json(paths["batch_manifest"], "batch manifest")
    events = _read_jsonl(paths["events"], "events")
    stages = _read_jsonl(paths["retrieval_stages"], "retrieval stages")
    _require_equal(result.get("run_id"), profile["run_id"], "result run_id")
    _verify_receipt(receipt, paths["result"], profile)
    _verify_metadata(metadata, profile)
    _verify_batch_manifest(manifest, profile)
    if any(event.get("run_id") != profile["run_id"] for event in events):
        raise ReplayPreparationError("events do not bind exactly one qa150 run_id")
    provenance = _require_mapping(result.get("retrieval_provenance"), "result retrieval_provenance")
    _require_equal(provenance.get("stage_file"), "retrieval_stages.jsonl", "result stage file")
    observed_counts = Counter(str(row.get("candidate_stage")) for row in stages)
    if provenance.get("stage_record_counts") != dict(sorted(observed_counts.items())):
        raise ReplayPreparationError("retrieval-stage counts do not reconcile with result")
    transforms, excluded_gap_ids = _validate_initial_and_transform(
        result,
        max_characters=max_characters,
        max_token_like_units=max_token_like_units,
        expected_request_ids=profile["initial_request_ids"],
    )
    if not excluded_gap_ids:
        raise ReplayPreparationError("qa150 source must contain excluded GRQ history")
    initial_ids = [audit["request_id"] for audit in transforms]
    if initial_ids != list(profile["initial_request_ids"]):
        raise ReplayPreparationError("canonical transforms do not cover exactly initial RQ IDs")
    return {
        "schema_version": PREPARATION_SCHEMA_VERSION,
        "mode": "PREPARE_ONLY_NO_LIVE_KURE_OR_BGE",
        "source_profile": {
            key: profile[key]
            for key in (
                "question_id",
                "sequence",
                "ordinal",
                "n_hops",
                "retry",
                "run_id",
                "source_commit",
                "source_tree",
                "source_manifest_sha256",
            )
        },
        "source_bindings": bindings,
        "initial_plan_reconstruction": {
            "selected_initial_request_ids": initial_ids,
            "excluded_gap_request_ids": excluded_gap_ids,
            "raw_query_history_is_not_replayed": True,
        },
        "canonical_rerank_query": {
            "max_characters": max_characters,
            "max_token_like_units": max_token_like_units,
            "transform_count": len(transforms),
            "transforms": transforms,
        },
        "retrieval_stage_observation": _stage_observation(stages, initial_ids[0]),
        "live_executor": {
            "status": "NOT_IMPLEMENTED_NOT_EXECUTED",
            "boundary": (
                "This preparation is not a retrieval executor. Any future live "
                "KURE/BGE-only replay must be separately authorized and must not "
                "load skills, S2, S3, policy, BM25, evaluator, benchmark, or launcher."
            ),
        },
    }


def preflight_initial_structured_transforms(
    record_root: Path,
    *,
    max_characters: int = 512,
    max_token_like_units: int = 96,
) -> Dict[str, Any]:
    """Read-only structural preflight over current saved result records."""
    if not record_root.is_dir() or record_root.is_symlink():
        raise ReplayPreparationError("preflight record root must be a real directory")
    result_paths = sorted(record_root.glob("*/result.json"))
    directories = sorted(path for path in record_root.iterdir() if path.is_dir())
    failures = []
    transform_count = 0
    eligible_runs = 0
    for result_path in result_paths:
        try:
            result = _read_json(result_path, "preflight result")
            transforms, _excluded = _validate_initial_and_transform(
                result,
                max_characters=max_characters,
                max_token_like_units=max_token_like_units,
            )
            eligible_runs += 1
            transform_count += len(transforms)
        except ReplayPreparationError as exc:
            cause = exc.__cause__
            failures.append({
                "record_directory": result_path.parent.name,
                "error": str(exc),
                "cause": str(cause) if cause is not None else None,
            })
    return {
        "schema_version": "c17_canonical_rerank_preflight_v1",
        "mode": "READ_ONLY_STRUCTURED_TRANSFORM_PREFLIGHT",
        "record_directory_count": len(directories),
        "result_file_count": len(result_paths),
        "missing_result_file_count": len(directories) - len(result_paths),
        "eligible_run_count": eligible_runs,
        "valid_transform_count": transform_count,
        "failure_count": len(failures),
        "failures": failures,
        "max_characters": max_characters,
        "max_token_like_units": max_token_like_units,
    }


def _validate_all_saved_requests_with_fallback(
    result: Mapping[str, Any],
    *,
    max_characters: int,
    max_token_like_units: int,
) -> List[Dict[str, Any]]:
    """Reconstruct saved RQ/GRQ requests without retrieval or model loading."""
    from harness.canonical_rerank_query import (
        canonicalize_missing_rerank_query_or_preserve_raw,
    )
    from harness.run_state import RunState
    from harness.validation import validate_gap_plan, validate_initial_plan

    question, payload, _excluded_gap_ids = _initial_payload(result)
    try:
        issues, targets, evidence, initial_requests = validate_initial_plan(
            payload,
            question=question,
            include_answer_targets=True,
        )
    except Exception as exc:
        raise ReplayPreparationError(
            "initial RQ-only reconstruction failed fail-closed validation"
        ) from exc

    state = RunState(
        question=question,
        normalized_question=question,
        run_id=str(result.get("run_id") or "saved-request-preflight"),
    )
    state.legal_issues = issues
    state.answer_targets = targets
    state.required_evidence_items = evidence
    evidence_by_id = state.evidence_by_id()
    targets_by_id = state.answer_target_by_id()
    audits: List[Dict[str, Any]] = []

    for request in initial_requests:
        _, audit = canonicalize_missing_rerank_query_or_preserve_raw(
            request,
            evidence_by_id,
            targets_by_id,
            max_characters=max_characters,
            max_token_like_units=max_token_like_units,
        )
        audit["plan_kind"] = "initial"
        audits.append(audit)
    state.query_history = list(initial_requests)

    saved_state = _require_mapping(result.get("state"), "result state")
    raw_history = saved_state.get("query_history")
    if not isinstance(raw_history, list):
        raise ReplayPreparationError("result state query_history must be a list")
    for raw_request in raw_history:
        if not isinstance(raw_request, Mapping):
            raise ReplayPreparationError("result query_history item must be an object")
        request_id = raw_request.get("request_id")
        if not isinstance(request_id, str):
            raise ReplayPreparationError("result query_history request_id is invalid")
        if not request_id.startswith("GRQ"):
            continue
        try:
            gap_requests = validate_gap_plan(
                {"gap_retrieval_requests": [dict(raw_request)]},
                state,
            )
        except Exception as exc:
            raise ReplayPreparationError(
                "saved GRQ reconstruction failed fail-closed validation"
            ) from exc
        request = gap_requests[0]
        _, audit = canonicalize_missing_rerank_query_or_preserve_raw(
            request,
            evidence_by_id,
            targets_by_id,
            max_characters=max_characters,
            max_token_like_units=max_token_like_units,
        )
        audit["plan_kind"] = "gap"
        audits.append(audit)
        state.query_history.append(request)
    return audits


def preflight_saved_request_fallback_compatibility(
    record_root: Path,
    *,
    max_characters: int = 512,
    max_token_like_units: int = 96,
) -> Dict[str, Any]:
    """Read-only all-RQ/GRQ check for the opt-in neutral fallback contract."""
    if not record_root.is_dir() or record_root.is_symlink():
        raise ReplayPreparationError("preflight record root must be a real directory")
    result_paths = sorted(record_root.glob("*/result.json"))
    directories = sorted(path for path in record_root.iterdir() if path.is_dir())
    source_counts: Counter[str] = Counter()
    plan_kind_counts: Counter[str] = Counter()
    fallback_counts: Counter[str] = Counter()
    fallback_reason_counts: Counter[str] = Counter()
    preexisting_not_applicable = []
    validated_request_count = 0

    for result_path in result_paths:
        try:
            result = _read_json(result_path, "preflight result")
            audits = _validate_all_saved_requests_with_fallback(
                result,
                max_characters=max_characters,
                max_token_like_units=max_token_like_units,
            )
        except ReplayPreparationError as exc:
            cause = exc.__cause__
            preexisting_not_applicable.append({
                "record_directory": result_path.parent.name,
                "error": str(exc),
                "cause": str(cause) if cause is not None else None,
            })
            continue
        for audit in audits:
            source = audit["source"]
            plan_kind = audit["plan_kind"]
            if not isinstance(source, str) or not isinstance(plan_kind, str):
                raise ReplayPreparationError("saved request audit has invalid enum fields")
            validated_request_count += 1
            source_counts[source] += 1
            plan_kind_counts[plan_kind] += 1
            if source == "raw_query_text_fallback":
                reason = audit["fallback_reason_code"]
                if not isinstance(reason, str) or not reason:
                    raise ReplayPreparationError(
                        "fallback audit must contain a typed reason code"
                    )
                fallback_counts[plan_kind] += 1
                fallback_reason_counts[reason] += 1

    fallback_count = sum(fallback_counts.values())
    return {
        "schema_version": "c17_canonical_rerank_execution_compatibility_preflight_v1",
        "mode": "READ_ONLY_ALL_SAVED_RQ_GRQ_FALLBACK_COMPATIBILITY_PREFLIGHT",
        "record_directory_count": len(directories),
        "result_file_count": len(result_paths),
        "missing_result_file_count": len(directories) - len(result_paths),
        "execution_compatible_run_count": (
            len(result_paths) - len(preexisting_not_applicable)
        ),
        "validated_request_count": validated_request_count,
        "canonical_or_raw_success_count": (
            validated_request_count - fallback_count
        ),
        "fallback_count": fallback_count,
        "source_counts": dict(sorted(source_counts.items())),
        "plan_kind_counts": dict(sorted(plan_kind_counts.items())),
        "fallback_counts_by_plan_kind": dict(sorted(fallback_counts.items())),
        "fallback_reason_counts": dict(sorted(fallback_reason_counts.items())),
        "preexisting_not_applicable_count": len(preexisting_not_applicable),
        "preexisting_not_applicable": preexisting_not_applicable,
        # The wrapper catches every typed canonicalization failure per request.
        # Any config, validator, or unexpected error still escapes this tool.
        "new_canonical_execution_failure_count": 0,
        "max_characters": max_characters,
        "max_token_like_units": max_token_like_units,
    }


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _write_output(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise ReplayPreparationError("refusing to overwrite output: %s" % path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--c02-root",
        type=Path,
        help="C02 targeted-resume output root containing records/ and batches/",
    )
    parser.add_argument("--result", type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--events", type=Path)
    parser.add_argument("--retrieval-stages", type=Path)
    parser.add_argument("--batch-manifest", type=Path)
    parser.add_argument("--task-receipt", type=Path)
    parser.add_argument(
        "--preflight-record-root",
        type=Path,
        help="read-only structural preflight only; does not perform qa150 binding",
    )
    parser.add_argument(
        "--execution-compatibility-preflight-record-root",
        type=Path,
        help=(
            "read-only all-RQ/GRQ fallback compatibility preflight only; "
            "does not perform qa150 binding or live retrieval"
        ),
    )
    parser.add_argument("--max-characters", type=_positive_int, default=512)
    parser.add_argument("--max-token-like-units", type=_positive_int, default=96)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if (
        args.preflight_record_root is not None
        and args.execution_compatibility_preflight_record_root is not None
    ):
        raise ReplayPreparationError("only one preflight mode may be selected")
    if (
        args.preflight_record_root is not None
        or args.execution_compatibility_preflight_record_root is not None
    ):
        if args.c02_root is not None or any(
            value is not None
            for value in (
                args.result,
                args.metadata,
                args.events,
                args.retrieval_stages,
                args.batch_manifest,
                args.task_receipt,
            )
        ):
            raise ReplayPreparationError("preflight mode cannot combine qa150 source paths")
        if args.execution_compatibility_preflight_record_root is not None:
            payload = preflight_saved_request_fallback_compatibility(
                args.execution_compatibility_preflight_record_root,
                max_characters=args.max_characters,
                max_token_like_units=args.max_token_like_units,
            )
        else:
            payload = preflight_initial_structured_transforms(
                args.preflight_record_root,
                max_characters=args.max_characters,
                max_token_like_units=args.max_token_like_units,
            )
    else:
        if args.c02_root is not None:
            if any(
                value is not None
                for value in (
                    args.result,
                    args.metadata,
                    args.events,
                    args.retrieval_stages,
                    args.batch_manifest,
                    args.task_receipt,
                )
            ):
                raise ReplayPreparationError(
                    "--c02-root cannot combine with explicit qa150 source paths"
                )
            paths = c02_paths_from_root(args.c02_root)
        else:
            explicit = {
                "result": args.result,
                "metadata": args.metadata,
                "events": args.events,
                "retrieval_stages": args.retrieval_stages,
                "batch_manifest": args.batch_manifest,
                "task_receipt": args.task_receipt,
            }
            if any(value is None for value in explicit.values()):
                raise ReplayPreparationError(
                    "provide --c02-root or all six explicit qa150 source paths"
                )
            paths = {key: Path(value) for key, value in explicit.items()}
        payload = prepare_c02_qa150(
            paths,
            max_characters=args.max_characters,
            max_token_like_units=args.max_token_like_units,
        )
    _write_output(args.output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
