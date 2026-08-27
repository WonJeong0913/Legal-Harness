# Legal Harness development-run evaluation

- Questions: 226
- Supported-answer yield: 0.8363
- Provision micro P/R/F1: 0.6798 / 0.6998 / 0.6897
- Latency median/p95: 137642.592 ms / 402128.381 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 189 | 0.8363 |
| ABSTAIN | 29 | 0.1283 |
| EXECUTION_FAILURE | 8 | 0.0354 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 34.86 | 214 | 12 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 36.14 | 214 | 4 |
| ABSTAIN only (missing = 0) | 18.29 | 25 | 4 |
| ABSTAIN candidates only (available only) | 21.21 | 25 | N/A |
| Available candidates only | 36.82 | 214 | N/A |

- Potential over-abstention exact matches@800: 0 / 29 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 226 | 148 | 0 | 41 | 29 | 8 | 68.97 | 42.04 | 32.52 | N/A | 38.88 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9274 | 0.8716 | available |
| rrf_at_100 | 0.9227 | 0.8624 | available |
| bge_at_10 | 0.8103 | 0.6743 | available |
| bge_at_20 | 0.8689 | 0.7661 | available |
| bge_at_30 | 0.8923 | 0.8073 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 47 | 8 | 2 | 0.8246 |
| 2 | 109 | 14 | 4 | 0.8583 |
| 3 | 33 | 7 | 2 | 0.7857 |
