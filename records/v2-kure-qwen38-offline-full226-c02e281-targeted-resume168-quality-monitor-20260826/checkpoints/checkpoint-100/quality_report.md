# C02 targeted-resume quality checkpoint

This is a quality-only projection of the frozen evaluator output. It deliberately omits efficiency, latency, throughput, and speed metrics.

- Completed prefix: `100`
- Source task sequence SHA-256: `0d497bd4a2764ad62c04a0da007aa66f7298debc679fcc8e1191dddb9d2a6996`
- Citation integrity: `81/81` (rate `1.0`)

## Outcome counts

- `ABSTAIN`: 12
- `ANSWER`: 81
- `EXECUTION_FAILURE`: 7

## Provision evidence

- Macro precision / recall / F1: `0.7048809523809524` / `0.7166666666666667` / `0.6894444444444444`
- Micro precision / recall / F1: `0.7076923076923077` / `0.700507614213198` / `0.7040816326530612`
- Exact match count / rate: `45` / `0.45`
- Complete evidence count / rate: `59` / `0.59`

## Token F1

- Answered only: `0.3948363543987334`
- Candidate (all outcomes / available only / normal outcomes): `0.34018590750740196` / `0.37383066759055156` / `0.36579129839505586`
- End-to-end: `0.31981744706297405`

The complete frozen evaluator aggregate, including its non-quality fields, is preserved separately under `evaluator_full/aggregate.json`.
