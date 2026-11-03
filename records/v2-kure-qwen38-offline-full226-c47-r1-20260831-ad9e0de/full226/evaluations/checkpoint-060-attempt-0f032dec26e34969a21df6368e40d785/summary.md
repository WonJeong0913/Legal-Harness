# Legal Harness development-run evaluation

- Questions: 60
- Supported-answer yield: 0.9000
- Provision micro P/R/F1: 0.7876 / 0.7807 / 0.7841
- Latency median/p95: 112359.747 ms / 224804.475 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 54 | 0.9000 |
| ABSTAIN | 6 | 0.1000 |
| EXECUTION_FAILURE | 0 | 0.0000 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 124 | 2.067 |
| Core (scored) | 113 | 1.883 |
| Supplemental | 6 | 0.100 |
| Qualifying | 3 | 0.050 |
| Alternative | 2 | 0.033 |
| Auxiliary union | 11 | 0.183 |

- Role-schema records: 60; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 3 across 3 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 35.69 | 59 | 1 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 35.69 | 59 | 1 |
| ABSTAIN only (missing = 0) | 22.26 | 5 | 1 |
| ABSTAIN candidates only (available only) | 26.71 | 5 | N/A |
| Available candidates only | 36.30 | 59 | N/A |

- Potential over-abstention exact matches@800: 0 / 6 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 60 | 43 | 1 | 10 | 6 | 0 | 78.41 | 50.00 | 33.47 | N/A | 37.18 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9474 | 0.9000 | available |
| rrf_at_100 | 0.9474 | 0.9000 | available |
| bge_at_10 | 0.8421 | 0.7333 | available |
| bge_at_20 | 0.9035 | 0.8167 | available |
| bge_at_30 | 0.9298 | 0.8667 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 14 | 3 | 0 | 0.8235 |
| 2 | 32 | 2 | 0 | 0.9412 |
| 3 | 8 | 1 | 0 | 0.8889 |
