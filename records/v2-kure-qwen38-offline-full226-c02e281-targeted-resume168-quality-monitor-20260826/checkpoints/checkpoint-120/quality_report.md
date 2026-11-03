# C02 targeted-resume quality checkpoint

This is a quality-only projection of the frozen evaluator output. It deliberately omits efficiency, latency, throughput, and speed metrics.

- Completed prefix: `120`
- Source task sequence SHA-256: `209d972f1cc798b1395517c37a0278633fc09ce709cf9d04676928edf8c91bc0`
- Citation integrity: `98/98` (rate `1.0`)

## Outcome counts

- `ABSTAIN`: 15
- `ANSWER`: 98
- `EXECUTION_FAILURE`: 7

## Provision evidence

- Macro precision / recall / F1: `0.7135119047619047` / `0.7180555555555556` / `0.6937433862433863`
- Micro precision / recall / F1: `0.6991525423728814` / `0.6962025316455697` / `0.6976744186046512`
- Exact match count / rate: `52` / `0.43333333333333335`
- Complete evidence count / rate: `67` / `0.5583333333333333`

## Token F1

- Answered only: `0.3889452118409054`
- Candidate (all outcomes / available only / normal outcomes): `0.33773767806776145` / `0.36844110334664887` / `0.358659481133906`
- End-to-end: `0.31763858967007275`

The complete frozen evaluator aggregate, including its non-quality fields, is preserved separately under `evaluator_full/aggregate.json`.
