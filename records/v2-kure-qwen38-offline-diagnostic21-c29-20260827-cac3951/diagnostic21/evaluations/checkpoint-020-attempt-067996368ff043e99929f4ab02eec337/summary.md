# Legal Harness development-run evaluation

- Questions: 20
- Supported-answer yield: 0.6500
- Provision micro P/R/F1: 0.8333 / 0.6579 / 0.7353
- Latency median/p95: 116711.275 ms / 209541.369 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 13 | 0.6500 |
| ABSTAIN | 4 | 0.2000 |
| EXECUTION_FAILURE | 3 | 0.1500 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 34 | 1.700 |
| Core (scored) | 30 | 1.500 |
| Supplemental | 3 | 0.150 |
| Qualifying | 1 | 0.050 |
| Alternative | 0 | 0.000 |
| Auxiliary union | 4 | 0.200 |

- Role-schema records: 20; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 1 across 1 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 24.72 | 17 | 3 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 29.08 | 17 | 0 |
| ABSTAIN only (missing = 0) | 20.71 | 4 | 0 |
| ABSTAIN candidates only (available only) | 20.71 | 4 | N/A |
| Available candidates only | 29.08 | 17 | N/A |

- Potential over-abstention exact matches@800: 0 / 4 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 20 | 10 | 0 | 3 | 4 | 3 | 73.53 | 35.00 | 20.58 | N/A | 31.66 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9333 | 0.8824 | available |
| rrf_at_100 | 0.9333 | 0.8824 | available |
| bge_at_10 | 0.7000 | 0.5882 | available |
| bge_at_20 | 0.7667 | 0.6471 | available |
| bge_at_30 | 0.8667 | 0.7647 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 6 | 2 | 0 | 0.7500 |
| 2 | 4 | 2 | 1 | 0.5714 |
| 3 | 3 | 0 | 2 | 0.6000 |
