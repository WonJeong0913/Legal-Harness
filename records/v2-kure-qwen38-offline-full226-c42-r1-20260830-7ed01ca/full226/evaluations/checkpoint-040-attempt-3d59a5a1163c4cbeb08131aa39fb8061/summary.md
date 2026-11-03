# Legal Harness development-run evaluation

- Questions: 40
- Supported-answer yield: 0.7750
- Provision micro P/R/F1: 0.7857 / 0.7333 / 0.7586
- Latency median/p95: 108778.068 ms / 267782.072 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 31 | 0.7750 |
| ABSTAIN | 6 | 0.1500 |
| EXECUTION_FAILURE | 3 | 0.0750 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 75 | 1.875 |
| Core (scored) | 70 | 1.750 |
| Supplemental | 4 | 0.100 |
| Qualifying | 1 | 0.025 |
| Alternative | 0 | 0.000 |
| Auxiliary union | 5 | 0.125 |

- Role-schema records: 40; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 2 across 2 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 31.15 | 36 | 4 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 33.67 | 36 | 1 |
| ABSTAIN only (missing = 0) | 20.56 | 5 | 1 |
| ABSTAIN candidates only (available only) | 24.67 | 5 | N/A |
| Available candidates only | 34.61 | 36 | N/A |

- Potential over-abstention exact matches@800: 0 / 6 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 40 | 26 | 0 | 5 | 6 | 3 | 75.86 | 47.50 | 28.06 | N/A | 36.21 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9155 | 0.8649 | available |
| rrf_at_100 | 0.9155 | 0.8649 | available |
| bge_at_10 | 0.7887 | 0.6757 | available |
| bge_at_20 | 0.8592 | 0.7568 | available |
| bge_at_30 | 0.8873 | 0.8108 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 8 | 2 | 2 | 0.6667 |
| 2 | 18 | 3 | 1 | 0.8182 |
| 3 | 5 | 1 | 0 | 0.8333 |
