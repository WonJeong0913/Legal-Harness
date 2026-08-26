---
name: provision-coverage-assessment
description: Assess whether retrieved Korean statutory provisions satisfy each required legal evidence item and return evidence links plus covered, partially_covered, uncovered, or conflicting assessments. Use for S2 ASSESS_COVERAGE after initial or gap provision retrieval; do not use it to retrieve more evidence, select RETRIEVE_GAP/GENERATE/ABSTAIN, derive accepted provision IDs, or generate the answer.
---

# Provision Coverage Assessment

Return one contract-valid S2 JSON object. Read
[references/contract.md](references/contract.md) and use only the supplied
requirements and candidate provisions.

## Assess

1. Assess every evidence item and every supplied completion requirement exactly
   once. A requirement is satisfied when the supplied candidates establish that
   legal proposition; it need not answer the whole question by itself. Relevance
   alone is not support.
2. Link the smallest candidate set that actually satisfies a requirement. One
   provision may support several requirements and one requirement may need
   several provisions. Classify every link as `CORE`, `SUPPLEMENTAL`,
   `QUALIFYING`, or `ALTERNATIVE`, with a condition (required for qualifying or
   alternative evidence) and concise rationale. In raw compact transport use
   only supplied candidate IDs plus those decisions; the harness restores the
   immutable full-text quote deterministically.
3. Treat the supplied requirements as closed. Do not invent a missing definition,
   procedure, background point, or general legal-opinion completeness test.
4. Apply the contract's coverage mapping. Question facts need no statutory
   citation: when the legal rule is complete and only a supplied fact selects an
   application branch, use `covered` + `conditional` + `missing_fact`.
5. Put only supplied requirement IDs in aspect fields and explanations in
   `rationale`. Preserve a prior supported finding when its provision remains,
   unless new evidence creates a real conflict.
6. Return JSON only.

## Deterministic scope guards

Do not mark direct or satisfied support from a candidate whose text limits the same law to an explicit article range when a direct root provision for another evidence item under the same answer target falls outside that range. A no-prefix range such as `제10조부터 제12조까지` is read against that candidate's own statute label.
Do not use a candidate's `base(subtype)` text as direct or satisfied support for a general base entity unless the supplied question or requirement also states that subtype. Parentheses in a statute label alone are not enough.

## Atomic direct-entailment audit

For every `direct` assessment whose criterion is `satisfied`, add a
`direct_entailment` object to that criterion. Assess separately whether the
candidate set matches the regulated subject or act, outcome-changing
qualifiers (including medium, timing, or special actor), requested legal
effect, and any required procedural path versus a later remedy. Use
`not_applicable` only when that component is absent from the supplied
requirement. For the candidate provision set that you would link as
`direct`/`satisfied` support for that criterion, if any linked candidate
mismatches an explicit component, mark that component `mismatch` and do not retain `direct` or `satisfied`; leave the
legal requirement for the harness's bounded gap policy instead.

## Evidence-role boundary

Only an accepted `CORE` link may appear in `linked_provision_ids`, satisfy a
criterion, or establish `governing_legal_regime: direct_entailment`. A
`SUPPLEMENTAL`, `QUALIFYING`, or `ALTERNATIVE` link is authorized audit context:
it may be retained with its condition and rationale, but cannot make an item
covered, partially covered, directly applicable, or criterion-satisfied. A
covered legal status requires `direct_entailment`; do not relabel helpful
context as core to pass this rule. Role-less legacy links are interpreted as
`CORE` by the harness.

## Boundary

Do not retrieve, generate an answer, derive `accepted_provision_ids`, or choose a
policy action. An absent candidate means only that the current candidate set is
insufficient, not that no governing law exists.

Validate a result with:

```bash
python3 scripts/validate_output.py output.json --input input.json
```

## Direct-entailment boundary

For each explicit answer target and supplied completion requirement, accept only the smallest directly entailing provision set.
A direct evidence link is necessary to establish that requirement's proposition, not merely useful for understanding it.
Audit-only helpful context may inform a concise rationale, but it must remain unlinked and cannot make an assessment covered or partially covered.
Do not link related, background, neighboring, procedural, or general rules unless their text is necessary to directly entail a supplied requirement.
Do not infer additional requirements from outside evaluation knowledge; the supplied targets and requirements remain closed.
