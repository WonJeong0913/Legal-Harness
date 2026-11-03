# Legal Harness development-run evaluation

- Questions: 20
- Supported-answer yield: 0.9500
- Provision micro P/R/F1: 0.7353 / 0.6757 / 0.7042
- Latency median/p95: 213848.199 ms / 329994.697 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 19 | 0.9500 |
| ABSTAIN | 1 | 0.0500 |
| EXECUTION_FAILURE | 0 | 0.0000 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 36.91 | 20 | 0 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 36.91 | 20 | 0 |
| ABSTAIN only (missing = 0) | 18.87 | 1 | 0 |
| ABSTAIN candidates only (available only) | 18.87 | 1 | N/A |
| Available candidates only | 36.91 | 20 | N/A |

- Potential over-abstention exact matches@800: 0 / 1 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 20 | 17 | 0 | 2 | 1 | 0 | 70.42 | 50.00 | 35.96 | N/A | 37.86 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9459 | 0.9000 | available |
| rrf_at_100 | 0.9459 | 0.9000 | available |
| bge_at_10 | 0.7838 | 0.6500 | available |
| bge_at_20 | 0.8919 | 0.8000 | available |
| bge_at_30 | 0.8919 | 0.8000 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 6 | 0 | 0 | 1.0000 |
| 2 | 10 | 1 | 0 | 0.9091 |
| 3 | 3 | 0 | 0 | 1.0000 |
