# Legal Harness development-run evaluation

- Questions: 40
- Supported-answer yield: 0.9250
- Provision micro P/R/F1: 0.6585 / 0.7200 / 0.6879
- Latency median/p95: 227049.069 ms / 459153.791 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 37 | 0.9250 |
| ABSTAIN | 2 | 0.0500 |
| EXECUTION_FAILURE | 1 | 0.0250 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 35.90 | 39 | 1 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 36.82 | 39 | 0 |
| ABSTAIN only (missing = 0) | 11.39 | 2 | 0 |
| ABSTAIN candidates only (available only) | 11.39 | 2 | N/A |
| Available candidates only | 36.82 | 39 | N/A |

- Potential over-abstention exact matches@800: 0 / 2 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 40 | 33 | 0 | 4 | 2 | 1 | 68.79 | 40.00 | 35.33 | N/A | 38.20 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9315 | 0.8718 | available |
| rrf_at_100 | 0.9315 | 0.8718 | available |
| bge_at_10 | 0.8219 | 0.6923 | available |
| bge_at_20 | 0.9041 | 0.8205 | available |
| bge_at_30 | 0.9041 | 0.8205 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 11 | 1 | 0 | 0.9167 |
| 2 | 20 | 1 | 1 | 0.9091 |
| 3 | 6 | 0 | 0 | 1.0000 |
