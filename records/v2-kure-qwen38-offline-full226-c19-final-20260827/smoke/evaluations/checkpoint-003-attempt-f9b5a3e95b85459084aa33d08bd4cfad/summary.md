# Legal Harness development-run evaluation

- Questions: 3
- Supported-answer yield: 0.6667
- Provision micro P/R/F1: 0.6667 / 0.6667 / 0.6667
- Latency median/p95: 136828.346 ms / 150925.148 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 2 | 0.6667 |
| ABSTAIN | 0 | 0.0000 |
| EXECUTION_FAILURE | 1 | 0.3333 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 6 | 2.000 |
| Core (scored) | 6 | 2.000 |
| Supplemental | 0 | 0.000 |
| Qualifying | 0 | 0.000 |
| Alternative | 0 | 0.000 |
| Auxiliary union | 0 | 0.000 |

- Role-schema records: 3; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 0 across 0 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 31.11 | 2 | 1 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 46.67 | 2 | 0 |
| ABSTAIN only (missing = 0) | N/A | 0 | 0 |
| ABSTAIN candidates only (available only) | N/A | 0 | N/A |
| Available candidates only | 46.67 | 2 | N/A |

- Potential over-abstention exact matches@800: 0 / 0 (N/A).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 3 | 1 | 1 | 0 | 0 | 1 | 66.67 | 66.67 | 31.11 | N/A | 46.67 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 1.0000 | 1.0000 | available |
| rrf_at_100 | 1.0000 | 1.0000 | available |
| bge_at_10 | 1.0000 | 1.0000 | available |
| bge_at_20 | 1.0000 | 1.0000 | available |
| bge_at_30 | 1.0000 | 1.0000 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1 | 0 | 0 | 1.0000 |
| 2 | 1 | 0 | 0 | 1.0000 |
| 3 | 0 | 0 | 1 | 0.0000 |
