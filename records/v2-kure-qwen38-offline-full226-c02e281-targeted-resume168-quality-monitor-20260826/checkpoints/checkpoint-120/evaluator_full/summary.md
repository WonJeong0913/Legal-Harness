# Legal Harness development-run evaluation

> **Status: `VALIDATED_IDENTICAL_EXCEPT_RETRIEVER` (`DIAGNOSTIC_ONLY`).**
>
> Do not use this artifact for a clean retriever comparison. Reasons: recorded comparison validity failure.

- Questions: 120
- Supported-answer yield: 0.8167
- Provision micro P/R/F1: 0.6992 / 0.6962 / 0.6977
- Latency median/p95: 118292.905 ms / 259707.750 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 98 | 0.8167 |
| ABSTAIN | 15 | 0.1250 |
| EXECUTION_FAILURE | 7 | 0.0583 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 33.77 | 110 | 10 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 35.87 | 110 | 3 |
| ABSTAIN only (missing = 0) | 16.08 | 12 | 3 |
| ABSTAIN candidates only (available only) | 20.10 | 12 | N/A |
| Available candidates only | 36.84 | 110 | N/A |

- Potential over-abstention exact matches@800: 0 / 15 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 120 | 75 | 0 | 23 | 15 | 7 | 69.77 | 43.33 | 31.76 | N/A | 38.89 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9013 | 0.8319 | available |
| rrf_at_100 | 0.8969 | 0.8230 | available |
| bge_at_10 | 0.7848 | 0.6372 | available |
| bge_at_20 | 0.8475 | 0.7434 | available |
| bge_at_30 | 0.8700 | 0.7788 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 23 | 4 | 2 | 0.7931 |
| 2 | 56 | 8 | 3 | 0.8358 |
| 3 | 19 | 3 | 2 | 0.7917 |
