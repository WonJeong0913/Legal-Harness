# C02 targeted-resume quality checkpoint

This is a quality-only projection of the frozen evaluator output. It deliberately omits efficiency, latency, throughput, and speed metrics.

- Completed prefix: `168`
- Source task sequence SHA-256: `190af662a1c5a005dc8135f173aad29bf62ff20f18fe91922647212591177bd9`
- Citation integrity: `136/136` (rate `1.0`)

## Outcome counts

- `ABSTAIN`: 24
- `ANSWER`: 136
- `EXECUTION_FAILURE`: 8

## Provision evidence

- Macro precision / recall / F1: `0.7035997732426303` / `0.7132936507936508` / `0.6847836356764928`
- Micro precision / recall / F1: `0.6705882352941176` / `0.6867469879518072` / `0.6785714285714286`
- Exact match count / rate: `68` / `0.40476190476190477`
- Complete evidence count / rate: `90` / `0.5357142857142857`

## Token F1

- Answered only: `0.3858027064773011`
- Candidate (all outcomes / available only / normal outcomes): `0.33715956782870915` / `0.3630949192001483` / `0.35401754622014464`
- End-to-end: `0.3123164766721009`

The complete frozen evaluator aggregate, including its non-quality fields, is preserved separately under `evaluator_full/aggregate.json`.
