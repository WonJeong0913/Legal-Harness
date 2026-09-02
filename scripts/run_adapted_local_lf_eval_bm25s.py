#!/usr/bin/env python3
"""Postprocess only the completed C02+ParSeR-bm25s run with local LF-Eval.

This runner never constructs an index, calls a retriever, changes a primary
metric, or sends anything outside the local Ollama endpoint.  It imports the
hash-sealed C02-vs-ParSeR adapted-local result as an immutable paired baseline,
then judges only the C02+bm25s published/candidate answers.  It is not the
official KoBLEX GPT-4o/DeepEval LF-Eval.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import run_adapted_local_lf_eval as base
from scripts import v2_kure_orchestration as v2


SCHEMA_VERSION = "adapted_local_lf_eval_c02_bm25s_linked_baseline_v1"
CONDITION = "OUR_C02_BM25S_PARSER_FIRST_STAGE"
BASELINE_CONDITIONS = ("OUR_C02_KURE", "PARSER_REPRODUCED")
EXPECTED_DATASET_SHA256 = "afdaff3a8000cdf5e0a64adbcfc8e6aff0042b318bf03718155f2b70f551c47b"
EXPECTED_BASELINE_RECEIPT_SHA256 = "49178990b277e5ab5f94883b4495908847a3486b7c73aef26b69a705b05a273d"
EXPECTED_BM25S_SOURCE_COMMIT = "edc9da4746b87cde61d967f0d8730cb8c9373649"
EXPECTED_BM25S_SOURCE_TREE = "9b3f613d8ffac9ce3c4b5f7ba2e172c242881553"
EXPECTED_BM25S_MANIFEST_SHA256 = "12cb09f808e047ae3e6d8067befa9341071a0588c2d2c71f94196f3e0f9a0964"


class LinkedB25sLFEvalError(RuntimeError):
    pass


def _fail(message: str) -> None:
    raise LinkedB25sLFEvalError(message)


def _json(path: Path, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LinkedB25sLFEvalError("invalid %s: %s" % (label, path)) from exc
    if not isinstance(value, Mapping):
        _fail("%s must be an object" % label)
    return dict(value)


def _jsonl(path: Path, label: str) -> List[Dict[str, Any]]:
    return base._read_jsonl(path, label)


def _string(value: Any, label: str) -> str:
    return base._require_string(value, label)


def _under(path: Path, root: Path, label: str) -> Path:
    return base._under(path, root, label)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    temporary = path.with_name(path.name + ".partial")
    if os.path.lexists(str(temporary)):
        _fail("stale partial checkpoint exists: %s" % temporary)
    temporary.write_text(json.dumps(dict(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _append_jsonl(path: Path, value: Mapping[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(value), ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _state(path: Path) -> Dict[str, Any]:
    return _json(path / "checkpoint.json", "LF-Eval checkpoint")


def _configuration(configuration: Mapping[str, Any]) -> None:
    if configuration.get("model") != v2.EXPECTED_RUNTIME["model"]:
        _fail("bm25s run used a different model alias")
    if configuration.get("ollama_endpoint") != v2.EXPECTED_RUNTIME["endpoint"]:
        _fail("bm25s run used a different Ollama endpoint")
    if configuration.get("seed") != 0:
        _fail("bm25s run seed must be zero")
    if configuration.get("retriever") != "bm25s_parser":
        _fail("input is not the ParSeR-compatible bm25s condition")
    provenance = configuration.get("retriever_provenance")
    if not isinstance(provenance, Mapping):
        _fail("bm25s retriever provenance is absent")
    required = {
        "backend": "bm25s.BM25",
        "bm25s_version": "0.3.10",
        "corpus_tokenization": "bm25s.tokenize(corpus, stopwords='en')",
        "query_tokenization": "bm25s.tokenize([query])",
        "top_k": 100,
        "first_stage_provision_id_deduplication": "FORBIDDEN",
        "fts5_query_expansion": "FORBIDDEN",
        "statute_hint_recall_channel": "FORBIDDEN",
    }
    for key, expected in required.items():
        if provenance.get(key) != expected:
            _fail("bm25s retriever provenance mismatch: %s" % key)
    if configuration.get("model_provenance") != v2.QWEN_MODEL_PROVENANCE:
        _fail("bm25s run Qwen provenance mismatch")


def _status_answer(result: Mapping[str, Any], summary: Mapping[str, Any], question_id: str) -> Dict[str, Any]:
    status = summary.get("status")
    if result.get("status") != status or result.get("run_id") != summary.get("run_id"):
        _fail("bm25s summary/result identity mismatch: %s" % question_id)
    answer, candidate = result.get("answer"), result.get("candidate_answer")
    candidate_status, candidate_basis = result.get("candidate_answer_status"), result.get("candidate_answer_basis")
    if status == "ANSWER":
        if not isinstance(answer, str) or not answer.strip() or candidate != answer:
            _fail("bm25s ANSWER must retain its exact published/candidate answer: %s" % question_id)
        if candidate_status != "PUBLISHED_ANSWER" or candidate_basis != "published_answer":
            _fail("bm25s ANSWER lacks published candidate provenance: %s" % question_id)
        return {"status": status, "published_answer": answer, "candidate_answer": candidate,
                "candidate_answer_status": candidate_status, "candidate_answer_basis": candidate_basis}
    if status == "ABSTAIN":
        if answer is not None:
            _fail("bm25s ABSTAIN leaked a public answer: %s" % question_id)
        if candidate_status == "GENERATED":
            if not isinstance(candidate, str) or not candidate.strip() or candidate_basis != "retrieved_candidates":
                _fail("bm25s ABSTAIN generated candidate contract failed: %s" % question_id)
        elif candidate_status == "EXECUTION_FAILURE":
            if candidate is not None or candidate_basis != "retrieved_candidates":
                _fail("bm25s ABSTAIN failed candidate contract failed: %s" % question_id)
        else:
            _fail("bm25s ABSTAIN candidate status is invalid: %s" % question_id)
        return {"status": status, "published_answer": None, "candidate_answer": candidate,
                "candidate_answer_status": candidate_status, "candidate_answer_basis": candidate_basis}
    if status == "EXECUTION_FAILURE":
        if answer is not None or candidate is not None or candidate_status is not None or candidate_basis is not None:
            _fail("bm25s execution failure leaked an answer: %s" % question_id)
        return {"status": status, "published_answer": None, "candidate_answer": None,
                "candidate_answer_status": None, "candidate_answer_basis": None}
    _fail("bm25s status is invalid: %s" % question_id)


def load_bm25s_condition(root: Path, dataset: Path) -> Tuple[List[str], Dict[str, Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    root = root.resolve()
    required_paths = {
        "plan": root / "plan.json", "final": root / "final.json", "batch_manifest": root / "batch" / "manifest.json",
        "batch_summary": root / "batch" / "summary.jsonl", "batch_metadata": root / "batch" / "metadata.json",
        "checkpoint": root / "checkpoints" / "checkpoint-226.json",
    }
    if not root.is_dir() or any(not value.is_file() for value in required_paths.values()):
        _fail("completed bm25s full226 input artifact is absent")
    plan, final = _json(required_paths["plan"], "bm25s plan"), _json(required_paths["final"], "bm25s final")
    manifest, metadata = _json(required_paths["batch_manifest"], "bm25s batch manifest"), _json(required_paths["batch_metadata"], "bm25s batch metadata")
    checkpoint, summary = _json(required_paths["checkpoint"], "bm25s final checkpoint"), _jsonl(required_paths["batch_summary"], "bm25s batch summary")
    if plan.get("mode") != "full226" or plan.get("entry_count") != base.TOTAL_QUESTIONS:
        _fail("bm25s plan is not full226")
    if plan.get("execution_policy") != "C02_BM25S_FIRST_STAGE_ONLY":
        _fail("bm25s plan execution policy mismatch")
    if plan.get("manifest_sha256") != EXPECTED_BM25S_MANIFEST_SHA256 or base.sha256(required_paths["batch_manifest"]) != EXPECTED_BM25S_MANIFEST_SHA256:
        _fail("bm25s manifest hash does not match the approved full226 input")
    manifest_path = Path(_string(plan.get("manifest"), "bm25s plan manifest"))
    if not manifest_path.is_file() or base.sha256(manifest_path) != EXPECTED_BM25S_MANIFEST_SHA256:
        _fail("bm25s frozen manifest is absent or hash-mismatched")
    source_snapshot = plan.get("source_snapshot")
    if not isinstance(source_snapshot, Mapping) or source_snapshot.get("git_commit") != EXPECTED_BM25S_SOURCE_COMMIT or source_snapshot.get("git_tree") != EXPECTED_BM25S_SOURCE_TREE:
        _fail("bm25s source snapshot is not the approved executable source")
    configuration = plan.get("frozen_configuration")
    if not isinstance(configuration, Mapping):
        _fail("bm25s frozen configuration is absent")
    _configuration(configuration)
    if metadata.get("configuration") != configuration or metadata.get("source_snapshot") != source_snapshot:
        _fail("bm25s batch metadata does not match the frozen plan")
    asset = plan.get("asset_provenance")
    if not isinstance(asset, Mapping) or not isinstance(asset.get("assets"), Mapping):
        _fail("bm25s asset provenance is absent")
    qa = asset["assets"].get("qa_parquet")
    if not isinstance(qa, Mapping) or qa.get("sha256") != EXPECTED_DATASET_SHA256:
        _fail("bm25s plan does not pin the canonical QA dataset")
    if not dataset.is_file() or base.sha256(dataset) != EXPECTED_DATASET_SHA256:
        _fail("supplied QA dataset does not match the canonical SHA256")
    entries = base._entries(manifest)
    roster = [str(entry["question_id"]) for entry in entries]
    if len(summary) != base.TOTAL_QUESTIONS or checkpoint.get("completed_questions") != base.TOTAL_QUESTIONS:
        _fail("bm25s collection is not complete")
    if checkpoint.get("checkpoint_status") != "COMPLETED_WITH_EXPLICIT_OUTCOMES" or checkpoint.get("manifest_sha256") != EXPECTED_BM25S_MANIFEST_SHA256:
        _fail("bm25s final checkpoint is not an auditable completed collection")
    if final.get("status") != "COMPLETED_WITH_EXPLICIT_OUTCOMES" or final.get("entry_count") != base.TOTAL_QUESTIONS:
        _fail("bm25s final status is not complete")
    outcomes: Dict[str, Dict[str, Any]] = {}
    result_hashes: Dict[str, str] = {}
    record_root = root / "records" / "runs"
    for entry, row in zip(entries, summary):
        ordinal, question_id = entry["ordinal"], str(entry["question_id"])
        if row.get("ordinal") != ordinal or row.get("source_ordinal") != ordinal or row.get("question_id") != question_id:
            _fail("bm25s summary does not preserve canonical roster order")
        record = _under(Path(_string(row.get("record_directory"), "bm25s record directory")), record_root, "bm25s record directory")
        result_path = _under(record / "result.json", record_root, "bm25s result")
        if not result_path.is_file() or row.get("record_result_file") != str(result_path):
            _fail("bm25s result file is absent or redirected: %s" % question_id)
        outcomes[question_id] = _status_answer(_json(result_path, "bm25s result"), row, question_id)
        result_hashes[question_id] = base.sha256(result_path)
    if len(outcomes) != base.TOTAL_QUESTIONS:
        _fail("bm25s outcome roster is not unique")
    counts = {status: sum(item["status"] == status for item in outcomes.values()) for status in ("ANSWER", "ABSTAIN", "EXECUTION_FAILURE")}
    if final.get("outcomes") != counts or checkpoint.get("outcomes") != counts or metadata.get("outcomes") != counts:
        _fail("bm25s final outcome counts disagree")
    hashes = {key: base.sha256(value) for key, value in required_paths.items()}
    provenance = {
        "condition": CONDITION, "output_root": str(root), "source_snapshot": dict(source_snapshot),
        "artifact_sha256": hashes, "result_sha256_by_question_id": result_hashes,
        "result_sha256_by_question_id_sha256": base.canonical_sha256(result_hashes),
        "dataset": str(dataset.resolve()), "dataset_sha256": base.sha256(dataset), "outcomes": counts,
    }
    provenance["input_bundle_sha256"] = base.canonical_sha256(provenance)
    return roster, outcomes, provenance, dict(configuration)


def _validate_channel(value: Any, label: str) -> None:
    if not isinstance(value, Mapping) or not isinstance(value.get("available"), bool):
        _fail("baseline %s score shape is invalid" % label)
    available, raw, end_to_end = value["available"], value.get("score_1_to_10"), value.get("end_to_end_score_0_to_10")
    if available:
        if isinstance(raw, bool) or not isinstance(raw, int) or not 1 <= raw <= 10 or end_to_end != raw:
            _fail("baseline %s available score is invalid" % label)
        for key in ("canonical_input_sha256", "prompt_sha256", "request_payload_sha256", "response_sha256"):
            if not isinstance(value.get(key), str) or len(value[key]) != 64:
                _fail("baseline %s lacks %s" % (label, key))
    elif raw is not None or end_to_end != 0:
        _fail("baseline %s unjudged-zero policy was violated" % label)


def metadata_aggregate_warning(metadata: Mapping[str, Any], actual_aggregate_sha256: str) -> Optional[Dict[str, str]]:
    declared = metadata.get("aggregate_sha256")
    if declared == actual_aggregate_sha256:
        return None
    return {"code": "LEGACY_METADATA_AGGREGATE_SHA256_STALE", "metadata_value": str(declared), "actual_file_sha256": actual_aggregate_sha256,
            "handling": "receipt.json plus actual artifact hashes are authoritative; legacy metadata value retained without mutation"}


def load_immutable_baseline(root: Path, roster: Sequence[str], dataset_sha256: str) -> Tuple[Dict[str, Dict[str, Dict[str, Any]]], Dict[str, Any], List[Dict[str, str]]]:
    root = root.resolve()
    paths = {name: root / name for name in ("aggregate.json", "metadata.json", "per_question.jsonl", "receipt.json")}
    if not root.is_dir() or any(not path.is_file() for path in paths.values()):
        _fail("immutable C02-vs-ParSeR adapted LF-Eval artifact is absent")
    if base.sha256(paths["receipt.json"]) != EXPECTED_BASELINE_RECEIPT_SHA256:
        _fail("baseline receipt is not the approved immutable C02-vs-ParSeR artifact")
    receipt, aggregate, metadata = _json(paths["receipt.json"], "baseline receipt"), _json(paths["aggregate.json"], "baseline aggregate"), _json(paths["metadata.json"], "baseline metadata")
    if receipt.get("schema_version") != base.SCHEMA_VERSION or metadata.get("schema_version") != base.SCHEMA_VERSION:
        _fail("baseline schema mismatch")
    for field, path in (("aggregate_sha256", paths["aggregate.json"]), ("metadata_sha256", paths["metadata.json"]), ("per_question_sha256", paths["per_question.jsonl"])):
        if receipt.get(field) != base.sha256(path):
            _fail("baseline receipt hash mismatch: %s" % field)
    warnings: List[Dict[str, str]] = []
    warning = metadata_aggregate_warning(metadata, base.sha256(paths["aggregate.json"]))
    if warning is not None:
        warnings.append(warning)
    if aggregate.get("evaluator_id") != base.EVALUATOR_ID or aggregate.get("official_lf_eval", {}).get("score_equivalence") != "FORBIDDEN":
        _fail("baseline is not an adapted non-official LF-Eval")
    judge = aggregate.get("adapted_local_judge")
    if not isinstance(judge, Mapping) or judge.get("model_alias") != v2.EXPECTED_RUNTIME["model"] or judge.get("temperature") != 0 or judge.get("seed") != 0:
        _fail("baseline local judge configuration mismatch")
    if judge.get("prompt_template_sha256") != base._sha256_bytes(base.LOCAL_PROMPT_TEMPLATE.encode("utf-8")) or judge.get("rubric_sha256") != base.canonical_sha256(base.OFFICIAL_RUBRIC):
        _fail("baseline local rubric/prompt hash mismatch")
    provenance = aggregate.get("input_provenance")
    if not isinstance(provenance, Mapping) or provenance.get("canonical_roster_sha256") != base.canonical_sha256(list(roster)):
        _fail("baseline roster hash mismatch")
    if provenance.get("kure_c02", {}).get("source_dataset_sha256") != dataset_sha256:
        _fail("baseline C02 dataset hash mismatch")
    parser_path = provenance.get("parser_reproduced", {}).get("final_results")
    parser_sha = provenance.get("parser_reproduced", {}).get("final_results_sha256")
    if not isinstance(parser_path, str) or not Path(parser_path).is_file() or base.sha256(Path(parser_path)) != parser_sha:
        _fail("baseline ParSeR source is absent or hash-mismatched")
    rows = _jsonl(paths["per_question.jsonl"], "baseline per-question")
    if len(rows) != base.TOTAL_QUESTIONS:
        _fail("baseline does not contain 226 paired rows")
    result: Dict[str, Dict[str, Dict[str, Any]]] = {condition: {} for condition in BASELINE_CONDITIONS}
    source_keys = {"OUR_C02_KURE": "kure", "PARSER_REPRODUCED": "parser_reproduced"}
    for ordinal, (question_id, row) in enumerate(zip(roster, rows), start=1):
        if row.get("ordinal") != ordinal or row.get("question_id") != question_id:
            _fail("baseline per-question roster order mismatch")
        for condition, key in source_keys.items():
            item = row.get(key)
            if not isinstance(item, Mapping) or item.get("status") not in {"ANSWER", "ABSTAIN", "EXECUTION_FAILURE"}:
                _fail("baseline condition row is invalid: %s" % condition)
            _validate_channel(item.get("public_answer"), condition + ".public")
            _validate_channel(item.get("candidate_answer"), condition + ".candidate")
            result[condition][question_id] = dict(item)
    for condition in BASELINE_CONDITIONS:
        expected = base._aggregate(result[condition], roster)
        if aggregate.get("conditions", {}).get(condition) != expected:
            _fail("baseline aggregate mismatch: %s" % condition)
    baseline_provenance = {"root": str(root), "receipt_sha256": base.sha256(paths["receipt.json"]),
                           "artifact_sha256": {name: base.sha256(path) for name, path in paths.items()},
                           "warnings": warnings}
    return result, baseline_provenance, warnings


def _cache_put(cache: MutableMapping[str, Dict[str, Any]], value: Mapping[str, Any], source: str) -> None:
    if not value.get("available"):
        return
    prompt = value.get("prompt_sha256")
    if not isinstance(prompt, str):
        _fail("available score lacks prompt hash: %s" % source)
    existing = cache.get(prompt)
    if existing is not None and existing.get("score_1_to_10") != value.get("score_1_to_10"):
        _fail("same prompt has conflicting immutable local scores")
    cache[prompt] = dict(value)


def _journal(path: Path) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    if not path.exists():
        return {}
    result: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for row in _jsonl(path, "judge journal"):
        qid, channel, prompt = row.get("question_id"), row.get("channel"), row.get("prompt_sha256")
        value = row.get("score")
        if not isinstance(qid, str) or channel not in {"public_answer", "candidate_answer"} or not isinstance(prompt, str) or not isinstance(value, Mapping):
            _fail("judge journal row is invalid")
        key = (qid, channel, prompt)
        if key in result:
            _fail("judge journal contains a duplicate scored channel")
        _validate_channel(value, "journal")
        if not value.get("available") or value.get("prompt_sha256") != prompt:
            _fail("judge journal score identity is invalid")
        result[key] = dict(value)
    return result


def _scored_channel(gold: Mapping[str, Any], answer: Optional[str], channel: str, question_id: str,
                    cache: MutableMapping[str, Dict[str, Any]], journal: MutableMapping[Tuple[str, str, str], Dict[str, Any]],
                    journal_path: Path, timeout_seconds: float) -> Dict[str, Any]:
    if answer is None:
        return base._score(gold, None, channel, cache, timeout_seconds)
    prediction = base.official_prediction(answer)
    if not prediction:
        return base._score(gold, answer, channel, cache, timeout_seconds)
    prompt = base.build_prompt(gold, prediction)
    prompt_sha256 = base._sha256_bytes(prompt.encode("utf-8"))
    key = (question_id, channel, prompt_sha256)
    if key in journal:
        restored = dict(journal[key])
        restored.update({"channel": channel, "checkpoint_reused": True})
        return restored
    prior = set(cache)
    value = base._score(gold, answer, channel, cache, timeout_seconds)
    if not value.get("available") or value.get("prompt_sha256") != prompt_sha256:
        _fail("judge produced an invalid score record")
    value = dict(value)
    value["checkpoint_reused"] = False
    value["immutable_baseline_cache_reused"] = prompt_sha256 in prior
    _append_jsonl(journal_path, {"question_id": question_id, "channel": channel, "prompt_sha256": prompt_sha256,
                                 "answer_sha256": base._sha256_bytes(answer.encode("utf-8")), "score": value})
    journal[key] = dict(value)
    return value


def _evaluate_bm25s(outcomes: Mapping[str, Mapping[str, Any]], gold: Mapping[str, Mapping[str, Any]], roster: Sequence[str],
                     cache: MutableMapping[str, Dict[str, Any]], journal: MutableMapping[Tuple[str, str, str], Dict[str, Any]],
                     journal_path: Path, checkpoint_path: Path, state: Mapping[str, Any], timeout_seconds: float, checkpoint_every: int) -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
    for ordinal, question_id in enumerate(roster, start=1):
        item = outcomes[question_id]
        public = _scored_channel(gold[question_id], item.get("published_answer"), "public_answer", question_id, cache, journal, journal_path, timeout_seconds)
        public["source_status"] = item["status"]
        if not public["available"]:
            public["zero_policy"] = base.PUBLIC_ZERO_POLICY
        candidate = _scored_channel(gold[question_id], item.get("candidate_answer"), "candidate_answer", question_id, cache, journal, journal_path, timeout_seconds)
        candidate.update({"source_status": item["status"], "candidate_answer_status": item.get("candidate_answer_status"), "candidate_answer_basis": item.get("candidate_answer_basis")})
        if not candidate["available"]:
            candidate["zero_policy"] = base.CANDIDATE_ZERO_POLICY
        results[question_id] = {"status": item["status"], "public_answer": public, "candidate_answer": candidate}
        if len(journal) and len(journal) % checkpoint_every == 0:
            checkpoint = dict(state)
            checkpoint.update({"status": "IN_PROGRESS", "completed_judgment_channels": len(journal), "last_ordinal": ordinal})
            _atomic_json(checkpoint_path, checkpoint)
            print(json.dumps({"status": "IN_PROGRESS", "completed_judgment_channels": len(journal), "last_ordinal": ordinal}, ensure_ascii=False), flush=True)
    return results


def _provenance() -> Dict[str, Any]:
    return {"project_root": str(PROJECT_ROOT), "git_commit": base._git_provenance().get("git_commit"),
            "git_tree": base._git_provenance().get("git_tree"), "postprocessor_sha256": base.sha256(Path(__file__))}


def run_linked_bm25s_lf_eval(bm25s_output_root: Path, baseline_output: Path, dataset: Path, output_dir: Path,
                              timeout_seconds: float = 120.0, resume: bool = False, prepare_only: bool = False,
                              checkpoint_every: int = 20) -> Dict[str, Any]:
    if checkpoint_every < 1:
        _fail("checkpoint interval must be positive")
    bm25s_output_root, baseline_output, dataset, output_dir = (path.resolve() for path in (bm25s_output_root, baseline_output, dataset, output_dir))
    if output_dir in {bm25s_output_root, baseline_output}:
        _fail("output cannot equal an input artifact")
    roster, bm25s, bm25s_provenance, configuration = load_bm25s_condition(bm25s_output_root, dataset)
    gold = base.load_gold_items(dataset)
    if set(roster) - set(gold):
        _fail("canonical roster is absent from QA dataset")
    baseline, baseline_provenance, warnings = load_immutable_baseline(baseline_output, roster, bm25s_provenance["dataset_sha256"])
    input_identity = {"schema_version": SCHEMA_VERSION, "canonical_roster_sha256": base.canonical_sha256(roster),
                      "bm25s_input_bundle_sha256": bm25s_provenance["input_bundle_sha256"], "baseline_receipt_sha256": baseline_provenance["receipt_sha256"],
                      "dataset_sha256": bm25s_provenance["dataset_sha256"]}
    input_identity_sha256 = base.canonical_sha256(input_identity)
    checkpoint_path, journal_path = output_dir / "checkpoint.json", output_dir / "judge_journal.jsonl"
    if resume:
        if not output_dir.is_dir() or not checkpoint_path.is_file():
            _fail("--resume requires a prepared unfinished output directory")
        state = _state(output_dir)
        if state.get("input_identity_sha256") != input_identity_sha256 or state.get("status") == "FINALIZED":
            _fail("resume checkpoint does not match this immutable input bundle")
    else:
        if os.path.lexists(str(output_dir)):
            _fail("refusing to overwrite linked LF-Eval output")
        output_dir.mkdir(parents=True)
        state = {"schema_version": SCHEMA_VERSION, "status": "PREPARED", "input_identity": input_identity,
                 "input_identity_sha256": input_identity_sha256, "baseline_warnings": warnings, "completed_judgment_channels": 0, "last_ordinal": 0}
        _atomic_json(checkpoint_path, state)
    if prepare_only:
        return {"status": "PREPARED", "output_dir": str(output_dir), "input_identity_sha256": input_identity_sha256}
    os.environ.update(v2.OFFLINE_ENVIRONMENT)
    readiness = base._verify_judge(configuration, timeout_seconds)
    journal = _journal(journal_path)
    cache: Dict[str, Dict[str, Any]] = {}
    for condition in BASELINE_CONDITIONS:
        for row in baseline[condition].values():
            _cache_put(cache, row["public_answer"], "baseline")
            _cache_put(cache, row["candidate_answer"], "baseline")
    for value in journal.values():
        _cache_put(cache, value, "journal")
    bm25s_scores = _evaluate_bm25s(bm25s, gold, roster, cache, journal, journal_path, checkpoint_path, state, timeout_seconds, checkpoint_every)
    rows: List[Dict[str, Any]] = []
    for ordinal, question_id in enumerate(roster, start=1):
        c02, parser, current = baseline["OUR_C02_KURE"][question_id], baseline["PARSER_REPRODUCED"][question_id], bm25s_scores[question_id]
        def delta(left: Mapping[str, Any], right: Mapping[str, Any]) -> Dict[str, int]:
            return {"public_answer_end_to_end_0_to_10": left["public_answer"]["end_to_end_score_0_to_10"] - right["public_answer"]["end_to_end_score_0_to_10"],
                    "candidate_answer_end_to_end_0_to_10": left["candidate_answer"]["end_to_end_score_0_to_10"] - right["candidate_answer"]["end_to_end_score_0_to_10"]}
        rows.append({"ordinal": ordinal, "question_id": question_id, "kure": c02, "parser_reproduced": parser,
                     "bm25s_parser_first_stage": current, "paired_delta_bm25s_minus_c02": delta(current, c02),
                     "paired_delta_bm25s_minus_parser": delta(current, parser)})
    aggregate = {"schema_version": SCHEMA_VERSION, "evaluator_id": base.EVALUATOR_ID,
                 "official_lf_eval": {"evaluator_id": base.OFFICIAL_EVALUATOR_ID, "source_url": base.OFFICIAL_SOURCE_URL,
                                      "execution_status": "NOT_EXECUTED_EXTERNAL_GPT4O_DEEPEVAL_FORBIDDEN", "score_equivalence": "FORBIDDEN",
                                      "reproduced_rubric_sha256": base.canonical_sha256(base.OFFICIAL_RUBRIC), "official_prediction_projection": "answer.split(\"<\\think>\")[0][:800]"},
                 "adapted_local_judge": {"model_alias": v2.EXPECTED_RUNTIME["model"], "endpoint": v2.EXPECTED_RUNTIME["endpoint"], "temperature": 0, "seed": 0,
                                         "prompt_template_sha256": base._sha256_bytes(base.LOCAL_PROMPT_TEMPLATE.encode("utf-8")), "rubric_sha256": base.canonical_sha256(base.OFFICIAL_RUBRIC), "readiness": readiness},
                 "execution_prohibitions": {"primary_score_injection": "FORBIDDEN", "bm25s_retriever_execution": "FORBIDDEN_BY_POSTPROCESSOR", "parser_execution": "FORBIDDEN", "external_api": "FORBIDDEN"},
                 "input_provenance": {"canonical_roster_sha256": base.canonical_sha256(roster), "bm25s": bm25s_provenance, "immutable_c02_parser_baseline": baseline_provenance, "warnings": warnings},
                 "conditions": {"OUR_C02_KURE": base._aggregate(baseline["OUR_C02_KURE"], roster), "PARSER_REPRODUCED": base._aggregate(baseline["PARSER_REPRODUCED"], roster), CONDITION: base._aggregate(bm25s_scores, roster)},
                 "paired_delta_definition": "%s minus immutable C02 and immutable ParSeR linked baseline; no judge call for non-answers or failures" % CONDITION}
    base._write_json_new(output_dir / "aggregate.json", aggregate)
    metadata = {"schema_version": SCHEMA_VERSION, "evaluator_id": base.EVALUATOR_ID, "official_comparability": "FORBIDDEN_NOT_OFFICIAL_GPT4O_DEEPEVAL_LF_EVAL",
                "score_import_shape": "INTENTIONALLY_INCOMPATIBLE_WITH_evaluate_dev_runs.load_lf_eval_scores", "source": _provenance(),
                "aggregate_sha256": base.sha256(output_dir / "aggregate.json"), "canonical_aggregate_sha256": base.canonical_sha256(aggregate), "per_question_schema": "three-condition linked local judge records; not a primary-evaluation import"}
    base._write_json_new(output_dir / "metadata.json", metadata)
    base._write_jsonl_new(output_dir / "per_question.jsonl", rows)
    receipt = {"schema_version": SCHEMA_VERSION, "metadata_sha256": base.sha256(output_dir / "metadata.json"),
               "per_question_sha256": base.sha256(output_dir / "per_question.jsonl"), "aggregate_sha256": base.sha256(output_dir / "aggregate.json"),
               "canonical_roster_sha256": base.canonical_sha256(roster), "input_identity_sha256": input_identity_sha256}
    base._write_json_new(output_dir / "receipt.json", receipt)
    final_state = dict(state)
    final_state.update({"status": "FINALIZED", "completed_judgment_channels": len(journal), "last_ordinal": base.TOTAL_QUESTIONS,
                        "receipt_sha256": base.sha256(output_dir / "receipt.json")})
    _atomic_json(checkpoint_path, final_state)
    return {"status": "PASS", "output_dir": str(output_dir), "receipt": receipt, "aggregate": aggregate}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bm25s-output-root", type=Path, required=True)
    parser.add_argument("--baseline-adapted-output", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--checkpoint-every", type=int, default=20)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--prepare-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_linked_bm25s_lf_eval(args.bm25s_output_root, args.baseline_adapted_output, args.dataset, args.output_dir,
                                       args.timeout_seconds, args.resume, args.prepare_only, args.checkpoint_every)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
