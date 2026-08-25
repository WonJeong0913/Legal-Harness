"""Execute the externally supplied S1/S2/S3 skill pack through local Ollama.

The deterministic harness deliberately uses compact internal contracts.  The
skill pack keeps richer, model-facing JSON contracts.  This adapter is the
only place where those representations meet: it prepares each skill input,
validates the model output with the skill's own validator, and maps the result
back to the harness contract.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import copy
import json
import re
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from harness.interfaces import SkillExecutionError


SKILL_IDS = {
    "legal_issue_and_query_planning": "S1",
    "provision_coverage_assessment": "S2",
    "grounded_legal_answer_generation": "S3",
}
EXTERNAL_CHANNELS = {
    "sparse_keyword": "sparse_keywords",
}
INTERNAL_CHANNELS = {
    "sparse_keywords": "sparse_keyword",
}
DEFAULT_SKILL_MAX_TOKENS = {
    "legal_issue_and_query_planning": 4096,
    "provision_coverage_assessment": 3072,
    "grounded_legal_answer_generation": 3072,
}
DEFAULT_S1_TRUNCATION_RETRY_MAX_TOKENS = 8192
RESPONSE_TAIL_CHARACTERS = 512
PUBLIC_ANSWER_MAX_CHARACTERS = 800
PUBLIC_ANSWER_MAX_CLAIMS = 3

PROMPT_RUN_ID_PLACEHOLDER = "__HARNESS_RUN_ID__"

S3_COMPACT_TRANSPORT_INVARIANT = (
    "For claim-bearing compact raw transport, omit answer, citation_id, "
    "quoted_text, and answer_marker; retain every claim plus claim_id, "
    "provision_id, answer_target_ids, and short support_description for each citation. Mark each claim public_role as conclusion or audit; conclusion claims are the only public text."
)
S2_COMPACT_AUDIT_INVARIANT = (
    "For raw S2 transport omit link_id, [FULL_TEXT], assessment-level linked "
    "IDs, satisfied_aspects, missing_aspects, and missing/conflict arrays when "
    "derivable; retain each legal status, criterion requirement_id/status, "
    "criterion linked candidate IDs, relation/conflict choice, and one concise rationale for each evidence link, coverage assessment, and criterion result."
)

@dataclass(frozen=True)
class GenerationResult:
    text: str
    done_reason: Optional[str] = None
    eval_count: Optional[int] = None


class ModelOutputTruncatedError(ValueError):
    """The model hit its deterministic output budget before completing JSON."""


class ModelOutputInvalidJsonError(ValueError):
    """The model stopped normally but returned syntactically invalid JSON."""


class LocalOllamaSkillExecutor:
    """Call local Qwen for skills while keeping all control in the harness."""

    def __init__(
        self,
        skills_root: Path,
        model: str,
        endpoint: str = "http://127.0.0.1:11434/api/generate",
        timeout_seconds: int = 600,
        num_ctx: int = 32768,
        max_attempts: int = 2,
        generator: Optional[Callable[[str], Any]] = None,
        diagnostic_sink: Optional[Callable[[Mapping[str, Any]], None]] = None,
        s1_max_tokens: int = DEFAULT_SKILL_MAX_TOKENS["legal_issue_and_query_planning"],
        s1_truncation_retry_max_tokens: int = DEFAULT_S1_TRUNCATION_RETRY_MAX_TOKENS,
        seed: int = 0,
    ):
        if timeout_seconds < 1 or num_ctx < 1024 or max_attempts < 1:
            raise ValueError("timeout, num_ctx, and max_attempts must be positive")
        if (
            isinstance(s1_max_tokens, bool)
            or isinstance(s1_truncation_retry_max_tokens, bool)
            or s1_max_tokens < 1
            or s1_truncation_retry_max_tokens <= s1_max_tokens
            or s1_truncation_retry_max_tokens > num_ctx
        ):
            raise ValueError(
                "S1 retry token limit must be larger than the initial limit and no larger than num_ctx"
            )
        self.skills_root = skills_root
        self.model = model
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.num_ctx = num_ctx
        self.max_attempts = max_attempts
        self.generator = generator
        self.diagnostic_sink = diagnostic_sink
        self.s1_max_tokens = s1_max_tokens
        self.s1_truncation_retry_max_tokens = s1_truncation_retry_max_tokens
        # Keep the historical default while forwarding the frozen run seed to
        # every Ollama request. Test generators retain their one-argument
        # interface so existing local unit tests and callers stay compatible.
        self.seed = seed
        self._resources: Dict[str, Dict[str, str]] = {}
        self._validators: Dict[str, Callable[[Mapping[str, Any], Mapping[str, Any]], List[str]]] = {}
        self._validator_modules: Dict[str, Any] = {}
        for skill_name in SKILL_IDS:
            self._load_skill(skill_name)

    def execute(
        self,
        skill_name: str,
        entry_point: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        if skill_name not in SKILL_IDS:
            raise SkillExecutionError("unknown local skill: %s" % skill_name)
        skill_input = self._build_skill_input(skill_name, entry_point, payload)
        errors: List[str] = []
        repair_note = ""
        max_tokens = self._max_tokens(skill_name)
        for attempt in range(1, self.max_attempts + 1):
            prompt = self._prompt(skill_name, entry_point, skill_input, repair_note)
            diagnostic: Dict[str, Any] = {
                "schema_version": "1.0",
                "run_id": skill_input.get("run_id"),
                "skill_name": skill_name,
                "skill_id": SKILL_IDS[skill_name],
                "entry_point": entry_point,
                "attempt": attempt,
                "requested_max_tokens": max_tokens,
            }
            try:
                generation = self._generate(prompt, max_tokens)
                diagnostic.update(self._generation_diagnostic(generation))
                if generation.done_reason == "length":
                    retry_tokens = self._retry_max_tokens(skill_name, max_tokens)
                    diagnostic["outcome"] = "truncated"
                    diagnostic["error_code"] = "MODEL_OUTPUT_TRUNCATED"
                    diagnostic["retry_max_tokens"] = retry_tokens
                    raise ModelOutputTruncatedError(
                        "MODEL_OUTPUT_TRUNCATED: %s %s attempt %d reached num_predict=%d"
                        % (skill_name, entry_point, attempt, max_tokens)
                    )
                raw_skill_output = self._parse_json_object(generation.text)
                skill_output = self._normalize_harness_owned_fields(
                    skill_name, entry_point, skill_input, copy.deepcopy(raw_skill_output)
                )
                unrepaired_skill_output = copy.deepcopy(skill_output)
                skill_output, deterministic_repairs = self._repair_s1_transport(
                    skill_name, entry_point, skill_output, skill_input
                )
                if deterministic_repairs:
                    diagnostic["deterministic_repairs"] = deterministic_repairs
                validation_errors = self._validators[skill_name](skill_output, skill_input)
                scope_mismatches = self._semantic_scope_mismatches(
                    skill_name, skill_output, skill_input
                )
                if scope_mismatches:
                    diagnostic["semantic_scope_mismatches"] = scope_mismatches
                if (
                    not validation_errors
                    and skill_output.get("status") == "ok"
                    and self._needs_neutral_s1_gap_replan(
                        skill_name,
                        entry_point,
                        unrepaired_skill_output,
                        skill_output,
                        skill_input,
                        deterministic_repairs,
                    )
                ):
                    replan_events = [
                        {
                            "kind": "neutral_semantic_gap_replan_attempted",
                            "reason": "material_scoring_query_repair",
                        }
                    ]
                    replan, replan_failure = self._neutral_s1_gap_replan(
                        entry_point, skill_input, skill_output, max_tokens
                    )
                    if replan is not None:
                        skill_output = replan
                        replan_events.append(
                            {"kind": "neutral_semantic_gap_replan_adopted"}
                        )
                    else:
                        replan_events.append(
                            {
                                "kind": "neutral_semantic_gap_replan_fallback",
                                "reason": replan_failure,
                            }
                        )
                    diagnostic["semantic_replan_events"] = replan_events
                if validation_errors:
                    errors = validation_errors
                    compact_transport = (
                        skill_name in {
                            "provision_coverage_assessment",
                            "grounded_legal_answer_generation",
                        }
                        and bool(
                            self._resources[skill_name].get(
                                "compact_output_schema"
                            )
                        )
                    )
                    repair_instruction = (
                        " Return a corrected replacement under the displayed raw compact "
                        "transport schema. Preserve valid semantic decisions and do not "
                        "add harness-owned fields."
                        if compact_transport
                        else (
                            " Return a corrected replacement JSON. Preserve valid fields and "
                            "rebuild linked_provision_ids from evidence_links."
                        )
                    )
                    repair_note = (
                        "Your previous JSON failed validation: "
                        + "; ".join(validation_errors)
                        + repair_instruction
                        + " Previous JSON: "
                        + json.dumps(
                            self._redact_run_ids_for_prompt(
                                raw_skill_output if (compact_transport or deterministic_repairs) else skill_output
                            ),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    )
                    diagnostic["outcome"] = "validation_error"
                    diagnostic["error"] = "; ".join(validation_errors)
                    continue
                if skill_output.get("status") == "error":
                    error = skill_output.get("error", {})
                    raise SkillExecutionError(
                        "%s returned %s: %s"
                        % (skill_name, error.get("code", "UNKNOWN"), error.get("message", ""))
                    )
                diagnostic["outcome"] = "valid"
                return self._adapt_output(skill_name, entry_point, skill_output, skill_input)
            except ModelOutputTruncatedError as exc:
                errors = [str(exc)]
                repair_note = (
                    "Your previous response was truncated at the output limit. "
                    "Return a complete, compact replacement JSON within the enlarged limit."
                )
                max_tokens = self._retry_max_tokens(skill_name, max_tokens)
            except ModelOutputInvalidJsonError as exc:
                errors = [str(exc)]
                diagnostic["outcome"] = "invalid_json"
                diagnostic["error_code"] = "MODEL_OUTPUT_INVALID_JSON"
                diagnostic["error"] = str(exc)
                repair_note = "Your previous response was unusable: " + str(exc)
            except SkillExecutionError as exc:
                errors = [str(exc)]
                diagnostic["outcome"] = "skill_error"
                diagnostic["error"] = str(exc)
                repair_note = "Your previous response was unusable: " + str(exc)
            finally:
                self._record_diagnostic(diagnostic)
        raise SkillExecutionError(
            "%s did not produce a valid %s result after %d attempts: %s"
            % (skill_name, entry_point, self.max_attempts, "; ".join(errors))
        )
    def _normalize_harness_owned_fields(
        self,
        skill_name: str,
        entry_point: str,
        skill_input: Mapping[str, Any],
        output: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Assign run and request IDs; their values carry no legal judgment."""
        normalized = dict(output)
        normalized["run_id"] = skill_input["run_id"]
        if skill_name == "provision_coverage_assessment":
            return self._normalize_s2_output(normalized, skill_input)
        if skill_name == "grounded_legal_answer_generation":
            return self._normalize_s3_transport(normalized, skill_input)
        if skill_name != "legal_issue_and_query_planning":
            return normalized
        request_key = "gap_retrieval_requests" if entry_point == "GAP_QUERY_PLAN" else "retrieval_requests"
        requests = normalized.get(request_key)
        if not isinstance(requests, list):
            return normalized
        prefix = "GRQ" if entry_point == "GAP_QUERY_PLAN" else "RQ"
        for index, request in enumerate(requests, start=1):
            if isinstance(request, dict):
                request["request_id"] = ("GRQ-R%d-%d" % (int(skill_input.get("next_retrieval_round", 1)), index) if entry_point == "GAP_QUERY_PLAN" else "RQ%d" % index)
                for key in ("query_terms", "statute_hints"):
                    values = request.get(key)
                    if isinstance(values, list):
                        unique_values = []
                        seen_values = set()
                        for value in values:
                            if not isinstance(value, str) or not value.strip():
                                continue
                            normalized_value = self._normalized_query(value)
                            if normalized_value in seen_values:
                                continue
                            seen_values.add(normalized_value)
                            unique_values.append(value.strip())
                        request[key] = unique_values
        if entry_point == "INITIAL_PLAN":
            issues_by_id = {
                issue.get("issue_id"): issue
                for issue in self._list(normalized, "legal_issues")
                if isinstance(issue, Mapping)
            }
            emitted_queries = set()
            for index, request in enumerate(requests, start=1):
                if not isinstance(request, dict):
                    continue
                query = request.get("query_text")
                contextual_query = self._with_source_context(query, skill_input)
                if not isinstance(query, str) or self._normalized_query(contextual_query) in emitted_queries:
                    issue = issues_by_id.get(request.get("issue_id"), {})
                    query = self._fallback_initial_query(issue, index, emitted_queries, skill_input)
                    contextual_query = self._with_source_context(query, skill_input)
                request["query_text"] = contextual_query
                emitted_queries.add(self._normalized_query(contextual_query))

        if entry_point == "GAP_QUERY_PLAN":
            unresolved = [item.get("evidence_item_id") for key in ("missing_evidence_items", "evidence_conflicts") for item in self._list(skill_input, key) if isinstance(item, Mapping)]
            evidence_by_id = {item.get("evidence_item_id"): item for item in self._list(skill_input, "required_evidence_items") if isinstance(item, Mapping)}
            prior_queries = {
                self._normalized_query(item.get("query_text") or item.get("normalized_query"))
                for item in self._list(skill_input, "query_history")
                if isinstance(item, Mapping) and isinstance(item.get("query_text") or item.get("normalized_query"), str)
            }
            emitted_queries = set(prior_queries)
            for index, request in enumerate(requests, start=1):
                if not isinstance(request, dict):
                    continue
                evidence_id = request.get("evidence_item_id")
                if evidence_id not in unresolved and len(unresolved) == 1:
                    evidence_id = unresolved[0]
                    request["evidence_item_id"] = evidence_id
                evidence = evidence_by_id.get(evidence_id)
                if not isinstance(evidence, Mapping):
                    continue
                request["issue_id"] = evidence.get("issue_id")
                query = request.get("query_text")
                contextual_query = self._with_source_context(query, skill_input)
                if not isinstance(query, str) or self._normalized_query(contextual_query) in emitted_queries:
                    query = self._fallback_gap_query(evidence, index, emitted_queries, skill_input)
                    contextual_query = self._with_source_context(query, skill_input)
                request["query_text"] = contextual_query
                emitted_queries.add(self._normalized_query(contextual_query))
            normalized["target_evidence_item_ids"] = list(dict.fromkeys(
                request.get("evidence_item_id") for request in requests if isinstance(request, dict)
            ))
        return normalized

    def _normalize_s3_transport(
        self,
        output: Dict[str, Any],
        skill_input: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Own S3 identifiers and rendering without changing model legal choices."""
        if output.get("status") != "ok":
            return output
        claims = output.get("claims")
        citations = output.get("claim_citations")
        question_only = (
            skill_input.get("mode") == "GENERATE_BENCHMARK_CANDIDATE"
            and skill_input.get("candidate_answer_basis") == "question_only"
        )
        if question_only and claims == [] and citations == []:
            answer = self._compact_question_only_answer(output.get("answer"))
            if answer is None:
                return output
            normalized = dict(output)
            normalized["answer"] = answer
            return normalized
        if not isinstance(claims, list) or not isinstance(citations, list):
            return output

        claim_id_map: Dict[str, str] = {}
        normalized_claims: List[Dict[str, Any]] = []
        answered_target_ids = self._list(
            skill_input, "answered_target_ids", required=False
        )
        for index, raw_claim in enumerate(claims, start=1):
            if not isinstance(raw_claim, Mapping):
                return output
            claim_id = raw_claim.get("claim_id")
            if (
                not isinstance(claim_id, str)
                or not claim_id.strip()
                or claim_id in claim_id_map
                or not isinstance(raw_claim.get("text"), str)
                or not raw_claim["text"].strip()
            ):
                return output
            claim_id_map[claim_id] = "C%d" % index
            claim = dict(raw_claim)
            claim["claim_id"] = claim_id_map[claim_id]
            claim_target_ids = claim.get("answer_target_ids")
            if len(answered_target_ids) == 1 and (
                not isinstance(claim_target_ids, list)
                or not claim_target_ids
                or set(claim_target_ids) - set(answered_target_ids)
            ):
                claim["answer_target_ids"] = list(answered_target_ids)
            normalized_claims.append(claim)

        provision_key = (
            "candidate_provisions"
            if skill_input.get("mode") == "GENERATE_BENCHMARK_CANDIDATE"
            else "accepted_provisions"
        )
        provisions = {
            provision.get("provision_id"): provision
            for provision in self._list(skill_input, provision_key)
            if isinstance(provision, Mapping)
            and isinstance(provision.get("provision_id"), str)
        }
        normalized_citations: List[Dict[str, Any]] = []
        markers_by_claim: Dict[str, List[str]] = {}
        for index, raw_citation in enumerate(citations, start=1):
            if not isinstance(raw_citation, Mapping):
                return output
            model_claim_id = raw_citation.get("claim_id")
            provision_id = raw_citation.get("provision_id")
            if not isinstance(model_claim_id, str) or not isinstance(provision_id, str):
                return output
            provision = provisions.get(provision_id)
            text = provision.get("text") if isinstance(provision, Mapping) else None
            if (
                model_claim_id not in claim_id_map
                or not isinstance(text, str)
                or not text
            ):
                return output
            citation = dict(raw_citation)
            citation_id = "CT%d" % index
            citation["citation_id"] = citation_id
            citation["claim_id"] = claim_id_map[model_claim_id]
            citation["quoted_text"] = text
            citation["answer_marker"] = "[%s]" % citation_id
            normalized_citations.append(citation)
            markers_by_claim.setdefault(citation["claim_id"], []).append(
                citation["answer_marker"]
            )

        for key in ("assumptions", "limitations"):
            raw_notes = output.get(key)
            if not isinstance(raw_notes, list):
                return output
            for note in raw_notes:
                if not isinstance(note, Mapping):
                    return output
                message = note.get("message")
                if not isinstance(message, str) or not message.strip():
                    return output
        self._ensure_public_roles(
            normalized_claims,
            answered_target_ids,
            allow_legacy_default=(
                skill_input.get("generation_constraints", {}).get("public_conclusion_contract")
                != "required"
            ),
        )
        answer_lines = [
            "%s%s" % (
                claim.get("text"),
                "".join(markers_by_claim.get(claim["claim_id"], [])),
            )
            for claim in self._public_s3_claims(normalized_claims, answered_target_ids)
        ]
        answer = "\n".join(answer_lines)
        max_answer_chars = skill_input.get("generation_constraints", {}).get(
            "max_answer_chars"
        )
        effective_max_chars = (
            min(max_answer_chars, PUBLIC_ANSWER_MAX_CHARACTERS)
            if isinstance(max_answer_chars, int)
            else PUBLIC_ANSWER_MAX_CHARACTERS
        )
        if not answer or len(answer) > effective_max_chars:
            return output
        normalized = dict(output)
        normalized["claims"] = normalized_claims
        normalized["claim_citations"] = normalized_citations
        normalized["answer"] = answer
        return normalized

    @staticmethod
    def _ensure_public_roles(
        claims: List[Dict[str, Any]],
        target_order: List[str],
        *,
        allow_legacy_default: bool,
    ) -> None:
        """Preserve explicit roles; migrate role-less output only for legacy inputs."""
        if not allow_legacy_default:
            return
        if any("public_role" in claim for claim in claims):
            for claim in claims:
                claim.setdefault("public_role", "audit")
            return
        for claim in claims:
            claim["public_role"] = "audit"
        selected: List[Dict[str, Any]] = []

        def select(claim: Dict[str, Any]) -> None:
            if claim not in selected and len(selected) < PUBLIC_ANSWER_MAX_CLAIMS:
                selected.append(claim)

        if claims:
            select(claims[0])
        for claim in claims:
            if claim.get("applicability") == "conditional":
                select(claim)
        for claim in claims:
            if claim.get("claim_type") == "legal_rule":
                select(claim)
        for claim in claims:
            select(claim)
        for claim in selected:
            claim["public_role"] = "conclusion"

    @staticmethod
    def _public_s3_claims(
        claims: List[Dict[str, Any]], target_order: List[str]
    ) -> List[Dict[str, Any]]:
        target_index = {target_id: index for index, target_id in enumerate(target_order)}
        public = [claim for claim in claims if claim.get("public_role") == "conclusion"]
        return sorted(
            public,
            key=lambda claim: min(
                (target_index[target_id] for target_id in claim.get("answer_target_ids", []) if target_id in target_index),
                default=len(target_index),
            ),
        )

    @staticmethod
    def _compact_question_only_answer(value: Any) -> Optional[str]:
        if not isinstance(value, str) or not value.strip():
            return None
        lines = []
        for raw_line in value.splitlines():
            line = " ".join(raw_line.split())
            if not line or line.startswith(("전제:", "한계:")):
                continue
            lines.append(line)
            if len(lines) == PUBLIC_ANSWER_MAX_CLAIMS:
                break
        answer = " ".join(lines)
        if not answer or len(answer) > PUBLIC_ANSWER_MAX_CHARACTERS:
            return None
        return answer

    def _normalize_s2_output(
        self,
        output: Dict[str, Any],
        skill_input: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """Canonicalize S2 transport structure without making legal judgments."""
        if output.get("status") != "ok":
            return output
        evidence = [
            item
            for item in self._list(skill_input, "required_evidence_items")
            if isinstance(item, Mapping)
        ]
        evidence_by_id = {item.get("evidence_item_id"): item for item in evidence}
        candidate_ids = {
            item.get("provision_id")
            for item in self._list(skill_input, "candidate_provisions")
            if isinstance(item, Mapping)
        }

        links = []
        seen_links = set()
        for raw in self._list(output, "evidence_links", required=False):
            if not isinstance(raw, Mapping):
                continue
            key = (
                raw.get("evidence_item_id"),
                raw.get("provision_id"),
                raw.get("relation"),
            )
            if key in seen_links:
                continue
            seen_links.add(key)
            link = dict(raw)
            link["link_id"] = "L%d" % (len(links) + 1)
            if key[0] in evidence_by_id and key[1] in candidate_ids:
                link["quoted_text"] = "[FULL_TEXT]"
            links.append(link)
        output["evidence_links"] = links

        links_by_evidence: Dict[str, List[str]] = {}
        for link in links:
            evidence_id = link.get("evidence_item_id")
            provision_id = link.get("provision_id")
            if isinstance(evidence_id, str) and isinstance(provision_id, str):
                links_by_evidence.setdefault(evidence_id, []).append(provision_id)

        first_assessment: Dict[str, Dict[str, Any]] = {}
        for raw in self._list(output, "coverage_assessments", required=False):
            if not isinstance(raw, Mapping):
                continue
            evidence_id = raw.get("evidence_item_id")
            if evidence_id in evidence_by_id and evidence_id not in first_assessment:
                assessment = dict(raw)
                status = assessment.get("status", assessment.get("evidence_status"))
                if isinstance(status, str) and "status" not in assessment:
                    assessment["status"] = status
                if not isinstance(status, str) and isinstance(
                    assessment.get("legal_status"), str
                ):
                    status = (
                        "partially_covered"
                        if assessment.get("legal_status") == "covered"
                        and assessment.get("applicability_status") == "conditional"
                        else assessment.get("legal_status")
                    )
                    assessment["status"] = status
                if status == "partially_covered":
                    if assessment.get("partial_kind") not in {
                        "factual_condition",
                        "legal_support_gap",
                    }:
                        assessment["partial_kind"] = "legal_support_gap"
                else:
                    assessment["partial_kind"] = "not_applicable"
                assessment["linked_provision_ids"] = list(
                    dict.fromkeys(links_by_evidence.get(evidence_id, []))
                )
                requirement_ids = [
                    requirement.get("requirement_id")
                    for requirement in evidence_by_id[evidence_id].get(
                        "completion_requirements", []
                    )
                    if isinstance(requirement, Mapping)
                    and isinstance(requirement.get("requirement_id"), str)
                ]
                criterion_results = assessment.get("criterion_results")
                if requirement_ids and isinstance(criterion_results, list):
                    results_by_id = {
                        result.get("requirement_id"): result
                        for result in criterion_results
                        if isinstance(result, Mapping)
                        and isinstance(result.get("requirement_id"), str)
                    }
                    if (
                        len(criterion_results) == len(requirement_ids)
                        and set(results_by_id) == set(requirement_ids)
                    ):
                        assessment["criterion_results"] = [
                            dict(results_by_id[requirement_id])
                            for requirement_id in requirement_ids
                        ]
                        assessment["satisfied_aspects"] = [
                            requirement_id
                            for requirement_id in requirement_ids
                            if results_by_id[requirement_id].get("status")
                            == "satisfied"
                        ]
                        assessment["missing_aspects"] = [
                            requirement_id
                            for requirement_id in requirement_ids
                            if results_by_id[requirement_id].get("status")
                            != "satisfied"
                        ]
                first_assessment[evidence_id] = assessment
        output["coverage_assessments"] = [
            first_assessment[evidence_id]
            for evidence_id in evidence_by_id
            if evidence_id in first_assessment
        ]

        prior_missing = {
            item.get("evidence_item_id"): item
            for item in self._list(output, "missing_evidence_items", required=False)
            if isinstance(item, Mapping)
        }
        missing = []
        for evidence_id, assessment in first_assessment.items():
            if assessment.get("status") == "covered":
                continue
            source = dict(prior_missing.get(evidence_id, {}))
            ledger = evidence_by_id[evidence_id]
            aspects = assessment.get("missing_aspects")
            if not isinstance(aspects, list) or not aspects:
                aspects = [
                    assessment.get("rationale") or ledger.get("completion_criteria")
                ]
            source.update(
                {
                    "evidence_item_id": evidence_id,
                    "issue_id": ledger.get("issue_id"),
                    "critical": ledger.get("critical"),
                    "missing_description": source.get("missing_description")
                    or "; ".join(str(item) for item in aspects),
                    "search_focus": source.get("search_focus")
                    or [str(item) for item in aspects if str(item).strip()],
                }
            )
            missing.append(source)
        output["missing_evidence_items"] = missing

        prior_conflicts = {
            item.get("evidence_item_id"): item
            for item in self._list(output, "evidence_conflicts", required=False)
            if isinstance(item, Mapping)
        }
        conflicts = []
        for evidence_id, assessment in first_assessment.items():
            if assessment.get("status") != "conflicting":
                continue
            source = dict(prior_conflicts.get(evidence_id, {}))
            source.update(
                {
                    "conflict_id": "CF%d" % (len(conflicts) + 1),
                    "evidence_item_id": evidence_id,
                    "provision_ids": list(
                        dict.fromkeys(links_by_evidence.get(evidence_id, []))
                    ),
                    "description": source.get("description")
                    or assessment.get("rationale")
                    or "후보 조문 간 적용 충돌",
                    "unresolved_question": source.get("unresolved_question")
                    or "어느 조문이 질문의 사실관계에 적용되는가",
                }
            )
            conflicts.append(source)
        output["evidence_conflicts"] = conflicts
        return output

    @staticmethod
    def _deduplicate_query_terms(values: Any) -> Any:
        if not isinstance(values, list):
            return values
        output: List[Any] = []
        seen = set()
        for value in values:
            if isinstance(value, str):
                if value in seen:
                    continue
                seen.add(value)
            output.append(value)
        return output

    @staticmethod
    def _normalized_query(query: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", query).lower().split())

    @staticmethod
    def _source_context_excerpt(source: str) -> str:
        parts = [
            part.strip()
            for part in re.split(r"(?<=[.!?])\s+|\[질문\]", source.strip())
            if part.strip() and part.strip() != "[배경 시나리오]"
        ]
        return " ".join(parts[-2:])[-1200:]

    def _with_source_context(
        self, query: Any, skill_input: Mapping[str, Any]
    ) -> str:
        if not isinstance(query, str):
            return ""
        source = skill_input.get("normalized_question")
        if not isinstance(source, str) or not source.strip():
            return query
        excerpt = self._source_context_excerpt(source)
        query_normalized = self._normalized_query(query)
        source_normalized = self._normalized_query(excerpt)
        if source_normalized in query_normalized:
            return query
        return "%s\n[원문 맥락]\n%s" % (query.strip(), excerpt)

    def _fallback_initial_query(
        self,
        issue: Mapping[str, Any],
        index: int,
        seen: set,
        skill_input: Mapping[str, Any],
    ) -> str:
        base = issue.get("decision_question") or issue.get("issue_statement") or "관련 법률"
        return self._first_unique_contextual_query(
            ["%s 법률 조문" % base, "%s 적용 요건 조문" % base],
            base,
            index,
            seen,
            skill_input,
        )

    def _fallback_gap_query(
        self,
        evidence: Mapping[str, Any],
        index: int,
        seen: set,
        skill_input: Mapping[str, Any],
    ) -> str:
        base = evidence.get("completion_criteria") or evidence.get("description")
        return self._first_unique_contextual_query(
            ["%s 법률 조문" % base, "%s 적용 요건 조문" % base],
            base,
            index,
            seen,
            skill_input,
        )

    def _first_unique_contextual_query(
        self,
        candidates: List[str],
        base: str,
        index: int,
        seen: set,
        skill_input: Mapping[str, Any],
    ) -> str:
        for candidate in candidates:
            contextual = self._with_source_context(candidate, skill_input)
            if self._normalized_query(contextual) not in seen:
                return candidate
        for serial in range(1, 101):
            candidate = "%s 보완 검색 조문 %d-%d" % (base, index, serial)
            contextual = self._with_source_context(candidate, skill_input)
            if self._normalized_query(contextual) not in seen:
                return candidate
        raise SkillExecutionError("could not construct a unique contextual retrieval query")



    def _max_tokens(self, skill_name: str) -> int:
        if skill_name == "legal_issue_and_query_planning":
            return self.s1_max_tokens
        return DEFAULT_SKILL_MAX_TOKENS[skill_name]

    def _retry_max_tokens(self, skill_name: str, current: int) -> int:
        if skill_name == "legal_issue_and_query_planning":
            return self.s1_truncation_retry_max_tokens
        return min(current * 2, self.num_ctx)

    def _load_skill(self, skill_name: str) -> None:
        directory = self.skills_root / skill_name
        paths = {
            "instructions": directory / "SKILL.md",
            "contract": directory / "references/contract.md",
            "input_schema": directory / "references/input.schema.json",
            "output_schema": directory / "references/output.schema.json",
            "validator": directory / "scripts/validate_output.py",
        }
        if skill_name in {"provision_coverage_assessment", "grounded_legal_answer_generation"}:
            paths["compact_output_schema"] = directory / "references" / "compact_output.schema.json"
        missing = [name for name, path in paths.items() if not path.is_file()]
        if missing:
            raise SkillExecutionError("%s is missing: %s" % (skill_name, ", ".join(missing)))
        self._resources[skill_name] = {
            name: path.read_text(encoding="utf-8")
            for name, path in paths.items()
            if name != "validator"
        }
        module_name = "legal_harness_%s_validator" % skill_name
        spec = importlib.util.spec_from_file_location(module_name, paths["validator"])
        if spec is None or spec.loader is None:
            raise SkillExecutionError("cannot load validator for %s" % skill_name)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        validator = getattr(module, "validate", None)
        if not callable(validator):
            raise SkillExecutionError("validator for %s has no validate function" % skill_name)
        self._validators[skill_name] = validator
        self._validator_modules[skill_name] = module

    def _repair_s1_transport(
        self,
        skill_name: str,
        entry_point: str,
        output: Dict[str, Any],
        skill_input: Mapping[str, Any],
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Deterministically neutralize only S1 retrieval specificity the validator rejects.

        The skill raw output remains the retry artifact. This repair never
        introduces an article, changes legal/evidence decisions, or relaxes
        provenance; it only removes unsupported pinpoint text and retains the
        statute/semantic query. Grounded question/candidate references stay as
        emitted.
        """
        if skill_name != "legal_issue_and_query_planning":
            return output, []
        repaired = copy.deepcopy(output)
        audit: List[Dict[str, Any]] = []
        if entry_point == "INITIAL_PLAN":
            question = str(skill_input.get("original_question") or skill_input.get("normalized_question") or "")
            question_segment = question.split("[질문]", 1)[-1]
            normalized_question = self._normalized_query(question_segment)
            for target in self._list(repaired, "answer_targets", required=False):
                if not isinstance(target, dict):
                    continue
                anchor = target.get("question_anchor")
                if isinstance(anchor, str) and self._normalized_query(anchor) in normalized_question:
                    continue
                requested = target.get("requested_output")
                if isinstance(requested, str) and requested.strip() and self._normalized_query(requested) in normalized_question:
                    target["question_anchor"] = requested.strip()
                    audit.append({
                        "kind": "normalized_question_anchor",
                        "answer_target_id": target.get("answer_target_id"),
                        "before": anchor,
                        "after": target["question_anchor"],
                    })
            return repaired, audit
        if entry_point != "GAP_QUERY_PLAN":
            return repaired, audit
        requests = repaired.get("gap_retrieval_requests")
        neutralizer = getattr(
            self._validator_modules[skill_name],
            "neutralize_ungrounded_article_specificity",
            None,
        )
        if not isinstance(requests, list) or not callable(neutralizer):
            return repaired, audit
        neutralized, article_repairs = neutralizer(requests, skill_input)
        repaired["gap_retrieval_requests"] = neutralized
        audit.extend(article_repairs)
        evidence_by_id = {
            item.get("evidence_item_id"): item
            for item in self._list(skill_input, "required_evidence_items")
            if isinstance(item, Mapping)
        }
        for request in neutralized:
            if not isinstance(request, dict):
                continue
            for field in ("first_stage_query_text", "rerank_query_text"):
                if request.get(field) == "":
                    request.pop(field, None)
            if isinstance(request.get("query_text"), str) and request["query_text"].strip():
                continue
            evidence = evidence_by_id.get(request.get("evidence_item_id"))
            description = evidence.get("description") if isinstance(evidence, Mapping) else None
            if not isinstance(description, str) or not description.strip():
                continue
            request["query_text"] = "%s 관련 법정 근거" % description.strip()
            audit.append({
                "kind": "neutral_semantic_gap_fallback",
                "request_id": request.get("request_id"),
                "field": "query_text",
                "after": request["query_text"],
            })
        return repaired, audit

    def _neutral_s1_gap_replan(
        self,
        entry_point: str,
        skill_input: Mapping[str, Any],
        repaired_fallback: Mapping[str, Any],
        max_tokens: int,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        fallback_targets = [
            request.get("evidence_item_id")
            for request in self._list(
                repaired_fallback, "gap_retrieval_requests", required=False
            )
            if isinstance(request, Mapping)
        ]
        replan_note = (
            "NEUTRAL_SEMANTIC_GAP_REPLAN: The prior GAP plan required a "
            "deterministic provenance repair that changed a retrieval scoring "
            "query. Return exactly one clean neutral semantic replan for the "
            "same unresolved critical evidence target(s), without restoring an "
            "unsupported statutory pinpoint. The retriever scores "
            "first_stage_query_text when provided, otherwise query_text; it "
            "scores rerank_query_text when provided, otherwise query_text. "
            "Return a full replacement JSON. Repaired fallback JSON: "
            + json.dumps(
                self._redact_run_ids_for_prompt(repaired_fallback),
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        try:
            generation = self._generate(
                self._prompt(
                    "legal_issue_and_query_planning",
                    entry_point,
                    skill_input,
                    replan_note,
                ),
                max_tokens,
            )
            if generation.done_reason == "length":
                return None, "replan_truncated"
            raw_replan = self._parse_json_object(generation.text)
            replan = self._normalize_harness_owned_fields(
                "legal_issue_and_query_planning",
                entry_point,
                skill_input,
                copy.deepcopy(raw_replan),
            )
            replan, replan_repairs = self._repair_s1_transport(
                "legal_issue_and_query_planning", entry_point, replan, skill_input
            )
            if replan_repairs:
                return None, "replan_required_deterministic_repair"
            replan_targets = [
                request.get("evidence_item_id")
                for request in self._list(
                    replan, "gap_retrieval_requests", required=False
                )
                if isinstance(request, Mapping)
            ]
            if replan_targets != fallback_targets:
                return None, "replan_changed_evidence_targets"
            if not self._s1_scoring_query_delta(repaired_fallback, replan):
                return None, "replan_no_scoring_delta"
            validation_errors = self._validators["legal_issue_and_query_planning"](
                replan, skill_input
            )
            if validation_errors:
                return None, "replan_validation_error"
            if replan.get("status") != "ok":
                return None, "replan_non_ok_status"
            return replan, ""
        except Exception as exc:
            return None, "replan_failed:%s" % exc.__class__.__name__

    def _needs_neutral_s1_gap_replan(
        self,
        skill_name: str,
        entry_point: str,
        unrepaired: Mapping[str, Any],
        repaired: Mapping[str, Any],
        skill_input: Mapping[str, Any],
        repairs: List[Mapping[str, Any]],
    ) -> bool:
        if (
            skill_name != "legal_issue_and_query_planning"
            or entry_point != "GAP_QUERY_PLAN"
        ):
            return False
        if not any(
            repair.get("kind") == "neutralized_ungrounded_article_specificity"
            for repair in repairs
            if isinstance(repair, Mapping)
        ):
            return False
        unresolved = {
            item.get("evidence_item_id")
            for key in ("missing_evidence_items", "evidence_conflicts")
            for item in self._list(skill_input, key)
            if isinstance(item, Mapping)
        }
        critical = {
            item.get("evidence_item_id")
            for item in self._list(skill_input, "required_evidence_items")
            if isinstance(item, Mapping) and item.get("critical") is True
        }
        before = {
            (index, request.get("request_id")): self._s1_scoring_query_fields(request)
            for index, request in enumerate(
                self._list(unrepaired, "gap_retrieval_requests", required=False)
            )
            if isinstance(request, Mapping)
        }
        for index, request in enumerate(
            self._list(repaired, "gap_retrieval_requests", required=False)
        ):
            if not isinstance(request, Mapping):
                continue
            evidence_id = request.get("evidence_item_id")
            if evidence_id not in unresolved or evidence_id not in critical:
                continue
            key = (index, request.get("request_id"))
            current = self._s1_scoring_query_fields(request)
            if before.get(key) != current:
                return True
        return False

    @staticmethod
    def _s1_scoring_query_fields(request: Mapping[str, Any]) -> Tuple[str, str]:
        query = request.get("query_text")
        if not isinstance(query, str):
            query = ""
        return (
            request.get("first_stage_query_text")
            if isinstance(request.get("first_stage_query_text"), str)
            and request.get("first_stage_query_text")
            else query,
            request.get("rerank_query_text")
            if isinstance(request.get("rerank_query_text"), str)
            and request.get("rerank_query_text")
            else query,
        )

    @classmethod
    def _s1_scoring_query_delta(
        cls, before: Mapping[str, Any], after: Mapping[str, Any]
    ) -> bool:
        before_requests = cls._list(before, "gap_retrieval_requests", required=False)
        after_requests = cls._list(after, "gap_retrieval_requests", required=False)
        if len(before_requests) != len(after_requests):
            return True
        return any(
            not isinstance(left, Mapping)
            or not isinstance(right, Mapping)
            or tuple(
                cls._normalized_query(query)
                for query in cls._s1_scoring_query_fields(left)
            )
            != tuple(
                cls._normalized_query(query)
                for query in cls._s1_scoring_query_fields(right)
            )
            for left, right in zip(before_requests, after_requests)
        )

    def _semantic_scope_mismatches(
        self,
        skill_name: str,
        output: Mapping[str, Any],
        skill_input: Mapping[str, Any],
    ) -> List[Dict[str, Any]]:
        if skill_name != "provision_coverage_assessment":
            return []
        checker = getattr(
            self._validator_modules[skill_name], "semantic_scope_mismatches", None
        )
        if not callable(checker):
            return []
        mismatches = checker(output, skill_input)
        return [dict(item) for item in mismatches if isinstance(item, Mapping)]

    def _build_skill_input(
        self,
        skill_name: str,
        entry_point: str,
        payload: Mapping[str, Any],
    ) -> Dict[str, Any]:
        run_id = self._string(payload, "run_id")
        if skill_name == "legal_issue_and_query_planning":
            return self._planning_input(entry_point, payload, run_id)
        if skill_name == "provision_coverage_assessment":
            if entry_point != "ASSESS_COVERAGE":
                raise SkillExecutionError("S2 supports ASSESS_COVERAGE only")
            return {
                "schema_version": "1.0",
                "mode": entry_point,
                "run_id": run_id,
                "normalized_question": self._string(payload, "normalized_question"),
                "legal_issues": self._list(payload, "legal_issues"),
                "answer_targets": self._list(payload, "answer_targets", required=False),
                "required_evidence_items": self._external_evidence(self._list(payload, "required_evidence_items")),
                "candidate_provisions": self._external_provisions(
                    self._list(payload, "candidate_provisions"), run_id
                ),
                "prior_coverage_assessments": self._list(
                    payload, "prior_coverage_assessments", required=False
                ),
            }
        if skill_name == "grounded_legal_answer_generation":
            if entry_point not in {"GENERATE_ANSWER", "GENERATE_BENCHMARK_CANDIDATE"}:
                raise SkillExecutionError("S3 entry point is invalid: %s" % entry_point)
            benchmark_candidate = entry_point == "GENERATE_BENCHMARK_CANDIDATE"
            candidate_basis = payload.get("candidate_answer_basis")
            if benchmark_candidate and candidate_basis not in {
                "retrieved_candidates",
                "question_only",
            }:
                raise SkillExecutionError("benchmark candidate basis is invalid")
            return {
                "schema_version": "1.0",
                "mode": entry_point,
                "run_id": run_id,
                "normalized_question": self._string(payload, "normalized_question"),
                "legal_issues": self._list(payload, "legal_issues"),
                "answer_targets": self._list(payload, "answer_targets", required=False),
                "required_evidence_items": self._external_evidence(self._list(payload, "required_evidence_items")),
                "coverage_assessments": self._list(payload, "coverage_assessments"),
                "accepted_provisions": self._external_provisions(
                    self._list(payload, "accepted_provisions"), run_id, accepted=True
                ),
                "candidate_provisions": self._external_provisions(
                    self._list(payload, "candidate_provisions", required=False),
                    run_id,
                    benchmark_candidate=True,
                ),
                "answer_mode": payload.get("answer_mode", "full"),
                "answered_target_ids": self._list(
                    payload, "answered_target_ids", required=False
                ),
                "deferred_target_ids": self._list(
                    payload, "deferred_target_ids", required=False
                ),
                "authorization": {
                    "action": (
                        "GENERATE_BENCHMARK_CANDIDATE"
                        if benchmark_candidate
                        else "GENERATE"
                    ),
                    "authorized_by": (
                        "HARNESS_BENCHMARK_DIAGNOSTIC"
                        if benchmark_candidate
                        else "PROVISION_COVERAGE_POLICY"
                    ),
                    "validated_state_version": int(payload.get("state_version", 0)),
                },
                "generation_purpose": (
                    "benchmark_candidate" if benchmark_candidate else "published_answer"
                ),
                "publishable": not benchmark_candidate,
                "candidate_answer_basis": (
                    candidate_basis if benchmark_candidate else "published_answer"
                ),
                "generation_constraints": {
                    "language": "ko",
                    "max_answer_chars": PUBLIC_ANSWER_MAX_CHARACTERS,
                    "citation_marker_style": "citation_id",
                    "public_conclusion_contract": "required",
                },
            }
        raise SkillExecutionError("unsupported skill: %s" % skill_name)

    def _planning_input(
        self,
        entry_point: str,
        payload: Mapping[str, Any],
        run_id: str,
    ) -> Dict[str, Any]:
        base = {
            "schema_version": "1.0",
            "mode": entry_point,
            "run_id": run_id,
            "normalized_question": self._string(payload, "normalized_question"),
            "constraints": {
                "allowed_query_channels": ["provision_style", "sparse_keywords", "statute_aware"],
                "max_requests_per_issue": 3,
                "answer_target_contract": "required",
            },
        }
        if entry_point == "INITIAL_PLAN":
            base.update(
                {
                    "original_question": self._string(payload, "question"),
                    "query_history": self._list(payload, "query_history", required=False),
                }
            )
            return base
        if entry_point != "GAP_QUERY_PLAN":
            raise SkillExecutionError("S1 entry point is invalid: %s" % entry_point)
        next_retrieval_round = payload.get("next_retrieval_round")
        if (
            isinstance(next_retrieval_round, bool)
            or not isinstance(next_retrieval_round, int)
            or next_retrieval_round < 1
        ):
            raise SkillExecutionError("next_retrieval_round must be a positive integer")
        base.update(
            {
                "next_retrieval_round": next_retrieval_round,
                "legal_issues": self._list(payload, "legal_issues"),
                "answer_targets": self._list(
                    payload, "answer_targets", required=False
                ),
                "required_evidence_items": self._external_evidence(
                    self._list(payload, "required_evidence_items")
                ),
                "coverage_assessments": self._list(payload, "coverage_assessments"),
                "missing_evidence_items": self._list(payload, "missing_evidence_items"),
                "evidence_conflicts": self._list(payload, "evidence_conflicts"),
                "query_history": self._list(payload, "query_history"),
                "candidate_cross_references": self._list(payload, "candidate_cross_references", required=False),
                "seen_provision_ids": self._list(payload, "seen_provision_ids"),
                "remaining_request_budget": payload.get("remaining_request_budget"),
            }
        )
        if not isinstance(base["remaining_request_budget"], int):
            raise SkillExecutionError("remaining_request_budget must be an integer")
        return base

    def _external_evidence(self, evidence_items: List[Any]) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        for item in evidence_items:
            if not isinstance(item, Mapping):
                raise SkillExecutionError("required_evidence_items must contain objects")
            result.append(
                {
                    "evidence_item_id": self._string(item, "evidence_item_id"),
                    "issue_id": self._string(item, "issue_id"),
                    "evidence_type": self._string(item, "evidence_type"),
                    "description": self._string(item, "description"),
                    "critical": item.get("critical"),
                    "completion_criteria": item.get("completion_criteria")
                    or self._string(item, "description"),
                    "necessity_reason": item.get("necessity_reason", ""),
                    "answer_target_ids": self._list(
                        item, "answer_target_ids", required=False
                    ),
                    "scope_source": item.get("scope_source", "legacy"),
                    "completion_requirements": self._list(
                        item, "completion_requirements", required=False
                    ),
                }
            )
        return result

    def _external_provisions(
        self,
        candidates: List[Any],
        run_id: str,
        accepted: bool = False,
        benchmark_candidate: bool = False,
    ) -> List[Dict[str, Any]]:
        provisions: List[Dict[str, Any]] = []
        for index, candidate in enumerate(candidates, start=1):
            if not isinstance(candidate, Mapping):
                raise SkillExecutionError("candidate provisions must contain objects")
            text = self._string(candidate, "provision_text")
            source_provision_id = self._string(candidate, "provision_id")
            provision = {
                "provision_id": source_provision_id if accepted else "C%03d" % index,
                "statute_name": self._string(candidate, "statute_name"),
                "article_label": self._string(candidate, "statute_name"),
                "text": text,
                "source_snapshot_id": "sha256:%s" % hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
            if accepted or benchmark_candidate:
                supported = candidate.get("supported_evidence_item_ids")
                if not isinstance(supported, list) or not supported:
                    supported = candidate.get("target_evidence_item_ids")
                if not isinstance(supported, list) or not supported:
                    raise SkillExecutionError(
                        "S3 source provisions require supported evidence item IDs"
                    )
                provision["supported_evidence_item_ids"] = supported
            if not accepted:
                provision["source_provision_id"] = source_provision_id
                retrieval_metadata = {
                    "source_request_id": candidate.get("source_request_id"),
                    "retrieval_round": candidate.get("retrieval_round"),
                    "first_stage_score": candidate.get("first_stage_score"),
                    "rerank_score": candidate.get("rerank_score"),
                }
                if any(value is not None for value in retrieval_metadata.values()):
                    provision["retrieval_metadata"] = {"run_id": run_id, **retrieval_metadata}
            provisions.append(provision)
        return provisions

    def _prompt(
        self,
        skill_name: str,
        entry_point: str,
        skill_input: Mapping[str, Any],
        repair_note: str,
    ) -> str:
        resources = self._resources[skill_name]
        prompt_input = self._redact_run_ids_for_prompt(skill_input)
        prompt_repair_note = self._redact_run_id_text(
            repair_note, skill_input.get("run_id")
        )
        compact_output_schema = resources.get("compact_output_schema")
        output_schema = compact_output_schema or resources["output_schema"]
        output_schema_label = (
            "RAW COMPACT TRANSPORT; the harness deterministically normalizes it before canonical validation"
            if compact_output_schema
            else "CANONICAL VALIDATED OUTPUT"
        )
        return """You are executing one external skill inside a deterministic legal QA harness.
Return exactly one JSON object and nothing else. Do not use Markdown code fences.
The harness, not you, controls retrieval, policy, abstention, and citation validation.

SKILL INSTRUCTIONS:
{instructions}

CONTRACT:
{contract}

OUTPUT JSON SCHEMA ({output_schema_label}):
{output_schema}

ENTRY POINT: {entry_point}
{repair_note}

INPUT:
{input_json}

FINAL OUTPUT INVARIANTS:
{output_invariants}
""".format(
            instructions=resources["instructions"],
            contract=resources["contract"],
            output_schema=output_schema,
            output_schema_label=output_schema_label,
            entry_point=entry_point,
            repair_note=prompt_repair_note,
            input_json=json.dumps(prompt_input, ensure_ascii=False, separators=(",", ":")),
            output_invariants=self._output_invariants(skill_name, prompt_input),
        )

    @classmethod
    def _redact_run_ids_for_prompt(cls, value: Any) -> Any:
        """Return a prompt-only copy with every run ID replaced deterministically."""
        if isinstance(value, Mapping):
            return {
                key: (
                    PROMPT_RUN_ID_PLACEHOLDER
                    if key == "run_id"
                    else cls._redact_run_ids_for_prompt(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._redact_run_ids_for_prompt(item) for item in value]
        if isinstance(value, tuple):
            return tuple(cls._redact_run_ids_for_prompt(item) for item in value)
        return value

    @staticmethod
    def _redact_run_id_text(text: str, run_id: Any) -> str:
        """Defend retry prompts against a run ID embedded in prior-output text."""
        if not isinstance(run_id, str) or not run_id:
            return text
        return text.replace(run_id, PROMPT_RUN_ID_PLACEHOLDER)

    def _output_invariants(self, skill_name: str, skill_input: Mapping[str, Any]) -> str:
        if skill_name == "legal_issue_and_query_planning":
            return self._s1_output_invariants(skill_input)
        if skill_name == "grounded_legal_answer_generation":
            if skill_input.get("mode") == "GENERATE_BENCHMARK_CANDIDATE":
                if skill_input.get("candidate_answer_basis") == "question_only":
                    return (
                        "This is a non-publishable question-only benchmark candidate because retrieval returned no candidate provisions. "
                        "The harness policy remains ABSTAIN. Return a conclusion-first benchmark answer in 1 to 3 short sentences and no more than 800 characters. "
                        "Do not add abstention or audit boilerplate, claims, citations, or citation markers; do not present it as authorized, supported, or publishable."
                    )
                return (
                    "This is a non-publishable benchmark candidate. The harness policy remains ABSTAIN. "
                    "Use only candidate provision IDs supplied in INPUT; they are retrieved evidence, not accepted evidence. "
                    "Give a conclusion-first benchmark answer in 1 to 3 short sentences and no more than 800 characters, with no abstention or audit boilerplate. "
                    "Answer every supplied target, cite every substantive claim, preserve all audit arrays, and do not state that the candidate is authorized or publishable."
                    + " "
                    + S3_COMPACT_TRANSPORT_INVARIANT
                )
            answer_mode = skill_input.get("answer_mode", "full")
            answered_target_ids = self._list(
                skill_input, "answered_target_ids", required=False
            )
            deferred_target_ids = self._list(
                skill_input, "deferred_target_ids", required=False
            )
            max_answer_chars = skill_input.get("generation_constraints", {}).get(
                "max_answer_chars", 800
            )
            partial_ids = [
                item.get("evidence_item_id")
                for item in self._list(skill_input, "coverage_assessments")
                if isinstance(item, Mapping)
                and item.get("status") == "partially_covered"
            ]
            if partial_ids:
                return (
                    "Use only accepted provision IDs supplied in INPUT. Answer mode is %s; substantive claims may name only answered target IDs %s and must not name deferred target IDs %s. Critical partial evidence IDs are %s. "
                    "Do not assert their missing facts. Include at least one cited conditional legal claim and a non-empty "
                    "limitations array that states each unresolved condition. Every claims[] item must set citation_required "
                    "true and have at least one claim_citation. Keep uncited missing-fact and limitation prose out of claims[]; "
                    "put it in assumptions[] or limitations[]. Preserve all audit claims, citations, assumptions, and limitations, but do not append them all to the public answer. "
                    "The public answer must put the conclusion first, use 1 to 3 short sentences and no more than 800 characters, and repeat only an outcome-changing unresolved condition with the minimum statutory basis."
                    % (
                        answer_mode,
                        json.dumps(answered_target_ids),
                        json.dumps(deferred_target_ids),
                        json.dumps(partial_ids),
                    )
                    + " "
                    + S3_COMPACT_TRANSPORT_INVARIANT
                )
            return (
                "Use only accepted provision IDs supplied in INPUT. Answer mode is %s; substantive claims may name only answered target IDs %s and must not name deferred target IDs %s. Every claims[] item must set citation_required true and have at least one claim_citation; keep uncited factual or limitation prose in assumptions[] or limitations[]. "
                "Preserve every audit field, but make the public answer conclusion-first, 1 to 3 short sentences, no more than 800 characters, and include only an outcome-changing condition and the minimum statutory basis; do not append all audit claims or notes."
                % (answer_mode, json.dumps(answered_target_ids), json.dumps(deferred_target_ids))
                + " "
                + S3_COMPACT_TRANSPORT_INVARIANT
            )
        if skill_name != "provision_coverage_assessment":
            return "Use only the identifiers and fields supplied in INPUT."
        evidence_ledger = [
            {"evidence_item_id": item.get("evidence_item_id"), "issue_id": item.get("issue_id"), "critical": item.get("critical")}
            for item in self._list(skill_input, "required_evidence_items")
            if isinstance(item, Mapping)
        ]
        candidate_ids = [
            item.get("provision_id")
            for item in self._list(skill_input, "candidate_provisions")
            if isinstance(item, Mapping)
        ]
        return (
            "Use only evidence IDs %s and candidate IDs %s. Assess each ledger item exactly once: %s. "
            "For raw compact transport omit link IDs and quoted text; retain one criterion result per supplied requirement, its linked candidate IDs, and every legal decision; never invent IDs or missing aspects. "
            "Follow the contract's closed-requirement coverage mapping."
            % (
                json.dumps([item["evidence_item_id"] for item in evidence_ledger]),
                json.dumps(candidate_ids),
                json.dumps(evidence_ledger, ensure_ascii=False, separators=(",", ":")),

            )
            + " "
            + S2_COMPACT_AUDIT_INVARIANT
        )
    def _s1_output_invariants(self, skill_input: Mapping[str, Any]) -> str:
        if skill_input.get("mode") != "GAP_QUERY_PLAN":
            return (
                "Copy run_id. Keep one target per requested conclusion, but preserve separate critical evidence for distinct rules, exceptions, cross-references, or legal effects. Give every critical item a request. Follow the supplied query-field contract without assuming a retriever-specific override."
                " Completion requirements distinguish statutory evidence obligations from retrieval hypotheses. Do not state a legal answer, article, condition, or threshold absent from the question as established fact; preserve genuinely independent rules, exceptions, cross-references, and legal effects."
            )
        prior_queries = []
        for item in self._list(skill_input, "query_history"):
            if isinstance(item, Mapping):
                query = item.get("query_text") or item.get("normalized_query")
                if isinstance(query, str):
                    prior_queries.append(query)
        unresolved = [
            item.get("evidence_item_id")
            for key in ("missing_evidence_items", "evidence_conflicts")
            for item in self._list(skill_input, key)
            if isinstance(item, Mapping)
        ]
        return (
            "Target only unresolved statute-evidence IDs %s. Do not search for missing facts or scope excess. "
            " A new statutory pinpoint must be grounded by the original question or the supplied candidate_cross_references; otherwise use a neutral semantic query for the original unresolved evidence item. "
            "Each KURE semantic gap query must differ from prior queries %s. Copy run_id and stay within budget."
            % (
                json.dumps(unresolved),
                json.dumps(prior_queries, ensure_ascii=False),
            )
        )

    def _generate(self, prompt: str, max_tokens: int) -> GenerationResult:
        if self.generator is not None:
            return self._generation_result(self.generator(prompt))
        request_data = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "keep_alive": "15m",
                "options": {
                    "temperature": 0,
                    "num_ctx": self.num_ctx,
                    "num_predict": max_tokens,
                    "seed": self.seed,
                },
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=request_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise SkillExecutionError("local Ollama request failed: %s" % exc) from exc
        return self._generation_result(payload)

    @staticmethod
    def _generation_result(payload: Any) -> GenerationResult:
        if isinstance(payload, str):
            generated = payload
            done_reason = None
            eval_count = None
        elif isinstance(payload, Mapping):
            generated = payload.get("response")
            raw_done_reason = payload.get("done_reason")
            done_reason = raw_done_reason if isinstance(raw_done_reason, str) else None
            raw_eval_count = payload.get("eval_count")
            eval_count = (
                raw_eval_count
                if isinstance(raw_eval_count, int) and not isinstance(raw_eval_count, bool)
                else None
            )
        else:
            raise SkillExecutionError("local generator returned an unsupported response")
        if not isinstance(generated, str) or not generated.strip():
            raise SkillExecutionError("local Ollama returned no JSON response")
        return GenerationResult(
            text=generated,
            done_reason=done_reason,
            eval_count=eval_count,
        )

    @staticmethod
    def _generation_diagnostic(generation: GenerationResult) -> Dict[str, Any]:
        encoded = generation.text.encode("utf-8")
        return {
            "done_reason": generation.done_reason,
            "eval_count": generation.eval_count,
            "response_tokens": generation.eval_count,
            "response_characters": len(generation.text),
            "response_utf8_bytes": len(encoded),
            "response_sha256": hashlib.sha256(encoded).hexdigest(),
            "response_tail": generation.text[-RESPONSE_TAIL_CHARACTERS:],
        }

    def _record_diagnostic(self, diagnostic: Mapping[str, Any]) -> None:
        if self.diagnostic_sink is not None:
            self.diagnostic_sink(dict(diagnostic))

    @staticmethod
    def _parse_json_object(raw: str) -> Dict[str, Any]:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
        decoder = json.JSONDecoder()
        first_brace = text.find("{")
        if first_brace < 0:
            raise ModelOutputInvalidJsonError(
                "MODEL_OUTPUT_INVALID_JSON: model response contains no JSON object"
            )
        try:
            parsed, _ = decoder.raw_decode(text[first_brace:])
        except json.JSONDecodeError as exc:
            raise ModelOutputInvalidJsonError(
                "MODEL_OUTPUT_INVALID_JSON: %s" % exc
            ) from exc
        if not isinstance(parsed, dict):
            raise ModelOutputInvalidJsonError(
                "MODEL_OUTPUT_INVALID_JSON: model response must be a JSON object"
            )
        return parsed

    def _adapt_output(
        self,
        skill_name: str,
        entry_point: str,
        output: Mapping[str, Any],
        skill_input: Mapping[str, Any],
    ) -> Dict[str, Any]:
        if skill_name == "legal_issue_and_query_planning":
            return self._adapt_s1(entry_point, output)
        if skill_name == "provision_coverage_assessment":
            return self._adapt_s2(output, skill_input)
        if skill_name == "grounded_legal_answer_generation":
            return self._adapt_s3(output, skill_input)
        raise SkillExecutionError("unsupported skill: %s" % skill_name)

    def _adapt_s1(self, entry_point: str, output: Mapping[str, Any]) -> Dict[str, Any]:
        request_key = "retrieval_requests" if entry_point == "INITIAL_PLAN" else "gap_retrieval_requests"
        requests: List[Dict[str, Any]] = []
        for request in self._list(output, request_key):
            if not isinstance(request, Mapping):
                raise SkillExecutionError("S1 request must be an object")
            channel = self._string(request, "query_channel")
            requests.append(
                {
                    "request_id": self._string(request, "request_id"),
                    "issue_id": self._string(request, "issue_id"),
                    "evidence_item_id": self._string(request, "evidence_item_id"),
                    "query_channel": INTERNAL_CHANNELS.get(channel, channel),
                    "query_text": self._string(request, "query_text"),
                    "top_k": 100,
                    "query_terms": [
                        item.strip()
                        for item in request.get("query_terms", [])
                        if isinstance(item, str) and item.strip()
                    ],
                    "statute_hints": [
                        item.strip()
                        for item in request.get("statute_hints", [])
                        if isinstance(item, str) and item.strip()
                    ],
                    "first_stage_query_text": request.get("first_stage_query_text"),
                    "rerank_query_text": request.get("rerank_query_text"),
                }
            )
        if entry_point == "GAP_QUERY_PLAN":
            return {"gap_retrieval_requests": requests}
        issues = []
        for issue in self._list(output, "legal_issues"):
            if not isinstance(issue, Mapping):
                raise SkillExecutionError("S1 issue must be an object")
            issues.append(
                {
                    "issue_id": self._string(issue, "issue_id"),
                    "description": issue.get("issue_statement") or self._string(issue, "decision_question"),
                }
            )
        evidence = []
        for item in self._list(output, "required_evidence_items"):
            if not isinstance(item, Mapping):
                raise SkillExecutionError("S1 evidence item must be an object")
            evidence.append(
                {
                    "evidence_item_id": self._string(item, "evidence_item_id"),
                    "issue_id": self._string(item, "issue_id"),
                    "evidence_type": self._string(item, "evidence_type"),
                    "description": self._string(item, "description"),
                    "critical": item.get("critical"),
                    "completion_criteria": self._string(item, "completion_criteria"),
                    "necessity_reason": item.get("necessity_reason", ""),
                    "answer_target_ids": [
                        target_id
                        for target_id in item.get("answer_target_ids", [])
                        if isinstance(target_id, str) and target_id
                    ],
                    "scope_source": item.get("scope_source", "legacy"),
                    "completion_requirements": [
                        {
                            "requirement_id": self._string(requirement, "requirement_id"),
                            "text": self._string(requirement, "text"),
                        }
                        for requirement in self._list(
                            item, "completion_requirements", required=False
                        )
                        if isinstance(requirement, Mapping)
                    ],
                }
            )
        answer_targets = []
        for target in self._list(output, "answer_targets", required=False):
            if not isinstance(target, Mapping):
                raise SkillExecutionError("S1 answer target must be an object")
            answer_targets.append(
                {
                    "answer_target_id": self._string(target, "answer_target_id"),
                    "question_anchor": self._string(target, "question_anchor"),
                    "requested_output": self._string(target, "requested_output"),
                    "answer_type": self._string(target, "answer_type"),
                }
            )
        return {
            "legal_issues": issues,
            "answer_targets": answer_targets,
            "required_evidence_items": evidence,
            "retrieval_requests": requests,
        }

    def _adapt_s2(self, output: Mapping[str, Any], skill_input: Mapping[str, Any]) -> Dict[str, Any]:
        evidence_by_id = {
            item["evidence_item_id"]: item
            for item in self._list(skill_input, "required_evidence_items")
            if isinstance(item, Mapping)
        }
        provisions = {
            item["provision_id"]: item
            for item in self._list(skill_input, "candidate_provisions")
            if isinstance(item, Mapping)
        }
        links = []
        for link in self._list(output, "evidence_links", required=False):
            if not isinstance(link, Mapping):
                raise SkillExecutionError("S2 evidence link must be an object")
            provision_id = self._string(link, "provision_id")
            evidence_id = self._string(link, "evidence_item_id")
            source = provisions.get(provision_id)
            if source is None:
                raise SkillExecutionError("S2 cited a provision outside the supplied candidates")
            quote = self._string(link, "quoted_text")
            if quote == "[FULL_TEXT]":
                quote = self._string(source, "text")
            start = source["text"].find(quote)
            if start < 0:
                raise SkillExecutionError("S2 quote is not in the supplied provision")
            links.append(
                {
                    "issue_id": evidence_by_id[evidence_id]["issue_id"],
                    "evidence_item_id": evidence_id,
                    "provision_id": self._source_provision_id(provisions, provision_id),
                    "support_spans": [{"start_char": start, "end_char": start + len(quote)}],
                    "assessment": "conflicting" if link.get("relation") == "conflicts" else "accepted",
                }
            )
        assessments = []
        for assessment in self._list(output, "coverage_assessments"):
            if not isinstance(assessment, Mapping):
                raise SkillExecutionError("S2 assessment must be an object")
            legal_status = assessment.get("legal_status")
            applicability_status = assessment.get("applicability_status")
            gap_type = assessment.get("gap_type")
            status = assessment.get("status", assessment.get("evidence_status"))
            if not isinstance(status, str) and isinstance(legal_status, str):
                status = (
                    "partially_covered"
                    if legal_status == "covered" and applicability_status == "conditional"
                    else legal_status
                )
            partial_kind = assessment.get("partial_kind")
            if not isinstance(partial_kind, str):
                partial_kind = (
                    "factual_condition"
                    if legal_status == "covered" and applicability_status == "conditional"
                    else "legal_support_gap"
                    if status == "partially_covered"
                    else "not_applicable"
                )
            criterion_results = []
            for result in self._list(assessment, "criterion_results", required=False):
                if not isinstance(result, Mapping):
                    raise SkillExecutionError("S2 criterion result must be an object")
                criterion_results.append(
                    {
                        "requirement_id": self._string(result, "requirement_id"),
                        "status": self._string(result, "status"),
                        "linked_provision_ids": [
                            self._source_provision_id(provisions, provision_id)
                            for provision_id in self._list(result, "linked_provision_ids")
                        ],
                        "rationale": self._string(result, "rationale"),
                    }
                )
            mapped_assessment = {
                "evidence_item_id": self._string(assessment, "evidence_item_id"),
                "status": self._string({"status": status}, "status"),
                "linked_provision_ids": [
                    self._source_provision_id(provisions, provision_id)
                    for provision_id in self._list(assessment, "linked_provision_ids")
                ],
                "rationale": self._string(assessment, "rationale"),
                "partial_kind": partial_kind,
                "missing_aspects": [
                    self._string({"value": item}, "value")
                    for item in self._list(assessment, "missing_aspects")
                ],
                "criterion_results": criterion_results,
            }
            if all(
                isinstance(value, str)
                for value in (legal_status, applicability_status, gap_type)
            ):
                mapped_assessment.update(
                    {
                        "legal_status": legal_status,
                        "applicability_status": applicability_status,
                        "gap_type": gap_type,
                    }
                )
            assessments.append(mapped_assessment)
        conflicts = []
        for conflict in self._list(output, "evidence_conflicts", required=False):
            if not isinstance(conflict, Mapping):
                raise SkillExecutionError("S2 conflict must be an object")
            conflicts.append(
                {
                    "evidence_item_id": self._string(conflict, "evidence_item_id"),
                    "provision_ids": [
                        self._source_provision_id(provisions, provision_id)
                        for provision_id in self._list(conflict, "provision_ids")
                    ],
                    "description": self._string(conflict, "description"),
                    "resolved": False,
                }
            )
        return {
            "evidence_links": links,
            "coverage_assessments": assessments,
            "evidence_conflicts": conflicts,
        }

    def _source_provision_id(
        self, provisions: Mapping[str, Mapping[str, Any]], provision_id: Any
    ) -> str:
        if not isinstance(provision_id, str):
            raise SkillExecutionError("S2 provision_id must be a non-empty string")
        source = provisions.get(provision_id)
        if source is None:
            raise SkillExecutionError("S2 cited a provision outside the supplied candidates")
        return self._string(source, "source_provision_id")

    def _adapt_s3(
        self, output: Mapping[str, Any], skill_input: Mapping[str, Any]
    ) -> Dict[str, Any]:
        benchmark_question_only = (
            skill_input.get("mode") == "GENERATE_BENCHMARK_CANDIDATE"
            and skill_input.get("candidate_answer_basis") == "question_only"
        )
        claims: List[Dict[str, Any]] = []
        for claim in self._list(
            output, "claims", required=not benchmark_question_only
        ):
            if not isinstance(claim, Mapping):
                raise SkillExecutionError("S3 claim must be an object")
            claim_payload = dict(claim)
            claim_payload.update(
                {
                    "claim_id": self._string(claim, "claim_id"),
                    "text": self._string(claim, "text"),
                    "answer_target_ids": self._list(
                        claim, "answer_target_ids", required=False
                    ),
                }
            )
            claims.append(claim_payload)

        provision_key = (
            "candidate_provisions"
            if skill_input.get("mode") == "GENERATE_BENCHMARK_CANDIDATE"
            else "accepted_provisions"
        )
        provisions = {
            self._string(provision, "provision_id"): provision
            for provision in self._list(skill_input, provision_key)
            if isinstance(provision, Mapping)
        }
        citations: List[Dict[str, Any]] = []
        for citation in self._list(
            output, "claim_citations", required=not benchmark_question_only
        ):
            if not isinstance(citation, Mapping):
                raise SkillExecutionError("S3 citation must be an object")
            claim_id = self._string(citation, "claim_id")
            provision_id = self._string(citation, "provision_id")
            provision = provisions.get(provision_id)
            if provision is None:
                raise SkillExecutionError(
                    "S3 cited a provision outside the supplied source set"
                )
            citation_payload = dict(citation)
            citation_payload["claim_id"] = claim_id
            citation_payload["provision_id"] = str(
                provision.get("source_provision_id", provision_id)
            )
            citations.append(citation_payload)

        expected_claim_ids = {claim["claim_id"] for claim in claims}
        if {citation["claim_id"] for citation in citations} != expected_claim_ids:
            raise SkillExecutionError(
                "S3 must cite every claim for the harness citation check"
            )

        audit_notes: Dict[str, List[Dict[str, Any]]] = {}
        for key in ("assumptions", "limitations"):
            values: List[Dict[str, Any]] = []
            for item in self._list(output, key):
                if not isinstance(item, Mapping):
                    raise SkillExecutionError("S3 %s item must be an object" % key)
                values.append(dict(item))
            audit_notes[key] = values

        return {
            "answer": self._string(output, "answer"),
            "claims": claims,
            "claim_citations": citations,
            "assumptions": audit_notes["assumptions"],
            "limitations": audit_notes["limitations"],
        }

    @staticmethod
    def _string(value: Mapping[str, Any], key: str) -> str:
        item = value.get(key)
        if not isinstance(item, str) or not item.strip():
            raise SkillExecutionError("%s must be a non-empty string" % key)
        return item.strip()

    @staticmethod
    def _list(value: Mapping[str, Any], key: str, required: bool = True) -> List[Any]:
        item = value.get(key)
        if item is None and not required:
            return []
        if not isinstance(item, list):
            raise SkillExecutionError("%s must be a list" % key)
        return item
