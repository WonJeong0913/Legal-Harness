# Legal Harness development-run evaluation

- Questions: 20
- Supported-answer yield: 0.9000
- Provision micro P/R/F1: 0.8611 / 0.8378 / 0.8493
- Latency median/p95: 113293.018 ms / 237536.726 ms

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
| Authorized union | 37 | 1.850 |
| Core (scored) | 36 | 1.800 |
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
| All outcomes (missing/failure = 0) | 35.24 | 20 | 0 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 35.24 | 20 | 0 |
| ABSTAIN only (missing = 0) | 20.78 | 2 | 0 |
| ABSTAIN candidates only (available only) | 20.78 | 2 | N/A |
| Available candidates only | 35.24 | 20 | N/A |

- Potential over-abstention exact matches@800: 0 / 2 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 20 | 17 | 0 | 1 | 2 | 0 | 84.93 | 65.00 | 33.16 | N/A | 36.84 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9730 | 0.9500 | available |
| rrf_at_100 | 0.9730 | 0.9500 | available |
| bge_at_10 | 0.8649 | 0.8000 | available |
| bge_at_20 | 0.8919 | 0.8000 | available |
| bge_at_30 | 0.9189 | 0.8500 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 6 | 0 | 0 | 1.0000 |
| 2 | 10 | 1 | 0 | 0.9091 |
| 3 | 2 | 1 | 0 | 0.6667 |
