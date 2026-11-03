# Legal Harness development-run evaluation

- Questions: 20
- Supported-answer yield: 0.7500
- Provision micro P/R/F1: 0.6970 / 0.6216 / 0.6571
- Latency median/p95: 198814.073 ms / 339791.291 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 15 | 0.7500 |
| ABSTAIN | 1 | 0.0500 |
| EXECUTION_FAILURE | 4 | 0.2000 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 30.65 | 16 | 4 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 38.31 | 16 | 0 |
| ABSTAIN only (missing = 0) | 18.87 | 1 | 0 |
| ABSTAIN candidates only (available only) | 18.87 | 1 | N/A |
| Available candidates only | 38.31 | 16 | N/A |

- Potential over-abstention exact matches@800: 0 / 1 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 20 | 15 | 0 | 0 | 1 | 4 | 65.71 | 50.00 | 29.70 | N/A | 39.60 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 1.0000 | 1.0000 | available |
| rrf_at_100 | 1.0000 | 1.0000 | available |
| bge_at_10 | 0.8889 | 0.8125 | available |
| bge_at_20 | 0.9259 | 0.8750 | available |
| bge_at_30 | 0.9259 | 0.8750 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 6 | 0 | 0 | 1.0000 |
| 2 | 8 | 1 | 2 | 0.7273 |
| 3 | 1 | 0 | 2 | 0.3333 |
