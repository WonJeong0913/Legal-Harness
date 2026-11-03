# Legal Harness development-run evaluation

- Questions: 60
- Supported-answer yield: 0.8833
- Provision micro P/R/F1: 0.7838 / 0.7632 / 0.7733
- Latency median/p95: 109925.338 ms / 224548.525 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 53 | 0.8833 |
| ABSTAIN | 6 | 0.1000 |
| EXECUTION_FAILURE | 1 | 0.0167 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 122 | 2.033 |
| Core (scored) | 111 | 1.850 |
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
| All outcomes (missing/failure = 0) | 34.80 | 58 | 2 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 35.39 | 58 | 1 |
| ABSTAIN only (missing = 0) | 22.26 | 5 | 1 |
| ABSTAIN candidates only (available only) | 26.71 | 5 | N/A |
| Available candidates only | 36.00 | 58 | N/A |

- Potential over-abstention exact matches@800: 0 / 6 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 60 | 42 | 1 | 10 | 6 | 1 | 77.33 | 48.33 | 32.57 | N/A | 36.87 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9464 | 0.8983 | available |
| rrf_at_100 | 0.9464 | 0.8983 | available |
| bge_at_10 | 0.8393 | 0.7288 | available |
| bge_at_20 | 0.9018 | 0.8136 | available |
| bge_at_30 | 0.9286 | 0.8644 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 14 | 3 | 0 | 0.8235 |
| 2 | 31 | 2 | 1 | 0.9118 |
| 3 | 8 | 1 | 0 | 0.8889 |
