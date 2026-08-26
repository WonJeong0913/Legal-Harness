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


AXIS_PROJECTIONS = {
    ("covered", "direct", "none"): "covered",
    ("covered", "conditional", "missing_fact"): "partially_covered",
    ("partially_covered", "not_assessed", "missing_statute"): "partially_covered",
    ("uncovered", "not_assessed", "missing_statute"): "uncovered",
    ("conflicting", "not_assessed", "conflict"): "conflicting",
}
SCOPE_EXCESS_TUPLE = ("uncovered", "not_assessed", "scope_excess")


def effective_status(assessment, evidence, errors):
    legacy = assessment.get("status", assessment.get("evidence_status"))
    axes = ("legal_status", "applicability_status", "gap_type")
    has_axes = any(key in assessment for key in axes)
    if not has_axes:
        return legacy
    if not all(key in assessment for key in axes):
        errors.append("coverage axes must be supplied together")
        return legacy
    legal = assessment.get("legal_status")
    applicability = assessment.get("applicability_status")
    gap_type = assessment.get("gap_type")
    if legal not in {"covered", "partially_covered", "uncovered", "conflicting"}:
        errors.append("invalid legal_status")
    if applicability not in {"direct", "conditional", "not_assessed"}:
        errors.append("invalid applicability_status")
    if gap_type not in {"none", "missing_statute", "missing_fact", "scope_excess", "conflict"}:
        errors.append("invalid gap_type")
    axis_tuple = (legal, applicability, gap_type)
    derived = AXIS_PROJECTIONS.get(axis_tuple)
    if derived is None:
        if axis_tuple == SCOPE_EXCESS_TUPLE and evidence.get("critical") is False:
            derived = "uncovered"
        else:
            errors.append("coverage axes are not an allowed tuple for this evidence item")
            derived = legal
    if legacy is not None and legacy != derived:
        errors.append("legacy status conflicts with coverage axes")
    return derived


def _scope_text(value):
    return value if isinstance(value, str) else ""


def _normalize_scope_text(value):
    return " ".join(_scope_text(value).split())


def _article_identity(provision):
    for field in ("article_label", "statute_name"):
        match = re.search(
            r"(?P<statute>[가-힣A-Za-z][가-힣A-Za-z0-9·ㆍ\- ]*?(?:법률|법|시행령|시행규칙))\s*제?\s*(?P<article>[0-9]+)\s*조",
            _scope_text(provision.get(field)),
        )
        if match:
            return (_normalize_scope_text(match.group("statute")), int(match.group("article")))
    return None


def _explicit_same_law_ranges(provision):
    identity = _article_identity(provision)
    own_statute = identity[0] if identity else None
    ranges = []
    for match in re.finditer(
        r"(?:(?P<statute>[가-힣A-Za-z][가-힣A-Za-z0-9·ㆍ\- ]*?(?:법률|법|시행령|시행규칙))\s*)?제\s*(?P<start>[0-9]+)\s*조\s*(?:부터|내지)\s*제\s*(?P<end>[0-9]+)\s*조(?:까지)?",
        _scope_text(provision.get("text")),
    ):
        statute = _normalize_scope_text(match.group("statute")) if match.group("statute") else own_statute
        start, end = int(match.group("start")), int(match.group("end"))
        if statute and statute == own_statute and start <= end:
            ranges.append((statute, start, end))
    return ranges


def _explicit_subtypes(provision):
    subtypes = []
    for match in re.finditer(
        r"(?P<base>[가-힣][가-힣0-9·ㆍ\-]{0,40})\s*\(\s*(?P<subtype>[가-힣][가-힣0-9·ㆍ\-]{0,20})\s*\)",
        _scope_text(provision.get("text")),
    ):
        base = match.group("base")
        if re.fullmatch(r"제\s*[0-9]+\s*조(?:의\s*[0-9]+)?", base):
            continue
        subtypes.append((base, match.group("subtype")))
    return subtypes

def _unsafe_direct_or_satisfied(assessment, provision_id):
    violations = []
    if (
        assessment.get("applicability_status") == "direct"
        and provision_id in assessment.get("linked_provision_ids", [])
    ):
        violations.append("direct")
    for result in assessment.get("criterion_results", []):
        if (
            isinstance(result, dict)
            and result.get("status") == "satisfied"
            and provision_id in result.get("linked_provision_ids", [])
        ):
            violations.append("satisfied:%s" % result.get("requirement_id"))
    return violations


