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


GENERIC_OUTPUT_DESCRIPTORS = ("법적 효력", "유효성")
_SCOPE_MINIMALITY_BOILERPLATE = frozenset(
    {
        "관한", "대한", "규정", "규정하", "규정하는", "조항", "법적", "효력",
        "유효성", "유효", "허용", "여부", "요건", "포함", "포함하", "등", "및",
        "또는", "필요", "필요한", "적용", "상기", "을", "를", "은", "는", "이",
        "가", "의", "에", "도", "만", "로", "과", "와",
    }
)
_KOREAN_PARTICLES = (
    "으로부터", "에게서", "으로", "에서", "까지", "부터", "에게", "보다",
    "처럼", "같이", "과", "와", "의", "을", "를", "은", "는", "이", "가",
    "에", "도", "만", "로",
)


def _korean_only_text(value):
    """Keep this narrow contract out of English and mixed-language plans."""
    return (
        isinstance(value, str)
        and bool(re.search(r"[가-힣]", value))
        and not bool(re.search(r"[A-Za-z]", value))
    )


def _scope_minimality_tokens(text):
    """Normalize only Korean completion-requirement carrier phrases."""
    if not _korean_only_text(text):
        return ()
    normalized = norm(text)
    for descriptor in GENERIC_OUTPUT_DESCRIPTORS:
        normalized = normalized.replace(descriptor, " ")
    tokens = []
    for token in re.findall(r"[가-힣]+", normalized):
        if token in _SCOPE_MINIMALITY_BOILERPLATE:
            continue
        for particle in _KOREAN_PARTICLES:
            if len(token) > len(particle) + 1 and token.endswith(particle):
                token = token[: -len(particle)]
                break
        if token and token not in _SCOPE_MINIMALITY_BOILERPLATE:
            tokens.append(token)
    return tuple(tokens)


def _contiguous_subsequence(needle, haystack):
    if len(needle) < 2 or len(needle) > len(haystack):
        return False
    width = len(needle)
    return any(tuple(haystack[index:index + width]) == tuple(needle)
               for index in range(len(haystack) - width + 1))


def validate_initial_plan_requirement_scope_minimality(out, inp, errors):
    """Reject only a duplicate Korean requirement expanded by a generic descriptor."""
    question = trusted_answer_question_segment(inp)
    if not _korean_only_text(question):
        return
    targets = {
        target.get("answer_target_id"): target
        for target in out.get("answer_targets", [])
        if isinstance(target, dict)
        and isinstance(target.get("answer_target_id"), str)
        and _korean_only_text(target.get("question_anchor"))
    }
    for item in out.get("required_evidence_items", []):
        if not isinstance(item, dict):
            continue
        target_ids = item.get("answer_target_ids")
        if (
            item.get("critical") is not True
            or item.get("scope_source") != "explicit_question"
            or not isinstance(target_ids, list)
            or len(target_ids) != 1
            or target_ids[0] not in targets
        ):
            continue
        anchor = targets[target_ids[0]].get("question_anchor")
        requirements = item.get("completion_requirements")
        if not _korean_only_text(anchor) or not isinstance(requirements, list):
            continue
        for requirement in requirements:
            if not isinstance(requirement, dict):
                continue
            text = requirement.get("text")
            if not _korean_only_text(text):
                continue
            descriptor = next(
                (
                    value for value in GENERIC_OUTPUT_DESCRIPTORS
                    if value in text and value not in question and value not in anchor
                ),
                None,
            )
            carrier = _scope_minimality_tokens(text)
            if descriptor is None or len(carrier) < 2:
                continue
            for sibling in requirements:
                sibling_text = sibling.get("text") if isinstance(sibling, dict) else None
                if (
                    sibling is requirement
                    or not _korean_only_text(sibling_text)
                    or any(value in sibling_text for value in GENERIC_OUTPUT_DESCRIPTORS)
                ):
                    continue
                if _contiguous_subsequence(carrier, _scope_minimality_tokens(sibling_text)):
                    errors.append(
                        "INITIAL_PLAN scope-expanding generic output descriptor absent from question: "
                        "evidence_item_id=%s; requirement_id=%s; descriptor=%s"
                        % (
                            item.get("evidence_item_id"),
                            requirement.get("requirement_id"),
                            descriptor,
                        )
                    )
                    break


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


