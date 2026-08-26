# Checkpoint20 single-issue round-merge analysis

Development-only, offline counterfactual analysis of the immutable 20-question
checkpoint20 trace. It reads persisted `retrieval_stages.jsonl` sidecars plus
the static dataset/corpus to score candidate completeness; it does not replay
retrieval, reranking, skills, generation, ParSeR, or LF-Eval.

Input batch:
`/workspace/Legal-Harness/records/v2-kure-qwen38-offline-full226-20260825-c02e281-deterministic-ties/full226/checkpoints/batch-020-attempt-8861c939c5554d15a46558a25d1f0611`

| Variant | Complete | Gains | Losses |
| --- | ---: | --- | --- |
| Observed trace | 12/20 | — | — |
| Later-round single-issue issue-fusion top10 | 14/20 | qa192, qa312 | none |
| Later-round single-issue guarded fusion rank <=2 promotion | 12/20 | none | none |

The supported rule is an opt-in mode, `single_issue_fusion_top_k`. It applies
only with per-round candidate budgeting, per-request reranking, a retrieval
round after round one, and exactly one active issue. It retains that issue's
already-produced quota-aware issue selection order (critical-evidence picks,
then issue-fusion fill) rather than applying a second global raw-score cutoff
to scores drawn from distinct request-query scales. On all 12 eligible
checkpoint20 rounds, that selected top10 exactly matched fusion ranks 1–10.
Round one and multi-issue rounds retain the existing selection path.

Evidence for the two gains:

- `qa_192_2hop_334`: round 3 has only issue `I2`; `형법 229조` is issue-fusion
  rank 8 and is retained by fusion top10.
- `qa_312_2hop_499`: round 2 has only issue `I2`; `민법 842조` is issue-fusion
  rank 5 and is retained by fusion top10.

`qa_49_2hop_192_rand` remains complete and unchanged because it completes in
round one, outside the guard. This same-input development result is not a
held-out answer-quality claim and must not replace the official benchmark
score.
