# Legal Harness development-run evaluation

- Questions: 20
- Supported-answer yield: 0.8500
- Provision micro P/R/F1: 0.7879 / 0.7027 / 0.7429
- Latency median/p95: 242653.564 ms / 558117.188 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 17 | 0.8500 |
| ABSTAIN | 3 | 0.1500 |
| EXECUTION_FAILURE | 0 | 0.0000 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 36.88 | 20 | 0 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 36.88 | 20 | 0 |
| ABSTAIN only (missing = 0) | 26.15 | 3 | 0 |
| ABSTAIN candidates only (available only) | 26.15 | 3 | N/A |
| Available candidates only | 36.88 | 20 | N/A |

- Potential over-abstention exact matches@800: 0 / 3 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 20 | 15 | 0 | 2 | 3 | 0 | 74.29 | 50.00 | 32.96 | N/A | 38.77 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9459 | 0.9000 | available |
| rrf_at_100 | 0.9459 | 0.9000 | available |
| bge_at_10 | 0.8919 | 0.8000 | available |
| bge_at_20 | 0.8919 | 0.8000 | available |
| bge_at_30 | 0.8919 | 0.8000 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 6 | 0 | 0 | 1.0000 |
| 2 | 9 | 2 | 0 | 0.8182 |
| 3 | 2 | 1 | 0 | 0.6667 |
