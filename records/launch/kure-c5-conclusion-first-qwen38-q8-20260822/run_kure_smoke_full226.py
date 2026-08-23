#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

EXEC_ROOT = Path(__file__).resolve().parents[3]
AUDIT_ROOT = Path("/root/Legal Harness")
PYTHON = AUDIT_ROOT / ".venv/bin/python"
EXPECTED_COMMIT = "a74e76d1c8fade04486b681974475d8c88f7f136"
LAUNCH = Path(__file__).resolve().parent
FULL_MANIFEST = LAUNCH / "kure_c5_full226_20260822.json"
FULL_REFERENCE = LAUNCH / "bm25_reference_c5_full226_20260822.json"
SMOKE_RUNNER = LAUNCH / "run_stage.py"
BATCH_NAME = "kure-c5-full226-20260822-a74e76d"
RECORD_ROOT = AUDIT_ROOT / "records/runs" / BATCH_NAME
BATCH_ROOT = AUDIT_ROOT / "records/batches" / BATCH_NAME
EVALUATION_ROOT = AUDIT_ROOT / "records/evaluations"
PROGRESS_ROOT = AUDIT_ROOT / "records/progress"
PROGRESS_JSONL = PROGRESS_ROOT / "kure-c5-full226-20260822.jsonl"
PROGRESS_LATEST = PROGRESS_ROOT / "kure-c5-full226-20260822-latest.json"
FINAL_GATE = AUDIT_ROOT / "records/gates/kure-c5-full226-20260822.json"
LINK_ROOT = EXEC_ROOT / "records" / ("batch-output-" + BATCH_NAME)
CHUNK_MANIFEST_ROOT = LAUNCH / "generated_full226_chunks"
CHECKPOINTS = ((1, 40), (41, 80), (81, 120), (121, 160), (161, 200), (201, 226))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fail(message: str) -> None:
    raise RuntimeError(message)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def emit(event: dict) -> None:
    event = {"recorded_at_utc": utc_now(), **event}
    PROGRESS_ROOT.mkdir(parents=True, exist_ok=True)
    with PROGRESS_JSONL.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        stream.flush()
    write_json(PROGRESS_LATEST, event)
    print("PROGRESS_EVENT " + json.dumps(event, ensure_ascii=False), flush=True)


def run(command, env) -> int:
    print("RUN " + " ".join(map(str, command)), flush=True)
    return subprocess.run(command, cwd=EXEC_ROOT, env=env, check=False).returncode


def filtered_manifest(source: dict, start: int, end: int, name: str) -> dict:
    result = deepcopy(source)
    result["name"] = name
    result["entries"] = [
        entry for entry in result["entries"]
        if start <= int(entry["ordinal"]) <= end
    ]
    result["selection"] = dict(result.get("selection", {}))
    result["selection"]["method"] = f"frozen full226 checkpoint chunk {start}-{end}"
    result["selection"]["entry_count"] = len(result["entries"])
    return result


def combined_manifest(source: dict, count: int) -> dict:
    result = deepcopy(source)
    result["name"] = f"{BATCH_NAME}-checkpoint-{count:03d}"
    result["entries"] = [
        entry for entry in result["entries"] if int(entry["ordinal"]) <= count
    ]
    result["selection"] = dict(result.get("selection", {}))
    result["selection"]["method"] = f"cumulative full226 checkpoint 1-{count}"
    result["selection"]["entry_count"] = len(result["entries"])
    return result


def read_rows(batch_dir: Path) -> list[dict]:
    path = batch_dir / "summary.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def public_abstain_leaks(rows: list[dict]) -> list[str]:
    leaks = []
    for row in rows:
        if row.get("status") != "ABSTAIN" or not row.get("record_directory"):
            continue
        result_path = Path(row["record_directory"]) / "result.json"
        if not result_path.is_file():
            leaks.append(str(row.get("question_id")))
            continue
        result = load_json(result_path)
        if result.get("answer") is not None or result.get("final_answer") is not None:
            leaks.append(str(row.get("question_id")))
    return leaks


def metric_available(aggregate: dict, name: str) -> bool:
    return aggregate.get("retrieval", {}).get(name, {}).get("available") is True


