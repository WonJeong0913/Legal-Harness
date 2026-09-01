#!/usr/bin/env python3
"""Prepare and run the isolated C02 bm25s first-stage ablation.

This module is intentionally separate from ``v2_kure_orchestration.py``.
The latter remains KURE-only and keeps its historical BM25 reference manifests
read-only.  The only executable comparison created here is a new, explicitly
labelled C02 condition whose first-stage retriever is ParSeR-compatible
``bm25s.BM25``; all C02 policy, skill, BGE, budget, and model settings remain
identical to the frozen KURE manifest.

``bootstrap``, ``preflight``, and ``smoke-search`` are CPU-only.  Full226
execution is deliberately behind an explicit action and is not started by any
of those control-plane commands.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback
from typing import Any, Dict, Iterable, List, Mapping, Sequence
from urllib.error import URLError
from urllib.request import urlopen
import uuid


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from retrieval.persistent import (  # noqa: E402
    Bm25sParSeRFirstStageSearcher,
    PARSER_BM25S_TOP_K,
    _bm25s_corpus_mapping_sha256,
    load_bm25s_parser_rows,
)
from runtime.comparison_guard import (  # noqa: E402
    resolve_frozen_configuration,
    validate_bm25s_first_stage_ablation,
)
from runtime.source_snapshot import (  # noqa: E402
    assert_source_snapshot_unchanged,
    capture_clean_source_snapshot,
)


C02_SOURCE_COMMIT = "c02e2818ad54e9d5a1a9bd02b604e987192bb244"
C02_SOURCE_TREE = "9fcb0ebceb0b3d96955f1626f2c952a457be930f"
TOTAL_FULL226 = 226
DEFAULT_ASSET_ROOT = Path("/workspace/Legal-Harness")
PRIMARY_MANIFEST = PROJECT_ROOT / "frozen_manifests/v2_kure_full226.json"
PROTECTED_REFERENCE_MANIFEST = PROJECT_ROOT / "frozen_manifests/v2_bm25_reference_full226.json"
FULL_MANIFEST = PROJECT_ROOT / "frozen_manifests/c02_bm25s_ablation_full226.json"
SMOKE_MANIFEST = PROJECT_ROOT / "frozen_manifests/c02_bm25s_ablation_smoke1.json"
LLM_SMOKE_MANIFEST = PROJECT_ROOT / "frozen_manifests/c02_bm25s_ablation_smoke3.json"
METADATA_PATH = PROJECT_ROOT / "frozen_manifests/c02_bm25s_ablation_metadata.json"
EXPECTED_ASSET_RELATIVE_PATHS = {
    "qa_parquet": Path("data/koblex/qa/test-00000-of-00001.parquet"),
    "statute_parquet": Path("data/koblex/statute/corpus-00000-of-00001.parquet"),
    "normalized_corpus": Path("data/koblex/normalized/statute.jsonl"),
}
ALLOWED_CONFIGURATION_DIFFERENCES = {
    "condition",
    "retriever",
    "retriever_provenance",
}
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
PARSER_PARITY_FIXTURES = (
    {
        "query": "운송계약 손해배상채권 소멸시효 기간 기산점 [원문 맥락] 이에 따라 을은 상품이 인도된 날로부터 언제까지 소송을 제기할 수 있는지를 고민하게 되었다. 을은 갑에 대한 손해배상청구권을 어느 시점까지 행사할 수 있는가?",
        "query_sha256": "1ca9aa149bcd8a44199db402e57b202d69673a7c0264dce28ef0ad9ebccb1a38",
        "saved_c02_record": "a55bac04-a675-4171-add2-f8f35295201f",
        "legacy_external_top100_index_sha256": "91072d93dfa6d998c726f0658f58b6f33e41dc2118b1f45c4708c08ed1127fd5",
        "canonical_source_index_list_sha256": "ff0562c5a21c6689ea489ff3328e1b957dde8bb0bbe36c09fa431b07dd24e223",
    },
    {
        "query": "형법 야간 주거 침입 절도죄 처벌 규정 [원문 맥락] 을은 그 사실을 다음 날 아침에 발견하고 경찰에 신고하였다. 갑이 야간에 을의 집에 몰래 들어가 금목걸이를 훔쳤다면 어떤 처벌을 받을 수 있는가?",
        "query_sha256": "a4cd2fcaf04fa07b2768be8a575a1c6ff9b02f6c3bf2d4f92afed8192a30f50f",
        "saved_c02_record": "9efd3e25-9c81-475e-be08-bd12c5807f41",
        "legacy_external_top100_index_sha256": "cd5b9966fcc6ceb6b60d7ecc6686eba7dc1fe5ab117c09ca789f22cc079093dd",
        "canonical_source_index_list_sha256": "07b123db0c1ca3ca079451525c73f6dda3dfae019ca1fb486bdbabe756f84eed",
    },
    {
        "query": "선거권 상실 또는 정지 사유 징역형 수감 [원문 맥락] 선거일이 다가오자 갑은 자신의 선거권을 행사할 수 있는지 궁금해졌다. 갑은 선거일에 자신의 선거권을 행사할 수 있는가?",
        "query_sha256": "36c9c76c16af89409c59ac41216a147994fe7c87b43d7220d143992a9b3d5a70",
        "saved_c02_record": "e5c3d9f7-d32a-4a50-94ff-497283b1ed94",
        "legacy_external_top100_index_sha256": "686d1b67f3597746a676a6c604ed4f1ef20c3ce098452ac16b32da0dc2a4e90d",
        "canonical_source_index_list_sha256": "5323a65ddf53d1ae0f519a39dc00e103f79fa0b95e5e0767557e20fc39f2a49e",
    },
)


class C02Bm25sAblationError(RuntimeError):
    """The isolated ablation cannot prove its immutable prerequisites."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C02Bm25sAblationError("invalid JSON artifact: %s" % path) from exc
    if not isinstance(value, dict):
        raise C02Bm25sAblationError("JSON artifact must be an object: %s" % path)
    return value


