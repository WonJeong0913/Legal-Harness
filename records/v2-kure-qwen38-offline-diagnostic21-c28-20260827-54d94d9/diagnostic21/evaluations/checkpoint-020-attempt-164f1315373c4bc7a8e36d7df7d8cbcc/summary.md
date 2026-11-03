# Legal Harness development-run evaluation

- Questions: 20
- Supported-answer yield: 0.7500
- Provision micro P/R/F1: 0.6579 / 0.6579 / 0.6579
- Latency median/p95: 132350.546 ms / 215377.473 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 15 | 0.7500 |
| ABSTAIN | 5 | 0.2500 |
| EXECUTION_FAILURE | 0 | 0.0000 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 41 | 2.050 |
| Core (scored) | 38 | 1.900 |
| Supplemental | 2 | 0.100 |
| Qualifying | 0 | 0.000 |
| Alternative | 1 | 0.050 |
| Auxiliary union | 3 | 0.150 |

- Role-schema records: 20; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 2 across 2 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 31.56 | 20 | 0 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 31.56 | 20 | 0 |
| ABSTAIN only (missing = 0) | 27.07 | 5 | 0 |
| ABSTAIN candidates only (available only) | 27.07 | 5 | N/A |
| Available candidates only | 31.56 | 20 | N/A |

- Potential over-abstention exact matches@800: 0 / 5 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 20 | 10 | 0 | 5 | 5 | 0 | 65.79 | 30.00 | 24.79 | N/A | 33.06 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9474 | 0.9000 | available |
| rrf_at_100 | 0.9474 | 0.9000 | available |
| bge_at_10 | 0.7632 | 0.6000 | available |
| bge_at_20 | 0.8947 | 0.8500 | available |
| bge_at_30 | 0.9474 | 0.9000 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 5 | 3 | 0 | 0.6250 |
| 2 | 5 | 2 | 0 | 0.7143 |
| 3 | 5 | 0 | 0 | 1.0000 |
