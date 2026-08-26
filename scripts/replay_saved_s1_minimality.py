#!/usr/bin/env python3
"""Bounded replay of immutable C02 questions through candidate S1 INITIAL_PLAN.

This is a prompt-ablation probe, not a harness launcher.  It restores only the
trusted original question and frozen model configuration, invokes exactly one
S1 INITIAL_PLAN, and never runs retrieval, S2, S3, policy, an evaluator, or a
benchmark candidate path.
"""

from __future__ import annotations

import argparse
import copy
import difflib
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness.validation import ValidationError, normalize_question, validate_initial_plan
from runtime.local_ollama_executor import LocalOllamaSkillExecutor


REPLAY_SCHEMA_VERSION = "saved_s1_initial_plan_minimality_probe.v1"
GENERATION_DIAGNOSTIC_SCHEMA_VERSION = "1.2"
C13_BASE_COMMIT = "96664c59eb6066f5f4c0d6c695f2d86ae1b38004"
C02_COMMIT = "c02e2818ad54e9d5a1a9bd02b604e987192bb244"
C02_TREE = "9fcb0ebceb0b3d96955f1626f2c952a457be930f"
C02_MODEL = "legal-harness-qwen38-q8"
C02_RETRIEVER = "kure"
C02_SOURCE_MANIFEST_SHA256 = "40591e4b6963abbe11b5b95e021c2abba9fb5b5bd7c8e2c379d04de9f6e41956"
C02_BATCH_MANIFEST_SHA256 = "74c61195e6ad5a63913106a33daa517b6bb2c0c6110dc513a23dc6e78b96f4c8"
C02_RECORD_ROOT = Path("/workspace/Legal-Harness/records/v2-kure-qwen38-offline-full226-c02e281-targeted-resume168-20260826")
C02_BATCH_RELATIVE = Path("batches/c02e281-targeted-resume-ord042-054-061-226-20260826")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
INITIAL_REQUEST_RE = re.compile(r"^RQ[1-9][0-9]*$")
S1_SKILL = "legal_issue_and_query_planning"
S1_ENTRY_POINT = "INITIAL_PLAN"
FORBIDDEN_STAGES = frozenset({
    "retrieval", "S2", "S3", "policy_action", "evaluator", "benchmark_candidate",
})


class ReplayError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReplayExpectations:
    question_id: str
    source_result_sha256: str
    source_metadata_sha256: str
    source_manifest_sha256: str
    source_task_receipt_sha256: str
    source_commit: str = C02_COMMIT
    source_tree: str = C02_TREE
    source_model: str = C02_MODEL
    source_retriever: str = C02_RETRIEVER
    source_manifest_lineage_sha256: str = C02_SOURCE_MANIFEST_SHA256


@dataclass(frozen=True)
class SavedSource:
    result_path: Path
    metadata_path: Path
    manifest_path: Path
    task_receipt_path: Path
    result_sha256: str
    metadata_sha256: str
    manifest_sha256: str
    task_receipt_sha256: str
    result: Dict[str, Any]
    metadata: Dict[str, Any]
    manifest: Dict[str, Any]
    task_receipt: Dict[str, Any]
    baseline_plan: Dict[str, Any]


@dataclass(frozen=True)
class ReplayResult:
    output_directory: Path
    payload: Dict[str, Any]
    resumed: bool = False


