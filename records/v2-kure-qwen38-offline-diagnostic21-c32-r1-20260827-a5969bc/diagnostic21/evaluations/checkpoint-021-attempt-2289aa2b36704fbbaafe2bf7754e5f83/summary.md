# Legal Harness development-run evaluation

- Questions: 21
- Supported-answer yield: 0.7619
- Provision micro P/R/F1: 0.8387 / 0.6500 / 0.7324
- Latency median/p95: 112983.148 ms / 207400.778 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 16 | 0.7619 |
| ABSTAIN | 5 | 0.2381 |
| EXECUTION_FAILURE | 0 | 0.0000 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 35 | 1.667 |
| Core (scored) | 31 | 1.476 |
| Supplemental | 3 | 0.143 |
| Qualifying | 1 | 0.048 |
| Alternative | 0 | 0.000 |
| Auxiliary union | 4 | 0.190 |

- Role-schema records: 21; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 1 across 1 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 28.66 | 21 | 0 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 28.66 | 21 | 0 |
| ABSTAIN only (missing = 0) | 19.77 | 5 | 0 |
| ABSTAIN candidates only (available only) | 19.77 | 5 | N/A |
| Available candidates only | 28.66 | 21 | N/A |

- Potential over-abstention exact matches@800: 0 / 5 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 21 | 13 | 0 | 3 | 5 | 0 | 73.24 | 33.33 | 23.95 | N/A | 31.44 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9250 | 0.8571 | available |
| rrf_at_100 | 0.9250 | 0.8571 | available |
| bge_at_10 | 0.7250 | 0.5714 | available |
| bge_at_20 | 0.7750 | 0.6190 | available |
| bge_at_30 | 0.8500 | 0.7143 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 6 | 2 | 0 | 0.7500 |
| 2 | 5 | 3 | 0 | 0.6250 |
| 3 | 5 | 0 | 0 | 1.0000 |
