#!/usr/bin/env python3
from __future__ import annotations
import argparse
import shlex
import subprocess
from pathlib import Path

EXEC_ROOT = Path("/root/Legal Harness/records/worktrees/kure-c5-conclusion-first-qwen38-q8-20260822-a74e76d")
PYTHON = Path("/root/Legal Harness/.venv/bin/python")
RUNNER = EXEC_ROOT / "records/launch/kure-c5-conclusion-first-qwen38-q8-20260822/run_stage.py"
LOG_ROOT = Path("/root/Legal Harness/records/tmux")
SESSIONS = {
    "all": ("lh-kure-c5-all-20260822", "kure-c5-all-20260822.log"),
    "smoke8": ("lh-kure-c5-smoke8-20260822", "kure-c5-smoke8-20260822.log"),
    "dev21": ("lh-kure-c5-dev21-20260822", "kure-c5-dev21-20260822.log"),
    "full226": ("lh-kure-c5-full226-20260822", "kure-c5-full226-20260822.log"),
}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=SESSIONS)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    session, log_name = SESSIONS[args.stage]
    inner = "; ".join([
        "set -o pipefail",
        "cd " + shlex.quote(str(EXEC_ROOT)),
        "PYTHONPATH=" + shlex.quote(str(EXEC_ROOT)) + " "
        + shlex.quote(str(PYTHON)) + " " + shlex.quote(str(RUNNER)) + " "
        + args.stage + " 2>&1 | tee " + shlex.quote(str(LOG_ROOT / log_name)),
    ])
    command = ["tmux", "new-session", "-d", "-s", session, "bash -lc " + shlex.quote(inner)]
    if args.dry_run:
        print(shlex.join(command))
        return 0
    LOG_ROOT.mkdir(parents=True, exist_ok=True)
    if subprocess.run(["tmux", "has-session", "-t", session], check=False).returncode == 0:
        raise SystemExit("tmux session already exists: " + session)
    subprocess.run(command, check=True)
    print("started tmux session:", session)
    print("log:", LOG_ROOT / log_name)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
