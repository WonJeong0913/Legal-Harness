#!/usr/bin/env python3
"""Run an isolated paired adapted-local legal-fidelity evaluation.

This postprocessor is deliberately *not* the official KoBLEX LF-Eval.  The
official implementation uses DeepEval with an external GPT-4o judge.  This
tool copies its published legal-fidelity rubric and 800-character prediction
projection, but sends those frozen inputs only to the local
``legal-harness-qwen38-q8`` Ollama model.  Its schema makes that non-
equivalence explicit and cannot be consumed by ``--lf-eval-scores``.

It reads, but never modifies, a completed C36 KURE full226 result and the
completed reproduced ParSeR full226 ``final_results.jsonl``.  BM25, ParSeR
execution, KURE execution, score injection, and any external API are outside
this program's scope.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import v2_kure_orchestration as v2


SCHEMA_VERSION = "adapted_local_lf_eval_dual_condition_v1"
EVALUATOR_ID = "ADAPTED_LOCAL_QWEN38_LF_EVAL"
OFFICIAL_EVALUATOR_ID = "OFFICIAL_KOBLEX_GPT4O_DEEPEVAL_LF_EVAL"
OFFICIAL_SOURCE_URL = "https://github.com/daehuikim/KoBLEX/blob/main/experiments/lf-eval/eval_pipeline.py"
TOTAL_QUESTIONS = 226
PUBLIC_ZERO_POLICY = "NON_ANSWER_OR_EXECUTION_FAILURE_IS_UNJUDGED_ZERO_FOR_END_TO_END"
CANDIDATE_ZERO_POLICY = "MISSING_OR_EXECUTION_FAILURE_CANDIDATE_IS_UNJUDGED_ZERO_FOR_END_TO_END"

# Reproduced verbatim from KoBLEX's evaluate_legal_fidelity() GEval setup.
OFFICIAL_CRITERIA = (
    "You will be given a complex legal question along with the relevant legal provisions that can be used to resolve it.\n"
    "Evaluate the legal accuracy of the response on a scale from 1 to 10. \n"
    "A score of 1 means the response addresses a completely unrelated situation and a score of 10 means the response correctly and thoroughly uses all of the given legal provisions.\n"
)
OFFICIAL_EVALUATION_STEPS = (
    "Check whether the 'actual output' properly answers the 'input' question.",
    "Check whether the 'actual output' contradicts or omits any legal facts or provisions in the 'context'.",
    "Heavily penalize if the legal conclusion differs in detail from the 'expected output'.",
    "Heavily penalize if the 'actual output' contradicts or omits any specific elements from the 'context'.",
    "Heavily penalize responses that include statements like 'The given context does not include the answer, but generally speaking...'.",
)
OFFICIAL_RUBRIC = {
    "criteria": OFFICIAL_CRITERIA,
    "evaluation_steps": list(OFFICIAL_EVALUATION_STEPS),
    "evaluation_params": ("input", "actual_output", "expected_output", "context"),
}
LOCAL_PROMPT_TEMPLATE = """This is an adapted local Qwen legal-fidelity judge, not the official GPT-4o/DeepEval LF-Eval. Do not claim official-score equivalence.
Apply the following official KoBLEX legal-fidelity rubric and evaluation steps exactly to the structured case below.

[OFFICIAL_CRITERIA]
{criteria}
[OFFICIAL_EVALUATION_STEPS]
{steps}
[CASE]
{case_json}

Return only a JSON object of the exact form {{"score": INTEGER}}, where INTEGER is from 1 through 10.
"""


class AdaptedLocalLFEvalError(RuntimeError):
    """The postprocessor cannot prove a paired, isolated local evaluation."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: Any) -> str:
    return _sha256_bytes(canonical_json(value).encode("utf-8"))


