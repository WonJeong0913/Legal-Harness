# Legal Harness development-run evaluation

- Questions: 80
- Supported-answer yield: 0.8875
- Provision micro P/R/F1: 0.7632 / 0.7436 / 0.7532
- Latency median/p95: 122286.883 ms / 257631.832 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 71 | 0.8875 |
| ABSTAIN | 9 | 0.1125 |
| EXECUTION_FAILURE | 0 | 0.0000 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 163 | 2.038 |
| Core (scored) | 152 | 1.900 |
| Supplemental | 6 | 0.075 |
| Qualifying | 3 | 0.037 |
| Alternative | 2 | 0.025 |
| Auxiliary union | 11 | 0.138 |

- Role-schema records: 80; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 3 across 3 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 35.06 | 78 | 2 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 35.06 | 78 | 2 |
| ABSTAIN only (missing = 0) | 17.93 | 7 | 2 |
| ABSTAIN candidates only (available only) | 23.05 | 7 | N/A |
| Available candidates only | 35.96 | 78 | N/A |

- Potential over-abstention exact matches@800: 0 / 9 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 80 | 56 | 1 | 14 | 9 | 0 | 75.32 | 46.25 | 33.05 | N/A | 37.24 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9103 | 0.8375 | available |
| rrf_at_100 | 0.9103 | 0.8375 | available |
| bge_at_10 | 0.8077 | 0.6750 | available |
| bge_at_20 | 0.8718 | 0.7625 | available |
| bge_at_30 | 0.8910 | 0.8000 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 16 | 3 | 0 | 0.8421 |
| 2 | 44 | 4 | 0 | 0.9167 |
| 3 | 11 | 2 | 0 | 0.8462 |
