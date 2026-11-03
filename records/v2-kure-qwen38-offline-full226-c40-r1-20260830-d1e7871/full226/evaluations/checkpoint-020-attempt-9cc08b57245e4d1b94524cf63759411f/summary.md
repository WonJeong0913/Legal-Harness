# Legal Harness development-run evaluation

- Questions: 20
- Supported-answer yield: 0.8500
- Provision micro P/R/F1: 0.8529 / 0.7838 / 0.8169
- Latency median/p95: 109925.266 ms / 239638.571 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 17 | 0.8500 |
| ABSTAIN | 2 | 0.1000 |
| EXECUTION_FAILURE | 1 | 0.0500 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 35 | 1.750 |
| Core (scored) | 34 | 1.700 |
| Supplemental | 0 | 0.000 |
| Qualifying | 1 | 0.050 |
| Alternative | 0 | 0.000 |
| Auxiliary union | 1 | 0.050 |

- Role-schema records: 20; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 0 across 0 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 29.70 | 19 | 1 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 31.27 | 19 | 0 |
| ABSTAIN only (missing = 0) | 13.68 | 2 | 0 |
| ABSTAIN candidates only (available only) | 13.68 | 2 | N/A |
| Available candidates only | 31.27 | 19 | N/A |

- Potential over-abstention exact matches@800: 0 / 2 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 20 | 16 | 0 | 1 | 2 | 1 | 81.69 | 60.00 | 28.34 | N/A | 33.34 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9714 | 0.9474 | available |
| rrf_at_100 | 0.9714 | 0.9474 | available |
| bge_at_10 | 0.8286 | 0.7895 | available |
| bge_at_20 | 0.8857 | 0.8421 | available |
| bge_at_30 | 0.9429 | 0.8947 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 6 | 0 | 0 | 1.0000 |
| 2 | 9 | 1 | 1 | 0.8182 |
| 3 | 2 | 1 | 0 | 0.6667 |