DIRECT_ENTAILMENT_COMPONENTS = (
    "regulated_subject_or_act",
    "outcome_changing_qualifiers",
    "legal_effect",
    "procedure_or_remedy_path",
)
DIRECT_ENTAILMENT_STATUSES = {"matched", "mismatch", "not_applicable"}


def _declared_direct_entailment_mismatches(output, input_data):
    """Expose model-declared atomic scope failures as validation errors.

    Korean legal entailment cannot be reduced safely to a fixed lexical
    dictionary. The contract therefore requires an explicit component-wise
    judgment from S2 for each direct satisfied criterion and makes a declared
    mismatch non-overridable by a `direct` label.
    """
    if not isinstance(output, dict) or not isinstance(input_data, dict):
        return []
    assessments = {
        item.get("evidence_item_id"): item
        for item in output.get("coverage_assessments", [])
        if isinstance(item, dict)
    }
    mismatches = []
    for evidence_id, assessment in assessments.items():
        if assessment.get("applicability_status") != "direct":
            continue
        for result in assessment.get("criterion_results", []):
            if not isinstance(result, dict) or result.get("status") != "satisfied":
                continue
            requirement_id = result.get("requirement_id")
            check = result.get("direct_entailment")
            provision_ids = [
                provision_id
                for provision_id in result.get("linked_provision_ids", [])
                if isinstance(provision_id, str)
            ]
            if not isinstance(check, dict):
                mismatches.append({
                    "kind": "missing_direct_entailment_check",
                    "evidence_item_id": evidence_id,
                    "requirement_id": requirement_id,
                    "provision_ids": provision_ids,
                    "components": list(DIRECT_ENTAILMENT_COMPONENTS),
                })
                continue
            invalid = [
                component
                for component in DIRECT_ENTAILMENT_COMPONENTS
                if check.get(component) not in DIRECT_ENTAILMENT_STATUSES
            ]
            if not isinstance(check.get("rationale"), str) or not check["rationale"].strip():
                invalid.append("rationale")
            if invalid:
                mismatches.append({
                    "kind": "invalid_direct_entailment_check",
                    "evidence_item_id": evidence_id,
                    "requirement_id": requirement_id,
                    "provision_ids": provision_ids,
                    "components": invalid,
                })
                continue
            mismatched = [
                component
                for component in DIRECT_ENTAILMENT_COMPONENTS
                if check.get(component) == "mismatch"
            ]
            if mismatched:
                mismatches.append({
                    "kind": "declared_direct_entailment_mismatch",
                    "evidence_item_id": evidence_id,
                    "requirement_id": requirement_id,
                    "provision_ids": provision_ids,
                    "components": mismatched,
                })
    return mismatches


