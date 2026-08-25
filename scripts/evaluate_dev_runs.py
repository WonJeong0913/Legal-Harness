#!/usr/bin/env python3
"""Evaluate one immutable Legal Harness batch against KoBLEX gold contexts.

The evaluator is intentionally offline: it never invokes an LLM, retriever, or
reranker.  Retrieval-stage metrics are computed only from an append-only
``retrieval_stages.jsonl`` sidecar.  Legacy runs without that sidecar retain
their outcome, accepted-evidence, and efficiency metrics, while stage metrics
are reported as unavailable rather than as zero.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import subprocess
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVALUATION_SCHEMA_VERSION = "1.4"
OUTCOME_STATUSES = ("ANSWER", "ABSTAIN", "EXECUTION_FAILURE")
ANSWER_MODES = ("full", "conditional", "limited")
NORMAL_OUTCOME_STATUSES = ("ANSWER", "ABSTAIN")
KOBLEX_PREDICTION_MAX_CHARACTERS = 800
LF_EVAL_SCALES = {"0_1": 1.0, "0_10": 10.0, "0_100": 100.0}
RETRIEVAL_EVENT_NAMES = {
    "INITIAL_RETRIEVAL_VALIDATED",
    "GAP_RETRIEVAL_VALIDATED",
}
STAGE_SPECS = {
    "first_stage_at_100": ("first_stage", 100),
    "rrf_at_100": ("fusion", 100),
    "bge_at_10": ("rerank", 10),
    "bge_at_20": ("rerank", 20),
    "bge_at_30": ("rerank", 30),
}
STAGE_ALIASES = {
    "first_stage": "first_stage",
    "bm25": "first_stage",
    "kure": "first_stage",
    "fusion": "fusion",
    "rrf": "fusion",
    "rerank": "rerank",
    "bge": "rerank",
    "bge_rerank": "rerank",
}


class EvaluationError(RuntimeError):
    """Raised when evaluation inputs are missing, ambiguous, or inconsistent."""


@dataclass(frozen=True)
class CorpusEntry:
    provision_id: str
    source_index: str
    hierarchy: str
    content: str


@dataclass(frozen=True)
class GoldGroup:
    question_id: str
    gold_context_id: str
    index: str
    hierarchy: str
    content_sha256: str
    acceptable_provision_ids: Tuple[str, ...]
    match_type: str
    warnings: Tuple[str, ...] = ()


@dataclass(frozen=True)
class LFEvalScores:
    """Imported, frozen LF-Eval scores; this evaluator never invokes a judge."""

    judge_model: str
    judge_revision: str
    prompt_sha256: str
    scale: str
    raw_scores: Mapping[str, float]
    normalized_scores: Mapping[str, float]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _json_ready(value: Any) -> Any:
    """Recursively replace non-finite floats with JSON-safe null values."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationError("invalid JSON file: %s" % path) from exc
    if not isinstance(payload, dict):
        raise EvaluationError("JSON root must be an object: %s" % path)
    return payload


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise EvaluationError(
                        "JSONL row must be an object: %s:%d" % (path, line_number)
                    )
                records.append(record)
    except json.JSONDecodeError as exc:
        raise EvaluationError("invalid JSONL file: %s" % path) from exc
    except OSError as exc:
        raise EvaluationError("cannot read JSONL file: %s" % path) from exc
    return records


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(_json_ready(dict(payload)), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _git_source_worktree_dirty() -> Optional[bool]:
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=str(PROJECT_ROOT), check=True, capture_output=True, text=True,
        ).stdout
        return any(
            line[3:] and not line[3:].startswith("records/")
            for line in status.splitlines()
        )
    except (OSError, subprocess.CalledProcessError):
        return None


def _git_commit() -> Optional[str]:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(PROJECT_ROOT),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _resolve_path(path: Path, base: Path = PROJECT_ROOT) -> Path:
    return path if path.is_absolute() else base / path


def load_dataset(path: Path) -> Dict[str, Dict[str, Any]]:
    """Load KoBLEX parquet, or JSON/JSONL fixtures used by unit tests."""
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:  # pragma: no cover - production dependency guard
            raise EvaluationError("pyarrow is required to read KoBLEX parquet") from exc
        try:
            rows = pq.read_table(
                path,
                columns=["id", "question", "answer", "background", "contexts", "n_hops"],
            ).to_pylist()
        except Exception as exc:
            raise EvaluationError("cannot read dataset parquet: %s" % path) from exc
    elif suffix == ".jsonl":
        rows = _read_jsonl(path)
    elif suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("rows", []) if isinstance(payload, dict) else payload
    else:
        raise EvaluationError("unsupported dataset format: %s" % path)

    if not isinstance(rows, list):
        raise EvaluationError("dataset must contain a row list")
    questions: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise EvaluationError("dataset row must be an object")
        question_id = str(row.get("id") or "")
        if not question_id:
            raise EvaluationError("dataset row is missing id")
        if question_id in questions:
            raise EvaluationError("duplicate dataset question id: %s" % question_id)
        contexts = row.get("contexts")
        if not isinstance(contexts, list) or not contexts:
            raise EvaluationError("question has no gold contexts: %s" % question_id)
        try:
            n_hops = int(row["n_hops"])
        except (KeyError, TypeError, ValueError) as exc:
            raise EvaluationError("question has invalid n_hops: %s" % question_id) from exc
        normalized = dict(row)
        normalized["id"] = question_id
        normalized["n_hops"] = n_hops
        questions[question_id] = normalized
    return questions


def load_corpus(path: Path, wanted_indexes: Set[str]) -> List[CorpusEntry]:
    """Load only corpus rows that can participate in selected gold groups."""
    if path.suffix.lower() == ".jsonl":
        raw_rows: Iterable[Mapping[str, Any]] = _read_jsonl(path)
    elif path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw_rows = payload.get("rows", []) if isinstance(payload, dict) else payload
    else:
        raise EvaluationError("unsupported normalized corpus format: %s" % path)

    entries: List[CorpusEntry] = []
    seen_ids: Set[str] = set()
    for raw in raw_rows:
        source_index = str(raw.get("source_index") or "")
        if source_index not in wanted_indexes:
            continue
        provision_id = str(raw.get("provision_id") or "")
        hierarchy = str(raw.get("statute_name") or "")
        content = str(raw.get("provision_text") or "")
        if not provision_id or not hierarchy or not content:
            raise EvaluationError("normalized corpus contains an incomplete selected row")
        if provision_id in seen_ids:
            raise EvaluationError("duplicate corpus provision_id: %s" % provision_id)
        seen_ids.add(provision_id)
        entries.append(CorpusEntry(provision_id, source_index, hierarchy, content))
    return entries


_IMAGE_TAG_RE = re.compile(r"<img\b[^>]*>", flags=re.IGNORECASE)


def normalize_gold_text(text: str, strip_image_tags: bool = False) -> str:
    """Apply a deliberately narrow normalization for gold-to-corpus matching."""
    value = unicodedata.normalize("NFC", str(text or ""))
    if strip_image_tags:
        value = _IMAGE_TAG_RE.sub("", value).replace("</img>", "")
    return re.sub(r"\s+", "", value)


def _without_terminal_period(text: str) -> str:
    value = normalize_gold_text(text, strip_image_tags=True)
    return value[:-1] if value.endswith(".") else value


def build_gold_groups(
    questions: Mapping[str, Mapping[str, Any]],
    question_ids: Sequence[str],
    corpus: Sequence[CorpusEntry],
) -> Dict[str, List[GoldGroup]]:
    """Map each KoBLEX context to an OR-group of acceptable corpus chunks.

    Exact duplicate corpus rows remain alternatives in one group.  If KoBLEX
    stores a whole article while the normalized corpus stores its clauses as
    chunks, every same-index chunk whose full text occurs in the gold context
    is an acceptable hit for that logical gold context.
    """
    by_index: Dict[str, List[CorpusEntry]] = defaultdict(list)
    for entry in corpus:
        by_index[entry.source_index].append(entry)

    result: Dict[str, List[GoldGroup]] = {}
    for question_id in question_ids:
        question = questions[question_id]
        groups: List[GoldGroup] = []
        for context_number, raw_context in enumerate(question["contexts"], start=1):
            if not isinstance(raw_context, dict):
                raise EvaluationError("gold context must be an object: %s" % question_id)
            index = str(raw_context.get("index") or "")
            hierarchy = str(raw_context.get("hierarchy") or "")
            content = str(raw_context.get("content") or "")
            if not index or not hierarchy or not content:
                raise EvaluationError("incomplete gold context: %s" % question_id)
            candidates = by_index.get(index, [])
            exact = [
                entry
                for entry in candidates
                if entry.hierarchy == hierarchy and entry.content == content
            ]
            warnings: List[str] = []
            if exact:
                matched = exact
                match_type = "exact_duplicate" if len(exact) > 1 else "exact_single"
            else:
                normalized_gold = normalize_gold_text(content, strip_image_tags=True)
                image_normalized = [
                    entry
                    for entry in candidates
                    if entry.hierarchy == hierarchy
                    and normalize_gold_text(entry.content, strip_image_tags=True)
                    == normalized_gold
                ]
                if image_normalized:
                    matched = image_normalized
                    match_type = "normalized_image_tag"
                else:
                    punctuation = [
                        entry
                        for entry in candidates
                        if entry.hierarchy == hierarchy
                        and _without_terminal_period(entry.content)
                        == _without_terminal_period(content)
                    ]
                    if punctuation:
                        matched = punctuation
                        match_type = "terminal_punctuation"
                    else:
                        composite = [
                            entry
                            for entry in candidates
                            if normalize_gold_text(entry.content, strip_image_tags=True)
                            and normalize_gold_text(entry.content, strip_image_tags=True)
                            in normalized_gold
                        ]
                        if not composite:
                            raise EvaluationError(
                                "cannot map gold context to corpus: %s context %d (%s)"
                                % (question_id, context_number, index)
                            )
                        matched = composite
                        match_type = "composite"
                        warnings.append("COMPOSITE_GOLD_CONTEXT")
            groups.append(
                GoldGroup(
                    question_id=question_id,
                    gold_context_id="%s::G%02d" % (question_id, context_number),
                    index=index,
                    hierarchy=hierarchy,
                    content_sha256=_text_sha256(content),
                    acceptable_provision_ids=tuple(
                        sorted({entry.provision_id for entry in matched})
                    ),
                    match_type=match_type,
                    warnings=tuple(warnings),
                )
            )
        result[question_id] = groups
    return result


