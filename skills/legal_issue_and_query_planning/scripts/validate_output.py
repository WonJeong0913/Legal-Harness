#!/usr/bin/env python3
import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path


def load(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def norm(text):
    return " ".join(unicodedata.normalize("NFKC", text).lower().split())


def answer_question_segment(text):
    normalized = norm(text)
    marker = "[질문]"
    return normalized.split(marker, 1)[1].strip() if marker in normalized else normalized


def trusted_answer_question_segment(inp):
    """Select the INITIAL_PLAN anchor source shared with runtime repair."""
    original_question = (inp or {}).get("original_question")
    if (
        isinstance(original_question, str)
        and original_question.strip()
        and "[질문]" in original_question
    ):
        return answer_question_segment(original_question)
    normalized_question = (inp or {}).get("normalized_question")
    return norm(normalized_question) if isinstance(normalized_question, str) else ""


SPECIFIC_LEGAL_EFFECT_LABELS = (
    "voidable",
    "void",
    "invalid",
    "cancellation",
    "rescission",
    "무효",
    "취소",
)
ENGLISH_SPECIFIC_LEGAL_EFFECT_LABELS = frozenset(
    label for label in SPECIFIC_LEGAL_EFFECT_LABELS if label.isascii()
)


def specific_legal_effect_labels(text):
    """Return listed effect terms without treating neutral validity wording as one."""
    if not isinstance(text, str):
        return set()
    normalized = norm(text)
    return {
        label
        for label in SPECIFIC_LEGAL_EFFECT_LABELS
        if (
            re.search(r"(?<![a-z])%s(?![a-z])" % re.escape(label), normalized)
            if label in ENGLISH_SPECIFIC_LEGAL_EFFECT_LABELS
            else label in normalized
        )
    }


def initial_plan_effect_neutrality_texts(out):
    """Yield only INITIAL_PLAN fields that can presuppose a legal effect."""
    issues = out.get("legal_issues", [])
    if isinstance(issues, list):
        for issue in issues:
            if isinstance(issue, dict):
                yield issue.get("issue_statement")
                yield issue.get("decision_question")
    evidence_items = out.get("required_evidence_items", [])
    if isinstance(evidence_items, list):
        for item in evidence_items:
            if not isinstance(item, dict):
                continue
            yield item.get("description")
            yield item.get("completion_criteria")
            yield item.get("necessity_reason")
            requirements = item.get("completion_requirements", [])
            if isinstance(requirements, list):
                for requirement in requirements:
                    if isinstance(requirement, dict):
                        yield requirement.get("text")
    requests = out.get("retrieval_requests", [])
    if isinstance(requests, list):
        for request in requests:
            if not isinstance(request, dict):
                continue
            yield request.get("query_text")
            yield request.get("rationale")
            for field in ("query_terms", "statute_hints"):
                values = request.get(field, [])
                if isinstance(values, list):
                    yield from values


def validate_initial_plan_effect_neutrality(out, inp, errors):
    """Reject effect-specific INITIAL_PLAN text not anchored in the question body."""
    question_effects = specific_legal_effect_labels(
        trusted_answer_question_segment(inp)
    )
    presupposed_effects = set()
    for text in initial_plan_effect_neutrality_texts(out):
        presupposed_effects.update(specific_legal_effect_labels(text) - question_effects)
    for label in SPECIFIC_LEGAL_EFFECT_LABELS:
        if label in presupposed_effects:
            errors.append(
                "INITIAL_PLAN presupposes specific legal effect absent from question: %s"
                % label
            )


def history_queries(data):
    values = set()
    for item in (data or {}).get("query_history", []):
        if isinstance(item, str):
            values.add(norm(item))
        elif isinstance(item, dict):
            value = item.get("normalized_query") or item.get("query_text")
            if isinstance(value, str):
                values.add(norm(value))
    return values


def unique_ids(items, key, pattern, errors):
    seen = set()
    for item in items:
        value = item.get(key)
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            errors.append(f"invalid {key}: {value!r}")
        elif value in seen:
            errors.append(f"duplicate {key}: {value}")
        seen.add(value)
    return seen


def validate_common(out, inp, errors):
    if out.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")
    if out.get("skill_id") != "S1":
        errors.append("skill_id must be S1")
    if out.get("mode") not in {"INITIAL_PLAN", "GAP_QUERY_PLAN"}:
        errors.append("invalid mode")
    if out.get("status") not in {"ok", "error"}:
        errors.append("status must be ok or error")
    if inp:
        if out.get("run_id") != inp.get("run_id"):
            errors.append("run_id does not match input")
        if out.get("mode") != inp.get("mode"):
            errors.append("mode does not match input")
    forbidden = {"accepted_provision_ids", "policy_action", "action", "coverage_assessments"}
    present = sorted(forbidden.intersection(out))
    if present:
        errors.append(f"harness/S2-owned fields are forbidden: {present}")


def validate_requests(requests, issues, evidence, prior_queries, allowed_channels, max_per_issue, errors, gap=False):
    pattern = r"GRQ-R[1-9][0-9]*-[1-9][0-9]*" if gap else r"RQ[1-9][0-9]*"
    unique_ids(requests, "request_id", pattern, errors)
    current_queries = set()
    per_issue = {}
    evidence_by_id = {item.get("evidence_item_id"): item for item in evidence}
    for request in requests:
        issue_id = request.get("issue_id")
        evidence_id = request.get("evidence_item_id")
        if issue_id not in issues:
            errors.append(f"unknown issue_id in request: {issue_id}")
        if evidence_id not in evidence_by_id:
            errors.append(f"unknown evidence_item_id in request: {evidence_id}")
        elif evidence_by_id[evidence_id].get("issue_id") != issue_id:
            errors.append(f"request issue/evidence mismatch: {request.get('request_id')}")
        channel = request.get("query_channel")
        if channel not in allowed_channels:
            errors.append(f"query channel not allowed: {channel}")
        query = request.get("query_text")
        if not isinstance(query, str) or not norm(query):
            errors.append(f"empty query_text: {request.get('request_id')}")
        else:
            normalized = norm(query)
            if normalized in current_queries:
                errors.append(f"duplicate normalized query in output: {query}")
            if normalized in prior_queries:
                errors.append(f"query repeats query_history: {query}")
            current_queries.add(normalized)
        per_issue[issue_id] = per_issue.get(issue_id, 0) + 1
        if gap and request.get("source_assessment_status") not in {"partially_covered", "uncovered", "conflicting"}:
            errors.append(f"invalid source_assessment_status: {request.get('request_id')}")
    for issue_id, count in per_issue.items():
        if count > max_per_issue:
            errors.append(f"{issue_id} has {count} requests; max is {max_per_issue}")


ARTICLE_ONLY_PATTERN = re.compile(r"제?([0-9]+)조(?:의([0-9]+))?(?:[ ]*제?([0-9]+)항)?")
STANDALONE_PARAGRAPH_PATTERN = re.compile(r"제?([0-9]+)항")
QUALIFIED_PAIR_PATTERN = re.compile(
    r"(?:「(?P<quoted>[^」]+)」|(?P<plain>[가-힣A-Za-z0-9· ]{1,60}?(?:법률|법|시행령|시행규칙)))[ ]*제?(?P<article>[0-9]+)조(?:의(?P<subarticle>[0-9]+))?(?:[ ]*제?(?P<paragraph>[0-9]+)항)?"
)

LAW_SUFFIXES = ("시행규칙", "시행령", "법률", "법")
GENERIC_STATUTE_NAMES = {"법", "법률", "시행령", "시행규칙"}

def _article_name(number, subarticle=None):
    return "제%s조%s" % (number, ("의" + subarticle) if subarticle else "")

def _paragraph_name(number):
    return "제%s항" % number if number else None

def _normalized_statute(value):
    return " ".join(value.split())

def _law_word_indices(words):
    return [
        index for index, word in enumerate(words)
        if any(word.endswith(suffix) for suffix in LAW_SUFFIXES)
    ]

def _statute_name(match, known_statutes=()):
    quoted = match.group("quoted")
    if quoted:
        return _normalized_statute(quoted), None
    plain = _normalized_statute(match.group("plain"))
    known = sorted({_normalized_statute(value) for value in known_statutes if value}, key=len, reverse=True)
    for statute in known:
        if plain == statute:
            return statute, None
        if plain.endswith(statute):
            prefix = plain[: -len(statute)]
            # A trusted statute suffix may follow descriptive prose, but it
            # must begin at a token boundary: 형법 is not a safe alias for 군형법.
            if prefix and not (prefix[-1].isalnum() or prefix[-1] == "·"):
                return statute, None
    words = plain.split()
    law_indices = _law_word_indices(words)
    if not law_indices:
        return None, plain
    # With no pre-authorized full statute name, the adjacent rightmost
    # non-generic law token is safer than arbitrary descriptive Korean prose
    # captured by the permissive reference pattern.  Known multiword names are
    # preserved by the exact/boundary-aware branch above.
    index = law_indices[-1]
    candidate = words[index]
    if (
        candidate in {"시행령", "시행규칙"}
        and index > 0
        and words[index - 1] not in {"법", "법률"}
        and words[index - 1].endswith(("법률", "법"))
    ):
        candidate = words[index - 1] + " " + candidate
    if candidate in GENERIC_STATUTE_NAMES:
        return None, plain
    return candidate, None

def _qualified_pairs(value, known_statutes=()):
    if not isinstance(value, str):
        return [], [], []
    pairs = []
    spans = []
    unresolved = []
    for match in QUALIFIED_PAIR_PATTERN.finditer(value):
        statute, unknown = _statute_name(match, known_statutes)
        spans.append(match.span())
        if unknown:
            unresolved.append(unknown)
            continue
        if not statute:
            continue
        pairs.append((
            statute,
            _article_name(match.group("article"), match.group("subarticle")),
            _paragraph_name(match.group("paragraph")),
        ))
    return pairs, spans, unresolved

def _bare_references(value, qualified_spans):
    if not isinstance(value, str):
        return []
    references = []
    for match in ARTICLE_ONLY_PATTERN.finditer(value):
        if any(match.start() < end and start < match.end() for start, end in qualified_spans):
            continue
        references.append((
            _article_name(match.group(1), match.group(2)),
            _paragraph_name(match.group(3)),
        ))
    return references

def _standalone_paragraphs(value, article_spans):
    if not isinstance(value, str):
        return []
    paragraphs = []
    for match in STANDALONE_PARAGRAPH_PATTERN.finditer(value):
        if any(match.start() < end and start < match.end() for start, end in article_spans):
            continue
        paragraphs.append(_paragraph_name(match.group(1)))
    return paragraphs

def _allowed_pairs(inp):
    source = str((inp or {}).get("original_question") or (inp or {}).get("normalized_question") or "")
    allowed, _, _ = _qualified_pairs(source)
    seen_ids = {item for item in (inp or {}).get("seen_provision_ids", []) if isinstance(item, str)}
    for reference in (inp or {}).get("candidate_cross_references", []):
        if not isinstance(reference, dict):
            continue
        source_id = reference.get("source_candidate_id")
        statute = reference.get("target_statute_name")
        article = reference.get("target_article")
        paragraph = reference.get("target_paragraph")
        excerpt = reference.get("excerpt")
        start = reference.get("start_char")
        end = reference.get("end_char")
        if (
            not isinstance(source_id, str)
            or (seen_ids and source_id not in seen_ids)
            or not isinstance(statute, str)
            or not statute.strip()
            or not isinstance(article, str)
            or not article.strip()
            or paragraph is not None and (not isinstance(paragraph, str) or not paragraph.strip())
            or not isinstance(excerpt, str)
            or not excerpt.strip()
            or not isinstance(start, int)
            or not isinstance(end, int)
            or end <= start
        ):
            continue
        allowed.append((" ".join(statute.split()), article, paragraph))
    return set(allowed)

def _pair_is_allowed(pair, allowed):
    if pair in allowed:
        return True
    statute, article, paragraph = pair
    return paragraph is None and any(
        permitted_statute == statute and permitted_article == article
        for permitted_statute, permitted_article, _ in allowed
    )

RETRIEVAL_TEXT_FIELDS = (
    "query_text",
    "first_stage_query_text",
    "rerank_query_text",
)
RETRIEVAL_LIST_FIELDS = ("query_terms", "statute_hints")


def _replace_spans(value, spans):
    repaired = value
    for start, end in sorted(set(spans), reverse=True):
        repaired = repaired[:start] + repaired[end:]
    return re.sub(r"\s+", " ", repaired).strip(" ,;:/")


def _article_span(match, value):
    start = match.start("article")
    if start > match.start() and value[start - 1:start] == "제":
        start -= 1
    return start, match.end()


def _ungrounded_standalone_paragraphs(request, allowed):
    """Return only paragraph anchors invalid in this request's final fields."""
    values = [request.get(field) for field in RETRIEVAL_TEXT_FIELDS]
    for field in RETRIEVAL_LIST_FIELDS:
        items = request.get(field)
        if isinstance(items, list):
            values.extend(items)
    explicit = set()
    standalone = []
    known_statutes = {pair[0] for pair in allowed}
    for value in values:
        pairs, _qualified_spans, _unresolved = _qualified_pairs(value, known_statutes)
        explicit.update(pairs)
        article_spans = [
            match.span() for match in ARTICLE_ONLY_PATTERN.finditer(value)
        ] if isinstance(value, str) else []
        standalone.extend(_standalone_paragraphs(value, article_spans))
    grounded_explicit = {
        pair for pair in explicit if _pair_is_allowed(pair, allowed)
    }
    invalid = set()
    for paragraph in standalone:
        bindings = {
            allowed_pair
            for allowed_pair in allowed
            if allowed_pair[2] == paragraph
            and any(
                explicit_pair[0] == allowed_pair[0]
                and explicit_pair[1] == allowed_pair[1]
                for explicit_pair in grounded_explicit
            )
        }
        if len(bindings) != 1:
            invalid.add(paragraph)
    return invalid


def _neutralize_ungrounded_standalone_paragraphs(value, paragraphs):
    if not isinstance(value, str) or not paragraphs:
        return value
    article_spans = [match.span() for match in ARTICLE_ONLY_PATTERN.finditer(value)]
    spans = [
        match.span()
        for match in STANDALONE_PARAGRAPH_PATTERN.finditer(value)
        if _paragraph_name(match.group(1)) in paragraphs
        and not any(
            match.start() < end and start < match.end()
            for start, end in article_spans
        )
    ]
    return _replace_spans(value, spans) if spans else value


def _has_retrieval_anchor(value):
    """Reject a cleanup that would leave only a legal-reference fragment."""
    if not isinstance(value, str):
        return True
    without_article = ARTICLE_ONLY_PATTERN.sub("", value)
    without_paragraph = STANDALONE_PARAGRAPH_PATTERN.sub("", without_article)
    compact_fragment = re.sub(r"[\s,;:/()\[\]{}]+", "", without_paragraph)
    if compact_fragment in {"에따른", "관련"}:
        return False
    return bool(re.search(r"[0-9A-Za-z가-힣]", without_paragraph))


def neutralize_ungrounded_article_specificity(requests, inp, *, _repair_standalone_paragraphs=True):
    """Remove only article/paragraph specificity that S1 provenance cannot authorize.

    This is a deterministic transport repair for retrieval text, not a legal
    judgment. It keeps the statute token and surrounding semantic query;
    question/candidate-cross-reference anchored pairs remain untouched.
    """
    allowed = _allowed_pairs(inp)
    repairs = []
    repaired_requests = []
    known_statutes = {pair[0] for pair in allowed}
    for original in requests:
        if not isinstance(original, dict):
            repaired_requests.append(original)
            continue
        request = dict(original)
        for field in RETRIEVAL_TEXT_FIELDS:
            value = request.get(field)
            if not isinstance(value, str):
                continue
            spans = []
            for match in QUALIFIED_PAIR_PATTERN.finditer(value):
                statute, _unknown = _statute_name(match, known_statutes)
                pair = (
                    statute,
                    _article_name(match.group("article"), match.group("subarticle")),
                    _paragraph_name(match.group("paragraph")),
                )
                if not statute or not _pair_is_allowed(pair, allowed):
                    spans.append(_article_span(match, value))
            after_qualified = _replace_spans(value, spans) if spans else value
            retained_spans = []
            for match in QUALIFIED_PAIR_PATTERN.finditer(after_qualified):
                statute, _unknown = _statute_name(match, known_statutes)
                pair = (
                    statute,
                    _article_name(match.group("article"), match.group("subarticle")),
                    _paragraph_name(match.group("paragraph")),
                )
                if statute and _pair_is_allowed(pair, allowed):
                    retained_spans.append(match.span())
            bare_spans = []
            for match in ARTICLE_ONLY_PATTERN.finditer(after_qualified):
                if any(match.start() < end and start < match.end() for start, end in retained_spans):
                    continue
                article = _article_name(match.group(1), match.group(2))
                paragraph = _paragraph_name(match.group(3))
                statutes = {
                    pair[0] for pair in allowed
                    if pair[1] == article and (paragraph is None or pair[2] == paragraph)
                }
                if len(statutes) != 1:
                    bare_spans.append(match.span())
            repaired = _replace_spans(after_qualified, bare_spans) if bare_spans else after_qualified
            if repaired != value:
                request[field] = repaired
                repairs.append({
                    "kind": "neutralized_ungrounded_article_specificity",
                    "request_id": request.get("request_id"),
                    "field": field,
                    "before": value,
                    "after": repaired,
                })
        for field in RETRIEVAL_LIST_FIELDS:
            values = request.get(field)
            if not isinstance(values, list):
                continue
            repaired_values = []
            original_repaired_pairs = []
            for value in values:
                if not isinstance(value, str):
                    repaired_values.append(value)
                    original_repaired_pairs.append((value, value))
                    continue
                temporary = {"query_text": value}
                repaired_value = neutralize_ungrounded_article_specificity(
                    [temporary], inp, _repair_standalone_paragraphs=False
                )[0][0].get("query_text", value)
                if repaired_value:
                    repaired_values.append(repaired_value)
                    original_repaired_pairs.append((value, repaired_value))
            if repaired_values != values:
                request[field] = repaired_values
                repairs.append({
                    "kind": "neutralized_ungrounded_article_specificity",
                    "request_id": request.get("request_id"),
                    "field": field,
                    "before": values,
                    "after": repaired_values,
                })
                # Neutralizing a later item can collapse it onto an earlier
                # broad statute/term. Drop only that new collision: a raw
                # duplicate must remain visible to the final harness validator.
                unique_values = []
                prior_original_norms = set()
                kept_repaired_norms = set()
                for original_value, repaired_value in original_repaired_pairs:
                    original_norm = norm(original_value) if isinstance(original_value, str) else None
                    repaired_norm = norm(repaired_value) if isinstance(repaired_value, str) else None
                    repair_induced_collision = (
                        repaired_norm is not None
                        and repaired_norm in kept_repaired_norms
                        and original_norm not in prior_original_norms
                    )
                    if not repair_induced_collision:
                        unique_values.append(repaired_value)
                        if repaired_norm is not None:
                            kept_repaired_norms.add(repaired_norm)
                    if original_norm is not None:
                        prior_original_norms.add(original_norm)
                if unique_values != repaired_values:
                    request[field] = unique_values
                    repairs.append({
                        "kind": "deduplicated_repair_induced_list_values",
                        "request_id": request.get("request_id"),
                        "field": field,
                        "before": repaired_values,
                        "after": unique_values,
                    })
        if _repair_standalone_paragraphs:
            ungrounded_paragraphs = _ungrounded_standalone_paragraphs(request, allowed)
            for field in RETRIEVAL_TEXT_FIELDS:
                value = request.get(field)
                repaired = _neutralize_ungrounded_standalone_paragraphs(
                    value, ungrounded_paragraphs
                )
                if repaired != value and _has_retrieval_anchor(repaired):
                    request[field] = repaired
                    repairs.append({
                        "kind": "neutralized_ungrounded_standalone_paragraph",
                        "request_id": request.get("request_id"),
                        "field": field,
                        "before": value,
                        "after": repaired,
                        "reason": "standalone_paragraph_lacks_request_scoped_grounded_article",
                    })
            for field in RETRIEVAL_LIST_FIELDS:
                values = request.get(field)
                if not isinstance(values, list):
                    continue
                repaired_pairs = []
                changed = False
                for value in values:
                    repaired = _neutralize_ungrounded_standalone_paragraphs(
                        value, ungrounded_paragraphs
                    )
                    changed = changed or repaired != value
                    if not isinstance(value, str) or (
                        repaired and _has_retrieval_anchor(repaired)
                    ):
                        repaired_pairs.append((value, repaired))
                repaired_values = []
                prior_original_norms = set()
                retained_repaired_norms = set()
                for original_value, repaired_value in repaired_pairs:
                    original_norm = (
                        norm(original_value) if isinstance(original_value, str) else None
                    )
                    repaired_norm = (
                        norm(repaired_value) if isinstance(repaired_value, str) else None
                    )
                    repair_induced_collision = (
                        repaired_norm is not None
                        and repaired_norm in retained_repaired_norms
                        and original_norm not in prior_original_norms
                    )
                    if not repair_induced_collision:
                        repaired_values.append(repaired_value)
                        if repaired_norm is not None:
                            retained_repaired_norms.add(repaired_norm)
                    if original_norm is not None:
                        prior_original_norms.add(original_norm)
                if (
                    changed
                    and repaired_values
                    and all(_has_retrieval_anchor(value) for value in repaired_values)
                ):
                    request[field] = repaired_values
                    repairs.append({
                        "kind": "neutralized_ungrounded_standalone_paragraph",
                        "request_id": request.get("request_id"),
                        "field": field,
                        "before": values,
                        "after": repaired_values,
                        "reason": "standalone_paragraph_lacks_request_scoped_grounded_article",
                    })
        repaired_requests.append(request)
    return repaired_requests, repairs


def validate_article_grounding(requests, inp, errors):
    """Validate target statute/article pairs across every retrieval field."""
    allowed = _allowed_pairs(inp)
    for request in requests:
        values = [
            request.get("query_text"),
            request.get("first_stage_query_text"),
            request.get("rerank_query_text"),
        ]
        for key in ("query_terms", "statute_hints"):
            field = request.get(key, [])
            if isinstance(field, list):
                values.extend(field)
        explicit = set()
        bare = []
        standalone_paragraphs = []
        for value in values:
            pairs, qualified_spans, unresolved_statutes = _qualified_pairs(
                value, {pair[0] for pair in allowed}
            )
            article_spans = [
                match.span() for match in ARTICLE_ONLY_PATTERN.finditer(value)
            ] if isinstance(value, str) else []
            explicit.update(pairs)
            for statute in unresolved_statutes:
                errors.append("unresolved or generic statute name before article: %s" % statute)
            bare.extend(_bare_references(value, qualified_spans))
            standalone_paragraphs.extend(_standalone_paragraphs(value, article_spans))
        grounded_explicit = {
            pair for pair in explicit if _pair_is_allowed(pair, allowed)
        }
        for pair in explicit:
            if not _pair_is_allowed(pair, allowed):
                errors.append("statute/article pair lacks question or supplied candidate-cross-reference provenance: %s %s" % (pair[0], pair[1]))
        for paragraph in standalone_paragraphs:
            # A standalone paragraph may use a paragraph-specific anchor when
            # this same request already names exactly one grounded statute and
            # article.  The model cannot use that shortcut to add a paragraph
            # to an article-only anchor or to choose between multiple laws.
            bindings = {
                allowed_pair
                for allowed_pair in allowed
                if allowed_pair[2] == paragraph
                and any(
                    explicit_pair[0] == allowed_pair[0]
                    and explicit_pair[1] == allowed_pair[1]
                    for explicit_pair in grounded_explicit
                )
            }
            if len(bindings) != 1:
                errors.append("standalone paragraph lacks request-scoped grounded article provenance: %s" % paragraph)
        for article, paragraph in bare:
            matching = {
                pair for pair in allowed
                if pair[1] == article and (paragraph is None or pair[2] == paragraph)
            }
            statutes = {pair[0] for pair in matching}
            if len(statutes) != 1:
                errors.append("unqualified statute/article lacks unique provenance: %s" % article)

def validate(out, inp):
    errors = []
    validate_common(out, inp, errors)
    if out.get("status") == "error":
        error = out.get("error")
        if not isinstance(error, dict) or error.get("code") not in {"INVALID_INPUT", "BUDGET_EXHAUSTED", "CONTRACT_UNSATISFIABLE"}:
            errors.append("invalid error envelope")
        return errors

    constraints = (inp or {}).get("constraints", {})
    allowed = set(constraints.get("allowed_query_channels", ["provision_style", "sparse_keywords", "statute_aware"]))
    max_per_issue = constraints.get("max_requests_per_issue", 3)
    requires_answer_targets = constraints.get("answer_target_contract") == "required"
    prior = history_queries(inp)

    if out.get("mode") == "INITIAL_PLAN":
        issues = out.get("legal_issues", [])
        targets = out.get("answer_targets", [])
        evidence = out.get("required_evidence_items", [])
        requests = out.get("retrieval_requests", [])
        issue_ids = unique_ids(issues, "issue_id", r"I[1-9][0-9]*", errors)
        target_ids = unique_ids(targets, "answer_target_id", r"T[1-9][0-9]*", errors)
        evidence_ids = unique_ids(evidence, "evidence_item_id", r"E[1-9][0-9]*", errors)
        if not issue_ids or not evidence_ids or not requests:
            errors.append("INITIAL_PLAN requires non-empty issues, evidence, and requests")
        for item in evidence:
            if item.get("issue_id") not in issue_ids:
                errors.append(f"evidence references unknown issue: {item.get('evidence_item_id')}")
        if requires_answer_targets and not targets:
            errors.append("answer_targets are required by the harness contract")
        if targets or requires_answer_targets:
            question = trusted_answer_question_segment(inp)
            if not question:
                errors.append("answer_targets require an input question")
            requirement_ids = set()
            critical_targets = set()
            for target in targets:
                anchor = target.get("question_anchor")
                if not isinstance(anchor, str) or not norm(anchor) or norm(anchor) not in question:
                    errors.append(f"question_anchor is not a question substring: {target.get('answer_target_id')}")
                if not isinstance(target.get("requested_output"), str) or not target.get("requested_output").strip():
                    errors.append(f"missing requested_output: {target.get('answer_target_id')}")
                if not isinstance(target.get("answer_type"), str) or not target.get("answer_type").strip():
                    errors.append(f"missing answer_type: {target.get('answer_target_id')}")
            for item in evidence:
                item_targets = item.get("answer_target_ids", [])
                if not isinstance(item_targets, list) or len(item_targets) != len(set(item_targets)):
                    errors.append(f"invalid answer_target_ids: {item.get('evidence_item_id')}")
                    continue
                if set(item_targets) - target_ids:
                    errors.append(f"evidence references unknown answer target: {item.get('evidence_item_id')}")
                scope_source = item.get("scope_source")
                if scope_source not in {"explicit_question", "outcome_changing_condition", "supporting_context"}:
                    errors.append(f"invalid scope_source: {item.get('evidence_item_id')}")
                if scope_source == "supporting_context" and item.get("critical") is True:
                    errors.append(f"supporting_context cannot be critical: {item.get('evidence_item_id')}")
                if item.get("critical") is True:
                    if not item_targets:
                        errors.append(f"critical evidence lacks answer target: {item.get('evidence_item_id')}")
                    critical_targets.update(item_targets)
                if not isinstance(item.get("necessity_reason"), str) or not item.get("necessity_reason").strip():
                    errors.append(f"missing necessity_reason: {item.get('evidence_item_id')}")
                requirements = item.get("completion_requirements", [])
                if not isinstance(requirements, list) or not requirements:
                    errors.append(f"missing completion_requirements: {item.get('evidence_item_id')}")
                    continue
                for requirement in requirements:
                    requirement_id = requirement.get("requirement_id") if isinstance(requirement, dict) else None
                    text = requirement.get("text") if isinstance(requirement, dict) else None
                    if not isinstance(requirement_id, str) or not requirement_id:
                        errors.append(f"invalid requirement_id: {item.get('evidence_item_id')}")
                    elif requirement_id in requirement_ids:
                        errors.append(f"duplicate requirement_id: {requirement_id}")
                    else:
                        requirement_ids.add(requirement_id)
                    if not isinstance(text, str) or not text.strip():
                        errors.append(f"invalid requirement text: {requirement_id}")
            if target_ids - critical_targets:
                errors.append("every answer target must have critical evidence")
        validate_requests(requests, issue_ids, evidence, prior, allowed, max_per_issue, errors)
        validate_article_grounding(requests, inp, errors)
        validate_initial_plan_effect_neutrality(out, inp, errors)
        targeted = {r.get("evidence_item_id") for r in requests}
        for item in evidence:
            if item.get("critical") is True and item.get("evidence_item_id") not in targeted:
                errors.append(f"critical evidence lacks a retrieval request: {item.get('evidence_item_id')}")
    else:
        requests = out.get("gap_retrieval_requests", [])
        targets = out.get("target_evidence_item_ids", [])
        if not inp:
            errors.append("GAP_QUERY_PLAN validation requires --input")
            return errors
        issues = {x.get("issue_id") for x in inp.get("legal_issues", [])}
        evidence = inp.get("required_evidence_items", [])
        evidence_ids = {x.get("evidence_item_id") for x in evidence}
        unresolved = {x.get("evidence_item_id") for x in inp.get("missing_evidence_items", [])}
        unresolved.update(x.get("evidence_item_id") for x in inp.get("evidence_conflicts", []))
        if len(targets) != len(set(targets)):
            errors.append("target_evidence_item_ids must be unique")
        if set(targets) - evidence_ids:
            errors.append("target list contains unknown evidence items")
        if set(targets) - unresolved:
            errors.append("target list contains resolved evidence items")
        request_targets = {r.get("evidence_item_id") for r in requests}
        if set(targets) != request_targets:
            errors.append("target_evidence_item_ids must equal request targets")
        if len(requests) > inp.get("remaining_request_budget", 0):
            errors.append("gap requests exceed remaining_request_budget")
        validate_requests(requests, issues, evidence, prior, allowed, max_per_issue, errors, gap=True)
        validate_article_grounding(requests, inp, errors)
    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate S1 output semantics")
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
    print("VALID: S1 output contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