def semantic_scope_mismatches(output, input_data):
    """Return narrow, text-backed direct-entailment scope mismatches."""
    if not isinstance(output, dict) or not isinstance(input_data, dict):
        return []
    evidence_by_id = {
        item.get("evidence_item_id"): item
        for item in input_data.get("required_evidence_items", [])
        if isinstance(item, dict)
    }
    provision_by_id = {
        item.get("provision_id"): item
        for item in input_data.get("candidate_provisions", [])
        if isinstance(item, dict)
    }
    assessments = {
        item.get("evidence_item_id"): item
        for item in output.get("coverage_assessments", [])
        if isinstance(item, dict)
    }
    supports = {}
    for link in output.get("evidence_links", []):
        if (
            isinstance(link, dict)
            and link.get("relation") == "supports"
            and link.get("role", "CORE") == "CORE"
        ):
            supports.setdefault(link.get("evidence_item_id"), set()).add(link.get("provision_id"))
    targets = {
        evidence_id: set(item.get("answer_target_ids", []))
        for evidence_id, item in evidence_by_id.items()
        if isinstance(item.get("answer_target_ids"), list)
    }
    mismatches, seen = [], set()

    def add(kind, evidence_id, provision_id, violations, **details):
        key = (kind, evidence_id, provision_id, tuple(violations), tuple(sorted(details.items())))
        if violations and key not in seen:
            seen.add(key)
            mismatches.append({
                "kind": kind,
                "evidence_item_id": evidence_id,
                "provision_id": provision_id,
                "violations": violations,
                **details,
            })

    for evidence_id, assessment in assessments.items():
        evidence = evidence_by_id.get(evidence_id)
        if not evidence:
            continue
        for provision_id in supports.get(evidence_id, set()):
            provision = provision_by_id.get(provision_id)
            if not provision:
                continue
            violations = _unsafe_direct_or_satisfied(assessment, provision_id)
            for statute, start, end in _explicit_same_law_ranges(provision):
                for other_id, other_assessment in assessments.items():
                    if other_id == evidence_id or not targets.get(evidence_id, set()).intersection(targets.get(other_id, set())):
                        continue
                    if other_assessment.get("applicability_status") != "direct":
                        continue
                    for root_id in supports.get(other_id, set()):
                        root = provision_by_id.get(root_id)
                        root_identity = _article_identity(root) if root else None
                        if root_identity and root_identity[0] == statute and not start <= root_identity[1] <= end:
                            add(
                                "cross_reference_range_excludes_shared_target_root",
                                evidence_id,
                                provision_id,
                                violations,
                                root_provision_id=root_id,
                                range_start=start,
                                range_end=end,
                            )
            scope = " ".join(
                [_scope_text(input_data.get("normalized_question"))]
                + [
                    _scope_text(requirement.get("text"))
                    for requirement in evidence.get("completion_requirements", [])
                    if isinstance(requirement, dict)
                ]
            )
            for base, subtype in _explicit_subtypes(provision):
                if base in scope and subtype not in scope:
                    add(
                        "general_entity_uses_explicit_special_subtype",
                        evidence_id,
                        provision_id,
                        violations,
                        base_entity=base,
                        special_subtype=subtype,
                    )
    mismatches.extend(_declared_direct_entailment_mismatches(output, input_data))
    return mismatches

