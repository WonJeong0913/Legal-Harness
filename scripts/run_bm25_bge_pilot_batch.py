#!/usr/bin/env python3
"""Run the remaining entries in the frozen BM25+BGE pilot sequentially."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Set

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from runtime.comparison_guard import (
    resolve_frozen_configuration,
    validate_retriever_comparison,
)
from runtime.local_ollama_executor import (
    DEFAULT_S1_TRUNCATION_RETRY_MAX_TOKENS,
    DEFAULT_SKILL_MAX_TOKENS,
)
from runtime.source_snapshot import (
    SourceSnapshot,
    assert_source_snapshot_unchanged,
    capture_clean_source_snapshot,
)


DEFAULT_MANIFEST = PROJECT_ROOT / "data/koblex/manifests/bm25_bge_pilot_20_seed_20260815.json"
DEFAULT_RECORD_ROOT = PROJECT_ROOT / "records/runs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--start-ordinal", type=int, default=1)
    parser.add_argument("--end-ordinal", type=int)
    parser.add_argument("--batch-name")
    parser.add_argument(
        "--comparison-manifest",
        type=Path,
        help="paired BM25/KURE manifest; mandatory for KURE unless declared by the manifest",
    )
    parser.add_argument("--python", type=Path, default=PROJECT_ROOT / ".venv/bin/python")
    parser.add_argument("--record-root", type=Path, default=DEFAULT_RECORD_ROOT)
    parser.add_argument("--batch-log-root", type=Path, default=PROJECT_ROOT / "records/batches")
    parser.add_argument(
        "--warm-resources",
        action="store_true",
        help=(
            "opt in to one sequential process that reuses KURE/BGE/corpus/skill "
            "resources; default remains one isolated subprocess per entry"
        ),
    )
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

KURE_PROVENANCE_ARTIFACTS = (
    ("normalized_corpus_path", "normalized_corpus_sha256"),
    ("vectors_path", "vectors_sha256"),
    ("provision_ids_path", "provision_ids_sha256"),
)


def verify_kure_retriever_provenance(
    configuration: Mapping[str, Any], project_root: Path = PROJECT_ROOT
) -> None:
    """Fail closed when a KURE batch's declared artifacts are not exact."""
    if configuration.get("retriever") != "kure":
        return

    provenance = configuration.get("retriever_provenance")
    if not isinstance(provenance, Mapping):
        raise RuntimeError("KURE retriever_provenance must be an object")

    resolved_root = project_root.resolve()
    for path_key, sha256_key in KURE_PROVENANCE_ARTIFACTS:
        declared_path = provenance.get(path_key)
        expected_sha256 = provenance.get(sha256_key)
        if not isinstance(declared_path, str) or not declared_path:
            raise RuntimeError(
                "KURE retriever_provenance missing %s" % path_key
            )
        if not isinstance(expected_sha256, str) or not expected_sha256:
            raise RuntimeError(
                "KURE retriever_provenance missing %s" % sha256_key
            )
        artifact_relative_path = Path(declared_path)
        if artifact_relative_path.is_absolute() or ".." in artifact_relative_path.parts:
            raise RuntimeError(
                "KURE provenance artifact must be project-relative without '..': %s"
                % path_key
            )
        artifact_path = resolved_root / artifact_relative_path
        if not artifact_path.is_file():
            raise RuntimeError(
                "KURE provenance artifact is missing for %s: %s"
                % (path_key, artifact_path)
            )
        actual_sha256 = sha256(artifact_path)
        if actual_sha256 != expected_sha256:
            raise RuntimeError(
                "KURE provenance SHA256 mismatch for %s: expected %s, actual %s"
                % (path_key, expected_sha256, actual_sha256)
            )


