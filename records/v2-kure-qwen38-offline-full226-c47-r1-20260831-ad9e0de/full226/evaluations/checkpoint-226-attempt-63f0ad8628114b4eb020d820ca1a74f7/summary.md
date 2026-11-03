# Legal Harness development-run evaluation

- Questions: 226
- Supported-answer yield: 0.7920
- Provision micro P/R/F1: 0.7153 / 0.6637 / 0.6885
- Latency median/p95: 142864.688 ms / 319974.167 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 179 | 0.7920 |
| ABSTAIN | 33 | 0.1460 |
| EXECUTION_FAILURE | 14 | 0.0619 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 440 | 1.947 |
| Core (scored) | 411 | 1.819 |
| Supplemental | 20 | 0.088 |
| Qualifying | 5 | 0.022 |
| Alternative | 4 | 0.018 |
| Auxiliary union | 29 | 0.128 |

- Role-schema records: 226; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 15 across 13 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 32.24 | 205 | 21 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 34.37 | 205 | 7 |
| ABSTAIN only (missing = 0) | 19.76 | 26 | 7 |
| ABSTAIN candidates only (available only) | 25.08 | 26 | N/A |
| Available candidates only | 35.55 | 205 | N/A |

- Potential over-abstention exact matches@800: 0 / 33 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 226 | 145 | 4 | 30 | 33 | 14 | 68.85 | 42.48 | 29.36 | N/A | 37.07 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9173 | 0.8538 | available |
| rrf_at_100 | 0.9173 | 0.8538 | available |
| bge_at_10 | 0.7932 | 0.6698 | available |
| bge_at_20 | 0.8637 | 0.7642 | available |
| bge_at_30 | 0.8905 | 0.8019 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 46 | 9 | 2 | 0.8070 |
| 2 | 105 | 16 | 6 | 0.8268 |
| 3 | 28 | 8 | 6 | 0.6667 |
