# Legal Harness development-run evaluation

- Questions: 60
- Supported-answer yield: 0.8833
- Provision micro P/R/F1: 0.6917 / 0.7281 / 0.7094
- Latency median/p95: 256199.361 ms / 526627.662 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 53 | 0.8833 |
| ABSTAIN | 5 | 0.0833 |
| EXECUTION_FAILURE | 2 | 0.0333 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 36.92 | 58 | 2 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 38.19 | 58 | 0 |
| ABSTAIN only (missing = 0) | 22.58 | 5 | 0 |
| ABSTAIN candidates only (available only) | 22.58 | 5 | N/A |
| Available candidates only | 38.19 | 58 | N/A |

- Potential over-abstention exact matches@800: 0 / 5 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 60 | 42 | 0 | 11 | 5 | 2 | 70.94 | 45.00 | 35.04 | N/A | 39.66 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9550 | 0.9138 | available |
| rrf_at_100 | 0.9459 | 0.8966 | available |
| bge_at_10 | 0.8919 | 0.7931 | available |
| bge_at_20 | 0.9189 | 0.8448 | available |
| bge_at_30 | 0.9279 | 0.8621 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 15 | 1 | 1 | 0.8824 |
| 2 | 30 | 3 | 1 | 0.8824 |
| 3 | 8 | 1 | 0 | 0.8889 |
