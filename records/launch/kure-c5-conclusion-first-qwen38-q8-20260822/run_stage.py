#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

EXEC_ROOT = Path(__file__).resolve().parents[3]
AUDIT_ROOT = Path("/root/Legal Harness")
PYTHON = AUDIT_ROOT / ".venv/bin/python"
EXPECTED_COMMIT = "a74e76d1c8fade04486b681974475d8c88f7f136"
LAUNCH_REL = Path("records/launch/kure-c5-conclusion-first-qwen38-q8-20260822")
STAGES = {
    "smoke8": {
        "manifest": "kure_c5_smoke8_20260822.json",
        "comparison": "bm25_reference_c5_smoke8_20260822.json",
        "prerequisite": None,
    },
    "dev21": {
        "manifest": "kure_c5_dev21_20260822.json",
        "comparison": "bm25_reference_c5_dev21_20260822.json",
        "prerequisite": "smoke8",
    },
    "full226": {
        "manifest": "kure_c5_full226_20260822.json",
        "comparison": "bm25_reference_c5_full226_20260822.json",
        "prerequisite": "dev21",
    },
}

def fail(message: str) -> None:
    raise SystemExit(message)

def run_checked(command, env):
    print("RUN", " ".join(map(str, command)), flush=True)
    return subprocess.run(command, cwd=EXEC_ROOT, env=env, check=False).returncode

