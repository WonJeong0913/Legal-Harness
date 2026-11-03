# Legal Harness development-run evaluation

- Questions: 20
- Supported-answer yield: 0.6500
- Provision micro P/R/F1: 0.6452 / 0.5263 / 0.5797
- Latency median/p95: 122860.193 ms / 215647.439 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 13 | 0.6500 |
| ABSTAIN | 5 | 0.2500 |
| EXECUTION_FAILURE | 2 | 0.1000 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 37 | 1.850 |
| Core (scored) | 31 | 1.550 |
| Supplemental | 4 | 0.200 |
| Qualifying | 1 | 0.050 |
| Alternative | 1 | 0.050 |
| Auxiliary union | 6 | 0.300 |

- Role-schema records: 20; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 0 across 0 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 27.14 | 18 | 2 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 30.16 | 18 | 0 |
| ABSTAIN only (missing = 0) | 20.22 | 5 | 0 |
| ABSTAIN candidates only (available only) | 20.22 | 5 | N/A |
| Available candidates only | 30.16 | 18 | N/A |

- Potential over-abstention exact matches@800: 0 / 5 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 20 | 8 | 1 | 4 | 5 | 2 | 57.97 | 25.00 | 22.09 | N/A | 33.98 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9412 | 0.8889 | available |
| rrf_at_100 | 0.9412 | 0.8889 | available |
| bge_at_10 | 0.6471 | 0.4444 | available |
| bge_at_20 | 0.8529 | 0.7222 | available |
| bge_at_30 | 0.9118 | 0.8333 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 4 | 3 | 1 | 0.5000 |
| 2 | 5 | 2 | 0 | 0.7143 |
| 3 | 4 | 0 | 1 | 0.8000 |
