# Legal Harness development-run evaluation

- Questions: 160
- Supported-answer yield: 0.8250
- Provision micro P/R/F1: 0.7361 / 0.6752 / 0.7043
- Latency median/p95: 129008.845 ms / 277588.946 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 132 | 0.8250 |
| ABSTAIN | 21 | 0.1313 |
| EXECUTION_FAILURE | 7 | 0.0437 |

## Evidence roles

Provision P/R/F1 and EM score CORE evidence only. Supplemental, qualifying, and alternative evidence remains reported but is not provision-scored.

| Role | Per-question unique total | Mean per question |
| --- | ---: | ---: |
| Authorized union | 311 | 1.944 |
| Core (scored) | 288 | 1.800 |
| Supplemental | 15 | 0.094 |
| Qualifying | 4 | 0.025 |
| Alternative | 4 | 0.025 |
| Auxiliary union | 23 | 0.144 |

- Role-schema records: 160; legacy accepted-evidence fallback records: 0.
- Auxiliary citation references: 11 across 9 questions.
- Counts are unique within each role list; one provision can have multiple link-level roles, so role totals can exceed the authorized-union count.

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 33.56 | 149 | 11 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 35.09 | 149 | 4 |
| ABSTAIN only (missing = 0) | 19.05 | 17 | 4 |
| ABSTAIN candidates only (available only) | 23.54 | 17 | N/A |
| Available candidates only | 36.03 | 149 | N/A |

- Potential over-abstention exact matches@800: 0 / 21 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 160 | 106 | 3 | 23 | 21 | 7 | 70.43 | 43.12 | 31.05 | N/A | 37.64 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9119 | 0.8431 | available |
| rrf_at_100 | 0.9119 | 0.8431 | available |
| bge_at_10 | 0.7966 | 0.6732 | available |
| bge_at_20 | 0.8644 | 0.7582 | available |
| bge_at_30 | 0.8814 | 0.7843 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 32 | 7 | 0 | 0.8205 |
| 2 | 82 | 8 | 2 | 0.8913 |
| 3 | 18 | 6 | 5 | 0.6207 |