def make_checkpoint(
    count: int,
    rows: list[dict],
    full_manifest: dict,
    comparison_metadata: dict,
    chunk_dirs: list[Path],
    full_started_monotonic: float,
    env: dict,
) -> dict:
    checkpoint_dir = BATCH_ROOT / f"combined-checkpoint-{count:03d}"
    if checkpoint_dir.exists():
        fail(f"refusing to overwrite checkpoint: {checkpoint_dir}")
    checkpoint_dir.mkdir(parents=True)
    write_json(checkpoint_dir / "manifest.json", combined_manifest(full_manifest, count))
    write_rows(checkpoint_dir / "summary.jsonl", rows)
    write_json(
        checkpoint_dir / "metadata.json",
        {
            "batch_id": f"{BATCH_NAME}-combined-checkpoint-{count:03d}",
            "started_at_utc": rows[0]["started_at_utc"],
            "completed_at_utc": rows[-1]["completed_at_utc"],
            "entry_count": count,
            "source_commit": EXPECTED_COMMIT,
            "retriever_comparison": comparison_metadata,
            "comparison_validity": comparison_metadata,
            "source_batch_directories": [str(path) for path in chunk_dirs],
            "record_root": str(RECORD_ROOT),
        },
    )
    evaluation_dir = EVALUATION_ROOT / f"{BATCH_NAME}-checkpoint-{count:03d}"
    if evaluation_dir.exists():
        fail(f"refusing to overwrite evaluation: {evaluation_dir}")
    eval_started = time.monotonic()
    evaluation_exit = run(
        [
            str(PYTHON),
            "scripts/evaluate_dev_runs.py",
            "--batch-dir", str(checkpoint_dir),
            "--output-dir", str(evaluation_dir),
            "--require-stage-provenance",
        ],
        env,
    )
    evaluation_seconds = time.monotonic() - eval_started
    aggregate_path = evaluation_dir / "aggregate.json"
    aggregate = load_json(aggregate_path) if aggregate_path.is_file() else {}
    abnormal = [
        str(row.get("question_id"))
        for row in rows
        if row.get("status") not in {"ANSWER", "ABSTAIN"}
    ]
    unexpected_exit = [
        str(row.get("question_id"))
        for row in rows
        if (
            row.get("status") == "ANSWER" and row.get("exit_code") not in {0, None}
        ) or (
            row.get("status") == "ABSTAIN" and row.get("exit_code") not in {0, 1, None}
        )
    ]
    recorded_errors = {
        str(row.get("question_id")): row.get("errors")
        for row in rows if row.get("errors")
    }
    leaks = public_abstain_leaks(rows)
    citation = aggregate.get("citation_integrity", {})
    provenance_missing = [
        metric for metric in
        ("first_stage_at_100", "rrf_at_100", "bge_at_10", "bge_at_20", "bge_at_30")
        if not metric_available(aggregate, metric)
    ]
    latencies = [
        float(row["end_to_end_latency_ms"]) / 1000.0
        for row in rows
        if isinstance(row.get("end_to_end_latency_ms"), (int, float))
    ]
    mean_seconds = statistics.mean(latencies) if latencies else None
    median_seconds = statistics.median(latencies) if latencies else None
    remaining_seconds = mean_seconds * (226 - count) if mean_seconds is not None else None
    estimated_completion = (
        datetime.now(timezone.utc) + timedelta(seconds=remaining_seconds)
        if remaining_seconds is not None else None
    )
    provision = aggregate.get("provision", {})
    hop2_provision = aggregate.get("by_hop", {}).get("2", {}).get("provision", {})
    validation_errors = []
    if evaluation_exit != 0:
        validation_errors.append(f"evaluation_exit={evaluation_exit}")
    if abnormal:
        validation_errors.append(f"abnormal_outcomes={len(abnormal)}")
    if unexpected_exit:
        validation_errors.append(f"unexpected_exit={len(unexpected_exit)}")
    if recorded_errors:
        validation_errors.append(f"recorded_errors={len(recorded_errors)}")
    if leaks:
        validation_errors.append(f"public_abstain_leakage={len(leaks)}")
    if citation.get("attempted", 0) and citation.get("pass_rate") != 1.0:
        validation_errors.append(f"citation_integrity={citation.get('pass_rate')}")
    if provenance_missing:
        validation_errors.append("provenance_missing=" + ",".join(provenance_missing))
    event = {
        "event": "CHECKPOINT" if count < 226 else "FULL226_COMPLETED",
        "completed_questions": count,
        "total_questions": 226,
        "checkpoint_status": "PASS" if not validation_errors else "ERRORS_FOUND",
        "validation_errors": validation_errors,
        "execution_failure_count": aggregate.get("answer_quality", {}).get(
            "execution_failure_count", len(abnormal)
        ),
        "abnormal_question_ids": abnormal,
        "unexpected_exit_question_ids": unexpected_exit,
        "recorded_errors": recorded_errors,
        "public_abstain_leak_question_ids": leaks,
        "citation_integrity": citation,
        "stage_provenance_complete": not provenance_missing,
        "stage_provenance_missing": provenance_missing,
        "metrics": {
            "macro_recall": provision.get("macro", {}).get("recall"),
            "macro_f1": provision.get("macro", {}).get("f1"),
            "complete_evidence_rate": provision.get("complete_evidence", {}).get("rate"),
            "hop2_macro_recall": hop2_provision.get("macro", {}).get("recall"),
            "hop2_macro_f1": hop2_provision.get("macro", {}).get("f1"),
            "hop2_complete_evidence_rate": hop2_provision.get("complete_evidence", {}).get("rate"),
        },
        "mean_question_seconds": mean_seconds,
        "median_question_seconds": median_seconds,
        "elapsed_full_seconds": time.monotonic() - full_started_monotonic,
        "evaluation_seconds": evaluation_seconds,
        "estimated_remaining_seconds": remaining_seconds,
        "estimated_completion_utc": estimated_completion.isoformat() if estimated_completion else None,
        "batch_directory": str(checkpoint_dir),
        "evaluation_directory": str(evaluation_dir),
    }
    emit(event)
    return event


