#!/usr/bin/env python3
"""Replay C02 candidate-selection hypotheses from immutable saved traces.

This program is deliberately *offline*.  It only reads the C02 source-row map,
its immutable ``retrieval_stages.jsonl`` sidecars, persisted result state, and
the static KoBLEX dataset/corpus.  It never imports or invokes a retriever,
reranker, LLM, GPU backend, BM25, ParSeR, or LF-Eval.

Gold groups are constructed by :mod:`scripts.evaluate_dev_runs` only after all
counterfactual selections have been made.  No gold information is exposed to a
selection hypothesis or used to choose a policy.

The primary cohort is the frozen evaluator's normal-outcome cohort (ANSWER and
ABSTAIN: 218 rows).  The seven execution-failure rows which still have saved
stage sidecars are emitted solely as a separately-labelled stage appendix.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import evaluate_dev_runs as evaluator


DEFAULT_SOURCE_MAP = Path(
    "/workspace/Legal-Harness/records/"
    "v2-kure-qwen38-offline-full226-c02e281-combined226-20260826/"
    "audit/source-row-map.json"
)
DEFAULT_DATASET = Path("/workspace/Legal-Harness/data/koblex/qa/test-00000-of-00001.parquet")
DEFAULT_CORPUS = Path("/workspace/Legal-Harness/data/koblex/normalized/statute.jsonl")
SCHEMA_VERSION = "1.0"


class ReplayError(RuntimeError):
    """Raised when saved inputs cannot faithfully support a replay."""


@dataclass(frozen=True)
class SourceRow:
    ordinal: int
    question_id: str
    status: str
    metadata_path: Path
    metadata_sha256: str
    result_sha256: str
    stage_sha256: str
    stage_contract: str

    @property
    def run_directory(self) -> Path:
        return self.metadata_path.parent

    @property
    def result_path(self) -> Path:
        return self.run_directory / "result.json"

    @property
    def stage_path(self) -> Path:
        return self.run_directory / "retrieval_stages.jsonl"


@dataclass(frozen=True)
class Candidate:
    """An alias-collapsed candidate reconstructed from persisted stage rows."""

    provision_id: str
    aliases: Tuple[str, ...]
    source_request_ids: Tuple[str, ...]
    target_evidence_item_ids: Tuple[str, ...]
    rerank_score: float
    fusion_rank: int
    request_rerank_ranks: Mapping[str, int]
    request_first_stage_ranks: Mapping[str, int]
    request_first_stage_scores: Mapping[str, float]

    def rerank_rank(self, request_id: str) -> int:
        return self.request_rerank_ranks.get(request_id, _MISSING_RANK)

    def first_stage_rank(self, request_id: str) -> int:
        return self.request_first_stage_ranks.get(request_id, _MISSING_RANK)


_MISSING_RANK = 10**9


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-map", type=Path, default=DEFAULT_SOURCE_MAP)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--dynamic-top-k-cap", type=int, default=20)
    parser.add_argument("--evidence-quota", type=int, default=2)
    parser.add_argument("--rrf-k", type=int, default=60)
    return parser.parse_args()


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayError("cannot read JSON: %s" % path) from exc
    if not isinstance(value, dict):
        raise ReplayError("expected JSON object: %s" % path)
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _string_list(value: Any) -> Tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(dict.fromkeys(str(item) for item in value if str(item)))


def _int(value: Any, default: int = _MISSING_RANK) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 1 else default


def _float(value: Any, default: float = float("-inf")) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _round(record: Mapping[str, Any]) -> Optional[int]:
    value = _int(record.get("retrieval_round"), 0)
    return value if value else None


def _source_rows(source_map: Path) -> List[SourceRow]:
    payload = _read_json(source_map)
    raw_rows = payload.get("selected_rows")
    if not isinstance(raw_rows, list):
        raise ReplayError("source map lacks selected_rows")
    rows: List[SourceRow] = []
    seen: Set[str] = set()
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise ReplayError("source-map row is not an object")
        question_id = str(raw.get("question_id") or "")
        metadata_path = Path(str(raw.get("source_metadata_path") or ""))
        if not question_id or not metadata_path.is_file() or question_id in seen:
            raise ReplayError("invalid or duplicate source-map row: %s" % question_id)
        seen.add(question_id)
        provenance = raw.get("stage_provenance")
        if not isinstance(provenance, dict):
            provenance = {}
        rows.append(
            SourceRow(
                ordinal=_int(raw.get("ordinal"), 0),
                question_id=question_id,
                status=str(raw.get("status") or ""),
                metadata_path=metadata_path,
                metadata_sha256=str(raw.get("source_metadata_sha256") or ""),
                result_sha256=str(raw.get("source_result_sha256") or ""),
                stage_sha256=str(raw.get("source_retrieval_stage_sha256") or ""),
                stage_contract=str(provenance.get("contract") or ""),
            )
        )
    return sorted(rows, key=lambda row: (row.ordinal, row.question_id))


class _UnionFind:
    def __init__(self) -> None:
        self.parent: Dict[str, str] = {}

    def add(self, value: str) -> None:
        self.parent.setdefault(value, value)

    def find(self, value: str) -> str:
        self.add(value)
        root = value
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[value] != value:
            next_value = self.parent[value]
            self.parent[value] = root
            value = next_value
        return root

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


def _aliases(record: Mapping[str, Any]) -> Tuple[str, ...]:
    provision_id = str(record.get("provision_id") or "")
    aliases = list(_string_list(record.get("alias_provision_ids")))
    if provision_id and provision_id not in aliases:
        aliases.append(provision_id)
    return tuple(aliases)


def _canonical_candidates(records: Sequence[Mapping[str, Any]], retrieval_round: int) -> Dict[str, Candidate]:
    """Construct per-round alias components using persisted alias evidence only."""
    round_records = [record for record in records if _round(record) == retrieval_round]
    aliases_by_record: List[Tuple[Mapping[str, Any], Tuple[str, ...]]] = []
    union_find = _UnionFind()
    for record in round_records:
        aliases = _aliases(record)
        if not aliases:
            continue
        aliases_by_record.append((record, aliases))
        for alias in aliases:
            union_find.add(alias)
            union_find.union(aliases[0], alias)

    by_component: Dict[str, List[Tuple[Mapping[str, Any], Tuple[str, ...]]]] = defaultdict(list)
    for record, aliases in aliases_by_record:
        by_component[union_find.find(aliases[0])].append((record, aliases))

    output: Dict[str, Candidate] = {}
    for component, members in by_component.items():
        selected = [member for member in members if member[0].get("candidate_stage") == "selected"]
        source = selected if selected else members
        representative_record, representative_aliases = min(
            source,
            key=lambda item: (
                -_float(item[0].get("rerank_score")),
                _int(item[0].get("fusion_rank")),
                str(item[0].get("provision_id") or ""),
            ),
        )
        all_aliases = sorted({alias for _, aliases in members for alias in aliases})
        request_ranks: Dict[str, int] = {}
        first_ranks: Dict[str, int] = {}
        first_scores: Dict[str, float] = {}
        source_requests: List[str] = []
        evidence_ids: List[str] = []
        rerank_scores: List[float] = []
        fusion_ranks: List[int] = []
        for record, _ in members:
            request_ids = _string_list(record.get("source_request_ids"))
            for request_id in request_ids:
                if request_id not in source_requests:
                    source_requests.append(request_id)
            for evidence_id in _string_list(record.get("target_evidence_item_ids")):
                if evidence_id not in evidence_ids:
                    evidence_ids.append(evidence_id)
            stage = str(record.get("candidate_stage") or "")
            if stage == "request_rerank" and len(request_ids) == 1:
                rank = _int(record.get("rerank_rank"))
                request_id = request_ids[0]
                request_ranks[request_id] = min(request_ranks.get(request_id, rank), rank)
            if stage == "first_stage" and len(request_ids) == 1:
                rank = _int(record.get("first_stage_rank"))
                score = _float(record.get("first_stage_score"))
                request_id = request_ids[0]
                if rank < first_ranks.get(request_id, _MISSING_RANK):
                    first_ranks[request_id] = rank
                    first_scores[request_id] = score
            if stage == "selected":
                rerank_scores.append(_float(record.get("rerank_score")))
                fusion_ranks.append(_int(record.get("fusion_rank")))
        output[component] = Candidate(
            provision_id=str(representative_record.get("provision_id") or ""),
            aliases=tuple(all_aliases or representative_aliases),
            source_request_ids=tuple(source_requests),
            target_evidence_item_ids=tuple(evidence_ids),
            rerank_score=max(rerank_scores, default=_float(representative_record.get("rerank_score"))),
            fusion_rank=min(fusion_ranks, default=_int(representative_record.get("fusion_rank"))),
            request_rerank_ranks=request_ranks,
            request_first_stage_ranks=first_ranks,
            request_first_stage_scores=first_scores,
        )
    return output


def _active_requests(records: Sequence[Mapping[str, Any]], retrieval_round: int) -> List[str]:
    values: List[str] = []
    for record in records:
        if _round(record) != retrieval_round or record.get("candidate_stage") != "first_stage":
            continue
        for request_id in _string_list(record.get("source_request_ids")):
            if request_id not in values:
                values.append(request_id)
    return values


def _actual(records: Sequence[Mapping[str, Any]]) -> Dict[int, List[Tuple[str, str, Tuple[str, ...]]]]:
    selected: Dict[int, List[Tuple[int, str, str, Tuple[str, ...]]]] = defaultdict(list)
    for record in records:
        if record.get("candidate_stage") != "round_selected":
            continue
        retrieval_round = _round(record)
        provision_id = str(record.get("provision_id") or "")
        if retrieval_round is None or not provision_id:
            raise ReplayError("malformed round_selected row")
        selected[retrieval_round].append(
            (
                _int(record.get("selection_rank")),
                provision_id,
                str(record.get("selection_reason") or ""),
                _aliases(record),
            )
        )
    return {
        round_id: [(provision_id, reason, aliases) for _, provision_id, reason, aliases in sorted(items)]
        for round_id, items in selected.items()
    }


def _request_metadata(result: Mapping[str, Any]) -> Tuple[List[str], Dict[str, str], List[str]]:
    state = result.get("state")
    state = state if isinstance(state, dict) else {}
    history = state.get("query_history")
    if not isinstance(history, list):
        history = []
    order: List[str] = []
    evidence_by_request: Dict[str, str] = {}
    for request in history:
        if not isinstance(request, dict):
            continue
        request_id = str(request.get("request_id") or "")
        evidence_id = str(request.get("evidence_item_id") or "")
        if request_id and request_id not in order:
            order.append(request_id)
        if request_id and evidence_id:
            evidence_by_request[request_id] = evidence_id
    evidence = state.get("required_evidence_items")
    critical = [
        str(item.get("evidence_item_id") or "")
        for item in evidence if isinstance(evidence, list) and isinstance(item, dict) and item.get("critical") is True
    ] if isinstance(evidence, list) else []
    return order, evidence_by_request, [item for item in critical if item]


def dynamic_top_k(
    base_top_k: int,
    cap: int,
    evidence_quota: int,
    active_critical_evidence_count: int,
) -> int:
    """Bounded budget: min(cap, max(base, quota * active critical evidence))."""
    return min(cap, max(base_top_k, evidence_quota * active_critical_evidence_count))


def _ranked_for_request(candidates: Sequence[Candidate], request_id: str) -> List[Candidate]:
    return sorted(
        (candidate for candidate in candidates if candidate.rerank_rank(request_id) < _MISSING_RANK),
        key=lambda candidate: (
            candidate.rerank_rank(request_id),
            -candidate.rerank_score,
            candidate.fusion_rank,
            candidate.provision_id,
        ),
    )


def _select_with_evidence_quota(
    ranked: Sequence[Candidate], evidence_order: Sequence[str], quota: int, top_k: int
) -> List[Candidate]:
    selected: List[Candidate] = []
    for evidence_id in dict.fromkeys(evidence_order):
        while (
            sum(evidence_id in candidate.target_evidence_item_ids for candidate in selected) < quota
            and len(selected) < top_k
        ):
            candidate = next(
                (item for item in ranked if evidence_id in item.target_evidence_item_ids and item not in selected),
                None,
            )
            if candidate is None:
                break
            selected.append(candidate)
    for candidate in ranked:
        if len(selected) >= top_k:
            break
        if candidate not in selected:
            selected.append(candidate)
    return selected


def _round_robin(
    candidates: Sequence[Candidate], request_order: Sequence[str]
) -> List[Candidate]:
    queues = {request_id: _ranked_for_request(candidates, request_id) for request_id in request_order}
    offsets = {request_id: 0 for request_id in request_order}
    selected: List[Candidate] = []
    seen: Set[str] = set()
    while True:
        progressed = False
        for request_id in request_order:
            queue = queues[request_id]
            while offsets[request_id] < len(queue):
                candidate = queue[offsets[request_id]]
                offsets[request_id] += 1
                if candidate.provision_id in seen:
                    continue
                seen.add(candidate.provision_id)
                selected.append(candidate)
                progressed = True
                break
        if not progressed:
            return selected


def _rrf_score(candidate: Candidate, rrf_k: int, kure_weight: int = 1) -> float:
    score = 0.0
    for rank in candidate.request_rerank_ranks.values():
        score += 1.0 / (rrf_k + rank)
    for rank in candidate.request_first_stage_ranks.values():
        score += kure_weight / (rrf_k + rank)
    return score


def _candidate_component(candidate: Candidate) -> str:
    return min(candidate.aliases, default=candidate.provision_id)


def _first_stage_anchors(
    candidates: Sequence[Candidate], request_order: Sequence[str], max_rank: int
) -> List[Candidate]:
    anchors: List[Candidate] = []
    seen: Set[str] = set()
    for request_id in request_order:
        for candidate in sorted(
            (item for item in candidates if item.first_stage_rank(request_id) <= max_rank),
            key=lambda item: (
                item.first_stage_rank(request_id),
                -item.request_first_stage_scores.get(request_id, float("-inf")),
                item.provision_id,
            ),
        ):
            component = _candidate_component(candidate)
            if component not in seen:
                seen.add(component)
                anchors.append(candidate)
    return anchors


def _anchor_selection(
    actual: Sequence[Tuple[str, str, Tuple[str, ...]]],
    candidates: Sequence[Candidate],
    request_order: Sequence[str],
    max_rank: int,
    top_k: int,
) -> List[str]:
    # Existing critical quota selections remain locked; the KURE anchors are
    # deliberately a diagnostic preservation layer before ordinary trace fill.
    locked = [item for item in actual if item[1].startswith("critical_quota:")]
    chosen = [item[0] for item in locked]
    seen_aliases = {alias for _, _, aliases in locked for alias in aliases}
    for candidate in _first_stage_anchors(candidates, request_order, max_rank):
        if len(chosen) >= top_k or set(candidate.aliases) & seen_aliases:
            continue
        chosen.append(candidate.provision_id)
        seen_aliases.update(candidate.aliases)
    for provision_id, _, aliases in actual:
        if len(chosen) >= top_k:
            break
        if set(aliases) & seen_aliases:
            continue
        chosen.append(provision_id)
        seen_aliases.update(aliases)
    return chosen


def _variant_rounds(
    records: Sequence[Mapping[str, Any]], result: Mapping[str, Any], top_k: int,
    dynamic_cap: int, evidence_quota: int, rrf_k: int,
) -> Tuple[Dict[str, Dict[int, List[str]]], Dict[str, Any]]:
    actual_by_round = _actual(records)
    global_request_order, evidence_by_request, critical = _request_metadata(result)
    candidate_components = {
        retrieval_round: _canonical_candidates(records, retrieval_round)
        for retrieval_round in sorted(actual_by_round)
    }
    variants: Dict[str, Dict[int, List[str]]] = {
        "current_trace": {round_id: [item[0] for item in selected] for round_id, selected in actual_by_round.items()},
        "request_local_best_rank": {},
        "request_local_rrf": {},
        "request_rank_round_robin_quota2_dynamic": {},
        "diagnostic_kure_first_stage_top1_anchor": {},
        "diagnostic_kure_first_stage_top2_anchor": {},
        "diagnostic_equal_kure_bge_rrf": {},
        "diagnostic_kure2x_bge_rrf": {},
    }
    dynamic_budget: Dict[str, int] = {}
    for retrieval_round in sorted(actual_by_round):
        active = [request_id for request_id in global_request_order if request_id in _active_requests(records, retrieval_round)]
        active.extend(request_id for request_id in _active_requests(records, retrieval_round) if request_id not in active)
        if not active:
            raise ReplayError("round has no active requests: %d" % retrieval_round)
        candidates = list(candidate_components[retrieval_round].values())
        bge_pool = [candidate for candidate in candidates if candidate.request_rerank_ranks]
        if not bge_pool:
            raise ReplayError("round has no saved request-rerank candidates: %d" % retrieval_round)
        active_evidence_ids = [
            evidence_by_request[request_id]
            for request_id in active if request_id in evidence_by_request
        ]
        active_critical_evidence_ids = list(
            dict.fromkeys(
                evidence for evidence in critical if evidence in set(active_evidence_ids)
            )
        )
        if not active_critical_evidence_ids:
            raise ReplayError(
                "round has no active critical evidence IDs: %d" % retrieval_round
            )
        by_best_rank = sorted(
            bge_pool,
            key=lambda candidate: (
                min(candidate.request_rerank_ranks.values()),
                -candidate.rerank_score,
                candidate.fusion_rank,
                candidate.provision_id,
            ),
        )
        by_rrf = sorted(
            bge_pool,
            key=lambda candidate: (-_rrf_score(candidate, rrf_k, 0), -candidate.rerank_score, candidate.provision_id),
        )
        by_equal_rrf = sorted(
            bge_pool,
            key=lambda candidate: (-_rrf_score(candidate, rrf_k, 1), -candidate.rerank_score, candidate.provision_id),
        )
        by_kure2x_rrf = sorted(
            bge_pool,
            key=lambda candidate: (-_rrf_score(candidate, rrf_k, 2), -candidate.rerank_score, candidate.provision_id),
        )
        variants["request_local_best_rank"][retrieval_round] = [
            candidate.provision_id for candidate in _select_with_evidence_quota(by_best_rank, active_critical_evidence_ids, 1, top_k)
        ]
        variants["request_local_rrf"][retrieval_round] = [
            candidate.provision_id for candidate in _select_with_evidence_quota(by_rrf, active_critical_evidence_ids, 1, top_k)
        ]
        dynamic_k = dynamic_top_k(top_k, dynamic_cap, evidence_quota, len(active_critical_evidence_ids))
        dynamic_budget[str(retrieval_round)] = dynamic_k
        rr_order = _round_robin(bge_pool, active)
        variants["request_rank_round_robin_quota2_dynamic"][retrieval_round] = [
            candidate.provision_id
            for candidate in _select_with_evidence_quota(rr_order, active_critical_evidence_ids, evidence_quota, dynamic_k)
        ]
        variants["diagnostic_kure_first_stage_top1_anchor"][retrieval_round] = _anchor_selection(
            actual_by_round[retrieval_round], candidates, active, 1, top_k
        )
        variants["diagnostic_kure_first_stage_top2_anchor"][retrieval_round] = _anchor_selection(
            actual_by_round[retrieval_round], candidates, active, 2, top_k
        )
        variants["diagnostic_equal_kure_bge_rrf"][retrieval_round] = [
            candidate.provision_id for candidate in _select_with_evidence_quota(by_equal_rrf, active_critical_evidence_ids, 1, top_k)
        ]
        variants["diagnostic_kure2x_bge_rrf"][retrieval_round] = [
            candidate.provision_id for candidate in _select_with_evidence_quota(by_kure2x_rrf, active_critical_evidence_ids, 1, top_k)
        ]
    carryover = {
        "status": "UNVERIFIED",
        "problems": ["per_round_s2_support_unavailable"],
        "variant_name": "diagnostic_carryover_request_rank_top1_guarded_swap",
    }
    return variants, {
        "carryover": carryover,
        "dynamic_top_k_formula": "min(dynamic_top_k_cap, max(top_k, evidence_quota * active_critical_evidence_count))",
        "dynamic_top_k_by_round": dynamic_budget,
    }


def _final_metrics(selected_by_round: Mapping[int, Sequence[str]], groups: Sequence[evaluator.GoldGroup]) -> Tuple[Optional[int], Dict[str, Any], List[str]]:
    cumulative: Set[str] = set()
    first_complete: Optional[int] = None
    for retrieval_round in sorted(selected_by_round):
        cumulative.update(selected_by_round[retrieval_round])
        if first_complete is None and evaluator.precision_recall_f1(cumulative, groups)["complete"]:
            first_complete = retrieval_round
    return first_complete, evaluator.precision_recall_f1(cumulative, groups), sorted(cumulative)


def _churn(actual: Mapping[int, Sequence[str]], variant: Mapping[int, Sequence[str]]) -> Dict[str, Any]:
    changed_rounds = 0
    inserted = evicted = positional = 0
    for retrieval_round in sorted(set(actual) | set(variant)):
        before, after = list(actual.get(retrieval_round, [])), list(variant.get(retrieval_round, []))
        if before != after:
            changed_rounds += 1
        inserted += len(set(after) - set(before))
        evicted += len(set(before) - set(after))
        positional += sum(
            (before[index] if index < len(before) else None) != (after[index] if index < len(after) else None)
            for index in range(max(len(before), len(after)))
        )
    return {"changed_rounds": changed_rounds, "inserted_slots": inserted, "evicted_slots": evicted, "position_changed_slots": positional}


def _micro(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    true_positive = sum(int(row["metrics"]["true_positive"]) for row in rows)
    predicted = sum(int(row["metrics"]["predicted"]) for row in rows)
    gold = sum(int(row["metrics"]["gold"]) for row in rows)
    return {
        "true_positive": true_positive,
        "predicted": predicted,
        "gold": gold,
        "candidate_precision": true_positive / predicted if predicted else 0.0,
        "recall": true_positive / gold if gold else 0.0,
    }


def _summary_variant(name: str, rows: Sequence[Mapping[str, Any]], actual: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    complete_ids = sorted(row["question_id"] for row in rows if row["metrics"]["complete"])
    actual_complete = {question_id for question_id, row in actual.items() if row["metrics"]["complete"]}
    actual_final = {question_id: set(row["final_ids"]) for question_id, row in actual.items()}
    changed_question_ids = sorted(
        row["question_id"] for row in rows if set(row["final_ids"]) != actual_final[row["question_id"]]
    )
    by_hop: Dict[str, Any] = {}
    for hop in sorted({int(row["n_hops"]) for row in rows}):
        subset = [row for row in rows if int(row["n_hops"]) == hop]
        by_hop[str(hop)] = {
            "question_count": len(subset),
            "complete_evidence_count": sum(bool(row["metrics"]["complete"]) for row in subset),
            "micro": _micro(subset),
        }
    churn = Counter()
    for row in rows:
        churn.update(row["churn"])
    return {
        "name": name,
        "question_count": len(rows),
        "complete_evidence_count": len(complete_ids),
        "complete_evidence_question_ids": complete_ids,
        "micro": _micro(rows),
        "macro_recall": mean(float(row["metrics"]["recall"]) for row in rows),
        "by_hop": by_hop,
        "gained_question_ids": sorted(set(complete_ids) - actual_complete),
        "lost_question_ids": sorted(actual_complete - set(complete_ids)),
        "changed_final_candidate_question_ids": changed_question_ids,
        "changed_final_candidate_question_count": len(changed_question_ids),
        "churn": dict(sorted(churn.items())),
    }


def _roster(rows: Sequence[SourceRow], statuses: Set[str], require_stage: bool) -> List[SourceRow]:
    output = []
    for row in rows:
        if row.status not in statuses:
            continue
        if require_stage and not row.stage_path.is_file():
            continue
        output.append(row)
    return output


def _input_hashes(source_map: Path, dataset: Path, corpus: Path, rows: Sequence[SourceRow]) -> Dict[str, Any]:
    mismatches: List[str] = []
    for row in rows:
        for path, expected, label in (
            (row.metadata_path, row.metadata_sha256, "metadata"),
            (row.result_path, row.result_sha256, "result"),
            (row.stage_path, row.stage_sha256, "retrieval_stages"),
        ):
            if expected and _sha256(path) != expected:
                mismatches.append("%s:%s" % (row.question_id, label))
    if mismatches:
        raise ReplayError("source hash mismatch: %s" % ", ".join(mismatches))
    return {
        "source_map": {"path": str(source_map), "sha256": _sha256(source_map)},
        "dataset": {"path": str(dataset), "sha256": _sha256(dataset)},
        "corpus": {"path": str(corpus), "sha256": _sha256(corpus)},
        "evaluator": {
            "path": str(PROJECT_ROOT / "scripts/evaluate_dev_runs.py"),
            "sha256": _sha256(PROJECT_ROOT / "scripts/evaluate_dev_runs.py"),
            "schema_version": evaluator.EVALUATION_SCHEMA_VERSION,
        },
        "source_rows_hash_verified": len(rows),
    }


def _analyze_cohort(
    cohort_name: str, rows: Sequence[SourceRow], questions: Mapping[str, Mapping[str, Any]],
    groups: Mapping[str, Sequence[evaluator.GoldGroup]], top_k: int, dynamic_cap: int,
    evidence_quota: int, rrf_k: int,
) -> Dict[str, Any]:
    rows_by_variant: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    actual_rows: Dict[str, Dict[str, Any]] = {}
    fidelity_mismatches: List[str] = []
    carryover_statuses: Dict[str, Any] = {}
    for source in rows:
        result = _read_json(source.result_path)
        if str(result.get("status") or "") != source.status:
            raise ReplayError("result/source-map status mismatch: %s" % source.question_id)
        records = evaluator._read_jsonl(source.stage_path)
        variants, provenance = _variant_rounds(records, result, top_k, dynamic_cap, evidence_quota, rrf_k)
        carryover_statuses[source.question_id] = provenance["carryover"]
        actual_rounds = variants["current_trace"]
        state = result.get("state") if isinstance(result.get("state"), dict) else {}
        state_ids = {
            str(candidate.get("provision_id") or "")
            for candidate in state.get("candidate_provisions", [])
            if isinstance(candidate, dict) and str(candidate.get("provision_id") or "")
        }
        if set().union(*(set(ids) for ids in actual_rounds.values())) != state_ids:
            fidelity_mismatches.append(source.question_id)
        for name, selected_by_round in variants.items():
            first_complete, metrics, final_ids = _final_metrics(selected_by_round, groups[source.question_id])
            current = variants["current_trace"]
            row = {
                "question_id": source.question_id,
                "n_hops": int(questions[source.question_id]["n_hops"]),
                "first_complete_round": first_complete,
                "metrics": metrics,
                "final_ids": final_ids,
                "churn": _churn(current, selected_by_round),
            }
            rows_by_variant[name].append(row)
            if name == "current_trace":
                actual_rows[source.question_id] = row
    summaries = {
        name: _summary_variant(name, variant_rows, actual_rows)
        for name, variant_rows in sorted(rows_by_variant.items())
    }
    unverified = sorted(question_id for question_id, value in carryover_statuses.items() if value["status"] != "VERIFIED")
    return {
        "cohort": cohort_name,
        "question_count": len(rows),
        "trace_fidelity": {
            "round_selected_matches_final_candidate_count": len(rows) - len(fidelity_mismatches),
            "round_selected_final_candidate_mismatch_question_ids": fidelity_mismatches,
        },
        "carryover_provenance": {
            "status": "VERIFIED" if not unverified else "UNVERIFIED",
            "unverified_question_ids": unverified,
            "per_question": carryover_statuses,
        },
        "variants": summaries,
        "per_question": {name: variant_rows for name, variant_rows in sorted(rows_by_variant.items())},
    }


def analyze(
    source_map: Path, dataset: Path, corpus: Path, top_k: int = 10,
    dynamic_cap: int = 20, evidence_quota: int = 2, rrf_k: int = 60,
) -> Dict[str, Any]:
    if top_k < 1 or dynamic_cap < top_k or evidence_quota < 1 or rrf_k < 1:
        raise ReplayError("invalid selection parameters")
    source_rows = _source_rows(source_map)
    primary = _roster(source_rows, set(evaluator.NORMAL_OUTCOME_STATUSES), True)
    appendix = _roster(source_rows, set(evaluator.OUTCOME_STATUSES), True)
    if len(primary) != 218:
        raise ReplayError("primary cohort must be 218 normal rows, found %d" % len(primary))
    if len(appendix) != 225:
        raise ReplayError("stage appendix must be 225 rows, found %d" % len(appendix))
    questions = evaluator.load_dataset(dataset)
    wanted_indexes = {
        str(context["index"])
        for row in appendix for context in questions[row.question_id]["contexts"]
    }
    groups = evaluator.build_gold_groups(
        questions, [row.question_id for row in appendix], evaluator.load_corpus(corpus, wanted_indexes)
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "offline_static_only": True,
        "gold_analysis_only": True,
        "s2_s3_replayed": False,
        "runtime_retrieval_selection_modified": False,
        "selection_hypotheses": {
            "request_local_best_rank": "min per-request BGE rerank rank, quota 1 for active critical evidence, then fill",
            "request_local_rrf": "sum(1 / (rrf_k + per-request BGE rerank rank)), quota 1, then fill",
            "request_rank_round_robin_quota2_dynamic": "two candidates per active critical evidence then request-local round-robin; K=min(cap,max(base,quota*active_critical_evidence_count))",
            "diagnostics": "KURE anchors and KURE+BGE RRF are same-trace diagnostics, not runtime recommendations",
            "carryover": "excluded as UNVERIFIED: saved sidecars do not preserve per-round S2 support decisions",
        },
        "parameters": {
            "top_k": top_k, "dynamic_top_k_cap": dynamic_cap,
            "evidence_quota": evidence_quota, "rrf_k": rrf_k,
        },
        "inputs": _input_hashes(source_map, dataset, corpus, appendix),
        "primary_218_normal_outcomes": _analyze_cohort(
            "primary_218_normal_outcomes", primary, questions, groups, top_k, dynamic_cap, evidence_quota, rrf_k
        ),
        "stage_appendix_225_including_execution_failures": _analyze_cohort(
            "stage_appendix_225_including_execution_failures", appendix, questions, groups, top_k, dynamic_cap, evidence_quota, rrf_k
        ),
    }


def _markdown(summary: Mapping[str, Any]) -> str:
    primary = summary["primary_218_normal_outcomes"]
    lines = [
        "# C02 saved-candidate hypothesis replay",
        "",
        "This is static same-trace analysis only. Gold is used after selection for metrics, never as policy input. No retrieval, reranking, S1/S2/S3, BM25, GPU, ParSeR, or LF-Eval ran.",
        "",
        "## Primary cohort: 218 normal outcomes",
        "",
        "| Variant | Complete | Micro precision | Micro recall | Gains | Losses | Changed rounds | Inserted / evicted slots |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, value in primary["variants"].items():
        micro = value["micro"]
        churn = value["churn"]
        lines.append(
            "| %s | %d/%d | %.6f | %.6f | %d | %d | %d | %d / %d |"
            % (name, value["complete_evidence_count"], value["question_count"], micro["candidate_precision"], micro["recall"], len(value["gained_question_ids"]), len(value["lost_question_ids"]), churn["changed_rounds"], churn["inserted_slots"], churn["evicted_slots"])
        )
    lines.extend(["", "## By-hop complete evidence", ""])
    for name, value in primary["variants"].items():
        hops = ", ".join(
            "hop%s=%d/%d" % (hop, row["complete_evidence_count"], row["question_count"])
            for hop, row in value["by_hop"].items()
        )
        lines.append("- %s: %s" % (name, hops))
    lines.extend([
        "", "## Provenance and caveats", "",
        "- Primary is 218 ANSWER/ABSTAIN rows. The 225 stage-backed-row output is an appendix only and includes seven execution failures.",
        "- Carry-over is %s for the primary cohort; it is omitted rather than inferred when provenance is insufficient." % primary["carryover_provenance"]["status"],
        "- The dynamic round-robin budget is `min(dynamic_top_k_cap, max(top_k, evidence_quota * active_critical_evidence_count))`.",
        "- Gains/losses and detailed per-question churn are in `summary.json`; no variant is an answer-quality or runtime-adoption claim.",
    ])
    return "\n".join(lines) + "\n"


def write_outputs(summary: Mapping[str, Any], output_dir: Path) -> None:
    if output_dir.exists():
        raise ReplayError("refusing to overwrite output directory: %s" % output_dir)
    output_dir.mkdir(parents=True)
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "summary.md").write_text(_markdown(summary), encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        summary = analyze(
            args.source_map.resolve(), args.dataset.resolve(), args.corpus.resolve(),
            args.top_k, args.dynamic_top_k_cap, args.evidence_quota, args.rrf_k,
        )
        write_outputs(summary, args.output_dir.resolve())
    except ReplayError as exc:
        print("candidate replay refused: %s" % exc, file=sys.stderr)
        return 2
    print("wrote %s" % args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
