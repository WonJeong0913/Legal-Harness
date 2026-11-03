# Legal Harness development-run evaluation

- Questions: 21
- Supported-answer yield: 0.7143
- Provision micro P/R/F1: 0.6765 / 0.5750 / 0.6216
- Latency median/p95: 123024.761 ms / 215704.841 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 15 | 0.7143 |
| ABSTAIN | 6 | 0.2857 |
| EXECUTION_FAILURE | 0 | 0.0000 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 41 | 1.952 |
| Core (scored) | 34 | 1.619 |
| Supplemental | 5 | 0.238 |
| Qualifying | 1 | 0.048 |
| Alternative | 1 | 0.048 |
| Auxiliary union | 7 | 0.333 |

- Role-schema records: 21; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 1 across 1 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 30.61 | 21 | 0 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 30.61 | 21 | 0 |
| ABSTAIN only (missing = 0) | 19.48 | 6 | 0 |
| ABSTAIN candidates only (available only) | 19.48 | 6 | N/A |
| Available candidates only | 30.61 | 21 | N/A |

- Potential over-abstention exact matches@800: 0 / 6 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 21 | 9 | 1 | 5 | 6 | 0 | 62.16 | 23.81 | 25.04 | N/A | 35.06 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9500 | 0.9048 | available |
| rrf_at_100 | 0.9500 | 0.9048 | available |
| bge_at_10 | 0.6750 | 0.4762 | available |
| bge_at_20 | 0.8500 | 0.7143 | available |
| bge_at_30 | 0.9000 | 0.8095 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 5 | 3 | 0 | 0.6250 |
| 2 | 5 | 3 | 0 | 0.6250 |
| 3 | 5 | 0 | 0 | 1.0000 |
