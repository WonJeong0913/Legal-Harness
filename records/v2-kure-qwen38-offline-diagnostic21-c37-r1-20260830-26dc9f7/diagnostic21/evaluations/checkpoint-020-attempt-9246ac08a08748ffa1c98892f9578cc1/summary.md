# Legal Harness development-run evaluation

- Questions: 20
- Supported-answer yield: 0.8000
- Provision micro P/R/F1: 0.6154 / 0.6316 / 0.6234
- Latency median/p95: 118944.965 ms / 241185.645 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 16 | 0.8000 |
| ABSTAIN | 3 | 0.1500 |
| EXECUTION_FAILURE | 1 | 0.0500 |

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
- Auxiliary citation references: 1 across 1 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 29.36 | 19 | 1 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 30.90 | 19 | 0 |
| ABSTAIN only (missing = 0) | 23.18 | 3 | 0 |
| ABSTAIN candidates only (available only) | 23.18 | 3 | N/A |
| Available candidates only | 30.90 | 19 | N/A |

- Potential over-abstention exact matches@800: 0 / 3 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 20 | 11 | 1 | 4 | 3 | 1 | 62.34 | 15.00 | 25.88 | N/A | 32.35 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9459 | 0.8947 | available |
| rrf_at_100 | 0.9459 | 0.8947 | available |
| bge_at_10 | 0.7027 | 0.5263 | available |
| bge_at_20 | 0.8919 | 0.7895 | available |
| bge_at_30 | 0.9459 | 0.8947 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 5 | 2 | 1 | 0.6250 |
| 2 | 6 | 1 | 0 | 0.8571 |
| 3 | 5 | 0 | 0 | 1.0000 |
