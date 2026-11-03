# Legal Harness development-run evaluation

> **Status: `VALIDATED_IDENTICAL_EXCEPT_RETRIEVER` (`DIAGNOSTIC_ONLY`).**
>
> Do not use this artifact for a clean retriever comparison. Reasons: recorded comparison validity failure.

- Questions: 40
- Supported-answer yield: 0.8000
- Provision micro P/R/F1: 0.7381 / 0.7381 / 0.7381
- Latency median/p95: 121387.663 ms / 221530.925 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 32 | 0.8000 |
| ABSTAIN | 4 | 0.1000 |
| EXECUTION_FAILURE | 4 | 0.1000 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 33.03 | 35 | 5 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 36.70 | 35 | 1 |
| ABSTAIN only (missing = 0) | 15.15 | 3 | 1 |
| ABSTAIN candidates only (available only) | 20.20 | 3 | N/A |
| Available candidates only | 37.75 | 35 | N/A |

- Potential over-abstention exact matches@800: 0 / 4 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 40 | 26 | 0 | 6 | 4 | 4 | 73.81 | 50.00 | 31.51 | N/A | 39.39 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9079 | 0.8611 | available |
| rrf_at_100 | 0.9079 | 0.8611 | available |
| bge_at_10 | 0.7763 | 0.6389 | available |
| bge_at_20 | 0.8421 | 0.7500 | available |
| bge_at_30 | 0.8553 | 0.7778 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 3 | 2 | 1 | 0.5000 |
| 2 | 22 | 1 | 2 | 0.8800 |
| 3 | 7 | 1 | 1 | 0.7778 |