# These profile assertions deliberately constrain plan structure, not benchmark
# answers, statutes, provisions, or gold wording.  They are checked after the
# candidate output has passed the normal S1 initial-plan validator.
QUESTION_PROFILES: Dict[str, Dict[str, Any]] = {
    "qa_145_2hop_559_rand": {
        "class": "positive_background_role_lane_removed", "sequence": 98, "ordinal": 156, "n_hops": 2,
        "run_id": "79e8f8fe-7ad5-45b5-ad1a-f23a7f9b5b08", "receipt": "098_ord156_qa_145_2hop_559_rand.json",
        "hashes": ("7b2c8e37dce838d14d3b296cb81f0237604c3565242bc106d44b29ff316c80b1", "97961a45d709735868c36df1b1d42f6bdb077e003b556098b5d70e67db834644", "737e234dc5efcfe0b44466f9e18249a89815482f35fb5540d8c82931c35767b3"),
        "assertions": [{"kind": "at_most", "counts": {"answer_targets": 1, "issues": 1, "evidence_items": 1, "queries": 1}}, {"kind": "all_targets_have_critical_evidence"}],
    },
    "qa_68_1hop_100": {
        "class": "positive_stipulated_violation_penalty", "sequence": 26, "ordinal": 84, "n_hops": 1,
        "run_id": "5b86ff62-9d98-449a-b7fe-23a3a651e70b", "receipt": "026_ord084_qa_68_1hop_100.json",
        "hashes": ("31ebd58593b8d0a579ae7921413930db6161ea2449c5ad3971baca924e749981", "95a9b118327169a1da875fc1eff71ad0f29a6add485d7fdbbcd1f4d2f2cac7ef", "8b6ca8b976f5f025e479e55e420bb00b4847dfda157c0496fe0e153389d5137f"),
        "assertions": [{"kind": "at_most", "counts": {"answer_targets": 1, "issues": 1, "evidence_items": 2, "queries": 2}}, {"kind": "all_targets_have_critical_evidence"}],
    },
    "qa_209_3hop_360": {
        "class": "positive_unasked_fallback_removed", "sequence": 73, "ordinal": 131, "n_hops": 3,
        "run_id": "4c420b6d-9294-415c-8a13-f78f5ba2f454", "receipt": "073_ord131_qa_209_3hop_360.json",
        "hashes": ("2a21c28939e22e2d9bdca2538579ff2ddca022fab0899298fc59aad9da8462c3", "2870d7364f9b2bd280882321d935c02f30068a7aa7370a2a010c7ac9984f6a80", "eca7ae4c2c72f0395684caa7331d67f338fd64568fbfa93fae80e411a978ee14"),
        "assertions": [{"kind": "at_most", "counts": {"answer_targets": 1, "issues": 2, "evidence_items": 2, "queries": 2}}, {"kind": "all_targets_have_critical_evidence"}],
    },
    "qa_2_1hop_4": {
        "class": "positive_unasked_definition_lane_removed", "sequence": 75, "ordinal": 133, "n_hops": 1,
        "run_id": "38ed8363-7748-4022-8af4-5e61b5663c63", "receipt": "075_ord133_qa_2_1hop_4.json",
        "hashes": ("bdcaed80655f80abe1bdda9774ed3676dd78cd5bc9921fb1b5176c7146755490", "1834cf7f6fd640ce3b79d320ae60fa9fab2a823953bddcbdbb3e65aba9a85939", "929ee124c886ae54329a14ef644af4d9abe699741c400952aea710dd519c1a70"),
        "assertions": [{"kind": "at_most", "counts": {"answer_targets": 1, "issues": 1, "evidence_items": 1, "queries": 1}}, {"kind": "all_targets_have_critical_evidence"}],
    },
    "qa_435_2hop_678": {
        "class": "safety_two_explicit_outputs", "sequence": 82, "ordinal": 140, "n_hops": 2,
        "run_id": "97e5ae06-b5e9-4985-852e-3b4b5816a33b", "receipt": "082_ord140_qa_435_2hop_678.json",
        "hashes": ("c635691bab14475f260717da55f5c4a1018c2c1ed298c2372ea7571d90f5b2d5", "90ce2c6a1d3b956aef0beaaab0c3d16bfcd6a7f94473b6e9d596586d5b5a01eb", "77e7267fd63587d1fae54c879623e4038561741e0cb51d9ca9406fae0bdaf161"),
        "assertions": [{"kind": "at_least", "counts": {"answer_targets": 2, "evidence_items": 2, "queries": 2}}, {"kind": "all_targets_have_critical_evidence"}],
    },
    "qa_281_2hop_441": {
        "class": "safety_base_offense_and_attempt", "sequence": 110, "ordinal": 168, "n_hops": 2,
        "run_id": "a4b7b846-da53-468c-a53b-5fbe3f491443", "receipt": "110_ord168_qa_281_2hop_441.json",
        "hashes": ("737fbf1135ee022a91528c72d450b487bb0bc49b6128ad525efec51fbc4d3a95", "d1216d6bf13bea5f676f6c639281fb80f240477c0fd0883d541518a06d01b6ad", "32a51772a530abce51eda6059380427b7a144702ac76523cf4c276a83c94d97e"),
        "assertions": [{"kind": "at_least", "counts": {"answer_targets": 1, "critical_evidence_items": 2, "critical_requirements": 2, "queries": 2}}, {"kind": "all_targets_have_critical_evidence"}],
    },
    "qa_134_2hop_515_rand": {
        "class": "safety_duration_and_post_expiry", "sequence": 54, "ordinal": 112, "n_hops": 2,
        "run_id": "03348db8-8bc1-4abb-ba57-4357e2f77c69", "receipt": "054_ord112_qa_134_2hop_515_rand.json",
        "hashes": ("edd0f7d550b029894d94297d07628ba67bee6738fdf5a5967ffce6213351837f", "fb3dd53b852c087d151b5a82e31c8032601d13f33313d750021833e3d297391a", "eefb269ac343148bede67da9a1ab7d0e746080b51e64e65f4cbf1aa6c05f3371"),
        "assertions": [{"kind": "at_least", "counts": {"answer_targets": 2, "critical_evidence_items": 2, "queries": 2}}, {"kind": "all_targets_have_critical_evidence"}],
    },
    "qa_366_3hop_580": {
        "class": "safety_three_explicit_acts", "sequence": 57, "ordinal": 115, "n_hops": 3,
        "run_id": "f00ff8f1-6a97-4c94-b771-6e3758352eae", "receipt": "057_ord115_qa_366_3hop_580.json",
        "hashes": ("2c655ac93512e22ec16aaf1c76cb9e00dc0aff15c4184cb640b7ce93e559658b", "284349df5aff7aa83e7b4e5b9e8436dbe2078a35c5dc42b02aeb52e851e6e60d", "9b0783646138e2daa6021037eebab7098e9662bc0bc949e3c70bc4cf0d889e3b"),
        "assertions": [{"kind": "at_least", "counts": {"answer_targets": 3, "critical_evidence_items": 3, "queries": 3}}, {"kind": "all_targets_have_critical_evidence"}],
    },
}


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReplayError("%s must be an object" % label)
    return value


