# Legal Harness development-run evaluation

- Questions: 20
- Supported-answer yield: 0.6000
- Provision micro P/R/F1: 0.7241 / 0.5526 / 0.6269
- Latency median/p95: 126409.641 ms / 234389.476 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 12 | 0.6000 |
| ABSTAIN | 7 | 0.3500 |
| EXECUTION_FAILURE | 1 | 0.0500 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 33 | 1.650 |
| Core (scored) | 29 | 1.450 |
| Supplemental | 2 | 0.100 |
| Qualifying | 0 | 0.000 |
| Alternative | 2 | 0.100 |
| Auxiliary union | 4 | 0.200 |

- Role-schema records: 20; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 1 across 1 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 27.24 | 19 | 1 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 28.67 | 19 | 0 |
| ABSTAIN only (missing = 0) | 23.37 | 7 | 0 |
| ABSTAIN candidates only (available only) | 23.37 | 7 | N/A |
| Available candidates only | 28.67 | 19 | N/A |

- Potential over-abstention exact matches@800: 0 / 7 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 20 | 9 | 0 | 3 | 7 | 1 | 62.69 | 20.00 | 19.06 | N/A | 31.76 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9444 | 0.8947 | available |
| rrf_at_100 | 0.9444 | 0.8947 | available |
| bge_at_10 | 0.6667 | 0.4737 | available |
| bge_at_20 | 0.8611 | 0.7368 | available |
| bge_at_30 | 0.9167 | 0.8421 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 5 | 3 | 0 | 0.6250 |
| 2 | 3 | 3 | 1 | 0.4286 |
| 3 | 4 | 1 | 0 | 0.8000 |
