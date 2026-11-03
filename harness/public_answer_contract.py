"""Shared, fail-closed bounds for public S3 answer presentation."""

from __future__ import annotations

PUBLIC_ANSWER_MIN_LINES = 1
PUBLIC_ANSWER_MAX_CHARACTERS = 800
PUBLIC_ANSWER_MAX_CLAIMS = 4
PUBLIC_ANSWER_FORMAT = "conclusion_first_1_to_4_short_sentences"

# The mapping is copied into frozen configurations; consumers must reject a
# manifest that declares different values rather than silently defaulting it.
PUBLIC_ANSWER_CONTRACT = {
    "s3_public_answer_max_characters": PUBLIC_ANSWER_MAX_CHARACTERS,
    "s3_public_answer_max_claims": PUBLIC_ANSWER_MAX_CLAIMS,
    "s3_public_answer_format": PUBLIC_ANSWER_FORMAT,
}