def _list(value: Any, label: str) -> List[Any]:
    if not isinstance(value, list):
        raise ReplayError("%s must be a list" % label)
    return value


def _string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReplayError("%s must be a non-empty string" % label)
    return value


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ReplayError("%s must be an integer >= %d" % (label, minimum))
    return value


def _read_json(path: Path, label: str) -> Dict[str, Any]:
    try:
        return dict(_mapping(json.loads(path.read_text(encoding="utf-8")), label))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayError("cannot read %s: %s" % (label, exc)) from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expect_hash(value: str, label: str) -> str:
    if not SHA256_RE.fullmatch(value):
        raise ReplayError("%s must be a lowercase SHA256" % label)
    return value


def _expect_git(value: str, label: str) -> str:
    if not GIT_RE.fullmatch(value):
        raise ReplayError("%s must be a 40-character git object" % label)
    return value


def _profile(question_id: str) -> Mapping[str, Any]:
    try:
        return QUESTION_PROFILES[question_id]
    except KeyError as exc:
        raise ReplayError("question_id is outside the saved S1 minimality allowlist") from exc


def _coordinates(profile: Mapping[str, Any]) -> Dict[str, int]:
    return {field: _integer(profile.get(field), "allowlisted %s" % field, 1)
            for field in ("sequence", "ordinal", "n_hops")}


def _validate_coordinates(value: Mapping[str, Any], label: str, question_id: str) -> None:
    profile = _profile(question_id)
    if _string(value.get("question_id"), "%s.question_id" % label) != question_id:
        raise ReplayError("%s question_id does not match allowlist" % label)
    for field, expected in _coordinates(profile).items():
        if _integer(value.get(field), "%s.%s" % (label, field), 1) != expected:
            raise ReplayError("%s %s does not match allowlist" % (label, field))


def _expected_from_profile(question_id: str) -> ReplayExpectations:
    profile = _profile(question_id)
    result_sha, metadata_sha, receipt_sha = profile["hashes"]
    return ReplayExpectations(
        question_id=question_id, source_result_sha256=result_sha,
        source_metadata_sha256=metadata_sha, source_manifest_sha256=C02_BATCH_MANIFEST_SHA256,
        source_task_receipt_sha256=receipt_sha,
    )


def default_artifact_paths(question_id: str, source_root: Path = C02_RECORD_ROOT) -> Tuple[Path, Path, Path, Path]:
    profile = _profile(question_id)
    run_root = source_root / "records" / "runs" / _string(profile.get("run_id"), "profile run_id")
    batch_root = source_root / C02_BATCH_RELATIVE
    return (
        run_root / "result.json", run_root / "metadata.json", batch_root / "manifest.json",
        batch_root / "task_receipts" / _string(profile.get("receipt"), "profile receipt"),
    )


