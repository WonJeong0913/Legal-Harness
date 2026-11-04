#!/usr/bin/env python3
"""Materialize a contiguous evaluator-compatible checkpoint from immutable batches."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTCOME_STATUSES = {"ANSWER", "ABSTAIN", "EXECUTION_FAILURE"}
CONFIG_IDENTITY_FIELDS = ("condition", "retriever", "model", "seed")
SOURCE_SNAPSHOT_FIELDS = ("git_commit", "git_tree", "source_manifest_sha256")


class CheckpointMaterializationError(RuntimeError):
    """An input batch cannot safely be included in a checkpoint."""


@dataclass(frozen=True)
class SourceBatch:
    directory: Path
    manifest: Dict[str, Any]
    metadata: Dict[str, Any]
    source_dataset: Dict[str, Any]
    configuration: Dict[str, Any]
    source_snapshot: Dict[str, Any]
    entries_by_ordinal: Dict[int, Dict[str, Any]]
    run_ids_by_ordinal: Dict[int, str]
    rows: Tuple[Dict[str, Any], ...]
    ordinal_start: int
    ordinal_end: int
    manifest_sha256: str
    metadata_sha256: str
    summary_sha256: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-batch-dir",
        type=Path,
        action="append",
        required=True,
        help="immutable completed chunk batch; repeat in any order",
    )
    parser.add_argument("--output-batch-dir", type=Path, required=True)
    parser.add_argument("--name", help="optional materialized manifest name")
    parser.add_argument(
        "--through-ordinal",
        type=int,
        help="fail-closed cutoff; output must contain every ordinal from 1 through N",
    )
    return parser.parse_args()


def _resolve_input_path(path: Path) -> Path:
    candidate = path if path.is_absolute() else PROJECT_ROOT / path
    return candidate.resolve()


def _resolve_output_path(path: Path) -> Path:
    candidate = path if path.is_absolute() else PROJECT_ROOT / path
    if os.path.lexists(str(candidate)):
        raise CheckpointMaterializationError(
            "refusing to overwrite existing output batch: %s" % candidate
        )
    resolved = candidate.resolve()
    if os.path.lexists(str(resolved)):
        raise CheckpointMaterializationError(
            "refusing to overwrite existing output batch: %s" % resolved
        )
    return resolved


def _sha256_bytes(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> Tuple[Dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CheckpointMaterializationError("invalid JSON file: %s" % path) from exc
    if not isinstance(payload, dict):
        raise CheckpointMaterializationError("JSON root must be an object: %s" % path)
    return dict(payload), _sha256_bytes(raw)


def _read_jsonl(path: Path) -> Tuple[List[Dict[str, Any]], str]:
    try:
        raw = path.read_bytes()
        lines = raw.decode("utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise CheckpointMaterializationError("cannot read JSONL file: %s" % path) from exc
    rows: List[Dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CheckpointMaterializationError(
                "invalid JSONL row: %s:%d" % (path, line_number)
            ) from exc
        if not isinstance(row, dict):
            raise CheckpointMaterializationError(
                "JSONL row must be an object: %s:%d" % (path, line_number)
            )
        rows.append(dict(row))
    return rows, _sha256_bytes(raw)


def _require_integer(value: Any, label: str, minimum: Optional[int] = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CheckpointMaterializationError("%s must be an integer" % label)
    if minimum is not None and value < minimum:
        raise CheckpointMaterializationError("%s must be at least %d" % (label, minimum))
    return value


def _require_nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CheckpointMaterializationError("%s must be a non-empty string" % label)
    return value


def _require_mapping(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CheckpointMaterializationError("%s must be an object" % label)
    return dict(value)


def _validate_source_dataset(value: Any, label: str) -> Dict[str, Any]:
    source = _require_mapping(value, label)
    _require_nonempty_string(source.get("path"), label + ".path")
    _require_nonempty_string(source.get("sha256"), label + ".sha256")
    return source


def _validate_configuration(value: Any, label: str) -> Dict[str, Any]:
    configuration = _require_mapping(value, label)
    for field in CONFIG_IDENTITY_FIELDS:
        if field == "seed":
            _require_integer(configuration.get(field), label + ".seed")
        else:
            _require_nonempty_string(configuration.get(field), label + "." + field)
    return configuration


def _validate_source_snapshot(value: Any, label: str) -> Dict[str, Any]:
    snapshot = _require_mapping(value, label)
    for field in SOURCE_SNAPSHOT_FIELDS:
        _require_nonempty_string(snapshot.get(field), label + "." + field)
    return snapshot


def _manifest_entries(manifest: Mapping[str, Any], label: str) -> Dict[int, Dict[str, Any]]:
    raw_entries = manifest.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise CheckpointMaterializationError("%s.entries must be a non-empty array" % label)
    by_ordinal: Dict[int, Dict[str, Any]] = {}
    question_ids = set()
    for index, raw_entry in enumerate(raw_entries, start=1):
        entry = _require_mapping(raw_entry, "%s.entries[%d]" % (label, index))
        ordinal = _require_integer(entry.get("ordinal"), "%s.entries[%d].ordinal" % (label, index), 1)
        question_id = _require_nonempty_string(
            entry.get("question_id"), "%s.entries[%d].question_id" % (label, index)
        )
        _require_integer(entry.get("n_hops"), "%s.entries[%d].n_hops" % (label, index), 1)
        if ordinal in by_ordinal or question_id in question_ids:
            raise CheckpointMaterializationError(
                "%s manifest has duplicate ordinal or question_id" % label
            )
        by_ordinal[ordinal] = entry
        question_ids.add(question_id)
    selection = manifest.get("selection")
    if isinstance(selection, Mapping) and selection.get("entry_count") is not None:
        if _require_integer(selection["entry_count"], label + ".selection.entry_count", 1) != len(by_ordinal):
            raise CheckpointMaterializationError(
                "%s selection.entry_count does not match manifest entries" % label
            )
    return by_ordinal


def _rebase_legacy_record_directory(raw_path: Path) -> Optional[Path]:
    """Match the evaluator's safe fallback for moved records/runs directories."""
    if not raw_path.is_absolute():
        return None
    parts = raw_path.parts
    for index in range(len(parts) - 1):
        if parts[index : index + 2] != ("records", "runs"):
            continue
        suffix = parts[index + 2 :]
        if len(suffix) < 2 or any(part in {"", ".", ".."} for part in suffix):
            return None
        return PROJECT_ROOT.joinpath("records", "runs", *suffix)
    return None


