# S3 contract

## Authorization

`GENERATE_ANSWER` requires harness action `GENERATE`, the supplied answer scope,
and citable accepted provisions for every answered critical item. An uncovered or
conflicting critical item may belong only to a deferred limited-answer target.

`GENERATE_BENCHMARK_CANDIDATE` requires its diagnostic authorization, uses only
`candidate_provisions`, and remains non-publishable. It cannot change public
`ABSTAIN`. With `candidate_answer_basis: question_only`, return an uncited
diagnostic answer with empty `claims` and `claim_citations`.

## Success output

- `answer`: a conclusion-first Korean public answer of 1--3 short sentences, at most 800 characters and preferably 300--500. It contains the legal conclusion, any outcome-changing condition, and only the minimum statutory basis needed to understand that conclusion.
- `claims[]`: the complete audit list of cited substantive legal claims, classified as `legal_rule`, `application`, `exception`, `procedure`, or `remedy`. Audit claims need not all appear in the public answer.
- Every claim identifies its answer target(s). In `limited` mode, no claim may identify a deferred target; the answer must instead state its deferral as a non-substantive limitation.
- `claim_citations[]`: the complete audit list of claim-to-accepted-provision links with exact source excerpts.
- `assumptions[]`: audit facts treated as assumptions rather than established facts.
- `limitations[]`: audit boundaries of the statutory answer.

Every `claims[]` item must set `citation_required: true` and have at least one citation. Uncited factual or limitation prose belongs in `assumptions[]` or `limitations[]`; only an outcome-changing condition is repeated briefly in `answer`. The harness does not append all audit claims, assumptions, or limitations to the public answer. The model owns claim text, claim-to-provision selection, applicability, and support descriptions; the harness owns sequential claim/citation IDs, full-text snapshots, marker values, prioritized public-claim selection, and final answer rendering.

The deterministic public serializer selects at most three audit claims in this order: the first conclusion claim, conditional claims, legal-rule claims, then remaining claims. It renders only those selected claim texts and their harness-owned citation markers. All unselected claims and every assumption and limitation remain available in the structured record.

## Grounding

Use no provision outside the mode's supplied provision set. Citation excerpts
must occur in the supplied text. The harness owns transport IDs, full snapshots,
citation markers, answer serialization, and deterministic citation validation.
It renders conclusion claims first and retains material assumptions and
limitations after them.

On failed preconditions, use the schema error envelope with `INVALID_INPUT`,
`GENERATION_NOT_AUTHORIZED`, `UNCOVERED_CRITICAL_EVIDENCE`, or
`CONTRACT_UNSATISFIABLE`. An S3 error is `EXECUTION_FAILURE`, not `ABSTAIN`.
