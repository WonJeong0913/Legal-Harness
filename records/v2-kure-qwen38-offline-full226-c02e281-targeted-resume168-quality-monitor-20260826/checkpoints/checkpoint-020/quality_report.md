# C02 targeted-resume quality checkpoint

This is a quality-only projection of the frozen evaluator output. It deliberately omits efficiency, latency, throughput, and speed metrics.

- Completed prefix: `20`
- Source task sequence SHA-256: `cfaa5ca3cc6599b02a41420a97efaefd331a5067cb63a228339e2ef2f4508e87`
- Citation integrity: `16/16` (rate `1.0`)

## Outcome counts

- `ABSTAIN`: 1
- `ANSWER`: 16
- `EXECUTION_FAILURE`: 3

## Provision evidence

- Macro precision / recall / F1: `0.7583333333333333` / `0.7` / `0.7116666666666667`
- Micro precision / recall / F1: `0.7567567567567568` / `0.7` / `0.7272727272727273`
- Exact match count / rate: `8` / `0.4`
- Complete evidence count / rate: `10` / `0.5`

## Token F1

- Answered only: `0.38333998198369035`
- Candidate (all outcomes / available only / normal outcomes): `0.31312359849017807` / `0.36838070410609186` / `0.36838070410609186`
- End-to-end: `0.30667198558695224`

The complete frozen evaluator aggregate, including its non-quality fields, is preserved separately under `evaluator_full/aggregate.json`.