def _resolve_record_for_validation(batch_directory: Path, row: Mapping[str, Any]) -> Path:
    """Resolve a record exactly through the evaluator's absolute-path candidates."""
    raw_directory = _require_nonempty_string(
        row.get("record_directory"), "summary.record_directory"
    )
    raw_path = Path(raw_directory)
    if not raw_path.is_absolute():
        raise CheckpointMaterializationError(
            "summary.record_directory must be absolute so the evaluator reads it unchanged"
        )
    candidates = [raw_path]
    rebased_path = _rebase_legacy_record_directory(raw_path)
    if rebased_path is not None:
        candidates.append(rebased_path)
    candidates.extend(
        [
            PROJECT_ROOT / "records/runs" / raw_path.name,
            batch_directory.parent.parent / "runs" / raw_path.name,
        ]
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    raise CheckpointMaterializationError(
        "cannot resolve evaluator record directory for %s"
        % row.get("question_id", "unknown")
    )


def _validate_record(
    row: Mapping[str, Any],
    configuration: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    batch_directory: Path,
    label: str,
) -> str:
    record_directory = _resolve_record_for_validation(batch_directory, row)
    metadata, _ = _read_json(record_directory / "metadata.json")
    result, _ = _read_json(record_directory / "result.json")
    question_id = _require_nonempty_string(row.get("question_id"), label + ".question_id")
    if metadata.get("question_id") != question_id:
        raise CheckpointMaterializationError("record metadata question mismatch for %s" % question_id)
    run_id = _require_nonempty_string(result.get("run_id"), label + ".result.run_id")
    if metadata.get("run_id") != run_id:
        raise CheckpointMaterializationError("record metadata/result run_id mismatch for %s" % question_id)
    status = row.get("status")
    if status not in OUTCOME_STATUSES or result.get("status") != status:
        raise CheckpointMaterializationError("summary/result status mismatch for %s" % question_id)
    record_configuration = _validate_configuration(
        metadata.get("configuration"), label + ".record.configuration"
    )
    for field in CONFIG_IDENTITY_FIELDS:
        if record_configuration.get(field) != configuration.get(field):
            raise CheckpointMaterializationError(
                "record configuration %s mismatch for %s" % (field, question_id)
            )
    if _validate_source_snapshot(metadata.get("source_snapshot"), label + ".record.source_snapshot") != dict(source_snapshot):
        raise CheckpointMaterializationError("record source snapshot mismatch for %s" % question_id)
    return run_id


def _load_source_batch(directory: Path) -> SourceBatch:
    if not directory.is_dir():
        raise CheckpointMaterializationError("source batch directory is missing: %s" % directory)
    manifest_path = directory / "manifest.json"
    metadata_path = directory / "metadata.json"
    summary_path = directory / "summary.jsonl"
    manifest, manifest_sha256 = _read_json(manifest_path)
    metadata, metadata_sha256 = _read_json(metadata_path)
    rows, summary_sha256 = _read_jsonl(summary_path)
    label = "source batch %s" % directory
    source_dataset = _validate_source_dataset(manifest.get("source_dataset"), label + ".manifest.source_dataset")
    configuration = _validate_configuration(manifest.get("frozen_configuration"), label + ".manifest.frozen_configuration")
    if _validate_configuration(metadata.get("configuration"), label + ".metadata.configuration") != configuration:
        raise CheckpointMaterializationError("%s metadata configuration does not match manifest" % label)
    source_snapshot = _validate_source_snapshot(metadata.get("source_snapshot"), label + ".metadata.source_snapshot")
    if not metadata.get("completed_at_utc"):
        raise CheckpointMaterializationError("%s is not complete" % label)
    declared_batch_manifest_sha256 = metadata.get("batch_manifest_sha256")
    if declared_batch_manifest_sha256 is not None and declared_batch_manifest_sha256 != manifest_sha256:
        raise CheckpointMaterializationError("%s batch manifest SHA-256 mismatch" % label)
    entry_count = _require_integer(metadata.get("entry_count"), label + ".metadata.entry_count", 1)
    if len(rows) != entry_count:
        raise CheckpointMaterializationError("%s summary row count does not match metadata" % label)
    entries_by_ordinal = _manifest_entries(manifest, label + ".manifest")
    for field in ("start_ordinal", "end_ordinal"):
        if metadata.get(field) is not None:
            _require_integer(metadata[field], label + ".metadata." + field, 1)
    seen_ordinals = set()
    seen_questions = set()
    checked_rows: List[Dict[str, Any]] = []
    run_ids_by_ordinal: Dict[int, str] = {}
    for index, row in enumerate(rows, start=1):
        row_label = "%s.summary[%d]" % (label, index)
        ordinal = _require_integer(row.get("ordinal"), row_label + ".ordinal", 1)
        entry = entries_by_ordinal.get(ordinal)
        if entry is None:
            raise CheckpointMaterializationError("summary ordinal is absent from manifest: %d" % ordinal)
        question_id = _require_nonempty_string(row.get("question_id"), row_label + ".question_id")
        if question_id != entry["question_id"]:
            raise CheckpointMaterializationError("summary/manifest question mismatch at ordinal %d" % ordinal)
        if _require_integer(row.get("n_hops"), row_label + ".n_hops", 1) != entry["n_hops"]:
            raise CheckpointMaterializationError("summary/manifest hop mismatch at ordinal %d" % ordinal)
        if ordinal in seen_ordinals or question_id in seen_questions:
            raise CheckpointMaterializationError("%s summary has duplicate ordinal or question_id" % label)
        run_ids_by_ordinal[ordinal] = _validate_record(
            row, configuration, source_snapshot, directory, row_label
        )
        seen_ordinals.add(ordinal)
        seen_questions.add(question_id)
        checked_rows.append(row)
    ordinals = sorted(seen_ordinals)
    actual_start, actual_end = ordinals[0], ordinals[-1]
    if ordinals != list(range(actual_start, actual_end + 1)):
        raise CheckpointMaterializationError("%s summary ordinals are not contiguous" % label)
    return SourceBatch(
        directory=directory,
        manifest=manifest,
        metadata=metadata,
        source_dataset=source_dataset,
        configuration=configuration,
        source_snapshot=source_snapshot,
        entries_by_ordinal=entries_by_ordinal,
        run_ids_by_ordinal=run_ids_by_ordinal,
        rows=tuple(checked_rows),
        ordinal_start=actual_start,
        ordinal_end=actual_end,
        manifest_sha256=manifest_sha256,
        metadata_sha256=metadata_sha256,
        summary_sha256=summary_sha256,
    )


def _assert_compatible(reference: SourceBatch, candidate: SourceBatch) -> None:
    if candidate.source_dataset != reference.source_dataset:
        raise CheckpointMaterializationError("source_dataset mismatch across source batches")
    if candidate.source_snapshot != reference.source_snapshot:
        raise CheckpointMaterializationError("source_snapshot mismatch across source batches")
    for field in CONFIG_IDENTITY_FIELDS:
        if candidate.configuration.get(field) != reference.configuration.get(field):
            raise CheckpointMaterializationError(
                "%s mismatch across source batches" % field
            )
    if candidate.configuration != reference.configuration:
        raise CheckpointMaterializationError("frozen_configuration mismatch across source batches")


def _assert_source_files_unchanged(sources: Sequence[SourceBatch]) -> None:
    for source in sources:
        expected = (
            (source.directory / "manifest.json", source.manifest_sha256),
            (source.directory / "metadata.json", source.metadata_sha256),
            (source.directory / "summary.jsonl", source.summary_sha256),
        )
        for path, expected_sha256 in expected:
            if _sha256(path) != expected_sha256:
                raise CheckpointMaterializationError(
                    "source batch changed while materializing: %s" % path
                )


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def materialize_cumulative_batch(
    source_batch_directories: Sequence[Path],
    output_batch_directory: Path,
    name: Optional[str] = None,
    through_ordinal: Optional[int] = None,
) -> Dict[str, Any]:
    if not source_batch_directories:
        raise CheckpointMaterializationError("at least one source batch directory is required")
    if through_ordinal is not None:
        through_ordinal = _require_integer(through_ordinal, "through_ordinal", 1)
    output_directory = _resolve_output_path(output_batch_directory)
    sources = [_load_source_batch(_resolve_input_path(path)) for path in source_batch_directories]
    reference = sources[0]
    for source in sources[1:]:
        _assert_compatible(reference, source)
    sources = sorted(sources, key=lambda source: (source.ordinal_start, source.ordinal_end, str(source.directory)))
    entries_by_ordinal: Dict[int, Dict[str, Any]] = {}
    rows_by_ordinal: Dict[int, Dict[str, Any]] = {}
    question_ids = set()
    run_ids = set()
    for source in sources:
        for row in source.rows:
            ordinal = int(row["ordinal"])
            question_id = str(row["question_id"])
            run_id = source.run_ids_by_ordinal[ordinal]
            if ordinal in entries_by_ordinal or question_id in question_ids or run_id in run_ids:
                raise CheckpointMaterializationError(
                    "duplicate ordinal, question_id, or run_id across source batches"
                )
            question_ids.add(question_id)
            run_ids.add(run_id)
            if through_ordinal is not None and ordinal > through_ordinal:
                continue
            entries_by_ordinal[ordinal] = dict(source.entries_by_ordinal[ordinal])
            rows_by_ordinal[ordinal] = dict(row)
    ordinals = sorted(entries_by_ordinal)
    if not ordinals:
        raise CheckpointMaterializationError("no source rows fall within the requested cutoff")
    if through_ordinal is not None:
        if ordinals != list(range(1, through_ordinal + 1)):
            raise CheckpointMaterializationError(
                "cutoff output must contain every ordinal from 1 through %d" % through_ordinal
            )
    elif ordinals != list(range(ordinals[0], ordinals[-1] + 1)):
        raise CheckpointMaterializationError("cumulative source ordinals are not contiguous")
    _assert_source_files_unchanged(sources)
    if os.path.lexists(str(output_directory)):
        raise CheckpointMaterializationError(
            "refusing to overwrite existing output batch: %s" % output_directory
        )
    output_directory.mkdir(parents=True, exist_ok=False)
    output_entries = [entries_by_ordinal[ordinal] for ordinal in ordinals]
    source_selection = reference.manifest.get("selection")
    selection = dict(source_selection) if isinstance(source_selection, Mapping) else {}
    selection.update(
        {
            "method": "contiguous cumulative checkpoint materialized from immutable chunk batches",
            "entry_count": len(output_entries),
            "ordinal_start": ordinals[0],
            "ordinal_end": ordinals[-1],
        }
    )
    output_manifest = dict(reference.manifest)
    output_manifest["name"] = name or "%s-checkpoint-%03d-%03d" % (
        reference.manifest.get("name", "batch"), ordinals[0], ordinals[-1]
    )
    output_manifest["selection"] = selection
    output_manifest["entries"] = output_entries
    manifest_path = output_directory / "manifest.json"
    summary_path = output_directory / "summary.jsonl"
    _write_json(manifest_path, output_manifest)
    with summary_path.open("w", encoding="utf-8") as handle:
        for ordinal in ordinals:
            handle.write(json.dumps(rows_by_ordinal[ordinal], ensure_ascii=False) + "\n")
    output_metadata: Dict[str, Any] = {
        "materialization_schema_version": "1.0",
        "batch_id": output_directory.name,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "entry_count": len(output_entries),
        "ordinal_start": ordinals[0],
        "ordinal_end": ordinals[-1],
        "source_dataset": reference.source_dataset,
        "configuration": reference.configuration,
        "source_snapshot": reference.source_snapshot,
        "condition": reference.configuration["condition"],
        "retriever": reference.configuration["retriever"],
        "model": reference.configuration["model"],
        "seed": reference.configuration["seed"],
        "has_execution_failure": any(
            row.get("status") == "EXECUTION_FAILURE" for row in rows_by_ordinal.values()
        ),
        "materialized_manifest_sha256": _sha256(manifest_path),
        "materialized_summary_sha256": _sha256(summary_path),
        "source_batches": [
            {
                "batch_directory": str(source.directory),
                "batch_id": source.metadata.get("batch_id"),
                "ordinal_start": source.ordinal_start,
                "ordinal_end": source.ordinal_end,
                "metadata_start_ordinal": source.metadata.get("start_ordinal"),
                "metadata_end_ordinal": source.metadata.get("end_ordinal"),
                "entry_count": len(source.rows),
                "manifest_sha256": source.manifest_sha256,
                "metadata_sha256": source.metadata_sha256,
                "summary_sha256": source.summary_sha256,
            }
            for source in sources
        ],
    }
    _write_json(output_directory / "metadata.json", output_metadata)
    return {
        "output_batch_directory": str(output_directory),
        "entry_count": len(output_entries),
        "ordinal_start": ordinals[0],
        "ordinal_end": ordinals[-1],
    }


def main() -> int:
    args = parse_args()
    result = materialize_cumulative_batch(
        args.source_batch_dir,
        args.output_batch_dir,
        args.name,
        args.through_ordinal,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CheckpointMaterializationError as exc:
        print("checkpoint materialization error: %s" % exc)
        raise SystemExit(2)
