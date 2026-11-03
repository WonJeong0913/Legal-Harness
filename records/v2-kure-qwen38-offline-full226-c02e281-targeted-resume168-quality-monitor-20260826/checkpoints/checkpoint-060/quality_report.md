# C02 targeted-resume quality checkpoint

This is a quality-only projection of the frozen evaluator output. It deliberately omits efficiency, latency, throughput, and speed metrics.

- Completed prefix: `60`
- Source task sequence SHA-256: `bac65a48edcf6045ade8a0f58871412ba682ed80523c8d447741aa58d399b6d3`
- Citation integrity: `49/49` (rate `1.0`)

## Outcome counts

- `ABSTAIN`: 6
- `ANSWER`: 49
- `EXECUTION_FAILURE`: 5

## Provision evidence

- Macro precision / recall / F1: `0.7283730158730158` / `0.7416666666666667` / `0.715`
- Micro precision / recall / F1: `0.7317073170731707` / `0.72` / `0.7258064516129032`
- Exact match count / rate: `28` / `0.4666666666666667`
- Complete evidence count / rate: `36` / `0.6`

## Token F1

- Answered only: `0.3936616738373059`
- Candidate (all outcomes / available only / normal outcomes): `0.3353441716595789` / `0.37963491131273086` / `0.3658300054468134`
- End-to-end: `0.3214903669671331`

The complete frozen evaluator aggregate, including its non-quality fields, is preserved separately under `evaluator_full/aggregate.json`.
