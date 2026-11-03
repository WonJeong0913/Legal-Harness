# Legal Harness development-run evaluation

> **Status: `VALIDATED_IDENTICAL_EXCEPT_RETRIEVER` (`DIAGNOSTIC_ONLY`).**
>
> Do not use this artifact for a clean retriever comparison. Reasons: recorded comparison validity failure.

- Questions: 80
- Supported-answer yield: 0.8125
- Provision micro P/R/F1: 0.7452 / 0.7267 / 0.7358
- Latency median/p95: 116725.560 ms / 212633.748 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 65 | 0.8125 |
| ABSTAIN | 9 | 0.1125 |
| EXECUTION_FAILURE | 6 | 0.0750 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 35.31 | 72 | 8 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 38.18 | 72 | 2 |
| ABSTAIN only (missing = 0) | 15.60 | 7 | 2 |
| ABSTAIN candidates only (available only) | 20.06 | 7 | N/A |
| Available candidates only | 39.24 | 72 | N/A |

- Potential over-abstention exact matches@800: 0 / 9 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 80 | 53 | 0 | 12 | 9 | 6 | 73.58 | 47.50 | 33.56 | N/A | 41.30 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9128 | 0.8514 | available |
| rrf_at_100 | 0.9128 | 0.8514 | available |
| bge_at_10 | 0.8188 | 0.7027 | available |
| bge_at_20 | 0.8792 | 0.7973 | available |
| bge_at_30 | 0.8859 | 0.8108 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 13 | 3 | 2 | 0.7222 |
| 2 | 40 | 3 | 2 | 0.8889 |
| 3 | 12 | 3 | 2 | 0.7059 |
