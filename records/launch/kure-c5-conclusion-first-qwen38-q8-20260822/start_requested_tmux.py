#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import subprocess
from pathlib import Path

EXEC_ROOT = Path(__file__).resolve().parents[3]
AUDIT_ROOT = Path("/root/Legal Harness")
PYTHON = AUDIT_ROOT / ".venv/bin/python"
RUNNER = Path(__file__).resolve().parent / "run_kure_smoke_full226.py"
SESSION = "lh-kure-c5-smoke-full226-20260822"
LOG = AUDIT_ROOT / "records/tmux/kure-c5-smoke-full226-20260822.log"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume-after-smoke", action="store_true")
    args = parser.parse_args()
    inner = (
        "set -o pipefail; cd "
        + shlex.quote(str(EXEC_ROOT))
        + "; PYTHONPATH="
        + shlex.quote(str(EXEC_ROOT))
        + " "
        + shlex.quote(str(PYTHON))
        + " "
        + shlex.quote(str(RUNNER))
        + (" --resume-after-smoke" if args.resume_after_smoke else "")
        + " 2>&1 | tee -a "
        + shlex.quote(str(LOG))
    )
    command = ["tmux", "new-session", "-d", "-s", SESSION, "bash", "-lc", inner]
    if args.dry_run:
        print(shlex.join(command))
        return 0
    LOG.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
