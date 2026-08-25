#!/usr/bin/env python3
"""Compare round-merge counterfactuals from immutable C5 retrieval traces.

This is deliberately offline.  It reads persisted sidecars and result records;
it never invokes a retriever, reranker, skill, LLM, Ollama, or LF-Eval.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import evaluate_dev_runs as evaluator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BATCH_DIR = (
    PROJECT_ROOT
    / "records/batches/kure-c5-full226-20260822-a74e76d/combined-checkpoint-226"
)
DEFAULT_DATASET = PROJECT_ROOT / "data/koblex/qa/test-00000-of-00001.parquet"
DEFAULT_CORPUS = PROJECT_ROOT / "data/koblex/normalized/statute.jsonl"
DEFAULT_PAIRED_CSV = (
    PROJECT_ROOT
    / "records/evaluations/"
    "kure-bge-abstain-repair-d4-qwen38-q8-226-20260820-reconciled-20260821/"
    "per_question.csv"
)


@dataclass(frozen=True)
class TraceCandidate:
    provision_id: str
    issue_id: str
    rerank_score: float
    fusion_rank: int
    source_request_ids: Tuple[str, ...]
    target_evidence_item_ids: Tuple[str, ...]
    alias_provision_ids: Tuple[str, ...]
    request_rerank_ranks: Mapping[str, int]

    @property
    def normalized_rerank_rank(self) -> int:
        return min(self.request_rerank_ranks.values(), default=10**9)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-dir", type=Path, default=DEFAULT_BATCH_DIR)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--paired-csv", type=Path, default=DEFAULT_PAIRED_CSV)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument(
        "--assert-c5-expected",
        action="store_true",
        help="fail if the documented C5 normal-222 conservative values differ",
    )
    return parser.parse_args()


def _read_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise evaluator.EvaluationError("expected object: %s" % path)
    return payload


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    return evaluator._read_jsonl(path)


def _as_string_list(value: Any) -> Tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(dict.fromkeys(str(item) for item in value if str(item)))


def _as_int(value: Any, default: int = 10**9) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 1 else default


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("-inf")


def _candidate_key(candidate: TraceCandidate) -> Tuple[float, int, str, str]:
    return (
        -candidate.rerank_score,
        candidate.fusion_rank,
        candidate.provision_id,
        candidate.issue_id,
    )


def _rank_key(candidate: TraceCandidate) -> Tuple[int, float, int, str, str]:
    return (
        candidate.normalized_rerank_rank,
        -candidate.rerank_score,
        candidate.fusion_rank,
        candidate.provision_id,
        candidate.issue_id,
    )


def _record_round(record: Mapping[str, Any]) -> Optional[int]:
    value = _as_int(record.get("retrieval_round"), default=0)
    return value if value else None


def _request_order(result: Mapping[str, Any]) -> List[str]:
    state = result.get("state")
    history = state.get("query_history", []) if isinstance(state, dict) else []
    if not isinstance(history, list):
        return []
    return list(
        dict.fromkeys(
            str(item.get("request_id") or "")
            for item in history
            if isinstance(item, dict) and str(item.get("request_id") or "")
        )
    )


def _critical_ids(result: Mapping[str, Any]) -> List[str]:
    state = result.get("state")
    evidence = state.get("required_evidence_items", []) if isinstance(state, dict) else []
    return [
        str(item.get("evidence_item_id"))
        for item in evidence
        if isinstance(item, dict)
        and item.get("critical") is True
        and str(item.get("evidence_item_id") or "")
    ]


def _merge_candidates(candidates: Sequence[TraceCandidate]) -> List[TraceCandidate]:
    grouped: Dict[str, List[TraceCandidate]] = defaultdict(list)
    for candidate in sorted(candidates, key=_candidate_key):
        alias_key = min(candidate.alias_provision_ids, default=candidate.provision_id)
        grouped[alias_key].append(candidate)

    merged: List[TraceCandidate] = []
    for equivalents in grouped.values():
        representative = equivalents[0]
        sources: List[str] = []
        evidence: List[str] = []
        aliases: List[str] = []
        ranks: Dict[str, int] = {}
        for candidate in equivalents:
            for request_id in candidate.source_request_ids:
                if request_id not in sources:
                    sources.append(request_id)
            for evidence_id in candidate.target_evidence_item_ids:
                if evidence_id not in evidence:
                    evidence.append(evidence_id)
            for provision_id in candidate.alias_provision_ids:
                if provision_id not in aliases:
                    aliases.append(provision_id)
            for request_id, rank in candidate.request_rerank_ranks.items():
                ranks[request_id] = min(ranks.get(request_id, rank), rank)
        merged.append(
            TraceCandidate(
                provision_id=representative.provision_id,
                issue_id=representative.issue_id,
                rerank_score=representative.rerank_score,
                fusion_rank=representative.fusion_rank,
                source_request_ids=tuple(sources),
                target_evidence_item_ids=tuple(evidence),
                alias_provision_ids=tuple(aliases),
                request_rerank_ranks=ranks,
            )
        )
    return merged


def _round_candidates(
    records: Sequence[Mapping[str, Any]],
) -> Dict[int, List[TraceCandidate]]:
    request_ranks: Dict[int, Dict[str, Dict[str, int]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    for record in records:
        if record.get("candidate_stage") != "request_rerank":
            continue
        retrieval_round = _record_round(record)
        provision_id = str(record.get("provision_id") or "")
        request_ids = _as_string_list(record.get("source_request_ids"))
        rank = _as_int(record.get("rerank_rank"))
        if retrieval_round is None or not provision_id or len(request_ids) != 1:
            continue
        request_id = request_ids[0]
        request_ranks[retrieval_round][provision_id][request_id] = min(
            request_ranks[retrieval_round][provision_id].get(request_id, rank),
            rank,
        )

    by_round: Dict[int, List[TraceCandidate]] = defaultdict(list)
    for record in records:
        if record.get("candidate_stage") != "selected":
            continue
        retrieval_round = _record_round(record)
        provision_id = str(record.get("provision_id") or "")
        if retrieval_round is None or not provision_id:
            continue
        aliases = list(_as_string_list(record.get("alias_provision_ids")))
        if provision_id not in aliases:
            aliases.insert(0, provision_id)
        ranks: Dict[str, int] = {}
        for alias_id in aliases:
            for request_id, rank in request_ranks[retrieval_round].get(alias_id, {}).items():
                ranks[request_id] = min(ranks.get(request_id, rank), rank)
        by_round[retrieval_round].append(
            TraceCandidate(
                provision_id=provision_id,
                issue_id=str(record.get("issue_id") or ""),
                rerank_score=_as_float(record.get("rerank_score")),
                fusion_rank=_as_int(record.get("fusion_rank")),
                source_request_ids=_as_string_list(record.get("source_request_ids")),
                target_evidence_item_ids=_as_string_list(
                    record.get("target_evidence_item_ids")
                ),
                alias_provision_ids=tuple(aliases),
                request_rerank_ranks=ranks,
            )
        )
    return {round_id: _merge_candidates(items) for round_id, items in by_round.items()}


def _actual_selected(
    records: Sequence[Mapping[str, Any]],
) -> Dict[int, List[Tuple[str, str]]]:
    by_round: Dict[int, List[Tuple[int, str, str]]] = defaultdict(list)
    for record in records:
        if record.get("candidate_stage") != "round_selected":
            continue
        retrieval_round = _record_round(record)
        provision_id = str(record.get("provision_id") or "")
        if retrieval_round is None or not provision_id:
            continue
        by_round[retrieval_round].append(
            (
                _as_int(record.get("selection_rank")),
                provision_id,
                str(record.get("selection_reason") or ""),
            )
        )
    return {
        round_id: [(provision_id, reason) for _, provision_id, reason in sorted(items)]
        for round_id, items in by_round.items()
    }


def _select_with_quotas(
    ranked: Sequence[TraceCandidate],
    critical_ids: Sequence[str],
    top_k: int,
) -> List[TraceCandidate]:
    selected: List[TraceCandidate] = []
    for evidence_id in dict.fromkeys(critical_ids):
        current_count = sum(
            evidence_id in item.target_evidence_item_ids for item in selected
        )
        if current_count >= 1 or len(selected) >= top_k:
            continue
        candidate = next(
            (
                item
                for item in ranked
                if evidence_id in item.target_evidence_item_ids and item not in selected
            ),
            None,
        )
        if candidate is not None and len(selected) < top_k:
            selected.append(candidate)
    for candidate in ranked:
        if len(selected) >= top_k:
            break
        if candidate not in selected:
            selected.append(candidate)
    return selected


def _request_rank_round_robin(
    candidates: Sequence[TraceCandidate],
    request_order: Sequence[str],
) -> List[Tuple[TraceCandidate, str, int]]:
    queues: Dict[str, List[Tuple[TraceCandidate, int]]] = {}
    for request_id in request_order:
        queues[request_id] = sorted(
            [
                (candidate, candidate.request_rerank_ranks[request_id])
                for candidate in candidates
                if request_id in candidate.request_rerank_ranks
            ],
            key=lambda item: (
                item[1],
                -item[0].rerank_score,
                item[0].fusion_rank,
                item[0].provision_id,
                item[0].issue_id,
            ),
        )
    offsets = {request_id: 0 for request_id in request_order}
    seen: Set[str] = set()
    ordered: List[Tuple[TraceCandidate, str, int]] = []
    while True:
        made_progress = False
        for request_id in request_order:
            queue = queues[request_id]
            while offsets[request_id] < len(queue):
                candidate, rank = queue[offsets[request_id]]
                offsets[request_id] += 1
                if candidate.provision_id in seen:
                    continue
                seen.add(candidate.provision_id)
                ordered.append((candidate, request_id, rank))
                made_progress = True
                break
        if not made_progress:
            return ordered


def _ids(candidates: Iterable[TraceCandidate]) -> List[str]:
    return [candidate.provision_id for candidate in candidates]


def _counterfactual_rounds(
    pools: Mapping[int, Sequence[TraceCandidate]],
    actual: Mapping[int, Sequence[Tuple[str, str]]],
    critical_ids: Sequence[str],
    request_order: Sequence[str],
    top_k: int,
) -> Dict[str, Dict[int, List[str]]]:
    variants: Dict[str, Dict[int, List[str]]] = {
        "actual_trace": {
            round_id: [provision_id for provision_id, _ in selected]
            for round_id, selected in actual.items()
        },
        "raw_score_reconstructed": {},
        "rank_normalized": {},
        "request_rank_round_robin": {},
        "hybrid_preserve_9_fill_1": {},
        "hybrid_preserve_5_fill_5": {},
        "request_rank_top1_guarded_swap": {},
    }
    prior_guarded_ids: Set[str] = set()
    for round_id in sorted(pools):
        pool = pools[round_id]
        raw = _select_with_quotas(sorted(pool, key=_candidate_key), critical_ids, top_k)
        normalized = _select_with_quotas(sorted(pool, key=_rank_key), critical_ids, top_k)
        fair = _select_with_quotas(
            [candidate for candidate, _, _ in _request_rank_round_robin(pool, request_order)],
            critical_ids,
            top_k,
        )
        variants["raw_score_reconstructed"][round_id] = _ids(raw)
        variants["rank_normalized"][round_id] = _ids(normalized)
        variants["request_rank_round_robin"][round_id] = _ids(fair)

        actual_ids = [provision_id for provision_id, _ in actual.get(round_id, [])]
        for preserve_count, name in (
            (top_k - 1, "hybrid_preserve_9_fill_1"),
            (5, "hybrid_preserve_5_fill_5"),
        ):
            hybrid = actual_ids[:preserve_count]
            hybrid.extend(provision_id for provision_id in _ids(fair) if provision_id not in hybrid)
            variants[name][round_id] = hybrid[:top_k]

        guarded = list(actual_ids[:top_k])
        tail_reason = actual.get(round_id, [("", "")])
        can_swap = len(guarded) == top_k and not tail_reason[-1][1].startswith("critical_quota:")
        if can_swap:
            for candidate, _, rank in _request_rank_round_robin(pool, request_order):
                if (
                    rank == 1
                    and candidate.provision_id not in guarded
                    and candidate.provision_id not in prior_guarded_ids
                ):
                    guarded[-1] = candidate.provision_id
                    break
        variants["request_rank_top1_guarded_swap"][round_id] = guarded
        prior_guarded_ids.update(guarded)
    return variants


def _first_complete(
    selected_by_round: Mapping[int, Sequence[str]],
    groups: Sequence[evaluator.GoldGroup],
) -> Tuple[Optional[int], Dict[str, Any], Dict[int, Dict[str, Any]]]:
    cumulative: Set[str] = set()
    first: Optional[int] = None
    per_round: Dict[int, Dict[str, Any]] = {}
    for round_id in sorted(selected_by_round):
        cumulative.update(selected_by_round[round_id])
        metrics = evaluator.precision_recall_f1(cumulative, groups)
        per_round[round_id] = metrics
        if first is None and metrics["complete"]:
            first = round_id
    return first, evaluator.precision_recall_f1(cumulative, groups), per_round


def _bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _paired_complete_ids(path: Path) -> Set[str]:
    if not path.is_file():
        return set()
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            str(row.get("question_id") or "")
            for row in csv.DictReader(handle)
            if _bool(row.get("accepted_complete_evidence"))
        }


def _first_label(value: Optional[int]) -> str:
    return "never" if value is None else "r%d" % value


def _mean_metric(rows: Sequence[Mapping[str, Any]], field: str) -> Optional[float]:
    return mean(float(row["final_metrics"][field]) for row in rows) if rows else None


def _variant_summary(
    name: str,
    rows: Sequence[Mapping[str, Any]],
    actual_rows: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    complete_ids = sorted(
        row["question_id"] for row in rows if row["final_metrics"]["complete"]
    )
    actual_complete = {
        question_id
        for question_id, row in actual_rows.items()
        if row["final_metrics"]["complete"]
    }
    by_hop: Dict[str, Dict[str, Any]] = {}
    for hop in sorted({int(row["n_hops"]) for row in rows}):
        subset = [row for row in rows if int(row["n_hops"]) == hop]
        by_hop[str(hop)] = {
            "question_count": len(subset),
            "candidate_complete_count": sum(
                row["final_metrics"]["complete"] for row in subset
            ),
            "macro_precision": _mean_metric(subset, "precision"),
            "macro_recall": _mean_metric(subset, "recall"),
            "macro_f1": _mean_metric(subset, "f1"),
        }
    first = Counter(_first_label(row["first_complete_round"]) for row in rows)
    transitions: Dict[str, List[str]] = defaultdict(list)
    for row in rows:
        before = actual_rows[row["question_id"]]["first_complete_round"]
        after = row["first_complete_round"]
        transitions["%s_to_%s" % (_first_label(before), _first_label(after))].append(
            row["question_id"]
        )
    complete_set = set(complete_ids)
    return {
        "name": name,
        "question_count": len(rows),
        "candidate_complete_count": len(complete_ids),
        "candidate_complete_question_ids": complete_ids,
        "macro_precision": _mean_metric(rows, "precision"),
        "macro_recall": _mean_metric(rows, "recall"),
        "macro_f1": _mean_metric(rows, "f1"),
        "first_candidate_complete": {
            key: first.get(key, 0) for key in ("r1", "r2", "r3", "never")
        },
        "by_hop": by_hop,
        "gained_question_ids": sorted(complete_set - actual_complete),
        "lost_question_ids": sorted(actual_complete - complete_set),
        "first_complete_transitions": {
            transition: sorted(question_ids)
            for transition, question_ids in sorted(transitions.items())
        },
    }


def _markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Fixed-input C5 round-merge ablation",
        "",
        "**Development ablation only.** The rule was chosen while inspecting the same full226 traces, so this is not new held-out evidence. S2/S3 were not replayed; these candidate metrics are not final answer-quality evidence and must not replace the official C5 score.",
        "",
        "| Variant | Complete | Macro precision | Macro recall | Gains | Losses |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, value in summary["variants"].items():
        lines.append(
            "| %s | %d | %.4f | %.4f | %d | %d |"
            % (
                name,
                value["candidate_complete_count"],
                value["macro_precision"],
                value["macro_recall"],
                len(value["gained_question_ids"]),
                len(value["lost_question_ids"]),
            )
        )
    fidelity = summary["trace_fidelity"]
    lines.extend(
        [
            "",
            "## Trace fidelity",
            "",
            "- Normal sidecar-backed questions: %d" % fidelity["normal_question_count"],
            "- Cumulative `round_selected` union matched final state candidates: %d"
            % fidelity["round_selected_matches_final_candidate_count"],
            "- Candidate-state mismatch IDs: %s"
            % (
                ", ".join(
                    fidelity["round_selected_final_candidate_mismatch_question_ids"]
                )
                or "none"
            ),
            "- Raw-score reconstruction exactly matched all round selections: %d"
            % fidelity["raw_score_exact_question_count"],
            "- Raw-score reconstruction mismatch IDs: %s"
            % (", ".join(fidelity["raw_score_mismatch_question_ids"]) or "none"),
            "",
            "## Paired regression cohort",
            "",
            "- D4 accepted-complete / C5 accepted-incomplete (2-hop): %d"
            % summary["paired_regression"]["count"],
            "- BGE@10-complete round-merge losses: %d"
            % summary["round_merge_loss"]["count"],
            "",
            "## Corrected historical hand analysis",
            "",
            "- The earlier 93/34/15/80 first-complete split and 80 two-hop count "
            "were corrected after exact raw trace parity, request ordering, and "
            "cross-issue alias rank unioning.",
        ]
    )
    return "\n".join(lines) + "\n"


def analyze(
    batch_dir: Path,
    dataset_path: Path,
    corpus_path: Path,
    paired_csv: Path,
    top_k: int,
) -> Dict[str, Any]:
    manifest = _read_json(batch_dir / "manifest.json")
    summaries = _read_jsonl(batch_dir / "summary.jsonl")
    normal_summaries = [
        row for row in summaries if row.get("status") in evaluator.NORMAL_OUTCOME_STATUSES
    ]
    question_ids = [str(row["question_id"]) for row in normal_summaries]
    questions = evaluator.load_dataset(dataset_path)
    wanted_indexes = {
        str(context["index"])
        for question_id in question_ids
        for context in questions[question_id]["contexts"]
    }
    groups = evaluator.build_gold_groups(
        questions,
        question_ids,
        evaluator.load_corpus(corpus_path, wanted_indexes),
    )
    d4_complete = _paired_complete_ids(paired_csv)
    rows_by_variant: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    actual_rows: Dict[str, Dict[str, Any]] = {}
    raw_mismatch_ids: List[str] = []
    final_candidate_mismatch_ids: List[str] = []

    for summary in normal_summaries:
        question_id = str(summary["question_id"])
        run_directory = evaluator._resolve_run_directory(batch_dir, summary)
        result = _read_json(run_directory / "result.json")
        records = _read_jsonl(run_directory / "retrieval_stages.jsonl")
        pools = _round_candidates(records)
        actual = _actual_selected(records)
        if not pools or not actual:
            continue
        variants = _counterfactual_rounds(
            pools,
            actual,
            _critical_ids(result),
            _request_order(result),
            top_k,
        )
        if variants["raw_score_reconstructed"] != variants["actual_trace"]:
            raw_mismatch_ids.append(question_id)
        stage_sets, _ = evaluator.load_stage_sets(run_directory)
        state = result.get("state") if isinstance(result.get("state"), dict) else {}
        state_candidates = state.get("candidate_provisions", [])
        final_candidate_ids = {
            str(candidate.get("provision_id") or "")
            for candidate in state_candidates
            if isinstance(candidate, dict) and str(candidate.get("provision_id") or "")
        }
        round_selected_ids = {
            provision_id
            for selected in actual.values()
            for provision_id, _ in selected
        }
        if round_selected_ids != final_candidate_ids:
            final_candidate_mismatch_ids.append(question_id)
        accepted_ids = state.get("accepted_provision_ids", [])
        accepted_complete = evaluator.precision_recall_f1(
            accepted_ids if isinstance(accepted_ids, list) else [], groups[question_id]
        )["complete"]
        bge_ids = stage_sets.get("bge_at_10")
        bge_complete = bge_ids is not None and evaluator.precision_recall_f1(
            bge_ids, groups[question_id]
        )["complete"]
        for name, selected_by_round in variants.items():
            first, final, per_round = _first_complete(selected_by_round, groups[question_id])
            row = {
                "question_id": question_id,
                "n_hops": int(questions[question_id]["n_hops"]),
                "accepted_complete": accepted_complete,
                "bge_at_10_complete": bge_complete,
                "first_complete_round": first,
                "final_metrics": final,
                "round_metrics": per_round,
                "final_candidate_ids": sorted(
                    set().union(*[set(ids) for ids in selected_by_round.values()])
                ),
            }
            rows_by_variant[name].append(row)
            if name == "actual_trace":
                actual_rows[question_id] = row

    variant_summaries = {
        name: _variant_summary(name, rows, actual_rows)
        for name, rows in sorted(rows_by_variant.items())
    }
    paired_ids = sorted(
        question_id
        for question_id, row in actual_rows.items()
        if question_id in d4_complete
        and int(row["n_hops"]) == 2
        and not row["accepted_complete"]
    )
    paired = {
        "count": len(paired_ids),
        "question_ids": paired_ids,
        "variant_candidate_complete_counts": {
            name: sum(
                row["final_metrics"]["complete"]
                for row in rows_by_variant[name]
                if row["question_id"] in set(paired_ids)
            )
            for name in sorted(rows_by_variant)
        },
    }
    round_merge_losses = {
        question_id
        for question_id in paired_ids
        if not actual_rows[question_id]["final_metrics"]["complete"]
        and actual_rows[question_id]["bge_at_10_complete"]
    }
    recovery = {
        name: sorted(
            question_id
            for question_id in round_merge_losses
            if next(
                row
                for row in rows_by_variant[name]
                if row["question_id"] == question_id
            )["final_metrics"]["complete"]
        )
        for name in sorted(rows_by_variant)
    }
    expected = {
        "actual_complete": 137,
        "guarded_complete": 142,
        "guarded_gains": 5,
        "guarded_losses": 0,
        "actual_first": {"r1": 88, "r2": 33, "r3": 16, "never": 85},
        "guarded_first": {
            "r1": 94,
            "r2": 35,
            "r3": 13,
            "never": 80,
        },
        "actual_2hop_complete": 77,
        "guarded_2hop_complete": 81,
    }
    actual_summary = variant_summaries["actual_trace"]
    guarded_summary = variant_summaries["request_rank_top1_guarded_swap"]
    observed = {
        "actual_complete": actual_summary["candidate_complete_count"],
        "guarded_complete": guarded_summary["candidate_complete_count"],
        "guarded_gains": len(guarded_summary["gained_question_ids"]),
        "guarded_losses": len(guarded_summary["lost_question_ids"]),
        "actual_first": actual_summary["first_candidate_complete"],
        "guarded_first": guarded_summary["first_candidate_complete"],
        "actual_2hop_complete": actual_summary["by_hop"]["2"]["candidate_complete_count"],
        "guarded_2hop_complete": guarded_summary["by_hop"]["2"]["candidate_complete_count"],
    }
    return {
        "schema_version": "1.1",
        "development_ablation_only": True,
        "not_new_heldout_evidence": True,
        "do_not_replace_official_c5_score": True,
        "s2_s3_replayed": False,
        "batch_name": manifest.get("name"),
        "normal_question_count": len(actual_rows),
        "trace_fidelity": {
            "normal_question_count": len(actual_rows),
            "round_selected_matches_final_candidate_count": (
                len(actual_rows) - len(final_candidate_mismatch_ids)
            ),
            "round_selected_final_candidate_mismatch_question_ids": sorted(
                final_candidate_mismatch_ids
            ),
            "raw_score_exact_question_count": len(actual_rows) - len(raw_mismatch_ids),
            "raw_score_mismatch_question_ids": sorted(raw_mismatch_ids),
        },
        "variants": variant_summaries,
        "paired_regression": paired,
        "round_merge_loss": {
            "count": len(round_merge_losses),
            "question_ids": sorted(round_merge_losses),
            "recovered_question_ids_by_variant": recovery,
        },
        "documented_c5_expected": expected,
        "historical_hand_analysis_correction": {
            "previous_guarded_first": {
                "r1": 93,
                "r2": 34,
                "r3": 15,
                "never": 80,
            },
            "previous_guarded_2hop_complete": 80,
            "reason": (
                "Corrected after exact raw trace parity, request ordering, and "
                "cross-issue alias request-rank unioning."
            ),
        },
        "observed_c5": observed,
        "documented_c5_expected_matches": observed == expected,
    }


def main() -> int:
    args = parse_args()
    if args.top_k < 2:
        raise SystemExit("--top-k must be at least 2")
    batch_dir = args.batch_dir.resolve()
    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        raise SystemExit("output directory already exists: %s" % output_dir)
    summary = analyze(
        batch_dir,
        args.dataset.resolve(),
        args.corpus.resolve(),
        args.paired_csv.resolve(),
        args.top_k,
    )
    output_dir.mkdir(parents=True)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "summary.md").write_text(_markdown(summary), encoding="utf-8")
    print("wrote %s" % output_dir)
    if args.assert_c5_expected and not summary["documented_c5_expected_matches"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
