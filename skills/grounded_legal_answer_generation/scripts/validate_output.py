#!/usr/bin/env python3
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from public_answer_contract import (  # noqa: E402
    qualifying_public_exception_citation_is_authorized as shared_qualifying_public_exception_citation_is_authorized,
)


def load(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def unique(items, key, pattern, errors):
    seen = set()
    for item in items:
        value = item.get(key)
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            errors.append(f"invalid {key}: {value!r}")
        elif value in seen:
            errors.append(f"duplicate {key}: {value}")
        seen.add(value)
    return seen


def public_claims(claims, target_order, require_roles=False):
    if not require_roles:
        selected = []
        def add(claim):
            if claim not in selected and len(selected) < 3:
                selected.append(claim)
        if claims:
            add(claims[0])
        for claim in claims:
            if claim.get("applicability") == "conditional":
                add(claim)
        for claim in claims:
            if claim.get("claim_type") == "legal_rule":
                add(claim)
        for claim in claims:
            add(claim)
        return selected
    target_index = {target_id: index for index, target_id in enumerate(target_order)}
    public = [claim for claim in claims if claim.get("public_role") == "conclusion"]
    return sorted(
        public,
        key=lambda claim: min(
            (target_index[target_id] for target_id in claim.get("answer_target_ids", []) if target_id in target_index),
            default=len(target_index),
        ),
    )


def validate_preconditions(input_data, errors):
    benchmark_candidate = input_data.get("mode") == "GENERATE_BENCHMARK_CANDIDATE"
    authorization = input_data.get("authorization", {})
    if benchmark_candidate:
        basis = input_data.get("candidate_answer_basis")
        if (
            authorization.get("action") != "GENERATE_BENCHMARK_CANDIDATE"
            or authorization.get("authorized_by") != "HARNESS_BENCHMARK_DIAGNOSTIC"
            or input_data.get("generation_purpose") != "benchmark_candidate"
            or input_data.get("publishable") is not False
        ):
            errors.append("benchmark candidate is not authorized by the diagnostic harness")
        if basis == "retrieved_candidates" and not input_data.get("candidate_provisions"):
            errors.append("retrieved-candidate basis requires candidate_provisions")
        elif basis == "question_only" and input_data.get("candidate_provisions"):
            errors.append("question-only basis must not receive candidate_provisions")
        elif basis not in {"retrieved_candidates", "question_only"}:
            errors.append("benchmark candidate basis is invalid")
        return
    if authorization.get("action") != "GENERATE" or authorization.get("authorized_by") != "PROVISION_COVERAGE_POLICY":
        errors.append("generation is not authorized by the provision coverage policy")
    if input_data.get("generation_purpose") != "published_answer" or input_data.get("publishable") is not True:
        errors.append("published generation purpose is invalid")
    if input_data.get("candidate_answer_basis") != "published_answer":
        errors.append("published generation must use the published_answer basis")
    evidence = {x.get("evidence_item_id"): x for x in input_data.get("required_evidence_items", [])}
    assessments = {x.get("evidence_item_id"): x for x in input_data.get("coverage_assessments", [])}
    core_provisions = input_data.get(
        "core_accepted_provisions", input_data.get("accepted_provisions", [])
    )
    supported = {
        evidence_id
        for provision in core_provisions
        for evidence_id in provision.get("supported_evidence_item_ids", [])
    }
    deferred_target_ids = set(input_data.get("deferred_target_ids", []))
    for evidence_id, item in evidence.items():
        if item.get("critical") is not True:
            continue
        item_target_ids = set(item.get("answer_target_ids", []))
        if item_target_ids and item_target_ids.issubset(deferred_target_ids):
            continue
        status = assessments.get(evidence_id, {}).get("status")
        if status == "covered":
            continue
        if status == "partially_covered" and evidence_id in supported:
            continue
        errors.append(f"critical evidence lacks citable support: {evidence_id}")
    if not core_provisions:
        errors.append("core_accepted_provisions must not be empty")


def validate_answer_target_scope(output, input_data, errors):
    answer_targets = {
        target.get("answer_target_id")
        for target in input_data.get("answer_targets", [])
        if isinstance(target, dict)
    }
    answered = input_data.get("answered_target_ids", [])
    deferred = input_data.get("deferred_target_ids", [])
    mode = input_data.get("answer_mode", "full")
    if not answer_targets:
        return
    if not isinstance(answered, list) or not isinstance(deferred, list):
        errors.append("answer target scope must be lists")
        return
    if set(answered) | set(deferred) != answer_targets or set(answered) & set(deferred):
        errors.append("answered/deferred target IDs must partition answer_targets")
    benchmark_candidate = input_data.get("mode") == "GENERATE_BENCHMARK_CANDIDATE"
    if benchmark_candidate:
        if mode != "abstain_candidate" or set(deferred) or set(answered) != answer_targets:
            errors.append("benchmark candidate must answer every target without a deferred scope")
        if input_data.get("candidate_answer_basis") == "question_only":
            if output.get("claims") or output.get("claim_citations"):
                errors.append("question-only benchmark candidate must not emit claims or citations")
            return
    elif mode not in {"full", "conditional", "limited"}:
        errors.append("invalid answer_mode")
    if not benchmark_candidate and mode in {"full", "conditional"} and set(deferred):
        errors.append("full and conditional modes cannot defer answer targets")
    claimed = set()
    for claim in output.get("claims", []):
        target_ids = claim.get("answer_target_ids", []) if isinstance(claim, dict) else []
        if not isinstance(target_ids, list) or not target_ids:
            errors.append("claims must identify answer_target_ids")
            continue
        if set(target_ids) - set(answered):
            errors.append("claim references deferred or unknown answer target")
        claimed.update(target_ids)
    if claimed != set(answered):
        errors.append("claims must cover every answered target exactly within scope")
    if input_data.get("generation_constraints", {}).get("public_conclusion_contract") == "required":
        public = [claim for claim in output.get("claims", []) if isinstance(claim, dict) and claim.get("public_role") == "conclusion"]
        if any(not isinstance(claim, dict) or claim.get("public_role") not in {"conclusion", "audit"} for claim in output.get("claims", [])):
            errors.append("every claim must declare public_role under the public conclusion contract")
        if not 1 <= len(public) <= 4:
            errors.append("public conclusion contract requires 1 to 4 conclusion claims")
        public_targets = {target_id for claim in public for target_id in claim.get("answer_target_ids", [])}
        if public_targets != set(answered):
            errors.append("public conclusion claims must cover every answered target")
    if mode == "limited" and deferred and not output.get("limitations"):
        errors.append("limited generation requires an explicit limitation")


def composite_single_target_application_target_id(input_data, claims, citations_by_claim):
    """Return the sole target that satisfies the public-application predicate."""
    if (
        input_data.get("mode") != "GENERATE_ANSWER"
        or input_data.get("generation_constraints", {}).get(
            "public_conclusion_contract"
        )
        != "required"
    ):
        return None
    answered_target_ids = input_data.get("answered_target_ids", [])
    if (
        not isinstance(answered_target_ids, list)
        or len(answered_target_ids) != 1
        or not isinstance(answered_target_ids[0], str)
    ):
        return None
    target_id = answered_target_ids[0]
    if not any(
        isinstance(target, dict)
        and target.get("answer_target_id") == target_id
        and target.get("answer_type") == "legal_conclusion"
        for target in input_data.get("answer_targets", [])
    ):
        return None
    critical_items = [
        item
        for item in input_data.get("required_evidence_items", [])
        if isinstance(item, dict)
        and item.get("critical") is True
        and isinstance(item.get("answer_target_ids"), list)
        and target_id in item["answer_target_ids"]
    ]
    if len(critical_items) != 1:
        return None
    public_legal_rules = [
        claim
        for claim in claims
        if claim.get("public_role") == "conclusion"
        and claim.get("claim_type") == "legal_rule"
        and isinstance(claim.get("answer_target_ids"), list)
        and target_id in claim["answer_target_ids"]
    ]
    if len(public_legal_rules) < 2:
        return None
    cited_rule_provision_ids = {
        citation.get("provision_id")
        for claim in public_legal_rules
        for citation in citations_by_claim.get(claim.get("claim_id"), [])
        if isinstance(citation.get("provision_id"), str)
    }
    if len(cited_rule_provision_ids) < 2:
        return None
    has_cited_public_application = any(
        claim.get("public_role") == "conclusion"
        and claim.get("claim_type") == "application"
        and isinstance(claim.get("answer_target_ids"), list)
        and target_id in claim["answer_target_ids"]
        and citations_by_claim.get(claim.get("claim_id"))
        for claim in claims
    )
    return None if has_cited_public_application else target_id


def validate_public_legal_conclusion_claims(output, input_data, citations_by_claim, errors):
    """Enforce the composite public-application and conditional-exception roles."""
    if (
        input_data.get("mode") != "GENERATE_ANSWER"
        or input_data.get("generation_constraints", {}).get(
            "public_conclusion_contract"
        )
        != "required"
    ):
        return
    claims = [claim for claim in output.get("claims", []) if isinstance(claim, dict)]
    missing_application_target_id = composite_single_target_application_target_id(
        input_data, claims, citations_by_claim
    )
    if missing_application_target_id is not None:
        errors.append(
            "legal-conclusion answer target lacks a public application claim: "
            + missing_application_target_id
        )
    answered_target_ids = {
        target_id
        for target_id in input_data.get("answered_target_ids", [])
        if isinstance(target_id, str)
    }
    for claim in claims:
        target_ids = claim.get("answer_target_ids", [])
        if (
            claim.get("claim_type") == "exception"
            and claim.get("applicability") == "conditional"
            and claim.get("public_role") == "audit"
            and isinstance(target_ids, list)
            and answered_target_ids.intersection(target_ids)
            and not audit_conditional_exception_is_publicly_covered(
                claim, claims, citations_by_claim
            )
        ):
            errors.append(
                "conditional exception for answered target must be a public conclusion: "
                + str(claim.get("claim_id"))
            )


_CASE_FACT_ANCHOR_STOPWORDS = frozenset({
    "관련", "관한", "대한", "위한", "해당", "경우", "여부", "필요", "기준",
    "요건", "조건", "법적", "법률", "규정", "조항", "적용", "판단", "인정",
    "확인", "검토", "효과", "사안", "사실", "인한", "따른", "있는", "없는",
    "그리고", "또는", "등", "수", "것", "중", "내", "및", "와", "과",
})
_CASE_FACT_ANCHOR_PARTICLE_SUFFIXES = (
    "으로", "에서", "에게", "까지", "부터", "처럼", "보다", "으로서",
    "으로써", "에게서", "이라면", "이라도", "이라서", "은", "는", "이",
    "가", "을", "를", "의", "에", "로", "도", "만", "와", "과",
)
_CASE_FACT_ANCHOR_CONTEXT_HEADS = frozenset({
    "기관", "법원", "회사", "사업장", "근로자", "사람", "당사자", "절차",
})
_CASE_FACT_ANCHOR_OUTPUT_DESCRIPTOR_HEADS = frozenset({
    "종류", "유형", "명칭", "내용", "여부",
})
_KOREAN_DESCRIPTIVE_MODIFIER_SUFFIXES = (
    "하는", "되는", "받은", "발생한", "입은", "따른", "있는", "없는", "한",
)


def _korean_case_fact_anchor_phrases(value):
    """Return one conservative particle-normalized Korean case-fact anchor."""
    if not isinstance(value, str) or re.search(r"[A-Za-z0-9]", value):
        return set()
    words = re.findall(r"[가-힣]+", unicodedata.normalize("NFKC", value))
    candidates = set()
    for left, right in zip(words, words[1:]):
        normalized_words = []
        right_had_particle = False
        for index, word in enumerate((left, right)):
            normalized = word
            for suffix in _CASE_FACT_ANCHOR_PARTICLE_SUFFIXES:
                if normalized.endswith(suffix) and len(normalized) - len(suffix) >= 2:
                    normalized = normalized[:-len(suffix)]
                    if index == 1:
                        right_had_particle = True
                    break
            normalized_words.append(normalized)
        if (
            right_had_particle
            and all(
                word not in _CASE_FACT_ANCHOR_STOPWORDS and len(word) >= 2
                for word in normalized_words
            )
            and normalized_words[1] not in _CASE_FACT_ANCHOR_CONTEXT_HEADS
            and normalized_words[1] not in _CASE_FACT_ANCHOR_OUTPUT_DESCRIPTOR_HEADS
            and not normalized_words[0].endswith(
                _KOREAN_DESCRIPTIVE_MODIFIER_SUFFIXES
            )
        ):
            candidates.add(" ".join(normalized_words))
    return {sorted(candidates)[-1]} if candidates else set()


def redundant_public_rule_application_case_fact_anchor_failures(
    output, input_data, citations_by_claim
):
    """Find the narrow pre-demotion case-fact preservation failures.

    Only the C33 exact public rule/application projection can reach this
    predicate. It exposes literal requested-output phrases for a retry but
    never invents their legal treatment or changes a claim.
    """
    if (
        input_data.get("mode") != "GENERATE_ANSWER"
        or input_data.get("generation_constraints", {}).get(
            "public_conclusion_contract"
        ) != "required"
    ):
        return []
    answered_target_ids = [
        target_id for target_id in input_data.get("answered_target_ids", [])
        if isinstance(target_id, str)
    ]
    if len(answered_target_ids) != 1:
        return []
    target_id = answered_target_ids[0]
    target = next(
        (
            item for item in input_data.get("answer_targets", [])
            if isinstance(item, dict) and item.get("answer_target_id") == target_id
        ),
        None,
    )
    if not isinstance(target, dict) or target.get("answer_type") != "legal_conclusion":
        return []
    anchors = _korean_case_fact_anchor_phrases(target.get("requested_output"))
    if not anchors:
        return []
    core_ids = {
        item.get("provision_id")
        for item in input_data.get("core_accepted_provisions", [])
        if isinstance(item, dict) and isinstance(item.get("provision_id"), str)
    }
    if not core_ids:
        return []
    claims = [claim for claim in output.get("claims", []) if isinstance(claim, dict)]

    def target_ids(claim):
        values = claim.get("answer_target_ids")
        return {value for value in values if isinstance(value, str)} if isinstance(values, list) else set()

    def provision_ids(claim):
        return {
            citation.get("provision_id")
            for citation in citations_by_claim.get(claim.get("claim_id"), [])
            if isinstance(citation, dict) and isinstance(citation.get("provision_id"), str)
        }

    applications = [
        claim for claim in claims
        if claim.get("public_role") == "conclusion"
        and claim.get("claim_type") == "application"
        and target_ids(claim) == {target_id}
    ]
    failures = []
    for rule in claims:
        rule_provisions = provision_ids(rule)
        if (
            rule.get("public_role") != "conclusion"
            or rule.get("claim_type") != "legal_rule"
            or rule.get("applicability") != "direct"
            or target_ids(rule) != {target_id}
            or not rule_provisions
            or not rule_provisions.issubset(core_ids)
        ):
            continue
        for application in applications:
            if provision_ids(application) != rule_provisions:
                continue
            rule_text = normalized_claim_text(rule.get("text"))
            application_text = normalized_claim_text(application.get("text"))
            missing = sorted(
                anchor for anchor in anchors
                if anchor not in rule_text and anchor not in application_text
            )
            if missing:
                failures.append({
                    "answer_target_id": target_id,
                    "legal_rule_claim_id": rule.get("claim_id"),
                    "application_claim_id": application.get("claim_id"),
                    "missing_anchors": missing,
                })
    return failures


def normalized_claim_text(value):
    """Normalize text only for literal conditional-exception coverage checks."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).casefold()).strip()


def audit_conditional_exception_is_publicly_covered(
    audit_exception, claims, citations_by_claim
):
    """Require normalized full-text containment and complete public coverage.

    A conditional exception left as audit is safe only when one public
    conclusion contains its text and every one of its targets and cited
    provisions. This deliberately avoids semantic inference: paraphrase,
    partial target coverage, or partial provision coverage fails closed.
    """
    exception_id = audit_exception.get("claim_id")
    exception_text = normalized_claim_text(audit_exception.get("text"))
    exception_targets = {
        target_id
        for target_id in audit_exception.get("answer_target_ids", [])
        if isinstance(target_id, str)
    }
    exception_provisions = {
        citation.get("provision_id")
        for citation in citations_by_claim.get(exception_id, [])
        if isinstance(citation, dict) and isinstance(citation.get("provision_id"), str)
    }
    if not exception_text or not exception_targets or not exception_provisions:
        return False
    for public_claim in claims:
        if public_claim.get("public_role") != "conclusion":
            continue
        public_id = public_claim.get("claim_id")
        public_text = normalized_claim_text(public_claim.get("text"))
        public_targets = {
            target_id
            for target_id in public_claim.get("answer_target_ids", [])
            if isinstance(target_id, str)
        }
        public_provisions = {
            citation.get("provision_id")
            for citation in citations_by_claim.get(public_id, [])
            if isinstance(citation, dict) and isinstance(citation.get("provision_id"), str)
        }
        if (
            exception_text in public_text
            and exception_targets.issubset(public_targets)
            and exception_provisions.issubset(public_provisions)
        ):
            return True
    return False


_C32_CARRY_FORWARD_CONTEXT_KEY = "_harness_c32_conditional_exception_carry_forward_obligations"
_C39_QUALIFYING_PUBLIC_EXCEPTION_CONTEXT_KEY = (
    "_harness_c39_qualifying_public_exception_links"
)


def qualifying_public_exception_citation_is_authorized(
    claim, provision_id, input_data
):
    """Authorize the C38 public conditional-exception exception structurally."""
    def provision_ids(key):
        provisions = input_data.get(key)
        if not isinstance(provisions, list) or not all(
            isinstance(item, dict)
            and isinstance(item.get("provision_id"), str)
            and item["provision_id"]
            for item in provisions
        ):
            return []
        return [item["provision_id"] for item in provisions]

    return shared_qualifying_public_exception_citation_is_authorized(
        claim,
        provision_id,
        input_data.get("answered_target_ids"),
        input_data.get("required_evidence_items"),
        provision_ids("accepted_provisions"),
        provision_ids("qualifying_provisions"),
        input_data.get(_C39_QUALIFYING_PUBLIC_EXCEPTION_CONTEXT_KEY),
    )


def qualifying_carry_forward_citation_is_authorized(
    claim, provision_id, input_data, citations_by_claim
):
    """Allow one qualifying citation only for a frozen retry obligation.

    This is deliberately a structural, literal check. The context is added
    only by the local executor after its first rejected S3 attempt; ordinary
    and standalone validation therefore retain the core-only boundary.
    """
    obligations = input_data.get(_C32_CARRY_FORWARD_CONTEXT_KEY)
    qualifying_ids = {
        item.get("provision_id")
        for item in input_data.get("qualifying_provisions", [])
        if isinstance(item, dict) and isinstance(item.get("provision_id"), str)
    }
    if not isinstance(obligations, list) or provision_id not in qualifying_ids:
        return False
    if not isinstance(claim, dict) or claim.get("public_role") != "conclusion":
        return False
    public_text = normalized_claim_text(claim.get("text"))
    public_targets = {
        target_id for target_id in claim.get("answer_target_ids", [])
        if isinstance(target_id, str)
    }
    public_provisions = {
        citation.get("provision_id")
        for citation in citations_by_claim.get(claim.get("claim_id"), [])
        if isinstance(citation, dict) and isinstance(citation.get("provision_id"), str)
    }
    for obligation in obligations:
        if not isinstance(obligation, dict):
            continue
        normalized_text = obligation.get("normalized_text")
        target_ids = obligation.get("answer_target_ids")
        provision_ids = obligation.get("provision_ids")
        if (
            not isinstance(normalized_text, str)
            or not normalized_text
            or not isinstance(target_ids, list)
            or not target_ids
            or not isinstance(provision_ids, list)
            or not provision_ids
            or not all(isinstance(value, str) and value for value in target_ids)
            or not all(isinstance(value, str) and value for value in provision_ids)
        ):
            continue
        required_targets = set(target_ids)
        required_provisions = set(provision_ids)
        if (
            provision_id in required_provisions
            and normalized_text in public_text
            and required_targets.issubset(public_targets)
            and required_provisions.issubset(public_provisions)
        ):
            return True
    return False


def validate(output, input_data):
    errors = []
    if output.get("schema_version") != "1.0" or output.get("skill_id") != "S3":
        errors.append("schema_version/skill_id must be 1.0/S3")
    allowed_modes = {"GENERATE_ANSWER", "GENERATE_BENCHMARK_CANDIDATE"}
    if input_data is not None:
        if output.get("mode") != input_data.get("mode"):
            errors.append("mode must match input")
    elif output.get("mode") not in allowed_modes:
        errors.append("mode must be a supported S3 entry point")
    if output.get("status") not in {"ok", "error"}:
        errors.append("status must be ok or error")
    if input_data and output.get("run_id") != input_data.get("run_id"):
        errors.append("run_id does not match input")
    forbidden = {"policy_action", "action", "abstention_reason", "citation_check_result", "PASS"}
    present = sorted(forbidden.intersection(output))
    if present:
        errors.append(f"harness/tool-owned fields are forbidden: {present}")
    if output.get("status") == "error":
        error = output.get("error")
        allowed = {"INVALID_INPUT", "GENERATION_NOT_AUTHORIZED", "UNCOVERED_CRITICAL_EVIDENCE", "CONTRACT_UNSATISFIABLE"}
        if not isinstance(error, dict) or error.get("code") not in allowed:
            errors.append("invalid error envelope")
        return errors
    if not input_data:
        errors.append("success validation requires --input")
        return errors
    validate_preconditions(input_data, errors)
    validate_answer_target_scope(output, input_data, errors)

    answer = output.get("answer", "")
    max_chars = input_data.get("generation_constraints", {}).get("max_answer_chars")
    effective_max_chars = min(max_chars, 800) if isinstance(max_chars, int) else 800
    if len(answer) > effective_max_chars:
        errors.append(
            f"answer exceeds max_answer_chars: {len(answer)} > {effective_max_chars}"
        )
    answer_lines = [line.strip() for line in answer.splitlines() if line.strip()]
    if not 1 <= len(answer_lines) <= 4:
        errors.append("public answer must contain 1 to 4 short lines")
    if any(
        line.startswith(("전제:", "한계:")) for line in answer_lines
    ):
        errors.append("public answer must not append audit assumptions or limitations")
    if "claims" not in output or "claim_citations" not in output:
        errors.append("success output requires claims and claim_citations arrays")
    claims = output.get("claims", [])
    citations = output.get("claim_citations", [])
    benchmark_question_only = (
        input_data.get("mode") == "GENERATE_BENCHMARK_CANDIDATE"
        and input_data.get("candidate_answer_basis") == "question_only"
    )
    if not benchmark_question_only and (not claims or not citations):
        errors.append("grounded generation requires claims and claim_citations")
    claim_ids = unique(claims, "claim_id", r"C[1-9][0-9]*", errors)
    unique(citations, "citation_id", r"CT[1-9][0-9]*", errors)
    claim_by_id = {x.get("claim_id"): x for x in claims}
    source_key = (
        "candidate_provisions"
        if input_data.get("mode") == "GENERATE_BENCHMARK_CANDIDATE"
        else "accepted_provisions"
    )
    sources = input_data.get(source_key, [])
    accepted_by_id = {x.get("provision_id"): x for x in sources}
    if len(accepted_by_id) != len(sources):
        errors.append("source provision IDs must be unique")
    core_sources = input_data.get("core_accepted_provisions", sources)
    core_ids = {
        source.get("provision_id")
        for source in core_sources
        if isinstance(source, dict)
    }

    citations_by_claim = {}
    for citation in citations:
        citations_by_claim.setdefault(citation.get("claim_id"), []).append(citation)
    for citation in citations:
        citation_id = citation.get("citation_id")
        claim_id = citation.get("claim_id")
        provision_id = citation.get("provision_id")
        if claim_id not in claim_ids:
            errors.append(f"citation references unknown claim: {citation_id}")
        provision = accepted_by_id.get(provision_id)
        if not provision:
            errors.append(f"citation uses non-accepted provision: {citation_id}")
        else:
            quote = citation.get("quoted_text")
            if not isinstance(quote, str) or quote not in provision.get("text", ""):
                errors.append(f"quoted_text is not exact accepted source text: {citation_id}")
        marker = citation.get("answer_marker")
        expected_marker = f"[{citation_id}]"
        if marker != expected_marker:
            errors.append(f"answer_marker must be {expected_marker}: {citation_id}")
        claim = claim_by_id.get(claim_id)
        if (
            input_data.get("mode") == "GENERATE_ANSWER"
            and isinstance(claim, dict)
            and claim.get("public_role", "conclusion") == "conclusion"
            and provision_id not in core_ids
            and not qualifying_public_exception_citation_is_authorized(
                claim, provision_id, input_data
            )
            and not qualifying_carry_forward_citation_is_authorized(
                claim, provision_id, input_data, citations_by_claim
            )
        ):
            errors.append(
                f"public conclusion may cite only core accepted provision: {citation_id}"
            )

    for claim_id, claim in claim_by_id.items():
        if claim.get("citation_required") is not True:
            errors.append(f"every claims[] item must require citation: {claim_id}")
        if not citations_by_claim.get(claim_id):
            errors.append(f"claim lacks citation: {claim_id}")
    for claim_id in citations_by_claim:
        if claim_id not in claim_by_id:
            errors.append(f"citations contain unknown claim: {claim_id}")

    validate_public_legal_conclusion_claims(
        output, input_data, citations_by_claim, errors
    )
    for failure in redundant_public_rule_application_case_fact_anchor_failures(
        output, input_data, citations_by_claim
    ):
        errors.append(
            "public application lacks requested-output case-fact anchors before "
            "redundant-rule demotion: answer_target_id=%s; "
            "application_claim_id=%s; missing_anchors=%s"
            % (
                failure["answer_target_id"],
                failure["application_claim_id"],
                ", ".join(failure["missing_anchors"]),
            )
        )

    if not benchmark_question_only:
        expected_lines = [
            "%s%s"
            % (
                claim.get("text", ""),
                "".join(
                    citation.get("answer_marker", "")
                    for citation in citations_by_claim.get(claim.get("claim_id"), [])
                ),
            )
            for claim in public_claims(
                claims,
                input_data.get("answered_target_ids", []),
                input_data.get("generation_constraints", {}).get("public_conclusion_contract") == "required",
            )
        ]
        expected_answer = "\n".join(expected_lines)
        if answer != expected_answer:
            errors.append("public answer does not match deterministic concise serialization")

    statuses = {
        item.get("evidence_item_id"): item.get("status")
        for item in input_data.get("coverage_assessments", [])
    }
    partial_critical = {
        item.get("evidence_item_id")
        for item in input_data.get("required_evidence_items", [])
        if item.get("critical") is True
        and statuses.get(item.get("evidence_item_id")) == "partially_covered"
    }
    if partial_critical and input_data.get("mode") != "GENERATE_BENCHMARK_CANDIDATE":
        if not any(claim.get("applicability") == "conditional" for claim in claims):
            errors.append("conditional generation requires at least one conditional claim")
        if not output.get("limitations"):
            errors.append("conditional generation requires an explicit limitation")
    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate S3 output semantics")
    parser.add_argument("output")
    parser.add_argument("--input")
    args = parser.parse_args()
    try:
        output = load(args.output)
        input_data = load(args.input) if args.input else None
        errors = validate(output, input_data)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(f"INVALID: {error}", file=sys.stderr)
        return 1
    print("VALID: S3 output contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
