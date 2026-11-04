#!/usr/bin/env python3
"""Re-score frozen ParSeR (Reproduced) provisions with the harness provision rule.

The ParSeR baseline evaluator (`scripts/evaluate_koblex_parser_baseline.py`)
scores provisions by exact string equality between selected statute texts and
KoBLEX gold contexts. The harness evaluator (`scripts/evaluate_dev_runs.py`)
maps each gold context to an OR-group of acceptable corpus provision IDs
(exact duplicates, image-tag/terminal-period normalization, and article-level
gold stored as clause chunks) and counts true positives by one-to-one matching.

This script puts ParSeR on the harness rule so both systems share one
provision scoring basis. It is postprocessing only: no model, retriever or GPU
is used, and the frozen ParSeR artifact is read, never modified.

ParSeR selects statute rows as `hierarchy + content`, which is exactly
`statute_name + provision_text` of the normalized corpus row with the same
row number, so every selected text maps to provision IDs without heuristics.
Exact duplicate rows count as one prediction that may match any duplicate.
Execution failures keep their stored (empty) provisions and score zero.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


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


def _exact_rule(predicted, gold):
    """ParSeR evaluator rule, kept for an in-script parity check."""
    p_set, g_set = set(predicted), set(gold)
    tp = len(p_set & g_set)
    precision = tp / len(p_set) if p_set else 0.0
    recall = tp / len(g_set) if g_set else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return f1, float(bool(g_set) and p_set == g_set)


def rescore(parser_results: Path, dataset: Path, corpus_path: Path):
    edr = _load_harness_evaluator()
    questions = edr.load_dataset(dataset)
    records = [
        json.loads(line)
        for line in parser_results.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    question_ids = [record["question_id"] for record in records]
    if len(question_ids) != 226 or len(set(question_ids)) != 226:
        raise SystemExit("expected 226 unique ParSeR question IDs")
    missing = [qid for qid in question_ids if qid not in questions]
    if missing:
        raise SystemExit("ParSeR question IDs missing from dataset: %s" % missing[:5])

    text_to_ids = defaultdict(list)
    with corpus_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            text_to_ids[row["statute_name"] + row["provision_text"]].append(row["provision_id"])

    wanted = {str(context["index"]) for qid in question_ids for context in questions[qid]["contexts"]}
    groups = edr.build_gold_groups(questions, question_ids, edr.load_corpus(corpus_path, wanted))

    rows = []
    for record in records:
        qid = record["question_id"]
        gold_ids = {pid for group in groups[qid] for pid in group.acceptable_provision_ids}
        predictions = set()
        unmapped = 0
        selected = list(dict.fromkeys(record.get("provisions") or []))
        for position, text in enumerate(selected):
            ids = text_to_ids.get(text, [])
            if not ids:
                unmapped += 1
                predictions.add("UNMAPPED::%s::%d" % (qid, position))
                continue
            in_gold = [pid for pid in ids if pid in gold_ids]
            predictions.add(in_gold[0] if in_gold else ids[0])
        harness = edr.precision_recall_f1(predictions, groups[qid])
        exact_f1, exact_em = _exact_rule(record.get("provisions") or [], record.get("gold_contexts") or [])
        rows.append(
            {
                "question_id": qid,
                "n_hops": record.get("n_hops"),
                "execution_failure": bool(record.get("error")),
                "selected_texts": len(selected),
                "unmapped_texts": unmapped,
                "predicted_provision_ids": sorted(predictions),
                "gold_groups": len(groups[qid]),
                "gold_match_types": [group.match_type for group in groups[qid]],
                "true_positive": harness["true_positive"],
                "provision_precision": harness["precision"],
                "provision_recall": harness["recall"],
                "provision_f1": harness["f1"],
                "provision_em": bool(harness["provision_em"]),
                "parser_exact_rule_f1": exact_f1,
                "parser_exact_rule_em": bool(exact_em),
            }
        )
    return rows


def aggregate(rows):
    n = len(rows)
    tp = sum(row["true_positive"] for row in rows)
    predicted = sum(len(row["predicted_provision_ids"]) for row in rows)
    gold = sum(row["gold_groups"] for row in rows)
    micro_p = tp / predicted if predicted else 0.0
    micro_r = tp / gold if gold else 0.0
    changed = [row for row in rows if abs(row["provision_f1"] - row["parser_exact_rule_f1"]) > 1e-12]
    match_types = defaultdict(int)
    for row in rows:
        for match_type in row["gold_match_types"]:
            match_types[match_type] += 1
    return {
        "questions": n,
        "execution_failures": sum(row["execution_failure"] for row in rows),
        "selected_texts": sum(row["selected_texts"] for row in rows),
        "unmapped_texts": sum(row["unmapped_texts"] for row in rows),
        "harness_provision_rule": {
            "macro_precision": sum(row["provision_precision"] for row in rows) / n,
            "macro_recall": sum(row["provision_recall"] for row in rows) / n,
            "macro_f1": sum(row["provision_f1"] for row in rows) / n,
            "micro_precision": micro_p,
            "micro_recall": micro_r,
            "micro_f1": 2 * micro_p * micro_r / (micro_p + micro_r) if micro_p + micro_r else 0.0,
            "exact_match_count": sum(row["provision_em"] for row in rows),
            "exact_match_rate": sum(row["provision_em"] for row in rows) / n,
            "true_positive": tp,
            "predicted": predicted,
            "gold": gold,
        },
        "parser_exact_rule_parity": {
            "macro_f1": sum(row["parser_exact_rule_f1"] for row in rows) / n,
            "exact_match_rate": sum(row["parser_exact_rule_em"] for row in rows) / n,
        },
        "questions_with_changed_f1": len(changed),
        "questions_changed_up": sum(row["provision_f1"] > row["parser_exact_rule_f1"] for row in changed),
        "questions_changed_down": sum(row["provision_f1"] < row["parser_exact_rule_f1"] for row in changed),
        "gold_group_match_types": dict(sorted(match_types.items())),
        "denominator_policy": "all 226 questions; execution failures score zero",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--parser-results", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise SystemExit("refusing to overwrite non-empty output dir: %s" % args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows = rescore(args.parser_results, args.dataset, args.corpus)
    summary = aggregate(rows)
    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "script": "scripts/rescore_parser_with_harness_provision_rule.py",
        "script_sha256": _sha256(Path(__file__).resolve()),
        "git_commit": _git_commit(),
        "harness_evaluator_sha256": _sha256(PROJECT_ROOT / "scripts" / "evaluate_dev_runs.py"),
        "inputs": {
            name: {"path": str(path), "sha256": _sha256(path)}
            for name, path in (
                ("parser_results", args.parser_results),
                ("dataset", args.dataset),
                ("corpus", args.corpus),
            )
        },
        "uses_gpu_or_model": False,
    }

    (args.output_dir / "aggregate.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (args.output_dir / "per_question.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    (args.output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    sums = "".join(
        "%s  %s\n" % (_sha256(args.output_dir / name), name)
        for name in ("aggregate.json", "per_question.jsonl")
    )
    (args.output_dir / "SHA256SUMS").write_text(sums, encoding="utf-8")

    rule = summary["harness_provision_rule"]
    print(
        "harness rule: macro F1 %.2f, micro F1 %.2f, EM %.2f (%d/226); exact-rule parity macro F1 %.2f"
        % (
            100 * rule["macro_f1"],
            100 * rule["micro_f1"],
            100 * rule["exact_match_rate"],
            rule["exact_match_count"],
            100 * summary["parser_exact_rule_parity"]["macro_f1"],
        )
    )


if __name__ == "__main__":
    main()