def _validate_manifest(manifest: Mapping[str, Any], expected: ReplayExpectations) -> None:
    if manifest.get("schema_version") != "c02_targeted_resume_batch_manifest_v1":
        raise ReplayError("source manifest has an unexpected schema_version")
    parent = Path(_string(manifest.get("parent_manifest"), "source manifest.parent_manifest"))
    if parent.name != "v2_kure_full226.json":
        raise ReplayError("source manifest parent lineage is unexpected")
    entries = [_mapping(item, "source manifest entry") for item in _list(manifest.get("entries"), "source manifest.entries")]
    matches = [entry for entry in entries if entry.get("question_id") == expected.question_id]
    if len(matches) != 1:
        raise ReplayError("source manifest must contain exactly one allowlisted question entry")
    _validate_coordinates(matches[0], "source manifest entry", expected.question_id)


def _validate_task_receipt(receipt: Mapping[str, Any], result_path: Path,
                           result: Mapping[str, Any], expected: ReplayExpectations) -> None:
    if receipt.get("schema_version") != "c02_targeted_resume_task_receipt_v1":
        raise ReplayError("source task receipt has an unexpected schema_version")
    _validate_coordinates(_mapping(receipt.get("task"), "source task receipt.task"), "source task receipt.task", expected.question_id)
    summary = _mapping(receipt.get("summary_row"), "source task receipt.summary_row")
    _validate_coordinates(summary, "source task receipt.summary_row", expected.question_id)
    if Path(_string(summary.get("record_result_file"), "source task receipt result path")).resolve() != result_path.resolve():
        raise ReplayError("source task receipt does not bind the supplied result path")
    if _string(summary.get("run_id"), "source task receipt run_id") != _string(result.get("run_id"), "saved result.run_id"):
        raise ReplayError("source task receipt does not bind the supplied result run_id")


def _baseline_plan(result: Mapping[str, Any]) -> Dict[str, Any]:
    state = _mapping(result.get("state"), "saved result.state")
    history = [_mapping(item, "state.query_history[]") for item in _list(state.get("query_history"), "state.query_history")]
    initial_requests = [item for item in history if INITIAL_REQUEST_RE.fullmatch(str(item.get("request_id", "")))]
    if not initial_requests:
        raise ReplayError("saved state has no initial S1 retrieval requests")
    return _project_plan({
        "answer_targets": _list(state.get("answer_targets"), "state.answer_targets"),
        "legal_issues": _list(state.get("legal_issues"), "state.legal_issues"),
        "required_evidence_items": _list(state.get("required_evidence_items"), "state.required_evidence_items"),
        "retrieval_requests": initial_requests,
    }, baseline=True)


def load_saved_source(result_path: Path, metadata_path: Path, manifest_path: Path,
                      task_receipt_path: Path, expected: ReplayExpectations) -> SavedSource:
    _profile(expected.question_id)
    paths = (result_path, metadata_path, manifest_path, task_receipt_path)
    if not all(path.is_file() for path in paths):
        raise ReplayError("source result, metadata, manifest, and task receipt must be regular files")
    actual_hashes = [_sha256_file(path) for path in paths]
    expected_hashes = [
        _expect_hash(expected.source_result_sha256, "expected source result SHA256"),
        _expect_hash(expected.source_metadata_sha256, "expected source metadata SHA256"),
        _expect_hash(expected.source_manifest_sha256, "expected source manifest SHA256"),
        _expect_hash(expected.source_task_receipt_sha256, "expected source task receipt SHA256"),
    ]
    labels = ("saved result", "saved metadata", "source manifest", "source task receipt")
    for actual, required, label in zip(actual_hashes, expected_hashes, labels):
        if actual != required:
            raise ReplayError("%s SHA256 mismatch" % label)
    result, metadata, manifest, receipt = [_read_json(path, label) for path, label in zip(paths, labels)]
    _validate_manifest(manifest, expected)
    _validate_task_receipt(receipt, result_path, result, expected)
    if _string(metadata.get("question_id"), "metadata.question_id") != expected.question_id:
        raise ReplayError("metadata.question_id does not match allowlist")
    _string(metadata.get("question"), "metadata.question")
    snapshot = _mapping(metadata.get("source_snapshot"), "metadata.source_snapshot")
    config = _mapping(metadata.get("configuration"), "metadata.configuration")
    if _string(snapshot.get("git_commit"), "source snapshot git_commit") != _expect_git(expected.source_commit, "expected source commit"):
        raise ReplayError("saved source commit mismatch")
    if _string(snapshot.get("git_tree"), "source snapshot git_tree") != _expect_git(expected.source_tree, "expected source tree"):
        raise ReplayError("saved source tree mismatch")
    lineage = _expect_hash(expected.source_manifest_lineage_sha256, "expected source manifest lineage SHA256")
    if _string(snapshot.get("source_manifest_sha256"), "source snapshot manifest lineage") != lineage or _string(config.get("source_manifest_sha256"), "configuration manifest lineage") != lineage:
        raise ReplayError("saved source manifest lineage mismatch")
    if _string(config.get("model"), "configuration.model") != _string(expected.source_model, "expected source model"):
        raise ReplayError("saved source model mismatch")
    if _string(config.get("retriever"), "configuration.retriever") != _string(expected.source_retriever, "expected source retriever"):
        raise ReplayError("saved source retriever mismatch")
    for field, value in (("num_ctx", 1024), ("seed", 0), ("s1_max_tokens", 1), ("s1_truncation_retry_max_tokens", 1)):
        _integer(config.get(field), "configuration.%s" % field, value)
    if _string(result.get("run_id"), "saved result.run_id") != _string(receipt.get("summary_row", {}).get("run_id"), "receipt summary run_id"):
        raise ReplayError("saved result run_id does not match task receipt")
    return SavedSource(
        *(path.resolve() for path in paths), *actual_hashes, result, metadata, manifest, receipt,
        _baseline_plan(result),
    )