def validate(output, input_data):
    errors = []
    if output.get("schema_version") != "1.0" or output.get("skill_id") != "S2":
        errors.append("schema_version/skill_id must be 1.0/S2")
    if output.get("mode") != "ASSESS_COVERAGE":
        errors.append("mode must be ASSESS_COVERAGE")
    if output.get("status") not in {"ok", "error"}:
        errors.append("status must be ok or error")
    if input_data:
        if output.get("run_id") != input_data.get("run_id"):
            errors.append("run_id does not match input")
        if input_data.get("mode") != "ASSESS_COVERAGE":
            errors.append("input mode must be ASSESS_COVERAGE")
    forbidden = {"accepted_provision_ids", "policy_action", "action", "answer", "claim_citations"}
    present = sorted(forbidden.intersection(output))
    if present:
        errors.append(f"harness/S3-owned fields are forbidden: {present}")
    if output.get("status") == "error":
        error = output.get("error")
        if not isinstance(error, dict) or error.get("code") not in {"INVALID_INPUT", "MISSING_REQUIRED_EVIDENCE", "CONTRACT_UNSATISFIABLE"}:
            errors.append("invalid error envelope")
        return errors
    if not input_data:
        errors.append("success validation requires --input")
        return errors

    evidence_items = input_data.get("required_evidence_items", [])
    evidence_by_id = {x.get("evidence_item_id"): x for x in evidence_items}
    if len(evidence_by_id) != len(evidence_items):
        errors.append("input evidence IDs must be unique")
    provisions = input_data.get("candidate_provisions", [])
    provision_by_id = {x.get("provision_id"): x for x in provisions}
    if len(provision_by_id) != len(provisions):
        errors.append("input candidate provision IDs must be unique")

    links = output.get("evidence_links", [])
    assessments = output.get("coverage_assessments", [])
    missing = output.get("missing_evidence_items", [])
    conflicts = output.get("evidence_conflicts", [])
    unique(links, "link_id", r"L[1-9][0-9]*", errors)
    assessment_ids = unique(assessments, "evidence_item_id", r"E[1-9][0-9]*", errors)
    missing_ids = unique(missing, "evidence_item_id", r"E[1-9][0-9]*", errors)
    unique(conflicts, "conflict_id", r"CF[1-9][0-9]*", errors)
    conflict_evidence_ids = [x.get("evidence_item_id") for x in conflicts]
    if len(conflict_evidence_ids) != len(set(conflict_evidence_ids)):
        errors.append("only one conflict object is allowed per evidence item")

    expected = set(evidence_by_id)
    if assessment_ids != expected:
        errors.append(f"assessments must cover every evidence item exactly once: expected {sorted(expected)}, got {sorted(assessment_ids)}")

    links_by_evidence = {}
    accepted_core_by_evidence = {}
    for link in links:
        evidence_id = link.get("evidence_item_id")
        provision_id = link.get("provision_id")
        links_by_evidence.setdefault(evidence_id, []).append(link)
        if evidence_id not in expected:
            errors.append(f"link references unknown evidence item: {evidence_id}")
        provision = provision_by_id.get(provision_id)
        if not provision:
            errors.append(f"link references unknown candidate provision: {provision_id}")
        else:
            quote = link.get("quoted_text")
            if quote != "[FULL_TEXT]" and (
                not isinstance(quote, str) or quote not in provision.get("text", "")
            ):
                errors.append(f"quoted_text is not exact source text: {link.get('link_id')}")
        if link.get("relation") not in {"supports", "partially_supports", "conflicts"}:
            errors.append(f"invalid link relation: {link.get('link_id')}")
        role = link.get("role", "CORE")
        if role not in {"CORE", "SUPPLEMENTAL", "QUALIFYING", "ALTERNATIVE"}:
            errors.append(f"invalid evidence role: {link.get('link_id')}")
            continue
        condition = link.get("condition", "")
        if not isinstance(condition, str):
            errors.append(f"evidence link condition must be a string: {link.get('link_id')}")
        elif role in {"QUALIFYING", "ALTERNATIVE"} and not condition.strip():
            errors.append(f"qualifying or alternative link requires condition: {link.get('link_id')}")
        if role == "CORE" and link.get("relation") in {"supports", "partially_supports"}:
            accepted_core_by_evidence.setdefault(evidence_id, set()).add(provision_id)

    conflict_id_set = set(conflict_evidence_ids)
    assessment_by_id = {x.get("evidence_item_id"): x for x in assessments}
    effective_status_by_id = {}
    for evidence_id, assessment in assessment_by_id.items():
        status = effective_status(
            assessment,
            evidence_by_id.get(evidence_id, {}),
            errors,
        )
        effective_status_by_id[evidence_id] = status
        linked = assessment.get("linked_provision_ids", [])
        actual_linked = accepted_core_by_evidence.get(evidence_id, set())
        if len(linked) != len(set(linked)):
            errors.append(f"linked_provision_ids must be unique: {evidence_id}")
        if set(linked) != actual_linked:
            errors.append(f"assessment/core-link provision mismatch: {evidence_id}")
        if set(linked) - set(provision_by_id):
            errors.append(f"assessment uses non-candidate provision: {evidence_id}")
        satisfied = assessment.get("satisfied_aspects", [])
        missing_aspects = assessment.get("missing_aspects", [])
        partial_kind = assessment.get("partial_kind")
        if status == "partially_covered":
            if partial_kind not in {"factual_condition", "legal_support_gap"}:
                errors.append(f"partially_covered requires a valid partial_kind: {evidence_id}")
        elif partial_kind != "not_applicable":
            errors.append(f"non-partial status requires partial_kind=not_applicable: {evidence_id}")
        if status == "covered":
            if not linked or missing_aspects or evidence_id in conflict_id_set:
                errors.append(f"covered consistency failure: {evidence_id}")
        elif status == "partially_covered":
            if not linked or not missing_aspects or evidence_id in conflict_id_set:
                errors.append(f"partially_covered consistency failure: {evidence_id}")
        elif status == "uncovered":
            if linked or satisfied or not missing_aspects or evidence_id in conflict_id_set:
                errors.append(f"uncovered consistency failure: {evidence_id}")
        elif status == "conflicting":
            if not linked or evidence_id not in conflict_id_set:
                errors.append(f"conflicting consistency failure: {evidence_id}")
        else:
            errors.append(f"invalid coverage status: {evidence_id}")

        legal_status = assessment.get("legal_status")
        governing = assessment.get("governing_legal_regime")
        if governing is not None and governing not in {
            "direct_entailment",
            "not_direct_entailment",
            "not_assessed",
        }:
            errors.append(f"invalid governing_legal_regime: {evidence_id}")
        effective_legal_status = legal_status or status
        effective_governing = governing or (
            "direct_entailment"
            if effective_legal_status == "covered"
            else "not_direct_entailment"
        )
        if (
            effective_legal_status == "covered"
            and effective_governing != "direct_entailment"
        ):
            errors.append(f"covered legal status requires direct governing regime: {evidence_id}")
        if (
            effective_governing == "direct_entailment"
            and effective_legal_status != "covered"
        ):
            errors.append(f"direct governing regime requires covered legal status: {evidence_id}")

        evidence = evidence_by_id.get(evidence_id, {})
        requirements = evidence.get("completion_requirements", [])
        criterion_results = assessment.get("criterion_results")
        if requirements and not all(
            key in assessment
            for key in ("legal_status", "applicability_status", "gap_type")
        ):
            errors.append(f"atomic requirements require coverage axes: {evidence_id}")
        if requirements and criterion_results is None:
            errors.append(f"atomic requirements require criterion_results: {evidence_id}")
        if criterion_results is not None:
            if not isinstance(criterion_results, list):
                errors.append(f"criterion_results must be a list: {evidence_id}")
            else:
                criterion_id_list = [
                    result.get("requirement_id")
                    for result in criterion_results
                    if isinstance(result, dict)
                ]
                criterion_ids = {
                    result.get("requirement_id")
                    for result in criterion_results
                    if isinstance(result, dict)
                }
                required_ids = {
                    requirement.get("requirement_id")
                    for requirement in requirements
                    if isinstance(requirement, dict)
                }
                if criterion_ids != required_ids:
                    errors.append(f"criterion results must match completion requirements: {evidence_id}")
                if len(criterion_id_list) != len(criterion_ids):
                    errors.append(f"criterion requirements must appear exactly once: {evidence_id}")
                for result in criterion_results:
                    if not isinstance(result, dict) or result.get("status") not in {"satisfied", "partially_satisfied", "unsatisfied", "conflicting"}:
                        errors.append(f"invalid criterion result: {evidence_id}")
                        continue
                    result_links = result.get("linked_provision_ids", [])
                    if not isinstance(result_links, list) or set(result_links) - actual_linked:
                        errors.append(f"criterion may use only accepted CORE provisions: {evidence_id}")
                    if result.get("status") == "satisfied" and not result_links:
                        errors.append(f"satisfied criterion requires accepted CORE evidence: {evidence_id}")
        if any(key in assessment for key in ("legal_status", "applicability_status", "gap_type")) and requirements:
            if set(missing_aspects) - {
                requirement.get("requirement_id")
                for requirement in requirements
                if isinstance(requirement, dict)
            }:
                errors.append(f"missing_aspects must reference requirement IDs: {evidence_id}")

    expected_missing = {
        eid for eid, assessment in assessment_by_id.items()
        if effective_status_by_id.get(eid) != "covered"
    }
    if missing_ids != expected_missing:
        errors.append("missing_evidence_items must equal all non-covered assessments")
    expected_conflicts = {
        eid for eid, assessment in assessment_by_id.items()
        if effective_status_by_id.get(eid) == "conflicting"
    }
    if conflict_id_set != expected_conflicts:
        errors.append("evidence_conflicts must equal all conflicting assessments")
    for item in missing:
        evidence = evidence_by_id.get(item.get("evidence_item_id"), {})
        if item.get("issue_id") != evidence.get("issue_id") or item.get("critical") != evidence.get("critical"):
            errors.append(f"missing item does not preserve issue/critical fields: {item.get('evidence_item_id')}")
    for conflict in conflicts:
        if set(conflict.get("provision_ids", [])) - set(provision_by_id):
            errors.append(f"conflict uses non-candidate provision: {conflict.get('conflict_id')}")
    for mismatch in semantic_scope_mismatches(output, input_data):
        details = ", ".join(
            "%s=%s" % (key, value)
            for key, value in mismatch.items()
            if key not in {"kind", "violations"}
        )
        errors.append(
            "semantic scope mismatch blocks direct/satisfied: %s; violations=%s; %s"
            % (mismatch.get("kind"), mismatch.get("violations"), details)
        )
    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate S2 output semantics")
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
    print("VALID: S2 output contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
