# Legal Harness development-run evaluation

- Questions: 20
- Supported-answer yield: 0.7000
- Provision micro P/R/F1: 0.6774 / 0.5526 / 0.6087
- Latency median/p95: 114961.504 ms / 282059.331 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 14 | 0.7000 |
| ABSTAIN | 3 | 0.1500 |
| EXECUTION_FAILURE | 3 | 0.1500 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 35 | 1.750 |
| Core (scored) | 31 | 1.550 |
| Supplemental | 2 | 0.100 |
| Qualifying | 1 | 0.050 |
| Alternative | 1 | 0.050 |
| Auxiliary union | 4 | 0.200 |

- Role-schema records: 20; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 3 across 3 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 29.61 | 17 | 3 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 34.83 | 17 | 0 |
| ABSTAIN only (missing = 0) | 27.92 | 3 | 0 |
| ABSTAIN candidates only (available only) | 27.92 | 3 | N/A |
| Available candidates only | 34.83 | 17 | N/A |

- Potential over-abstention exact matches@800: 0 / 3 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 20 | 9 | 1 | 4 | 3 | 3 | 60.87 | 15.00 | 25.42 | N/A | 36.31 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9412 | 0.8824 | available |
| rrf_at_100 | 0.9412 | 0.8824 | available |
| bge_at_10 | 0.7353 | 0.5294 | available |
| bge_at_20 | 0.8824 | 0.8235 | available |
| bge_at_30 | 0.9412 | 0.8824 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 5 | 1 | 2 | 0.6250 |
| 2 | 4 | 2 | 1 | 0.5714 |
| 3 | 5 | 0 | 0 | 1.0000 |
