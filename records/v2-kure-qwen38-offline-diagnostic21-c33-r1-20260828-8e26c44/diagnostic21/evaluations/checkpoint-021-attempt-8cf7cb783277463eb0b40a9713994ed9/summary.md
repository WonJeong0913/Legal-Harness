# Legal Harness development-run evaluation

- Questions: 21
- Supported-answer yield: 0.8095
- Provision micro P/R/F1: 0.7647 / 0.6500 / 0.7027
- Latency median/p95: 136526.300 ms / 321297.969 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 17 | 0.8095 |
| ABSTAIN | 4 | 0.1905 |
| EXECUTION_FAILURE | 0 | 0.0000 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 38 | 1.810 |
| Core (scored) | 34 | 1.619 |
| Supplemental | 1 | 0.048 |
| Qualifying | 2 | 0.095 |
| Alternative | 1 | 0.048 |
| Auxiliary union | 4 | 0.190 |

- Role-schema records: 21; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 2 across 2 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 30.76 | 21 | 0 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 30.76 | 21 | 0 |
| ABSTAIN only (missing = 0) | 19.79 | 4 | 0 |
| ABSTAIN candidates only (available only) | 19.79 | 4 | N/A |
| Available candidates only | 30.76 | 21 | N/A |

- Potential over-abstention exact matches@800: 0 / 4 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 21 | 10 | 1 | 6 | 4 | 0 | 70.27 | 28.57 | 26.99 | N/A | 33.34 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9250 | 0.8571 | available |
| rrf_at_100 | 0.9250 | 0.8571 | available |
| bge_at_10 | 0.7250 | 0.5238 | available |
| bge_at_20 | 0.8000 | 0.6190 | available |
| bge_at_30 | 0.8750 | 0.7619 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 6 | 2 | 0 | 0.7500 |
| 2 | 6 | 2 | 0 | 0.7500 |
| 3 | 5 | 0 | 0 | 1.0000 |
