# Legal Harness development-run evaluation

- Questions: 220
- Supported-answer yield: 0.7955
- Provision micro P/R/F1: 0.7207 / 0.6752 / 0.6972
- Latency median/p95: 144919.468 ms / 320916.275 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 175 | 0.7955 |
| ABSTAIN | 32 | 0.1455 |
| EXECUTION_FAILURE | 13 | 0.0591 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 429 | 1.950 |
| Core (scored) | 401 | 1.823 |
| Supplemental | 19 | 0.086 |
| Qualifying | 5 | 0.023 |
| Alternative | 4 | 0.018 |
| Auxiliary union | 28 | 0.127 |

- Role-schema records: 220; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 14 across 12 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 32.70 | 201 | 19 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 34.76 | 201 | 6 |
| ABSTAIN only (missing = 0) | 20.38 | 26 | 6 |
| ABSTAIN candidates only (available only) | 25.08 | 26 | N/A |
| Available candidates only | 35.79 | 201 | N/A |

- Potential over-abstention exact matches@800: 0 / 32 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 220 | 141 | 4 | 30 | 32 | 13 | 69.72 | 43.18 | 29.74 | N/A | 37.38 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9198 | 0.8599 | available |
| rrf_at_100 | 0.9198 | 0.8599 | available |
| bge_at_10 | 0.7970 | 0.6763 | available |
| bge_at_20 | 0.8697 | 0.7729 | available |
| bge_at_30 | 0.8922 | 0.8068 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 46 | 9 | 2 | 0.8070 |
| 2 | 103 | 15 | 6 | 0.8306 |
| 3 | 26 | 8 | 5 | 0.6667 |
