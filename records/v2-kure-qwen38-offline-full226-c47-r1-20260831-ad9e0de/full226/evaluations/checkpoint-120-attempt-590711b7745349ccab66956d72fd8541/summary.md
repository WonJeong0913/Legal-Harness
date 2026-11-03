# Legal Harness development-run evaluation

- Questions: 120
- Supported-answer yield: 0.8417
- Provision micro P/R/F1: 0.7578 / 0.7101 / 0.7332
- Latency median/p95: 123739.138 ms / 257039.287 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 101 | 0.8417 |
| ABSTAIN | 14 | 0.1167 |
| EXECUTION_FAILURE | 5 | 0.0417 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 238 | 1.983 |
| Core (scored) | 223 | 1.858 |
| Supplemental | 10 | 0.083 |
| Qualifying | 3 | 0.025 |
| Alternative | 2 | 0.017 |
| Auxiliary union | 15 | 0.125 |

- Role-schema records: 120; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 5 across 5 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 34.05 | 111 | 9 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 35.53 | 111 | 4 |
| ABSTAIN only (missing = 0) | 17.34 | 10 | 4 |
| ABSTAIN candidates only (available only) | 24.28 | 10 | N/A |
| Available candidates only | 36.81 | 111 | N/A |

- Potential over-abstention exact matches@800: 0 / 14 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 120 | 83 | 2 | 16 | 14 | 5 | 73.32 | 46.67 | 32.02 | N/A | 38.05 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9152 | 0.8522 | available |
| rrf_at_100 | 0.9152 | 0.8522 | available |
| bge_at_10 | 0.8125 | 0.6957 | available |
| bge_at_20 | 0.8705 | 0.7739 | available |
| bge_at_30 | 0.8884 | 0.8000 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 24 | 5 | 0 | 0.8276 |
| 2 | 63 | 4 | 1 | 0.9265 |
| 3 | 14 | 5 | 4 | 0.6087 |
