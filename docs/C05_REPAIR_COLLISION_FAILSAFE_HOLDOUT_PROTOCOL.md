# C05 repair-collision fail-safe holdout protocol

This is a preregistration and source-freeze artifact for the c05
repair-induced S1 duplicate-query fail-safe. It is not a quality report.

## Development boundary and quality blinding

- Development evidence is limited to the persisted c02 ordinal 42 and 54
  failure traces (`qa_406_2hop_622` and `qa_99_1hop_167`) and deterministic
  unit fixtures derived from those traces. It must not use their gold answer,
  score, or evaluator decision fields.
- The fixed quality-blinded KoBLEX holdout is full-manifest ordinals 101--120.
  Its frozen order, IDs, and hop labels are supplied by the full manifest.
- Before the c05 source freeze, do not inspect holdout answers, status,
  accepted-provision state, evidence state, or gold/evaluator outputs for
  ordinals 101--120. Runtime code, prompts, retriever selection, and policy
  branching must never receive gold.
- Preserve the c04 source parent once as the reference run. Run fresh c05
  twice, each with an independent output root. All three runs use offline KURE
  with Qwen3.8 Q8 under the same frozen manifest and operational configuration.
- BM25 is reference-only and must never be executed. LF-Eval and ParSeR are
  excluded from execution. A ParSeR or deterministic-C5 comparison may use
  only persisted results on exactly the same question IDs.

## Scope and invariants

The change recognizes only a repair-induced history collision: an S1 GAP
request was novel before deterministic transport repair, its repaired
`query_text` matches `query_history`, and the matching request received
`neutralized_ungrounded_article_specificity` for its query text. Any raw
duplicate or other schema, ID, scope, provenance, or validator error remains
an invalid S1 output.

For a mixed plan, dispatch only remaining novel requests and recompute target
evidence IDs from those requests. For an all-collision plan, do not dispatch
retrieval or add a round; preserve the last validated S2 state and invoke the
existing `can_attempt_gap_query=False` policy. That policy may produce a
limited answer only from previously citable evidence, otherwise it abstains
with `NO_VALID_GAP_QUERY`; it must never promote a full answer.

All-collision recovery must leave query history, coverage assessments,
accepted/core/supplemental/qualifying/alternative role sets, retrieval round
count, request budget, round budget, and `no_progress_rounds` unchanged. The
trace must disclose request IDs, repaired-query hashes, and dropped/remaining
counts. Exactly the existing S1 -> retrieval -> S2 -> policy -> S3 ordering is
retained; a neutral S1 replan remains bounded to one attempt.

## Required acceptance gates

For every c05 holdout run:

- zero source, validation, and execution failures; 100% citation integrity
  among answered items;
- zero dispatches of a repair-induced duplicate query;
- raw duplicates remain invalid;
- all-collision recovery makes no retrieval/state mutation and follows only
  the existing limited-or-abstain policy; and
- mixed recovery dispatches each remaining novel request once and no dropped
  request.

Against c04 on the same 20 IDs, c05 must have non-decreasing core macro
provision F1, complete-evidence count, exact-match count, and two-hop core
recall. At least failure count or one quality metric must improve strictly.
No c04-complete item may regress. Repeat stability uses the prior frozen
thresholds: c05 status plus authorized role state agrees for at least 18 of
20 items, macro F1 differs by at most two percentage points, and complete and
exact-match counts each differ by at most one.

Comparable ParSeR or deterministic-C5 claims are permitted only for the same
IDs and persisted comparable artifacts. A pass does not authorize a broader
benchmark run until the three run records, post-run evaluation, citation audit,
collision audit, and manifest/source hashes are preserved.
