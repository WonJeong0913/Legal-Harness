"""Cycle-free, shared contract for the published S3 answer surface.

This module intentionally imports nothing: the executor, validation harness, and
paired-manifest comparison guard must all consume the same frozen values without
depending on one another.
"""

PUBLIC_ANSWER_MAX_CHARACTERS = 800
PUBLIC_ANSWER_MAX_CLAIMS = 4
PUBLIC_ANSWER_MIN_LINES = 1
PUBLIC_ANSWER_MAX_LINES = PUBLIC_ANSWER_MAX_CLAIMS
PUBLIC_ANSWER_FORMAT = "conclusion_first_1_to_4_short_sentences"


def qualifying_public_exception_citation_is_authorized(
    claim,
    provision_id,
    answered_target_ids,
    required_evidence_items,
    accepted_provision_ids,
    qualifying_provision_ids,
    qualifying_links,
):
    """Authorize only a target-linked QUALIFYING conditional exception.

    The caller supplies role projections derived from accepted evidence links.
    This module deliberately has no harness or skill imports so both the S3
    validator and final harness validation use the same fail-closed predicate.
    """
    if (
        not isinstance(claim, dict)
        or claim.get("public_role") != "conclusion"
        or claim.get("claim_type") != "exception"
        or claim.get("applicability") != "conditional"
        or not isinstance(provision_id, str)
        or not provision_id
    ):
        return False

    def identifiers(values):
        if not isinstance(values, (list, tuple, set)):
            return None
        result = set()
        for value in values:
            if not isinstance(value, str) or not value:
                return None
            result.add(value)
        return result

    claim_targets = identifiers(claim.get("answer_target_ids"))
    answered_targets = identifiers(answered_target_ids)
    accepted_ids = identifiers(accepted_provision_ids)
    qualifying_ids = identifiers(qualifying_provision_ids)
    if (
        not claim_targets
        or not answered_targets
        or not claim_targets.issubset(answered_targets)
        or accepted_ids is None
        or qualifying_ids is None
        or provision_id not in accepted_ids
        or provision_id not in qualifying_ids
        or not isinstance(required_evidence_items, (list, tuple))
        or not isinstance(qualifying_links, (list, tuple))
    ):
        return False
    evidence_targets = {}
    for evidence in required_evidence_items:
        if not isinstance(evidence, dict):
            continue
        evidence_id = evidence.get("evidence_item_id")
        target_ids = identifiers(evidence.get("answer_target_ids"))
        if isinstance(evidence_id, str) and evidence_id and target_ids:
            evidence_targets[evidence_id] = target_ids
    return any(
        isinstance(link, dict)
        and link.get("provision_id") == provision_id
        and claim_targets.issubset(evidence_targets.get(link.get("evidence_item_id"), set()))
        for link in qualifying_links
    )