def _issue_projection(item: Mapping[str, Any], baseline: bool) -> Dict[str, Any]:
    return {
        "issue_id": item.get("issue_id"),
        "description": item.get("description") if baseline else item.get("description", item.get("issue_statement")),
        "importance": item.get("importance"),
    }


def _project_plan(raw: Mapping[str, Any], baseline: bool = False) -> Dict[str, Any]:
    targets = [_mapping(item, "answer target") for item in _list(raw.get("answer_targets", []), "answer_targets")]
    issues = [_mapping(item, "legal issue") for item in _list(raw.get("legal_issues"), "legal_issues")]
    evidence = [_mapping(item, "evidence item") for item in _list(raw.get("required_evidence_items"), "required_evidence_items")]
    requests = [_mapping(item, "retrieval request") for item in _list(raw.get("retrieval_requests"), "retrieval_requests")]
    return {
        "answer_targets": [dict(item) for item in targets],
        "legal_issues": [_issue_projection(item, baseline) for item in issues],
        "required_evidence_items": [{
            "evidence_item_id": item.get("evidence_item_id"), "issue_id": item.get("issue_id"),
            "evidence_type": item.get("evidence_type"), "description": item.get("description"),
            "critical": item.get("critical"), "answer_target_ids": item.get("answer_target_ids", []),
            "scope_source": item.get("scope_source"),
            "completion_requirements": item.get("completion_requirements", []),
        } for item in evidence],
        "retrieval_requests": [{
            "request_id": item.get("request_id"), "issue_id": item.get("issue_id"),
            "evidence_item_id": item.get("evidence_item_id"), "query_channel": item.get("query_channel"),
            "query_text": item.get("query_text"), "query_terms": item.get("query_terms", []),
            "statute_hints": item.get("statute_hints", []),
            "first_stage_query_text": item.get("first_stage_query_text"), "rerank_query_text": item.get("rerank_query_text"),
        } for item in requests],
    }


def _counts(plan: Mapping[str, Any]) -> Dict[str, int]:
    evidence = _list(plan.get("required_evidence_items"), "plan.required_evidence_items")
    critical = [item for item in evidence if _mapping(item, "plan evidence item").get("critical") is True]
    return {
        "answer_targets": len(_list(plan.get("answer_targets"), "plan.answer_targets")),
        "issues": len(_list(plan.get("legal_issues"), "plan.legal_issues")),
        "evidence_items": len(evidence),
        "critical_evidence_items": len(critical),
        "requirements": sum(len(_list(_mapping(item, "plan evidence item").get("completion_requirements", []), "completion_requirements")) for item in evidence),
        "critical_requirements": sum(len(_list(_mapping(item, "critical evidence item").get("completion_requirements", []), "completion_requirements")) for item in critical),
        "queries": len(_list(plan.get("retrieval_requests"), "plan.retrieval_requests")),
    }


