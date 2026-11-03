# Legal Harness development-run evaluation

- Questions: 8
- Supported-answer yield: 0.8750
- Provision micro P/R/F1: 0.5200 / 0.7647 / 0.6190
- Latency median/p95: 170025.848 ms / 204007.354 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 7 | 0.8750 |
| ABSTAIN | 1 | 0.1250 |
| EXECUTION_FAILURE | 0 | 0.0000 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 32.94 | 8 | 0 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 32.94 | 8 | 0 |
| ABSTAIN only (missing = 0) | 0.00 | 1 | 0 |
| ABSTAIN candidates only (available only) | 0.00 | 1 | N/A |
| Available candidates only | 32.94 | 8 | N/A |

- Potential over-abstention exact matches@800: 0 / 1 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 8 | 5 | 0 | 2 | 1 | 0 | 61.90 | 25.00 | 32.94 | N/A | 37.65 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 1.0000 | 1.0000 | available |
| rrf_at_100 | 1.0000 | 1.0000 | available |
| bge_at_10 | 1.0000 | 1.0000 | available |
| bge_at_20 | 1.0000 | 1.0000 | available |
| bge_at_30 | 1.0000 | 1.0000 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 0 | 1 | 0 | 0.0000 |
| 2 | 5 | 0 | 0 | 1.0000 |
| 3 | 2 | 0 | 0 | 1.0000 |
