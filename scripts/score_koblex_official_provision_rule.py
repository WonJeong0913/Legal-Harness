#!/usr/bin/env python3
"""Score provisions with the official KoBLEX retrieval rule and bootstrap paired deltas.

Official rule: ``evaluate_retrieval`` in ``experiments/lf-eval/eval_pipeline.py``
of https://github.com/daehuikim/KoBLEX (audited at commit 1a2d225). Gold and
predictions are sets of ``hierarchy + content`` strings and a hit requires
exact string equality; precision, recall, F1 and EM are averaged per item.
No normalization, duplicate-row alternatives or article/clause matching.

All three conditions are put on that rule from frozen artifacts:

- ParSeR (Reproduced): selected texts in ``final_results.jsonl`` as stored.
- C02 conditions: ``state.accepted_provision_ids`` from each run's
  ``result.json``, mapped to the statute parquet row named by the ID suffix
  (``...#KOBLEX-<row>``). The script first re-derives the harness-rule F1/EM
  from the same IDs and requires a per-question match with the frozen
  evaluation CSV, so the extracted predictions are the evaluated ones.

Paired bootstrap (unchanged from the 2026-09-01 report): NumPy
``default_rng(seed)``, one ``integers(0, n, size=(resamples, n))`` index matrix
shared by every metric and comparison, mean of per-question differences, 95%
percentile interval with NumPy's default linear (type 7) method. With
``--parity-report`` the script reproduces the stored 2026-09-01 F1/EM rows
before computing new ones and stops if they differ.

Postprocessing only: no model, retriever or GPU; inputs are never modified.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import platform
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PARSER = "PARSER_REPRODUCED"
OFFICIAL_RULE_SOURCE = "daehuikim/KoBLEX@1a2d225:experiments/lf-eval/eval_pipeline.py::evaluate_retrieval"


def _load_harness_evaluator():
    spec = importlib.util.spec_from_file_location(
        "evaluate_dev_runs", PROJECT_ROOT / "scripts" / "evaluate_dev_runs.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["evaluate_dev_runs"] = module
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"], text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _true(value: str) -> bool:
    return str(value).strip().lower() in ("true", "1", "1.0")


def official_retrieval(predicted, gold):
    """Per-item body of the official ``evaluate_retrieval``."""
    p_set, g_set = set(predicted), set(gold)
    tp = len(p_set & g_set)
    fp, fn = len(p_set) - tp, len(g_set) - tp
    if not p_set and not g_set:
        precision = recall = f1 = em = 1.0
    else:
        precision = tp / len(p_set) if p_set else 0.0
        recall = tp / len(g_set) if g_set else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall > 0 else 0.0
        em = 1.0 if fp + fn == 0 else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "em": em,
        "true_positive": tp,
        "predicted": len(p_set),
        "gold": len(g_set),
        "complete": bool(g_set) and tp == len(g_set),
    }


class StatuteTexts:
    """Official corpus text (``hierarchy + content``) addressed by provision ID."""

    def __init__(self, parquet_path: Path):
        table = pq.read_table(parquet_path, columns=["index", "hierarchy", "content"]).to_pydict()
        self._index = table["index"]
        self._text = [h + c for h, c in zip(table["hierarchy"], table["content"])]

    def text(self, provision_id: str) -> str:
        prefix, _, row = provision_id.rpartition("#KOBLEX-")
        position = int(row) - 1
        if not prefix or position < 0 or self._index[position] != prefix:
            raise SystemExit("provision ID does not address the statute parquet: %s" % provision_id)
        return self._text[position]


def load_c02_condition(edr, name, summary_path, eval_dir, questions, groups, texts):
    batch_dir = summary_path.parent
    summaries = sorted(_read_jsonl(summary_path), key=lambda row: int(row["ordinal"]))
    frozen = {
        row["question_id"]: row
        for row in csv.DictReader((eval_dir / "per_question.csv").open(encoding="utf-8"))
    }
    if len(summaries) != len(frozen) or {row["question_id"] for row in summaries} != set(frozen):
        raise SystemExit("%s: summary and frozen evaluation cover different questions" % name)
    rows = {}
    order = []
    for summary in summaries:
        qid = summary["question_id"]
        run_dir = edr._resolve_run_directory(batch_dir, summary)
        result_path = run_dir / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        status = result.get("status")
        if status != summary.get("status") or status != frozen[qid]["status"]:
            raise SystemExit("%s: status mismatch for %s" % (name, qid))
        accepted = sorted({str(item) for item in result["state"].get("accepted_provision_ids", [])})
        answer_mode = edr._answer_mode(result, qid)
        if (answer_mode or "") != frozen[qid]["answer_mode"]:
            raise SystemExit("%s: answer_mode mismatch for %s" % (name, qid))
        harness = edr.precision_recall_f1(accepted, groups[qid])
        if abs(harness["f1"] - float(frozen[qid]["provision_f1"] or 0)) > 1e-12 or bool(
            harness["provision_em"]
        ) != _true(frozen[qid]["provision_em"]):
            raise SystemExit("%s: harness-rule cross-check failed for %s" % (name, qid))
        gold = [context["hierarchy"] + context["content"] for context in questions[qid]["contexts"]]
        rows[qid] = {
            "status": status,
            "answer_mode": answer_mode,
            "accepted_provision_ids": accepted,
            "result_sha256": _sha256(result_path),
            "official": official_retrieval([texts.text(pid) for pid in accepted], gold),
            "harness": {
                "f1": harness["f1"],
                "em": bool(harness["provision_em"]),
                "complete": bool(harness["complete"]),
            },
        }
        order.append(qid)
    return order, rows


def load_parser(edr, path, questions, groups, statute_text_to_ids):
    rows = {}
    for record in _read_jsonl(path):
        qid = record["question_id"]
        gold = [context["hierarchy"] + context["content"] for context in questions[qid]["contexts"]]
        if set(record.get("gold_contexts") or []) != set(gold):
            raise SystemExit("ParSeR stored gold differs from dataset gold: %s" % qid)
        selected = list(record.get("provisions") or [])
        # harness-rule value for the supplementary column (same mapping as
        # scripts/rescore_parser_with_harness_provision_rule.py)
        gold_ids = {pid for group in groups[qid] for pid in group.acceptable_provision_ids}
        mapped = set()
        for position, text in enumerate(dict.fromkeys(selected)):
            ids = statute_text_to_ids.get(text, [])
            in_gold = [pid for pid in ids if pid in gold_ids]
            mapped.add(in_gold[0] if in_gold else (ids[0] if ids else "UNMAPPED::%s::%d" % (qid, position)))
        harness = edr.precision_recall_f1(mapped, groups[qid])
        rows[qid] = {
            "status": "EXECUTION_FAILURE" if record.get("error") else "ANSWER",
            "answer_mode": None,
            "official": official_retrieval(selected, gold),
            "harness": {
                "f1": harness["f1"],
                "em": bool(harness["provision_em"]),
                "complete": bool(harness["complete"]),
            },
        }
    return rows


def summarize(order, rows):
    n = len(order)
    official = [rows[qid]["official"] for qid in order]
    tp = sum(item["true_positive"] for item in official)
    predicted = sum(item["predicted"] for item in official)
    gold = sum(item["gold"] for item in official)
    micro_p = tp / predicted if predicted else 0.0
    micro_r = tp / gold if gold else 0.0

    def subset(keep):
        ids = [qid for qid in order if keep(rows[qid]["status"])]
        if not ids:
            return {"questions": 0}
        return {
            "questions": len(ids),
            "macro_f1": sum(rows[qid]["official"]["f1"] for qid in ids) / len(ids),
            "exact_match_rate": sum(rows[qid]["official"]["em"] for qid in ids) / len(ids),
            "exact_match_count": int(sum(rows[qid]["official"]["em"] for qid in ids)),
        }

    by_mode = defaultdict(lambda: {"answers": 0, "incomplete_official": 0, "incomplete_harness": 0})
    for qid in order:
        row = rows[qid]
        if row["status"] != "ANSWER":
            continue
        bucket = by_mode[row["answer_mode"] or "unrecorded"]
        bucket["answers"] += 1
        bucket["incomplete_official"] += int(not row["official"]["complete"])
        bucket["incomplete_harness"] += int(not row["harness"]["complete"])
    return {
        "questions": n,
        "status_counts": {
            status: sum(rows[qid]["status"] == status for qid in order)
            for status in ("ANSWER", "ABSTAIN", "EXECUTION_FAILURE")
        },
        "official_rule": {
            "macro_precision": sum(item["precision"] for item in official) / n,
            "macro_recall": sum(item["recall"] for item in official) / n,
            "macro_f1": sum(item["f1"] for item in official) / n,
            "exact_match_rate": sum(item["em"] for item in official) / n,
            "exact_match_count": int(sum(item["em"] for item in official)),
            "micro_precision": micro_p,
            "micro_recall": micro_r,
            "micro_f1": 2 * micro_p * micro_r / (micro_p + micro_r) if micro_p + micro_r else 0.0,
            "abstain_removed": subset(lambda status: status != "ABSTAIN"),
            "answered_only": subset(lambda status: status == "ANSWER"),
        },
        "harness_rule_supplementary": {
            "macro_f1": sum(rows[qid]["harness"]["f1"] for qid in order) / n,
            "exact_match_rate": sum(rows[qid]["harness"]["em"] for qid in order) / n,
        },
        "answered_completeness_by_answer_mode": dict(sorted(by_mode.items())),
    }


def paired(a, b, index_matrix, bonferroni_alpha):
    difference = a - b
    boot = difference[index_matrix].mean(axis=1)
    low, high = np.percentile(boot, [2.5, 97.5])
    adj_low, adj_high = np.percentile(boot, [100 * bonferroni_alpha / 2, 100 * (1 - bonferroni_alpha / 2)])
    return {
        "delta": float(difference.mean()),
        "ci95_low": float(low),
        "ci95_high": float(high),
        "ci_bonferroni_low": float(adj_low),
        "ci_bonferroni_high": float(adj_high),
        "wins": int((a > b).sum()),
        "ties": int((a == b).sum()),
        "losses": int((a < b).sum()),
    }


def parity_check(report_path, c02_csv, order, parser_rows, index_matrix):
    stored = {
        row["metric"]: row
        for row in json.loads(report_path.read_text(encoding="utf-8"))["queries"]["paired_robustness"]["rows"]
    }
    frozen = {row["question_id"]: row for row in csv.DictReader(c02_csv.open(encoding="utf-8"))}
    frozen_order = [row["question_id"] for row in sorted(frozen.values(), key=lambda row: int(row["ordinal"]))]
    if frozen_order != order:
        raise SystemExit("parity CSV order differs from the canonical order")
    checks = {
        "Retrieval F1 (macro per item)": (
            np.array([float(frozen[qid]["provision_f1"] or 0) for qid in order]),
            np.array([parser_rows[qid]["official"]["f1"] for qid in order]),
        ),
        "Retrieval exact match": (
            np.array([float(_true(frozen[qid]["provision_em"])) for qid in order]),
            np.array([parser_rows[qid]["official"]["em"] for qid in order]),
        ),
    }
    outcome = {}
    for metric, (a, b) in checks.items():
        got = paired(a, b, index_matrix, 0.05)
        want = stored[metric]
        same = (
            round(got["delta"], 6) == want["c02MinusParser"]
            and round(got["ci95_low"], 6) == want["ci95Low"]
            and round(got["ci95_high"], 6) == want["ci95High"]
            and (got["wins"], got["ties"], got["losses"]) == (want["wins"], want["ties"], want["losses"])
        )
        if not same:
            raise SystemExit("bootstrap parity failed for %s: %s vs %s" % (metric, got, want))
        outcome[metric] = "PASS"
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, required=True, help="KoBLEX QA parquet")
    parser.add_argument("--statute", type=Path, required=True, help="KoBLEX statute corpus parquet")
    parser.add_argument("--corpus", type=Path, required=True, help="normalized statute.jsonl (harness cross-check)")
    parser.add_argument("--parser-results", type=Path, required=True)
    parser.add_argument(
        "--condition", nargs=3, action="append", required=True, metavar=("NAME", "SUMMARY_JSONL", "EVAL_DIR"),
        help="C02 condition: batch summary whose rows resolve to run directories, and its frozen evaluation",
    )
    parser.add_argument("--parity-report", type=Path)
    parser.add_argument("--parity-c02-csv", type=Path)
    parser.add_argument("--seed", type=int, default=20260901)
    parser.add_argument("--resamples", type=int, default=10_000)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise SystemExit("refusing to overwrite non-empty output dir: %s" % args.output_dir)

    edr = _load_harness_evaluator()
    questions = edr.load_dataset(args.dataset)
    texts = StatuteTexts(args.statute)

    first_summary = sorted(_read_jsonl(Path(args.condition[0][1])), key=lambda row: int(row["ordinal"]))
    order = [row["question_id"] for row in first_summary]
    if len(order) != 226 or len(set(order)) != 226 or any(qid not in questions for qid in order):
        raise SystemExit("expected 226 unique dataset question IDs")
    wanted = {str(context["index"]) for qid in order for context in questions[qid]["contexts"]}
    groups = edr.build_gold_groups(questions, order, edr.load_corpus(args.corpus, wanted))
    statute_text_to_ids = defaultdict(list)
    with args.corpus.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            statute_text_to_ids[row["statute_name"] + row["provision_text"]].append(row["provision_id"])

    conditions = {}
    for name, summary_path, eval_dir in args.condition:
        condition_order, rows = load_c02_condition(
            edr, name, Path(summary_path), Path(eval_dir), questions, groups, texts
        )
        if condition_order != order:
            raise SystemExit("%s: question order differs from the canonical order" % name)
        conditions[name] = rows
    parser_rows = load_parser(edr, args.parser_results, questions, groups, statute_text_to_ids)
    if set(parser_rows) != set(order):
        raise SystemExit("ParSeR results cover different questions")
    conditions[PARSER] = parser_rows

    n = len(order)
    index_matrix = np.random.default_rng(args.seed).integers(0, n, size=(args.resamples, n))
    parity = None
    if args.parity_report and args.parity_c02_csv:
        parity = parity_check(args.parity_report, args.parity_c02_csv, order, parser_rows, index_matrix)

    c02_names = [name for name, _, _ in args.condition]
    pairs = [(name, PARSER) for name in c02_names] + [
        (c02_names[i], c02_names[j]) for i in range(len(c02_names)) for j in range(i + 1, len(c02_names))
    ]
    metrics = {"provision_f1": "f1", "provision_em": "em"}
    family = len(pairs) * len(metrics)
    alpha = 0.05 / family
    comparisons = []
    for left, right in pairs:
        for metric, key in metrics.items():
            a = np.array([conditions[left][qid]["official"][key] for qid in order], dtype=float)
            b = np.array([conditions[right][qid]["official"][key] for qid in order], dtype=float)
            comparisons.append({"left": left, "right": right, "metric": metric, **paired(a, b, index_matrix, alpha)})

    aggregate = {
        "official_rule_source": OFFICIAL_RULE_SOURCE,
        "denominator_policy": "all 226 questions; ABSTAIN and execution-failure rows are scored on the provisions "
        "they stored (none for ParSeR failures)",
        "conditions": {name: summarize(order, rows) for name, rows in conditions.items()},
        "bootstrap": {
            "procedure": "numpy default_rng(seed).integers(0, n, size=(resamples, n)) shared by all metrics and "
            "comparisons; mean of per-question left-minus-right differences; percentile intervals, numpy linear",
            "seed": args.seed,
            "resamples": args.resamples,
            "questions": n,
            "bonferroni_family_size": family,
            "bonferroni_interval_percentiles": [100 * alpha / 2, 100 * (1 - alpha / 2)],
            "parity_with_20260901_report": parity,
            "comparisons": comparisons,
        },
    }
    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "script": "scripts/score_koblex_official_provision_rule.py",
        "script_sha256": _sha256(Path(__file__).resolve()),
        "git_commit": _git_commit(),
        "harness_evaluator_sha256": _sha256(PROJECT_ROOT / "scripts" / "evaluate_dev_runs.py"),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "uses_gpu_or_model": False,
        "inputs": {
            key: {"path": str(path), "sha256": _sha256(Path(path))}
            for key, path in [
                ("dataset", args.dataset),
                ("statute", args.statute),
                ("corpus", args.corpus),
                ("parser_results", args.parser_results),
            ]
            + [("%s_summary" % name, summary) for name, summary, _ in args.condition]
            + [("%s_per_question_csv" % name, Path(eval_dir) / "per_question.csv") for name, _, eval_dir in args.condition]
            + ([("parity_report", args.parity_report), ("parity_c02_csv", args.parity_c02_csv)] if parity else [])
        },
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "aggregate.json").write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (args.output_dir / "per_question.jsonl").open("w", encoding="utf-8") as handle:
        for ordinal, qid in enumerate(order, start=1):
            row = {"ordinal": ordinal, "question_id": qid, "n_hops": questions[qid]["n_hops"]}
            row.update({name: conditions[name][qid] for name in conditions})
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output_dir / "SHA256SUMS").write_text(
        "".join(
            "%s  %s\n" % (_sha256(args.output_dir / name), name) for name in ("aggregate.json", "per_question.jsonl")
        ),
        encoding="utf-8",
    )

    for name, summary in aggregate["conditions"].items():
        rule = summary["official_rule"]
        print(
            "%-18s macro F1 %.2f  micro F1 %.2f  EM %.2f (%d)  | abstain-removed n=%d F1 %.2f EM %.2f"
            % (
                name, 100 * rule["macro_f1"], 100 * rule["micro_f1"], 100 * rule["exact_match_rate"],
                rule["exact_match_count"], rule["abstain_removed"]["questions"],
                100 * rule["abstain_removed"].get("macro_f1", 0), 100 * rule["abstain_removed"].get("exact_match_rate", 0),
            )
        )
    print("parity:", parity)
    for item in comparisons:
        print(
            "%-10s - %-18s %-13s delta %+.2f  95%% CI [%+.2f, %+.2f]  W/T/L %d/%d/%d"
            % (
                item["left"], item["right"], item["metric"], 100 * item["delta"],
                100 * item["ci95_low"], 100 * item["ci95_high"], item["wins"], item["ties"], item["losses"],
            )
        )


if __name__ == "__main__":
    main()
