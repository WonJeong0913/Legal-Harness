# Legal Harness development-run evaluation

- Questions: 40
- Supported-answer yield: 0.8750
- Provision micro P/R/F1: 0.7000 / 0.7467 / 0.7226
- Latency median/p95: 327963.565 ms / 753549.976 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 35 | 0.8750 |
| ABSTAIN | 5 | 0.1250 |
| EXECUTION_FAILURE | 0 | 0.0000 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 32.60 | 38 | 2 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 32.60 | 38 | 2 |
| ABSTAIN only (missing = 0) | 19.63 | 3 | 2 |
| ABSTAIN candidates only (available only) | 32.72 | 3 | N/A |
| Available candidates only | 34.32 | 38 | N/A |

- Potential over-abstention exact matches@800: 0 / 5 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 40 | 30 | 0 | 5 | 5 | 0 | 72.26 | 45.00 | 30.15 | N/A | 34.46 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9333 | 0.8750 | available |
| rrf_at_100 | 0.9333 | 0.8750 | available |
| bge_at_10 | 0.8533 | 0.7500 | available |
| bge_at_20 | 0.9067 | 0.8250 | available |
| bge_at_30 | 0.9067 | 0.8250 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 9 | 3 | 0 | 0.7500 |
| 2 | 20 | 2 | 0 | 0.9091 |
| 3 | 6 | 0 | 0 | 1.0000 |