def _full_diff(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> List[str]:
    before = json.dumps(baseline, ensure_ascii=False, sort_keys=True, indent=2).splitlines()
    after = json.dumps(candidate, ensure_ascii=False, sort_keys=True, indent=2).splitlines()
    return list(difflib.unified_diff(before, after, fromfile="saved_baseline_plan", tofile="candidate_s1_initial_plan", lineterm=""))


def _assert_profile(profile: Mapping[str, Any], candidate: Mapping[str, Any]) -> List[Dict[str, Any]]:
    counts = _counts(candidate)
    outcomes: List[Dict[str, Any]] = []
    for assertion in profile.get("assertions", []):
        item = _mapping(assertion, "profile assertion")
        kind = _string(item.get("kind"), "profile assertion kind")
        passed = True
        detail: Dict[str, Any] = {"kind": kind}
        if kind in {"at_least", "at_most"}:
            requested = _mapping(item.get("counts"), "profile assertion counts")
            checked = {}
            for field, bound in requested.items():
                bound = _integer(bound, "profile assertion bound", 0)
                if field not in counts:
                    raise ReplayError("unknown structural assertion count: %s" % field)
                actual = counts[field]
                checked[field] = {"actual": actual, "bound": bound}
                passed = passed and (actual >= bound if kind == "at_least" else actual <= bound)
            detail["counts"] = checked
        elif kind == "all_targets_have_critical_evidence":
            targets = {item.get("answer_target_id") for item in _list(candidate.get("answer_targets"), "candidate targets")}
            covered = {target_id for evidence in _list(candidate.get("required_evidence_items"), "candidate evidence") if _mapping(evidence, "candidate evidence item").get("critical") is True for target_id in _mapping(evidence, "candidate evidence item").get("answer_target_ids", [])}
            missing = sorted(target for target in targets if target not in covered)
            passed = not missing
            detail["missing_target_ids"] = missing
        else:
            raise ReplayError("unknown profile assertion kind: %s" % kind)
        outcomes.append({**detail, "passed": passed})
    return outcomes


def _git_value(project_root: Path, expression: str) -> str:
    try:
        value = subprocess.run(["git", "rev-parse", expression], cwd=str(project_root), check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReplayError("cannot resolve candidate git %s" % expression) from exc
    return _expect_git(value, "candidate git %s" % expression)


def _assert_candidate_base(project_root: Path) -> Tuple[str, str]:
    try:
        subprocess.run(["git", "merge-base", "--is-ancestor", C13_BASE_COMMIT, "HEAD"], cwd=str(project_root), check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReplayError("candidate source must descend from the C13 integration commit") from exc
    return _git_value(project_root, "HEAD"), _git_value(project_root, "HEAD^{tree}")


class S1OnlyExecutor:
    """Narrow executor port: any non-S1 initial-plan call is a hard failure."""

    def __init__(self, delegate: Any):
        self.delegate = delegate

    def execute(self, skill_name: str, entry_point: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if (skill_name, entry_point) != (S1_SKILL, S1_ENTRY_POINT):
            raise ReplayError("saved S1 replay blocks stage %s/%s" % (skill_name, entry_point))
        if set(payload) - {"run_id", "question", "normalized_question", "query_history"}:
            raise ReplayError("S1 replay payload contains untrusted restored state")
        return self.delegate.execute(skill_name, entry_point, payload)


class ReplayArtifact:
    def __init__(self, directory: Path):
        self.directory = directory
        self.attempt_count = 0
        directory.mkdir(parents=True, exist_ok=False)

    def write_json(self, name: str, value: Mapping[str, Any]) -> None:
        (self.directory / name).write_text(json.dumps(dict(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    def record_skill_attempt(self, diagnostic: Mapping[str, Any]) -> None:
        item = dict(diagnostic)
        if item.get("schema_version") != GENERATION_DIAGNOSTIC_SCHEMA_VERSION:
            raise ReplayError("diagnostic must use C10 raw response schema 1.2")
        if item.get("skill_name") != S1_SKILL or item.get("entry_point") != S1_ENTRY_POINT:
            raise ReplayError("S1 replay diagnostic records an out-of-scope stage")
        upstream_kind = item.get("generation_kind")
        item["generation_kind"] = "s1_initial_plan_minimality_probe"
        item["upstream_generation_kind"] = upstream_kind
        response = item.get("response_text")
        if response is not None:
            if not isinstance(response, str):
                raise ReplayError("diagnostic response_text must be a string")
            encoded = response.encode("utf-8")
            if item.get("response_sha256") != hashlib.sha256(encoded).hexdigest() or item.get("response_utf8_bytes") != len(encoded) or item.get("response_characters") != len(response) or item.get("response_tail") != response[-512:]:
                raise ReplayError("diagnostic raw response retention fields do not bind response_text")
        item = {"recorded_at_utc": datetime.now(timezone.utc).isoformat(), **item}
        with (self.directory / "skill_attempts.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
        self.attempt_count += 1


def _output_directory(root: Path, source: SavedSource, candidate_commit: str) -> Path:
    resolved = root.resolve()
    if str(resolved) == "/workspace" or str(resolved).startswith("/workspace/"):
        raise ReplayError("S1 replay output_root must not be under /workspace")
    for source_path in (source.result_path, source.metadata_path, source.manifest_path, source.task_receipt_path):
        try:
            source_path.relative_to(resolved)
        except ValueError:
            continue
        raise ReplayError("S1 replay output_root must not contain immutable source inputs")
    return resolved / ("%s--%s--%s" % (source.metadata["question_id"], source.result_sha256[:16], candidate_commit[:12]))


def _resume(directory: Path, source: SavedSource, candidate_commit: str, candidate_tree: str) -> ReplayResult:
    payload = _read_json(directory / "replay.json", "saved replay receipt")
    if payload.get("schema_version") != REPLAY_SCHEMA_VERSION or payload.get("replay_status") != "S1_INITIAL_PLAN_COMPLETED":
        raise ReplayError("existing replay receipt is not resumable")
    source_binding = _mapping(payload.get("source_binding"), "saved replay source binding")
    if source_binding.get("result_sha256") != source.result_sha256 or source_binding.get("metadata_sha256") != source.metadata_sha256 or source_binding.get("manifest_sha256") != source.manifest_sha256 or source_binding.get("task_receipt_sha256") != source.task_receipt_sha256:
        raise ReplayError("existing replay receipt source binding mismatch")
    candidate_binding = _mapping(payload.get("candidate_snapshot"), "saved replay candidate snapshot")
    if candidate_binding.get("git_commit") != candidate_commit or candidate_binding.get("git_tree") != candidate_tree:
        raise ReplayError("existing replay receipt candidate snapshot mismatch")
    return ReplayResult(directory, payload, resumed=True)


def replay_saved_s1_initial_plan(*, source_result: Path, source_metadata: Path,
                                 source_manifest: Path, source_task_receipt: Path,
                                 output_root: Path, question_id: str,
                                 executor_factory: Optional[Callable[..., Any]] = None,
                                 project_root: Path = PROJECT_ROOT,
                                 expectations: Optional[ReplayExpectations] = None,
                                 resume: bool = False,
                                 expected_candidate_commit: Optional[str] = None,
                                 expected_candidate_tree: Optional[str] = None) -> ReplayResult:
    expected = expectations or _expected_from_profile(question_id)
    if expected.question_id != question_id:
        raise ReplayError("expectations question_id does not match requested allowlisted question")
    source = load_saved_source(source_result, source_metadata, source_manifest, source_task_receipt, expected)
    candidate_commit, candidate_tree = _assert_candidate_base(project_root)
    if expected_candidate_commit is not None and candidate_commit != _expect_git(expected_candidate_commit, "expected candidate commit"):
        raise ReplayError("candidate commit does not match expected binding")
    if expected_candidate_tree is not None and candidate_tree != _expect_git(expected_candidate_tree, "expected candidate tree"):
        raise ReplayError("candidate tree does not match expected binding")
    output_directory = _output_directory(output_root, source, candidate_commit)
    if output_directory.exists():
        if not resume:
            raise ReplayError("refusing to overwrite existing S1 replay output")
        return _resume(output_directory, source, candidate_commit, candidate_tree)
    artifact = ReplayArtifact(output_directory)
    config = _mapping(source.metadata.get("configuration"), "saved configuration")
    run_id = "s1-minimality-%s-%s-%s" % (question_id, source.result_sha256[:16], candidate_commit[:12])
    payload = {
        "run_id": run_id, "question": _string(source.metadata.get("question"), "metadata.question"),
        "normalized_question": normalize_question(_string(source.metadata.get("question"), "metadata.question")), "query_history": [],
    }
    factory = executor_factory or LocalOllamaSkillExecutor
    delegate = factory(
        skills_root=project_root / "skills", model=_string(config.get("model"), "configuration.model"),
        endpoint=_string(config.get("ollama_endpoint"), "configuration.ollama_endpoint"),
        num_ctx=_integer(config.get("num_ctx"), "configuration.num_ctx", 1024),
        max_attempts=2, seed=_integer(config.get("seed"), "configuration.seed", 0),
        s1_max_tokens=_integer(config.get("s1_max_tokens"), "configuration.s1_max_tokens", 1),
        s1_truncation_retry_max_tokens=_integer(config.get("s1_truncation_retry_max_tokens"), "configuration.s1_truncation_retry_max_tokens", 2),
        diagnostic_sink=artifact.record_skill_attempt,
    )
    candidate_raw = S1OnlyExecutor(delegate).execute(S1_SKILL, S1_ENTRY_POINT, payload)
    if not isinstance(candidate_raw, Mapping):
        raise ReplayError("candidate S1 INITIAL_PLAN must return an object")
    forbidden_fields = sorted({"accepted_provision_ids", "policy_action", "action", "coverage_assessments"}.intersection(candidate_raw))
    if forbidden_fields:
        raise ReplayError("candidate S1 output contains harness/S2 fields: %s" % forbidden_fields)
    try:
        validate_initial_plan(candidate_raw, question=payload["question"], include_answer_targets=True)
    except (ValidationError, ValueError) as exc:
        raise ReplayError("candidate S1 INITIAL_PLAN failed deterministic validation: %s" % exc) from exc
    candidate_plan = _project_plan(candidate_raw)
    baseline_counts, candidate_counts = _counts(source.baseline_plan), _counts(candidate_plan)
    assertions = _assert_profile(_profile(question_id), candidate_plan)
    comparison = {
        "baseline_counts": baseline_counts, "candidate_counts": candidate_counts,
        "count_delta": {key: candidate_counts[key] - baseline_counts[key] for key in baseline_counts},
        "full_unified_diff": _full_diff(source.baseline_plan, candidate_plan),
        "assertions": assertions,
    }
    receipt = {
        "schema_version": REPLAY_SCHEMA_VERSION, "replay_status": "S1_INITIAL_PLAN_COMPLETED",
        "question_id": question_id, "profile_class": _profile(question_id)["class"],
        "scope": {"executed": [{"skill": S1_SKILL, "entry_point": S1_ENTRY_POINT}], "hard_blocked": sorted(FORBIDDEN_STAGES)},
        "source_binding": {"result_sha256": source.result_sha256, "metadata_sha256": source.metadata_sha256, "manifest_sha256": source.manifest_sha256, "task_receipt_sha256": source.task_receipt_sha256, "manifest_lineage_sha256": expected.source_manifest_lineage_sha256},
        "candidate_snapshot": {"git_commit": candidate_commit, "git_tree": candidate_tree},
        "trusted_configuration": {key: config[key] for key in ("model", "retriever", "num_ctx", "seed", "s1_max_tokens", "s1_truncation_retry_max_tokens")},
        "baseline_plan": source.baseline_plan, "candidate_plan": candidate_plan, "comparison": comparison,
        "raw_response_diagnostics": {"schema_version": GENERATION_DIAGNOSTIC_SCHEMA_VERSION, "attempt_file": "skill_attempts.jsonl" if artifact.attempt_count else None, "attempt_count": artifact.attempt_count, "generation_kind": "s1_initial_plan_minimality_probe"},
    }
    artifact.write_json("baseline_plan.json", source.baseline_plan)
    artifact.write_json("candidate_plan.json", candidate_plan)
    artifact.write_json("comparison.json", comparison)
    artifact.write_json("replay.json", receipt)
    return ReplayResult(output_directory, receipt)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question_id", choices=sorted(QUESTION_PROFILES))
    parser.add_argument("--source-root", type=Path, default=C02_RECORD_ROOT)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--expected-candidate-commit")
    parser.add_argument("--expected-candidate-tree")
    args = parser.parse_args(argv)
    paths = default_artifact_paths(args.question_id, args.source_root)
    try:
        replay = replay_saved_s1_initial_plan(
            source_result=paths[0], source_metadata=paths[1], source_manifest=paths[2], source_task_receipt=paths[3],
            output_root=args.output_root, question_id=args.question_id, resume=args.resume,
            expected_candidate_commit=args.expected_candidate_commit, expected_candidate_tree=args.expected_candidate_tree,
        )
    except ReplayError as exc:
        print("S1 minimality replay refused: %s" % exc, file=sys.stderr)
        return 2
    print(json.dumps({"output_directory": str(replay.output_directory), "replay_status": replay.payload["replay_status"], "resumed": replay.resumed}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
