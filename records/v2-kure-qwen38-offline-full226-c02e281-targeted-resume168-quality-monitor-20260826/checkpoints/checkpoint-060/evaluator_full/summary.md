# Legal Harness development-run evaluation

> **Status: `VALIDATED_IDENTICAL_EXCEPT_RETRIEVER` (`DIAGNOSTIC_ONLY`).**
>
> Do not use this artifact for a clean retriever comparison. Reasons: recorded comparison validity failure.

- Questions: 60
- Supported-answer yield: 0.8167
- Provision micro P/R/F1: 0.7317 / 0.7200 / 0.7258
- Latency median/p95: 133198.008 ms / 212633.748 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 49 | 0.8167 |
| ABSTAIN | 6 | 0.1000 |
| EXECUTION_FAILURE | 5 | 0.0833 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 33.53 | 53 | 7 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 36.58 | 53 | 2 |
| ABSTAIN only (missing = 0) | 13.85 | 4 | 2 |
| ABSTAIN candidates only (available only) | 20.78 | 4 | N/A |
| Available candidates only | 37.96 | 53 | N/A |

- Potential over-abstention exact matches@800: 0 / 6 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 60 | 41 | 0 | 8 | 6 | 5 | 72.58 | 46.67 | 32.15 | N/A | 39.37 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9211 | 0.8727 | available |
| rrf_at_100 | 0.9211 | 0.8727 | available |
| bge_at_10 | 0.8070 | 0.6909 | available |
| bge_at_20 | 0.8772 | 0.8000 | available |
| bge_at_30 | 0.8860 | 0.8182 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 8 | 2 | 1 | 0.7273 |
| 2 | 31 | 2 | 2 | 0.8857 |
| 3 | 10 | 2 | 2 | 0.7143 |