_GAP_ANCHOR_STOPWORDS = frozenset({
    "관련", "관한", "대한", "위한", "해당", "경우", "여부", "필요", "필요한",
    "기준", "요건", "조건", "법적", "법률", "규정", "조항", "적용", "판단",
    "인정", "확인", "검토", "효과", "사안", "사실", "인한", "따른", "있는",
    "없는", "그리고", "또는", "등", "수", "것", "중", "내", "및", "와", "과",
})
_KOREAN_PARTICLE_SUFFIXES = (
    "으로", "에서", "에게", "까지", "부터", "처럼", "보다", "으로서",
    "으로써", "에게서", "이라면", "이라도", "이라서", "은", "는", "이",
    "가", "을", "를", "의", "에", "로", "도", "만", "와", "과",
)
_GAP_ANCHOR_CONTEXT_HEADS = frozenset({
    "기관", "법원", "회사", "사업장", "근로자", "사람", "당사자", "절차",
})
_KOREAN_DESCRIPTIVE_MODIFIER_SUFFIXES = (
    "하는", "되는", "받은", "발생한", "입은", "따른", "있는", "없는", "치는", "한",
)


def _is_korean_descriptive_modifier(value):
    """Keep verbal attributives out of literal noun-phrase anchor extraction."""
    return isinstance(value, str) and value.endswith(
        _KOREAN_DESCRIPTIVE_MODIFIER_SUFFIXES
    )


def _korean_gap_anchor_phrases(value):
    """Return only literal Korean two-word fact/effect anchors.

    This deliberately skips English and mixed source text. It keeps only a
    distinctive modifier/head pair whose head bears a normalized Korean
    particle, avoiding arbitrary bigrams from a long evidence sentence.
    """
    if not isinstance(value, str) or re.search(r"[A-Za-z0-9]", value):
        return set()
    source_words = re.findall(r"[가-힣]+", unicodedata.normalize("NFKC", value))
    phrases = set()
    for left, right in zip(source_words, source_words[1:]):
        normalized_words = []
        right_had_particle = False
        for index, word in enumerate((left, right)):
            normalized = word
            for suffix in _KOREAN_PARTICLE_SUFFIXES:
                if normalized.endswith(suffix) and len(normalized) - len(suffix) >= 2:
                    normalized = normalized[:-len(suffix)]
                    if index == 1:
                        right_had_particle = True
                    break
            normalized_words.append(normalized)
        if (
            right_had_particle
            and all(
            word not in _GAP_ANCHOR_STOPWORDS and len(word) >= 2
            for word in normalized_words
            )
            and normalized_words[1] not in _GAP_ANCHOR_CONTEXT_HEADS
            # Strip particles only from noun heads.  In particular, never turn
            # 규정하는/미치는 into the spurious heads 규정하/미치.
            and not _is_korean_descriptive_modifier(left)
            and not _is_korean_descriptive_modifier(right)
        ):
            phrases.add(" ".join(normalized_words))
    return phrases


def _trusted_gap_anchor_phrases(evidence_item):
    """Activate one most-specific anchor repeated by Korean source fields."""
    if not isinstance(evidence_item, dict):
        return set()
    description_phrases = _korean_gap_anchor_phrases(
        evidence_item.get("description")
    )
    requirement_phrases = set()
    for requirement in evidence_item.get("completion_requirements", []):
        if isinstance(requirement, dict):
            requirement_phrases.update(
                _korean_gap_anchor_phrases(requirement.get("text"))
            )
    shared = description_phrases.intersection(requirement_phrases)
    if not shared:
        return set()
    # Query terms are intentionally bounded to 2--6 values.  Requiring every
    # bigram from a long evidence sentence would turn this narrow integrity
    # check into a competing query planner. The candidate extractor has already
    # excluded general context heads and descriptive-verb modifiers, so retain
    # one stable literal result-object/effect anchor.
    return {sorted(shared)[-1]}