def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def check_abstain_leakage(batch_dir: Path):
    leaks = []
    for line in (batch_dir / "summary.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("status") != "ABSTAIN":
            continue
        record = Path(row["record_directory"])
        result = load_json(record / "result.json")
        if result.get("answer") is not None or result.get("final_answer") is not None:
            leaks.append(row["question_id"])
    return leaks

def gate(stage: str, batch_dir: Path, evaluation_dir: Path, batch_status: int, evaluation_status: int):
    reasons = []
    if batch_status != 0:
        reasons.append(f"batch_exit={batch_status}")
    if evaluation_status != 0:
        reasons.append(f"evaluation_exit={evaluation_status}")
    aggregate = load_json(evaluation_dir / "aggregate.json") if (evaluation_dir / "aggregate.json").is_file() else {}
    failures = aggregate.get("answer_quality", {}).get("execution_failure_count")
    if failures != 0:
        reasons.append(f"execution_failure_count={failures}")
    leaks = check_abstain_leakage(batch_dir)
    if leaks:
        reasons.append("public_abstain_leakage=" + ",".join(leaks))
    citation = aggregate.get("citation_integrity", {})
    if citation.get("attempted", 0) and citation.get("pass_rate") != 1.0:
        reasons.append(f"citation_integrity_pass_rate={citation.get('pass_rate')}")
    for metric in ("first_stage_at_100", "rrf_at_100", "bge_at_10", "bge_at_20", "bge_at_30"):
        if aggregate.get("retrieval", {}).get(metric, {}).get("available") is not True:
            reasons.append(metric + "_unavailable")
    if stage == "dev21" and aggregate:
        provision = aggregate["provision"]
        checks = {
            "macro_recall": (provision["macro"]["recall"], 0.7381),
            "macro_f1": (provision["macro"]["f1"], 0.6149),
            "complete_evidence": (provision["complete_evidence"]["rate"], 0.6667),
        }
        for name, (actual, minimum) in checks.items():
            if actual + 1e-12 < minimum:
                reasons.append(f"{name}={actual:.6f}<baseline={minimum:.6f}")
    if stage == "full226" and aggregate:
        provision = aggregate["provision"]
        hop2 = aggregate["by_hop"]["2"]["provision"]
        checks = {
            "full_macro_recall": (provision["macro"]["recall"], 0.6969),
            "full_macro_f1_noninferiority": (provision["macro"]["f1"], 0.5844 - 0.02),
            "full_complete_evidence": (provision["complete_evidence"]["rate"], 0.6062),
            "hop2_macro_recall": (hop2["macro"]["recall"], 0.8071),
            "hop2_macro_f1_noninferiority": (hop2["macro"]["f1"], 0.6640 - 0.02),
            "hop2_complete_evidence": (hop2["complete_evidence"]["rate"], 0.6929),
        }
        for name, (actual, minimum) in checks.items():
            if actual + 1e-12 < minimum:
                reasons.append(f"{name}={actual:.6f}<gate={minimum:.6f}")
    payload = {
        "stage": stage,
        "status": "PASS" if not reasons else "FAIL",
        "source_commit": EXPECTED_COMMIT,
        "batch_directory": str(batch_dir),
        "evaluation_directory": str(evaluation_dir),
        "reasons": reasons,
        "lf_eval": "NOT_RUN_NO_FROZEN_SCORES_INPUT",
    }
    gate_path = AUDIT_ROOT / "records/gates" / f"kure-c5-{stage}-20260822.json"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
    return not reasons

def run_static_regression() -> bool:
    if not os.environ.get("TMUX"):
        fail("Experiments must run inside tmux; TMUX is not set.")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(EXEC_ROOT) + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    command = [str(PYTHON), "-m", "unittest", "discover", "-s", "tests", "-q"]
    status = run_checked(command, env)
    payload = {
        "stage": "static_regression",
        "status": "PASS" if status == 0 else "FAIL",
        "source_commit": EXPECTED_COMMIT,
        "committed_test_count": 118,
        "exit_code": status,
    }
    gate_path = AUDIT_ROOT / "records/gates/kure-c5-static-regression-20260822.json"
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
    return status == 0


def run_stage(stage: str) -> bool:
    if not os.environ.get("TMUX"):
        fail("Experiments must run inside tmux; TMUX is not set.")
    spec = STAGES[stage]
    prerequisite = spec["prerequisite"]
    if prerequisite:
        gate_path = AUDIT_ROOT / "records/gates" / f"kure-c5-{prerequisite}-20260822.json"
        if not gate_path.is_file() or load_json(gate_path).get("status") != "PASS":
            fail(f"{stage} blocked: prerequisite {prerequisite} gate has not passed")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(EXEC_ROOT) + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=EXEC_ROOT, text=True).strip()
    if head != EXPECTED_COMMIT:
        fail(f"source commit mismatch: {head}")
    preflight = [str(PYTHON), "-c", "from pathlib import Path; from runtime.source_snapshot import capture_clean_source_snapshot; capture_clean_source_snapshot(Path.cwd())"]
    if run_checked(preflight, env) != 0:
        fail("clean source preflight failed before model execution")
    batch_name = f"kure-c5-{stage}-20260822-a74e76d"
    main_record_root = AUDIT_ROOT / "records/runs" / batch_name
    main_batch_root = AUDIT_ROOT / "records/batches" / batch_name
    evaluation_dir = AUDIT_ROOT / "records/evaluations" / batch_name
    link_root = EXEC_ROOT / "records" / f"batch-output-{batch_name}"
    for target in (main_record_root, evaluation_dir):
        if target.exists():
            fail(f"refusing to overwrite existing artifact: {target}")
    if main_batch_root.exists() and any(main_batch_root.iterdir()):
        fail(f"refusing to reuse non-empty batch root: {main_batch_root}")
    main_batch_root.mkdir(parents=True, exist_ok=True)
    if not link_root.exists():
        link_root.symlink_to(main_batch_root, target_is_directory=True)
    manifest = EXEC_ROOT / LAUNCH_REL / spec["manifest"]
    comparison = EXEC_ROOT / LAUNCH_REL / spec["comparison"]
    batch_command = [
        str(PYTHON), "scripts/run_bm25_bge_pilot_batch.py",
        "--manifest", str(manifest),
        "--comparison-manifest", str(comparison),
        "--python", str(PYTHON),
        "--batch-name", batch_name,
        "--record-root", str(main_record_root),
        "--batch-log-root", str(link_root),
    ]
    batch_status = run_checked(batch_command, env)
    batch_dirs = sorted(path for path in main_batch_root.iterdir() if path.is_dir())
    if len(batch_dirs) != 1:
        fail(f"expected exactly one batch directory, found {len(batch_dirs)}")
    batch_dir = batch_dirs[0]
    evaluation_command = [
        str(PYTHON), "scripts/evaluate_dev_runs.py",
        "--batch-dir", str(batch_dir),
        "--output-dir", str(evaluation_dir),
        "--require-stage-provenance",
    ]
    evaluation_status = run_checked(evaluation_command, env)
    return gate(stage, batch_dir, evaluation_dir, batch_status, evaluation_status)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["smoke8", "dev21", "full226", "all"])
    args = parser.parse_args()
    sequence = [args.stage] if args.stage != "all" else ["smoke8", "dev21", "full226"]
    if sequence[0] == "smoke8" and not run_static_regression():
        return 1
    for stage in sequence:
        if not run_stage(stage):
            return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
