# Legal Harness development-run evaluation

- Questions: 40
- Supported-answer yield: 0.9000
- Provision micro P/R/F1: 0.7867 / 0.7867 / 0.7867
- Latency median/p95: 108915.402 ms / 224804.475 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 36 | 0.9000 |
| ABSTAIN | 4 | 0.1000 |
| EXECUTION_FAILURE | 0 | 0.0000 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 79 | 1.975 |
| Core (scored) | 75 | 1.875 |
| Supplemental | 3 | 0.075 |
| Qualifying | 1 | 0.025 |
| Alternative | 0 | 0.000 |
| Auxiliary union | 4 | 0.100 |

- Role-schema records: 40; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 2 across 2 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 35.17 | 40 | 0 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 35.17 | 40 | 0 |
| ABSTAIN only (missing = 0) | 24.96 | 4 | 0 |
| ABSTAIN candidates only (available only) | 24.96 | 4 | N/A |
| Available candidates only | 35.17 | 40 | N/A |

- Potential over-abstention exact matches@800: 0 / 4 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 40 | 30 | 0 | 6 | 4 | 0 | 78.67 | 52.50 | 32.68 | N/A | 36.31 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9333 | 0.8750 | available |
| rrf_at_100 | 0.9333 | 0.8750 | available |
| bge_at_10 | 0.8267 | 0.7250 | available |
| bge_at_20 | 0.8933 | 0.8000 | available |
| bge_at_30 | 0.9067 | 0.8250 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 10 | 2 | 0 | 0.8333 |
| 2 | 21 | 1 | 0 | 0.9545 |
| 3 | 5 | 1 | 0 | 0.8333 |
