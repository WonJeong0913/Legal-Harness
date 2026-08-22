---
name: legal-evidence-planning
description: Structure Korean statutory multi-hop questions into legal issues, required evidence items, and targeted provision-retrieval requests. Use for S1 INITIAL_PLAN before retrieval or S1 GAP_QUERY_PLAN after a provision-coverage assessment identifies missing or conflicting evidence; do not use it to retrieve statutes, assess coverage, choose the next harness action, or draft the answer.
---

# Legal Evidence Planning

Return one compact, contract-valid S1 JSON object. Read
[references/contract.md](references/contract.md) and follow the supplied mode and
output schema.

## Plan

1. Plan only the result the question asks for. Use one `answer_target` when
   several clauses ask for one dispositive conclusion, even if several
   provisions are needed; split only independently requested outputs.
2. Make critical requirements the minimum legal propositions needed to derive
   those outputs. Do not predict benchmark hop count or assume one provision per
   requirement. Preserve a distinct outcome-determinative rule, exception,
   cross-reference, or legal effect, but do not make question facts, generic
   completeness, background, definitions, or procedure critical unless the
   question requests them or they change the conclusion.
3. In `INITIAL_PLAN`, give every critical evidence item at least one focused
   request. Add another request only for a genuinely different statutory route,
   exception, or cross-reference, within the supplied limit. Follow the
   contract's retrieval query-field rules and do not restate the whole question
   in each field.
4. In `GAP_QUERY_PLAN`, target only supplied unresolved statute evidence. Do not
   search for `missing_fact` or `scope_excess`. Use a genuinely new legal angle
   and stay within the supplied budget.
5. Compact descriptive prose, not the structural evidence coverage. Use one
   short sentence per descriptive field, avoid repeated rationale, close the
   JSON object, and return JSON only.

## Boundary

Do not retrieve statutes, assess coverage, generate an answer, or choose
`RETRIEVE_GAP`, `GENERATE`, or `ABSTAIN`. The harness owns transport IDs, retries,
budgets, and control flow; the retrieval tool owns Top-k, fusion, and reranking.

Validate a result with:

```bash
python3 scripts/validate_output.py output.json --input input.json
```
