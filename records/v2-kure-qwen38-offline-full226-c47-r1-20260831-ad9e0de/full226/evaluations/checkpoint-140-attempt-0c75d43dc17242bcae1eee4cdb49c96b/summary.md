# Legal Harness development-run evaluation

- Questions: 140
- Supported-answer yield: 0.8429
- Provision micro P/R/F1: 0.7462 / 0.7029 / 0.7239
- Latency median/p95: 123739.138 ms / 277588.946 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 118 | 0.8429 |
| ABSTAIN | 17 | 0.1214 |
| EXECUTION_FAILURE | 5 | 0.0357 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 282 | 2.014 |
| Core (scored) | 260 | 1.857 |
| Supplemental | 15 | 0.107 |
| Qualifying | 3 | 0.021 |
| Alternative | 4 | 0.029 |
| Auxiliary union | 22 | 0.157 |

- Role-schema records: 140; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 10 across 8 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 34.42 | 131 | 9 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 35.70 | 131 | 4 |
| ABSTAIN only (missing = 0) | 20.33 | 13 | 4 |
| ABSTAIN candidates only (available only) | 26.58 | 13 | N/A |
| Available candidates only | 36.79 | 131 | N/A |

- Potential over-abstention exact matches@800: 0 / 17 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 140 | 97 | 2 | 19 | 17 | 5 | 72.39 | 44.29 | 31.96 | N/A | 37.91 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9122 | 0.8444 | available |
| rrf_at_100 | 0.9122 | 0.8444 | available |
| bge_at_10 | 0.8053 | 0.6815 | available |
| bge_at_20 | 0.8702 | 0.7704 | available |
| bge_at_30 | 0.8855 | 0.7926 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 28 | 6 | 0 | 0.8235 |
| 2 | 73 | 6 | 1 | 0.9125 |
| 3 | 17 | 5 | 4 | 0.6538 |
