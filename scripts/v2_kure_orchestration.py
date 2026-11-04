#!/usr/bin/env python3
"""Prepare and run the isolated, offline V2 KURE experiment plan.

This file intentionally contains no model warm-up at import time.  The only
execution path that loads KURE/BGE/Ollama is ``run``; ``bootstrap``,
``preflight``, and ``--dry-run`` are CPU-only control-plane operations.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
import traceback
from urllib.error import URLError
from urllib.request import urlopen
import uuid
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
TOTAL_FULL226 = 226
CHUNK_SIZE = 20
OFFLINE_ENVIRONMENT = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "TOKENIZERS_PARALLELISM": "false",
    "OLLAMA_NUM_PARALLEL": "1",
    "GGML_CUDA_DISABLE_GRAPHS": "1",
    "OLLAMA_NO_CLOUD": "1",
}
EXPECTED_RUNTIME = {
    "model": "legal-harness-qwen38-q8",
    "endpoint": "http://127.0.0.1:11435/api/generate",
    "seed": 0,
    "num_ctx": 32768,
    "num_parallel": 1,
}
PRIMARY_FROZEN_NAME = "v2-kure-qwen38-q8-offline-full226-20260825"
REFERENCE_FROZEN_NAME = "v2-bm25-reference-qwen38-q8-offline-full226-20260825"
SMOKE_FROZEN_NAME = "v2-kure-qwen38-q8-offline-smoke3-20260825"
SMOKE_REFERENCE_FROZEN_NAME = "v2-bm25-reference-qwen38-q8-offline-smoke3-20260825"
NORMAL_STATUSES = {"ANSWER", "ABSTAIN"}
DEFAULT_GPU_IDLE_UTILIZATION_MAX = 10
DEFAULT_GPU_IDLE_USED_MIB_MAX = 2048
DEFAULT_GPU_IDLE_POLL_SECONDS = 1800
DEFAULT_GPU_IDLE_STABLE_INTERVAL_SECONDS = 30
DEFAULT_GPU_IDLE_REQUIRED_STABLE_SAMPLES = 2
QWEN_MODEL_PROVENANCE = {
    "alias": "legal-harness-qwen38-q8",
    "ollama_model_blob": "/root/.ollama/models/blobs/sha256-f5c702d8820d36fb55985bb238fc83ee3a313e920f4b752a437c3a6a9e14e4c8",
    "sha256": "f5c702d8820d36fb55985bb238fc83ee3a313e920f4b752a437c3a6a9e14e4c8",
    "file": "Qwen3.8-27B-Q8_0.gguf",
    "quantization": "Q8_0",
    "observed_architecture": "qwen35",
    "observed_parameter_count": "26.9B",
    "ollama_manifest_digest": "91f49c230b9d1fd034414b1035b361cfe4ad1c89f7076012b10420edea8b78ff",
    "ollama_details": {
        "family": "qwen35",
        "parameter_size": "26.9B",
        "quantization_level": "Q8_0",
    },
    "provenance_note": "Observed local Ollama metadata; architecture is recorded, not relabeled.",
}


class OrchestrationError(RuntimeError):
    """The isolated run plan would be unreproducible or unsafe."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OrchestrationError("invalid JSON: %s" % path) from exc
    if not isinstance(payload, dict):
        raise OrchestrationError("JSON root must be an object: %s" % path)
    return dict(payload)


