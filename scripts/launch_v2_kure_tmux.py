#!/usr/bin/env python3
"""Detach an already-prepared V2 KURE run in a unique tmux session.

No action is taken at import time or with ``--dry-run``. The launcher does
not start an endpoint; it only invokes the immutable offline orchestration.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shlex
import subprocess
import sys
from typing import List


class LaunchError(RuntimeError):
    pass


def session_name(output_root: Path, mode: str) -> str:
    safe = "".join(char if char.isalnum() else "-" for char in output_root.name).strip("-")
    return "lh-v2-kure-%s-%s" % (mode, safe or "run")


def log_path(output_root: Path, mode: str) -> Path:
    return output_root.parent / "tmux" / (session_name(output_root, mode) + ".log")


def build_tmux_command(exec_root: Path, output_root: Path, mode: str, resume: bool, skip_gpu_idle_gate: bool = False) -> List[str]:
    session = session_name(output_root, mode)
    runtime_python = exec_root / ".venv/bin/python"
    runner = exec_root / "scripts/v2_kure_orchestration.py"
    log = log_path(output_root, mode)
    arguments = [str(runtime_python), str(runner), "run", "--exec-root", str(exec_root), "--output-root", str(output_root), "--mode", mode]
    if resume:
        arguments.append("--resume")
    if skip_gpu_idle_gate:
        arguments.append("--skip-gpu-idle-gate")
    environment = " ".join("%s=%s" % (key, shlex.quote(value)) for key, value in {
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "HF_DATASETS_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "OLLAMA_NUM_PARALLEL": "1",
        "GGML_CUDA_DISABLE_GRAPHS": "1",
        "OLLAMA_NO_CLOUD": "1",
        "PYTHONPATH": str(exec_root),
    }.items())
    inner = "set -o pipefail; %s %s 2>&1 | tee -a %s" % (environment, shlex.join(arguments), shlex.quote(str(log)))
    return ["tmux", "new-session", "-d", "-s", session, "bash", "-lc", inner]


def assert_launchable(exec_root: Path, output_root: Path, mode: str, resume: bool) -> None:
    if not (exec_root / "scripts/v2_kure_orchestration.py").is_file():
        raise LaunchError("isolated V2 runner is missing")
    if not (exec_root / ".venv/bin/python").is_file():
        raise LaunchError("isolated worktree must link the workspace .venv")
    if mode == "all":
        if ((output_root / "smoke").exists() or (output_root / "full226").exists()) and not resume:
            raise LaunchError("refusing to overwrite existing V2 output root; use validated --resume")
    elif (output_root / mode).exists() and not resume:
        raise LaunchError("refusing to overwrite existing V2 output root; use validated --resume")
    if mode == "full226" and not (output_root / "smoke" / "gate.json").is_file():
        raise LaunchError("full226 requires a completed isolated smoke gate")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exec-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--mode", choices=("smoke", "full226", "all"), required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-gpu-idle-gate", action="store_true", help="explicitly bypass only the initial smoke GPU idle gate")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    exec_root, output_root = args.exec_root.resolve(), args.output_root.resolve()
    assert_launchable(exec_root, output_root, args.mode, args.resume)
    command = build_tmux_command(exec_root, output_root, args.mode, args.resume, args.skip_gpu_idle_gate)
    if args.dry_run:
        print(shlex.join(command))
        return 0
    log = log_path(output_root, args.mode)
    if log.exists() or log.is_symlink():
        raise LaunchError("refusing to overwrite existing tmux log: %s" % log)
    log.parent.mkdir(parents=True, exist_ok=True)
    session = session_name(output_root, args.mode)
    if subprocess.run(["tmux", "has-session", "-t", session], check=False).returncode == 0:
        raise LaunchError("tmux session already exists: %s" % session)
    subprocess.run(command, check=True)
    print("started detached tmux session: %s" % session)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LaunchError as exc:
        print("launch error: %s" % exc, file=sys.stderr)
        raise SystemExit(2)
