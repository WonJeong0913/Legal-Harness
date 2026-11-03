# Legal Harness development-run evaluation

- Questions: 40
- Supported-answer yield: 0.9000
- Provision micro P/R/F1: 0.6310 / 0.7067 / 0.6667
- Latency median/p95: 259244.807 ms / 555911.459 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 36 | 0.9000 |
| ABSTAIN | 4 | 0.1000 |
| EXECUTION_FAILURE | 0 | 0.0000 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 36.22 | 40 | 0 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 36.22 | 40 | 0 |
| ABSTAIN only (missing = 0) | 20.59 | 4 | 0 |
| ABSTAIN candidates only (available only) | 20.59 | 4 | N/A |
| Available candidates only | 36.22 | 40 | N/A |

- Potential over-abstention exact matches@800: 0 / 4 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 40 | 30 | 0 | 6 | 4 | 0 | 66.67 | 42.50 | 34.16 | N/A | 37.95 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9333 | 0.8750 | available |
| rrf_at_100 | 0.9333 | 0.8750 | available |
| bge_at_10 | 0.8800 | 0.7750 | available |
| bge_at_20 | 0.9067 | 0.8250 | available |
| bge_at_30 | 0.9067 | 0.8250 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 11 | 1 | 0 | 0.9167 |
| 2 | 20 | 2 | 0 | 0.9091 |
| 3 | 5 | 1 | 0 | 0.8333 |
