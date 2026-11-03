# Legal Harness development-run evaluation

- Questions: 20
- Supported-answer yield: 0.7500
- Provision micro P/R/F1: 0.6774 / 0.5526 / 0.6087
- Latency median/p95: 138585.018 ms / 383472.560 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 15 | 0.7500 |
| ABSTAIN | 5 | 0.2500 |
| EXECUTION_FAILURE | 0 | 0.0000 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 38 | 1.900 |
| Core (scored) | 31 | 1.550 |
| Supplemental | 5 | 0.250 |
| Qualifying | 1 | 0.050 |
| Alternative | 1 | 0.050 |
| Auxiliary union | 7 | 0.350 |

- Role-schema records: 20; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 1 across 1 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 31.68 | 20 | 0 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 31.68 | 20 | 0 |
| ABSTAIN only (missing = 0) | 21.53 | 5 | 0 |
| ABSTAIN candidates only (available only) | 21.53 | 5 | N/A |
| Available candidates only | 31.68 | 20 | N/A |

- Potential over-abstention exact matches@800: 0 / 5 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 20 | 9 | 1 | 5 | 5 | 0 | 60.87 | 25.00 | 26.29 | N/A | 35.06 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9474 | 0.9000 | available |
| rrf_at_100 | 0.9474 | 0.9000 | available |
| bge_at_10 | 0.6579 | 0.4500 | available |
| bge_at_20 | 0.8421 | 0.7000 | available |
| bge_at_30 | 0.8947 | 0.8000 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 5 | 3 | 0 | 0.6250 |
| 2 | 5 | 2 | 0 | 0.7143 |
| 3 | 5 | 0 | 0 | 1.0000 |
