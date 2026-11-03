# Legal Harness development-run evaluation

- Questions: 100
- Supported-answer yield: 0.8500
- Provision micro P/R/F1: 0.7592 / 0.7214 / 0.7398
- Latency median/p95: 123739.138 ms / 257631.832 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 85 | 0.8500 |
| ABSTAIN | 13 | 0.1300 |
| EXECUTION_FAILURE | 2 | 0.0200 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 205 | 2.050 |
| Core (scored) | 191 | 1.910 |
| Supplemental | 9 | 0.090 |
| Qualifying | 3 | 0.030 |
| Alternative | 2 | 0.020 |
| Auxiliary union | 14 | 0.140 |

- Role-schema records: 100; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 4 across 4 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 35.01 | 95 | 5 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 35.73 | 95 | 3 |
| ABSTAIN only (missing = 0) | 18.68 | 10 | 3 |
| ABSTAIN candidates only (available only) | 24.28 | 10 | N/A |
| Available candidates only | 36.86 | 95 | N/A |

- Potential over-abstention exact matches@800: 0 / 13 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 100 | 69 | 2 | 14 | 13 | 2 | 73.98 | 46.00 | 32.59 | N/A | 38.34 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9128 | 0.8469 | available |
| rrf_at_100 | 0.9128 | 0.8469 | available |
| bge_at_10 | 0.8000 | 0.6735 | available |
| bge_at_20 | 0.8615 | 0.7551 | available |
| bge_at_30 | 0.8821 | 0.7857 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 17 | 5 | 0 | 0.7727 |
| 2 | 54 | 4 | 0 | 0.9310 |
| 3 | 14 | 4 | 2 | 0.7000 |
