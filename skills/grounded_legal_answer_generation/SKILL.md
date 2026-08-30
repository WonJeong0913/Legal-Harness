---
name: grounded-legal-answer-generation
description: Generate a Korean statutory answer with claim-level citations from the provision set authorized by the harness. Use for publishable S3 GENERATE_ANSWER or non-publishable GENERATE_BENCHMARK_CANDIDATE; do not use it to retrieve evidence, assess coverage, choose abstention, or validate citations.
---

# Grounded Legal Answer Generation

Return one compact S3 JSON object. Read
[references/contract.md](references/contract.md) and follow the harness-owned
authorization and answer scope.

## Generate

1. Answer in Korean unless the input constraint explicitly selects another language. Put the legal conclusion first and normally keep the eventual public answer to 2--4 short sentences, never more than 800 characters and preferably about 80--250 characters. Include only the outcome-changing condition and the minimum statutory basis needed to understand the conclusion.
2. Separate statutory rules from conditional application to the facts. Do not invent missing facts, case law, administrative guidance, or provision text.
3. `accepted_provisions[]` is the authorized union. Use
   `core_accepted_provisions[]` for every `public_role: "conclusion"` citation,
   except on a retry with an explicit harness `CONDITIONAL-EXCEPTION
   CARRY-FORWARD` instruction. Then, only the listed `QUALIFYING` provision may
   be cited by the one conclusion that visibly contains that exact condition
   and all of its target and provision IDs. `supplemental_provisions[]`, every
   other `qualifying_provisions[]`, and `alternative_provisions[]` may be cited
   only by `public_role: "audit"` claims. Preserve each selected claim-to-provision connection and its support
   description; the harness replaces `quoted_text` with the immutable full
   provision snapshot.
4. Put only substantive legal claims in `claims[]`, set `citation_required: true`, attach at least one citation, and identify its `answer_target_ids`. Mark one to four claims `public_role: "conclusion"` so they cover every answered target; mark all remaining claims `audit`. For `GENERATE_ANSWER` with the required public conclusion contract, require a citation-supported, target-level `claim_type: "application"` conclusion claim only when exactly one answered target is a `legal_conclusion`, exactly one linked `required_evidence_items[]` item is critical, at least two of that target's public conclusion claims are `legal_rule` claims citing at least two different `provision_id` values, and no cited public application claim exists for it; do not merely relabel an abstract `legal_rule`. A conditional `exception` claim attached to an answered target must also be a citation-supported public conclusion, unless it is an audit duplicate whose normalized full text is visibly contained in one public conclusion whose target and cited-provision sets contain all of the exception target IDs and provision IDs. On a repair retry, you may consolidate prior claim objects, but every initially hidden conditional exception must remain visibly contained in one public conclusion with all of its targets and cited provisions, even if the original audit object is removed. The harness then deterministically orders and renders only the model-designated conclusion claims with harness-owned IDs, markers, and full provision text.
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

## Target-only answer boundary

Generate only the supplied, authorized requested answer targets; do not summarize every accepted provision.
Each public conclusion and substantive claim must be necessary to answer a requested target, with its existing citation preserved.
Exclude an adjacent legal fact, background rule, neighboring procedure, or extra consequence unless it is necessary to state the target conclusion or its outcome-changing condition.
In `conditional` and `limited` modes, preserve the authorized condition, deferred-target boundary, citations, assumptions, and limitations rather than adding adjacent conclusions.
Do not use outside evaluation knowledge to expand the requested target scope.
