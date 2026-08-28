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
2. Before writing JSON for `INITIAL_PLAN`, perform a mandatory internal
   deletion pass. For every critical item and completion requirement, remove it
   or lower it to noncritical when the requested output could still be stated
   legally and accurately without it. Keep only the minimum legal propositions
   needed to derive the explicit outputs. Do not predict benchmark hop count or
   assume one provision per requirement. Preserve a distinct outcome-changing
   rule, exception, indispensable cross-reference predicate, or legal effect;
   do not make question facts, generic completeness, background, definitions,
   or procedure critical unless the question asks for them or they change that
   result.
3. Treat people, titles, numbers, and other background facts as context, not a
   separate critical axis, unless the question expressly asks about that
   qualification or scope, or it changes the governing rule. If the question
   expressly assumes a violation and asks only for the penalty, the full proof
   of the violation is supporting by default; retain only the smallest
   cross-reference predicate indispensable to identify the penalty subsection.
   Do not expand broad wording such as “necessary conditions” into every
   conceivably related legal dimension: plan only the immediate operative rule's
   minimum conjuncts.
4. Start each answer target with one evidence item that groups its atomic
   requirements. Split it only for an independently requested clause, an
   indispensable bridge, or an outcome-changing condition. For example, a
   governance-role list beside a quorum question does not itself create a
   qualification axis; a stipulated-violation penalty question does not require
   an unnecessary offense re-proof; separately asked duration and post-expiry
   procedure remain separate outputs; and an attempt penalty keeps both the
   base offense and the attempt rule.
5. In `INITIAL_PLAN`, give every critical evidence item at least one focused
   request. Add another request only for a genuinely different statutory route,
   exception, or cross-reference, within the supplied limit. Follow the
   contract's retrieval query-field rules and do not restate the whole question
   in each field. A generic request for conditions or requirements does not by
   itself authorize a blanket "exception provision" completion requirement or
   query term. Add an exception or alternative only when the question expressly
   asks for it or a stated concrete fact activates it; name that fact or
   condition, never a generic exception provision.
6. In `GAP_QUERY_PLAN`, target only supplied unresolved statute evidence. Do not
   search for `missing_fact` or `scope_excess`. Center each request on one
   unsatisfied atomic completion requirement, and vary a material legal relation
   rather than paraphrasing a prior query. When an unresolved critical item's
   Korean description and completion requirement repeat a distinctive factual or
   effect phrase, preserve one such literal phrase in its explicit `query_terms`;
   do not rely on copied question context. Stay within the supplied budget.
7. Compact descriptive prose, not the structural evidence coverage. Use one
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

## Epistemic neutrality

Keep evidence obligations and retrieval hypotheses distinct. Do not present a legal answer, article, paragraph, condition, deadline, or threshold absent from the question as established fact; a court, agency, actor, or procedure name alone is not a statute hint. Preserve explicit independent outputs and genuinely distinct rules, exceptions, cross-references, and legal effects without inventing extra lanes. GAP queries remain tied to the supplied unresolved item. A candidate cross-reference proves provenance, not relevance: use its numeric pinpoint only when its supplied excerpt matches every material component stated in the unresolved completion requirement, including subject/actor, act, trigger/qualifier, and legal effect as applicable. A partial component overlap is insufficient. Do not promote a literal range that excludes the requirement's relevant root. Otherwise use a neutral semantic query. Preserve a supplied cross-reference pinpoint when that direct match is present.
