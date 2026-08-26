#!/usr/bin/env python3
"""Bounded offline replay of saved C02 candidates through C13 S2 -> S3 only.

This is not a harness launcher: it restores saved S1/retrieval state, invokes
only S2 and policy-authorized S3, and hard-fails if retrieval or S1 is reached.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness.contracts import (
    AnswerDraft, AnswerTarget, CandidateProvision, CitationIntegrityResult,
    CompletionRequirement, LegalIssue, OutcomeStatus, Phase,
    PolicyAction, QueryChannel, RequiredEvidenceItem, RetrievalRequest,
)
from harness.interfaces import CitationIntegrityValidator, ProvisionRetriever, SkillExecutor
from harness.policy import decide_next_action
from harness.run_state import RunState
from harness.runner import HarnessConfig, HarnessOutcome, HarnessRunner
from harness.state_update import record_policy_decision
from harness.tracing import to_primitive
from runtime.local_ollama_executor import LocalOllamaSkillExecutor


REPLAY_SCHEMA_VERSION = "offline_saved_s2s3_microreplay.v1"
GENERATION_DIAGNOSTIC_SCHEMA_VERSION = "1.2"
C13_BASE_COMMIT = "96664c59eb6066f5f4c0d6c695f2d86ae1b38004"

# Never substitute a similarly named item from a partially completed batch.
QUESTION_PROFILES = {
    "qa_180_2hop_689_rand": {
        "profile": "positive_material_card", "sequence": 5, "ordinal": 63, "n_hops": 2,
    },
    "qa_26_1hop_39": {
        "profile": "no_card_concise", "sequence": 11, "ordinal": 69, "n_hops": 1,
    },
    "qa_653_2hop_987": {
        "profile": "partial_no_rescue", "sequence": 18, "ordinal": 76, "n_hops": 2,
    },
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")


class ReplayError(RuntimeError):
    pass


@dataclass(frozen=True)
class ReplayExpectations:
    question_id: str
    source_result_sha256: str
    source_metadata_sha256: str
    source_manifest_sha256: str
    source_task_receipt_sha256: str
    source_commit: str
    source_tree: str
    source_model: str
    source_retriever: str


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
    state_sha256: str


@dataclass(frozen=True)
class ReplayResult:
    output_directory: Path
    payload: Dict[str, Any]
    resumed: bool = False


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


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


def _strings(value: Any, label: str) -> List[str]:
    return [_string(item, "%s[]" % label) for item in _list(value, label)]


def _integer(value: Any, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ReplayError("%s must be an integer >= %d" % (label, minimum))
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReplayError("%s must be a number" % label)
    return float(value)


def _optional_string(value: Any, label: str) -> Optional[str]:
    return None if value is None else _string(value, label)


def _optional_integer(value: Any, label: str) -> Optional[int]:
    return None if value is None else _integer(value, label)


def _read_json(path: Path, label: str) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayError("cannot read %s: %s" % (label, exc)) from exc
    return dict(_mapping(payload, label))


def _expected_hash(value: str, label: str) -> str:
    if not SHA256_RE.fullmatch(value):
        raise ReplayError("%s must be a lowercase SHA256" % label)
    return value


def _expected_git(value: str, label: str) -> str:
    if not GIT_RE.fullmatch(value):
        raise ReplayError("%s must be a lowercase 40-character git object" % label)
    return value


def _profile(question_id: str) -> str:
    return _string(_profile_spec(question_id).get("profile"), "allowlisted profile")


def _profile_spec(question_id: str) -> Mapping[str, Any]:
    try:
        return _mapping(QUESTION_PROFILES[question_id], "allowlisted question profile")
    except KeyError as exc:
        raise ReplayError("question_id is outside the saved-candidate allowlist") from exc


def _git_value(project_root: Path, expression: str) -> str:
    try:
        value = subprocess.run(
            ["git", "rev-parse", expression], cwd=str(project_root), check=True,
            capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReplayError("cannot resolve candidate git %s" % expression) from exc
    return _expected_git(value, "candidate git %s" % expression)


def _git_dirty_paths(project_root: Path) -> List[str]:
    try:
        output = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all"],
            cwd=str(project_root), check=True, capture_output=True, text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReplayError("cannot inspect candidate source status") from exc
    return [line for line in output.splitlines() if line]


def _assert_c13_base_ancestor(project_root: Path) -> None:
    try:
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", C13_BASE_COMMIT, "HEAD"],
            cwd=str(project_root), check=True, capture_output=True, text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReplayError("candidate source must descend from the C13 integration commit") from exc


def _within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _allowlisted_coordinates(question_id: str) -> Dict[str, int]:
    spec = _profile_spec(question_id)
    return {field: _integer(spec.get(field), "allowlisted %s" % field, 1)
            for field in ("sequence", "ordinal", "n_hops")}


def _validate_coordinates(value: Mapping[str, Any], label: str, expected: ReplayExpectations) -> None:
    coordinates = _allowlisted_coordinates(expected.question_id)
    if _string(value.get("question_id"), "%s.question_id" % label) != expected.question_id:
        raise ReplayError("%s question_id does not match the allowlisted input" % label)
    for field, expected_value in coordinates.items():
        if _integer(value.get(field), "%s.%s" % (label, field), 1) != expected_value:
            raise ReplayError("%s %s does not match the allowlisted input" % (label, field))


def _validate_manifest(manifest: Mapping[str, Any], expected: ReplayExpectations) -> None:
    entries = [_mapping(item, "source manifest entry") for item in _list(manifest.get("entries"), "source manifest.entries")]
    matching = [entry for entry in entries if entry.get("question_id") == expected.question_id]
    if len(matching) != 1:
        raise ReplayError("source manifest must contain exactly one allowlisted question entry")
    _validate_coordinates(matching[0], "source manifest entry", expected)


def _validate_task_receipt(receipt: Mapping[str, Any], result_path: Path,
                           result: Mapping[str, Any], expected: ReplayExpectations) -> None:
    if receipt.get("schema_version") != "c02_targeted_resume_task_receipt_v1":
        raise ReplayError("source task receipt has an unexpected schema_version")
    _validate_coordinates(_mapping(receipt.get("task"), "source task receipt.task"),
                          "source task receipt.task", expected)
    summary = _mapping(receipt.get("summary_row"), "source task receipt.summary_row")
    _validate_coordinates(summary, "source task receipt.summary_row", expected)
    recorded_result = Path(_string(summary.get("record_result_file"), "source task receipt result path")).resolve()
    if recorded_result != result_path.resolve():
        raise ReplayError("source task receipt does not bind the supplied result path")
    if _string(summary.get("run_id"), "source task receipt run_id") != _string(result.get("run_id"), "saved result.run_id"):
        raise ReplayError("source task receipt does not bind the supplied result run_id")
    saved_state = _mapping(result.get("state"), "saved result.state")
    if _strings(summary.get("accepted_provision_ids"), "source task receipt accepted provision IDs") != _strings(
            saved_state.get("accepted_provision_ids"), "saved accepted provision IDs"):
        raise ReplayError("source task receipt accepted provisions do not bind the supplied result")


def load_saved_source(result_path: Path, metadata_path: Path, manifest_path: Path,
                      task_receipt_path: Path, expected: ReplayExpectations) -> SavedSource:
    _profile(expected.question_id)
    if not all(path.is_file() for path in (result_path, metadata_path, manifest_path, task_receipt_path)):
        raise ReplayError("source result, metadata, manifest, and task receipt must be regular files")
    result_sha256 = _sha256_file(result_path)
    metadata_sha256 = _sha256_file(metadata_path)
    manifest_sha256 = _sha256_file(manifest_path)
    task_receipt_sha256 = _sha256_file(task_receipt_path)
    if result_sha256 != _expected_hash(expected.source_result_sha256, "expected source result SHA256"):
        raise ReplayError("saved result SHA256 mismatch")
    if metadata_sha256 != _expected_hash(expected.source_metadata_sha256, "expected source metadata SHA256"):
        raise ReplayError("saved metadata SHA256 mismatch")
    if manifest_sha256 != _expected_hash(expected.source_manifest_sha256, "expected source manifest SHA256"):
        raise ReplayError("source manifest SHA256 mismatch")
    if task_receipt_sha256 != _expected_hash(expected.source_task_receipt_sha256, "expected source task receipt SHA256"):
        raise ReplayError("source task receipt SHA256 mismatch")
    result = _read_json(result_path, "saved result")
    metadata = _read_json(metadata_path, "saved metadata")
    manifest = _read_json(manifest_path, "source manifest")
    task_receipt = _read_json(task_receipt_path, "source task receipt")
    _validate_manifest(manifest, expected)
    _validate_task_receipt(task_receipt, result_path, result, expected)
    if _string(metadata.get("question_id"), "metadata.question_id") != expected.question_id:
        raise ReplayError("metadata.question_id does not match the allowlisted input")
    _string(metadata.get("question"), "metadata.question")
    state = _mapping(result.get("state"), "saved result.state")
    snapshot = _mapping(metadata.get("source_snapshot"), "metadata.source_snapshot")
    configuration = _mapping(metadata.get("configuration"), "metadata.configuration")
    if _string(snapshot.get("git_commit"), "source snapshot commit") != _expected_git(expected.source_commit, "expected source commit"):
        raise ReplayError("saved source commit mismatch")
    if _string(snapshot.get("git_tree"), "source snapshot tree") != _expected_git(expected.source_tree, "expected source tree"):
        raise ReplayError("saved source tree mismatch")
    if _string(configuration.get("model"), "source model") != _string(expected.source_model, "expected source model"):
        raise ReplayError("saved source model mismatch")
    if _string(configuration.get("retriever"), "source retriever") != _string(expected.source_retriever, "expected source retriever"):
        raise ReplayError("saved source retriever mismatch")
    return SavedSource(
        result_path=result_path.resolve(), metadata_path=metadata_path.resolve(),
        manifest_path=manifest_path.resolve(), task_receipt_path=task_receipt_path.resolve(),
        result_sha256=result_sha256, metadata_sha256=metadata_sha256,
        manifest_sha256=manifest_sha256, task_receipt_sha256=task_receipt_sha256,
        result=result, metadata=metadata, manifest=manifest, task_receipt=task_receipt,
        state_sha256=_canonical_sha256(dict(state)),
    )

def _issues(raw: Any) -> List[LegalIssue]:
    values = [LegalIssue(_string(item.get("issue_id"), "issue ID"), _string(item.get("description"), "issue description"))
              for item in (_mapping(value, "legal issue") for value in _list(raw, "state.legal_issues"))]
    if not values or len({item.issue_id for item in values}) != len(values):
        raise ReplayError("saved legal issues must be non-empty and unique")
    return values


def _targets(raw: Any) -> List[AnswerTarget]:
    values = [AnswerTarget(
        _string(item.get("answer_target_id"), "target ID"),
        _string(item.get("question_anchor"), "target anchor"),
        _string(item.get("requested_output"), "target output"),
        _string(item.get("answer_type"), "target type"),
    ) for item in (_mapping(value, "answer target") for value in _list(raw, "state.answer_targets"))]
    if not values or len({item.answer_target_id for item in values}) != len(values):
        raise ReplayError("saved answer targets must be non-empty and unique")
    return values


def _evidence(raw: Any, issue_ids: Sequence[str], target_ids: Sequence[str]) -> List[RequiredEvidenceItem]:
    values: List[RequiredEvidenceItem] = []
    for value in _list(raw, "state.required_evidence_items"):
        item = _mapping(value, "evidence item")
        issue_id = _string(item.get("issue_id"), "evidence issue ID")
        target_links = _strings(item.get("answer_target_ids"), "evidence targets")
        if issue_id not in issue_ids or not target_links or set(target_links) - set(target_ids):
            raise ReplayError("saved evidence has unknown S1 scope")
        requirements = [CompletionRequirement(
            _string(requirement.get("requirement_id"), "requirement ID"),
            _string(requirement.get("text"), "requirement text"),
        ) for requirement in (_mapping(entry, "completion requirement") for entry in _list(item.get("completion_requirements"), "completion requirements"))]
        critical = item.get("critical")
        if not requirements or not isinstance(critical, bool):
            raise ReplayError("saved evidence is missing completion requirements or critical flag")
        values.append(RequiredEvidenceItem(
            _string(item.get("evidence_item_id"), "evidence ID"), issue_id,
            _string(item.get("evidence_type"), "evidence type"),
            _string(item.get("description"), "evidence description"), critical,
            completion_criteria=str(item.get("completion_criteria", "")),
            necessity_reason=str(item.get("necessity_reason", "")),
            answer_target_ids=target_links, scope_source=str(item.get("scope_source", "legacy")),
            completion_requirements=requirements,
        ))
    if not values or len({item.evidence_item_id for item in values}) != len(values):
        raise ReplayError("saved evidence must be non-empty and unique")
    return values


def _history(raw: Any, issue_ids: Sequence[str], evidence_ids: Sequence[str]) -> List[RetrievalRequest]:
    values: List[RetrievalRequest] = []
    for value in _list(raw, "state.query_history"):
        item = _mapping(value, "query history entry")
        issue_id = _string(item.get("issue_id"), "request issue ID")
        evidence_id = _string(item.get("evidence_item_id"), "request evidence ID")
        if issue_id not in issue_ids or evidence_id not in evidence_ids:
            raise ReplayError("saved query history has unknown S1 scope")
        try:
            channel = QueryChannel(_string(item.get("query_channel"), "request channel"))
        except ValueError as exc:
            raise ReplayError("saved query history has invalid channel") from exc
        values.append(RetrievalRequest(
            _string(item.get("request_id"), "request ID"), issue_id, evidence_id, channel,
            _string(item.get("query_text"), "request text"),
            _integer(item.get("top_k", 100), "request top_k", 1),
            _strings(item.get("query_terms", []), "query terms"),
            _strings(item.get("statute_hints", []), "statute hints"),
            _optional_string(item.get("first_stage_query_text"), "first-stage query"),
            _optional_string(item.get("rerank_query_text"), "rerank query"),
        ))
    if not values or len({item.request_id for item in values}) != len(values):
        raise ReplayError("saved query history must be non-empty and unique")
    return values


def _candidates(raw: Any, issue_ids: Sequence[str]) -> List[CandidateProvision]:
    values: List[CandidateProvision] = []
    for value in _list(raw, "state.candidate_provisions"):
        item = _mapping(value, "candidate provision")
        issue_id = _string(item.get("issue_id"), "candidate issue ID")
        if issue_id not in issue_ids:
            raise ReplayError("saved candidate has unknown issue")
        values.append(CandidateProvision(
            _string(item.get("provision_id"), "candidate ID"),
            _string(item.get("statute_name"), "candidate statute"),
            _string(item.get("provision_text"), "candidate text"), issue_id,
            _string(item.get("source_request_id"), "candidate source request"),
            _integer(item.get("retrieval_round"), "candidate retrieval round", 1),
            _number(item.get("first_stage_score"), "candidate first-stage score"),
            _integer(item.get("fusion_rank"), "candidate fusion rank", 1),
            _number(item.get("rerank_score"), "candidate rerank score"),
            source_request_ids=_strings(item.get("source_request_ids", []), "candidate source request IDs"),
            target_evidence_item_ids=_strings(item.get("target_evidence_item_ids", []), "candidate evidence IDs"),
            first_stage_rank=_optional_integer(item.get("first_stage_rank"), "first-stage rank"),
            rerank_rank=_optional_integer(item.get("rerank_rank"), "rerank rank"),
            selection_rank=_optional_integer(item.get("selection_rank"), "selection rank"),
            candidate_stage=str(item.get("candidate_stage", "bge_rerank")),
            selection_reason=str(item.get("selection_reason", "global_top_k")),
            alias_provision_ids=_strings(item.get("alias_provision_ids", []), "candidate aliases"),
        ))
    if not values or len({item.provision_id for item in values}) != len(values):
        raise ReplayError("saved candidates must be non-empty and unique")
    return values


def restore_saved_state(source: SavedSource, candidate_commit: str) -> RunState:
    """Restore S1/retrieval inputs; never restore final S2 coverage as prior state."""
    raw = _mapping(source.result.get("state"), "saved result.state")
    issues = _issues(raw.get("legal_issues"))
    targets = _targets(raw.get("answer_targets"))
    evidence = _evidence(raw.get("required_evidence_items"), [item.issue_id for item in issues], [item.answer_target_id for item in targets])
    history = _history(raw.get("query_history"), [item.issue_id for item in issues], [item.evidence_item_id for item in evidence])
    candidates = _candidates(raw.get("candidate_provisions"), [item.issue_id for item in issues])
    request_ids = {item.request_id for item in history}
    if any(item.source_request_id not in request_ids for item in candidates):
        raise ReplayError("candidate source request is absent from saved S1 history")
    snapshots = _mapping(raw.get("corpus_text_snapshots"), "saved corpus snapshots")
    if any(snapshots.get(item.provision_id) != item.provision_text for item in candidates):
        raise ReplayError("candidate text does not match saved corpus snapshot")
    state = RunState(
        question=_string(source.metadata.get("question"), "metadata.question"),
        normalized_question=_string(raw.get("normalized_question"), "saved normalized question"),
        run_id="offline-s2s3-%s-%s-%s" % (_string(source.metadata.get("question_id"), "metadata.question_id"), source.result_sha256[:16], candidate_commit[:12]),
        total_round_budget=_integer(raw.get("total_round_budget"), "total round budget", 1),
        remaining_round_budget=_integer(raw.get("remaining_round_budget"), "remaining round budget"),
        remaining_request_budget=_integer(raw.get("remaining_request_budget"), "remaining request budget"),
        phase=Phase.RETRIEVING_GAP, legal_issues=issues, answer_targets=targets,
        required_evidence_items=evidence, candidate_provisions=candidates,
        query_history=history,
        corpus_text_snapshots={item.provision_id: item.provision_text for item in candidates},
        seen_provision_ids={item.provision_id for item in candidates},
        retrieval_rounds_used=_integer(raw.get("retrieval_rounds_used"), "retrieval rounds used", 1),
        no_progress_rounds=_integer(raw.get("no_progress_rounds", 0), "no-progress rounds"),
        last_retrieval_new_provision_count=_integer(raw.get("last_retrieval_new_provision_count", 0), "last retrieval count"),
        last_validated_event="OFFLINE_REPLAY_S1_RETRIEVAL_RESTORED",
    )
    if state.retrieval_rounds_used > state.total_round_budget:
        raise ReplayError("saved retrieval rounds exceed total budget")
    state.record("OFFLINE_REPLAY_S1_RETRIEVAL_RESTORED",
                 source_result_sha256=source.result_sha256, source_state_sha256=source.state_sha256,
                 candidate_provision_count=len(candidates), source_query_request_count=len(history),
                 s1_reexecuted=False, retrieval_reexecuted=False)
    return state


class SavedCandidateCitationValidator(CitationIntegrityValidator):
    """Citation validation against only the saved candidate text snapshots."""

    def validate(self, state: RunState, answer: AnswerDraft) -> CitationIntegrityResult:
        errors: List[str] = []
        candidates = state.candidate_by_id()
        citations = {item.claim_id: item for item in answer.claim_citations}
        for claim in answer.claims:
            citation = citations.get(claim.claim_id)
            if citation is None or not citation.provision_ids:
                errors.append("MISSING_CITATION:%s" % claim.claim_id)
                continue
            for provision_id in citation.provision_ids:
                candidate = candidates.get(provision_id)
                if candidate is None:
                    errors.append("UNKNOWN_SAVED_CANDIDATE:%s" % provision_id)
                elif provision_id not in state.accepted_provision_ids:
                    errors.append("UNACCEPTED_SAVED_CANDIDATE:%s" % provision_id)
                elif state.corpus_text_snapshots.get(provision_id) != candidate.provision_text:
                    errors.append("SAVED_CANDIDATE_SNAPSHOT_MISMATCH:%s" % provision_id)
        return CitationIntegrityResult(passed=not errors, errors=errors)


class ForbiddenRetriever(ProvisionRetriever):
    def retrieve(self, *args: Any, **kwargs: Any) -> List[CandidateProvision]:
        raise ReplayError("offline saved-candidate replay must never call retrieval")


class ReplayArtifact:
    """Output with C10 full raw response retention and generation_kind binding."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.attempt_count = 0
        directory.mkdir(parents=True, exist_ok=False)

    def write_json(self, name: str, payload: Mapping[str, Any]) -> None:
        (self.directory / name).write_text(json.dumps(to_primitive(dict(payload)), ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    def record_skill_attempt(self, diagnostic: Mapping[str, Any]) -> None:
        payload = to_primitive(dict(diagnostic))
        if payload.get("schema_version") != GENERATION_DIAGNOSTIC_SCHEMA_VERSION:
            raise ReplayError("diagnostic must use raw response schema 1.2")
        if payload.get("generation_kind") not in {"primary_skill_attempt", "neutral_semantic_gap_replan"}:
            raise ReplayError("diagnostic must retain a permitted generation_kind")
        response = payload.get("response_text")
        if response is not None:
            if not isinstance(response, str):
                raise ReplayError("diagnostic response_text must be a string")
            encoded = response.encode("utf-8")
            if (payload.get("response_sha256") != hashlib.sha256(encoded).hexdigest()
                    or payload.get("response_utf8_bytes") != len(encoded)
                    or payload.get("response_characters") != len(response)
                    or payload.get("response_tail") != response[-512:]):
                raise ReplayError("diagnostic raw response retention fields do not bind response_text")
        self.attempt_count += 1
        payload = {"recorded_at_utc": datetime.now(timezone.utc).isoformat(), **payload}
        with (self.directory / "skill_attempts.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def descriptor(self) -> Dict[str, Any]:
        return {
            "schema_version": GENERATION_DIAGNOSTIC_SCHEMA_VERSION,
            "attempt_file": "skill_attempts.jsonl" if self.attempt_count else None,
            "attempt_count": self.attempt_count,
            "response_retention": {
                "generation_kind": {"field": "generation_kind", "required": True,
                                    "allowed_values": ["primary_skill_attempt", "neutral_semantic_gap_replan"]},
                "response_text": {"retention": "full", "encoding": "utf-8", "sha256_field": "response_sha256",
                                  "character_count_field": "response_characters", "utf8_byte_count_field": "response_utf8_bytes"},
                "response_tail": {"retention": "last_characters", "character_limit": 512},
            },
        }


def _output_directory(root: Path, source: SavedSource, candidate_commit: str) -> Path:
    resolved = root.resolve()
    if str(resolved) == "/workspace" or str(resolved).startswith("/workspace/"):
        raise ReplayError("offline replay output_root must not be under /workspace")
    if any(_within(path, resolved) for path in (source.result_path, source.metadata_path,
                                                   source.manifest_path, source.task_receipt_path)):
        raise ReplayError("offline replay output_root must not contain immutable source inputs")
    return resolved / ("%s--%s--%s" % (_string(source.metadata.get("question_id"), "metadata.question_id"), source.result_sha256[:16], candidate_commit[:12]))


def _receipt(source: SavedSource, expected: ReplayExpectations, commit: str, tree: str, dirty: Sequence[str]) -> Dict[str, Any]:
    config = _mapping(source.metadata.get("configuration"), "source configuration")
    snapshot = _mapping(source.metadata.get("source_snapshot"), "source snapshot")
    state = _mapping(source.result.get("state"), "saved result.state")
    return {
        "schema_version": REPLAY_SCHEMA_VERSION, "question_id": expected.question_id,
        "profile": _profile(expected.question_id),
        "source": {"result_path": str(source.result_path), "result_sha256": source.result_sha256,
                   "metadata_path": str(source.metadata_path), "metadata_sha256": source.metadata_sha256,
                   "manifest_path": str(source.manifest_path), "manifest_sha256": source.manifest_sha256,
                   "task_receipt_path": str(source.task_receipt_path), "task_receipt_sha256": source.task_receipt_sha256,
                   "task_coordinates": _allowlisted_coordinates(expected.question_id),
                   "state_sha256": source.state_sha256, "git_commit": snapshot["git_commit"],
                   "git_tree": snapshot["git_tree"], "model": config["model"], "retriever": config["retriever"],
                   "baseline_run_id": source.result.get("run_id"),
                   "baseline_accepted_provision_ids": state.get("accepted_provision_ids", [])},
        "candidate_source": {"c13_base_commit": C13_BASE_COMMIT, "git_commit": commit, "git_tree": tree,
                             "dirty_paths_at_start": list(dirty)},
        "execution_boundary": {"replayed_skills": ["S2", "S3"], "s1_reexecuted": False,
                               "retrieval_reexecuted": False, "evaluator_reexecuted": False,
                               "benchmark_candidate_generation": False},
    }


def _candidate_outcome(outcome: HarnessOutcome) -> Dict[str, Any]:
    return {"status": outcome.status.value,
            "termination_reason": outcome.termination_reason.value if outcome.termination_reason else None,
            "answer": outcome.answer, "answer_mode": outcome.answer_mode.value if outcome.answer_mode else None,
            "complete_answer": outcome.complete_answer, "answered_target_ids": list(outcome.answered_target_ids),
            "deferred_target_ids": list(outcome.deferred_target_ids), "claims": list(outcome.claims),
            "claim_citations": list(outcome.claim_citations), "assumptions": list(outcome.assumptions),
            "limitations": list(outcome.limitations), "candidate_answer": outcome.candidate_answer,
            "candidate_answer_status": outcome.candidate_answer_status.value if outcome.candidate_answer_status else None,
            "candidate_answer_basis": outcome.candidate_answer_basis.value if outcome.candidate_answer_basis else None,
            "errors": list(outcome.errors)}


def _baseline(result: Mapping[str, Any]) -> Dict[str, Any]:
    return {field: result.get(field, [] if field in {"claims", "claim_citations", "assumptions", "limitations", "errors", "answered_target_ids", "deferred_target_ids"} else None)
            for field in ("status", "termination_reason", "answer", "answer_mode", "answered_target_ids", "deferred_target_ids", "claims", "claim_citations", "assumptions", "limitations", "errors")}


def _material_cards(state: RunState) -> List[Dict[str, Any]]:
    return [to_primitive(card) for assessment in state.coverage_assessments
            for criterion in assessment.criterion_results for card in criterion.public_material_conditions]


def _assert_profile(profile: str, state: RunState, outcome: Optional[HarnessOutcome], s3_ran: bool) -> None:
    cards = _material_cards(state)
    if profile == "positive_material_card":
        if outcome is None or outcome.status is not OutcomeStatus.ANSWER or not s3_ran or not cards:
            raise ReplayError("positive material-card replay requires C11 card plus S3 answer")
        named = {card_id for claim in outcome.claims for card_id in claim.get("public_material_condition_ids", []) if isinstance(card_id, str)}
        if {card["material_id"] for card in cards} - named:
            raise ReplayError("S3 omitted a C11 material-card ID")
    elif profile == "no_card_concise":
        if outcome is None or outcome.status is not OutcomeStatus.ANSWER or not s3_ran or cards:
            raise ReplayError("no-card concise replay requires S3 answer without material card")
        if not isinstance(outcome.answer, str) or len(outcome.answer) > 800:
            raise ReplayError("no-card concise answer must stay under 800 characters")
        count = sum(claim.get("public_role", "conclusion") == "conclusion" for claim in outcome.claims)
        if count < 1 or count > 3:
            raise ReplayError("no-card concise answer must have one to three public conclusions")
    elif cards or outcome is not None or s3_ran:
        raise ReplayError("partial/no-rescue replay must not emit cards or invoke S3")


ExecutorFactory = Callable[..., SkillExecutor]


def replay_saved_s2s3(*, source_result: Path, source_metadata: Path, source_manifest: Path,
                       source_task_receipt: Path, output_root: Path,
                       expectations: ReplayExpectations, model: str, endpoint: str,
                       skills_root: Path = PROJECT_ROOT / "skills", num_ctx: Optional[int] = None,
                       max_attempts: int = 2, resume: bool = False,
                       expected_candidate_commit: Optional[str] = None, expected_candidate_tree: Optional[str] = None,
                       executor_factory: ExecutorFactory = LocalOllamaSkillExecutor,
                       project_root: Path = PROJECT_ROOT) -> ReplayResult:
    """Perform one hash-bound S2→S3 replay, or receipt-identical resume only."""
    profile = _profile(expectations.question_id)
    source = load_saved_source(source_result, source_metadata, source_manifest, source_task_receipt, expectations)
    if model != expectations.source_model:
        raise ReplayError("replay model must exactly match the source model")
    _assert_c13_base_ancestor(project_root)
    commit, tree = _git_value(project_root, "HEAD"), _git_value(project_root, "HEAD^{tree}")
    if expected_candidate_commit and commit != _expected_git(expected_candidate_commit, "expected candidate commit"):
        raise ReplayError("candidate commit mismatch")
    if expected_candidate_tree and tree != _expected_git(expected_candidate_tree, "expected candidate tree"):
        raise ReplayError("candidate tree mismatch")
    receipt = _receipt(source, expectations, commit, tree, _git_dirty_paths(project_root))
    destination = _output_directory(output_root, source, commit)
    if destination.exists():
        if not resume:
            raise ReplayError("deterministic output exists; pass --resume only for its identical receipt")
        prior = _read_json(destination / "receipt.json", "existing replay receipt")
        for key in ("schema_version", "question_id", "profile", "source", "candidate_source"):
            if prior.get(key) != receipt.get(key):
                raise ReplayError("--resume receipt mismatch; refusing overwrite")
        return ReplayResult(destination, _read_json(destination / "result.json", "existing replay result"), True)
    if resume:
        raise ReplayError("--resume requires an existing deterministic output")
    if max_attempts < 1:
        raise ReplayError("max_attempts must be positive")
    artifact = ReplayArtifact(destination)
    artifact.write_json("receipt.json", receipt)
    state = restore_saved_state(source, commit)
    config = _mapping(source.metadata.get("configuration"), "source configuration")
    effective_num_ctx = num_ctx or _integer(config.get("num_ctx"), "source num_ctx", 1024)
    executor = executor_factory(skills_root=skills_root, model=model, endpoint=endpoint,
                                num_ctx=effective_num_ctx, max_attempts=max_attempts,
                                seed=_integer(config.get("seed", 0), "source seed"),
                                diagnostic_sink=artifact.record_skill_attempt)
    runner = HarnessRunner(executor, ForbiddenRetriever(), SavedCandidateCitationValidator(),
                           HarnessConfig(state.total_round_budget, max(1, state.remaining_request_budget + len(state.query_history))))
    s2_failure = runner._assess_coverage(state)
    outcome: Optional[HarnessOutcome] = None
    s3_ran = False
    if s2_failure is not None:
        replay_status = "S2_EXECUTION_FAILURE"
        policy = {"action": None, "offline_retrieval_disabled": True}
        outcome = s2_failure
    else:
        decision = decide_next_action(state)
        policy = {"action": decision.action.value,
                  "termination_reason": decision.termination_reason.value if decision.termination_reason else None,
                  "explanation": decision.explanation,
                  "answer_mode": decision.answer_mode.value if decision.answer_mode else None,
                  "answered_target_ids": list(decision.answered_target_ids),
                  "deferred_target_ids": list(decision.deferred_target_ids),
                  "offline_retrieval_disabled": True}
        if decision.action is PolicyAction.GENERATE:
            runner._record_and_apply_generation_decision(state, decision)
            s3_ran = True
            outcome = runner._generate_and_validate(state)
            replay_status = "S2_S3_COMPLETED" if outcome.status is OutcomeStatus.ANSWER else "S3_EXECUTION_FAILURE"
        else:
            record_policy_decision(state, decision.action.value,
                                   termination_reason=policy["termination_reason"], explanation=decision.explanation,
                                   offline_retrieval_disabled=True, benchmark_candidate_generation=False)
            replay_status = "OFFLINE_POLICY_BLOCKED_NO_RETRIEVAL"
    _assert_profile(profile, state, outcome, s3_ran)
    candidate = _candidate_outcome(outcome) if outcome is not None else {
        "status": replay_status, "termination_reason": policy.get("termination_reason"), "answer": None,
        "answer_mode": None, "complete_answer": False, "answered_target_ids": [], "deferred_target_ids": [],
        "claims": [], "claim_citations": [], "assumptions": [], "limitations": [], "candidate_answer": None,
        "candidate_answer_status": None, "candidate_answer_basis": None, "errors": []}
    cards = _material_cards(state)
    named = [item for claim in candidate["claims"] for item in claim.get("public_material_condition_ids", []) if isinstance(item, str)]
    audit = {"profile": profile, "material_cards": cards, "material_card_count": len(cards),
             "claim_material_condition_ids": named, "s3_was_run": s3_ran, "replay_status": replay_status,
             "expected": {"positive_material_card": "at_least_one_card_and_S3_rendering",
                          "no_card_concise": "zero_cards_and_concise_S3",
                          "partial_no_rescue": "zero_cards_no_S3_no_retrieval_no_benchmark_candidate"}[profile]}
    baseline = _baseline(source.result)
    comparison = {"schema_version": REPLAY_SCHEMA_VERSION, "baseline": baseline, "candidate": candidate,
                  "answer_sha256": {"baseline": hashlib.sha256(baseline["answer"].encode("utf-8")).hexdigest() if isinstance(baseline["answer"], str) else None,
                                    "candidate": hashlib.sha256(candidate["answer"].encode("utf-8")).hexdigest() if isinstance(candidate["answer"], str) else None},
                  "answer_changed": baseline["answer"] != candidate["answer"] if isinstance(baseline["answer"], str) and isinstance(candidate["answer"], str) else None,
                  "score_or_gold_data_used": False}
    result = {"schema_version": REPLAY_SCHEMA_VERSION, "receipt_file": "receipt.json", "question_id": expectations.question_id,
              "profile": profile, "replay_status": replay_status, "policy": policy, "source": receipt["source"],
              "candidate": candidate, "candidate_state": to_primitive(state),
              "skill_generation_diagnostics": artifact.descriptor(), "material_card_audit": audit,
              "reconstruction_limitations": [
                  "S1 and retrieval were not re-executed; only saved final S1/retrieval fields were restored.",
                  "Saved final result.json lacks the pre-final-S2 coverage/evidence-link snapshot; prior S2 state is intentionally cleared.",
                  "No live corpus, retrieval scorer state, source checkout, evaluator, or benchmark candidate generation is reconstructed.",
                  "A non-GENERATE policy is recorded as blocked; no gap retrieval or candidate-answer rescue is substituted.",
              ]}
    artifact.write_json("comparison.json", comparison)
    artifact.write_json("result.json", result)
    receipt["output"] = {"result_file": "result.json", "comparison_file": "comparison.json",
                         "skill_attempt_file": "skill_attempts.jsonl" if artifact.attempt_count else None,
                         "skill_attempt_count": artifact.attempt_count}
    artifact.write_json("receipt.json", receipt)
    return ReplayResult(destination, result)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-result", type=Path, required=True)
    parser.add_argument("--source-metadata", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--source-task-receipt", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--question-id", choices=sorted(QUESTION_PROFILES), required=True)
    parser.add_argument("--expected-source-result-sha256", required=True)
    parser.add_argument("--expected-source-metadata-sha256", required=True)
    parser.add_argument("--expected-source-manifest-sha256", required=True)
    parser.add_argument("--expected-source-task-receipt-sha256", required=True)
    parser.add_argument("--expected-source-commit", required=True)
    parser.add_argument("--expected-source-tree", required=True)
    parser.add_argument("--expected-source-model", required=True)
    parser.add_argument("--expected-source-retriever", required=True)
    parser.add_argument("--model", required=True, help="must equal --expected-source-model")
    parser.add_argument("--ollama-endpoint", default="http://127.0.0.1:11434/api/generate")
    parser.add_argument("--skills-root", type=Path, default=PROJECT_ROOT / "skills")
    parser.add_argument("--num-ctx", type=int)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--expected-candidate-commit")
    parser.add_argument("--expected-candidate-tree")
    parser.add_argument("--resume", action="store_true", help="only read an existing receipt-identical replay")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        replay = replay_saved_s2s3(
            source_result=args.source_result, source_metadata=args.source_metadata,
            source_manifest=args.source_manifest, source_task_receipt=args.source_task_receipt, output_root=args.output_root,
            expectations=ReplayExpectations(args.question_id, args.expected_source_result_sha256,
                args.expected_source_metadata_sha256, args.expected_source_manifest_sha256,
                args.expected_source_task_receipt_sha256, args.expected_source_commit, args.expected_source_tree,
                args.expected_source_model, args.expected_source_retriever),
            model=args.model, endpoint=args.ollama_endpoint, skills_root=args.skills_root, num_ctx=args.num_ctx,
            max_attempts=args.max_attempts, resume=args.resume,
            expected_candidate_commit=args.expected_candidate_commit, expected_candidate_tree=args.expected_candidate_tree)
    except ReplayError as exc:
        print("offline replay refused: %s" % exc, file=sys.stderr)
        return 2
    print(json.dumps({"output_directory": str(replay.output_directory), "replay_status": replay.payload.get("replay_status"), "resumed": replay.resumed}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
