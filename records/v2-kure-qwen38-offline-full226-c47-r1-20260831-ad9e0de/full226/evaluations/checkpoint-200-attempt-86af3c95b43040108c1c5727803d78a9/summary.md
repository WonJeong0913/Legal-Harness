# Legal Harness development-run evaluation

- Questions: 200
- Supported-answer yield: 0.8000
- Provision micro P/R/F1: 0.7201 / 0.6830 / 0.7011
- Latency median/p95: 137824.744 ms / 317910.649 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 160 | 0.8000 |
| ABSTAIN | 27 | 0.1350 |
| EXECUTION_FAILURE | 13 | 0.0650 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 395 | 1.975 |
| Core (scored) | 368 | 1.840 |
| Supplemental | 19 | 0.095 |
| Qualifying | 4 | 0.020 |
| Alternative | 4 | 0.020 |
| Auxiliary union | 27 | 0.135 |

- Role-schema records: 200; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 13 across 11 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 32.58 | 182 | 18 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 34.85 | 182 | 5 |
| ABSTAIN only (missing = 0) | 21.34 | 22 | 5 |
| ABSTAIN candidates only (available only) | 26.19 | 22 | N/A |
| Available candidates only | 35.81 | 182 | N/A |

- Potential over-abstention exact matches@800: 0 / 27 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 200 | 129 | 4 | 27 | 27 | 13 | 70.11 | 43.00 | 29.70 | N/A | 37.13 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9164 | 0.8503 | available |
| rrf_at_100 | 0.9164 | 0.8503 | available |
| bge_at_10 | 0.8022 | 0.6738 | available |
| bge_at_20 | 0.8663 | 0.7594 | available |
| bge_at_30 | 0.8886 | 0.7968 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 41 | 9 | 2 | 0.7885 |
| 2 | 95 | 11 | 6 | 0.8482 |
| 3 | 24 | 7 | 5 | 0.6667 |
