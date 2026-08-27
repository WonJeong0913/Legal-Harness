# C02 KURE + Qwen3.8 Q8_0 full226

This directory records the frozen C02 evaluation over all 226 KoBLEX test
questions. It is a compact result bundle: evaluator outputs, the combined
batch manifest, source-row audit hashes, and the frozen execution plan are
included; the 62 MB raw run directories and local model weights are not.

## Frozen configuration

- Evaluated source commit: `c02e2818ad54e9d5a1a9bd02b604e987192bb244`
- Evaluated source tree: `9fcb0ebceb0b3d96955f1626f2c952a457be930f`
- Condition: `V2-KURE-offline-full226-Qwen3.8-Q8_0`
- Primary retriever: KURE (`nlpai-lab/KURE-v1`)
- Model alias: `legal-harness-qwen38-q8`
- Model artifact: `Qwen3.8-27B-Q8_0.gguf`, observed 26.9B Q8_0
- Model blob SHA-256: `f5c702d8820d36fb55985bb238fc83ee3a313e920f4b752a437c3a6a9e14e4c8`
- Seed: `0`; context: `32768`; Ollama parallelism: `1`
- Offline flags were enabled. BM25 and ParSeR execution were forbidden; the
  paired BM25 manifest was read-only configuration metadata.
- LF-Eval was deliberately not provided or executed. LF-Eval fields are
  therefore `N/A`, not zero.

The exact configuration and provenance hashes are in `execution-plan.json`.

## Result

| Metric | C02 |
| --- | ---: |
| Questions | 226 |
| ANSWER / ABSTAIN / EXECUTION_FAILURE | 189 / 29 / 8 |
| Supported-answer yield | 83.63% |
| Provision macro precision / recall / F1 | 72.263 / 72.788 / 70.224 |
| Provision micro precision / recall / F1 | 67.982 / 69.977 / 68.966 |
| Provision exact match | 95 / 226 (42.035%) |
| Complete evidence | 125 / 226 (55.310%) |
| Token-F1@800, end-to-end | 32.518 |
| Token-F1@800, answered rows | 38.884 |
| Citation-integrity pass | 189 / 189 |

Retrieval-stage metrics cover the 218 non-failure rows with stage provenance.
The eight execution failures are part of all end-to-end denominators.

## Composition and caveats

This is an immutable merge of 58 rows from the original checkpoint, two
targeted retry rows, and 166 targeted-resume rows. All 226 selected rows point
to the same frozen source commit/tree and configuration. `audit/source-row-map.json`
records every selection and source artifact hash.

This is a development result, not a hidden-test or official leaderboard
submission. The result contains eight execution failures. Latency fields are
retained because the evaluator emitted them, but this combined/resumed run was
not designed as a controlled speed comparison and latency should not be used
as benchmark evidence.

The evaluator metadata and per-question CSV preserve original absolute record
paths for auditability. Those raw paths are not portable and the underlying
run directories are intentionally not duplicated in this compact bundle.

## Validation

The evaluator was rerun offline from a clean worktree at the evaluated commit,
without LF-Eval input. The regenerated `aggregate.json`, `per_question.csv`,
and `summary.md` matched the committed files byte-for-byte.

- Rows: 226; ordinals: 1 through 226, all unique
- Unique question IDs: 226; unique run IDs: 226
- Retriever values: KURE only; seed values: `0` only
- CSV, combined manifest, and source-row-map order: exact match
- Outcome counts recomputed from CSV: 189 / 29 / 8
- Gold / predicted / true positive: 443 / 456 / 310
- LF-Eval score cells populated: 0
- Evaluator warnings: 0

Re-evaluate after restoring the KoBLEX dataset and normalized statute corpus
whose hashes are recorded in `metadata.json`:

```bash
python3 scripts/evaluate_dev_runs.py \
  --batch-dir records/evaluations/kure-c02-qwen38-q8-full226-20260826/batch \
  --dataset data/koblex/qa/test-00000-of-00001.parquet \
  --corpus data/koblex/normalized/statute.jsonl \
  --output-dir /tmp/legal-harness-c02-reevaluation \
  --require-stage-provenance
```

The regenerated metadata timestamp will differ. The three substantive output
files above should retain the hashes listed in `SHA256SUMS`.

## Bundle contents

- `aggregate.json`, `metadata.json`, `per_question.csv`, `summary.md`: frozen
  evaluator outputs.
- `batch/`: combined 226-row manifest, metadata, and evaluator summary input.
- `audit/`: immutable merge receipt and per-row/source hashes.
- `execution-plan.json`: original frozen run configuration and provenance.
- `SHA256SUMS`: integrity hashes for every imported artifact.