def load_questions(dataset_path: Path) -> Dict[str, Mapping[str, Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError(
            "install pyarrow in the project environment to run the pilot batch"
        ) from exc
    rows = pq.read_table(
        dataset_path, columns=["id", "background", "question", "n_hops"]
    ).to_pylist()
    return {str(row["id"]): row for row in rows}

def resolve_batch_log_root(batch_log_root: Path) -> Path:
    if not batch_log_root.is_absolute():
        batch_log_root = PROJECT_ROOT / batch_log_root
    return batch_log_root.resolve()


def format_benchmark_input(question: Mapping[str, Any]) -> str:
    background = str(question.get("background") or "").strip()
    prompt = str(question.get("question") or "").strip()
    if not prompt:
        raise RuntimeError("benchmark question text is empty")
    if not background:
        return "[질문]\n%s" % prompt
    return "[배경 시나리오]\n%s\n\n[질문]\n%s" % (background, prompt)


def build_run_command(
    python: Path,
    benchmark_input: str,
    question_id: str,
    configuration: Mapping[str, Any],
    record_root: Path,
    source_snapshot: SourceSnapshot,
) -> List[str]:
    """Build one child run command without consulting mutable batch state."""
    command = [
        str(python),
        str(PROJECT_ROOT / "scripts/run_local_harness.py"),
        benchmark_input,
        "--retriever", configuration["retriever"],
        "--model", configuration["model"],
        "--ollama-endpoint", str(
            configuration.get(
                "ollama_endpoint", "http://127.0.0.1:11434/api/generate"
            )
        ),
        "--num-ctx", str(configuration["num_ctx"]),
        "--s1-max-tokens", str(
            configuration.get(
                "s1_max_tokens", DEFAULT_SKILL_MAX_TOKENS["legal_issue_and_query_planning"]
            )
        ),
        "--s1-truncation-retry-max-tokens", str(
            configuration.get(
                "s1_truncation_retry_max_tokens",
                DEFAULT_S1_TRUNCATION_RETRY_MAX_TOKENS,
            )
        ),
        "--rounds", str(configuration["total_retrieval_rounds"]),
        "--requests", str(configuration["total_retrieval_requests"]),
        "--question-id", question_id,
        "--condition", configuration["condition"],
        "--seed", str(configuration["seed"]),
        "--rerank-pool-k", str(configuration.get("rerank_pool_k", 100)),
        "--final-top-k", str(configuration.get("final_top_k", 10)),
        "--rerank-query-mode", str(
            configuration.get("rerank_query_mode", "combined_issue")
        ),
        "--candidate-selection", str(
            configuration.get("candidate_selection", "global_top_k")
        ),
        "--per-evidence-min-k", str(configuration.get("per_evidence_min_k", 1)),
        "--candidate-budget-scope", str(
            configuration.get("candidate_budget_scope", "per_issue")
        ),
        "--round-merge-mode", str(
            configuration.get("round_merge_mode", "raw_score")
        ),
        "--dedup-mode", str(configuration.get("dedup_mode", "none")),
        "--rerank-document-mode", str(
            configuration.get("rerank_document_mode", "body_only")
        ),
        "--input-format", str(
            configuration.get("input_format", "koblex_background_plus_question")
        ),
        "--record-dir", str(record_root),
        "--expected-git-commit", source_snapshot.git_commit,
        "--expected-source-manifest-sha256", source_snapshot.source_manifest_sha256,
    ]
    if configuration.get("canonical_rerank_query_missing_only", False):
        command.extend([
            "--canonical-rerank-query-missing-only",
            "--canonical-rerank-query-max-characters",
            str(configuration.get("canonical_rerank_query_max_characters", 512)),
            "--canonical-rerank-query-max-token-like-units",
            str(configuration.get("canonical_rerank_query_max_token_like_units", 96)),
        ])
    return command


def record_directories(root: Path) -> Set[Path]:
    if not root.exists():
        return set()
    return {path for path in root.iterdir() if path.is_dir()}


def read_result(created: Iterable[Path]) -> Dict[str, Any]:
    directories = sorted(created)
    if len(directories) != 1:
        return {"record_directory_count": len(directories), "status": "NO_UNIQUE_RECORD"}
    directory = directories[0]
    result_file = directory / "result.json"
    outcome: Dict[str, Any] = {"record_directory": str(directory)}
    if not result_file.is_file():
        outcome["status"] = "NO_FINAL_RESULT"
        return outcome
    result = json.loads(result_file.read_text(encoding="utf-8"))
    outcome.update(
        {
            "status": result.get("status"),
            "termination_reason": result.get("termination_reason"),
            "abstention_reason": result.get("abstention_reason"),
            "errors": result.get("errors", []),
            "end_to_end_latency_ms": result.get("end_to_end_latency_ms"),
        }
    )
    return outcome


def _warm_harness_module() -> Any:
    """Import only when the explicit persistent execution mode is selected."""
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from scripts import run_local_harness

    return run_local_harness


def main() -> int:
    args = parse_args()
    source_snapshot = capture_clean_source_snapshot(PROJECT_ROOT)
    if not args.record_root.is_absolute():
        args.record_root = PROJECT_ROOT / args.record_root
    args.record_root = args.record_root.resolve()
    manifest_path = args.manifest
    args.batch_log_root = resolve_batch_log_root(args.batch_log_root)
    if not manifest_path.is_absolute():
        manifest_path = PROJECT_ROOT / manifest_path
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = manifest["source_dataset"]
    dataset_path = PROJECT_ROOT / source["path"]
    if sha256(dataset_path) != source["sha256"]:
        raise RuntimeError("KoBLEX dataset hash does not match the frozen pilot manifest")
    if not args.warm_resources and not args.python.is_file():
        raise RuntimeError("project Python is unavailable: %s" % args.python)

    questions = load_questions(dataset_path)
    configuration = resolve_frozen_configuration(manifest["frozen_configuration"])
    verify_kure_retriever_provenance(configuration)
    comparison_reference = args.comparison_manifest
    if comparison_reference is None:
        selection = manifest.get("selection", {})
        if isinstance(selection, Mapping):
            declared_reference = selection.get("reference_configuration_manifest")
            if declared_reference:
                comparison_reference = Path(str(declared_reference))

    comparison_metadata = None
    if comparison_reference is not None:
        if not comparison_reference.is_absolute():
            comparison_reference = PROJECT_ROOT / comparison_reference
        comparison_reference = comparison_reference.resolve()
        if not comparison_reference.is_file():
            raise RuntimeError(
                "comparison manifest is unavailable: %s" % comparison_reference
            )
        reference_manifest = json.loads(
            comparison_reference.read_text(encoding="utf-8")
        )
        comparison_metadata = validate_retriever_comparison(
            manifest,
            reference_manifest,
            manifest_path,
            comparison_reference,
        )
    elif configuration.get("retriever") == "kure":
        raise RuntimeError(
            "KURE batches require a paired BM25 comparison manifest before start"
        )
    if args.end_ordinal is not None and args.end_ordinal < args.start_ordinal:
        raise RuntimeError("end ordinal cannot be smaller than start ordinal")
    entries: List[Mapping[str, Any]] = [
        entry
        for entry in manifest["entries"]
        if int(entry["ordinal"]) >= args.start_ordinal
        and (
            args.end_ordinal is None
            or int(entry["ordinal"]) <= args.end_ordinal
        )
    ]
    if not entries:
        raise RuntimeError("no pilot entries remain at or after ordinal %d" % args.start_ordinal)

    batch_name = args.batch_name or manifest.get("name", "bm25-bge-batch")
    batch_id = "%s-%s" % (batch_name, uuid.uuid4())
    batch_dir = args.batch_log_root / batch_id
    batch_dir.mkdir(parents=True, exist_ok=False)
    batch_manifest = dict(manifest)
    batch_manifest["frozen_configuration"] = configuration
    if comparison_metadata is not None:
        batch_manifest["retriever_comparison"] = comparison_metadata
    batch_manifest_path = batch_dir / "manifest.json"
    batch_manifest_path.write_text(
        json.dumps(batch_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    batch_metadata = {
        "batch_id": batch_id,
        "started_at_utc": utc_now(),
        "manifest": str(manifest_path.relative_to(PROJECT_ROOT)),
        "source_snapshot": source_snapshot.to_dict(),
        "manifest_sha256": sha256(manifest_path),
        "batch_manifest_sha256": sha256(batch_manifest_path),
        "start_ordinal": args.start_ordinal,
        "end_ordinal": args.end_ordinal,
        "entry_count": len(entries),
        "configuration": configuration,
        "retriever_comparison": comparison_metadata,
        "record_root": str(args.record_root),
        "execution_mode": (
            "warm_persistent" if args.warm_resources else "subprocess_per_entry"
        ),
    }
    (batch_dir / "metadata.json").write_text(
        json.dumps(batch_metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    warm_harness = None
    warm_resources = None
    if args.warm_resources:
        warm_harness = _warm_harness_module()
        warm_resource_args = warm_harness.build_frozen_run_args(
            "",
            "",
            configuration,
            args.record_root,
            source_snapshot.git_commit,
            source_snapshot.source_manifest_sha256,
        )
        warm_resources = warm_harness.PersistentHarnessResources(warm_resource_args)

    summary_path = batch_dir / "summary.jsonl"
    has_failure = False
    with summary_path.open("w", encoding="utf-8") as summary:
        for entry in entries:
            assert_source_snapshot_unchanged(PROJECT_ROOT, source_snapshot)
            ordinal = int(entry["ordinal"])
            question_id = str(entry["question_id"])
            question = questions.get(question_id)
            if question is None:
                raise RuntimeError("question ID missing from frozen dataset: %s" % question_id)
            if int(question["n_hops"]) != int(entry["n_hops"]):
                raise RuntimeError("hop count mismatch for %s" % question_id)
            log_path = batch_dir / ("%02d_%s.log" % (ordinal, question_id))
            benchmark_input = format_benchmark_input(question)
            command = build_run_command(
                args.python,
                benchmark_input,
                question_id,
                configuration,
                args.record_root,
                source_snapshot,
            )
            before = record_directories(args.record_root)
            started_at = utc_now()
            assert_source_snapshot_unchanged(PROJECT_ROOT, source_snapshot)
            with log_path.open("w", encoding="utf-8") as log:
                if args.warm_resources:
                    try:
                        warm_args = warm_harness.build_frozen_run_args(
                            benchmark_input,
                            question_id,
                            configuration,
                            args.record_root,
                            source_snapshot.git_commit,
                            source_snapshot.source_manifest_sha256,
                        )
                        execution = warm_harness.run_question(
                            warm_args,
                            source_snapshot=source_snapshot,
                            resources=warm_resources,
                        )
                    except Exception:
                        traceback.print_exc(file=log)
                        exit_code = 1
                    else:
                        print(execution.rendered_output, file=log)
                        exit_code = execution.exit_code
                else:
                    completed = subprocess.run(
                        command,
                        cwd=PROJECT_ROOT,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        text=True,
                        check=False,
                    )
                    exit_code = completed.returncode
            assert_source_snapshot_unchanged(PROJECT_ROOT, source_snapshot)
            outcome = read_result(record_directories(args.record_root) - before)
            status = outcome.get("status")
            normal = status in {"ANSWER", "ABSTAIN"}
            has_failure = has_failure or not normal
            summary_row = {
                "ordinal": ordinal,
                "question_id": question_id,
                "n_hops": entry["n_hops"],
                "started_at_utc": started_at,
                "completed_at_utc": utc_now(),
                "exit_code": exit_code,
                "log_file": str(log_path.relative_to(PROJECT_ROOT)),
                **outcome,
            }
            summary.write(json.dumps(summary_row, ensure_ascii=False) + "\n")
            summary.flush()
            print(json.dumps(summary_row, ensure_ascii=False), flush=True)

    assert_source_snapshot_unchanged(PROJECT_ROOT, source_snapshot)
    batch_metadata["completed_at_utc"] = utc_now()
    batch_metadata["has_execution_failure"] = has_failure
    (batch_dir / "metadata.json").write_text(
        json.dumps(batch_metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 1 if has_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
