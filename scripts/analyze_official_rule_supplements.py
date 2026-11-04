#!/usr/bin/env python3
"""Supplementary analyses for the official-rule provision results.

Reads the frozen official-rule record written by
``scripts/score_koblex_official_provision_rule.py`` plus frozen evaluation and
local-LF records, and reports three things the paper cites:

1. Gold reachability under the official exact-string rule: gold contexts whose
   ``hierarchy + content`` string is not a row of the statute corpus, the
   questions they affect, and the resulting EM ceiling. No system can match
   such a gold context exactly.
2. Answered-question completeness by answer mode under the official rule and
   under lenient scoring (the provision rule of ``scripts/evaluate_dev_runs.py``,
   which accepts clause chunks of an article-level gold provision, duplicate
   rows and minor text normalization), and whether every question that is
   complete only under lenient scoring misses nothing but unreachable gold.
3. Abstain-excluded rows (ABSTAIN removed, execution failures kept):
   Token-F1@800 and adapted local Qwen LF, on the public-answer and the
   candidate-answer bases.

Every input is checked against the frozen aggregates it came from before any
new number is written. Postprocessing only: no model, retriever or GPU.
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
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parents[1]
C02_CONDITIONS = ("C02_KURE", "C02_BM25S")
PARSER = "PARSER_REPRODUCED"
LF_KEYS = {"C02_KURE": "kure", "C02_BM25S": "bm25s_parser_first_stage", PARSER: "parser_reproduced"}


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


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def _verify_record(record_dir: Path) -> None:
    for line in (record_dir / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        _require(_sha256(record_dir / name) == digest, "official record checksum mismatch: %s" % name)


def _mean(values):
    return sum(values) / len(values) if values else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--official-record", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--statute", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True, help="normalized statute.jsonl (lenient match types)")
    parser.add_argument("--eval", nargs=2, action="append", required=True, metavar=("NAME", "EVAL_DIR"))
    parser.add_argument("--parser-eval-csv", type=Path, required=True)
    parser.add_argument("--lf-record", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise SystemExit("refusing to overwrite non-empty output dir: %s" % args.output_dir)

    _verify_record(args.official_record)
    official_rows = sorted(_read_jsonl(args.official_record / "per_question.jsonl"), key=lambda row: row["ordinal"])
    order = [row["question_id"] for row in official_rows]
    official = {row["question_id"]: row for row in official_rows}
    _require(len(order) == 226 and len(set(order)) == 226, "official record must cover 226 questions")

    edr = _load_harness_evaluator()
    questions = edr.load_dataset(args.dataset)
    statute = pq.read_table(args.statute, columns=["index", "hierarchy", "content"]).to_pydict()
    statute_texts = [h + c for h, c in zip(statute["hierarchy"], statute["content"])]
    corpus_set = set(statute_texts)

    def text_of(provision_id: str) -> str:
        prefix, _, row = provision_id.rpartition("#KOBLEX-")
        position = int(row) - 1
        _require(statute["index"][position] == prefix, "provision ID does not address the statute: %s" % provision_id)
        return statute_texts[position]

    wanted = {str(context["index"]) for qid in order for context in questions[qid]["contexts"]}
    groups = edr.build_gold_groups(questions, order, edr.load_corpus(args.corpus, wanted))

    # 1. gold reachability --------------------------------------------------
    per_question = []
    unreachable_contexts = []
    for qid in order:
        contexts = questions[qid]["contexts"]
        _require(len(contexts) == len(groups[qid]), "gold group count mismatch: %s" % qid)
        gold = []
        for context, group in zip(contexts, groups[qid]):
            text = context["hierarchy"] + context["content"]
            verbatim = text in corpus_set
            gold.append({"hierarchy": context["hierarchy"], "verbatim_in_corpus": verbatim, "lenient_match_type": group.match_type})
            if not verbatim:
                unreachable_contexts.append({"question_id": qid, "hierarchy": context["hierarchy"], "lenient_match_type": group.match_type})
        per_question.append({"ordinal": official[qid]["ordinal"], "question_id": qid, "gold": gold})
    affected = sorted({item["question_id"] for item in unreachable_contexts}, key=order.index)
    em_on_affected = {
        name: sum(official[qid][name]["official"]["em"] == 1.0 for qid in affected)
        for name in C02_CONDITIONS + (PARSER,)
    }
    reachability = {
        "gold_contexts": sum(len(questions[qid]["contexts"]) for qid in order),
        "gold_contexts_not_verbatim_in_corpus": len(unreachable_contexts),
        "not_verbatim_by_lenient_match_type": dict(sorted(Counter(item["lenient_match_type"] for item in unreachable_contexts).items())),
        "questions_with_unreachable_gold": len(affected),
        "official_em_ceiling": (len(order) - len(affected)) / len(order),
        "official_em1_on_affected_questions": em_on_affected,
        "affected_question_ids": affected,
        "unreachable_gold_contexts": unreachable_contexts,
    }
    unreachable_by_question = {qid: {item["hierarchy"] for item in unreachable_contexts if item["question_id"] == qid} for qid in affected}

    # 2. answered completeness by answer mode -------------------------------
    completeness = {}
    for name in C02_CONDITIONS:
        modes = {}
        for qid in order:
            row = official[qid][name]
            if row["status"] != "ANSWER":
                continue
            bucket = modes.setdefault(row["answer_mode"], {"answers": 0, "incomplete_lenient": 0, "incomplete_official": 0, "official_only_question_ids": []})
            bucket["answers"] += 1
            bucket["incomplete_lenient"] += int(not row["harness"]["complete"])
            bucket["incomplete_official"] += int(not row["official"]["complete"])
            if row["harness"]["complete"] and not row["official"]["complete"]:
                bucket["official_only_question_ids"].append(qid)
        for mode, bucket in modes.items():
            only_unreachable = []
            for qid in bucket["official_only_question_ids"]:
                predicted = {text_of(pid) for pid in official[qid][name]["accepted_provision_ids"]}
                missed = [c for c in questions[qid]["contexts"] if c["hierarchy"] + c["content"] not in predicted]
                only_unreachable.append(all(c["hierarchy"] + c["content"] not in corpus_set for c in missed))
            bucket["official_only"] = len(bucket["official_only_question_ids"])
            bucket["official_only_missing_only_unreachable_gold"] = sum(only_unreachable)
            _require(bucket["incomplete_official"] == bucket["incomplete_lenient"] + bucket["official_only"], "completeness arithmetic failed")
        completeness[name] = dict(sorted(modes.items()))

    # 3. abstain-excluded Token-F1 and local LF -----------------------------
    lf_rows = {row["question_id"]: row for row in _read_jsonl(args.lf_record / "per_question.jsonl")}
    lf_aggregate = json.loads((args.lf_record / "aggregate.json").read_text(encoding="utf-8"))
    _require(set(lf_rows) == set(order), "LF record covers different questions")
    eval_dirs = dict(args.eval)
    _require(set(eval_dirs) == set(C02_CONDITIONS), "--eval must name C02_KURE and C02_BM25S")

    token = {}
    for name in C02_CONDITIONS:
        csv_rows = {row["question_id"]: row for row in csv.DictReader((Path(eval_dirs[name]) / "per_question.csv").open(encoding="utf-8"))}
        aggregate = json.loads((Path(eval_dirs[name]) / "aggregate.json").read_text(encoding="utf-8"))
        token[name] = {}
        for qid in order:
            _require(csv_rows[qid]["status"] == official[qid][name]["status"] == lf_rows[qid][LF_KEYS[name]]["status"], "status mismatch: %s %s" % (name, qid))
            token[name][qid] = (
                float(csv_rows[qid]["token_f1_at_800"] or 0.0),
                float(csv_rows[qid]["candidate_token_f1_at_800"] or 0.0),
            )
        _require(abs(_mean([token[name][q][0] for q in order]) - aggregate["answer_quality"]["token_f1_at_800"]["end_to_end"]) < 1e-12, "%s public Token-F1 differs from frozen aggregate" % name)
        _require(abs(_mean([token[name][q][1] for q in order]) - aggregate["answer_quality"]["candidate_token_f1_at_800"]["all_outcomes"]) < 1e-12, "%s candidate Token-F1 differs from frozen aggregate" % name)
    parser_csv = {row["question_id"]: row for row in csv.DictReader(args.parser_eval_csv.open(encoding="utf-8"))}
    token[PARSER] = {qid: ((0.0 if parser_csv[qid]["error"] else float(parser_csv[qid]["token_f1"])),) * 2 for qid in order}

    def lf_score(name, qid, channel):
        return float(lf_rows[qid][LF_KEYS[name]][channel]["end_to_end_score_0_to_10"])

    for name in C02_CONDITIONS + (PARSER,):
        frozen = lf_aggregate["conditions"]["OUR_C02_BM25S_PARSER_FIRST_STAGE" if name == "C02_BM25S" else ("OUR_C02_KURE" if name == "C02_KURE" else PARSER)]
        for channel in ("public_answer", "candidate_answer"):
            _require(abs(_mean([lf_score(name, q, channel) for q in order]) - frozen[channel]["end_to_end_mean_0_to_10"]) < 1e-9, "%s %s LF differs from frozen aggregate" % (name, channel))

    abstain_excluded = {}
    for name in C02_CONDITIONS + (PARSER,):
        kept = [qid for qid in order if official[qid][name]["status"] != "ABSTAIN"]
        public_token = _mean([token[name][q][0] for q in kept])
        candidate_token = _mean([token[name][q][1] for q in kept])
        public_lf = _mean([lf_score(name, q, "public_answer") for q in kept])
        candidate_lf = _mean([lf_score(name, q, "candidate_answer") for q in kept])
        abstain_excluded[name] = {
            "questions": len(kept),
            "status_counts": dict(Counter(official[q][name]["status"] for q in kept)),
            "provision_f1_official": _mean([official[q][name]["official"]["f1"] for q in kept]),
            "provision_em_official": _mean([official[q][name]["official"]["em"] for q in kept]),
            "token_f1_at_800_public": public_token,
            "token_f1_at_800_candidate": candidate_token,
            "local_lf_0_to_10_public": public_lf,
            "local_lf_0_to_10_candidate": candidate_lf,
            "public_equals_candidate": abs(public_token - candidate_token) < 1e-12 and abs(public_lf - candidate_lf) < 1e-12,
        }
        frozen_subset = json.loads((args.official_record / "aggregate.json").read_text(encoding="utf-8"))["conditions"][name]["official_rule"]["abstain_removed"]
        _require(abs(abstain_excluded[name]["provision_f1_official"] - frozen_subset["macro_f1"]) < 1e-12, "%s abstain-excluded F1 differs from the official record" % name)

    for row in per_question:
        qid = row["question_id"]
        for name in C02_CONDITIONS + (PARSER,):
            row[name] = {
                "status": official[qid][name]["status"],
                "answer_mode": official[qid][name]["answer_mode"],
                "official_complete": official[qid][name]["official"]["complete"],
                "lenient_complete": official[qid][name]["harness"]["complete"],
                "token_f1_at_800_public": token[name][qid][0],
                "token_f1_at_800_candidate": token[name][qid][1],
                "local_lf_public": lf_score(name, qid, "public_answer"),
                "local_lf_candidate": lf_score(name, qid, "candidate_answer"),
            }

    aggregate = {
        "gold_reachability_official_rule": reachability,
        "answered_completeness_by_answer_mode": completeness,
        "abstain_excluded": abstain_excluded,
        "definitions": {
            "official_rule": "per-item exact hierarchy+content string sets (KoBLEX eval_pipeline.py::evaluate_retrieval)",
            "lenient_scoring": "provision rule of scripts/evaluate_dev_runs.py (stored as `harness` in the official-rule record)",
            "incomplete": "at least one gold provision not matched",
            "abstain_excluded": "ABSTAIN rows removed; EXECUTION_FAILURE rows kept with their stored scores",
            "local_lf": "adapted local Qwen3.8-27B judge, not the official GPT-4o LF-Eval",
        },
    }
    metadata = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "script": "scripts/analyze_official_rule_supplements.py",
        "script_sha256": _sha256(Path(__file__).resolve()),
        "git_commit": _git_commit(),
        "python": platform.python_version(),
        "uses_gpu_or_model": False,
        "inputs": {
            key: {"path": str(path), "sha256": _sha256(path)}
            for key, path in [
                ("official_record_per_question", args.official_record / "per_question.jsonl"),
                ("official_record_aggregate", args.official_record / "aggregate.json"),
                ("dataset", args.dataset),
                ("statute", args.statute),
                ("corpus", args.corpus),
                ("parser_eval_csv", args.parser_eval_csv),
                ("lf_per_question", args.lf_record / "per_question.jsonl"),
                ("lf_aggregate", args.lf_record / "aggregate.json"),
            ]
            + [("%s_per_question_csv" % n, Path(d) / "per_question.csv") for n, d in args.eval]
            + [("%s_aggregate" % n, Path(d) / "aggregate.json") for n, d in args.eval]
        },
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "aggregate.json").write_text(json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (args.output_dir / "per_question.jsonl").open("w", encoding="utf-8") as handle:
        for row in per_question:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    (args.output_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    kure_full = completeness["C02_KURE"]["full"]
    excluded = abstain_excluded
    lines = [
        "# Official-rule supplementary analyses",
        "",
        "Generated by `scripts/analyze_official_rule_supplements.py`; numbers below are rounded for display only, "
        "`aggregate.json` keeps full precision. Lenient scoring = provision rule of `scripts/evaluate_dev_runs.py`.",
        "",
        "## Gold reachability under the official rule",
        "",
        "| Item | Value | `aggregate.json` path |",
        "|---|---:|---|",
        "| Gold contexts | %d | `gold_reachability_official_rule.gold_contexts` |" % reachability["gold_contexts"],
        "| Not verbatim in statute corpus | %d | `gold_reachability_official_rule.gold_contexts_not_verbatim_in_corpus` |" % reachability["gold_contexts_not_verbatim_in_corpus"],
        "| Questions where official EM=1 is impossible | %d | `gold_reachability_official_rule.questions_with_unreachable_gold` |" % reachability["questions_with_unreachable_gold"],
        "| Official EM ceiling | %.2f%% | `gold_reachability_official_rule.official_em_ceiling` |" % (100 * reachability["official_em_ceiling"]),
        "| EM=1 on those questions (KURE / BM25s / ParSeR) | %d / %d / %d | `gold_reachability_official_rule.official_em1_on_affected_questions` |"
        % (em_on_affected["C02_KURE"], em_on_affected["C02_BM25S"], em_on_affected[PARSER]),
        "",
        "## C02 + KURE full-mode answers (paper section 6)",
        "",
        "| Item | Value | `aggregate.json` path |",
        "|---|---:|---|",
        "| Full-mode answers | %d | `answered_completeness_by_answer_mode.C02_KURE.full.answers` |" % kure_full["answers"],
        "| Incomplete, official rule | %d | `...C02_KURE.full.incomplete_official` |" % kure_full["incomplete_official"],
        "| Incomplete, lenient scoring | %d | `...C02_KURE.full.incomplete_lenient` |" % kure_full["incomplete_lenient"],
        "| Incomplete only under the official rule | %d | `...C02_KURE.full.official_only` |" % kure_full["official_only"],
        "| ...of which every missed gold provision is unreachable | %d | `...C02_KURE.full.official_only_missing_only_unreachable_gold` |" % kure_full["official_only_missing_only_unreachable_gold"],
        "",
        "## Abstain-excluded rows (ABSTAIN removed, execution failures kept)",
        "",
        "| Condition | Questions | Provision F1 | EM | Token-F1@800 | Local LF (/10) | Public = candidate |",
        "|---|---:|---:|---:|---:|---:|:---:|",
    ]
    for name, label in (("C02_KURE", "C02 + KURE"), ("C02_BM25S", "C02 + BM25s"), (PARSER, "ParSeR (Reproduced)")):
        item = excluded[name]
        lines.append(
            "| %s | %d | %.2f | %.2f | %.2f | %.3f | %s |"
            % (label, item["questions"], 100 * item["provision_f1_official"], 100 * item["provision_em_official"],
               100 * item["token_f1_at_800_public"], item["local_lf_0_to_10_public"], "yes" if item["public_equals_candidate"] else "no")
        )
    lines += ["", "Field paths: `abstain_excluded.<CONDITION>.*`. Local LF is an adapted local Qwen judge, not official LF-Eval.", ""]
    (args.output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    (args.output_dir / "SHA256SUMS").write_text(
        "".join("%s  %s\n" % (_sha256(args.output_dir / name), name) for name in ("aggregate.json", "per_question.jsonl", "summary.md")),
        encoding="utf-8",
    )
    print((args.output_dir / "summary.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