def load_gold_map(
    path: Path,
    questions: Mapping[str, Mapping[str, Any]],
    question_ids: Sequence[str],
) -> Dict[str, List[GoldGroup]]:
    payload = _read_json(path)
    raw_groups = payload.get("groups")
    if not isinstance(raw_groups, list):
        raise EvaluationError("gold map must contain a groups array")
    grouped: Dict[str, List[GoldGroup]] = defaultdict(list)
    for raw in raw_groups:
        if not isinstance(raw, dict):
            raise EvaluationError("gold map group must be an object")
        question_id = str(raw.get("question_id") or "")
        if question_id not in questions:
            continue
        provision_ids = raw.get("acceptable_provision_ids")
        if not isinstance(provision_ids, list) or not provision_ids:
            raise EvaluationError("gold group has no acceptable provision IDs")
        grouped[question_id].append(
            GoldGroup(
                question_id=question_id,
                gold_context_id=str(raw.get("gold_context_id") or ""),
                index=str(raw.get("index") or ""),
                hierarchy=str(raw.get("hierarchy") or ""),
                content_sha256=str(raw.get("content_sha256") or ""),
                acceptable_provision_ids=tuple(sorted({str(item) for item in provision_ids})),
                match_type=str(raw.get("match_type") or "external"),
                warnings=tuple(str(item) for item in raw.get("warnings", [])),
            )
        )
    for question_id in question_ids:
        groups = grouped.get(question_id, [])
        expected = len(questions[question_id]["contexts"])
        if len(groups) != expected:
            raise EvaluationError(
                "gold map count mismatch for %s: expected %d, found %d"
                % (question_id, expected, len(groups))
            )
        identifiers = [group.gold_context_id for group in groups]
        if not all(identifiers) or len(set(identifiers)) != len(identifiers):
            raise EvaluationError("gold map has empty or duplicate group IDs for %s" % question_id)
    return dict(grouped)


def _maximum_gold_matches(prediction_ids: Set[str], groups: Sequence[GoldGroup]) -> int:
    """Return maximum prediction-to-gold matching without duplicate inflation."""
    group_edges: Dict[str, List[int]] = defaultdict(list)
    for group_index, group in enumerate(groups):
        for provision_id in group.acceptable_provision_ids:
            if provision_id in prediction_ids:
                group_edges[provision_id].append(group_index)
    group_owner: Dict[int, str] = {}

    def assign(provision_id: str, visited: Set[int]) -> bool:
        for group_index in group_edges.get(provision_id, []):
            if group_index in visited:
                continue
            visited.add(group_index)
            owner = group_owner.get(group_index)
            if owner is None or assign(owner, visited):
                group_owner[group_index] = provision_id
                return True
        return False

    matches = 0
    for provision_id in sorted(prediction_ids):
        if assign(provision_id, set()):
            matches += 1
    return matches


def precision_recall_f1(
    prediction_ids: Iterable[str], groups: Sequence[GoldGroup]
) -> Dict[str, Any]:
    predictions = {str(item) for item in prediction_ids}
    true_positives = _maximum_gold_matches(predictions, groups)
    precision = true_positives / len(predictions) if predictions else 0.0
    recall = true_positives / len(groups) if groups else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "predicted": len(predictions),
        "gold": len(groups),
        "true_positive": true_positives,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        # ``complete`` is recall-only: extra predicted provisions do not make
        # it false.  KoBLEX provision EM is stricter and requires exact sets.
        "provision_em": bool(groups)
        and true_positives == len(groups)
        and len(predictions) == len(groups),
        "complete": bool(groups) and true_positives == len(groups),
    }


