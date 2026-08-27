# S3 contract

## Authorization

`GENERATE_ANSWER` requires harness action `GENERATE`, the supplied answer scope,
and citable accepted provisions for every answered critical item. An uncovered or
conflicting critical item may belong only to a deferred limited-answer target.

`GENERATE_BENCHMARK_CANDIDATE` requires its diagnostic authorization, uses only
`candidate_provisions`, and remains non-publishable. It cannot change public
`ABSTAIN`. With `candidate_answer_basis: question_only`, return an uncited
diagnostic answer with empty `claims` and `claim_citations`.

## Canonical normalized success output

This section describes the post-normalization record used by the canonical validator; the prompt's raw compact transport schema controls model emission.

- `answer`: a conclusion-first Korean public answer of 1--3 short sentences, at most 800 characters and preferably 80--250. It contains the legal conclusion, any outcome-changing condition, and only the minimum statutory basis needed to understand that conclusion.
- `claims[]`: the complete audit list of cited substantive legal claims, classified as `legal_rule`, `application`, `exception`, `procedure`, or `remedy`. Each claim has `public_role` of `conclusion` or `audit`; one to three conclusion claims cover every answered target and are the only claims rendered publicly. For `GENERATE_ANSWER` under the required public conclusion contract, require a citation-supported, target-level `application` claim with `public_role: conclusion` only when exactly one answered target is a `legal_conclusion`, exactly one critical `required_evidence_items[]` item is linked to it, at least two public conclusion `legal_rule` claims for it cite at least two different `provision_id` values, and no cited public application claim exists for it; an abstract `legal_rule` cannot satisfy that case merely by relabeling. A conditional `exception` claim attached to an answered target is likewise citation-supported and `public_role: conclusion`, never audit-only. Audit claims need not appear in the public answer.
- Every claim identifies its answer target(s). In `limited` mode, no claim may identify a deferred target; the answer must instead state its deferral as a non-substantive limitation.
- `claim_citations[]`: the complete audit list of claim-to-accepted-provision links with exact source excerpts.
- `assumptions[]`: audit facts treated as assumptions rather than established facts.
- `limitations[]`: audit boundaries of the statutory answer.

Every `claims[]` item must set `citation_required: true` and have at least one citation. Uncited factual or limitation prose belongs in `assumptions[]` or `limitations[]`; only an outcome-changing condition is repeated briefly in `answer`. The harness does not append all audit claims, assumptions, or limitations to the public answer. The model owns claim text, claim-to-provision selection, applicability, support descriptions, and conclusion-versus-audit role designation; the harness owns sequential claim/citation IDs, full-text snapshots, marker values, deterministic ordering of model-designated conclusion claims, and final answer rendering.

The deterministic public serializer renders only `public_role: conclusion` claims, ordered by answered-target order, with their harness-owned citation markers. It never falls back to first-claim or legal-rule priority; all other claims remain audit-only in the structured record. All unselected claims and every assumption and limitation remain available in the structured record.

## Grounding

Use no provision outside the mode's supplied provision set. Citation excerpts
must occur in the supplied text. The harness owns transport IDs, full snapshots,
citation markers, answer serialization, and deterministic citation validation.
It publicly renders only model-designated conclusion claims; material assumptions
and limitations remain available in the structured audit record.

## Core and auxiliary evidence boundary

`accepted_provisions[]` is the authorized union. The harness separately supplies
`core_accepted_provisions[]`, `supplemental_provisions[]`,
`qualifying_provisions[]`, and `alternative_provisions[]`; the role lists may
overlap because one provision can have distinct link roles. Every public
`conclusion` claim must cite only `core_accepted_provisions[]`. Auxiliary
provisions are authorized only for `audit` claim citations and must never be
used to establish, serialize, or rescue a public conclusion. The core evidence
set is the only coverage and governing-regime basis for publishable generation.

On failed preconditions, use the schema error envelope with `INVALID_INPUT`,
`GENERATION_NOT_AUTHORIZED`, `UNCOVERED_CRITICAL_EVIDENCE`, or
`CONTRACT_UNSATISFIABLE`. An S3 error is `EXECUTION_FAILURE`, not `ABSTAIN`.

## Target-only generation boundary

Generate only conclusions needed for the supplied, authorized requested answer targets; do not summarize every accepted provision.
Every substantive claim and citation must support a requested target, not merely a related legal topic found in an accepted provision.
An adjacent legal fact, background rule, neighboring procedure, or extra consequence is excluded unless necessary to answer that target or state its outcome-changing condition.
Keep conditional and limited behavior intact: retain the existing cited target conclusion, put unresolved conditions in the existing assumptions or limitations fields, and do not add conclusions for deferred targets.
Do not invent fields or expand scope from outside evaluation knowledge.

## Compact deterministic transport

For claim-bearing raw JSON, omit the harness-owned `answer`, citation IDs, citation markers, and full quoted text. Retain every claim, its public_role, claim-to-provision choice, claim text, target IDs, applicability, citation requirement, and short support description. The harness reconstructs only the omitted deterministic fields before unchanged validation; a question-only candidate still returns its uncited `answer`.