def write_json_new_or_verify(path: Path, value: Mapping[str, Any]) -> None:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise C02Bm25sAblationError("refusing to overwrite frozen artifact: %s" % path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")


def resolve_asset_root(asset_root: Path) -> Path:
    """Permit only the declared fixed shared asset root, never path traversal."""
    try:
        resolved = asset_root.resolve(strict=True)
        expected = DEFAULT_ASSET_ROOT.resolve(strict=True)
    except OSError as exc:
        raise C02Bm25sAblationError("C02 read-only asset root is unavailable") from exc
    if resolved != expected:
        raise C02Bm25sAblationError(
            "C02 bm25s ablation permits only the declared asset root: %s" % expected
        )
    return resolved


def asset_path(asset_root: Path, relative_path: Path) -> Path:
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise C02Bm25sAblationError("asset path must be a safe relative path")
    candidate = (asset_root / relative_path).resolve()
    if asset_root not in candidate.parents or not candidate.is_file():
        raise C02Bm25sAblationError("declared C02 asset is unavailable: %s" % relative_path)
    return candidate


def load_asset_provenance(asset_root: Path) -> Dict[str, Any]:
    root = resolve_asset_root(asset_root)
    paths = {
        key: asset_path(root, relative)
        for key, relative in EXPECTED_ASSET_RELATIVE_PATHS.items()
    }
    rows = load_bm25s_parser_rows(paths["statute_parquet"], paths["normalized_corpus"])
    if len(rows) != 233544:
        raise C02Bm25sAblationError(
            "C02 bm25s corpus must contain 233544 provisions, found %d" % len(rows)
        )
    return {
        "asset_root": str(root),
        "assets": {
            key: {
                "path": str(relative),
                "sha256": sha256(paths[key]),
            }
            for key, relative in EXPECTED_ASSET_RELATIVE_PATHS.items()
        },
        "documents": len(rows),
        "parquet_to_provision_id_mapping_sha256": _bm25s_corpus_mapping_sha256(rows),
        "parquet_to_provision_id_mapping": (
            "positional parquet row to normalized provision_id; duplicate parquet index "
            "values remain distinct and are never first-stage deduplicated"
        ),
    }


def assert_reference_manifest_read_only() -> Dict[str, Any]:
    reference = read_json(PROTECTED_REFERENCE_MANIFEST)
    configuration = dict(reference.get("frozen_configuration") or {})
    if configuration.get("retriever") != "bm25":
        raise C02Bm25sAblationError("protected V2 BM25 reference is not recognised")
    purpose = str(reference.get("purpose") or "")
    if "prohibited" not in purpose.lower() and "never" not in purpose.lower():
        raise C02Bm25sAblationError("protected V2 BM25 reference lacks no-execution policy")
    return {
        "path": str(PROTECTED_REFERENCE_MANIFEST.relative_to(PROJECT_ROOT)),
        "sha256": sha256(PROTECTED_REFERENCE_MANIFEST),
        "execution_policy": "MUST_NEVER_BE_EXECUTED",
    }


def assert_retriever_only_configuration(
    c02_configuration: Mapping[str, Any],
    ablation_configuration: Mapping[str, Any],
) -> None:
    source = resolve_frozen_configuration(c02_configuration)
    ablation = resolve_frozen_configuration(ablation_configuration)
    differences = sorted(
        key
        for key in set(source) | set(ablation)
        if source.get(key) != ablation.get(key)
    )
    if set(differences) - ALLOWED_CONFIGURATION_DIFFERENCES:
        raise C02Bm25sAblationError(
            "C02 bm25s configuration differs outside retriever-only fields: %s"
            % ", ".join(differences)
        )
    if ablation.get("retriever") != "bm25s_parser":
        raise C02Bm25sAblationError("C02 bm25s manifest has the wrong retriever")
    if source.get("retriever") != "kure":
        raise C02Bm25sAblationError("C02 basis manifest is not KURE")


def bm25s_retriever_provenance(asset_provenance: Mapping[str, Any]) -> Dict[str, Any]:
    try:
        import bm25s
    except ImportError as exc:
        raise C02Bm25sAblationError("bm25s must be installed to freeze the ablation") from exc
    assets = dict(asset_provenance["assets"])
    return {
        "backend": "bm25s.BM25",
        "bm25s_version": str(getattr(bm25s, "__version__", "unknown")),
        "documents": int(asset_provenance["documents"]),
        "statute_parquet_path": assets["statute_parquet"]["path"],
        "statute_parquet_sha256": assets["statute_parquet"]["sha256"],
        "normalized_corpus_path": assets["normalized_corpus"]["path"],
        "normalized_corpus_sha256": assets["normalized_corpus"]["sha256"],
        "parquet_to_provision_id_mapping_sha256": asset_provenance[
            "parquet_to_provision_id_mapping_sha256"
        ],
        "corpus_text": "parquet hierarchy + content in immutable parquet row order",
        "corpus_tokenization": "bm25s.tokenize(corpus, stopwords='en')",
        "query_tokenization": "bm25s.tokenize([query])",
        "top_k": PARSER_BM25S_TOP_K,
        "mapping_policy": asset_provenance["parquet_to_provision_id_mapping"],
        "first_stage_only": True,
        "fts5_query_expansion": "FORBIDDEN",
        "statute_hint_recall_channel": "FORBIDDEN",
        "first_stage_provision_id_deduplication": "FORBIDDEN",
    }


def _derived_configuration(
    source_configuration: Mapping[str, Any],
    asset_provenance: Mapping[str, Any],
    *,
    mode: str,
) -> Dict[str, Any]:
    configuration = deepcopy(dict(source_configuration))
    configuration["condition"] = (
        "C02-BM25s-ParSeR-first-stage-ablation-Qwen3.8-Q8_0-%s" % mode
    )
    configuration["retriever"] = "bm25s_parser"
    configuration["retriever_provenance"] = bm25s_retriever_provenance(asset_provenance)
    assert_retriever_only_configuration(source_configuration, configuration)
    return configuration


def build_manifests(asset_root: Path) -> Dict[str, Path]:
    """Materialize immutable, separately named C02 bm25s artifacts."""
    source = read_json(PRIMARY_MANIFEST)
    entries = list(source.get("entries") or [])
    if len(entries) != TOTAL_FULL226:
        raise C02Bm25sAblationError("C02 source manifest must contain exactly 226 entries")
    if [int(entry.get("ordinal", 0)) for entry in entries] != list(range(1, TOTAL_FULL226 + 1)):
        raise C02Bm25sAblationError("C02 source manifest ordinals are not contiguous")
    source_dataset = dict(source.get("source_dataset") or {})
    asset_provenance = load_asset_provenance(asset_root)
    if source_dataset.get("sha256") != asset_provenance["assets"]["qa_parquet"]["sha256"]:
        raise C02Bm25sAblationError("C02 QA parquet does not match its source manifest")
    reference = assert_reference_manifest_read_only()
    full_configuration = _derived_configuration(
        source["frozen_configuration"], asset_provenance, mode="full226"
    )
    full = {
        "manifest_schema_version": "1.0",
        "name": "c02-bm25s-parser-first-stage-ablation-full226-20260901",
        "purpose": (
            "Executable isolated C02 ablation: replace only KURE first-stage retrieval "
            "with ParSeR-compatible bm25s.BM25. C02 skills, BGE reranker, per-request "
            "rerank queries, Top-10 selection, Qwen alias/seed/temperature, budgets, and "
            "policies remain frozen. The historical v2_bm25_reference_full226.json is "
            "read-only and MUST_NEVER_BE_EXECUTED."
        ),
        "source_dataset": source_dataset,
        "entries": entries,
        "frozen_configuration": full_configuration,
        "selection": {
            "method": "exact C02 frozen 226 roster and order; retriever-only replacement",
            "entry_count": TOTAL_FULL226,
            "execution_role": "EXECUTABLE_ISOLATED_BM25S_FIRST_STAGE_ABLATION",
            "c02_source_commit": C02_SOURCE_COMMIT,
            "c02_source_tree": C02_SOURCE_TREE,
            "protected_reference": reference,
            "lf_eval": "excluded; no LF-Eval invocation or score injection",
        },
    }
    smoke_entry = dict(entries[0])
    smoke_entry["source_ordinal"] = int(smoke_entry["ordinal"])
    smoke_entry["ordinal"] = 1
    smoke = deepcopy(full)
    smoke["name"] = "c02-bm25s-parser-first-stage-ablation-smoke1-20260901"
    smoke["entries"] = [smoke_entry]
    smoke["frozen_configuration"] = _derived_configuration(
        source["frozen_configuration"], asset_provenance, mode="smoke1"
    )
    smoke["selection"] = {
        **dict(full["selection"]),
        "entry_count": 1,
        "execution_role": "RETRIEVER_ONLY_SMOKE_NO_BGE_NO_OLLAMA",
        "source_ordinal": int(entries[0]["ordinal"]),
    }
    smoke3_source_entries = [
        next(entry for entry in entries if int(entry["ordinal"]) == ordinal)
        for ordinal in (1, 5, 16)
    ]
    if {int(entry["n_hops"]) for entry in smoke3_source_entries} != {1, 2, 3}:
        raise C02Bm25sAblationError("C02 smoke3 must preserve one 1/2/3-hop entry")
    smoke3_entries = [
        {
            **dict(entry),
            "source_ordinal": int(entry["ordinal"]),
            "ordinal": index,
        }
        for index, entry in enumerate(smoke3_source_entries, start=1)
    ]
    smoke3 = deepcopy(full)
    smoke3["name"] = "c02-bm25s-parser-first-stage-ablation-smoke3-20260901"
    smoke3["entries"] = smoke3_entries
    smoke3["frozen_configuration"] = _derived_configuration(
        source["frozen_configuration"], asset_provenance, mode="smoke3"
    )
    smoke3["selection"] = {
        **dict(full["selection"]),
        "entry_count": 3,
        "execution_role": "OPERATIONAL_LLM_SMOKE3_NOT_BENCHMARK_EVIDENCE",
        "source_ordinals": [1, 5, 16],
    }
    metadata = {
        "schema_version": "c02-bm25s-ablation-1.0",
        "c02_source_commit": C02_SOURCE_COMMIT,
        "c02_source_tree": C02_SOURCE_TREE,
        "c02_source_manifest": str(PRIMARY_MANIFEST.relative_to(PROJECT_ROOT)),
        "c02_source_manifest_sha256": sha256(PRIMARY_MANIFEST),
        "protected_v2_bm25_reference": reference,
        "asset_provenance": asset_provenance,
        "parity_receipt": {
            "oracle": "saved baselines/koblex_parser/retrieval.py Bm25Retriever",
            "comparison": "ordered Top-100 raw parquet source-index arrays must be exactly equal",
            "canonical_serialization": "UTF-8 JSON list, ensure_ascii=False, separators=(',', ':')",
            "fixtures": [
                {
                    key: fixture[key]
                    for key in (
                        "query_sha256", "saved_c02_record",
                        "legacy_external_top100_index_sha256",
                        "canonical_source_index_list_sha256",
                    )
                }
                for fixture in PARSER_PARITY_FIXTURES
            ],
        },
        "generated": {
            "full226": {
                "path": str(FULL_MANIFEST.relative_to(PROJECT_ROOT)),
                "sha256": canonical_sha256(full),
            },
            "smoke1": {
                "path": str(SMOKE_MANIFEST.relative_to(PROJECT_ROOT)),
                "sha256": canonical_sha256(smoke),
            },
            "smoke3": {
                "path": str(LLM_SMOKE_MANIFEST.relative_to(PROJECT_ROOT)),
                "sha256": canonical_sha256(smoke3),
            },
        },
        "execution_policy": {
            "condition": "C02_BM25S_PARSER_FIRST_STAGE_ABLATION_ONLY",
            "kure_main_execution": "NOT_MODIFIED",
            "v2_bm25_reference_execution": "MUST_NEVER_BE_EXECUTED",
            "parser_execution": "FORBIDDEN",
            "bm25s_first_stage": "PERMITTED_ONLY_VIA_THIS_MANIFEST",
            "network": "OFFLINE_ONLY",
            "lf_eval_score_injection": "FORBIDDEN",
        },
    }
    validate_bm25s_first_stage_ablation(
        source, full, PRIMARY_MANIFEST, FULL_MANIFEST
    )
    write_json_new_or_verify(FULL_MANIFEST, full)
    write_json_new_or_verify(SMOKE_MANIFEST, smoke)
    write_json_new_or_verify(LLM_SMOKE_MANIFEST, smoke3)
    write_json_new_or_verify(METADATA_PATH, metadata)
    return {
        "full226": FULL_MANIFEST,
        "smoke1": SMOKE_MANIFEST,
        "smoke3": LLM_SMOKE_MANIFEST,
        "metadata": METADATA_PATH,
    }


def validate_frozen_artifacts(asset_root: Path) -> Dict[str, Any]:
    paths = build_manifests(asset_root)
    metadata = read_json(paths["metadata"])
    for name in ("full226", "smoke1", "smoke3"):
        path = paths[name]
        manifest = read_json(path)
        generated = dict(metadata.get("generated") or {}).get(name)
        if not isinstance(generated, Mapping) or generated.get("sha256") != canonical_sha256(manifest):
            raise C02Bm25sAblationError("frozen manifest hash mismatch: %s" % path)
        assert_retriever_only_configuration(
            read_json(PRIMARY_MANIFEST)["frozen_configuration"],
            manifest["frozen_configuration"],
        )
    validate_bm25s_first_stage_ablation(
        read_json(PRIMARY_MANIFEST), read_json(paths["full226"]),
        PRIMARY_MANIFEST, paths["full226"],
    )
    return {
        "status": "PASS",
        "artifacts": {name: str(path) for name, path in paths.items()},
        "metadata": metadata,
    }


def _load_questions(qa_parquet: Path) -> Dict[str, Mapping[str, Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise C02Bm25sAblationError("pyarrow is required for C02 question loading") from exc
    rows = pq.read_table(
        str(qa_parquet), columns=["id", "background", "question", "n_hops"]
    ).to_pylist()
    return {str(row["id"]): row for row in rows}


def format_benchmark_input(question: Mapping[str, Any]) -> str:
    background = str(question.get("background") or "").strip()
    prompt = str(question.get("question") or "").strip()
    if not prompt:
        raise C02Bm25sAblationError("frozen benchmark question text is empty")
    if not background:
        return "[질문]\n%s" % prompt
    return "[배경 시나리오]\n%s\n\n[질문]\n%s" % (background, prompt)


def run_retriever_smoke(asset_root: Path, query: str | None = None) -> Dict[str, Any]:
    """CPU-only one-query verification. It never loads BGE, KURE, or Ollama."""
    validation = validate_frozen_artifacts(asset_root)
    metadata = dict(validation["metadata"])
    assets = dict(metadata["asset_provenance"]["assets"])
    root = resolve_asset_root(asset_root)
    statute = asset_path(root, Path(str(assets["statute_parquet"]["path"])))
    normalized = asset_path(root, Path(str(assets["normalized_corpus"]["path"])))
    qa_path = asset_path(root, Path(str(assets["qa_parquet"]["path"])))
    if query is None:
        smoke_entry = read_json(SMOKE_MANIFEST)["entries"][0]
        question = _load_questions(qa_path).get(str(smoke_entry["question_id"]))
        if question is None:
            raise C02Bm25sAblationError("smoke question is absent from frozen QA parquet")
        query = format_benchmark_input(question)
    searcher = Bm25sParSeRFirstStageSearcher.from_parquet(statute, normalized)
    from harness.contracts import QueryChannel, RetrievalRequest
    request = RetrievalRequest(
        request_id="C02-BM25S-SMOKE-RQ1",
        issue_id="SMOKE-I1",
        evidence_item_id="SMOKE-E1",
        query_channel=QueryChannel.PROVISION_STYLE,
        query_text=query,
        top_k=PARSER_BM25S_TOP_K,
        query_terms=["MUST_NOT_AFFECT_BM25S_QUERY"],
        statute_hints=["MUST_NOT_AFFECT_BM25S_QUERY"],
    )
    hits = searcher.search(request)
    if len(hits) != PARSER_BM25S_TOP_K:
        raise C02Bm25sAblationError("bm25s smoke did not return exactly Top-100 hits")
    hit_ids = [hit.document.provision_id for hit in hits]
    if len(hit_ids) != len(set(hit_ids)):
        raise C02Bm25sAblationError("normalized provision ID mapping unexpectedly collapsed rows")
    return {
        "status": "PASS",
        "mode": "RETRIEVER_ONLY_CPU_SMOKE",
        "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
        "corpus_size": searcher.corpus_size,
        "corpus_mapping_sha256": searcher.corpus_mapping_sha256,
        "top_k": len(hits),
        "top100_provision_ids_sha256": canonical_sha256(hit_ids),
        "top5": [
            {"provision_id": hit.document.provision_id, "score": hit.score}
            for hit in hits[:5]
        ],
        "no_model_loaded": True,
        "no_bge_loaded": True,
    }


def run_saved_parser_parity(asset_root: Path) -> Dict[str, Any]:
    """CPU-only exact Top-100 parity against the saved ParSeR reproducer.

    Both indexes are built once and reused across the three recovered C02
    queries.  Equality is on the raw ordered parquet source-index array, not
    on provision IDs, because ParSeR's parquet indexes intentionally duplicate
    some legal-text labels.
    """
    validation = validate_frozen_artifacts(asset_root)
    metadata = dict(validation["metadata"])
    assets = dict(metadata["asset_provenance"]["assets"])
    root = resolve_asset_root(asset_root)
    statute = asset_path(root, Path(str(assets["statute_parquet"]["path"])))
    normalized = asset_path(root, Path(str(assets["normalized_corpus"]["path"])))
    from baselines.koblex_parser.retrieval import Bm25Retriever, load_statute_corpus
    baseline = Bm25Retriever(load_statute_corpus(statute))
    searcher = Bm25sParSeRFirstStageSearcher.from_parquet(statute, normalized)
    source_index_by_provision_id = {
        document.provision_id: source_index
        for source_index, document in zip(searcher.source_indexes, searcher.documents)
    }
    receipts = []
    for fixture in PARSER_PARITY_FIXTURES:
        query = fixture["query"]
        if hashlib.sha256(query.encode("utf-8")).hexdigest() != fixture["query_sha256"]:
            raise C02Bm25sAblationError("saved parity query hash does not match its receipt")
        from harness.contracts import QueryChannel, RetrievalRequest
        hits = searcher.search(RetrievalRequest(
            "C02-PARITY", "I", "E", QueryChannel.PROVISION_STYLE, query,
            PARSER_BM25S_TOP_K, query_terms=["IGNORED"], statute_hints=["IGNORED"],
        ))
        actual = [source_index_by_provision_id[hit.document.provision_id] for hit in hits]
        expected = [baseline.records[index].index for index in baseline.top_k(query)]
        if actual != expected:
            raise C02Bm25sAblationError("bm25s Top-100 source-index parity mismatch")
        actual_sha256 = canonical_sha256(actual)
        if actual_sha256 != fixture["canonical_source_index_list_sha256"]:
            raise C02Bm25sAblationError("bm25s canonical parity receipt hash mismatch")
        receipts.append({
            key: fixture[key]
            for key in (
                "query_sha256", "saved_c02_record",
                "legacy_external_top100_index_sha256",
                "canonical_source_index_list_sha256",
            )
        })
    return {
        "status": "PASS",
        "mode": "CPU_ONLY_SAVED_PARSER_TOP100_PARITY",
        "documents": searcher.corpus_size,
        "fixtures": receipts,
        "canonical_serialization": "UTF-8 JSON list, ensure_ascii=False, separators=(',', ':')",
        "no_model_loaded": True,
        "no_bge_loaded": True,
    }


def _write_runtime_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise C02Bm25sAblationError(
                "invalid ablation summary JSONL at line %d" % number
            ) from exc
        if not isinstance(row, dict):
            raise C02Bm25sAblationError("ablation summary row must be an object")
        rows.append(dict(row))
    return rows


def _model_readiness(configuration: Mapping[str, Any]) -> Dict[str, Any]:
    """Read local tags only; this does not send a generation request."""
    model = str(configuration.get("model") or "")
    provenance = configuration.get("model_provenance")
    if not model or not isinstance(provenance, Mapping):
        raise C02Bm25sAblationError("frozen C02 model provenance is missing")
    endpoint = str(configuration.get("ollama_endpoint") or "")
    if not endpoint.endswith("/api/generate"):
        raise C02Bm25sAblationError("frozen C02 Ollama endpoint is invalid")
    tags_url = endpoint[: -len("/api/generate")] + "/api/tags"
    try:
        with urlopen(tags_url, timeout=10) as response:  # nosec B310 - fixed local endpoint from frozen config
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, json.JSONDecodeError) as exc:
        raise C02Bm25sAblationError("local Ollama readiness check failed") from exc
    expected_digest = provenance.get("ollama_manifest_digest")
    expected_details = provenance.get("ollama_details")
    if not isinstance(expected_digest, str) or not isinstance(expected_details, Mapping):
        raise C02Bm25sAblationError("frozen C02 model digest/details are missing")
    for item in payload.get("models", []) if isinstance(payload, Mapping) else []:
        if not isinstance(item, Mapping):
            continue
        names = {str(item.get(key)) for key in ("name", "model") if item.get(key)}
        details = item.get("details")
        if model not in names and (model + ":latest") not in names:
            continue
        if item.get("digest") != expected_digest or not isinstance(details, Mapping):
            continue
        if all(details.get(key) == expected_details.get(key) for key in ("family", "parameter_size", "quantization_level")):
            return {
                "status": "PASS",
                "endpoint": endpoint,
                "model_alias": model,
                "manifest_digest": expected_digest,
                "details": {
                    key: details[key]
                    for key in ("family", "parameter_size", "quantization_level")
                },
                "generation_requested": False,
            }
    raise C02Bm25sAblationError("local Ollama alias/digest does not match frozen C02")


def _outcome_counts(rows: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    return {
        status: sum(1 for row in rows if row.get("status") == status)
        for status in ("ANSWER", "ABSTAIN", "EXECUTION_FAILURE")
    }


def _synthetic_execution_failure_record(
    records_root: Path,
    *,
    question_id: str,
    record_configuration: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    error: BaseException,
) -> Dict[str, Any]:
    """Materialize a zero-score explicit failure that the offline evaluator can join."""
    run_id = str(uuid.uuid4())
    directory = records_root / run_id
    directory.mkdir(parents=True, exist_ok=False)
    failure = "%s: %s" % (type(error).__name__, error)
    _write_runtime_json(directory / "metadata.json", {
        "run_id": run_id,
        "question_id": question_id,
        "configuration": dict(record_configuration),
        "source_snapshot": dict(source_snapshot),
        "record_kind": "EXPLICIT_EXECUTION_FAILURE",
    })
    _write_runtime_json(directory / "result.json", {
        "run_id": run_id,
        "status": "EXECUTION_FAILURE",
        "termination_reason": "SKILL_EXECUTION_FAILED",
        "abstention_reason": None,
        "answer": "",
        "candidate_answer": None,
        "candidate_answer_status": "EXECUTION_FAILURE",
        "candidate_answer_basis": None,
        "accepted_provision_ids": [],
        "errors": [failure],
        "end_to_end_latency_ms": 0.0,
        "state": {
            "accepted_provision_ids": [],
            "candidate_provisions": [],
            "query_history": [],
            "retrieval_rounds_used": 0,
            "action_trace": [],
        },
    })
    return {
        "status": "EXECUTION_FAILURE",
        "record_directory": str(directory),
        "record_result_file": str(directory / "result.json"),
        "run_id": run_id,
        "errors": [failure],
        "exit_code": 1,
    }


def _assert_completed_rows(
    rows: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any],
    records_root: Path,
    record_configuration: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
) -> None:
    entries = list(manifest.get("entries") or [])
    if len(rows) > len(entries):
        raise C02Bm25sAblationError("ablation summary exceeds frozen manifest length")
    for expected_ordinal, row in enumerate(rows, start=1):
        entry = entries[expected_ordinal - 1]
        if (
            int(row.get("ordinal", 0)) != expected_ordinal
            or row.get("question_id") != entry.get("question_id")
            or int(row.get("n_hops", 0)) != int(entry.get("n_hops", 0))
        ):
            raise C02Bm25sAblationError("ablation resume summary is not a contiguous frozen prefix")
        if row.get("status") not in {"ANSWER", "ABSTAIN", "EXECUTION_FAILURE"}:
            raise C02Bm25sAblationError("ablation summary has an invalid outcome status")
        directory = Path(str(row.get("record_directory") or "")).resolve()
        if records_root not in directory.parents or not directory.is_dir():
            raise C02Bm25sAblationError("ablation summary record path escapes its output root")
        metadata = read_json(directory / "metadata.json")
        result = read_json(directory / "result.json")
        if (
            metadata.get("question_id") != entry.get("question_id")
            or not _record_configuration_matches(
                metadata.get("configuration"), record_configuration
            )
            or metadata.get("source_snapshot") != dict(source_snapshot)
            or result.get("status") != row.get("status")
            or metadata.get("run_id") != result.get("run_id")
        ):
            raise C02Bm25sAblationError("ablation summary/record provenance mismatch")


def _record_configuration_matches(
    recorded: Any,
    expected: Mapping[str, Any],
) -> bool:
    """Compare the normal run-record configuration, not a batch-only config."""
    if not isinstance(recorded, Mapping):
        return False
    identity_fields = (
        "condition", "retriever", "model", "seed", "ollama_endpoint", "num_ctx",
        "total_retrieval_rounds", "total_retrieval_requests", "rerank_pool_k",
        "final_top_k", "rerank_query_mode", "candidate_selection",
        "per_evidence_min_k", "candidate_budget_scope", "round_merge_mode",
        "dedup_mode", "rerank_document_mode", "input_format",
        "s1_max_tokens", "s1_truncation_retry_max_tokens",
        "source_manifest_sha256",
    )
    return all(recorded.get(key) == expected.get(key) for key in identity_fields)


def _initialize_or_resume_output(
    output_root: Path,
    *,
    manifest: Mapping[str, Any],
    manifest_path: Path,
    mode: str,
    asset_provenance: Mapping[str, Any],
    configuration: Mapping[str, Any],
    record_configuration: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
    model_readiness: Mapping[str, Any],
    resume: bool,
) -> tuple[Path, Path, List[Dict[str, Any]]]:
    plan = {
        "name": manifest["name"],
        "mode": mode,
        "source_snapshot": dict(source_snapshot),
        "manifest": str(manifest_path),
        "manifest_sha256": sha256(manifest_path),
        "frozen_configuration": dict(configuration),
        "asset_provenance": dict(asset_provenance),
        "model_readiness": dict(model_readiness),
        "execution_policy": "C02_BM25S_FIRST_STAGE_ONLY",
        "entry_count": len(manifest["entries"]),
    }
    records_root = output_root / "records" / "runs"
    batch_root = output_root / "batch"
    if not output_root.exists() and not output_root.is_symlink():
        output_root.mkdir(parents=True, exist_ok=False)
        records_root.mkdir(parents=True, exist_ok=False)
        batch_root.mkdir(parents=True, exist_ok=False)
        _write_runtime_json(output_root / "plan.json", {"created_at_utc": utc_now(), **plan})
        # Preserve the frozen manifest bytes as well as its parsed content so
        # later evaluator/receipt checks can use the original manifest SHA.
        (batch_root / "manifest.json").write_bytes(manifest_path.read_bytes())
        _write_runtime_json(batch_root / "metadata.json", {
            "batch_id": "c02-bm25s-" + uuid.uuid4().hex,
            "started_at_utc": utc_now(),
            "entry_count": len(manifest["entries"]),
            "configuration": dict(configuration),
            "source_snapshot": dict(source_snapshot),
            "batch_manifest_sha256": sha256(batch_root / "manifest.json"),
            "asset_provenance": dict(asset_provenance),
            "execution_mode": "warm_persistent_bm25s_first_stage_only",
            "resume_policy": "CONTIGUOUS_PREFIX_ONLY",
            "v2_bm25_reference_execution": "MUST_NEVER_BE_EXECUTED",
        })
        return records_root, batch_root, []
    if not resume:
        raise C02Bm25sAblationError("refusing to overwrite ablation output; pass --resume")
    existing = read_json(output_root / "plan.json")
    stable_keys = (
        "name", "mode", "source_snapshot", "manifest", "manifest_sha256",
        "frozen_configuration", "asset_provenance", "entry_count",
    )
    if any(existing.get(key) != plan.get(key) for key in stable_keys):
        raise C02Bm25sAblationError("ablation resume source/manifest/asset plan mismatch")
    if not records_root.is_dir() or not batch_root.is_dir():
        raise C02Bm25sAblationError("ablation resume output structure is incomplete")
    if sha256(batch_root / "manifest.json") != plan["manifest_sha256"]:
        raise C02Bm25sAblationError("ablation batch manifest differs from frozen manifest")
    rows = _read_jsonl(batch_root / "summary.jsonl")
    _assert_completed_rows(
        rows, manifest, records_root, record_configuration, source_snapshot
    )
    return records_root, batch_root, rows


def _write_checkpoint(
    output_root: Path,
    rows: Sequence[Mapping[str, Any]],
    *,
    manifest_path: Path,
    source_snapshot: Mapping[str, Any],
) -> None:
    completed = len(rows)
    if completed == 0 or (completed % 20 != 0 and completed != 3 and completed != 226):
        return
    path = output_root / "checkpoints" / ("checkpoint-%03d.json" % completed)
    if path.exists():
        existing = read_json(path)
        if (
            existing.get("completed_questions") != completed
            or existing.get("manifest_sha256") != sha256(manifest_path)
            or existing.get("source_snapshot") != dict(source_snapshot)
        ):
            raise C02Bm25sAblationError("existing ablation checkpoint provenance mismatch")
        return
    _write_runtime_json(path, {
        "checkpoint_status": "COMPLETED_WITH_EXPLICIT_OUTCOMES",
        "completed_questions": completed,
        "manifest_sha256": sha256(manifest_path),
        "source_snapshot": dict(source_snapshot),
        "outcomes": _outcome_counts(rows),
        "created_at_utc": utc_now(),
    })


def _assert_smoke3_gate(
    smoke3_output_root: Path,
    configuration: Mapping[str, Any],
    source_snapshot: Mapping[str, Any],
) -> None:
    gate = read_json(smoke3_output_root / "gate.json")
    if gate.get("status") != "PASS" or gate.get("mode") != "smoke3":
        raise C02Bm25sAblationError("full226 requires a passing immutable bm25s smoke3 gate")
    smoke_manifest = read_json(LLM_SMOKE_MANIFEST)
    if (
        gate.get("smoke_manifest_sha256") != sha256(LLM_SMOKE_MANIFEST)
        or gate.get("smoke_configuration_sha256")
        != canonical_sha256(smoke_manifest["frozen_configuration"])
        or gate.get("source_snapshot") != dict(source_snapshot)
    ):
        raise C02Bm25sAblationError("smoke3 gate provenance does not match this source snapshot")
    expected_model = configuration.get("model_provenance")
    gate_model = gate.get("model_readiness")
    if (
        not isinstance(expected_model, Mapping)
        or not isinstance(gate_model, Mapping)
        or gate_model.get("model_alias") != configuration.get("model")
        or gate_model.get("manifest_digest") != expected_model.get("ollama_manifest_digest")
    ):
        raise C02Bm25sAblationError("smoke3 gate model provenance does not match full226")


def execute_condition(
    asset_root: Path,
    output_root: Path,
    *,
    manifest_path: Path,
    mode: str,
    resume: bool,
    smoke3_output_root: Path | None = None,
) -> int:
    """Run only an explicit C02 bm25s manifest with contiguous-prefix resume."""
    os.environ.update(OFFLINE_ENVIRONMENT)
    validation = validate_frozen_artifacts(asset_root)
    manifest = read_json(manifest_path)
    configuration = resolve_frozen_configuration(manifest["frozen_configuration"])
    assert_retriever_only_configuration(
        read_json(PRIMARY_MANIFEST)["frozen_configuration"], configuration
    )
    root = resolve_asset_root(asset_root)
    qa_path = asset_path(root, EXPECTED_ASSET_RELATIVE_PATHS["qa_parquet"])
    if sha256(qa_path) != manifest["source_dataset"].get("sha256"):
        raise C02Bm25sAblationError("QA parquet hash does not match C02 bm25s manifest")
    model_readiness = _model_readiness(configuration)
    snapshot = capture_clean_source_snapshot(PROJECT_ROOT)
    if mode == "full226":
        if smoke3_output_root is None:
            raise C02Bm25sAblationError("full226 requires --smoke3-output-root")
        _assert_smoke3_gate(smoke3_output_root, configuration, snapshot.to_dict())
    from scripts import run_local_harness
    provisional_records_root = output_root / "records" / "runs"
    bootstrap_args = run_local_harness.build_frozen_run_args(
        "", "", configuration, provisional_records_root, snapshot.git_commit,
        snapshot.source_manifest_sha256, asset_root=root,
    )
    record_configuration = run_local_harness.resolve_runtime_configuration(
        bootstrap_args, snapshot.source_manifest_sha256
    )
    records_root, batch_root, rows = _initialize_or_resume_output(
        output_root,
        manifest=manifest,
        manifest_path=manifest_path,
        mode=mode,
        asset_provenance=validation["metadata"]["asset_provenance"],
        configuration=configuration,
        record_configuration=record_configuration,
        source_snapshot=snapshot.to_dict(),
        model_readiness=model_readiness,
        resume=resume,
    )
    questions = _load_questions(qa_path)
    bootstrap_args.record_dir = records_root
    resources = run_local_harness.PersistentHarnessResources(bootstrap_args)
    for entry in manifest["entries"][len(rows):]:
        assert_source_snapshot_unchanged(PROJECT_ROOT, snapshot)
        question_id = str(entry["question_id"])
        question = questions.get(question_id)
        if question is None or int(question["n_hops"]) != int(entry["n_hops"]):
            raise C02Bm25sAblationError("frozen question is absent or hop-mismatched: %s" % question_id)
        started = utc_now()
        run_args = run_local_harness.build_frozen_run_args(
            format_benchmark_input(question), question_id, configuration,
            records_root, snapshot.git_commit, snapshot.source_manifest_sha256,
            asset_root=root,
        )
        try:
            execution = run_local_harness.run_question(
                run_args, source_snapshot=snapshot, resources=resources
            )
            outcome = {**dict(execution.summary), "exit_code": execution.exit_code}
        except Exception as exc:  # keeps collection honest without coercing an outcome
            error_path = batch_root / "errors" / (
                "%03d_%s.traceback.log" % (int(entry["ordinal"]), question_id)
            )
            error_path.parent.mkdir(parents=True, exist_ok=True)
            error_path.write_text(traceback.format_exc(), encoding="utf-8")
            outcome = _synthetic_execution_failure_record(
                records_root, question_id=question_id,
                record_configuration=record_configuration,
                source_snapshot=snapshot.to_dict(), error=exc,
            )
        assert_source_snapshot_unchanged(PROJECT_ROOT, snapshot)
        row = {
            "ordinal": int(entry["ordinal"]),
            "source_ordinal": int(entry.get("source_ordinal", entry["ordinal"])),
            "question_id": question_id,
            "n_hops": int(entry["n_hops"]),
            "started_at_utc": started,
            "completed_at_utc": utc_now(),
            **outcome,
        }
        with (batch_root / "summary.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
        rows.append(row)
        _write_checkpoint(
            output_root, rows, manifest_path=manifest_path,
            source_snapshot=snapshot.to_dict(),
        )
    assert_source_snapshot_unchanged(PROJECT_ROOT, snapshot)
    _assert_completed_rows(
        rows, manifest, records_root, record_configuration, snapshot.to_dict()
    )
    final = {
        "status": "COMPLETED_WITH_EXPLICIT_OUTCOMES",
        "mode": mode,
        "entry_count": len(rows),
        "outcomes": _outcome_counts(rows),
        "completed_at_utc": utc_now(),
    }
    _write_runtime_json(output_root / "final.json", final)
    _write_checkpoint(output_root, rows, manifest_path=manifest_path, source_snapshot=snapshot.to_dict())
    metadata = read_json(batch_root / "metadata.json")
    metadata.update({
        "completed_at_utc": utc_now(),
        "completed_questions": len(rows),
        "outcomes": _outcome_counts(rows),
        "has_execution_failure": bool(_outcome_counts(rows)["EXECUTION_FAILURE"]),
    })
    _write_runtime_json(batch_root / "metadata.json", metadata)
    if mode == "smoke3":
        gate = {
            "mode": "smoke3",
            "status": (
                "PASS"
                if final["outcomes"]["ANSWER"] >= 1
                and final["outcomes"]["EXECUTION_FAILURE"] == 0
                else "FAIL"
            ),
            "final": final,
            "smoke_manifest_sha256": sha256(LLM_SMOKE_MANIFEST),
            "smoke_configuration_sha256": canonical_sha256(manifest["frozen_configuration"]),
            "source_snapshot": snapshot.to_dict(),
            "model_readiness": model_readiness,
        }
        _write_runtime_json(output_root / "gate.json", gate)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("bootstrap", "preflight", "parity", "smoke-search", "run-smoke3", "run-full226"),
    )
    parser.add_argument("--asset-root", type=Path, default=DEFAULT_ASSET_ROOT)
    parser.add_argument("--query", help="explicit one-query CPU retrieval smoke text")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "records/c02-bm25s-parser-first-stage-ablation",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="resume only a contiguous prefix with identical source/manifest/assets",
    )
    parser.add_argument(
        "--smoke3-output-root",
        type=Path,
        help="immutable passing smoke3 output required before full226",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.action == "bootstrap":
        paths = build_manifests(args.asset_root)
        print(json.dumps({key: str(value) for key, value in paths.items()}, ensure_ascii=False, indent=2))
        return 0
    if args.action == "preflight":
        validation = validate_frozen_artifacts(args.asset_root)
        configuration = read_json(FULL_MANIFEST)["frozen_configuration"]
        print(json.dumps({
            **validation,
            "source_snapshot": capture_clean_source_snapshot(PROJECT_ROOT).to_dict(),
            "model_readiness": _model_readiness(configuration),
            "saved_parser_parity": run_saved_parser_parity(args.asset_root),
            "offline_environment": OFFLINE_ENVIRONMENT,
        }, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.action == "parity":
        print(json.dumps(run_saved_parser_parity(args.asset_root), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.action == "smoke-search":
        print(json.dumps(run_retriever_smoke(args.asset_root, args.query), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.action == "run-smoke3":
        return execute_condition(
            args.asset_root, args.output_root, manifest_path=LLM_SMOKE_MANIFEST,
            mode="smoke3", resume=args.resume,
        )
    return execute_condition(
        args.asset_root, args.output_root, manifest_path=FULL_MANIFEST,
        mode="full226", resume=args.resume,
        smoke3_output_root=args.smoke3_output_root,
    )


if __name__ == "__main__":
    raise SystemExit(main())
