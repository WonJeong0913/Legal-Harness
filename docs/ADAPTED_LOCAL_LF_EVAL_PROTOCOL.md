# Adapted local Qwen LF-Eval protocol

> **Note (2026-11):** This document describes the first version, which compared a C36 KURE output with ParSeR. Later commits extended the same postprocessor to C02 inputs (`a839228`) and to a three-condition C02 KURE / C02 BM25s / ParSeR comparison (`scripts/run_adapted_local_lf_eval_bm25s.py`, `c1eb0c4`). The results summarized in the root README come from these later records.

`scripts/run_adapted_local_lf_eval.py` is a postprocessing-only comparison of a
completed C36 KURE `full226/` output and the completed reproduced ParSeR
`final_results.jsonl`. It is not the official KoBLEX LF-Eval: the official
implementation uses DeepEval with an external GPT-4o judge. The local artifact
therefore identifies itself as `ADAPTED_LOCAL_QWEN38_LF_EVAL`, records
`score_equivalence: FORBIDDEN`, and cannot be supplied to the harness's
`--lf-eval-scores` import.

It uses the frozen `legal-harness-qwen38-q8` alias only after verifying the
loopback endpoint, Ollama manifest metadata, and local blob SHA-256. Every
request has `temperature=0` and `seed=0`. The official rubric and prediction
projection (`answer.split("<\think>")[0][:800]`, including the source's literal
escape behavior) are recorded by SHA-256 in the output provenance.

The tool rejects non-PASS C36 runs, any roster/gold question/gold answer/gold
context mismatch, duplicate IDs, and attempts to write inside or overwrite an
input artifact. It emits C36-frozen roster order, preserves the raw ParSeR
input-order hash, and records per-question/aggregate ParSeR-minus-KURE deltas.
Published KURE ABSTAINs and both conditions' execution failures receive an
explicit unjudged zero only in end-to-end public-answer aggregation. KURE
`candidate_answer` is evaluated independently; its availability is never
presented as a public answer.

Example, after the two primary full226 artifacts are complete:

```bash
python3 scripts/run_adapted_local_lf_eval.py \
  --kure-output-root /path/to/c36-output \
  --parser-results /path/to/koblex-parser-reproduced/final_results.jsonl \
  --output-dir /path/to/new-adapted-local-lf-eval-output
```

This command never invokes BM25, ParSeR, or the C36 KURE pipeline, and it never
modifies their artifacts or injects a score into the primary evaluation.