def final_gate(event: dict) -> dict:
    reasons = list(event["validation_errors"])
    metrics = event["metrics"]
    checks = {
        "macro_recall": (metrics.get("macro_recall"), 0.6969),
        "macro_f1_noninferiority": (metrics.get("macro_f1"), 0.5844 - 0.02),
        "complete_evidence": (metrics.get("complete_evidence_rate"), 0.6062),
        "hop2_macro_recall": (metrics.get("hop2_macro_recall"), 0.8071),
        "hop2_macro_f1_noninferiority": (metrics.get("hop2_macro_f1"), 0.6640 - 0.02),
        "hop2_complete_evidence": (metrics.get("hop2_complete_evidence_rate"), 0.6929),
    }
    for name, (actual, minimum) in checks.items():
        if actual is None or actual + 1e-12 < minimum:
            reasons.append(f"{name}={actual}<gate={minimum}")
    gate = {
        "stage": "full226",
        "status": "PASS" if not reasons else "FAIL",
        "source_commit": EXPECTED_COMMIT,
        "retriever": "kure",
        "dev21_skipped": True,
        "bm25_executed": False,
        "completed_questions": event["completed_questions"],
        "reasons": reasons,
        "metrics": metrics,
        "final_checkpoint": event,
        "lf_eval": "NOT_RUN_NO_FROZEN_SCORES_INPUT",
    }
    write_json(FINAL_GATE, gate)
    emit({"event": "FINAL_GATE", **gate})
    return gate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume-after-smoke", action="store_true")
    args = parser.parse_args()
    if not os.environ.get("TMUX"):
        raise SystemExit("Experiments must run inside tmux; TMUX is not set.")
    progress_exists = PROGRESS_JSONL.exists() or PROGRESS_LATEST.exists()
    if not args.resume_after_smoke and progress_exists:
        raise SystemExit("refusing to overwrite existing progress record")
    if args.resume_after_smoke and not PROGRESS_JSONL.exists():
        raise SystemExit("cannot resume without the existing progress JSONL")
    orchestration_started = time.monotonic()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(EXEC_ROOT) + (
        ":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    from runtime.comparison_guard import validate_retriever_comparison
    from runtime.source_snapshot import capture_clean_source_snapshot

    snapshot = capture_clean_source_snapshot(EXEC_ROOT)
    if snapshot.git_commit != EXPECTED_COMMIT:
        fail(f"source commit mismatch: {snapshot.git_commit}")
    primary = load_json(FULL_MANIFEST)
    reference = load_json(FULL_REFERENCE)
    comparison = validate_retriever_comparison(
        primary, reference, FULL_MANIFEST, FULL_REFERENCE
    )
    smoke_gate_path = AUDIT_ROOT / "records/gates/kure-c5-smoke8-20260822.json"
    if args.resume_after_smoke:
        smoke_gate = load_json(smoke_gate_path) if smoke_gate_path.is_file() else {}
        if smoke_gate.get("status") != "PASS":
            raise SystemExit("cannot resume: smoke8 gate has not passed")
        emit(
            {
                "event": "RUN_RESUMED_AFTER_SMOKE",
                "source_snapshot": snapshot.to_dict(),
                "smoke_gate": smoke_gate,
                "normal_abstain_exit_codes": [0, 1],
            }
        )
    else:
        emit(
            {
                "event": "RUN_STARTED",
                "source_snapshot": snapshot.to_dict(),
                "plan": ["smoke8", "full226"],
                "dev21_skipped": True,
                "bm25_executed": False,
                "bm25_reference_use": "configuration_validation_only",
                "comparison_validation": comparison,
                "initial_estimated_hours": {"lower": 22, "upper": 26},
            }
        )
        smoke_started = time.monotonic()
        smoke_exit = run([str(PYTHON), str(SMOKE_RUNNER), "smoke8"], env)
        smoke_gate = load_json(smoke_gate_path) if smoke_gate_path.is_file() else {}
        emit(
            {
                "event": "SMOKE8_COMPLETED",
                "exit_code": smoke_exit,
                "elapsed_seconds": time.monotonic() - smoke_started,
                "gate": smoke_gate,
            }
        )
        if smoke_exit != 0 or smoke_gate.get("status") != "PASS":
            emit({"event": "RUN_ABORTED", "reason": "smoke8 gate did not pass"})
            return 1

    for target in (RECORD_ROOT, BATCH_ROOT):
        if target.exists():
            fail(f"refusing to overwrite existing artifact: {target}")
    RECORD_ROOT.mkdir(parents=True)
    BATCH_ROOT.mkdir(parents=True)
    if LINK_ROOT.exists() or LINK_ROOT.is_symlink():
        fail(f"refusing to reuse batch link: {LINK_ROOT}")
    LINK_ROOT.symlink_to(BATCH_ROOT, target_is_directory=True)
    CHUNK_MANIFEST_ROOT.mkdir(parents=True, exist_ok=False)

    all_rows: list[dict] = []
    chunk_dirs: list[Path] = []
    full_started = time.monotonic()
    final_event = None
    for start, end in CHECKPOINTS:
        capture_clean_source_snapshot(EXEC_ROOT)
        primary_chunk = filtered_manifest(
            primary, start, end, f"{BATCH_NAME}-chunk-{start:03d}-{end:03d}"
        )
        reference_chunk = filtered_manifest(
            reference, start, end, f"bm25-reference-c5-chunk-{start:03d}-{end:03d}"
        )
        primary_path = CHUNK_MANIFEST_ROOT / f"kure_{start:03d}_{end:03d}.json"
        reference_path = CHUNK_MANIFEST_ROOT / f"bm25_reference_{start:03d}_{end:03d}.json"
        primary_chunk["selection"]["reference_configuration_manifest"] = str(
            reference_path.relative_to(EXEC_ROOT)
        )
        write_json(primary_path, primary_chunk)
        write_json(reference_path, reference_chunk)
        validate_retriever_comparison(
            primary_chunk, reference_chunk, primary_path, reference_path
        )
        before = {path for path in BATCH_ROOT.iterdir() if path.is_dir()}
        chunk_exit = run(
            [
                str(PYTHON),
                "scripts/run_bm25_bge_pilot_batch.py",
                "--manifest", str(primary_path),
                "--comparison-manifest", str(reference_path),
                "--python", str(PYTHON),
                "--batch-name", f"{BATCH_NAME}-chunk-{start:03d}-{end:03d}",
                "--record-root", str(RECORD_ROOT),
                "--batch-log-root", str(LINK_ROOT),
            ],
            env,
        )
        after = {path for path in BATCH_ROOT.iterdir() if path.is_dir()}
        created = sorted(after - before)
        if len(created) != 1:
            fail(f"expected one chunk batch directory, found {len(created)}")
        chunk_dir = created[0]
        chunk_rows = read_rows(chunk_dir)
        expected = end - start + 1
        if len(chunk_rows) != expected:
            fail(f"chunk {start}-{end} produced {len(chunk_rows)} of {expected} rows")
        if [int(row["ordinal"]) for row in chunk_rows] != list(range(start, end + 1)):
            fail(f"chunk {start}-{end} ordinal mismatch")
        chunk_dirs.append(chunk_dir)
        all_rows.extend(chunk_rows)
        emit(
            {
                "event": "CHUNK_EXECUTION_COMPLETED",
                "range": [start, end],
                "chunk_exit_code": chunk_exit,
                "cumulative_questions": len(all_rows),
                "chunk_batch_directory": str(chunk_dir),
            }
        )
        final_event = make_checkpoint(
            len(all_rows),
            all_rows,
            primary,
            comparison,
            chunk_dirs,
            full_started,
            env,
        )

    if final_event is None or len(all_rows) != 226:
        fail("full226 did not produce exactly 226 summary rows")
    gate = final_gate(final_event)
    emit(
        {
            "event": "RUN_COMPLETED",
            "completed_questions": 226,
            "smoke_questions": 8,
            "full_elapsed_seconds": time.monotonic() - full_started,
            "orchestration_process_elapsed_seconds": time.monotonic() - orchestration_started,
            "final_gate_status": gate["status"],
            "progress_file": str(PROGRESS_JSONL),
        }
    )
    return 0 if gate["status"] == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaseException as exc:
        try:
            if not isinstance(exc, SystemExit):
                emit(
                    {
                        "event": "RUN_ABORTED",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
        finally:
            raise
