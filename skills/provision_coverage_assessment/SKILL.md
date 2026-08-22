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
   several provisions. Use only supplied candidate IDs and set `quoted_text` to
   `[FULL_TEXT]`.
3. Treat the supplied requirements as closed. Do not invent a missing definition,
   procedure, background point, or general legal-opinion completeness test.
4. Apply the contract's coverage mapping. Question facts need no statutory
   citation: when the legal rule is complete and only a supplied fact selects an
   application branch, use `covered` + `conditional` + `missing_fact`.
5. Put only supplied requirement IDs in aspect fields and explanations in
   `rationale`. Preserve a prior supported finding when its provision remains,
   unless new evidence creates a real conflict.
6. Return JSON only.

## Boundary

Do not retrieve, generate an answer, derive `accepted_provision_ids`, or choose a
policy action. An absent candidate means only that the current candidate set is
insufficient, not that no governing law exists.

Validate a result with:

```bash
python3 scripts/validate_output.py output.json --input input.json
```