def _request_scoped_completion_requirement(evidence_item, request):
    """Return the exact atomic requirement named by a GAP request, if any.

    A model may name an existing requirement in ``gap_reason`` to distinguish
    complementary retrieval requests for one evidence item.  This is only a
    routing reference: malformed, unknown, or non-Korean references return
    ``None`` so the broader evidence-level anchor predicate stays in force.
    """
    if not isinstance(evidence_item, dict) or not isinstance(request, dict):
        return None
    evidence_id = evidence_item.get("evidence_item_id")
    reason = request.get("gap_reason")
    if not isinstance(evidence_id, str) or not isinstance(reason, str):
        return None
    match = re.match(
        r"^\s*(%s-R[1-9][0-9]*)\s+미충족\s*:" % re.escape(evidence_id),
        reason,
    )
    if match is None:
        return None
    matches = [
        requirement
        for requirement in evidence_item.get("completion_requirements", [])
        if isinstance(requirement, dict)
        and requirement.get("requirement_id") == match.group(1)
        and isinstance(requirement.get("text"), str)
        and requirement["text"].strip()
    ]
    return matches[0] if len(matches) == 1 else None


def _scoped_anchor_in_query_terms(anchors, values):
    """Match a literal Korean requirement anchor in one explicit query term.

    The only relaxed morphology is a two-or-more-syllable suffix of one
    compound source token (``조치`` in ``긴급조치``).  The full two-word anchor
    must remain contiguous; this is not semantic expansion and never consults
    query_text or source-question context.
    """
    if not isinstance(values, list):
        return False
    terms = [
        re.findall(r"[가-힣]+", unicodedata.normalize("NFKC", value))
        for value in values
        if isinstance(value, str) and not re.search(r"[A-Za-z0-9]", value)
    ]
    # Preserve the existing contract that one request's ordered explicit terms
    # may jointly spell an anchor; never join terms across requests.
    term_views = terms + [
        [token for term in terms for token in term]
    ]
    for anchor in anchors:
        anchor_tokens = anchor.split()
        if len(anchor_tokens) != 2:
            continue
        for term_tokens in term_views:
            for index in range(len(term_tokens) - 1):
                candidate = term_tokens[index : index + 2]
                if all(
                    source == observed
                    or (
                        len(observed) >= 2
                        and source.endswith(observed)
                    )
                    for source, observed in zip(anchor_tokens, candidate)
                ):
                    return True
    return False


def validate_gap_query_terms_anchor_coverage(requests, evidence, unresolved, errors):
    """Keep repeated Korean fact/effect anchors in explicit gap query_terms.

    The predicate is intentionally mechanical: it neither creates a query nor
    chooses a law, and query_text/original-question context cannot satisfy it.
    """
    for item in evidence:
        if (
            not isinstance(item, dict)
            or item.get("critical") is not True
            or item.get("evidence_item_id") not in unresolved
        ):
            continue
        anchors = _trusted_gap_anchor_phrases(item)
        if not anchors:
            continue
        request_term_views = []
        has_scoped_requirement = False
        for request in requests:
            if request.get("evidence_item_id") != item.get("evidence_item_id"):
                continue
            values = request.get("query_terms", [])
            requirement = _request_scoped_completion_requirement(item, request)
            requirement_anchors = (
                _korean_gap_anchor_phrases(requirement.get("text"))
                if requirement is not None
                else set()
            )
            if requirement_anchors:
                has_scoped_requirement = True
                if not _scoped_anchor_in_query_terms(requirement_anchors, values):
                    errors.append(
                        "GAP_QUERY_PLAN query_terms omit trusted Korean fact/effect anchors: "
                        "evidence_item_id=%s; requirement_id=%s; missing_anchors=%s"
                        % (
                            item.get("evidence_item_id"),
                            requirement.get("requirement_id"),
                            ", ".join(sorted(requirement_anchors)),
                        )
                    )
                continue
            if isinstance(values, list):
                normalized_terms = [
                    norm(value) for value in values if isinstance(value, str) and norm(value)
                ]
                request_term_views.append((
                    normalized_terms, " ".join(normalized_terms),
                ))
        if has_scoped_requirement and not request_term_views:
            continue
        missing = sorted(
            anchor for anchor in anchors
            if not any(
                any(anchor in query_term for query_term in terms)
                or anchor in joined_terms
                for terms, joined_terms in request_term_views
            )
        )
        if missing:
            errors.append(
                "GAP_QUERY_PLAN query_terms omit trusted Korean fact/effect anchors: "
                "evidence_item_id=%s; missing_anchors=%s"
                % (item.get("evidence_item_id"), ", ".join(missing))
            )

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
        validate_initial_plan_requirement_scope_minimality(out, inp, errors)
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
        validate_gap_query_terms_anchor_coverage(requests, evidence, unresolved, errors)
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
