# Legal Harness development-run evaluation

- Questions: 3
- Supported-answer yield: 0.6667
- Provision micro P/R/F1: 0.5000 / 0.3333 / 0.4000
- Latency median/p95: 221794.878 ms / 307098.002 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 2 | 0.6667 |
| ABSTAIN | 1 | 0.3333 |
| EXECUTION_FAILURE | 0 | 0.0000 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 27.77 | 3 | 0 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 27.77 | 3 | 0 |
| ABSTAIN only (missing = 0) | 18.87 | 1 | 0 |
| ABSTAIN candidates only (available only) | 18.87 | 1 | N/A |
| Available candidates only | 27.77 | 3 | N/A |

- Potential over-abstention exact matches@800: 0 / 1 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 3 | 2 | 0 | 0 | 1 | 0 | 40.00 | 33.33 | 21.48 | N/A | 32.22 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 1.0000 | 1.0000 | available |
| rrf_at_100 | 1.0000 | 1.0000 | available |
| bge_at_10 | 0.8333 | 0.6667 | available |
| bge_at_20 | 0.8333 | 0.6667 | available |
| bge_at_30 | 0.8333 | 0.6667 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1 | 0 | 0 | 1.0000 |
| 2 | 0 | 1 | 0 | 0.0000 |
| 3 | 1 | 0 | 0 | 1.0000 |
