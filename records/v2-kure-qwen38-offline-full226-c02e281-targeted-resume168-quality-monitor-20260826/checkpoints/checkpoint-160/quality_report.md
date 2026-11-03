# C02 targeted-resume quality checkpoint

This is a quality-only projection of the frozen evaluator output. It deliberately omits efficiency, latency, throughput, and speed metrics.

- Completed prefix: `160`
- Source task sequence SHA-256: `7221b31bd6a0387bbe76aaf85e3a12ae1b4cb27628ba83670d24b1bf42b01011`
- Citation integrity: `131/131` (rate `1.0`)

## Outcome counts

- `ABSTAIN`: 21
- `ANSWER`: 131
- `EXECUTION_FAILURE`: 8

## Provision evidence

- Macro precision / recall / F1: `0.7180505952380952` / `0.7270833333333333` / `0.6988144841269841`
- Micro precision / recall / F1: `0.697452229299363` / `0.6996805111821086` / `0.6985645933014353`
- Exact match count / rate: `67` / `0.41875`
- Complete evidence count / rate: `89` / `0.55625`

## Token F1

- Answered only: `0.39268712015683077`
- Candidate (all outcomes / available only / normal outcomes): `0.3448761642878495` / `0.3728390965274049` / `0.3630275413556311`
- End-to-end: `0.3215125796284052`

The complete frozen evaluator aggregate, including its non-quality fields, is preserved separately under `evaluator_full/aggregate.json`.
