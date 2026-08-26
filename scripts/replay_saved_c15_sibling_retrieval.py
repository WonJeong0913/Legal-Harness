#!/usr/bin/env python3
"""Saved C02 initial-request C15.1 sibling expansion retrieval microprobe.

This is deliberately not a harness runner: it creates neither an LLM/skill
executor nor policy, coverage, evaluator, BM25, or benchmark objects.  It
replays only persisted original ``RQ<N>`` requests for retrieval round one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
DEFAULT_SOURCE_ROOT = Path(
    "/workspace/Legal-Harness/records/"
    "v2-kure-qwen38-offline-full226-c02e281-targeted-resume168-20260826"
)
BATCH_RELATIVE = Path("batches/c02e281-targeted-resume-ord042-054-061-226-20260826")
C15_1_COMMIT = "bfabd4a3cc5b7147723c1e7720ca7beea09a2547"
C15_1_TREE = "4ffe19a0a5a156228a0437b50a0ef661f5d38bd0"
C02_COMMIT = "c02e2818ad54e9d5a1a9bd02b604e987192bb244"
C02_SOURCE_MANIFEST_SHA256 = "40591e4b6963abbe11b5b95e021c2abba9fb5b5bd7c8e2c379d04de9f6e41956"
C02_SUMMARY_SHA256 = "2d52a25c698425e45e7e607df008404078dd90eaba4da55a8b881e15cd3f487a"
C02_BATCH_MANIFEST_SHA256 = "74c61195e6ad5a63913106a33daa517b6bb2c0c6110dc513a23dc6e78b96f4c8"
KURE_PROVISION_IDS_SHA256 = "37333588e1692927d5e6925e4f6bde1ea2d8291f3fda2dddbdad18507445cff8"
KURE_VECTORS_SHA256 = "3e312dbf4cf24e7b91bc9833a9001416d85644e6868bdb657d889bd535a9d983"
NORMALIZED_CORPUS_SHA256 = "0e2283c7bcfa8f92d3ea7d4dd249449a31c0528b47dde04ab408bee45e0857b0"
KURE_MODEL_WEIGHTS_SHA256 = "c18156e80caf8ff45eb84a24a853130c3bca03087ccb41b051f86e7556bae02c"
BGE_MODEL_WEIGHTS_SHA256 = "aba51b69d97bfff4cd2c1d8eb6c57764e350231850f712b75ae426270f265a43"
CORPUS_OBSERVED_MAX_FAMILY_MEMBERS = 111
FAMILY_MEMBER_BOUND = 128
KOBLEX_SUFFIX_RE = re.compile(r"(?:.*#)?(KOBLEX-[0-9]+)\Z")


@dataclass(frozen=True)
class SourceProfile:
    question_id: str
    sequence: int
    ordinal: int
    n_hops: int
    run_id: str
    receipt_name: str
    result_sha256: str
    metadata_sha256: str
    receipt_sha256: str
    expected_root_provision_id: str | None = None
    expected_scored_sibling_ids: tuple[str, ...] = ()
    expected_available_provision_id: str | None = None


# Static by design. qa_125_1hop_225 is intentionally excluded. The qa125
# expectations are canonical terminal KOBLEX suffixes, not full corpus IDs.
SOURCE_PROFILES: Dict[str, SourceProfile] = {
    "qa_125_2hop_226": SourceProfile(
        "qa_125_2hop_226", 48, 106, 2, "ce09d435-580f-4b0e-8f2d-fc08a5a3a9d6",
        "048_ord106_qa_125_2hop_226.json",
        "4b45fbb21e434b102683f85ba98d3bc19bffb12030557aa8584012139dec6dfd",
        "e884c3eab1e97ab8690d5bf0ff5f499cd573af9c8d7f13172689ae98dad01a38",
        "faa1b24c5bf3b0923e5829d421ac405330ca6578ac68952ad318cfb653cefbec",
        "KOBLEX-232721", tuple("KOBLEX-%d" % item for item in range(232722, 232737)),
        "KOBLEX-232732",
    ),
    "qa_68_1hop_100": SourceProfile(
        "qa_68_1hop_100", 26, 84, 1, "5b86ff62-9d98-449a-b7fe-23a3a651e70b",
        "026_ord084_qa_68_1hop_100.json",
        "31ebd58593b8d0a579ae7921413930db6161ea2449c5ad3971baca924e749981",
        "95a9b118327169a1da875fc1eff71ad0f29a6add485d7fdbbcd1f4d2f2cac7ef",
        "8b6ca8b976f5f025e479e55e420bb00b4847dfda157c0496fe0e153389d5137f",
    ),
    "qa_435_2hop_678": SourceProfile(
        "qa_435_2hop_678", 82, 140, 2, "97e5ae06-b5e9-4985-852e-3b4b5816a33b",
        "082_ord140_qa_435_2hop_678.json",
        "c635691bab14475f260717da55f5c4a1018c2c1ed298c2372ea7571d90f5b2d5",
        "90ce2c6a1d3b956aef0beaaab0c3d16bfcd6a7f94473b6e9d596586d5b5a01eb",
        "77e7267fd63587d1fae54c879623e4038561741e0cb51d9ca9406fae0bdaf161",
    ),
}


class ProbeSafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceBundle:
    profile: SourceProfile
    requests: tuple[Any, ...]
    retrieval_configuration: Mapping[str, Any]
    source_binding: Mapping[str, Any]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def canonical_koblex_suffix(provision_id: Any, label: str) -> str:
    """Accept only an exact bare or terminal composite KOBLEX identifier."""
    if not isinstance(provision_id, str):
        raise ProbeSafetyError("%s must be a string provision id" % label)
    match = KOBLEX_SUFFIX_RE.fullmatch(provision_id)
    if not match:
        raise ProbeSafetyError("%s has no exact terminal KOBLEX identifier" % label)
    return match.group(1)


def _canonical_expected_ids(provision_ids: Sequence[str], label: str) -> set[str]:
    output: Dict[str, str] = {}
    for provision_id in provision_ids:
        canonical = canonical_koblex_suffix(provision_id, label)
        if canonical in output:
            raise ProbeSafetyError("duplicate canonical KOBLEX expectation: %s" % canonical)
        output[canonical] = provision_id
    return set(output)


def _canonical_stage_ids(records: Sequence[Mapping[str, Any]], field: str, label: str) -> Dict[str, str]:
    """Map suffix to raw ID, rejecting distinct raw IDs with one suffix."""
    output: Dict[str, str] = {}
    for record in records:
        raw = record.get(field)
        canonical = canonical_koblex_suffix(raw, "%s.%s" % (label, field))
        previous = output.setdefault(canonical, raw)
        if previous != raw:
            raise ProbeSafetyError("ambiguous canonical KOBLEX identifier: %s" % canonical)
    return output


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def require_sha(path: Path, expected: str, label: str) -> None:
    if sha256_file(path) != expected:
        raise ProbeSafetyError("%s SHA-256 mismatch: %s" % (label, path))


def assert_safe_output(path: Path) -> None:
    try:
        path.resolve().relative_to(Path("/workspace"))
    except ValueError:
        return
    raise ProbeSafetyError("probe output under /workspace is forbidden")


def initial_requests_from_result(result: Mapping[str, Any]) -> tuple[Any, ...]:
    """Trust exactly saved original RQ<N> requests; reject all gap repairs."""
    from harness.contracts import QueryChannel, RetrievalRequest
    history = result.get("state", {}).get("query_history")
    if not isinstance(history, list):
        raise ProbeSafetyError("saved result has no query_history")
    output = []
    for item in history:
        request_id = item.get("request_id") if isinstance(item, dict) else None
        if not isinstance(request_id, str) or not re.fullmatch(r"RQ[1-9][0-9]*", request_id):
            continue
        try:
            output.append(RetrievalRequest(
                request_id=request_id, issue_id=item["issue_id"],
                evidence_item_id=item["evidence_item_id"],
                query_channel=QueryChannel(item["query_channel"]), query_text=item["query_text"],
                top_k=item["top_k"], query_terms=list(item.get("query_terms", [])),
                statute_hints=list(item.get("statute_hints", [])),
                first_stage_query_text=item.get("first_stage_query_text"),
                rerank_query_text=item.get("rerank_query_text"),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            raise ProbeSafetyError("invalid saved initial retrieval request") from exc
    if not output or len({request.request_id for request in output}) != len(output):
        raise ProbeSafetyError("saved original RQ<N> requests are missing or duplicated")
    return tuple(output)


def resolved_retrieval_configuration(configuration: Mapping[str, Any]) -> Dict[str, Any]:
    if configuration.get("retriever") != "kure":
        raise ProbeSafetyError("only the frozen KURE first stage is allowed")
    if configuration.get("rerank_query_mode") != "per_request":
        raise ProbeSafetyError("C15.1 sibling expansion requires per_request BGE")
    required = {"rerank_pool_k", "final_top_k", "candidate_selection", "per_evidence_min_k",
                "dedup_mode", "candidate_budget_scope", "round_merge_mode", "rerank_document_mode"}
    if required - set(configuration):
        raise ProbeSafetyError("saved retrieval configuration is incomplete")
    return {
        "retriever": "kure", "rerank_pool_k": configuration["rerank_pool_k"],
        "final_top_k": configuration["final_top_k"], "rerank_query_mode": "per_request",
        "candidate_selection": configuration["candidate_selection"],
        "per_evidence_min_k": configuration["per_evidence_min_k"],
        "dedup_mode": configuration["dedup_mode"],
        "candidate_budget_scope": configuration["candidate_budget_scope"],
        "round_merge_mode": configuration["round_merge_mode"],
        "rerank_document_mode": configuration["rerank_document_mode"],
        "article_family_sibling_rerank_expansion": False,
        "article_family_expansion_trigger_top_k": 3,
        "article_family_expansion_max_siblings_per_root": 4,
        "article_family_expansion_max_siblings_per_request": 8,
        "article_family_expansion_max_family_members_scored": FAMILY_MEMBER_BOUND,
    }


def load_saved_source(source_root: Path, question_id: str, *, profiles: Mapping[str, SourceProfile] = SOURCE_PROFILES) -> SourceBundle:
    """Verify immutable C02 result/metadata/receipt/manifest lineage first."""
    if question_id not in profiles:
        raise ProbeSafetyError("question id is not in the static C15.2 allowlist")
    profile = profiles[question_id]
    batch = source_root / BATCH_RELATIVE
    paths = {
        "summary": batch / "summary.jsonl", "manifest": batch / "manifest.json",
        "receipt": batch / "task_receipts" / profile.receipt_name,
        "result": source_root / "records" / "runs" / profile.run_id / "result.json",
        "metadata": source_root / "records" / "runs" / profile.run_id / "metadata.json",
    }
    if not all(path.is_file() for path in paths.values()):
        raise ProbeSafetyError("one or more immutable C02 source artifacts are missing")
    if profiles is SOURCE_PROFILES:
        require_sha(paths["summary"], C02_SUMMARY_SHA256, "C02 summary")
        require_sha(paths["manifest"], C02_BATCH_MANIFEST_SHA256, "C02 batch manifest")
        require_sha(paths["receipt"], profile.receipt_sha256, "C02 task receipt")
        require_sha(paths["result"], profile.result_sha256, "C02 result")
        require_sha(paths["metadata"], profile.metadata_sha256, "C02 metadata")
    rows = [json.loads(line) for line in paths["summary"].read_text(encoding="utf-8").splitlines() if line]
    matching = [row for row in rows if row.get("question_id") == question_id]
    if len(matching) != 1:
        raise ProbeSafetyError("C02 summary has no unique allowed task")
    row = matching[0]
    for field in ("question_id", "sequence", "ordinal", "n_hops", "run_id"):
        if row.get(field) != getattr(profile, field):
            raise ProbeSafetyError("C02 summary binding mismatch for %s" % field)
    receipt = read_json(paths["receipt"])
    expected_task = {"question_id": profile.question_id, "sequence": profile.sequence,
                     "ordinal": profile.ordinal, "n_hops": profile.n_hops, "retry": False}
    if receipt.get("task") != expected_task or receipt.get("summary_row") != row:
        raise ProbeSafetyError("C02 receipt task/summary binding mismatch")
    if receipt.get("summary_sha256") != canonical_sha256(row):
        raise ProbeSafetyError("C02 receipt summary hash mismatch")
    manifest = read_json(paths["manifest"])
    if not isinstance(manifest.get("entries"), list) or expected_task not in manifest["entries"]:
        raise ProbeSafetyError("C02 batch manifest does not bind the receipt")
    metadata = read_json(paths["metadata"])
    configuration = metadata.get("configuration")
    if metadata.get("git_commit") != C02_COMMIT or not isinstance(configuration, dict):
        raise ProbeSafetyError("saved metadata is not C02")
    if configuration.get("source_manifest_sha256") != C02_SOURCE_MANIFEST_SHA256:
        raise ProbeSafetyError("saved C02 source manifest mismatch")
    result = read_json(paths["result"])
    if result.get("run_id") != profile.run_id:
        raise ProbeSafetyError("saved result run id mismatch")
    return SourceBundle(profile, initial_requests_from_result(result),
        resolved_retrieval_configuration(configuration), {
            "source_root": str(source_root.resolve()),
            **{name + "_sha256": sha256_file(path) for name, path in paths.items()},
            "source_git_commit": metadata["git_commit"],
            "source_manifest_sha256": configuration["source_manifest_sha256"],
        })


class RecordingFirstStage:
    article_family_sibling_expansion_capability = "kure_exact"
    def __init__(self, wrapped: Any, trace: Dict[str, Any]):
        self.wrapped, self.trace = wrapped, trace
    def search(self, request: Any) -> Any:
        self.trace["kure_queries"].append({"request_id": request.request_id,
            "utf8_hex": request.query_text.encode("utf-8").hex()})
        return self.wrapped.search(request)
    def article_family_members(self, provision_id: str) -> Any:
        return self.wrapped.article_family_members(provision_id)


class RecordingReranker:
    def __init__(self, wrapped: Any, trace: Dict[str, Any]):
        self.wrapped, self.trace = wrapped, trace
    def rerank(self, query_text: str, hits: Sequence[Any], top_k: int) -> list[float]:
        selected = list(hits[:top_k])
        sibling = bool(selected) and all(hit.first_stage_score is None for hit in selected)
        record = {"kind": "article_family_sibling" if sibling else "request",
                  "utf8_hex": query_text.encode("utf-8").hex(),
                  "provision_ids": [hit.document.provision_id for hit in selected]}
        self.trace["bge_calls"].append(record)
        if not sibling:
            self.trace["bge_request_queries"].append(record)
        return self.wrapped.rerank(query_text, hits, top_k)


def pipeline_from_parts(config: Mapping[str, Any], first_stage: Any, reranker: Any) -> Any:
    from retrieval.pipeline import RetrievalPipeline
    return RetrievalPipeline(first_stage, reranker, rerank_pool_k=config["rerank_pool_k"],
        final_top_k=config["final_top_k"], rerank_query_mode=config["rerank_query_mode"],
        candidate_selection=config["candidate_selection"], per_evidence_min_k=config["per_evidence_min_k"],
        dedup_mode=config["dedup_mode"], candidate_budget_scope=config["candidate_budget_scope"],
        round_merge_mode=config["round_merge_mode"],
        article_family_sibling_rerank_expansion=config["article_family_sibling_rerank_expansion"],
        article_family_expansion_trigger_top_k=config["article_family_expansion_trigger_top_k"],
        article_family_expansion_max_siblings_per_root=config["article_family_expansion_max_siblings_per_root"],
        article_family_expansion_max_siblings_per_request=config["article_family_expansion_max_siblings_per_request"],
        article_family_expansion_max_family_members_scored=config["article_family_expansion_max_family_members_scored"])


def frozen_artifact_paths(artifact_root: Path) -> Dict[str, Path]:
    return {"vectors": artifact_root / "data/koblex/indexes/kure-v1/vectors.f32.npy",
        "ids": artifact_root / "data/koblex/indexes/kure-v1/provision_ids.txt",
        "corpus": artifact_root / "data/koblex/normalized/statute.jsonl",
        "kure": artifact_root / "models/huggingface/nlpai-lab--KURE-v1",
        "bge": artifact_root / "models/huggingface/dragonkue--bge-reranker-v2-m3-ko",
        "kure_weights": artifact_root / "models/huggingface/nlpai-lab--KURE-v1/model.safetensors",
        "bge_weights": artifact_root / "models/huggingface/dragonkue--bge-reranker-v2-m3-ko/model.safetensors"}


def audit_corpus_family_bound(corpus_path: Path) -> int:
    """Reproduce the source-index alias grouping without creating a retriever."""
    families: Dict[str, set[tuple[str, str]]] = {}
    with corpus_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                record = json.loads(line)
                source_index = record.get("source_index")
                if not isinstance(source_index, str) or not source_index.strip():
                    continue
                statute_name = record["statute_name"]
                provision_text = record["provision_text"]
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ProbeSafetyError("invalid frozen normalized corpus line %d" % line_number) from exc
            family = source_index.strip()
            alias = (
                re.sub(r"\\s+", " ", statute_name).strip(),
                re.sub(r"\\s+", " ", provision_text).strip(),
            )
            families.setdefault(family, set()).add(alias)
    observed = max((len(members) for members in families.values()), default=0)
    if observed != CORPUS_OBSERVED_MAX_FAMILY_MEMBERS:
        raise ProbeSafetyError("frozen corpus family maximum changed: %d" % observed)
    if observed > FAMILY_MEMBER_BOUND:
        raise ProbeSafetyError("frozen corpus exceeds article-family hard scoring bound")
    return observed


def validate_frozen_artifacts(paths: Mapping[str, Path]) -> Dict[str, str]:
    if not all(path.exists() for path in paths.values()):
        raise ProbeSafetyError("frozen KURE/BGE artifact is missing")
    expected = {"vectors": KURE_VECTORS_SHA256, "ids": KURE_PROVISION_IDS_SHA256,
        "corpus": NORMALIZED_CORPUS_SHA256, "kure_weights": KURE_MODEL_WEIGHTS_SHA256,
        "bge_weights": BGE_MODEL_WEIGHTS_SHA256}
    actual = {name: sha256_file(paths[name]) for name in expected}
    mismatched = sorted(name for name in expected if actual[name] != expected[name])
    if mismatched:
        raise ProbeSafetyError("frozen artifact SHA-256 mismatch: %s" % ", ".join(mismatched))
    audit_corpus_family_bound(paths["corpus"])
    return actual


def production_pipeline_factory(config: Mapping[str, Any], artifact_root: Path, trace: Dict[str, Any]) -> Any:
    """The only real-execution path: exact local KURE -> local BGE, CUDA only."""
    from retrieval.persistent import KureExactIndexSearcher
    from retrieval.reranker import LocalBgeCrossEncoderReranker
    if config.get("retriever") != "kure":
        raise ProbeSafetyError("BM25/hybrid first stage is forbidden")
    paths = frozen_artifact_paths(artifact_root)
    validate_frozen_artifacts(paths)
    first = RecordingFirstStage(KureExactIndexSearcher(vectors_path=paths["vectors"],
        provision_ids_path=paths["ids"], normalized_corpus_path=paths["corpus"],
        model_path=paths["kure"], device="cuda"), trace)
    bge = RecordingReranker(LocalBgeCrossEncoderReranker(paths["bge"], device="cuda",
        document_mode=config["rerank_document_mode"]), trace)
    return pipeline_from_parts(config, first, bge)


def artifact_fingerprints(artifact_root: Path) -> Dict[str, str]:
    # Resume verification must receive the same fail-closed artifact check as
    # a fresh production factory, before either path can claim a binding.
    validate_frozen_artifacts(frozen_artifact_paths(artifact_root))
    def tree_sha(path: Path) -> str:
        digest = hashlib.sha256()
        for member in sorted(item for item in path.rglob("*") if item.is_file()):
            digest.update(member.relative_to(path).as_posix().encode("utf-8")); digest.update(b"\0")
            digest.update(sha256_file(member).encode("ascii")); digest.update(b"\n")
        return digest.hexdigest()
    paths = {"kure_vectors": artifact_root / "data/koblex/indexes/kure-v1/vectors.f32.npy",
        "kure_provision_ids": artifact_root / "data/koblex/indexes/kure-v1/provision_ids.txt",
        "normalized_corpus": artifact_root / "data/koblex/normalized/statute.jsonl",
        "kure_model_tree": artifact_root / "models/huggingface/nlpai-lab--KURE-v1",
        "bge_model_tree": artifact_root / "models/huggingface/dragonkue--bge-reranker-v2-m3-ko"}
    output = {}
    for name, path in paths.items():
        if not path.exists(): raise ProbeSafetyError("frozen artifact missing: %s" % path)
        output[name] = tree_sha(path) if path.is_dir() else sha256_file(path)
    if output["kure_provision_ids"] != KURE_PROVISION_IDS_SHA256:
        raise ProbeSafetyError("KURE provision id hash mismatch")
    return output


def audit_siblings(profile: SourceProfile, stages: Sequence[Mapping[str, Any]], *, enabled: bool) -> Dict[str, Any]:
    triggers = [record for record in stages if record["candidate_stage"] == "article_family_expansion_trigger"]
    siblings = [record for record in stages if record["candidate_stage"] == "article_family_sibling_rerank"]
    observed = max((record["article_family_sibling_candidate_count"] + 1 for record in triggers), default=0)
    if observed > FAMILY_MEMBER_BOUND:
        raise ProbeSafetyError("article family exceeded hard scoring bound")
    if enabled and profile.expected_root_provision_id:
        expected_root = canonical_koblex_suffix(profile.expected_root_provision_id, "expected root")
        expected_siblings = _canonical_expected_ids(profile.expected_scored_sibling_ids, "expected sibling")
        if expected_root in expected_siblings:
            raise ProbeSafetyError("expected root is also an expected sibling")
        trigger_ids = _canonical_stage_ids(triggers, "provision_id", "family trigger")
        if expected_root not in trigger_ids:
            raise ProbeSafetyError("qa125 root family was not audited")
        _canonical_stage_ids(siblings, "article_family_root_provision_id", "sibling root")
        scored_records = [record for record in siblings if canonical_koblex_suffix(
            record.get("article_family_root_provision_id"), "sibling root.article_family_root_provision_id"
        ) == expected_root]
        scored = _canonical_stage_ids(scored_records, "provision_id", "scored sibling")
        missing = sorted(expected_siblings - set(scored))
        if missing: raise ProbeSafetyError("qa125 siblings not all BGE-scored: %s" % ", ".join(missing))
        expected_available = canonical_koblex_suffix(profile.expected_available_provision_id, "expected available provision")
        if expected_available not in scored:
            raise ProbeSafetyError("qa125 #232732 availability is absent")
    return {"trigger_records": triggers, "sibling_records": siblings,
        "max_observed_family_members": observed, "hard_family_member_bound": FAMILY_MEMBER_BOUND,
        "known_corpus_observed_max_family_members": CORPUS_OBSERVED_MAX_FAMILY_MEMBERS}


PipelineFactory = Callable[[Mapping[str, Any], Dict[str, Any]], Any]


def run_condition(bundle: SourceBundle, configuration: Mapping[str, Any], factory: PipelineFactory) -> Dict[str, Any]:
    """The retrieval-only boundary: one pipeline.retrieve(..., round=1), no gold."""
    from harness.tracing import to_primitive
    from harness.validation import validate_retrieval_candidates, validate_retrieval_stage_records
    trace: Dict[str, Any] = {"kure_queries": [], "bge_calls": [], "bge_request_queries": []}
    pipeline = factory(configuration, trace)
    candidates = pipeline.retrieve(bundle.requests, retrieval_round=1)
    validate_retrieval_candidates(candidates, bundle.requests, retrieval_round=1)
    validate_retrieval_stage_records(pipeline.last_stage_records, bundle.requests, retrieval_round=1)
    stages = [to_primitive(record) for record in pipeline.last_stage_records]
    return {"configuration": dict(configuration), "candidates": [to_primitive(item) for item in candidates],
        "stage_records": stages, "query_trace": trace,
        "stage_provision_ids": {stage: [record["provision_id"] for record in stages if record["candidate_stage"] == stage]
            for stage in sorted({record["candidate_stage"] for record in stages})},
        "sibling_audit": audit_siblings(bundle.profile, stages,
            enabled=configuration["article_family_sibling_rerank_expansion"])}


def candidate_code_binding() -> Dict[str, str]:
    try:
        commit = subprocess.check_output(["git", "rev-parse", C15_1_COMMIT], cwd=PROJECT_ROOT, text=True).strip()
        tree = subprocess.check_output(["git", "rev-parse", C15_1_COMMIT + "^{tree}"], cwd=PROJECT_ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ProbeSafetyError("C15.1 candidate commit/tree unavailable") from exc
    if commit != C15_1_COMMIT or tree != C15_1_TREE:
        raise ProbeSafetyError("C15.1 candidate commit/tree mismatch")
    return {"commit": commit, "tree": tree}


def immutable_binding(bundle: SourceBundle, artifact_hashes: Mapping[str, str]) -> Dict[str, Any]:
    return {"source": {"profile": bundle.profile.__dict__, "binding": dict(bundle.source_binding)},
        "candidate_code": candidate_code_binding(), "artifact_hashes": dict(artifact_hashes)}


def verify_resume(output_dir: Path, bundle: SourceBundle, artifact_hashes: Mapping[str, str]) -> Path:
    """Verify a sealed output without constructing a retriever or rerunning it."""
    assert_safe_output(output_dir)
    result_path = output_dir / "probe.json"
    if not result_path.is_file():
        raise ProbeSafetyError("resume output has no probe.json")
    existing = read_json(result_path)
    expected = canonical_sha256(immutable_binding(bundle, artifact_hashes))
    if existing.get("immutable_binding_sha256") != expected:
        raise ProbeSafetyError("resume binding mismatch; refusing rerun")
    return result_path


def run_retrieval_only_probe(bundle: SourceBundle, factory: PipelineFactory, artifact_hashes: Mapping[str, str]) -> Dict[str, Any]:
    baseline_config, enabled_config = dict(bundle.retrieval_configuration), dict(bundle.retrieval_configuration)
    baseline_config["article_family_sibling_rerank_expansion"] = False
    enabled_config["article_family_sibling_rerank_expansion"] = True
    baseline, enabled = run_condition(bundle, baseline_config, factory), run_condition(bundle, enabled_config, factory)
    changed = {name for name in set(baseline_config) | set(enabled_config) if baseline_config.get(name) != enabled_config.get(name)}
    if changed != {"article_family_sibling_rerank_expansion"}:
        raise ProbeSafetyError("paired configs differ outside expansion: %s" % sorted(changed))
    if baseline["query_trace"]["kure_queries"] != enabled["query_trace"]["kure_queries"]:
        raise ProbeSafetyError("KURE query bytes differ between conditions")
    if baseline["query_trace"]["bge_request_queries"] != enabled["query_trace"]["bge_request_queries"]:
        raise ProbeSafetyError("BGE request query bytes differ between conditions")
    binding = immutable_binding(bundle, artifact_hashes)
    result = {"schema_version": "c15_2_saved_s1_retrieval_only_probe_v1",
        "generation_kind": "retrieval_only_c15_1_sibling_expansion_probe", "retrieval_sealed": True,
        **binding,
        "baseline_feature_disabled": baseline, "enabled_c15_1": enabled, "post_hoc_gold": None}
    result["immutable_binding_sha256"] = canonical_sha256(binding)
    return result


def score_post_hoc_gold(sealed_result: Mapping[str, Any], gold_jsonl: Path) -> Dict[str, Any]:
    """Separated scoring: no retrieval/cap/config object enters this function."""
    if sealed_result.get("retrieval_sealed") is not True:
        raise ProbeSafetyError("gold may be read only after retrieval is sealed")
    if not gold_jsonl.is_file(): raise ProbeSafetyError("post-hoc gold file is missing")
    question_id = sealed_result["source"]["profile"]["question_id"]
    rows = [json.loads(line) for line in gold_jsonl.read_text(encoding="utf-8").splitlines() if line]
    matching = [row for row in rows if row.get("question_id") == question_id]
    if len(matching) != 1 or not matching[0].get("provision_ids"):
        raise ProbeSafetyError("post-hoc gold must contain one nonempty matching row")
    gold_ids, conditions = set(matching[0]["provision_ids"]), {}
    for name in ("baseline_feature_disabled", "enabled_c15_1"):
        ids = {item["provision_id"] for item in sealed_result[name]["candidates"]}
        conditions[name] = {"gold_overlap_provision_ids": sorted(ids & gold_ids),
            "complete_gold_evidence": gold_ids <= ids, "candidate_provision_ids": sorted(ids)}
    return {"phase": "post_hoc_only", "question_id": question_id, "conditions": conditions}


def write_result(output_dir: Path, result: Mapping[str, Any], resume: bool) -> Path:
    assert_safe_output(output_dir); result_path = output_dir / "probe.json"
    if output_dir.exists():
        if not resume: raise ProbeSafetyError("output exists; refusing overwrite")
        if not result_path.is_file() or read_json(result_path).get("immutable_binding_sha256") != result.get("immutable_binding_sha256"):
            raise ProbeSafetyError("resume binding mismatch; refusing overwrite")
        return result_path
    output_dir.mkdir(parents=True, exist_ok=False)
    temporary = output_dir / "probe.json.tmp"
    temporary.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(result_path)
    return result_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question-id", choices=sorted(SOURCE_PROFILES), required=True)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--artifact-root", type=Path, default=Path("/workspace/Legal-Harness"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--post-hoc-gold-jsonl", type=Path)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args(); assert_safe_output(args.output_dir)
    if args.output_dir.exists() and not args.resume:
        raise ProbeSafetyError("output exists; refusing overwrite")
    bundle = load_saved_source(args.source_root, args.question_id)
    artifacts = artifact_fingerprints(args.artifact_root)
    if args.resume:
        print(verify_resume(args.output_dir, bundle, artifacts))
        return 0
    result = run_retrieval_only_probe(bundle,
        lambda config, trace: production_pipeline_factory(config, args.artifact_root, trace), artifacts)
    if args.post_hoc_gold_jsonl:
        result["post_hoc_gold"] = score_post_hoc_gold(result, args.post_hoc_gold_jsonl)
    print(write_result(args.output_dir, result, False)); return 0


if __name__ == "__main__":
    try: raise SystemExit(main())
    except ProbeSafetyError as exc: raise SystemExit("C15.2 retrieval-only probe blocked: %s" % exc)
