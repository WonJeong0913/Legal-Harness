"""Write immutable, paper-ready artifacts for one harness execution."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, Mapping, Optional

from harness.tracing import JsonlTraceSink, to_primitive
from runtime.source_snapshot import source_dirty_paths_from_porcelain


RECORD_SCHEMA_VERSION = "1.4"
RETRIEVAL_PROVENANCE_SCHEMA_VERSION = "1.0"
SKILL_GENERATION_DIAGNOSTIC_SCHEMA_VERSION = "1.1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_worktree_dirty_from_porcelain(status: str) -> bool:
    return bool(source_dirty_paths_from_porcelain(status))


def _git_source_worktree_dirty(project_root: Path) -> Optional[bool]:
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=str(project_root), check=True, capture_output=True, text=True,
        ).stdout
        return _source_worktree_dirty_from_porcelain(status)
    except (OSError, subprocess.CalledProcessError):
        return None


def _git_commit(project_root: Path) -> Optional[str]:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(project_root),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _package_versions() -> Dict[str, Optional[str]]:
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover - Python 3.8 fallback
        return {}
    versions: Dict[str, Optional[str]] = {}
    for package in ("torch", "transformers", "sentence-transformers", "pyarrow"):
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = None
    return versions


def _ollama_model_artifact(model: object) -> Optional[str]:
    if not isinstance(model, str) or not model:
        return None
    try:
        modelfile = subprocess.run(
            ["ollama", "show", model, "--modelfile"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in modelfile.splitlines():
        if line.startswith("FROM "):
            return line.removeprefix("FROM ").strip()
    return None


def _skill_hashes(skills_root: Path) -> Dict[str, str]:
    hashes: Dict[str, str] = {}
    for path in sorted(skills_root.glob("**/*")):
        if (
            path.is_file()
            and path.name != ".gitkeep"
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
        ):
            hashes[str(path.relative_to(skills_root))] = _sha256(path)
    return hashes


class ExperimentRecord:
    """Own one fresh on-disk record directory and its event trace."""

    def __init__(
        self,
        record_root: Path,
        run_id: str,
        project_root: Path,
        skills_root: Path,
        configuration: Mapping[str, Any],
        question: str,
        question_id: Optional[str],
        source_snapshot: Optional[Mapping[str, Any]] = None,
    ):
        self.run_id = run_id
        self.directory = record_root / run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.trace_sink = JsonlTraceSink(self.directory / "events.jsonl")
        self.started_at = datetime.now(timezone.utc)
        self._started_at_monotonic = perf_counter()
        self._skill_attempt_count = 0
        metadata = {
            "record_schema_version": RECORD_SCHEMA_VERSION,
            "retrieval_provenance_schema_version": RETRIEVAL_PROVENANCE_SCHEMA_VERSION,
            "run_id": run_id,
            "started_at_utc": self.started_at.isoformat(),
            "model_artifact": _ollama_model_artifact(configuration.get("model")),
            "question_id": question_id,
            "question": question,
            "configuration": to_primitive(dict(configuration)),
            "git_commit": _git_commit(project_root),
            "source_snapshot": (
                to_primitive(dict(source_snapshot))
                if source_snapshot is not None
                else None
            ),
            "git_source_worktree_dirty": _git_source_worktree_dirty(project_root),
            "runtime": {
                "python": sys.version,
                "platform": platform.platform(),
                "packages": _package_versions(),
            },
            "skill_sha256": _skill_hashes(skills_root),
            "index_metadata": self._read_index_metadata(project_root),
        }
        self._write_json("metadata.json", metadata)

    def record_skill_attempt(self, diagnostic: Mapping[str, Any]) -> None:
        self._skill_attempt_count += 1
        payload = {
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            **to_primitive(dict(diagnostic)),
        }
        path = self.directory / "skill_attempts.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
            )

    @staticmethod
    def _read_index_metadata(project_root: Path) -> Optional[Dict[str, Any]]:
        path = project_root / "data/koblex/indexes/metadata.json"
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"error": "invalid index metadata", "path": str(path)}

    def finalize(self, outcome: Any) -> Path:
        completed_at = datetime.now(timezone.utc)
        state = to_primitive(outcome.state)
        stage_records = state.pop("retrieval_stage_records", [])
        stage_counts = Counter(
            record.get("candidate_stage", "unknown")
            for record in stage_records
            if isinstance(record, dict)
        )
        stage_file = None
        if stage_records:
            stage_file = "retrieval_stages.jsonl"
            with (self.directory / stage_file).open("w", encoding="utf-8") as handle:
                for record in stage_records:
                    handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
                    handle.write("\n")
        result = {
            "record_schema_version": RECORD_SCHEMA_VERSION,
            "retrieval_provenance": {
                "schema_version": RETRIEVAL_PROVENANCE_SCHEMA_VERSION,
                "stage_file": stage_file,
                "stage_record_counts": dict(sorted(stage_counts.items())),
            },
            "skill_generation_diagnostics": {
                "schema_version": SKILL_GENERATION_DIAGNOSTIC_SCHEMA_VERSION,
                "attempt_file": (
                    "skill_attempts.jsonl" if self._skill_attempt_count else None
                ),
                "attempt_count": self._skill_attempt_count,
                "response_retention": {
                    "response_text": {
                        "retention": "full",
                        "encoding": "utf-8",
                        "sha256_field": "response_sha256",
                        "character_count_field": "response_characters",
                        "utf8_byte_count_field": "response_utf8_bytes",
                    },
                    "response_tail": {
                        "retention": "last_characters",
                        "character_limit": 512,
                    },
                },
            },
            "run_id": self.run_id,
            "completed_at_utc": completed_at.isoformat(),
            "end_to_end_latency_ms": round((perf_counter() - self._started_at_monotonic) * 1000, 3),
            "status": outcome.status.value,
            "termination_reason": outcome.termination_reason.value if outcome.termination_reason else None,
            "abstention_reason": outcome.abstention_reason.value if outcome.abstention_reason else None,
            "answer": outcome.answer,
            "claims": list(getattr(outcome, "claims", ())),
            "claim_citations": list(getattr(outcome, "claim_citations", ())),
            "assumptions": list(getattr(outcome, "assumptions", ())),
            "limitations": list(getattr(outcome, "limitations", ())),
            "answer_mode": (
                outcome.answer_mode.value if getattr(outcome, "answer_mode", None) else None
            ),
            "complete_answer": bool(getattr(outcome, "complete_answer", False)),
            "answered_target_ids": list(
                getattr(outcome, "answered_target_ids", ())
            ),
            "deferred_target_ids": list(
                getattr(outcome, "deferred_target_ids", ())
            ),
            "candidate_answer": getattr(outcome, "candidate_answer", None),
            "candidate_answer_status": (
                getattr(outcome, "candidate_answer_status", None).value
                if getattr(outcome, "candidate_answer_status", None)
                else None
            ),
            "candidate_answer_basis": (
                getattr(outcome, "candidate_answer_basis", None).value
                if getattr(outcome, "candidate_answer_basis", None)
                else None
            ),
            "candidate_answer_termination_reason": (
                getattr(outcome, "candidate_answer_termination_reason", None).value
                if getattr(outcome, "candidate_answer_termination_reason", None)
                else None
            ),
            "candidate_answer_error": getattr(outcome, "candidate_answer_error", None),
            "candidate_claims": list(getattr(outcome, "candidate_claims", ())),
            "candidate_claim_citations": list(
                getattr(outcome, "candidate_claim_citations", ())
            ),
            "candidate_assumptions": list(
                getattr(outcome, "candidate_assumptions", ())
            ),
            "candidate_limitations": list(
                getattr(outcome, "candidate_limitations", ())
            ),
            "errors": list(outcome.errors),
            "state": state,
        }
        return self._write_json("result.json", result)

    def _write_json(self, filename: str, payload: Mapping[str, Any]) -> Path:
        path = self.directory / filename
        path.write_text(
            json.dumps(to_primitive(dict(payload)), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path
