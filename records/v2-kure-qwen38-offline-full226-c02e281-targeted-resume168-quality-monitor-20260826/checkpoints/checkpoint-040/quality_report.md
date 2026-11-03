# C02 targeted-resume quality checkpoint

This is a quality-only projection of the frozen evaluator output. It deliberately omits efficiency, latency, throughput, and speed metrics.

- Completed prefix: `40`
- Source task sequence SHA-256: `912cbc7da44273ec26e060cdb1219415de71a8fa13d546d73e17422c880559fa`
- Citation integrity: `32/32` (rate `1.0`)

## Outcome counts

- `ABSTAIN`: 4
- `ANSWER`: 32
- `EXECUTION_FAILURE`: 4

## Provision evidence

- Macro precision / recall / F1: `0.7446428571428572` / `0.7458333333333333` / `0.7316666666666667`
- Micro precision / recall / F1: `0.7380952380952381` / `0.7380952380952381` / `0.7380952380952381`
- Exact match count / rate: `20` / `0.5`
- Complete evidence count / rate: `24` / `0.6`

## Token F1

- Answered only: `0.39393148846508047`
- Candidate (all outcomes / available only / normal outcomes): `0.3302920949938316` / `0.3774766799929504` / `0.36699121665981294`
- End-to-end: `0.3151451907720644`

The complete frozen evaluator aggregate, including its non-quality fields, is preserved separately under `evaluator_full/aggregate.json`.
