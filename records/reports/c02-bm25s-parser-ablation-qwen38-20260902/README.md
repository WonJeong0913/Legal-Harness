# C02 ParSeR-style BM25s ablation with local Qwen LF evaluation

Status: complete (`226/226`)

This branch publishes an isolated first-stage retrieval ablation for Legal-Harness C02. The C02 harness, BGE reranker, answer policy, and `legal-harness-qwen38-q8` model were held fixed; only the first-stage retriever was changed from KURE to a ParSeR-compatible `bm25s` implementation.

## Frozen configuration

- C02 source baseline: `c02e2818ad54e9d5a1a9bd02b604e987192bb244`
- BM25s executable source: `edc9da4746b87cde61d967f0d8730cb8c9373649`
- Linked LF postprocessor: `c1eb0c4a18e7ee58d00dc893d3a326246eab726c`
- Model: `legal-harness-qwen38-q8:latest`
- Model manifest digest: `91f49c230b9d1fd034414b1035b361cfe4ad1c89f7076012b10420edea8b78ff`
- Model blob SHA256: `f5c702d8820d36fb55985bb238fc83ee3a313e920f4b752a437c3a6a9e14e4c8`
- Judge settings: temperature `0`, seed `0`
- Canonical roster SHA256: `3d1886c27f618b452b1c1d05533e9fb55cb1aa6ed5f0d984dbeac25b8931dfca`
- QA parquet SHA256: `afdaff3a8000cdf5e0a64adbcfc8e6aff0042b318bf03718155f2b70f551c47b`
- BM25s: version `0.3.10`, ordered Top100, no first-stage provision deduplication, no FTS5 expansion, no statute-hint recall channel

Exact ordered Top100 parity against the saved ParSeR `Bm25Retriever` was checked on three real C02 queries before the full run.

## Same-harness retrieval ablation

| Metric | C02 KURE | C02 ParSeR-style BM25s | BM25s minus KURE |
|---|---:|---:|---:|
| ANSWER | 189 | 145 | -44 |
| ABSTAIN | 29 | 64 | +35 |
| Execution failure | 8 | 17 | +9 |
| First-stage Top100 provision recall | 92.74% | 72.79% | -19.95 pp |
| First-stage Top100 complete-evidence recall | 87.16% | 60.29% | -26.87 pp |
| BGE Top10 provision recall | 81.03% | 64.46% | -16.57 pp |
| Provision precision | 67.98% | 68.47% | +0.48 pp |
| Provision recall | 69.98% | 54.40% | -15.58 pp |
| Provision micro-F1 | 68.97% | 60.63% | -8.34 pp |
| Provision exact match | 42.04% | 28.76% | -13.27 pp |
| Token-F1@800 end-to-end | 32.52% | 24.40% | -8.12 pp |
| Token-F1@800 answered-only | 38.88% | 38.03% | -0.85 pp |

The precision is essentially unchanged. The main loss is recall and complete-evidence coverage, which propagates into more abstentions and lower end-to-end quality.

## Adapted local Qwen LF evaluation

| Condition | Public scored | Public answered-only /10 | Public E2E /10 | Candidate scored | Candidate available-only /10 | Candidate E2E /10 |
|---|---:|---:|---:|---:|---:|---:|
| OUR_C02_KURE | 189 | 7.503 | 6.274 | 214 | 7.117 | 6.739 |
| OUR_C02_BM25S_PARSER_FIRST_STAGE | 145 | 6.993 | 4.487 | 177 | 6.718 | 5.261 |
| PARSER_REPRODUCED | 220 | 6.409 | 6.239 | 220 | 6.409 | 6.239 |

BM25s answers that survive are reasonably strong, but their lower coverage produces a much lower public E2E score. KURE exceeds BM25s by `+1.788` public E2E points. BM25s exceeds reproduced ParSeR by `+0.584` on answered-only quality but trails it by `-1.752` E2E points.

This is an adapted local Qwen evaluation using the frozen KoBLEX projection and rubric. It is deliberately marked as **not equivalent** to the official GPT-4o/DeepEval LF-Eval.

## Failure accounting

All 17 BM25s execution failures are durable harness outcomes, not GPU, timeout, launcher, or infrastructure failures:

- `GAP_QUERY_PLAN`: 13
- `COVERAGE`: 2
- `INITIAL_PLAN`: 2

## Published artifacts

- [BM25s full226 plan](../../c02-bm25s-parser-full226-20260901-r1/plan.json)
- [BM25s full226 final status](../../c02-bm25s-parser-full226-20260901-r1/final.json)
- [BM25s final checkpoint](../../c02-bm25s-parser-full226-20260901-r1/checkpoints/checkpoint-226.json)
- [BM25s batch summary](../../c02-bm25s-parser-full226-20260901-r1/batch/summary.jsonl)
- [BM25s offline aggregate](../../evaluations/c02-bm25s-parser-full226-20260902-r1/aggregate.json)
- [KURE comparable offline aggregate](../../evaluations/c02-kure-full226-comparable-20260902-r1/aggregate.json)
- [Three-condition local LF aggregate](../../adapted-local-qwen38-lf-eval-c02-bm25s-linked-r1-20260902/aggregate.json)
- [Local LF per-question records](../../adapted-local-qwen38-lf-eval-c02-bm25s-linked-r1-20260902/per_question.jsonl)
- [Local LF judge journal](../../adapted-local-qwen38-lf-eval-c02-bm25s-linked-r1-20260902/judge_journal.jsonl)
- [Local LF receipt](../../adapted-local-qwen38-lf-eval-c02-bm25s-linked-r1-20260902/receipt.json)
- [BM25s ablation runner](../../../scripts/run_c02_bm25s_ablation.py)
- [Linked local LF runner](../../../scripts/run_adapted_local_lf_eval_bm25s.py)

The approximately 250 MB of raw per-run retrieval traces remains preserved locally and is intentionally excluded from Git. The full batch summary, all per-question offline metrics, all local LF per-question records, the judge journal, final checkpoints, and cryptographic receipts are included in this branch.
