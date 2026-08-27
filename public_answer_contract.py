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
