# Legal Harness development-run evaluation

- Questions: 180
- Supported-answer yield: 0.8000
- Provision micro P/R/F1: 0.7251 / 0.6857 / 0.7048
- Latency median/p95: 134277.959 ms / 318394.409 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 144 | 0.8000 |
| ABSTAIN | 25 | 0.1389 |
| EXECUTION_FAILURE | 11 | 0.0611 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 356 | 1.978 |
| Core (scored) | 331 | 1.839 |
| Supplemental | 17 | 0.094 |
| Qualifying | 4 | 0.022 |
| Alternative | 4 | 0.022 |
| Auxiliary union | 25 | 0.139 |

- Role-schema records: 180; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 11 across 9 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 32.47 | 164 | 16 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 34.58 | 164 | 5 |
| ABSTAIN only (missing = 0) | 19.88 | 20 | 5 |
| ABSTAIN candidates only (available only) | 24.85 | 20 | N/A |
| Available candidates only | 35.64 | 164 | N/A |

- Potential over-abstention exact matches@800: 0 / 25 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 180 | 116 | 4 | 24 | 25 | 11 | 70.48 | 42.78 | 29.71 | N/A | 37.13 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9105 | 0.8402 | available |
| rrf_at_100 | 0.9105 | 0.8402 | available |
| bge_at_10 | 0.7994 | 0.6746 | available |
| bge_at_20 | 0.8642 | 0.7574 | available |
| bge_at_30 | 0.8827 | 0.7870 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 37 | 9 | 1 | 0.7872 |
| 2 | 85 | 10 | 5 | 0.8500 |
| 3 | 22 | 6 | 5 | 0.6667 |
