#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path


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
    supported = {
        evidence_id
        for provision in input_data.get("accepted_provisions", [])
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
    if not input_data.get("accepted_provisions"):
        errors.append("accepted_provisions must not be empty")


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
        if not 1 <= len(public) <= 3:
            errors.append("public conclusion contract requires 1 to 3 conclusion claims")
        public_targets = {target_id for claim in public for target_id in claim.get("answer_target_ids", [])}
        if public_targets != set(answered):
            errors.append("public conclusion claims must cover every answered target")
    if mode == "limited" and deferred and not output.get("limitations"):
        errors.append("limited generation requires an explicit limitation")


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
    if not 1 <= len(answer_lines) <= 3:
        errors.append("public answer must contain 1 to 3 short lines")
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

    citations_by_claim = {}
    for citation in citations:
        citation_id = citation.get("citation_id")
        claim_id = citation.get("claim_id")
        provision_id = citation.get("provision_id")
        citations_by_claim.setdefault(claim_id, []).append(citation)
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

    for claim_id, claim in claim_by_id.items():
        if claim.get("citation_required") is not True:
            errors.append(f"every claims[] item must require citation: {claim_id}")
        if not citations_by_claim.get(claim_id):
            errors.append(f"claim lacks citation: {claim_id}")
    for claim_id in citations_by_claim:
        if claim_id not in claim_by_id:
            errors.append(f"citations contain unknown claim: {claim_id}")

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
