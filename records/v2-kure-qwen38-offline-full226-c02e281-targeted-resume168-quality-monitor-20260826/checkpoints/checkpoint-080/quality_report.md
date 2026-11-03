# C02 targeted-resume quality checkpoint

This is a quality-only projection of the frozen evaluator output. It deliberately omits efficiency, latency, throughput, and speed metrics.

- Completed prefix: `80`
- Source task sequence SHA-256: `eeab22b717070fc1a3c3e6f495c7a09557ae87d5ac347895dffd9fd7abe676f8`
- Citation integrity: `65/65` (rate `1.0`)

## Outcome counts

- `ABSTAIN`: 9
- `ANSWER`: 65
- `EXECUTION_FAILURE`: 6

## Provision evidence

- Macro precision / recall / F1: `0.7379464285714286` / `0.75` / `0.7225`
- Micro precision / recall / F1: `0.7452229299363057` / `0.7267080745341615` / `0.7358490566037735`
- Exact match count / rate: `38` / `0.475`
- Complete evidence count / rate: `50` / `0.625`

## Token F1

- Answered only: `0.41301902716122174`
- Candidate (all outcomes / available only / normal outcomes): `0.3531333967841066` / `0.3923704408712296` / `0.3817658343611963`
- End-to-end: `0.3355779595684927`

The complete frozen evaluator aggregate, including its non-quality fields, is preserved separately under `evaluator_full/aggregate.json`.