def write_json_new(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise OrchestrationError("refusing to overwrite immutable artifact: %s" % path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl_new(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    if path.exists() or path.is_symlink():
        raise OrchestrationError("refusing to overwrite immutable artifact: %s" % path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")


def chunks_for_entries(total: int = TOTAL_FULL226, size: int = CHUNK_SIZE) -> Tuple[Tuple[int, int], ...]:
    if total <= 0 or size <= 0:
        raise OrchestrationError("total and chunk size must be positive")
    return tuple((start, min(start + size - 1, total)) for start in range(1, total + 1, size))


def assert_full226_chunks(chunks: Sequence[Tuple[int, int]]) -> None:
    expected = chunks_for_entries()
    if tuple(chunks) != expected:
        raise OrchestrationError("full226 must use immutable 20-question checkpoints")


def _entry_signature(entries: Any) -> Tuple[Tuple[int, str, int], ...]:
    if not isinstance(entries, list):
        raise OrchestrationError("manifest.entries must be an array")
    result = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise OrchestrationError("manifest entry must be an object")
        try:
            result.append((int(entry["ordinal"]), str(entry["question_id"]), int(entry["n_hops"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise OrchestrationError("invalid frozen manifest entry") from exc
    if not result:
        raise OrchestrationError("manifest has no entries")
    return tuple(result)


def assert_kure_only(configuration: Mapping[str, Any]) -> None:
    if configuration.get("retriever") != "kure":
        raise OrchestrationError("V2 execution permits only the KURE retriever")
    for key, expected in (("model", EXPECTED_RUNTIME["model"]), ("seed", 0), ("num_ctx", 32768)):
        if configuration.get(key) != expected:
            raise OrchestrationError("frozen configuration %s mismatch" % key)
    if configuration.get("ollama_endpoint") != EXPECTED_RUNTIME["endpoint"]:
        raise OrchestrationError("V2 must use the offline endpoint on port 11435")
    runtime = configuration.get("runtime_determinism")
    if not isinstance(runtime, Mapping) or runtime.get("num_parallel") != 1:
        raise OrchestrationError("frozen runtime must declare num_parallel=1")


def assert_reference_is_read_only(primary: Mapping[str, Any], reference: Mapping[str, Any], primary_path: Path, reference_path: Path) -> Dict[str, Any]:
    """Validate the paired reference without scheduling any BM25 operation."""
    from runtime.comparison_guard import validate_retriever_comparison

    assert_kure_only(dict(primary.get("frozen_configuration") or {}))
    reference_configuration = reference.get("frozen_configuration")
    if not isinstance(reference_configuration, Mapping) or reference_configuration.get("retriever") != "bm25":
        raise OrchestrationError("comparison reference must be BM25 metadata only")
    comparison = validate_retriever_comparison(primary, reference, primary_path, reference_path)
    if comparison.get("primary_retriever") != "kure" or comparison.get("reference_retriever") != "bm25":
        raise OrchestrationError("comparison pair is not KURE primary / BM25 reference")
    return {
        **comparison,
        "bm25_execution": "FORBIDDEN",
        "bm25_reference_use": "READ_ONLY_CONFIGURATION_GUARD",
    }


def assert_no_external_score_injection(command: Sequence[str]) -> None:
    forbidden = [item for item in command if item == "--lf-eval-scores" or item.startswith("--lf-eval-scores=")]
    if forbidden:
        raise OrchestrationError("external LF-Eval score injection is forbidden")


def assert_kure_execution_command(command: Sequence[str]) -> None:
    values = list(command)
    if "--retriever" not in values:
        raise OrchestrationError("execution command must declare retriever")
    index = values.index("--retriever")
    if index + 1 >= len(values) or values[index + 1] != "kure":
        raise OrchestrationError("execution command must use KURE, never BM25")
    assert_no_external_score_injection(values)


def _safe_relative_artifact(exec_root: Path, declared: Any, label: str) -> Path:
    if not isinstance(declared, str) or not declared:
        raise OrchestrationError("missing local artifact path: %s" % label)
    relative = Path(declared)
    if relative.is_absolute() or ".." in relative.parts:
        raise OrchestrationError("artifact path must be relative without '..': %s" % label)
    return exec_root / relative


def verify_kure_artifacts(configuration: Mapping[str, Any], exec_root: Path) -> Dict[str, Any]:
    """Hash only local KURE files; this never initializes a searcher."""
    provenance = configuration.get("retriever_provenance")
    if not isinstance(provenance, Mapping):
        raise OrchestrationError("KURE retriever provenance is missing")
    verified: Dict[str, str] = {}
    for path_key, hash_key in (
        ("normalized_corpus_path", "normalized_corpus_sha256"),
        ("vectors_path", "vectors_sha256"),
        ("provision_ids_path", "provision_ids_sha256"),
    ):
        artifact = _safe_relative_artifact(exec_root, provenance.get(path_key), path_key)
        expected = provenance.get(hash_key)
        if not isinstance(expected, str) or len(expected) != 64:
            raise OrchestrationError("invalid KURE provenance hash: %s" % hash_key)
        if not artifact.is_file():
            raise OrchestrationError("KURE artifact is missing: %s" % artifact)
        if sha256(artifact) != expected:
            raise OrchestrationError("KURE artifact hash mismatch: %s" % path_key)
        verified[path_key] = expected
    model_root = _safe_relative_artifact(exec_root, provenance.get("model_path"), "model_path")
    model_weights = model_root / "model.safetensors"
    expected_weights = provenance.get("model_weights_sha256")
    if not isinstance(expected_weights, str) or len(expected_weights) != 64:
        raise OrchestrationError("invalid KURE model_weights_sha256")
    if not model_weights.is_file():
        raise OrchestrationError("KURE model.safetensors is missing: %s" % model_weights)
    if sha256(model_weights) != expected_weights:
        raise OrchestrationError("KURE model.safetensors hash mismatch")
    verified["model.safetensors"] = expected_weights
    return verified


def check_local_ollama_readiness(configuration: Mapping[str, Any], timeout_seconds: float = 5.0) -> Dict[str, Any]:
    """Non-generative local readiness check; it never calls /api/generate."""
    endpoint = str(configuration.get("ollama_endpoint") or "")
    model = str(configuration.get("model") or "")
    if not endpoint.startswith("http://127.0.0.1:") or not endpoint.endswith("/api/generate"):
        raise OrchestrationError("readiness requires the fixed local generate endpoint")
    if model != EXPECTED_RUNTIME["model"]:
        raise OrchestrationError("readiness model alias mismatch")
    tags_url = endpoint[: -len("/generate")] + "/tags"
    try:
        with urlopen(tags_url, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise OrchestrationError("local Ollama readiness check failed") from exc
    provenance = configuration.get("model_provenance")
    if not isinstance(provenance, Mapping):
        raise OrchestrationError("readiness model provenance is missing")
    if provenance.get("alias") != model:
        raise OrchestrationError("readiness provenance alias mismatch")
    expected_digest = provenance.get("ollama_manifest_digest")
    expected_details = provenance.get("ollama_details")
    if not isinstance(expected_digest, str) or len(expected_digest) != 64:
        raise OrchestrationError("readiness manifest digest is missing")
    if not isinstance(expected_details, Mapping):
        raise OrchestrationError("readiness model details are missing")
    models = payload.get("models") if isinstance(payload, Mapping) else None
    aliases, matched = set(), []
    allowed_names = {model, model + ":latest"}
    if isinstance(models, list):
        for item in models:
            if not isinstance(item, Mapping):
                continue
            names = {str(item[key]) for key in ("name", "model") if isinstance(item.get(key), str)}
            aliases.update(names)
            if names & allowed_names:
                matched.append(dict(item))
    if not matched:
        raise OrchestrationError("local Ollama alias is unavailable: %s" % model)
    for item in matched:
        details = item.get("details")
        if item.get("digest") != expected_digest:
            continue
        if isinstance(details, Mapping) and all(details.get(key) == expected_details.get(key) for key in ("family", "parameter_size", "quantization_level")):
            matched_name = sorted({str(item[key]) for key in ("name", "model") if item.get(key) in allowed_names})[0]
            return {
                "endpoint": endpoint,
                "tags_url": tags_url,
                "model_alias": model,
                "resolved_model_name": matched_name,
                "manifest_digest": expected_digest,
                "details": {key: details[key] for key in ("family", "parameter_size", "quantization_level")},
                "available_aliases": sorted(aliases),
            }
    raise OrchestrationError("local Ollama model provenance does not match the frozen alias")


def _copy_manifest(source: Mapping[str, Any], name: str, configuration: Mapping[str, Any], entries: Sequence[Mapping[str, Any]], role: str) -> Dict[str, Any]:
    output = deepcopy(dict(source))
    output["name"] = name
    output["entries"] = [dict(entry) for entry in entries]
    output["frozen_configuration"] = dict(configuration)
    selection = dict(output.get("selection") or {})
    selection.update({
        "method": "V2 immutable frozen selection derived without reordering from the C5 full226 manifest",
        "entry_count": len(entries),
        "execution_role": role,
        "lf_eval": "excluded; no LF-Eval invocation or score injection",
    })
    output["selection"] = selection
    output["purpose"] = (
        "V2 offline KURE orchestration. BM25 is read-only configuration comparison metadata; "
        "BM25 search/index execution, ParSeR, and LF-Eval are prohibited."
    )
    return output


def build_v2_manifests(primary_source: Mapping[str, Any], reference_source: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    source_entries = list(primary_source.get("entries") or [])
    if _entry_signature(source_entries) != _entry_signature(reference_source.get("entries")):
        raise OrchestrationError("source KURE/BM25 manifest order differs")
    if len(source_entries) != TOTAL_FULL226:
        raise OrchestrationError("V2 full run requires the exact frozen 226-entry order")
    if [int(entry["ordinal"]) for entry in source_entries] != list(range(1, TOTAL_FULL226 + 1)):
        raise OrchestrationError("frozen 226 ordinals must be contiguous")

    primary_configuration = deepcopy(dict(primary_source.get("frozen_configuration") or {}))
    reference_configuration = deepcopy(dict(reference_source.get("frozen_configuration") or {}))
    primary_configuration.update({
        "condition": "V2-KURE-offline-full226-Qwen3.8-Q8_0",
        "retriever": "kure",
        "model": EXPECTED_RUNTIME["model"],
        "seed": 0,
        "num_ctx": 32768,
        "ollama_endpoint": EXPECTED_RUNTIME["endpoint"],
    })
    runtime = dict(primary_configuration.get("runtime_determinism") or {})
    runtime.update({"num_parallel": 1, "seed_forwarding": "ollama_options_seed"})
    primary_configuration["runtime_determinism"] = runtime
    primary_configuration["model_provenance"] = deepcopy(QWEN_MODEL_PROVENANCE)
    assert_kure_only(primary_configuration)

    reference_configuration = deepcopy(primary_configuration)
    reference_configuration["condition"] = "V2-BM25-reference-only-full226-Qwen3.8-Q8_0"
    reference_configuration["retriever"] = "bm25"
    reference_configuration.pop("retriever_provenance", None)
    full = _copy_manifest(primary_source, PRIMARY_FROZEN_NAME, primary_configuration, source_entries, "PRIMARY_KURE_EXECUTION")
    reference = _copy_manifest(reference_source, REFERENCE_FROZEN_NAME, reference_configuration, source_entries, "COMPARISON_REFERENCE_ONLY_MUST_NEVER_BE_EXECUTED")

    smoke_entries: List[Mapping[str, Any]] = []
    seen_hops = set()
    for entry in source_entries:
        hop = int(entry["n_hops"])
        if hop in {1, 2, 3} and hop not in seen_hops:
            smoke_entries.append(entry)
            seen_hops.add(hop)
        if seen_hops == {1, 2, 3}:
            break
    if {int(item["n_hops"]) for item in smoke_entries} != {1, 2, 3}:
        raise OrchestrationError("frozen full226 has no deterministic 1/2/3-hop smoke trio")
    # Smoke execution ordinals are contiguous; source_ordinal preserves frozen full226 provenance.
    smoke_entries = [
        {**dict(entry), "source_ordinal": int(entry["ordinal"]), "ordinal": index}
        for index, entry in enumerate(smoke_entries, start=1)
    ]
    smoke_configuration = deepcopy(primary_configuration)
    smoke_configuration["condition"] = "V2-KURE-offline-smoke3-Qwen3.8-Q8_0"
    smoke_reference_configuration = deepcopy(reference_configuration)
    smoke_reference_configuration["condition"] = "V2-BM25-reference-only-smoke3-Qwen3.8-Q8_0"
    return {
        "full": full,
        "reference": reference,
        "smoke": _copy_manifest(primary_source, SMOKE_FROZEN_NAME, smoke_configuration, smoke_entries, "OPERATIONAL_SMOKE_ONLY_NOT_BENCHMARK_EVIDENCE"),
        "smoke_reference": _copy_manifest(reference_source, SMOKE_REFERENCE_FROZEN_NAME, smoke_reference_configuration, smoke_entries, "COMPARISON_REFERENCE_ONLY_MUST_NEVER_BE_EXECUTED"),
    }


def write_v2_manifests(exec_root: Path, primary_source: Path, reference_source: Path) -> Dict[str, Path]:
    frozen_root = exec_root / "frozen_manifests"
    if frozen_root.exists() or frozen_root.is_symlink():
        raise OrchestrationError("refusing to overwrite existing frozen_manifests")
    primary = read_json(primary_source)
    reference = read_json(reference_source)
    manifests = build_v2_manifests(primary, reference)
    paths = {
        "full": frozen_root / "v2_kure_full226.json",
        "reference": frozen_root / "v2_bm25_reference_full226.json",
        "smoke": frozen_root / "v2_kure_smoke3.json",
        "smoke_reference": frozen_root / "v2_bm25_reference_smoke3.json",
    }
    for key, path in paths.items():
        write_json_new(path, manifests[key])
    source_metadata = {
        "created_at_utc": utc_now(),
        "primary_source_manifest": str(primary_source.resolve()),
        "primary_source_manifest_sha256": sha256(primary_source),
        "reference_source_manifest": str(reference_source.resolve()),
        "reference_source_manifest_sha256": sha256(reference_source),
        "generated": {key: {"path": str(path.relative_to(exec_root)), "sha256": sha256(path)} for key, path in paths.items()},
        "smoke_entries": [
            {"ordinal": int(entry["ordinal"]), "source_ordinal": int(entry.get("source_ordinal", entry["ordinal"])), "question_id": str(entry["question_id"]), "n_hops": int(entry["n_hops"])}
            for entry in manifests["smoke"]["entries"]
        ],
        "execution_policy": {
            "primary_retriever": "kure",
            "bm25_execution": "FORBIDDEN",
            "parser_execution": "FORBIDDEN",
            "lf_eval_score_injection": "FORBIDDEN",
            "network": "OFFLINE_ONLY",
        },
    }
    write_json_new(frozen_root / "source_metadata.json", source_metadata)
    assert_reference_is_read_only(manifests["full"], manifests["reference"], paths["full"], paths["reference"])
    assert_reference_is_read_only(manifests["smoke"], manifests["smoke_reference"], paths["smoke"], paths["smoke_reference"])
    return paths


def offline_environment(base: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    result = dict(base or os.environ)
    result.update(OFFLINE_ENVIRONMENT)
    result["PYTHONPATH"] = str(PROJECT_ROOT) + (":" + result["PYTHONPATH"] if result.get("PYTHONPATH") else "")
    return result


def enforce_offline_environment() -> Dict[str, str]:
    """Force offline controls even when run is invoked without the launcher."""
    os.environ.update(OFFLINE_ENVIRONMENT)
    return {key: os.environ[key] for key in OFFLINE_ENVIRONMENT}


def query_gpu_state() -> Dict[str, Any]:
    """Read GPU occupancy only; never initializes CUDA or contacts a model."""
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
        check=False, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise OrchestrationError("GPU idle gate cannot query nvidia-smi")
    samples = []
    for raw in result.stdout.splitlines():
        parts = [part.strip() for part in raw.split(",")]
        if len(parts) != 2:
            raise OrchestrationError("GPU idle gate received malformed nvidia-smi output")
        try:
            samples.append({"utilization_percent": int(parts[0]), "used_memory_mib": int(parts[1])})
        except ValueError as exc:
            raise OrchestrationError("GPU idle gate received non-numeric nvidia-smi output") from exc
    if not samples:
        raise OrchestrationError("GPU idle gate found no GPUs")
    return {
        "gpus": samples,
        "max_utilization_percent": max(sample["utilization_percent"] for sample in samples),
        "max_used_memory_mib": max(sample["used_memory_mib"] for sample in samples),
    }


def wait_for_initial_gpu_idle(
    paths: Mapping[str, Path], *,
    utilization_max: int = DEFAULT_GPU_IDLE_UTILIZATION_MAX,
    used_memory_mib_max: int = DEFAULT_GPU_IDLE_USED_MIB_MAX,
    poll_seconds: int = DEFAULT_GPU_IDLE_POLL_SECONDS,
    stable_interval_seconds: int = DEFAULT_GPU_IDLE_STABLE_INTERVAL_SECONDS,
    required_stable_samples: int = DEFAULT_GPU_IDLE_REQUIRED_STABLE_SAMPLES,
) -> Dict[str, Any]:
    """Fail closed until GPU utilization and memory are jointly idle twice."""
    if min(utilization_max, used_memory_mib_max, poll_seconds, stable_interval_seconds) < 0 or required_stable_samples < 2:
        raise OrchestrationError("invalid GPU idle gate configuration")
    stable_samples, checks = 0, 0
    while True:
        state = query_gpu_state()
        checks += 1
        idle = state["max_utilization_percent"] <= utilization_max and state["max_used_memory_mib"] <= used_memory_mib_max
        stable_samples = stable_samples + 1 if idle else 0
        event = append_progress(paths, {
            "event": "GPU_IDLE_CHECK", "check_number": checks, "idle": idle,
            "stable_samples": stable_samples, "required_stable_samples": required_stable_samples,
            "utilization_max_percent": utilization_max, "used_memory_max_mib": used_memory_mib_max, **state,
        })
        if stable_samples >= required_stable_samples:
            return event
        time.sleep(stable_interval_seconds if idle else poll_seconds)


def plan_paths(output_root: Path, mode: str) -> Dict[str, Path]:
    root = output_root / mode
    return {
        "root": root,
        "plan": root / "plan.json",
        "records": root / "records" / "runs",
        "batches": root / "batches",
        "checkpoints": root / "checkpoints",
        "evaluations": root / "evaluations",
        "progress_jsonl": root / "progress.jsonl",
        "progress_latest": root / "progress.latest.json",
        "gate": root / "gate.json",
    }


def manifest_paths(exec_root: Path, mode: str) -> Tuple[Path, Path]:
    frozen = exec_root / "frozen_manifests"
    if mode == "smoke":
        return frozen / "v2_kure_smoke3.json", frozen / "v2_bm25_reference_smoke3.json"
    if mode == "full226":
        return frozen / "v2_kure_full226.json", frozen / "v2_bm25_reference_full226.json"
    raise OrchestrationError("unknown mode: %s" % mode)


def source_snapshot_dict(exec_root: Path) -> Dict[str, str]:
    from runtime.source_snapshot import capture_clean_source_snapshot
    return capture_clean_source_snapshot(exec_root).to_dict()


def make_plan(exec_root: Path, output_root: Path, mode: str) -> Dict[str, Any]:
    primary_path, reference_path = manifest_paths(exec_root, mode)
    primary, reference = read_json(primary_path), read_json(reference_path)
    comparison = assert_reference_is_read_only(primary, reference, primary_path, reference_path)
    entries = list(primary["entries"])
    if mode == "full226":
        if len(entries) != TOTAL_FULL226:
            raise OrchestrationError("full226 plan has wrong number of entries")
        chunks = chunks_for_entries()
        assert_full226_chunks(chunks)
    else:
        if len(entries) != 3 or {int(entry["n_hops"]) for entry in entries} != {1, 2, 3}:
            raise OrchestrationError("smoke plan must be exactly one frozen 1/2/3-hop trio")
        chunks = ((1, 3),)
    return {
        "orchestration_schema_version": "v2.0",
        "created_at_utc": utc_now(),
        "mode": mode,
        "exec_root": str(exec_root),
        "output_root": str(output_root),
        "source_snapshot": source_snapshot_dict(exec_root),
        "primary_manifest": str(primary_path),
        "primary_manifest_sha256": sha256(primary_path),
        "reference_manifest": str(reference_path),
        "reference_manifest_sha256": sha256(reference_path),
        "entry_count": len(entries),
        "chunks": [{"start_ordinal": start, "end_ordinal": end} for start, end in chunks],
        "frozen_configuration": primary["frozen_configuration"],
        "comparison_validation": comparison,
        "runtime": {**EXPECTED_RUNTIME, "warm_persistent": True, "offline_environment": OFFLINE_ENVIRONMENT},
        "execution_policy": {
            "primary_retriever": "kure",
            "bm25_execution": "FORBIDDEN",
            "bm25_reference_use": "READ_ONLY_CONFIGURATION_GUARD",
            "parser_execution": "FORBIDDEN",
            "lf_eval_score_injection": "FORBIDDEN",
            "source_snapshot_assertion": "BEFORE_AND_AFTER_EVERY_CHUNK_AND_QUESTION",
        },
        "smoke_score_not_benchmark_evidence": mode == "smoke",
    }


def _jsonl_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise OrchestrationError("invalid progress JSONL line %d" % number) from exc
            if not isinstance(row, dict):
                raise OrchestrationError("progress JSONL row must be an object")
            rows.append(dict(row))
    return rows


def completed_checkpoints(paths: Mapping[str, Path], plan: Mapping[str, Any]) -> Tuple[int, ...]:
    complete: List[int] = []
    for item in plan["chunks"]:
        end = int(item["end_ordinal"])
        checkpoint = paths["checkpoints"] / ("checkpoint-%03d.json" % end)
        if checkpoint.is_file():
            payload = read_json(checkpoint)
            if payload.get("checkpoint_status") != "PASS" or payload.get("completed_questions") != end:
                raise OrchestrationError("checkpoint is not a completed PASS boundary: %s" % checkpoint)
            complete.append(end)
    return tuple(complete)


def _attempt_prefix(start: int, end: int) -> str:
    return "chunk-%03d-%03d-attempt-" % (start, end)


def _completed_attempt(path: Path, start: int, end: int) -> bool:
    metadata_path, summary_path = path / "metadata.json", path / "summary.jsonl"
    if not metadata_path.is_file() or not summary_path.is_file():
        return False
    metadata = read_json(metadata_path)
    if not metadata.get("completed_at_utc") or metadata.get("start_ordinal") != start or metadata.get("end_ordinal") != end:
        return False
    rows = _jsonl_rows(summary_path)
    return [row.get("ordinal") for row in rows] == list(range(start, end + 1))


def completed_attempt_for(paths: Mapping[str, Path], start: int, end: int) -> Optional[Path]:
    candidates = [
        child for child in paths["batches"].iterdir()
        if child.is_dir() and child.name.startswith(_attempt_prefix(start, end)) and _completed_attempt(child, start, end)
    ] if paths["batches"].is_dir() else []
    if len(candidates) > 1:
        raise OrchestrationError("ambiguous completed chunk attempts for %03d-%03d" % (start, end))
    return candidates[0] if candidates else None


def assert_resume_state(paths: Mapping[str, Path], plan: Mapping[str, Any], resume: bool) -> int:
    exists = paths["root"].exists() or paths["root"].is_symlink()
    if not exists:
        if resume:
            raise OrchestrationError("cannot resume: output root does not exist")
        return 0
    if not paths["root"].is_dir() or not paths["plan"].is_file():
        raise OrchestrationError("output root is not a valid immutable V2 plan")
    existing = read_json(paths["plan"])
    stable_keys = ("mode", "exec_root", "source_snapshot", "primary_manifest_sha256", "reference_manifest_sha256", "chunks", "frozen_configuration")
    if any(existing.get(key) != plan.get(key) for key in stable_keys):
        raise OrchestrationError("existing output plan does not match this immutable source")
    if not resume:
        raise OrchestrationError("refusing to overwrite existing V2 output; use validated --resume")
    completed = completed_checkpoints(paths, plan)
    expected = [int(item["end_ordinal"]) for item in plan["chunks"]]
    if completed != tuple(expected[:len(completed)]):
        raise OrchestrationError("resume is permitted only after contiguous completed chunk boundaries")
    # Incomplete attempts are immutable evidence of an interruption. They are
    # intentionally retained and a new attempt is created after the last PASS.
    for item in plan["chunks"]:
        completed_attempt_for(paths, int(item["start_ordinal"]), int(item["end_ordinal"]))
    return completed[-1] if completed else 0


def initialize_output(paths: Mapping[str, Path], plan: Mapping[str, Any], resume: bool) -> int:
    completed = assert_resume_state(paths, plan, resume)
    if completed:
        return completed
    if paths["root"].exists() or paths["root"].is_symlink():
        return 0
    paths["root"].mkdir(parents=True, exist_ok=False)
    write_json_new(paths["plan"], plan)
    for key in ("records", "batches", "checkpoints", "evaluations"):
        paths[key].mkdir(parents=True, exist_ok=False)
    return 0


def append_progress(paths: Mapping[str, Path], event: Mapping[str, Any]) -> Dict[str, Any]:
    payload = {"recorded_at_utc": utc_now(), **dict(event)}
    paths["progress_jsonl"].parent.mkdir(parents=True, exist_ok=True)
    with paths["progress_jsonl"].open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
    paths["progress_latest"].write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("PROGRESS_EVENT " + json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)
    return payload


def _build_v2_run_args(question: str, question_id: str, configuration: Mapping[str, Any], record_root: Path, snapshot: Mapping[str, str]) -> Any:
    from scripts import run_local_harness
    return run_local_harness.build_frozen_run_args(question, question_id, configuration, record_root, str(snapshot["git_commit"]), str(snapshot["source_manifest_sha256"]))


def _load_questions(dataset_path: Path) -> Dict[str, Mapping[str, Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise OrchestrationError("runtime Python must provide pyarrow for KoBLEX") from exc
    rows = pq.read_table(dataset_path, columns=["id", "background", "question", "n_hops"]).to_pylist()
    return {str(row["id"]): row for row in rows}


def _format_benchmark_input(question: Mapping[str, Any]) -> str:
    background = str(question.get("background") or "").strip()
    prompt = str(question.get("question") or "").strip()
    if not prompt:
        raise OrchestrationError("benchmark question text is empty")
    return "[질문]\n%s" % prompt if not background else "[배경 시나리오]\n%s\n\n[질문]\n%s" % (background, prompt)


def _record_directories(root: Path) -> set[Path]:
    return {path for path in root.iterdir() if path.is_dir()} if root.is_dir() else set()


def _read_result(created: Iterable[Path]) -> Dict[str, Any]:
    directories = sorted(created)
    if len(directories) != 1:
        return {"record_directory_count": len(directories), "status": "EXECUTION_FAILURE", "errors": ["NO_UNIQUE_RECORD"]}
    result_file = directories[0] / "result.json"
    if not result_file.is_file():
        return {"record_directory": str(directories[0]), "status": "EXECUTION_FAILURE", "errors": ["NO_FINAL_RESULT"]}
    payload = read_json(result_file)
    return {
        "record_directory": str(directories[0]),
        "status": payload.get("status"),
        "termination_reason": payload.get("termination_reason"),
        "abstention_reason": payload.get("abstention_reason"),
        "errors": payload.get("errors", []),
        "end_to_end_latency_ms": payload.get("end_to_end_latency_ms"),
        "run_id": payload.get("run_id"),
    }


def entries_for_chunk(primary: Mapping[str, Any], start: int, end: int) -> List[Dict[str, Any]]:
    entries = [dict(entry) for entry in primary.get("entries", []) if start <= int(entry.get("ordinal", 0)) <= end]
    if [int(entry["ordinal"]) for entry in entries] != list(range(start, end + 1)):
        raise OrchestrationError("frozen execution entries are not contiguous for chunk %03d-%03d" % (start, end))
    return entries


def execute_chunk(exec_root: Path, paths: Mapping[str, Path], plan: Mapping[str, Any], start: int, end: int, resources: Any, questions: Mapping[str, Mapping[str, Any]]) -> Tuple[Path, bool]:
    """Run one immutable KURE attempt; abandoned attempts are never overwritten."""
    from runtime.source_snapshot import assert_source_snapshot_unchanged, capture_clean_source_snapshot
    from scripts import run_local_harness

    primary = read_json(Path(str(plan["primary_manifest"])))
    configuration = dict(primary["frozen_configuration"])
    assert_kure_only(configuration)
    snapshot = capture_clean_source_snapshot(exec_root)
    if snapshot.to_dict() != dict(plan["source_snapshot"]):
        raise OrchestrationError("source snapshot changed before chunk %03d-%03d" % (start, end))
    entries = entries_for_chunk(primary, start, end)
    attempt_id = uuid.uuid4().hex
    chunk_dir = paths["batches"] / (_attempt_prefix(start, end) + attempt_id)
    chunk_dir.mkdir(parents=True, exist_ok=False)
    chunk_manifest = deepcopy(primary)
    chunk_manifest["name"] = "%s-chunk-%03d-%03d-attempt-%s" % (primary.get("name", PRIMARY_FROZEN_NAME), start, end, attempt_id)
    chunk_manifest["entries"] = entries
    selection = dict(chunk_manifest.get("selection") or {})
    selection.update({"method": "immutable V2 execution chunk %03d-%03d" % (start, end), "entry_count": len(entries), "ordinal_start": start, "ordinal_end": end})
    chunk_manifest["selection"] = selection
    write_json_new(chunk_dir / "manifest.json", chunk_manifest)
    metadata: Dict[str, Any] = {
        "batch_id": chunk_dir.name,
        "attempt_id": attempt_id,
        "started_at_utc": utc_now(),
        "entry_count": len(entries),
        "start_ordinal": start,
        "end_ordinal": end,
        "configuration": configuration,
        "source_snapshot": snapshot.to_dict(),
        "batch_manifest_sha256": sha256(chunk_dir / "manifest.json"),
        "record_root": str(paths["records"]),
        "execution_mode": "warm_persistent_kure_only",
        "bm25_execution": "FORBIDDEN",
        "lf_eval_score_injection": "FORBIDDEN",
    }
    write_json_new(chunk_dir / "metadata.json", metadata)
    rows: List[Dict[str, Any]] = []
    has_failure = False
    for entry in entries:
        assert_source_snapshot_unchanged(exec_root, snapshot)
        ordinal, question_id = int(entry["ordinal"]), str(entry["question_id"])
        question = questions.get(question_id)
        if question is None or int(question.get("n_hops", 0)) != int(entry["n_hops"]):
            raise OrchestrationError("frozen question is absent or hop-mismatched: %s" % question_id)
        before = _record_directories(paths["records"])
        log_path = chunk_dir / ("%03d_%s.log" % (ordinal, question_id))
        started = utc_now()
        exit_code = 1
        with log_path.open("x", encoding="utf-8") as log:
            try:
                run_args = _build_v2_run_args(_format_benchmark_input(question), question_id, configuration, paths["records"], snapshot.to_dict())
                execution = run_local_harness.run_question(run_args, source_snapshot=snapshot, resources=resources)
                print(execution.rendered_output, file=log)
                exit_code = execution.exit_code
            except Exception:
                traceback.print_exc(file=log)
        assert_source_snapshot_unchanged(exec_root, snapshot)
        outcome = _read_result(_record_directories(paths["records"]) - before)
        status = outcome.get("status")
        if status not in NORMAL_STATUSES:
            has_failure = True
        rows.append({
            "ordinal": ordinal,
            "source_ordinal": int(entry.get("source_ordinal", ordinal)),
            "question_id": question_id,
            "n_hops": int(entry["n_hops"]),
            "started_at_utc": started,
            "completed_at_utc": utc_now(),
            "exit_code": exit_code,
            "log_file": str(log_path),
            **outcome,
        })
    write_jsonl_new(chunk_dir / "summary.jsonl", rows)
    assert_source_snapshot_unchanged(exec_root, snapshot)
    metadata["completed_at_utc"] = utc_now()
    metadata["has_execution_failure"] = has_failure
    (chunk_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return chunk_dir, has_failure


def _metric_projection(aggregate: Mapping[str, Any]) -> Dict[str, Any]:
    provision = dict(aggregate.get("provision") or {})
    macro, micro = dict(provision.get("macro") or {}), dict(provision.get("micro") or {})
    complete, exact = dict(provision.get("complete_evidence") or {}), dict(provision.get("exact_match") or {})
    quality, outcomes = dict(aggregate.get("answer_quality") or {}), dict(aggregate.get("outcomes") or {})
    latency = dict(dict(aggregate.get("efficiency") or {}).get("end_to_end_latency_ms") or {})
    return {
        "provision_macro_precision": macro.get("precision"),
        "provision_macro_recall": macro.get("recall"),
        "provision_macro_f1": macro.get("f1"),
        "provision_micro_f1": micro.get("f1"),
        "complete_evidence_count": complete.get("count"),
        "complete_evidence_rate": complete.get("rate"),
        "provision_exact_match_count": exact.get("count"),
        "provision_exact_match_rate": exact.get("rate"),
        "token_f1_end_to_end": quality.get("token_f1_at_800", {}).get("end_to_end") if isinstance(quality.get("token_f1_at_800"), Mapping) else None,
        "token_f1_answered_only": quality.get("token_f1_at_800", {}).get("answered_only") if isinstance(quality.get("token_f1_at_800"), Mapping) else None,
        "token_f1_candidate": quality.get("candidate_token_f1_at_800", {}).get("all_outcomes") if isinstance(quality.get("candidate_token_f1_at_800"), Mapping) else None,
        "answer_count": quality.get("answer_count"),
        "abstain_count": quality.get("abstain_count"),
        "execution_failure_count": quality.get("execution_failure_count"),
        "outcome_counts": {name: value.get("count") for name, value in outcomes.items() if isinstance(value, Mapping)},
        "citation_integrity": aggregate.get("citation_integrity"),
        "mean_latency_ms": latency.get("mean"),
        "median_latency_ms": latency.get("median"),
        "p95_latency_ms": latency.get("p95"),
    }


def evaluate_checkpoint(exec_root: Path, paths: Mapping[str, Path], plan: Mapping[str, Any], chunk_dirs: Sequence[Path], completed: int, runtime_python: Path) -> Dict[str, Any]:
    """Evaluate completed immutable attempts; failed evaluator attempts remain auditable."""
    from scripts.materialize_checkpoint_batch import materialize_cumulative_batch

    final_checkpoint = paths["checkpoints"] / ("checkpoint-%03d.json" % completed)
    if final_checkpoint.exists():
        payload = read_json(final_checkpoint)
        if payload.get("checkpoint_status") != "PASS":
            raise OrchestrationError("final checkpoint is not PASS: %s" % final_checkpoint)
        return payload
    attempt_id = uuid.uuid4().hex
    checkpoint_batch = paths["checkpoints"] / ("batch-%03d-attempt-%s" % (completed, attempt_id))
    evaluation_dir = paths["evaluations"] / ("checkpoint-%03d-attempt-%s" % (completed, attempt_id))
    materialize_cumulative_batch(chunk_dirs, checkpoint_batch, name="%s-checkpoint-%03d" % (PRIMARY_FROZEN_NAME, completed), through_ordinal=completed)
    command = [str(runtime_python), str(exec_root / "scripts/evaluate_dev_runs.py"), "--batch-dir", str(checkpoint_batch), "--output-dir", str(evaluation_dir), "--require-stage-provenance"]
    assert_no_external_score_injection(command)
    started = time.monotonic()
    result = subprocess.run(command, cwd=exec_root, env=offline_environment(), check=False, text=True, capture_output=True)
    (paths["checkpoints"] / ("evaluator-%03d-attempt-%s.stdout.log" % (completed, attempt_id))).write_text(result.stdout, encoding="utf-8")
    (paths["checkpoints"] / ("evaluator-%03d-attempt-%s.stderr.log" % (completed, attempt_id))).write_text(result.stderr, encoding="utf-8")
    aggregate_path = evaluation_dir / "aggregate.json"
    aggregate = read_json(aggregate_path) if aggregate_path.is_file() else {}
    rows = _jsonl_rows(checkpoint_batch / "summary.jsonl")
    abnormal = [str(row.get("question_id")) for row in rows if row.get("status") not in NORMAL_STATUSES]
    unexpected_exit = [
        str(row.get("question_id")) for row in rows
        if (row.get("status") == "ANSWER" and row.get("exit_code") not in (0, None))
        or (row.get("status") == "ABSTAIN" and row.get("exit_code") not in (0, 1, None))
    ]
    recorded_errors = {str(row.get("question_id")): row.get("errors") for row in rows if row.get("errors")}
    citation = dict(aggregate.get("citation_integrity") or {})
    provenance_missing = [
        name for name in ("first_stage_at_100", "rrf_at_100", "bge_at_10", "bge_at_20", "bge_at_30")
        if (aggregate.get("retrieval", {}).get(name, {}) if isinstance(aggregate.get("retrieval"), Mapping) else {}).get("available") is not True
    ]
    errors = []
    if result.returncode:
        errors.append("evaluator_exit=%d" % result.returncode)
    if abnormal:
        errors.append("abnormal_outcomes=%d" % len(abnormal))
    if unexpected_exit:
        errors.append("unexpected_exit=%d" % len(unexpected_exit))
    if recorded_errors:
        errors.append("recorded_errors=%d" % len(recorded_errors))
    if citation.get("attempted", 0) and citation.get("pass_rate") != 1.0:
        errors.append("citation_integrity=%s" % citation.get("pass_rate"))
    if provenance_missing:
        errors.append("stage_provenance_missing=" + ",".join(provenance_missing))
    projection = _metric_projection(aggregate)
    mean_latency_ms = projection.get("mean_latency_ms")
    remaining_ms = (TOTAL_FULL226 - completed) * float(mean_latency_ms) if isinstance(mean_latency_ms, (int, float)) and plan["mode"] == "full226" else None
    event = {
        "event": "FULL226_COMPLETED" if plan["mode"] == "full226" and completed == TOTAL_FULL226 else "CHECKPOINT_COMPLETED",
        "checkpoint_status": "PASS" if not errors else "ERRORS_FOUND",
        "completed_questions": completed,
        "total_questions": int(plan["entry_count"]),
        "checkpoint_range": [int(chunk_dirs[-1].name.split("-")[1]), int(chunk_dirs[-1].name.split("-")[2])],
        "validation_errors": errors,
        "abnormal_question_ids": abnormal,
        "unexpected_exit_question_ids": unexpected_exit,
        "recorded_errors": recorded_errors,
        "stage_provenance_missing": provenance_missing,
        "metrics": projection,
        "evaluator_command": command,
        "evaluator_elapsed_seconds": time.monotonic() - started,
        "batch_directory": str(checkpoint_batch),
        "evaluation_directory": str(evaluation_dir),
        "remaining_eta_ms": remaining_ms,
        "remaining_eta_seconds": remaining_ms / 1000.0 if remaining_ms is not None else None,
        "remaining_eta_utc": (datetime.now(timezone.utc) + timedelta(seconds=remaining_ms / 1000.0)).isoformat() if remaining_ms is not None else None,
        "bm25_execution": "FORBIDDEN",
        "lf_eval_score_injection": "FORBIDDEN",
    }
    if errors:
        write_json_new(paths["checkpoints"] / ("checkpoint-%03d-attempt-%s.json" % (completed, attempt_id)), event)
    else:
        write_json_new(final_checkpoint, event)
    return event


def smoke_gate(event: Mapping[str, Any]) -> Dict[str, Any]:
    metrics = dict(event.get("metrics") or {})
    reasons = list(event.get("validation_errors") or [])
    if metrics.get("answer_count") is None or int(metrics.get("answer_count") or 0) < 1:
        reasons.append("answer_count_below_one")
    if metrics.get("execution_failure_count") != 0:
        reasons.append("execution_failure_count")
    citation = metrics.get("citation_integrity")
    if not isinstance(citation, Mapping) or int(citation.get("attempted") or 0) < 1 or citation.get("pass_rate") != 1.0:
        reasons.append("citation_integrity")
    if event.get("stage_provenance_missing"):
        reasons.append("stage_provenance")
    return {
        "stage": "operational_smoke3",
        "status": "PASS" if not reasons else "FAIL",
        "score_is_benchmark_evidence": False,
        "required_checks": ["schema_execution", "at_least_one_answer_s3_path", "citation_integrity", "stage_provenance", "zero_execution_failures", "evaluator_success"],
        "reasons": sorted(set(reasons)),
        "source_checkpoint": dict(event),
    }


def _finished_smoke_gate(paths: Mapping[str, Path], completed: int) -> Optional[int]:
    if completed != 3:
        return None
    if paths["gate"].is_file():
        return 0 if read_json(paths["gate"]).get("status") == "PASS" else 1
    checkpoint = read_json(paths["checkpoints"] / "checkpoint-003.json")
    gate = smoke_gate(checkpoint)
    write_json_new(paths["gate"], gate)
    append_progress(paths, {"event": "SMOKE_GATE_RECOVERED", **gate})
    return 0 if gate["status"] == "PASS" else 1


def _finished_full_gate(paths: Mapping[str, Path], completed: int) -> Optional[int]:
    if completed != TOTAL_FULL226:
        return None
    if paths["gate"].is_file():
        return 0 if read_json(paths["gate"]).get("status") == "PASS" else 1
    checkpoint = read_json(paths["checkpoints"] / "checkpoint-%03d.json" % TOTAL_FULL226)
    gate = {
        "stage": "full226",
        "status": "PASS" if checkpoint.get("checkpoint_status") == "PASS" else "FAIL",
        "completed_questions": TOTAL_FULL226,
        "bm25_execution": "FORBIDDEN",
        "parser_execution": "FORBIDDEN",
        "lf_eval_score_injection": "FORBIDDEN",
        "final_checkpoint": checkpoint,
    }
    write_json_new(paths["gate"], gate)
    append_progress(paths, {"event": "FULL_GATE_RECOVERED", **gate})
    return 0 if gate["status"] == "PASS" else 1


def execute_plan(
    exec_root: Path, output_root: Path, mode: str, runtime_python: Path, resume: bool, *,
    skip_gpu_idle_gate: bool = False, gpu_utilization_max: int = DEFAULT_GPU_IDLE_UTILIZATION_MAX,
    gpu_used_memory_mib_max: int = DEFAULT_GPU_IDLE_USED_MIB_MAX, gpu_poll_seconds: int = DEFAULT_GPU_IDLE_POLL_SECONDS,
    gpu_stable_interval_seconds: int = DEFAULT_GPU_IDLE_STABLE_INTERVAL_SECONDS,
    warm_state: Optional[Dict[str, Any]] = None,
) -> int:
    if not os.environ.get("TMUX"):
        raise OrchestrationError("execution requires a detached tmux session")
    enforce_offline_environment()
    if not runtime_python.is_file():
        raise OrchestrationError("workspace runtime Python is unavailable: %s" % runtime_python)
    plan = make_plan(exec_root, output_root, mode)
    paths = plan_paths(output_root, mode)
    completed_before = initialize_output(paths, plan, resume)
    if mode == "full226":
        smoke = read_json(plan_paths(output_root, "smoke")["gate"]) if plan_paths(output_root, "smoke")["gate"].is_file() else {}
        if smoke.get("status") != "PASS":
            raise OrchestrationError("full226 cannot start until the isolated smoke3 gate passes")
    if mode == "smoke":
        finished = _finished_smoke_gate(paths, completed_before)
        if finished is not None:
            return finished
    if mode == "full226":
        finished = _finished_full_gate(paths, completed_before)
        if finished is not None:
            return finished
    append_progress(paths, {"event": "RUN_STARTED" if not completed_before else "RUN_RESUMED", "completed_questions": completed_before, "source_snapshot": plan["source_snapshot"], "offline_environment": OFFLINE_ENVIRONMENT})
    if mode == "smoke" and not completed_before:
        if skip_gpu_idle_gate:
            append_progress(paths, {"event": "GPU_IDLE_GATE_BYPASSED", "reason": "explicit_flag"})
        else:
            wait_for_initial_gpu_idle(paths, utilization_max=gpu_utilization_max, used_memory_mib_max=gpu_used_memory_mib_max, poll_seconds=gpu_poll_seconds, stable_interval_seconds=gpu_stable_interval_seconds)
    primary = read_json(Path(str(plan["primary_manifest"])))
    dataset_path = exec_root / str(primary["source_dataset"]["path"])
    if sha256(dataset_path) != primary["source_dataset"]["sha256"]:
        raise OrchestrationError("KoBLEX dataset hash does not match frozen manifest")
    state = warm_state if warm_state is not None else {}
    if "preflight" not in state:
        state["preflight"] = preflight(exec_root, mode, runtime_python)
        append_progress(paths, {"event": "ARTIFACT_PREFLIGHT_PASS", "preflight": state["preflight"]})
        state["ollama_readiness"] = check_local_ollama_readiness(primary["frozen_configuration"])
        append_progress(paths, {"event": "OLLAMA_NON_GENERATIVE_READY", "readiness": state["ollama_readiness"]})
    # Imports below this line are the only retrieval/model-capable path.
    from scripts import run_local_harness
    from runtime.source_snapshot import assert_source_snapshot_unchanged, capture_clean_source_snapshot
    snapshot = capture_clean_source_snapshot(exec_root)
    if {"resources", "questions", "snapshot"}.issubset(state):
        if state["snapshot"].to_dict() != snapshot.to_dict():
            raise OrchestrationError("warm persistent state does not match the immutable source snapshot")
        resources, questions = state["resources"], state["questions"]
    else:
        questions = _load_questions(dataset_path)
        bootstrap_args = _build_v2_run_args("", "", primary["frozen_configuration"], paths["records"], snapshot.to_dict())
        resources = run_local_harness.PersistentHarnessResources(bootstrap_args)
        state.update({"resources": resources, "questions": questions, "snapshot": snapshot})
    all_chunks = [(int(item["start_ordinal"]), int(item["end_ordinal"])) for item in plan["chunks"]]
    prior_chunks: List[Path] = []
    for start, end in all_chunks:
        if end <= completed_before:
            attempt = completed_attempt_for(paths, start, end)
            if attempt is None:
                raise OrchestrationError("PASS checkpoint lacks its immutable completed attempt: %03d-%03d" % (start, end))
            prior_chunks.append(attempt)
            continue
        assert_source_snapshot_unchanged(exec_root, snapshot)
        attempt = completed_attempt_for(paths, start, end)
        if attempt is None:
            attempt, failed = execute_chunk(exec_root, paths, plan, start, end, resources, questions)
            append_progress(paths, {"event": "CHUNK_EXECUTED", "range": [start, end], "completed_questions": end, "chunk_directory": str(attempt), "chunk_execution_failure": failed})
        else:
            append_progress(paths, {"event": "CHUNK_REUSED_FOR_EVALUATOR_RETRY", "range": [start, end], "chunk_directory": str(attempt)})
        prior_chunks.append(attempt)
        checkpoint = evaluate_checkpoint(exec_root, paths, plan, prior_chunks, end, runtime_python)
        append_progress(paths, checkpoint)
        if checkpoint["checkpoint_status"] != "PASS":
            return 1
    final_checkpoint = read_json(paths["checkpoints"] / ("checkpoint-%03d.json" % int(plan["entry_count"])))
    if mode == "smoke":
        gate = smoke_gate(final_checkpoint)
        write_json_new(paths["gate"], gate)
        append_progress(paths, {"event": "SMOKE_GATE", **gate})
        return 0 if gate["status"] == "PASS" else 1
    gate = {"stage": "full226", "status": "PASS" if final_checkpoint.get("checkpoint_status") == "PASS" else "FAIL", "completed_questions": TOTAL_FULL226, "bm25_execution": "FORBIDDEN", "parser_execution": "FORBIDDEN", "lf_eval_score_injection": "FORBIDDEN", "final_checkpoint": final_checkpoint}
    write_json_new(paths["gate"], gate)
    append_progress(paths, {"event": "RUN_COMPLETED", **gate})
    return 0 if gate["status"] == "PASS" else 1


def execute_smoke_then_full(
    exec_root: Path, output_root: Path, runtime_python: Path, *, resume: bool = False, skip_gpu_idle_gate: bool = False,
    gpu_utilization_max: int = DEFAULT_GPU_IDLE_UTILIZATION_MAX, gpu_used_memory_mib_max: int = DEFAULT_GPU_IDLE_USED_MIB_MAX,
    gpu_poll_seconds: int = DEFAULT_GPU_IDLE_POLL_SECONDS, gpu_stable_interval_seconds: int = DEFAULT_GPU_IDLE_STABLE_INTERVAL_SECONDS,
) -> int:
    """One detached flow: resume smoke safely, then continue immediately into full226."""
    warm_state: Dict[str, Any] = {}
    smoke_exists = plan_paths(output_root, "smoke")["root"].exists()
    smoke_exit = execute_plan(exec_root, output_root, "smoke", runtime_python, resume=resume if smoke_exists else False, skip_gpu_idle_gate=skip_gpu_idle_gate, gpu_utilization_max=gpu_utilization_max, gpu_used_memory_mib_max=gpu_used_memory_mib_max, gpu_poll_seconds=gpu_poll_seconds, gpu_stable_interval_seconds=gpu_stable_interval_seconds, warm_state=warm_state)
    if smoke_exit != 0:
        return smoke_exit
    full_exists = plan_paths(output_root, "full226")["root"].exists()
    return execute_plan(exec_root, output_root, "full226", runtime_python, resume=resume if full_exists else False, warm_state=warm_state)


def preflight(exec_root: Path, mode: str, runtime_python: Path) -> Dict[str, Any]:
    """CPU-only file/hash preflight. It never contacts Ollama or loads KURE."""
    if not runtime_python.is_file():
        raise OrchestrationError("workspace runtime Python is unavailable: %s" % runtime_python)
    primary_path, reference_path = manifest_paths(exec_root, mode)
    primary, reference = read_json(primary_path), read_json(reference_path)
    comparison = assert_reference_is_read_only(primary, reference, primary_path, reference_path)
    verify_kure_artifacts(primary["frozen_configuration"], exec_root)
    model = primary["frozen_configuration"].get("model_provenance")
    if not isinstance(model, Mapping):
        raise OrchestrationError("model provenance is missing")
    for key, expected_value in QWEN_MODEL_PROVENANCE.items():
        if model.get(key) != expected_value:
            raise OrchestrationError("frozen Qwen model provenance mismatch: %s" % key)
    blob = Path(str(model.get("ollama_model_blob") or ""))
    if not blob.is_file():
        raise OrchestrationError("offline Qwen model blob is missing: %s" % blob)
    expected = str(model.get("sha256") or "")
    if len(expected) != 64 or sha256(blob) != expected:
        raise OrchestrationError("offline Qwen model blob hash mismatch")
    return {"status": "PASS", "mode": mode, "runtime_python": str(runtime_python), "comparison": comparison, "offline_environment": OFFLINE_ENVIRONMENT, "model_blob": str(blob), "model_blob_sha256": expected}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("bootstrap", "run", "preflight"))
    parser.add_argument("--exec-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--mode", choices=("smoke", "full226", "all"), default="smoke")
    parser.add_argument("--primary-source-manifest", type=Path)
    parser.add_argument("--reference-source-manifest", type=Path)
    parser.add_argument("--runtime-python", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-gpu-idle-gate", action="store_true", help="explicitly bypass the initial smoke-only GPU idle gate")
    parser.add_argument("--gpu-utilization-max", type=int, default=DEFAULT_GPU_IDLE_UTILIZATION_MAX)
    parser.add_argument("--gpu-used-memory-mib-max", type=int, default=DEFAULT_GPU_IDLE_USED_MIB_MAX)
    parser.add_argument("--gpu-poll-seconds", type=int, default=DEFAULT_GPU_IDLE_POLL_SECONDS)
    parser.add_argument("--gpu-stable-interval-seconds", type=int, default=DEFAULT_GPU_IDLE_STABLE_INTERVAL_SECONDS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    exec_root = args.exec_root.resolve()
    runtime_python = (args.runtime_python or exec_root / ".venv/bin/python").resolve()
    if args.command == "bootstrap":
        if args.output_root is not None or not args.primary_source_manifest or not args.reference_source_manifest:
            raise OrchestrationError("bootstrap requires exactly both source manifests and no output root")
        paths = write_v2_manifests(exec_root, args.primary_source_manifest.resolve(), args.reference_source_manifest.resolve())
        print(json.dumps({key: str(value) for key, value in paths.items()}, ensure_ascii=False, sort_keys=True))
        return 0
    if args.output_root is None:
        raise OrchestrationError("run/preflight require --output-root")
    output_root = args.output_root.resolve()
    if args.command == "preflight":
        if args.mode == "all":
            raise OrchestrationError("preflight requires smoke or full226 mode")
        print(json.dumps(preflight(exec_root, args.mode, runtime_python), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    plans = [make_plan(exec_root, output_root, name) for name in (("smoke", "full226") if args.mode == "all" else (args.mode,))]
    if args.dry_run:
        print(json.dumps({"status": "DRY_RUN", "plans": plans, "runtime_python": str(runtime_python), "would_require_tmux": True, "gpu_idle_gate": {"smoke_only": True, "bypass_requested": args.skip_gpu_idle_gate, "utilization_max": args.gpu_utilization_max, "used_memory_mib_max": args.gpu_used_memory_mib_max, "poll_seconds": args.gpu_poll_seconds, "stable_interval_seconds": args.gpu_stable_interval_seconds, "required_stable_samples": DEFAULT_GPU_IDLE_REQUIRED_STABLE_SAMPLES}}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.mode == "all":
        return execute_smoke_then_full(exec_root, output_root, runtime_python, resume=args.resume, skip_gpu_idle_gate=args.skip_gpu_idle_gate, gpu_utilization_max=args.gpu_utilization_max, gpu_used_memory_mib_max=args.gpu_used_memory_mib_max, gpu_poll_seconds=args.gpu_poll_seconds, gpu_stable_interval_seconds=args.gpu_stable_interval_seconds)
    return execute_plan(exec_root, output_root, args.mode, runtime_python, args.resume, skip_gpu_idle_gate=args.skip_gpu_idle_gate, gpu_utilization_max=args.gpu_utilization_max, gpu_used_memory_mib_max=args.gpu_used_memory_mib_max, gpu_poll_seconds=args.gpu_poll_seconds, gpu_stable_interval_seconds=args.gpu_stable_interval_seconds)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OrchestrationError as exc:
        print("orchestration error: %s" % exc, file=sys.stderr)
        raise SystemExit(2)
