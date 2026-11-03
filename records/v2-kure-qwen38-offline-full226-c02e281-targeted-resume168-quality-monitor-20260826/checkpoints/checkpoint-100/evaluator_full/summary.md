# Legal Harness development-run evaluation

> **Status: `VALIDATED_IDENTICAL_EXCEPT_RETRIEVER` (`DIAGNOSTIC_ONLY`).**
>
> Do not use this artifact for a clean retriever comparison. Reasons: recorded comparison validity failure.

- Questions: 100
- Supported-answer yield: 0.8100
- Provision micro P/R/F1: 0.7077 / 0.7005 / 0.7041
- Latency median/p95: 121387.663 ms / 232909.749 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 81 | 0.8100 |
| ABSTAIN | 12 | 0.1200 |
| EXECUTION_FAILURE | 7 | 0.0700 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 34.02 | 91 | 9 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 36.58 | 91 | 2 |
| ABSTAIN only (missing = 0) | 16.97 | 10 | 2 |
| ABSTAIN candidates only (available only) | 20.37 | 10 | N/A |
| Available candidates only | 37.38 | 91 | N/A |

- Potential over-abstention exact matches@800: 0 / 12 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 100 | 63 | 0 | 18 | 12 | 7 | 70.41 | 45.00 | 31.98 | N/A | 39.48 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9071 | 0.8495 | available |
| rrf_at_100 | 0.9071 | 0.8495 | available |
| bge_at_10 | 0.8033 | 0.6882 | available |
| bge_at_20 | 0.8634 | 0.7849 | available |
| bge_at_30 | 0.8743 | 0.7957 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 17 | 4 | 2 | 0.7391 |
| 2 | 51 | 5 | 3 | 0.8644 |
| 3 | 13 | 3 | 2 | 0.7222 |