def koblex_normalize(text: str) -> str:
    """Normalize answer text exactly as the KoBLEX Token-F1 protocol requires."""
    value = str(text or "").lower()
    value = re.sub(r"[^가-힣a-z0-9\s]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def koblex_token_f1(prediction: str, gold: str) -> float:
    """Return KoBLEX's multiset Token-F1 on normalized Korean text."""
    prediction_tokens = koblex_normalize(prediction).split()
    gold_tokens = koblex_normalize(gold).split()
    common = Counter(prediction_tokens) & Counter(gold_tokens)
    overlap = sum(common.values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(prediction_tokens)
    recall = overlap / len(gold_tokens)
    return 2.0 * precision * recall / (precision + recall)


def koblex_official_prediction(answer: str) -> str:
    """`temp_answer.split("<\\think>")[0][:800]` from the ParSeR evaluator.

    `"<\\think>"` is `<` + TAB + `hink>` in Python, so this intentionally
    preserves the baseline's near-no-op split rather than interpreting a
    literal `<think>` tag.
    """
    if not answer:
        return ""
    return answer.split("<\think>")[0][:KOBLEX_PREDICTION_MAX_CHARACTERS]  # noqa: W605


def koblex_token_f1_at_800(prediction: str, gold: str) -> float:
    return koblex_token_f1(koblex_official_prediction(prediction), gold)


def _koblex_exact_match_at_800(prediction: str, gold: str) -> bool:
    return koblex_normalize(koblex_official_prediction(prediction)) == koblex_normalize(gold)


def load_lf_eval_scores(path: Path) -> LFEvalScores:
    """Load externally judged LF-Eval scores and convert them to the 0--1 scale."""
    payload = _read_json(path)
    required_metadata = ("judge_model", "judge_revision", "prompt_sha256", "scale")
    values: Dict[str, str] = {}
    for field in required_metadata:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise EvaluationError("LF-Eval input is missing %s" % field)
        values[field] = value.strip()
    scale_maximum = LF_EVAL_SCALES.get(values["scale"])
    if scale_maximum is None:
        raise EvaluationError("unsupported LF-Eval scale: %s" % values["scale"])
    raw_scores = payload.get("scores")
    if not isinstance(raw_scores, dict):
        raise EvaluationError("LF-Eval input must contain a scores object")

    normalized: Dict[str, float] = {}
    raw: Dict[str, float] = {}
    for question_id, value in raw_scores.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EvaluationError("invalid LF-Eval score for %s" % question_id)
        score = float(value)
        if not math.isfinite(score) or not 0.0 <= score <= scale_maximum:
            raise EvaluationError("LF-Eval score is outside %s for %s" % (values["scale"], question_id))
        identifier = str(question_id)
        raw[identifier] = score
        normalized[identifier] = score / scale_maximum
    return LFEvalScores(
        judge_model=values["judge_model"],
        judge_revision=values["judge_revision"],
        prompt_sha256=values["prompt_sha256"],
        scale=values["scale"],
        raw_scores=raw,
        normalized_scores=normalized,
    )


def percentile_type7(values: Sequence[float], percentile: float) -> Optional[float]:
    if not values:
        return None
    if not 0.0 <= percentile <= 1.0:
        raise ValueError("percentile must be in [0, 1]")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _describe(values: Sequence[float]) -> Dict[str, Any]:
    if not values:
        return {"count": 0, "mean": None, "median": None, "p95": None}
    numbers = [float(value) for value in values]
    return {
        "count": len(numbers),
        "mean": mean(numbers),
        "median": median(numbers),
        "p95": percentile_type7(numbers, 0.95),
    }


def _canonical_stage(value: Any) -> Optional[str]:
    return STAGE_ALIASES.get(str(value or "").strip().lower())


def load_stage_sets(run_directory: Path) -> Tuple[Dict[str, Optional[Set[str]]], List[str]]:
    stage_path = run_directory / "retrieval_stages.jsonl"
    empty = {name: None for name in STAGE_SPECS}
    if not stage_path.is_file():
        return empty, ["STAGE_PROVENANCE_UNAVAILABLE"]

    records = _read_jsonl(stage_path)
    stage_records: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
    for line_number, record in enumerate(records, start=1):
        stage = _canonical_stage(record.get("stage", record.get("candidate_stage")))
        if stage is None:
            continue
        provision_id = str(record.get("provision_id") or "")
        raw_rank = record.get("rank")
        if raw_rank is None:
            raw_rank = record.get(
                {"first_stage": "first_stage_rank", "fusion": "fusion_rank", "rerank": "rerank_rank"}[stage]
            )
        try:
            rank = int(raw_rank)
        except (TypeError, ValueError) as exc:
            raise EvaluationError(
                "invalid stage rank: %s:%d" % (stage_path, line_number)
            ) from exc
        if not provision_id or rank < 1:
            raise EvaluationError("invalid stage row: %s:%d" % (stage_path, line_number))
        stage_records[stage].append((rank, provision_id))

    output: Dict[str, Optional[Set[str]]] = {}
    warnings: List[str] = []
    for metric_name, (stage, cutoff) in STAGE_SPECS.items():
        ranked = stage_records.get(stage)
        if not ranked:
            output[metric_name] = None
            warnings.append("%s_UNAVAILABLE" % metric_name.upper())
        else:
            output[metric_name] = {
                provision_id for rank, provision_id in ranked if rank <= cutoff
            }
    return output, warnings


def load_round_selected_sets(
    run_directory: Path,
) -> Tuple[Optional[Dict[int, Set[str]]], List[str]]:
    """Load selected candidates by retrieval round from provenance sidecar."""
    stage_path = run_directory / "retrieval_stages.jsonl"
    if not stage_path.is_file():
        return None, ["ROUND_SELECTED_PROVENANCE_UNAVAILABLE"]

    selected_by_round: Dict[int, Set[str]] = defaultdict(set)
    found = False
    for line_number, record in enumerate(_read_jsonl(stage_path), start=1):
        if record.get("candidate_stage") != "round_selected":
            continue
        provision_id = str(record.get("provision_id") or "")
        raw_round = record.get("retrieval_round")
        try:
            retrieval_round = int(raw_round)
        except (TypeError, ValueError) as exc:
            raise EvaluationError(
                "invalid round-selected retrieval round: %s:%d"
                % (stage_path, line_number)
            ) from exc
        if not provision_id or retrieval_round < 1:
            raise EvaluationError(
                "invalid round-selected row: %s:%d" % (stage_path, line_number)
            )
        found = True
        selected_by_round[retrieval_round].add(provision_id)

    if not found:
        return None, ["ROUND_SELECTED_PROVENANCE_UNAVAILABLE"]
    return dict(sorted(selected_by_round.items())), []


def build_retrieval_loss_metrics(
    run_directory: Path,
    candidates: Sequence[Mapping[str, Any]],
    candidate_ids: Set[str],
    accepted_metrics: Mapping[str, Any],
    groups: Sequence[GoldGroup],
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """Measure the persisted retrieval funnel without rerunning retrieval."""
    selected_by_round, warnings = load_round_selected_sets(run_directory)
    if selected_by_round is None:
        return None, warnings

    cumulative_selected: Set[str] = set()
    cumulative_selected_metrics: Dict[str, Dict[str, Any]] = {}
    first_round_selected_complete_round: Optional[int] = None
    for retrieval_round, provision_ids in selected_by_round.items():
        cumulative_selected.update(provision_ids)
        cumulative_selected_metrics[str(retrieval_round)] = precision_recall_f1(
            cumulative_selected,
            groups,
        )
        if (
            first_round_selected_complete_round is None
            and cumulative_selected_metrics[str(retrieval_round)]["complete"]
        ):
            first_round_selected_complete_round = retrieval_round
    candidates_by_round: Dict[int, Set[str]] = defaultdict(set)
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        provision_id = str(candidate.get("provision_id") or "")
        if not provision_id:
            continue
        try:
            retrieval_round = int(candidate.get("retrieval_round"))
        except (TypeError, ValueError):
            continue
        if retrieval_round >= 1:
            candidates_by_round[retrieval_round].add(provision_id)

    cumulative_candidates: Set[str] = set()
    first_candidate_complete_round: Optional[int] = None
    for retrieval_round, provision_ids in sorted(candidates_by_round.items()):
        cumulative_candidates.update(provision_ids)
        if (
            first_candidate_complete_round is None
            and precision_recall_f1(cumulative_candidates, groups)["complete"]
        ):
            first_candidate_complete_round = retrieval_round

    round_selected_matches_final_candidate = cumulative_selected == candidate_ids
    if not round_selected_matches_final_candidate:
        warnings.append("ROUND_SELECTED_FINAL_CANDIDATE_MISMATCH")
    final_round = max(selected_by_round)
    return (
        {
            "round_selected_cumulative": cumulative_selected_metrics,
            "round_selected_final": cumulative_selected_metrics[str(final_round)],
            "final_candidate": precision_recall_f1(candidate_ids, groups),
            "accepted": dict(accepted_metrics),
            "first_candidate_complete_round": first_candidate_complete_round,
            "first_round_selected_complete_round": first_round_selected_complete_round,
            "round_selected_matches_final_candidate": round_selected_matches_final_candidate,
        },
        warnings,
    )


def load_answer_labels(path: Optional[Path]) -> Dict[str, bool]:
    """Load false-supported labels; True means the supported answer is false."""
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_labels = payload.get("labels", payload) if isinstance(payload, dict) else None
    if not isinstance(raw_labels, dict):
        raise EvaluationError("answer labels must be an object keyed by question_id")
    labels: Dict[str, bool] = {}
    for question_id, raw in raw_labels.items():
        if isinstance(raw, dict):
            raw = raw.get("false_supported")
        if isinstance(raw, bool):
            labels[str(question_id)] = raw
        elif isinstance(raw, str):
            normalized = raw.strip().lower()
            if normalized in {"false_supported", "incorrect", "true", "1"}:
                labels[str(question_id)] = True
            elif normalized in {"supported", "correct", "false", "0"}:
                labels[str(question_id)] = False
            else:
                raise EvaluationError("unknown answer label: %s" % raw)
        else:
            raise EvaluationError("invalid answer label for %s" % question_id)
    return labels


def _rebase_legacy_record_directory(raw_path: Path) -> Optional[Path]:
    """Map an old absolute records/runs path to this project safely."""
    if not raw_path.is_absolute():
        return None
    parts = raw_path.parts
    for index in range(len(parts) - 1):
        if parts[index : index + 2] != ("records", "runs"):
            continue
        suffix = parts[index + 2 :]
        if len(suffix) < 2 or any(part in {"", ".", ".."} for part in suffix):
            return None
        return PROJECT_ROOT.joinpath("records", "runs", *suffix)
    return None


def _resolve_run_directory(batch_directory: Path, summary: Mapping[str, Any]) -> Path:
    candidates: List[Path] = []
    raw_directory = summary.get("record_directory")
    if raw_directory:
        raw_path = Path(str(raw_directory))
        candidates.append(raw_path)
        rebased_path = _rebase_legacy_record_directory(raw_path)
        if rebased_path is not None:
            candidates.append(rebased_path)
        if not raw_path.is_absolute():
            candidates.extend([PROJECT_ROOT / raw_path, batch_directory / raw_path])
        candidates.append(PROJECT_ROOT / "records/runs" / raw_path.name)
        candidates.append(batch_directory.parent.parent / "runs" / raw_path.name)
    run_id = summary.get("run_id")
    if run_id:
        candidates.extend(
            [
                PROJECT_ROOT / "records/runs" / str(run_id),
                batch_directory.parent.parent / "runs" / str(run_id),
            ]
        )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    raise EvaluationError(
        "cannot resolve record directory for %s" % summary.get("question_id", "unknown")
    )


def _citation_status(result: Mapping[str, Any]) -> Tuple[bool, Optional[bool]]:
    status = result.get("status")
    termination_reason = result.get("termination_reason")
    state = result.get("state", {})
    last_event = state.get("last_validated_event") if isinstance(state, dict) else None
    if status == "ANSWER":
        passed = last_event == "D4.CITATION_INTEGRITY_PASS"
        return True, passed
    if termination_reason == "CITATION_INTEGRITY_FAILED":
        return True, False
    return False, None


def _optional_string_list(
    result: Mapping[str, Any], field: str, question_id: str
) -> List[str]:
    value = result.get(field)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise EvaluationError("invalid %s for %s" % (field, question_id))
    return list(value)


def _answer_mode(result: Mapping[str, Any], question_id: str) -> Optional[str]:
    value = result.get("answer_mode")
    if value is None:
        return None
    if result.get("status") != "ANSWER" or value not in ANSWER_MODES:
        raise EvaluationError("invalid answer_mode for %s" % question_id)
    return str(value)


def _candidate_prediction(
    result: Mapping[str, Any], question_id: str
) -> Tuple[Optional[str], str]:
    status = str(result.get("status") or "")
    if status not in NORMAL_OUTCOME_STATUSES:
        return None, "NOT_NORMAL_OUTCOME"
    if "candidate_answer" not in result:
        published = result.get("answer")
        if status == "ANSWER" and isinstance(published, str) and published.strip():
            return published, "LEGACY_PUBLISHED_FALLBACK"
        return None, "UNRECORDED"
    candidate = result.get("candidate_answer")
    candidate_status = result.get("candidate_answer_status")
    candidate_basis = result.get("candidate_answer_basis")
    if candidate_basis not in {
        "published_answer",
        "retrieved_candidates",
        "question_only",
        None,
    }:
        raise EvaluationError("invalid candidate answer basis for %s" % question_id)
    if status == "ABSTAIN" and (
        candidate_status == "PUBLISHED_ANSWER"
        or candidate_basis == "published_answer"
    ):
        raise EvaluationError("ABSTAIN must not use a published candidate answer for %s" % question_id)
    if status == "ANSWER" and candidate_basis in {
        "retrieved_candidates",
        "question_only",
    }:
        raise EvaluationError("ANSWER must not use an abstain candidate basis for %s" % question_id)
    if candidate is None:
        if candidate_status not in {"EXECUTION_FAILURE", None}:
            raise EvaluationError("invalid candidate answer status for %s" % question_id)
        return None, str(candidate_status or "UNRECORDED")
    if not isinstance(candidate, str) or not candidate.strip():
        raise EvaluationError("candidate_answer must be a non-empty string for %s" % question_id)
    if candidate_status not in {"PUBLISHED_ANSWER", "GENERATED", None}:
        raise EvaluationError("invalid candidate answer status for %s" % question_id)
    return candidate, str(candidate_status or "LEGACY_RECORDED")


def load_evaluation_splits(
    path: Optional[Path], question_ids: Sequence[str]
) -> Dict[str, Tuple[str, ...]]:
    """Load optional development/held-out/all memberships for a completed batch.

    The split manifest is intentionally external to immutable run records.  Its
    ``splits`` object maps a display name to either a question-ID list or an
    object containing ``question_ids``.  ``all`` is always present and must
    cover the completed batch exactly when explicitly supplied.
    """
    all_ids = tuple(str(question_id) for question_id in question_ids)
    known_ids = set(all_ids)
    splits: Dict[str, Tuple[str, ...]] = {"all": all_ids}
    if path is None:
        return splits
    payload = _read_json(path)
    raw_splits = payload.get("splits")
    if not isinstance(raw_splits, dict) or not raw_splits:
        raise EvaluationError("split manifest must contain a non-empty splits object")
    for raw_name, raw_split in raw_splits.items():
        name = str(raw_name).strip()
        if not name:
            raise EvaluationError("split manifest contains an empty split name")
        members = raw_split.get("question_ids") if isinstance(raw_split, dict) else raw_split
        if not isinstance(members, list) or not members:
            raise EvaluationError("split %s must contain question_ids" % name)
        identifiers = tuple(str(item) for item in members)
        if len(set(identifiers)) != len(identifiers):
            raise EvaluationError("split %s contains duplicate question IDs" % name)
        unknown = sorted(set(identifiers) - known_ids)
        if unknown:
            raise EvaluationError("split %s references non-batch questions: %s" % (name, unknown))
        if name == "all" and set(identifiers) != known_ids:
            raise EvaluationError("all split must cover the completed batch exactly")
        splits[name] = identifiers
    return splits


def _returned_candidate_count(state: Mapping[str, Any]) -> int:
    total = 0
    for trace in state.get("action_trace", []):
        if not isinstance(trace, dict) or trace.get("event") not in RETRIEVAL_EVENT_NAMES:
            continue
        details = trace.get("details", {})
        if isinstance(details, dict):
            total += int(details.get("candidate_count", 0) or 0)
    return total


def _load_replacement_summaries(
    replacement_batch_directories: Sequence[Path],
    primary_question_ids: Sequence[str],
) -> Dict[str, Tuple[Dict[str, Any], Path]]:
    """Load retry summaries without requiring their full manifest to be rerun."""
    known_ids = set(primary_question_ids)
    replacements: Dict[str, Tuple[Dict[str, Any], Path]] = {}
    for raw_directory in replacement_batch_directories:
        batch_directory = Path(raw_directory).resolve()
        manifest_path = batch_directory / "manifest.json"
        if not manifest_path.is_file():
            raise EvaluationError("replacement batch manifest is missing: %s" % batch_directory)
        _read_json(manifest_path)
        for summary in _read_jsonl(batch_directory / "summary.jsonl"):
            question_id = str(summary.get("question_id") or "")
            if question_id not in known_ids:
                raise EvaluationError(
                    "replacement summary references non-primary question: %s"
                    % question_id
                )
            if question_id in replacements:
                raise EvaluationError(
                    "duplicate replacement summary row: %s" % question_id
                )
            replacements[question_id] = (summary, batch_directory)
    return replacements


def _join_inputs(
    batch_directory: Path,
    manifest: Mapping[str, Any],
    questions: Mapping[str, Mapping[str, Any]],
    replacement_summaries: Optional[
        Mapping[str, Tuple[Dict[str, Any], Path]]
    ] = None,
) -> List[Tuple[Dict[str, Any], Dict[str, Any], Path, Dict[str, Any], Dict[str, Any]]]:
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise EvaluationError("batch manifest has no entries")
    declared_count = manifest.get("selection", {}).get("entry_count")
    if declared_count is not None and int(declared_count) != len(entries):
        raise EvaluationError("manifest selection.entry_count does not match entries")
    ordinals = [int(entry["ordinal"]) for entry in entries]
    identifiers = [str(entry["question_id"]) for entry in entries]
    if len(set(ordinals)) != len(ordinals) or len(set(identifiers)) != len(identifiers):
        raise EvaluationError("manifest contains duplicate ordinal or question_id")

    summary_path = batch_directory / "summary.jsonl"
    summaries = _read_jsonl(summary_path)
    by_question: Dict[str, List[Tuple[Dict[str, Any], Path]]] = defaultdict(list)
    for summary in summaries:
        by_question[str(summary.get("question_id") or "")].append(
            (summary, batch_directory)
        )
    if set(by_question) != set(identifiers):
        missing = sorted(set(identifiers) - set(by_question))
        extra = sorted(set(by_question) - set(identifiers))
        raise EvaluationError("summary/manifest mismatch; missing=%s extra=%s" % (missing, extra))
    for question_id in identifiers:
        if len(by_question[question_id]) != 1:
            raise EvaluationError(
                "question must have exactly one summary row: %s" % question_id
            )
    if replacement_summaries:
        for question_id, replacement in replacement_summaries.items():
            by_question[question_id] = [replacement]

    joined = []
    for entry in sorted(entries, key=lambda item: int(item["ordinal"])):
        question_id = str(entry["question_id"])
        if len(by_question[question_id]) != 1:
            raise EvaluationError("question must have exactly one summary row: %s" % question_id)
        if question_id not in questions:
            raise EvaluationError("manifest question missing from dataset: %s" % question_id)
        question = questions[question_id]
        if int(entry["n_hops"]) != int(question["n_hops"]):
            raise EvaluationError("hop mismatch for %s" % question_id)
        summary, summary_batch_directory = by_question[question_id][0]
        run_directory = _resolve_run_directory(summary_batch_directory, summary)
        metadata_path = run_directory / "metadata.json"
        result_path = run_directory / "result.json"
        if not metadata_path.is_file() or not result_path.is_file():
            raise EvaluationError("run is incomplete: %s" % run_directory)
        metadata = _read_json(metadata_path)
        result = _read_json(result_path)
        if metadata.get("question_id") != question_id:
            raise EvaluationError("run metadata question mismatch: %s" % question_id)
        if result.get("status") not in OUTCOME_STATUSES:
            raise EvaluationError("invalid result status for %s" % question_id)
        if summary.get("status") != result.get("status"):
            raise EvaluationError("summary/result status mismatch for %s" % question_id)
        if metadata.get("run_id") != result.get("run_id"):
            raise EvaluationError("metadata/result run_id mismatch for %s" % question_id)
        joined.append((dict(entry), dict(question), run_directory, metadata, result))
    return joined


def evaluate_batch(
    batch_directory: Path,
    dataset_path: Path,
    corpus_path: Path,
    gold_map_path: Optional[Path] = None,
    answer_labels_path: Optional[Path] = None,
    require_stage_provenance: bool = True,
    lf_eval_scores_path: Optional[Path] = None,
    split_manifest_path: Optional[Path] = None,
    replacement_batch_directories: Sequence[Path] = (),
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    batch_directory = batch_directory.resolve()
    dataset_path = dataset_path.resolve()
    corpus_path = corpus_path.resolve()
    manifest_path = batch_directory / "manifest.json"
    manifest = _read_json(manifest_path)
    batch_metadata_path = batch_directory / "metadata.json"
    batch_metadata = (
        _read_json(batch_metadata_path) if batch_metadata_path.is_file() else {}
    )
    comparison_validity = batch_metadata.get("comparison_validity")
    if not isinstance(comparison_validity, Mapping):
        comparison_validity = None
    source = manifest.get("source_dataset", {})
    expected_dataset_sha = source.get("sha256") if isinstance(source, dict) else None
    actual_dataset_sha = _sha256(dataset_path)
    if expected_dataset_sha and actual_dataset_sha != expected_dataset_sha:
        raise EvaluationError("dataset SHA-256 does not match batch manifest")

    questions = load_dataset(dataset_path)
    entries = manifest.get("entries", [])
    question_ids = [str(entry["question_id"]) for entry in entries]
    replacement_summaries = _load_replacement_summaries(
        [Path(path).resolve() for path in replacement_batch_directories],
        question_ids,
    )
    joined = _join_inputs(
        batch_directory, manifest, questions, replacement_summaries
    )
    split_memberships = load_evaluation_splits(
        split_manifest_path.resolve() if split_manifest_path else None, question_ids
    )
    lf_eval_scores = load_lf_eval_scores(
        lf_eval_scores_path.resolve() if lf_eval_scores_path else None
    ) if lf_eval_scores_path else None
    wanted_indexes = {
        str(context["index"])
        for question_id in question_ids
        for context in questions[question_id]["contexts"]
    }
    if gold_map_path is None:
        corpus = load_corpus(corpus_path, wanted_indexes)
        groups_by_question = build_gold_groups(questions, question_ids, corpus)
    else:
        gold_map_path = gold_map_path.resolve()
        groups_by_question = load_gold_map(gold_map_path, questions, question_ids)
    labels = load_answer_labels(answer_labels_path.resolve() if answer_labels_path else None)

    warnings: Set[str] = set()
    per_question: List[Dict[str, Any]] = []
    for entry, question, run_directory, run_metadata, result in joined:
        question_id = str(entry["question_id"])
        groups = groups_by_question[question_id]
        state = result.get("state")
        if not isinstance(state, dict):
            raise EvaluationError("result state must be an object: %s" % question_id)
        candidates = state.get("candidate_provisions", [])
        if not isinstance(candidates, list):
            raise EvaluationError("candidate_provisions must be an array: %s" % question_id)
        candidate_ids = {
            str(candidate.get("provision_id"))
            for candidate in candidates
            if isinstance(candidate, dict) and candidate.get("provision_id")
        }
        accepted_ids = {str(item) for item in state.get("accepted_provision_ids", [])}
        if not accepted_ids.issubset(candidate_ids):
            raise EvaluationError("accepted provision is absent from candidates: %s" % question_id)
        provision = precision_recall_f1(accepted_ids, groups)
        normal_outcome = result["status"] in NORMAL_OUTCOME_STATUSES
        if normal_outcome:
            stage_sets, stage_warnings = load_stage_sets(run_directory)
            warnings.update(stage_warnings)
            if require_stage_provenance and any(
                value is None for value in stage_sets.values()
            ):
                raise EvaluationError("complete stage provenance is required: %s" % question_id)
        else:
            stage_sets = {name: None for name in STAGE_SPECS}
        stage_metrics: Dict[str, Optional[Dict[str, Any]]] = {}
        for metric_name, provision_ids in stage_sets.items():
            stage_metrics[metric_name] = (
                None if provision_ids is None else precision_recall_f1(provision_ids, groups)
            )

        if normal_outcome:
            retrieval_loss_metrics, retrieval_loss_warnings = (
                build_retrieval_loss_metrics(
                    run_directory,
                    candidates,
                    candidate_ids,
                    provision,
                    groups,
                )
            )
            warnings.update(retrieval_loss_warnings)
        else:
            retrieval_loss_metrics = None
        retrieval_loss = retrieval_loss_metrics or {}
        citation_attempted, citation_passed = _citation_status(result)
        supported_answer = result["status"] == "ANSWER" and citation_passed is True
        false_supported = labels.get(question_id) if supported_answer else None
        gold_incomplete_supported = supported_answer and not provision["complete"]
        answer_mode = _answer_mode(result, question_id)
        answered_target_ids = _optional_string_list(result, "answered_target_ids", question_id)
        deferred_target_ids = _optional_string_list(result, "deferred_target_ids", question_id)
        answer_text = result.get("answer") if result["status"] == "ANSWER" else ""
        prediction = answer_text if isinstance(answer_text, str) else ""
        token_f1 = koblex_token_f1(prediction, str(question.get("answer") or ""))
        token_f1_at_800 = koblex_token_f1_at_800(
            prediction, str(question.get("answer") or "")
        )
        candidate_prediction, candidate_answer_status = _candidate_prediction(
            result, question_id
        )
        candidate_token_f1_at_800 = (
            koblex_token_f1_at_800(
                candidate_prediction, str(question.get("answer") or "")
            )
            if candidate_prediction is not None
            else None
        )
        candidate_exact_match_at_800 = (
            _koblex_exact_match_at_800(
                candidate_prediction, str(question.get("answer") or "")
            )
            if candidate_prediction is not None
            else None
        )
        lf_eval_raw_score = (
            lf_eval_scores.raw_scores.get(question_id)
            if lf_eval_scores is not None and result["status"] == "ANSWER"
            else None
        )
        lf_eval_normalized_score = (
            lf_eval_scores.normalized_scores.get(question_id)
            if lf_eval_scores is not None and result["status"] == "ANSWER"
            else None
        )
        query_history = state.get("query_history", [])
        if not isinstance(query_history, list):
            raise EvaluationError("query_history must be an array: %s" % question_id)
        latency = result.get("end_to_end_latency_ms")
        if not isinstance(latency, (int, float)) or float(latency) < 0:
            raise EvaluationError("invalid end_to_end_latency_ms: %s" % question_id)
        row: Dict[str, Any] = {
            "ordinal": int(entry["ordinal"]),
            "question_id": question_id,
            "n_hops": int(question["n_hops"]),
            "run_id": str(result.get("run_id") or ""),
            "record_directory": str(run_directory),
            "condition": run_metadata.get("configuration", {}).get("condition"),
            "retriever": run_metadata.get("configuration", {}).get("retriever"),
            "seed": run_metadata.get("configuration", {}).get("seed"),
            "status": result["status"],
            "termination_reason": result.get("termination_reason"),
            "abstention_reason": result.get("abstention_reason"),
            "answer_mode": answer_mode,
            "answered_target_ids": answered_target_ids,
            "deferred_target_ids": deferred_target_ids,
            "split_memberships": sorted(
                name for name, identifiers in split_memberships.items() if question_id in identifiers
            ),
            "gold_count": provision["gold"],
            "accepted_count": provision["predicted"],
            "gold_true_positive": provision["true_positive"],
            "provision_precision": provision["precision"],
            "provision_recall": provision["recall"],
            "provision_f1": provision["f1"],
            "provision_em": provision["provision_em"],
            "accepted_complete_evidence": provision["complete"],
            "token_f1": token_f1,
            "token_f1_at_800": token_f1_at_800,
            "candidate_answer_status": candidate_answer_status,
            "candidate_answer": candidate_prediction,
            "candidate_answer_basis": result.get("candidate_answer_basis"),
            "candidate_answer_available": candidate_prediction is not None,
            "candidate_token_f1_at_800": candidate_token_f1_at_800,
            "candidate_exact_match_at_800": candidate_exact_match_at_800,
            "lf_eval_score_raw": lf_eval_raw_score,
            "lf_eval_score_normalized": lf_eval_normalized_score,
            "supported_answer": supported_answer,
            "false_supported": false_supported,
            "gold_incomplete_supported_answer": gold_incomplete_supported,
            "citation_integrity_attempted": citation_attempted,
            "citation_integrity_passed": citation_passed,
            "retrieval_rounds": int(state.get("retrieval_rounds_used", 0) or 0),
            "retrieval_requests": len(query_history),
            "candidate_count_returned": _returned_candidate_count(state),
            "candidate_count_unique": len(candidate_ids),
            "end_to_end_latency_ms": float(latency),
            "stage_provenance_required": normal_outcome,
            "stage_provenance_available": (
                all(metric is not None for metric in stage_metrics.values())
                if normal_outcome
                else None
            ),
            "stage_metrics": stage_metrics,
            "retrieval_loss_provenance_available": (
                retrieval_loss_metrics is not None if normal_outcome else None
            ),
            "round_selected_cumulative_metrics": retrieval_loss.get(
                "round_selected_cumulative"
            ),
            "round_selected_final_metrics": retrieval_loss.get(
                "round_selected_final"
            ),
            "final_candidate_metrics": retrieval_loss.get("final_candidate"),
            "gold_match_types": dict(Counter(group.match_type for group in groups)),
            "accepted_metrics": retrieval_loss.get("accepted"),
            "first_candidate_complete_round": retrieval_loss.get(
                "first_candidate_complete_round"
            ),
            "first_round_selected_complete_round": retrieval_loss.get(
                "first_round_selected_complete_round"
            ),
            "round_selected_matches_final_candidate": retrieval_loss.get(
                "round_selected_matches_final_candidate"
            ),
        }
        per_question.append(row)

    aggregate = aggregate_rows(per_question, lf_eval_scores=lf_eval_scores)
    aggregate["splits"] = {
        name: {
            "question_count": len(identifiers),
            "metrics": aggregate_rows(
                [row for row in per_question if row["question_id"] in set(identifiers)],
                lf_eval_scores=lf_eval_scores,
            ),
        }
        for name, identifiers in split_memberships.items()
    }
    aggregate.update(
        {
            "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
            "batch_name": manifest.get("name"),
            "question_count": len(per_question),
            "warnings": sorted(warnings),
        }
    )
    if comparison_validity is not None:
        aggregate["comparison_validity"] = dict(comparison_validity)
    replacement_record_directories = {
        str(entry["question_id"]): str(run_directory)
        for entry, _, run_directory, _, _ in joined
        if str(entry["question_id"]) in replacement_summaries
    }
    if replacement_summaries:
        aggregate["replacements"] = {
            "question_ids": sorted(replacement_summaries),
            "source_batch_directories": {
                question_id: str(source_directory)
                for question_id, (_, source_directory) in sorted(
                    replacement_summaries.items()
                )
            },
            "source_record_directories": replacement_record_directories,
        }
    metadata = {
        "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "evaluator_git_commit": _git_commit(),
        "evaluator_git_source_worktree_dirty": _git_source_worktree_dirty(),
        "comparison_validity": comparison_validity,
        "inputs": {
            "batch_directory": str(batch_directory),
            "manifest": str(manifest_path),
            "manifest_sha256": _sha256(manifest_path),
            "dataset": str(dataset_path),
            "dataset_sha256": actual_dataset_sha,
            "corpus": str(corpus_path),
            "corpus_sha256": _sha256(corpus_path),
            "gold_map": str(gold_map_path) if gold_map_path else None,
            "gold_map_sha256": _sha256(gold_map_path) if gold_map_path else None,
            "answer_labels": str(answer_labels_path.resolve()) if answer_labels_path else None,
            "answer_labels_sha256": _sha256(answer_labels_path.resolve()) if answer_labels_path else None,
            "lf_eval_scores": str(lf_eval_scores_path.resolve()) if lf_eval_scores_path else None,
            "lf_eval_scores_sha256": _sha256(lf_eval_scores_path.resolve())
            if lf_eval_scores_path
            else None,
            "split_manifest": str(split_manifest_path.resolve()) if split_manifest_path else None,
            "split_manifest_sha256": _sha256(split_manifest_path.resolve())
            if split_manifest_path
            else None,
        },
        "answer_quality": {
            "token_f1_normalization": "lowercase + [가-힣a-z0-9] tokenization",
            "published_token_f1": {"mode": "legacy_full_text", "max_characters": None},
            "official_token_f1_at_800": {
                "mode": "answer.split(\"<\\think>\")[0][:800]",
                "max_characters": KOBLEX_PREDICTION_MAX_CHARACTERS,
            },
            "candidate_token_f1_at_800": {
                "scope": "ANSWER uses candidate_answer or legacy answer fallback; ABSTAIN uses candidate_answer",
                "execution_failure_score": 0.0,
            },
            "candidate_lf_eval": {
                "available": False,
                "unavailable_reason": "SEPARATE_FROZEN_CANDIDATE_INPUT_REQUIRED",
                "note": "Export candidate_answer to a separate frozen LF-Eval input; --lf-eval-scores continues to score published ANSWER records only.",
            },
            "internal_score_scale": "0_1",
            "display_score_scale": "0_100",
        },
        "lf_eval": {
            "provided": lf_eval_scores is not None,
            "judge_model": lf_eval_scores.judge_model if lf_eval_scores else None,
            "judge_revision": lf_eval_scores.judge_revision if lf_eval_scores else None,
            "prompt_sha256": lf_eval_scores.prompt_sha256 if lf_eval_scores else None,
            "scale": lf_eval_scores.scale if lf_eval_scores else None,
            "input_scale": lf_eval_scores.scale if lf_eval_scores else None,
            "internal_score_scale": "0_1",
            "display_score_scale": "0_100",
        },
        "validation": {
            "manifest_entries": len(entries),
            "joined_results": len(per_question),
            "require_stage_provenance": require_stage_provenance,
            "warnings": sorted(warnings),
        },
    }
    if replacement_summaries:
        metadata["inputs"]["replacements"] = {
            "question_ids": sorted(replacement_summaries),
            "source_batch_directories": {
                question_id: str(source_directory)
                for question_id, (_, source_directory) in sorted(
                    replacement_summaries.items()
                )
            },
            "source_record_directories": replacement_record_directories,
        }
    return aggregate, per_question, metadata


def _outcomes(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Dict[str, Any]]:
    counts = Counter(str(row["status"]) for row in rows)
    total = len(rows)
    return {
        status: {"count": counts[status], "rate": counts[status] / total if total else None}
        for status in OUTCOME_STATUSES
    }


def _aggregate_provisions(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    total_predictions = sum(int(row["accepted_count"]) for row in rows)
    total_gold = sum(int(row["gold_count"]) for row in rows)
    total_true_positive = sum(int(row["gold_true_positive"]) for row in rows)
    micro_precision = total_true_positive / total_predictions if total_predictions else 0.0
    micro_recall = total_true_positive / total_gold if total_gold else 0.0
    micro_f1 = (
        2 * micro_precision * micro_recall / (micro_precision + micro_recall)
        if micro_precision + micro_recall
        else 0.0
    )
    complete_count = sum(bool(row["accepted_complete_evidence"]) for row in rows)
    provision_em_count = sum(bool(row["provision_em"]) for row in rows)
    return {
        "micro": {
            "predicted": total_predictions,
            "gold": total_gold,
            "true_positive": total_true_positive,
            "precision": micro_precision,
            "recall": micro_recall,
            "f1": micro_f1,
        },
        "macro": {
            "precision": mean([float(row["provision_precision"]) for row in rows]) if rows else None,
            "recall": mean([float(row["provision_recall"]) for row in rows]) if rows else None,
            "f1": mean([float(row["provision_f1"]) for row in rows]) if rows else None,
        },
        "complete_evidence": {
            "count": complete_count,
            "rate": complete_count / len(rows) if rows else None,
        },
        "exact_match": {
            "count": provision_em_count,
            "rate": provision_em_count / len(rows) if rows else None,
        },
    }


def _aggregate_stage(rows: Sequence[Mapping[str, Any]], metric_name: str) -> Dict[str, Any]:
    eligible = [row for row in rows if row["status"] in NORMAL_OUTCOME_STATUSES]
    if not eligible:
        return {
            "available": False,
            "available_questions": 0,
            "question_count": 0,
            "provision_recall_micro": None,
            "provision_recall_macro": None,
            "complete_evidence_count": None,
            "complete_evidence_recall": None,
            "unavailable_reason": "NO_NORMAL_OUTCOMES",
        }
    metrics = [row["stage_metrics"].get(metric_name) for row in eligible]
    available = [metric for metric in metrics if metric is not None]
    if len(available) != len(eligible):
        return {
            "available": False,
            "available_questions": len(available),
            "question_count": len(eligible),
            "provision_recall_micro": None,
            "provision_recall_macro": None,
            "complete_evidence_count": None,
            "complete_evidence_recall": None,
            "unavailable_reason": "INCOMPLETE_STAGE_PROVENANCE",
        }
    total_tp = sum(int(metric["true_positive"]) for metric in available)
    total_gold = sum(int(metric["gold"]) for metric in available)
    complete_count = sum(bool(metric["complete"]) for metric in available)
    return {
        "available": True,
        "available_questions": len(available),
        "question_count": len(eligible),
        "provision_recall_micro": total_tp / total_gold if total_gold else 0.0,
        "provision_recall_macro": mean([float(metric["recall"]) for metric in available])
        if available
        else None,
        "complete_evidence_count": complete_count,
        "complete_evidence_recall": complete_count / len(eligible),
        "unavailable_reason": None,
    }


def _aggregate_provenance_metric(
    metrics: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    total_predictions = sum(int(metric["predicted"]) for metric in metrics)
    total_gold = sum(int(metric["gold"]) for metric in metrics)
    total_true_positives = sum(int(metric["true_positive"]) for metric in metrics)
    precision = total_true_positives / total_predictions if total_predictions else 0.0
    recall = total_true_positives / total_gold if total_gold else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    complete_count = sum(bool(metric["complete"]) for metric in metrics)
    return {
        "question_count": len(metrics),
        "predicted": total_predictions,
        "gold": total_gold,
        "true_positive": total_true_positives,
        "micro": {"precision": precision, "recall": recall, "f1": f1},
        "macro": {
            "precision": mean(float(metric["precision"]) for metric in metrics),
            "recall": mean(float(metric["recall"]) for metric in metrics),
            "f1": mean(float(metric["f1"]) for metric in metrics),
        },
        "complete_evidence": {
            "count": complete_count,
            "rate": complete_count / len(metrics) if metrics else None,
        },
    }


def _aggregate_retrieval_loss(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    eligible = [row for row in rows if row["status"] in NORMAL_OUTCOME_STATUSES]
    available = [
        row for row in eligible if row.get("retrieval_loss_provenance_available")
    ]
    output: Dict[str, Any] = {
        "available": False,
        "normal_outcome_questions": len(eligible),
        "available_questions": len(available),
        "round_selected_cumulative": None,
        "final_candidate": None,
        "accepted": None,
        "first_candidate_complete_round": None,
        "first_round_selected_complete_round": None,
        "round_selected_matches_final_candidate": None,
        "unavailable_reason": None,
    }
    if not eligible:
        output["unavailable_reason"] = "NO_NORMAL_OUTCOMES"
        return output
    if len(available) != len(eligible):
        output["unavailable_reason"] = "INCOMPLETE_ROUND_SELECTED_PROVENANCE"
        return output

    round_numbers = sorted(
        {
            int(round_key)
            for row in available
            for round_key in row["round_selected_cumulative_metrics"]
        }
    )
    cumulative: Dict[str, Dict[str, Any]] = {}
    for retrieval_round in round_numbers:
        metrics = []
        for row in available:
            rounds = row["round_selected_cumulative_metrics"]
            completed_rounds = [
                int(key) for key in rounds if int(key) <= retrieval_round
            ]
            metrics.append(rounds[str(max(completed_rounds))])
        cumulative[str(retrieval_round)] = _aggregate_provenance_metric(metrics)

    first_candidate_counts = Counter(
        row["first_candidate_complete_round"]
        for row in available
        if row["first_candidate_complete_round"] is not None
    )
    first_selected_counts = Counter(
        row["first_round_selected_complete_round"]
        for row in available
        if row["first_round_selected_complete_round"] is not None
    )
    matches = sum(
        bool(row["round_selected_matches_final_candidate"]) for row in available
    )
    output.update(
        {
            "available": True,
            "round_selected_cumulative": cumulative,
            "final_candidate": _aggregate_provenance_metric(
                [row["final_candidate_metrics"] for row in available]
            ),
            "accepted": _aggregate_provenance_metric(
                [row["accepted_metrics"] for row in available]
            ),
            "first_candidate_complete_round": {
                "counts": dict(sorted(first_candidate_counts.items())),
                "never_complete_count": (
                    len(available) - sum(first_candidate_counts.values())
                ),
            },
            "first_round_selected_complete_round": {
                "counts": dict(sorted(first_selected_counts.items())),
                "never_complete_count": (
                    len(available) - sum(first_selected_counts.values())
                ),
            },
            "round_selected_matches_final_candidate": {
                "match_count": matches,
                "mismatch_count": len(available) - matches,
            },
        }
    )
    return output


def _aggregate_answer_quality(
    rows: Sequence[Mapping[str, Any]], lf_eval_scores: Optional[LFEvalScores]
) -> Dict[str, Any]:
    total = len(rows)
    answered = [row for row in rows if row["status"] == "ANSWER"]
    token_scores = [float(row["token_f1"]) for row in rows]
    answered_token_scores = [float(row["token_f1"]) for row in answered]
    official_token_scores = [
        float(row.get("token_f1_at_800", row["token_f1"])) for row in rows
    ]
    answered_official_token_scores = [
        float(row.get("token_f1_at_800", row["token_f1"])) for row in answered
    ]
    normal_outcomes = [
        row for row in rows if row["status"] in NORMAL_OUTCOME_STATUSES
    ]
    abstained = [row for row in rows if row["status"] == "ABSTAIN"]
    candidate_available = [
        row for row in normal_outcomes if row.get("candidate_token_f1_at_800") is not None
    ]
    abstain_candidate_available = [
        row for row in abstained if row.get("candidate_token_f1_at_800") is not None
    ]
    candidate_score_or_zero = lambda row: float(
        row.get("candidate_token_f1_at_800") or 0.0
    )
    mode_counts = Counter(
        str(row["answer_mode"]) for row in answered if row.get("answer_mode") in ANSWER_MODES
    )
    if lf_eval_scores is None:
        lf_eval = {
            "available": False,
            "end_to_end": None,
            "answered_only": None,
            "unavailable_reason": "LF_EVAL_NOT_PROVIDED",
            "missing_answer_score_count": len(answered),
            "scale": None,
            "input_scale": None,
            "internal_scale": "0_1",
            "scale_display": "0_100",
        }
    else:
        missing_answers = [
            row for row in answered if row.get("lf_eval_score_normalized") is None
        ]
        lf_eval = {
            "available": not missing_answers,
            "end_to_end": (
                sum(
                    float(row["lf_eval_score_normalized"])
                    for row in answered
                    if row["lf_eval_score_normalized"] is not None
                )
                / total
                if not missing_answers and total
                else None
            ),
            "answered_only": (
                mean(float(row["lf_eval_score_normalized"]) for row in answered)
                if not missing_answers and answered
                else None
            ),
            "unavailable_reason": "MISSING_ANSWER_SCORES" if missing_answers else None,
            "missing_answer_score_count": len(missing_answers),
            "scale": lf_eval_scores.scale,
            "input_scale": lf_eval_scores.scale,
            "internal_scale": "0_1",
            "scale_display": "0_100",
            "judge_model": lf_eval_scores.judge_model,
            "judge_revision": lf_eval_scores.judge_revision,
            "prompt_sha256": lf_eval_scores.prompt_sha256,
        }
    return {
        "answer_count": len(answered),
        "answer_rate": len(answered) / total if total else None,
        "abstain_count": sum(row["status"] == "ABSTAIN" for row in rows),
        "abstain_rate": sum(row["status"] == "ABSTAIN" for row in rows) / total if total else None,
        "execution_failure_count": sum(
            row["status"] == "EXECUTION_FAILURE" for row in rows
        ),
        "execution_failure_rate": sum(
            row["status"] == "EXECUTION_FAILURE" for row in rows) / total if total else None,
        "token_f1": {
            "end_to_end": mean(token_scores) if token_scores else None,
            "answered_only": mean(answered_token_scores) if answered_token_scores else None,
            "internal_scale": "0_1",
            "scale_display": "0_100",
        },
        "token_f1_at_800": {
            "end_to_end": mean(official_token_scores) if official_token_scores else None,
            "answered_only": (
                mean(answered_official_token_scores)
                if answered_official_token_scores
                else None
            ),
            "prediction_projection": "answer.split(\"<\\think>\")[0][:800]",
            "internal_scale": "0_1",
            "scale_display": "0_100",
        },
        "candidate_token_f1_at_800": {
            "all_outcomes": (
                mean([candidate_score_or_zero(row) for row in rows]) if rows else None
            ),
            "normal_outcomes": (
                mean([candidate_score_or_zero(row) for row in normal_outcomes])
                if normal_outcomes
                else None
            ),
            "abstain_only": (
                mean([candidate_score_or_zero(row) for row in abstained])
                if abstained
                else None
            ),
            "available_only": (
                mean(float(row["candidate_token_f1_at_800"]) for row in candidate_available)
                if candidate_available
                else None
            ),
            "abstain_available_only": (
                mean(
                    float(row["candidate_token_f1_at_800"])
                    for row in abstain_candidate_available
                )
                if abstain_candidate_available
                else None
            ),
            "available_count": len(candidate_available),
            "missing_count": len(normal_outcomes) - len(candidate_available),
            "normal_outcome_count": len(normal_outcomes),
            "all_outcomes_available_count": len(candidate_available),
            "all_outcomes_missing_or_execution_failure_count": total - len(candidate_available),
            "abstain_available_count": len(abstain_candidate_available),
            "abstain_missing_count": len(abstained) - len(abstain_candidate_available),
            "abstain_count": len(abstained),
            "execution_failure_count": total - len(normal_outcomes),
            "missing_or_execution_failure_score": 0.0,
            "prediction_projection": "answer.split(\"<\\think>\")[0][:800]",
            "internal_scale": "0_1",
            "scale_display": "0_100",
        },
        "candidate_lf_eval": {
            "available": False,
            "unavailable_reason": "SEPARATE_FROZEN_CANDIDATE_INPUT_REQUIRED",
            "note": "Export candidate_answer to a separately frozen LF-Eval input. The existing --lf-eval-scores import keeps its published ANSWER-record meaning.",
        },
        "over_abstention_exact_match_at_800": {
            "count": sum(
                row.get("candidate_exact_match_at_800") is True for row in abstained
            ),
            "rate": (
                sum(row.get("candidate_exact_match_at_800") is True for row in abstained)
                / len(abstained)
                if abstained
                else None
            ),
            "definition": "ABSTAIN rows whose available benchmark candidate exactly matches the gold answer after answer.split(\"<\\think>\")[0][:800] and KoBLEX normalization; unavailable candidates are counted as non-matches.",
        },
        "lf_eval": lf_eval,
        "answer_modes": {mode: mode_counts[mode] for mode in ANSWER_MODES},
        "answer_mode_rates_e2e": {
            mode: mode_counts[mode] / total if total else None for mode in ANSWER_MODES
        },
        "unrecorded_answer_mode_count": sum(
            row.get("answer_mode") is None for row in answered
        ),
    }


def aggregate_rows(
    rows: Sequence[Mapping[str, Any]],
    include_hops: bool = True,
    lf_eval_scores: Optional[LFEvalScores] = None,
) -> Dict[str, Any]:
    total = len(rows)
    supported_count = sum(bool(row["supported_answer"]) for row in rows)
    labelled = [
        row for row in rows if row["supported_answer"] and row["false_supported"] is not None
    ]
    false_count = sum(bool(row["false_supported"]) for row in labelled)
    citation_attempts = [row for row in rows if row["citation_integrity_attempted"]]
    citation_passes = sum(row["citation_integrity_passed"] is True for row in citation_attempts)
    output: Dict[str, Any] = {
        "outcomes": _outcomes(rows),
        "provision": _aggregate_provisions(rows),
        "answer_quality": _aggregate_answer_quality(rows, lf_eval_scores),
        "retrieval": {
            name: _aggregate_stage(rows, name) for name in STAGE_SPECS
        },
        "retrieval_loss": _aggregate_retrieval_loss(rows),
        "answers": {
            "supported_answer_count": supported_count,
            "supported_answer_yield": supported_count / total if total else None,
            "false_supported_answer_count": false_count if labelled else None,
            "false_supported_answer_rate": false_count / len(labelled) if labelled else None,
            "false_supported_labelled_count": len(labelled),
            "false_supported_label_coverage": len(labelled) / supported_count
            if supported_count
            else None,
            "gold_incomplete_supported_answer_count": sum(
                bool(row["gold_incomplete_supported_answer"]) for row in rows
            ),
        },
        "citation_integrity": {
            "attempted": len(citation_attempts),
            "passed": citation_passes,
            "pass_rate": citation_passes / len(citation_attempts) if citation_attempts else None,
        },
        "efficiency": {
            "retrieval_rounds": _describe([float(row["retrieval_rounds"]) for row in rows]),
            "retrieval_requests": _describe([float(row["retrieval_requests"]) for row in rows]),
            "candidate_count_returned": _describe(
                [float(row["candidate_count_returned"]) for row in rows]
            ),
            "candidate_count_unique": _describe(
                [float(row["candidate_count_unique"]) for row in rows]
            ),
            "end_to_end_latency_ms": _describe(
                [float(row["end_to_end_latency_ms"]) for row in rows]
            ),
        },
    }
    if include_hops:
        output["by_hop"] = {
            str(hop): aggregate_rows(
                [row for row in rows if int(row["n_hops"]) == hop],
                include_hops=False,
                lf_eval_scores=lf_eval_scores,
            )
            for hop in sorted({int(row["n_hops"]) for row in rows})
        }
    return output


CSV_FIELDS = [
    "ordinal",
    "question_id",
    "n_hops",
    "run_id",
    "condition",
    "retriever",
    "seed",
    "status",
    "termination_reason",
    "abstention_reason",
    "answer_mode",
    "answered_target_ids",
    "deferred_target_ids",
    "split_memberships",
    "gold_count",
    "accepted_count",
    "gold_true_positive",
    "provision_precision",
    "provision_recall",
    "provision_f1",
    "provision_em",
    "accepted_complete_evidence",
    "token_f1",
    "token_f1_at_800",
    "candidate_answer",
    "candidate_answer_status",
    "candidate_answer_basis",
    "candidate_answer_available",
    "candidate_token_f1_at_800",
    "candidate_exact_match_at_800",
    "lf_eval_score_raw",
    "lf_eval_score_normalized",
    "supported_answer",
    "false_supported",
    "gold_incomplete_supported_answer",
    "citation_integrity_attempted",
    "citation_integrity_passed",
    "retrieval_rounds",
    "retrieval_requests",
    "candidate_count_returned",
    "candidate_count_unique",
    "end_to_end_latency_ms",
    "stage_provenance_available",
    "first_stage_recall_at_100",
    "retrieval_loss_provenance_available",
    "round_selected_final_recall",
    "round_selected_final_complete_evidence",
    "final_candidate_recall",
    "final_candidate_complete_evidence",
    "first_candidate_complete_round",
    "first_round_selected_complete_round",
    "round_selected_matches_final_candidate",
    "first_stage_complete_at_100",
    "rrf_recall_at_100",
    "rrf_complete_at_100",
    "bge_recall_at_10",
    "bge_complete_at_10",
    "bge_recall_at_20",
    "bge_complete_at_20",
    "bge_recall_at_30",
    "bge_complete_at_30",
    "record_directory",
]


def _flatten_csv_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    flattened = {field: row.get(field) for field in CSV_FIELDS}
    for field in ("answered_target_ids", "deferred_target_ids", "split_memberships"):
        value = flattened[field]
        if isinstance(value, list):
            flattened[field] = ";".join(str(item) for item in value)
    mappings = {
        "first_stage_at_100": ("first_stage_recall_at_100", "first_stage_complete_at_100"),
        "rrf_at_100": ("rrf_recall_at_100", "rrf_complete_at_100"),
        "bge_at_10": ("bge_recall_at_10", "bge_complete_at_10"),
        "bge_at_20": ("bge_recall_at_20", "bge_complete_at_20"),
        "bge_at_30": ("bge_recall_at_30", "bge_complete_at_30"),
    }
    for metric_name, (recall_field, complete_field) in mappings.items():
        metric = row["stage_metrics"].get(metric_name)
        flattened[recall_field] = None if metric is None else metric["recall"]
        flattened[complete_field] = None if metric is None else metric["complete"]
    round_selected = row.get("round_selected_final_metrics")
    final_candidate = row.get("final_candidate_metrics")
    flattened["round_selected_final_recall"] = (
        None if round_selected is None else round_selected["recall"]
    )
    flattened["round_selected_final_complete_evidence"] = (
        None if round_selected is None else round_selected["complete"]
    )
    flattened["final_candidate_recall"] = (
        None if final_candidate is None else final_candidate["recall"]
    )
    flattened["final_candidate_complete_evidence"] = (
        None if final_candidate is None else final_candidate["complete"]
    )
    return flattened


def render_markdown(aggregate: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> str:
    outcomes = aggregate["outcomes"]
    answers = aggregate["answers"]
    provision = aggregate["provision"]
    latency = aggregate["efficiency"]["end_to_end_latency_ms"]
    lines = [
        "# Legal Harness development-run evaluation",
        "",
        "- Questions: %d" % len(rows),
        "- Supported-answer yield: %s"
        % _format_metric(answers["supported_answer_yield"]),
        "- Provision micro P/R/F1: %s / %s / %s"
        % (
            _format_metric(provision["micro"]["precision"]),
            _format_metric(provision["micro"]["recall"]),
            _format_metric(provision["micro"]["f1"]),
        ),
        "- Latency median/p95: %s ms / %s ms"
        % (_format_number(latency["median"]), _format_number(latency["p95"])),
        "",
        "## Outcomes",
        "",
        "| Outcome | Count | Rate |",
        "| --- | ---: | ---: |",
    ]
    for status in OUTCOME_STATUSES:
        lines.append(
            "| %s | %d | %s |"
            % (status, outcomes[status]["count"], _format_metric(outcomes[status]["rate"]))
        )
    validity = aggregate.get("comparison_validity")
    if isinstance(validity, Mapping) and validity.get("status"):
        reasons = validity.get("reasons", [])
        reason_codes = ", ".join(
            "`%s`" % reason.get("code")
            for reason in reasons
            if isinstance(reason, Mapping) and reason.get("code")
        )
        lines[2:2] = [
            "> **Status: `%s` (`%s`).**"
            % (validity["status"], validity.get("use", "DIAGNOSTIC_ONLY")),
            ">",
            "> Do not use this artifact for a clean retriever comparison. Reasons: %s."
            % (reason_codes or "recorded comparison validity failure"),
            "",
        ]
    candidate_quality = aggregate["answer_quality"]["candidate_token_f1_at_800"]
    over_abstention = aggregate["answer_quality"]["over_abstention_exact_match_at_800"]
    lines.extend(
        [
            "",
            "## ABSTAIN benchmark-candidate diagnostic",
            "",
            "Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.",
            "",
            "| Candidate Token-F1@800 scope | Score | Available | Missing |",
            "| --- | ---: | ---: | ---: |",
            "| All outcomes (missing/failure = 0) | %s | %d | %d |"
            % (
                _format_display_score(candidate_quality["all_outcomes"]),
                candidate_quality["all_outcomes_available_count"],
                candidate_quality["all_outcomes_missing_or_execution_failure_count"],
            ),
            "| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | %s | %d | %d |"
            % (
                _format_display_score(candidate_quality["normal_outcomes"]),
                candidate_quality["available_count"],
                candidate_quality["missing_count"],
            ),
            "| ABSTAIN only (missing = 0) | %s | %d | %d |"
            % (
                _format_display_score(candidate_quality["abstain_only"]),
                candidate_quality["abstain_available_count"],
                candidate_quality["abstain_missing_count"],
            ),
            "| ABSTAIN candidates only (available only) | %s | %d | N/A |"
            % (
                _format_display_score(candidate_quality["abstain_available_only"]),
                candidate_quality["abstain_available_count"],
            ),
            "| Available candidates only | %s | %d | N/A |"
            % (
                _format_display_score(candidate_quality["available_only"]),
                candidate_quality["available_count"],
            ),
            "",
            "- Potential over-abstention exact matches@800: %d / %d (%s)."
            % (
                over_abstention["count"],
                candidate_quality["abstain_count"],
                _format_metric(over_abstention["rate"]),
            ),
        ]
    )
    lines.extend(
        [
            "",
            "## KoBLEX-aligned metrics",
            "",
            "All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.",
            "",
            "| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    split_aggregates = aggregate.get(
        "splits", {"all": {"question_count": len(rows), "metrics": aggregate}}
    )
    for split_name, split in split_aggregates.items():
        metrics = split["metrics"]
        quality = metrics["answer_quality"]
        lf_eval = quality["lf_eval"]
        lines.append(
            "| %s | %d | %d | %d | %d | %d | %d | %s | %s | %s | %s | %s | %s |"
            % (
                split_name,
                split["question_count"],
                quality["answer_modes"]["full"],
                quality["answer_modes"]["conditional"],
                quality["answer_modes"]["limited"],
                quality["abstain_count"],
                quality["execution_failure_count"],
                _format_display_score(metrics["provision"]["micro"]["f1"]),
                _format_display_score(metrics["provision"]["exact_match"]["rate"]),
                _format_display_score(quality["token_f1_at_800"]["end_to_end"]),
                _format_display_score(lf_eval["end_to_end"]),
                _format_display_score(quality["token_f1_at_800"]["answered_only"]),
                _format_display_score(lf_eval["answered_only"]),
            )
        )
    lines.extend(
        [
            "",
            "## Retrieval stages",
            "",
            "| Stage | Provision recall | Complete-evidence recall | Availability |",
            "| --- | ---: | ---: | --- |",
        ]
    )
    for name in STAGE_SPECS:
        metric = aggregate["retrieval"][name]
        lines.append(
            "| %s | %s | %s | %s |"
            % (
                name,
                _format_metric(metric["provision_recall_micro"]),
                _format_metric(metric["complete_evidence_recall"]),
                "available" if metric["available"] else "unavailable",
            )
        )
    lines.extend(
        [
            "",
            "## Hop strata",
            "",
            "| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |",
            "| ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for hop, metrics in aggregate.get("by_hop", {}).items():
        lines.append(
            "| %s | %d | %d | %d | %s |"
            % (
                hop,
                metrics["outcomes"]["ANSWER"]["count"],
                metrics["outcomes"]["ABSTAIN"]["count"],
                metrics["outcomes"]["EXECUTION_FAILURE"]["count"],
                _format_metric(metrics["answers"]["supported_answer_yield"]),
            )
        )
    if aggregate.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend("- `%s`" % warning for warning in aggregate["warnings"])
    return "\n".join(lines) + "\n"


def _format_metric(value: Any) -> str:
    return "N/A" if value is None else "%.4f" % float(value)


def _format_display_score(value: Any) -> str:
    return "N/A" if value is None else "%.2f" % (100.0 * float(value))


def _format_number(value: Any) -> str:
    return "N/A" if value is None else "%.3f" % float(value)


def write_outputs(
    output_directory: Path,
    aggregate: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any],
) -> None:
    output_directory.mkdir(parents=True, exist_ok=False)
    _write_json(output_directory / "aggregate.json", aggregate)
    _write_json(output_directory / "metadata.json", metadata)
    with (output_directory / "per_question.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in sorted(rows, key=lambda item: int(item["ordinal"])):
            flattened = _flatten_csv_row(row)
            writer.writerow(
                {key: "" if value is None else value for key, value in flattened.items()}
            )
    (output_directory / "summary.md").write_text(
        render_markdown(aggregate, rows), encoding="utf-8"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-dir", type=Path, required=True)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument(
        "--corpus",
        type=Path,
        default=PROJECT_ROOT / "data/koblex/normalized/statute.jsonl",
    )
    parser.add_argument("--gold-map", type=Path)
    parser.add_argument("--answer-labels", type=Path)
    parser.add_argument(
        "--lf-eval-scores",
        type=Path,
        help="frozen external LF-Eval JSON; omitted scores remain unavailable",
    )
    parser.add_argument(
        "--split-manifest",
        type=Path,
        help="optional JSON split memberships for development, held-out, and all rows",
    )
    parser.add_argument(
        "--replacement-batch-dir",
        type=Path,
        action="append",
        default=[],
        help="retry batch whose subset summary rows replace matching primary rows",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    stage_group = parser.add_mutually_exclusive_group()
    stage_group.add_argument(
        "--require-stage-provenance",
        dest="require_stage_provenance",
        action="store_true",
    )
    stage_group.add_argument(
        "--allow-missing-stage-provenance",
        dest="require_stage_provenance",
        action="store_false",
    )
    parser.set_defaults(require_stage_provenance=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    batch_directory = _resolve_path(args.batch_dir).resolve()
    manifest = _read_json(batch_directory / "manifest.json")
    if args.dataset is None:
        source = manifest.get("source_dataset", {})
        if not isinstance(source, dict) or not source.get("path"):
            raise EvaluationError("--dataset is required when manifest has no source path")
        dataset_path = _resolve_path(Path(str(source["path"]))).resolve()
    else:
        dataset_path = _resolve_path(args.dataset).resolve()
    corpus_path = _resolve_path(args.corpus).resolve()
    gold_map_path = _resolve_path(args.gold_map).resolve() if args.gold_map else None
    labels_path = _resolve_path(args.answer_labels).resolve() if args.answer_labels else None
    lf_eval_scores_path = _resolve_path(args.lf_eval_scores).resolve() if args.lf_eval_scores else None
    split_manifest_path = _resolve_path(args.split_manifest).resolve() if args.split_manifest else None
    replacement_batch_directories = [
        _resolve_path(path).resolve() for path in args.replacement_batch_dir
    ]
    output_directory = _resolve_path(args.output_dir).resolve()
    aggregate, rows, metadata = evaluate_batch(
        batch_directory=batch_directory,
        dataset_path=dataset_path,
        corpus_path=corpus_path,
        gold_map_path=gold_map_path,
        answer_labels_path=labels_path,
        require_stage_provenance=args.require_stage_provenance,
        lf_eval_scores_path=lf_eval_scores_path,
        split_manifest_path=split_manifest_path,
        replacement_batch_directories=replacement_batch_directories,
    )
    write_outputs(output_directory, aggregate, rows, metadata)
    print(json.dumps(_json_ready(aggregate), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EvaluationError as exc:
        print("evaluation error: %s" % exc, file=sys.stderr)
        raise SystemExit(2)
