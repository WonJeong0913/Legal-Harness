# Legal Harness development-run evaluation

- Questions: 20
- Supported-answer yield: 0.9000
- Provision micro P/R/F1: 0.6154 / 0.6316 / 0.6234
- Latency median/p95: 113870.088 ms / 218958.574 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 18 | 0.9000 |
| ABSTAIN | 2 | 0.1000 |
| EXECUTION_FAILURE | 0 | 0.0000 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 44 | 2.200 |
| Core (scored) | 39 | 1.950 |
| Supplemental | 1 | 0.050 |
| Qualifying | 2 | 0.100 |
| Alternative | 2 | 0.100 |
| Auxiliary union | 5 | 0.250 |

- Role-schema records: 20; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 2 across 2 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 31.35 | 20 | 0 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 31.35 | 20 | 0 |
| ABSTAIN only (missing = 0) | 11.23 | 2 | 0 |
| ABSTAIN candidates only (available only) | 11.23 | 2 | N/A |
| Available candidates only | 31.35 | 20 | N/A |

- Potential over-abstention exact matches@800: 0 / 2 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 20 | 12 | 1 | 5 | 2 | 0 | 62.34 | 15.00 | 30.22 | N/A | 33.58 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9474 | 0.9000 | available |
| rrf_at_100 | 0.9474 | 0.9000 | available |
| bge_at_10 | 0.7105 | 0.5500 | available |
| bge_at_20 | 0.8947 | 0.8000 | available |
| bge_at_30 | 0.9474 | 0.9000 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 6 | 2 | 0 | 0.7500 |
| 2 | 7 | 0 | 0 | 1.0000 |
| 3 | 5 | 0 | 0 | 1.0000 |
