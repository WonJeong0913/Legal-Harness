---
name: grounded-legal-answer-generation
description: Generate a Korean statutory answer with claim-level citations from the provision set authorized by the harness. Use for publishable S3 GENERATE_ANSWER or non-publishable GENERATE_BENCHMARK_CANDIDATE; do not use it to retrieve evidence, assess coverage, choose abstention, or validate citations.
---

# Grounded Legal Answer Generation

Return one compact S3 JSON object. Read
[references/contract.md](references/contract.md) and follow the harness-owned
authorization and answer scope.

## Generate

1. Answer in Korean unless the input constraint explicitly selects another language. Put the legal conclusion first and keep the public `answer` to 1--3 short sentences, never more than 800 characters and preferably about 300--500 characters. Include only the outcome-changing condition and the minimum statutory basis needed to understand the conclusion.
2. Separate statutory rules from conditional application to the facts. Do not invent missing facts, case law, administrative guidance, or provision text.
3. Use only `accepted_provisions[]`. Preserve each selected claim-to-provision connection and its support description; the harness replaces `quoted_text` with the immutable full provision snapshot.
4. Put only substantive legal claims in `claims[]`, set `citation_required: true`, attach at least one citation, and identify its `answer_target_ids`. The harness preserves every audit claim and citation but deterministically publishes at most three prioritized claims with harness-owned IDs, markers, full provision text, and final serialization.
5. Keep uncited factual premises and limitation explanations out of `claims[]`; preserve them in `assumptions[]` and `limitations[]`. Do not append every audit note to the public answer.
6. Preserve all assumptions and material limitations without presenting them as established facts. Repeat only an outcome-changing condition briefly in the public answer body.
7. For every partially covered critical item, state the unresolved condition in `limitations[]` and phrase the corresponding claim with `applicability: "conditional"`. Do not turn the missing factual premise into a fact.
8. Return JSON only.

For `GENERATE_ANSWER`, cite only `accepted_provisions`. For
`GENERATE_BENCHMARK_CANDIDATE`, cite only `candidate_provisions`, answer all
supplied targets, and keep the result non-publishable; the public policy remains
`ABSTAIN`. With `question_only`, return a concise diagnostic answer with empty
claims and citations.

## Boundary

Do not retrieve, reassess coverage, choose a policy action, or claim that citation
validation passed. Return a structured error when authorization or evidence
preconditions fail.

Validate a result with:

```bash
python3 scripts/validate_output.py output.json --input input.json
```
