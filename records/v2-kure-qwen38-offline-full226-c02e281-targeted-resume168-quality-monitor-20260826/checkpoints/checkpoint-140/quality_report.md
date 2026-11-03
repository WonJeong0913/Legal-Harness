# C02 targeted-resume quality checkpoint

This is a quality-only projection of the frozen evaluator output. It deliberately omits efficiency, latency, throughput, and speed metrics.

- Completed prefix: `140`
- Source task sequence SHA-256: `be83024274c0b3dc4f6247317a68ae674ba2a712a0563e0da612c542b5d75aba`
- Citation integrity: `117/117` (rate `1.0`)

## Outcome counts

- `ABSTAIN`: 16
- `ANSWER`: 117
- `EXECUTION_FAILURE`: 7

## Provision evidence

- Macro precision / recall / F1: `0.7170578231292517` / `0.7285714285714285` / `0.699359410430839`
- Micro precision / recall / F1: `0.6967509025270758` / `0.706959706959707` / `0.7018181818181818`
- Exact match count / rate: `60` / `0.42857142857142855`
- Complete evidence count / rate: `79` / `0.5642857142857143`

## Token F1

- Answered only: `0.3825894574593835`
- Candidate (all outcomes / available only / normal outcomes): `0.3369632652176465` / `0.3656965669028722` / `0.35469817391331215`
- End-to-end: `0.31973547516248474`

The complete frozen evaluator aggregate, including its non-quality fields, is preserved separately under `evaluator_full/aggregate.json`.
