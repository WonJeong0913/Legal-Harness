# Legal Harness development-run evaluation

- Questions: 40
- Supported-answer yield: 0.8750
- Provision micro P/R/F1: 0.8082 / 0.7867 / 0.7973
- Latency median/p95: 117290.910 ms / 294856.500 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 35 | 0.8750 |
| ABSTAIN | 5 | 0.1250 |
| EXECUTION_FAILURE | 0 | 0.0000 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 78 | 1.950 |
| Core (scored) | 73 | 1.825 |
| Supplemental | 4 | 0.100 |
| Qualifying | 1 | 0.025 |
| Alternative | 0 | 0.000 |
| Auxiliary union | 5 | 0.125 |

- Role-schema records: 40; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 2 across 2 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 35.08 | 40 | 0 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 35.08 | 40 | 0 |
| ABSTAIN only (missing = 0) | 24.67 | 5 | 0 |
| ABSTAIN candidates only (available only) | 24.67 | 5 | N/A |
| Available candidates only | 35.08 | 40 | N/A |

- Potential over-abstention exact matches@800: 0 / 5 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 40 | 30 | 0 | 5 | 5 | 0 | 79.73 | 50.00 | 31.99 | N/A | 36.56 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9333 | 0.8750 | available |
| rrf_at_100 | 0.9333 | 0.8750 | available |
| bge_at_10 | 0.8267 | 0.7000 | available |
| bge_at_20 | 0.8800 | 0.7750 | available |
| bge_at_30 | 0.9067 | 0.8250 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 10 | 2 | 0 | 0.8333 |
| 2 | 20 | 2 | 0 | 0.9091 |
| 3 | 5 | 1 | 0 | 0.8333 |