def _read_json(path: Path, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdaptedLocalLFEvalError("invalid %s: %s" % (label, path)) from exc
    if not isinstance(value, Mapping):
        raise AdaptedLocalLFEvalError("%s must be a JSON object: %s" % (label, path))
    return dict(value)


def _read_jsonl(path: Path, label: str) -> List[Dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise AdaptedLocalLFEvalError("cannot read %s: %s" % (label, path)) from exc
    rows: List[Dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AdaptedLocalLFEvalError("invalid %s row %d" % (label, line_number)) from exc
        if not isinstance(value, Mapping):
            raise AdaptedLocalLFEvalError("%s row %d must be an object" % (label, line_number))
        rows.append(dict(value))
    return rows


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdaptedLocalLFEvalError("%s must be a non-empty string" % label)
    return value


def _require_mapping(value: Any, label: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise AdaptedLocalLFEvalError("%s must be an object" % label)
    return dict(value)


def _under(path: Path, root: Path, label: str) -> Path:
    resolved, parent = path.resolve(), root.resolve()
    try:
        resolved.relative_to(parent)
    except ValueError as exc:
        raise AdaptedLocalLFEvalError("%s must remain under %s" % (label, parent)) from exc
    return resolved


def _write_json_new(path: Path, value: Mapping[str, Any]) -> None:
    if os.path.lexists(str(path)):
        raise AdaptedLocalLFEvalError("refusing to overwrite output: %s" % path)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl_new(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    if os.path.lexists(str(path)):
        raise AdaptedLocalLFEvalError("refusing to overwrite output: %s" % path)
    path.write_text(
        "".join(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def official_prediction(answer: str) -> str:
    """Exact KoBLEX ``temp_answer.split("<\\think>")[0][:800]`` behavior."""
    return answer.split("<\think>")[0][:800] if answer else ""  # noqa: W605 - official escape behavior


def _gold_item(raw: Mapping[str, Any], label: str) -> Dict[str, Any]:
    question_id = _require_string(raw.get("id"), label + ".id")
    answer = _require_string(raw.get("answer"), label + ".answer")
    question = str(raw.get("background") or "") + str(raw.get("question") or "")
    if not question.strip():
        raise AdaptedLocalLFEvalError("%s question is empty" % label)
    contexts_raw = raw.get("contexts")
    if not isinstance(contexts_raw, list):
        raise AdaptedLocalLFEvalError("%s.contexts must be an array" % label)
    contexts: List[str] = []
    for index, item in enumerate(contexts_raw, start=1):
        context = _require_mapping(item, "%s.contexts[%d]" % (label, index))
        contexts.append(str(context.get("hierarchy") or "") + str(context.get("content") or ""))
    return {"question_id": question_id, "input": question, "expected_output": answer, "context": contexts}


def load_gold_items(dataset_path: Path) -> Dict[str, Dict[str, Any]]:
    if dataset_path.suffix.lower() == ".jsonl":
        raw_rows = _read_jsonl(dataset_path, "gold dataset")
    elif dataset_path.suffix.lower() == ".parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise AdaptedLocalLFEvalError("pyarrow is required for the frozen KoBLEX parquet") from exc
        try:
            raw_rows = pq.read_table(
                str(dataset_path), columns=["id", "background", "question", "answer", "contexts", "n_hops"]
            ).to_pylist()
        except Exception as exc:  # pyarrow has several version-specific exception classes.
            raise AdaptedLocalLFEvalError("cannot load frozen KoBLEX dataset") from exc
    else:
        raise AdaptedLocalLFEvalError("frozen source dataset must be .parquet or .jsonl")
    result: Dict[str, Dict[str, Any]] = {}
    for index, raw in enumerate(raw_rows, start=1):
        item = _gold_item(_require_mapping(raw, "gold[%d]" % index), "gold[%d]" % index)
        if item["question_id"] in result:
            raise AdaptedLocalLFEvalError("gold dataset has duplicate question_id: %s" % item["question_id"])
        result[item["question_id"]] = item
    return result


def _entries(manifest: Mapping[str, Any]) -> List[Dict[str, Any]]:
    raw = manifest.get("entries")
    if not isinstance(raw, list) or len(raw) != TOTAL_QUESTIONS:
        raise AdaptedLocalLFEvalError("C36 full226 manifest must contain exactly 226 entries")
    entries: List[Dict[str, Any]] = []
    seen = set()
    for expected_ordinal, raw_entry in enumerate(raw, start=1):
        entry = _require_mapping(raw_entry, "manifest entry %d" % expected_ordinal)
        if entry.get("ordinal") != expected_ordinal:
            raise AdaptedLocalLFEvalError("C36 full226 ordinals must be contiguous")
        question_id = _require_string(entry.get("question_id"), "manifest question_id")
        if question_id in seen:
            raise AdaptedLocalLFEvalError("C36 full226 has duplicate question_id: %s" % question_id)
        seen.add(question_id)
        entries.append(dict(entry))
    return entries


def _configuration_is_frozen(configuration: Mapping[str, Any]) -> None:
    if configuration.get("model") != v2.EXPECTED_RUNTIME["model"]:
        raise AdaptedLocalLFEvalError("C36 model alias is not the frozen local Qwen alias")
    if configuration.get("ollama_endpoint") != v2.EXPECTED_RUNTIME["endpoint"]:
        raise AdaptedLocalLFEvalError("C36 Ollama endpoint is not the frozen local endpoint")
    if configuration.get("seed") != 0:
        raise AdaptedLocalLFEvalError("C36 seed must be zero")
    if configuration.get("model_provenance") != v2.QWEN_MODEL_PROVENANCE:
        raise AdaptedLocalLFEvalError("C36 Qwen provenance mismatch")


def _load_kure_condition(output_root: Path) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Any]]:
    mode_root = (output_root / "full226").resolve()
    plan_path = mode_root / "plan.json"
    plan = _read_json(plan_path, "C36 full226 plan")
    if plan.get("mode") != "full226" or plan.get("entry_count") != TOTAL_QUESTIONS:
        raise AdaptedLocalLFEvalError("input must be a completed C36 full226 output")
    policy = _require_mapping(plan.get("execution_policy"), "C36 execution_policy")
    if policy.get("bm25_execution") != "FORBIDDEN" or policy.get("lf_eval_score_injection") != "FORBIDDEN":
        raise AdaptedLocalLFEvalError("C36 plan does not retain its execution prohibitions")
    primary_path = Path(_require_string(plan.get("primary_manifest"), "plan.primary_manifest"))
    if not primary_path.is_file() or sha256(primary_path) != plan.get("primary_manifest_sha256"):
        raise AdaptedLocalLFEvalError("C36 primary manifest hash mismatch")
    manifest = _read_json(primary_path, "C36 primary manifest")
    entries = _entries(manifest)
    configuration = _require_mapping(manifest.get("frozen_configuration"), "C36 frozen_configuration")
    _configuration_is_frozen(configuration)
    if plan.get("frozen_configuration") != configuration:
        raise AdaptedLocalLFEvalError("C36 plan configuration mismatch")
    gate = _read_json(mode_root / "gate.json", "C36 full226 gate")
    if gate.get("status") not in {"PASS", v2.FULL226_COMPLETED_WITH_ERRORS}:
        raise AdaptedLocalLFEvalError("C36 full226 gate is not a completed collection")
    checkpoint = _read_json(mode_root / "checkpoints" / "checkpoint-226.json", "C36 final checkpoint")
    if checkpoint.get("completed_questions") != TOTAL_QUESTIONS:
        raise AdaptedLocalLFEvalError("C36 final checkpoint is not a 226-row collection")
    if checkpoint.get("checkpoint_status") == v2.FULL226_COMPLETED_WITH_ERRORS:
        if (
            checkpoint.get("collection_status") != v2.FULL226_EXPLICIT_FAILURE_COLLECTION
            or not isinstance(checkpoint.get("execution_failure_question_ids"), list)
            or checkpoint.get("execution_failure_count") != len(checkpoint["execution_failure_question_ids"])
            or not checkpoint["execution_failure_question_ids"]
            or checkpoint.get("validation_errors") != []
        ):
            raise AdaptedLocalLFEvalError("C36 completed-with-errors checkpoint is not auditable")
    elif checkpoint.get("checkpoint_status") != "PASS":
        raise AdaptedLocalLFEvalError("C36 final checkpoint is not a completed collection")
    if gate.get("status") != checkpoint.get("checkpoint_status"):
        raise AdaptedLocalLFEvalError("C36 gate/checkpoint collection status mismatch")
    if checkpoint.get("checkpoint_status") == v2.FULL226_COMPLETED_WITH_ERRORS and (
        gate.get("collection_status") != checkpoint.get("collection_status")
    ):
        raise AdaptedLocalLFEvalError("C36 gate/checkpoint collection status mismatch")
    if checkpoint.get("bm25_execution") != "FORBIDDEN" or checkpoint.get("lf_eval_score_injection") != "FORBIDDEN":
        raise AdaptedLocalLFEvalError("C36 final checkpoint relaxed a forbidden execution policy")
    batch_dir = Path(_require_string(checkpoint.get("batch_directory"), "checkpoint.batch_directory"))
    batch_dir = _under(batch_dir, mode_root, "checkpoint batch_directory")
    summary_path = batch_dir / "summary.jsonl"
    summary_rows = _read_jsonl(summary_path, "C36 checkpoint summary")
    if len(summary_rows) != TOTAL_QUESTIONS:
        raise AdaptedLocalLFEvalError("C36 checkpoint summary must contain 226 rows")
    outcome: Dict[str, Dict[str, Any]] = {}
    record_root = mode_root / "records" / "runs"
    for entry, summary in zip(entries, summary_rows):
        question_id = str(entry["question_id"])
        if summary.get("ordinal") != entry.get("ordinal") or summary.get("question_id") != question_id:
            raise AdaptedLocalLFEvalError("C36 checkpoint summary does not preserve frozen roster order")
        status = summary.get("status")
        if status not in {"ANSWER", "ABSTAIN", "EXECUTION_FAILURE"}:
            raise AdaptedLocalLFEvalError("invalid C36 outcome status: %s" % question_id)
        record_directory = _under(Path(_require_string(summary.get("record_directory"), "summary.record_directory")), record_root, "record_directory")
        result = _read_json(record_directory / "result.json", "C36 result")
        metadata = _read_json(record_directory / "metadata.json", "C36 metadata")
        if metadata.get("question_id") != question_id or result.get("status") != status:
            raise AdaptedLocalLFEvalError("C36 record identity/status mismatch: %s" % question_id)
        if summary.get("run_id") and result.get("run_id") != summary.get("run_id"):
            raise AdaptedLocalLFEvalError("C36 run_id mismatch: %s" % question_id)
        answer = result.get("answer")
        if status == "ANSWER":
            answer = _require_string(answer, "published answer for %s" % question_id)
        elif answer is not None:
            raise AdaptedLocalLFEvalError("non-ANSWER leaked a public answer: %s" % question_id)
        candidate = result.get("candidate_answer")
        if candidate is not None and (not isinstance(candidate, str) or not candidate.strip()):
            raise AdaptedLocalLFEvalError("invalid candidate answer: %s" % question_id)
        if status == "EXECUTION_FAILURE" and candidate is not None:
            raise AdaptedLocalLFEvalError("execution failure leaked a candidate answer: %s" % question_id)
        outcome[question_id] = {
            "status": status,
            "published_answer": answer if status == "ANSWER" else None,
            "candidate_answer": candidate,
            "candidate_answer_status": result.get("candidate_answer_status"),
            "candidate_answer_basis": result.get("candidate_answer_basis"),
            "record_directory": str(record_directory),
            "result_sha256": sha256(record_directory / "result.json"),
        }
    source_dataset = _require_mapping(manifest.get("source_dataset"), "C36 source_dataset")
    exec_root = Path(_require_string(plan.get("exec_root"), "plan.exec_root"))
    dataset_path = _under(exec_root / _require_string(source_dataset.get("path"), "source_dataset.path"), exec_root, "source dataset")
    if not dataset_path.is_file() or sha256(dataset_path) != source_dataset.get("sha256"):
        raise AdaptedLocalLFEvalError("frozen C36 source dataset hash mismatch")
    provenance = {
        "mode_root": str(mode_root),
        "plan_sha256": sha256(plan_path),
        "primary_manifest": str(primary_path.resolve()),
        "primary_manifest_sha256": sha256(primary_path),
        "gate_sha256": sha256(mode_root / "gate.json"),
        "checkpoint_sha256": sha256(mode_root / "checkpoints" / "checkpoint-226.json"),
        "checkpoint_batch": str(batch_dir),
        "checkpoint_summary_sha256": sha256(summary_path),
        "source_dataset": str(dataset_path),
        "source_dataset_sha256": sha256(dataset_path),
        "frozen_model_provenance": dict(v2.QWEN_MODEL_PROVENANCE),
    }
    return entries, outcome, provenance


def _parser_contexts(row: Mapping[str, Any], question_id: str) -> List[str]:
    contexts = row.get("gold_contexts")
    if not isinstance(contexts, list) or any(not isinstance(value, str) for value in contexts):
        raise AdaptedLocalLFEvalError("ParSeR gold_contexts invalid: %s" % question_id)
    return list(contexts)


def _load_parser_condition(
    parser_results: Path, entries: Sequence[Mapping[str, Any]], gold: Mapping[str, Mapping[str, Any]]
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    source_rows = _read_jsonl(parser_results, "ParSeR final_results")
    if len(source_rows) != TOTAL_QUESTIONS:
        raise AdaptedLocalLFEvalError("ParSeR final_results must contain exactly 226 rows")
    roster = [str(entry["question_id"]) for entry in entries]
    by_id: Dict[str, Dict[str, Any]] = {}
    source_order: List[str] = []
    for row in source_rows:
        question_id = _require_string(row.get("question_id"), "ParSeR question_id")
        if question_id in by_id:
            raise AdaptedLocalLFEvalError("ParSeR has duplicate question_id: %s" % question_id)
        by_id[question_id] = row
        source_order.append(question_id)
    if set(by_id) != set(roster):
        raise AdaptedLocalLFEvalError("ParSeR roster does not exactly match C36 full226")
    outcome: Dict[str, Dict[str, Any]] = {}
    for question_id in roster:
        row, expected = by_id[question_id], gold[question_id]
        if str(row.get("background") or "") + str(row.get("question") or "") != expected["input"]:
            raise AdaptedLocalLFEvalError("ParSeR question differs from frozen gold: %s" % question_id)
        if row.get("gold_answer") != expected["expected_output"]:
            raise AdaptedLocalLFEvalError("ParSeR gold answer differs from frozen gold: %s" % question_id)
        if _parser_contexts(row, question_id) != expected["context"]:
            raise AdaptedLocalLFEvalError("ParSeR gold contexts differ from frozen gold: %s" % question_id)
        error = row.get("error")
        answer = row.get("answer")
        if error:
            status, answer = "EXECUTION_FAILURE", None
        else:
            status, answer = "ANSWER", _require_string(answer, "ParSeR answer for %s" % question_id)
        outcome[question_id] = {
            "status": status,
            "published_answer": answer,
            "candidate_answer": answer,
            "candidate_answer_status": "PARSER_PUBLISHED_ANSWER" if answer else "EXECUTION_FAILURE",
            "candidate_answer_basis": "parser_published_answer",
        }
    return outcome, {
        "final_results": str(parser_results.resolve()),
        "final_results_sha256": sha256(parser_results),
        "source_order_sha256": canonical_sha256(source_order),
        "canonical_order_sha256": canonical_sha256(roster),
        "source_order_matches_c36": source_order == roster,
        "condition": "PARSER_REPRODUCED",
    }


def _verify_judge(configuration: Mapping[str, Any], timeout_seconds: float) -> Dict[str, Any]:
    readiness = v2.check_local_ollama_readiness(configuration, timeout_seconds=timeout_seconds)
    blob = Path(str(v2.QWEN_MODEL_PROVENANCE["ollama_model_blob"]))
    if not blob.is_file() or sha256(blob) != v2.QWEN_MODEL_PROVENANCE["sha256"]:
        raise AdaptedLocalLFEvalError("local Qwen blob does not match frozen SHA256")
    return {
        **readiness,
        "model_blob": str(blob),
        "model_blob_sha256": sha256(blob),
        "seed": 0,
        "temperature": 0,
    }


def build_prompt(gold: Mapping[str, Any], prediction: str) -> str:
    steps = "\n".join(OFFICIAL_EVALUATION_STEPS)
    case = {
        "input": gold["input"],
        "actual_output": prediction,
        "expected_output": gold["expected_output"],
        "context": gold["context"],
    }
    return LOCAL_PROMPT_TEMPLATE.format(criteria=OFFICIAL_CRITERIA, steps=steps, case_json=canonical_json(case))


def _judge_prompt(prompt: str, timeout_seconds: float) -> Tuple[int, str, Dict[str, Any]]:
    request_payload = {
        "model": v2.EXPECTED_RUNTIME["model"],
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0,
            "seed": 0,
            "num_ctx": int(v2.EXPECTED_RUNTIME["num_ctx"]),
            "num_predict": 32,
        },
    }
    request = Request(
        v2.EXPECTED_RUNTIME["endpoint"],
        data=canonical_json(request_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AdaptedLocalLFEvalError("local adapted judge request failed") from exc
    if not isinstance(payload, Mapping) or not isinstance(payload.get("response"), str):
        raise AdaptedLocalLFEvalError("local adapted judge returned no response text")
    response_text = str(payload["response"])
    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise AdaptedLocalLFEvalError("local adapted judge response is not JSON") from exc
    if not isinstance(parsed, Mapping) or isinstance(parsed.get("score"), bool) or not isinstance(parsed.get("score"), int):
        raise AdaptedLocalLFEvalError("local adapted judge response lacks an integer score")
    score = int(parsed["score"])
    if not 1 <= score <= 10:
        raise AdaptedLocalLFEvalError("local adapted judge score is outside 1..10")
    return score, response_text, request_payload


def _score(
    gold: Mapping[str, Any], answer: Optional[str], channel: str, cache: MutableMapping[str, Dict[str, Any]], timeout_seconds: float
) -> Dict[str, Any]:
    if answer is None:
        return {"available": False, "channel": channel, "judge_invoked": False, "score_1_to_10": None, "end_to_end_score_0_to_10": 0}
    prediction = official_prediction(answer)
    if not prediction:
        return {"available": False, "channel": channel, "judge_invoked": False, "score_1_to_10": None, "end_to_end_score_0_to_10": 0, "reason": "EMPTY_AFTER_OFFICIAL_TRUNCATION"}
    prompt = build_prompt(gold, prediction)
    prompt_sha256 = _sha256_bytes(prompt.encode("utf-8"))
    canonical_input = {
        "input": gold["input"], "actual_output": prediction,
        "expected_output": gold["expected_output"], "context": gold["context"],
    }
    if prompt_sha256 in cache:
        reused = dict(cache[prompt_sha256])
        reused.update({"channel": channel, "cache_reused": True})
        return reused
    score, response_text, request_payload = _judge_prompt(prompt, timeout_seconds)
    value = {
        "available": True,
        "channel": channel,
        "judge_invoked": True,
        "cache_reused": False,
        "score_1_to_10": score,
        "end_to_end_score_0_to_10": score,
        "canonical_input_sha256": canonical_sha256(canonical_input),
        "prompt_sha256": prompt_sha256,
        "request_payload_sha256": canonical_sha256(request_payload),
        "response_text": response_text,
        "response_sha256": _sha256_bytes(response_text.encode("utf-8")),
    }
    cache[prompt_sha256] = dict(value)
    return value


def _evaluate_condition(
    condition: Mapping[str, Mapping[str, Any]], gold: Mapping[str, Mapping[str, Any]], roster: Sequence[str], cache: MutableMapping[str, Dict[str, Any]], timeout_seconds: float
) -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
    for question_id in roster:
        item = condition[question_id]
        public = _score(gold[question_id], item.get("published_answer"), "public_answer", cache, timeout_seconds)
        public["source_status"] = item["status"]
        if not public["available"]:
            public["zero_policy"] = PUBLIC_ZERO_POLICY
        candidate = _score(gold[question_id], item.get("candidate_answer"), "candidate_answer", cache, timeout_seconds)
        candidate["source_status"] = item["status"]
        candidate["candidate_answer_status"] = item.get("candidate_answer_status")
        candidate["candidate_answer_basis"] = item.get("candidate_answer_basis")
        if not candidate["available"]:
            candidate["zero_policy"] = CANDIDATE_ZERO_POLICY
        results[question_id] = {"status": item["status"], "public_answer": public, "candidate_answer": candidate}
    return results


def _mean(values: Sequence[int]) -> Optional[float]:
    return round(sum(values) / len(values), 12) if values else None


def _aggregate(results: Mapping[str, Mapping[str, Any]], roster: Sequence[str]) -> Dict[str, Any]:
    public = [dict(results[question_id]["public_answer"]) for question_id in roster]
    candidate = [dict(results[question_id]["candidate_answer"]) for question_id in roster]
    return {
        "question_count": len(roster),
        "public_answer": {
            "policy": PUBLIC_ZERO_POLICY,
            "model_scored_count": sum(item["available"] for item in public),
            "unjudged_zero_count": sum(not item["available"] for item in public),
            "end_to_end_mean_0_to_10": _mean([int(item["end_to_end_score_0_to_10"]) for item in public]),
            "answered_only_mean_1_to_10": _mean([int(item["score_1_to_10"]) for item in public if item["available"]]),
        },
        "candidate_answer": {
            "policy": CANDIDATE_ZERO_POLICY,
            "model_scored_count": sum(item["available"] for item in candidate),
            "unjudged_zero_count": sum(not item["available"] for item in candidate),
            "end_to_end_mean_0_to_10": _mean([int(item["end_to_end_score_0_to_10"]) for item in candidate]),
            "available_only_mean_1_to_10": _mean([int(item["score_1_to_10"]) for item in candidate if item["available"]]),
        },
    }


def _git_provenance() -> Dict[str, Any]:
    def run(args: Sequence[str]) -> Optional[str]:
        try:
            return subprocess.run(args, cwd=PROJECT_ROOT, check=True, capture_output=True, text=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    return {
        "project_root": str(PROJECT_ROOT),
        "git_commit": run(("git", "rev-parse", "HEAD")),
        "git_tree": run(("git", "rev-parse", "HEAD^{tree}")),
        "git_status_porcelain": run(("git", "status", "--porcelain=v1", "--untracked-files=all")),
        "postprocessor_sha256": sha256(Path(__file__)),
    }


def run_adapted_local_lf_eval(kure_output_root: Path, parser_results: Path, output_dir: Path, timeout_seconds: float = 120.0) -> Dict[str, Any]:
    kure_output_root, parser_results, output_dir = kure_output_root.resolve(), parser_results.resolve(), output_dir.resolve()
    if not kure_output_root.is_dir() or not parser_results.is_file():
        raise AdaptedLocalLFEvalError("KURE output root or ParSeR final_results input is absent")
    if os.path.lexists(str(output_dir)):
        raise AdaptedLocalLFEvalError("refusing to overwrite adapted evaluator output")
    for source in (kure_output_root, parser_results):
        try:
            output_dir.relative_to(source)
        except ValueError:
            continue
        raise AdaptedLocalLFEvalError("adapted evaluator output must not be inside an input artifact")
    entries, kure, kure_provenance = _load_kure_condition(kure_output_root)
    source_dataset = Path(kure_provenance["source_dataset"])
    gold = load_gold_items(source_dataset)
    roster = [str(entry["question_id"]) for entry in entries]
    if set(roster) - set(gold):
        raise AdaptedLocalLFEvalError("C36 roster has question(s) absent from frozen source dataset")
    parser, parser_provenance = _load_parser_condition(parser_results, entries, gold)
    configuration = _read_json(Path(kure_provenance["primary_manifest"]), "C36 primary manifest")["frozen_configuration"]
    os.environ.update(v2.OFFLINE_ENVIRONMENT)
    readiness = _verify_judge(_require_mapping(configuration, "C36 frozen configuration"), timeout_seconds)
    cache: Dict[str, Dict[str, Any]] = {}
    kure_scores = _evaluate_condition(kure, gold, roster, cache, timeout_seconds)
    parser_scores = _evaluate_condition(parser, gold, roster, cache, timeout_seconds)
    paired_rows: List[Dict[str, Any]] = []
    for ordinal, question_id in enumerate(roster, start=1):
        kure_row, parser_row = kure_scores[question_id], parser_scores[question_id]
        paired_rows.append({
            "ordinal": ordinal,
            "question_id": question_id,
            "kure": kure_row,
            "parser_reproduced": parser_row,
            "paired_delta_parser_minus_kure": {
                "public_answer_end_to_end_0_to_10": parser_row["public_answer"]["end_to_end_score_0_to_10"] - kure_row["public_answer"]["end_to_end_score_0_to_10"],
                "candidate_answer_end_to_end_0_to_10": parser_row["candidate_answer"]["end_to_end_score_0_to_10"] - kure_row["candidate_answer"]["end_to_end_score_0_to_10"],
            },
        })
    aggregate = {
        "schema_version": SCHEMA_VERSION,
        "evaluator_id": EVALUATOR_ID,
        "official_lf_eval": {
            "evaluator_id": OFFICIAL_EVALUATOR_ID,
            "source_url": OFFICIAL_SOURCE_URL,
            "execution_status": "NOT_EXECUTED_EXTERNAL_GPT4O_DEEPEVAL_FORBIDDEN",
            "score_equivalence": "FORBIDDEN",
            "reproduced_rubric_sha256": canonical_sha256(OFFICIAL_RUBRIC),
            "official_prediction_projection": "answer.split(\"<\\think>\")[0][:800]",
        },
        "adapted_local_judge": {
            "model_alias": v2.EXPECTED_RUNTIME["model"],
            "endpoint": v2.EXPECTED_RUNTIME["endpoint"],
            "temperature": 0,
            "seed": 0,
            "prompt_template_sha256": _sha256_bytes(LOCAL_PROMPT_TEMPLATE.encode("utf-8")),
            "rubric_sha256": canonical_sha256(OFFICIAL_RUBRIC),
            "readiness": readiness,
        },
        "execution_prohibitions": {
            "kure_primary_score_injection": "FORBIDDEN",
            "bm25_execution": "FORBIDDEN",
            "parser_execution": "FORBIDDEN",
            "external_api": "FORBIDDEN",
        },
        "input_provenance": {
            "canonical_c36_roster_sha256": canonical_sha256(roster),
            "kure_c36": kure_provenance,
            "parser_reproduced": parser_provenance,
        },
        "conditions": {
            "OUR_C36_KURE": _aggregate(kure_scores, roster),
            "PARSER_REPRODUCED": _aggregate(parser_scores, roster),
        },
        "paired_delta_definition": "PARSER_REPRODUCED minus OUR_C36_KURE; no judge call for public abstentions or failures",
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "evaluator_id": EVALUATOR_ID,
        "official_comparability": "FORBIDDEN_NOT_OFFICIAL_GPT4O_DEEPEVAL_LF_EVAL",
        "score_import_shape": "INTENTIONALLY_INCOMPATIBLE_WITH_evaluate_dev_runs.load_lf_eval_scores",
        "source": _git_provenance(),
        "aggregate_sha256": canonical_sha256(aggregate),
        "per_question_schema": "paired local judge records; scores are not a primary-evaluation import",
    }
    _write_json_new(output_dir / "metadata.json", metadata)
    _write_jsonl_new(output_dir / "per_question.jsonl", paired_rows)
    _write_json_new(output_dir / "aggregate.json", aggregate)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "metadata_sha256": sha256(output_dir / "metadata.json"),
        "per_question_sha256": sha256(output_dir / "per_question.jsonl"),
        "aggregate_sha256": sha256(output_dir / "aggregate.json"),
        "canonical_roster_sha256": canonical_sha256(roster),
    }
    _write_json_new(output_dir / "receipt.json", receipt)
    return {"output_dir": str(output_dir), "receipt": receipt, "aggregate": aggregate}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kure-output-root", type=Path, required=True, help="completed C36 output root containing full226/")
    parser.add_argument("--parser-results", type=Path, required=True, help="completed reproduced ParSeR final_results.jsonl")
    parser.add_argument("--output-dir", type=Path, required=True, help="new, separate adapted-evaluator artifact directory")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = run_adapted_local_lf_eval(args.kure_output_root, args.parser_results, args.output_dir, args.timeout_seconds)
    print(json.dumps({"status": "PASS", "evaluator_id": EVALUATOR_ID, "output_dir": result["output_dir"], "receipt": result["receipt"]}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
