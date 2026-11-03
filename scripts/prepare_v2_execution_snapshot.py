#!/usr/bin/env python3
"""Create a clean, local-only V2 execution worktree from a dirty source tree.

The source worktree is only read.  Its non-record tracked delta and non-record
untracked source files are copied into a detached temporary worktree, committed
there locally, and then frozen.  Existing records are never copied into a new
run root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Dict, Iterable, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SnapshotPreparationError(RuntimeError):
    pass


def run(command: List[str], cwd: Path, *, input_text: str | None = None) -> str:
    try:
        result = subprocess.run(command, cwd=cwd, input=input_text, text=True, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        raise SnapshotPreparationError("command failed: %s: %s" % (" ".join(command), detail)) from exc
    return result.stdout


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_new_json(path: Path, value: Dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise SnapshotPreparationError("refusing to overwrite: %s" % path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def non_record_untracked(source_root: Path) -> List[Path]:
    output = run(["git", "ls-files", "--others", "--exclude-standard"], source_root)
    paths = []
    for raw in output.splitlines():
        if not raw or raw.startswith("records/"):
            continue
        candidate = Path(raw)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise SnapshotPreparationError("unsafe untracked source path: %s" % raw)
        paths.append(candidate)
    return paths


def copy_untracked_source(source_root: Path, execution_root: Path, paths: Iterable[Path]) -> List[str]:
    copied = []
    for relative in paths:
        source, target = source_root / relative, execution_root / relative
        if not source.is_file() or source.is_symlink():
            raise SnapshotPreparationError("untracked source must be a regular file: %s" % relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(str(relative))
    return copied


def link_ignored_artifacts(source_root: Path, execution_root: Path, parent: Path) -> Dict[str, str]:
    links: Dict[str, str] = {}
    for relative in (Path(".venv"), Path("models"), Path("data/koblex/indexes"), Path("data/koblex/normalized"), Path("data/koblex/qa"), Path("data/koblex/statute")):
        source, target = source_root / relative, execution_root / relative
        if not source.exists() or target.exists() or target.is_symlink():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(source, target_is_directory=True)
        links[str(relative)] = str(source)
    # Never mount old run artifacts inside the clean source worktree.  This
    # read-only pointer is outside it and exists only for provenance inspection.
    source_records = source_root / "records"
    records_link = parent / "source-records-readonly"
    if source_records.is_dir() and not records_link.exists() and not records_link.is_symlink():
        records_link.symlink_to(source_records, target_is_directory=True)
        links["../source-records-readonly"] = str(source_records)
    # Existing tests and frozen input manifests live under records/launch.
    # Link only that read-only input tree; all new run output remains external.
    source_launch, launch_target = source_records / "launch", execution_root / "records" / "launch"
    if source_launch.is_dir() and not launch_target.exists() and not launch_target.is_symlink():
        launch_target.symlink_to(source_launch, target_is_directory=True)
        links["records/launch"] = str(source_launch)
    elif source_launch.is_dir() and launch_target.is_dir():
        # The clean base carries old tracked launch files. Link only missing
        # frozen inputs from the dirty source; do not replace any existing data.
        linked_inputs = 0
        for source_file in source_launch.rglob("*"):
            if not source_file.is_file():
                continue
            target_file = launch_target / source_file.relative_to(source_launch)
            if target_file.exists() or target_file.is_symlink():
                continue
            target_file.parent.mkdir(parents=True, exist_ok=True)
            target_file.symlink_to(source_file)
            linked_inputs += 1
        links["records/launch_missing_frozen_inputs"] = "%s files from %s" % (linked_inputs, source_launch)
    return links


def prepare(source_root: Path, execution_parent: Path, primary_manifest: Path, reference_manifest: Path) -> Dict[str, Any]:
    source_root, execution_parent = source_root.resolve(), execution_parent.resolve()
    if not (source_root / ".git").exists():
        raise SnapshotPreparationError("source root is not a Git worktree")
    if execution_parent.exists() or execution_parent.is_symlink():
        raise SnapshotPreparationError("refusing to reuse execution parent: %s" % execution_parent)
    if not primary_manifest.is_file() or not reference_manifest.is_file():
        raise SnapshotPreparationError("both frozen source manifests must exist")
    execution_parent.mkdir(parents=True, exist_ok=False)
    execution_root = execution_parent / "worktree"
    source_head = run(["git", "rev-parse", "HEAD"], source_root).strip()
    combined_delta = run(["git", "diff", "--binary", "HEAD", "--", ".", ":(exclude)records/**"], source_root)
    untracked = non_record_untracked(source_root)
    run(["git", "worktree", "add", "--detach", str(execution_root), source_head], source_root)
    if combined_delta:
        run(["git", "apply", "--whitespace=nowarn", "-"], execution_root, input_text=combined_delta)
    copied = copy_untracked_source(source_root, execution_root, untracked)
    runner = execution_root / "scripts/v2_kure_orchestration.py"
    run([sys.executable, str(runner), "bootstrap", "--exec-root", str(execution_root), "--primary-source-manifest", str(primary_manifest.resolve()), "--reference-source-manifest", str(reference_manifest.resolve())], execution_root)
    # Git treats directory symlinks differently from trailing-slash ignore rules.
    # Keep only the execution-local links out of the immutable source manifest;
    # their exact hashes are independently checked by preflight.
    with (execution_root / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write("\n# Isolated V2 execution-only artifact symlinks\n/.venv\n/models\n")
    run(["git", "add", "-A", "--", "."], execution_root)
    run(["git", "-c", "user.name=Legal Harness V2 Snapshot", "-c", "user.email=local-v2-snapshot@invalid", "commit", "--no-gpg-sign", "-m", "local immutable V2 execution snapshot"], execution_root)
    links = link_ignored_artifacts(source_root, execution_root, execution_parent)
    source_snapshot = run([sys.executable, "-c", "from runtime.source_snapshot import capture_clean_source_snapshot; import json; print(json.dumps(capture_clean_source_snapshot(__import__('pathlib').Path('.')).to_dict(), sort_keys=True))"], execution_root)
    snapshot = json.loads(source_snapshot)
    result = {
        "snapshot_schema_version": "v2.0",
        "source_root": str(source_root),
        "source_head_before_snapshot": source_head,
        "source_nonrecord_delta_sha256": hashlib.sha256(combined_delta.encode("utf-8")).hexdigest(),
        "copied_untracked_nonrecord_source": copied,
        "execution_root": str(execution_root),
        "execution_git_commit": run(["git", "rev-parse", "HEAD"], execution_root).strip(),
        "execution_git_tree": run(["git", "rev-parse", "HEAD^{tree}"], execution_root).strip(),
        "source_snapshot": snapshot,
        "artifact_links": links,
        "primary_source_manifest": str(primary_manifest.resolve()),
        "primary_source_manifest_sha256": sha256(primary_manifest),
        "reference_source_manifest": str(reference_manifest.resolve()),
        "reference_source_manifest_sha256": sha256(reference_manifest),
        "generated_manifest_hashes": {
            path.name: sha256(path) for path in sorted((execution_root / "frozen_manifests").glob("*.json"))
        },
        "output_root_policy": "No output root is created or required by this snapshot. The launcher caller must supply a new unused durable root, which may be under /workspace/Legal-Harness/records/.",
        "suggested_ephemeral_output_root": str(execution_parent / "outputs"),
        "records_policy": "Existing records are read-only outside the worktree. A caller-selected V2 output root must be new and is never overwritten.",
    }
    write_new_json(execution_parent / "execution_snapshot.json", result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--execution-parent", type=Path, required=True)
    parser.add_argument("--primary-source-manifest", type=Path, required=True)
    parser.add_argument("--reference-source-manifest", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(json.dumps(prepare(args.source_root, args.execution_parent, args.primary_source_manifest, args.reference_source_manifest), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SnapshotPreparationError as exc:
        print("snapshot preparation error: %s" % exc, file=sys.stderr)
        raise SystemExit(2)
