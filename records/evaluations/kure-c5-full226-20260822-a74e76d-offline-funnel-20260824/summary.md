# Legal Harness development-run evaluation

> **Status: `VALIDATED_IDENTICAL_EXCEPT_RETRIEVER` (`DIAGNOSTIC_ONLY`).**
>
> Do not use this artifact for a clean retriever comparison. Reasons: recorded comparison validity failure.

- Questions: 226
- Supported-answer yield: 0.8274
- Provision micro P/R/F1: 0.6253 / 0.6930 / 0.6574
- Latency median/p95: 123934.735 ms / 241864.844 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 187 | 0.8274 |
| ABSTAIN | 35 | 0.1549 |
| EXECUTION_FAILURE | 4 | 0.0177 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 32.84 | 213 | 13 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 33.43 | 213 | 9 |
| ABSTAIN only (missing = 0) | 17.11 | 26 | 9 |
| ABSTAIN candidates only (available only) | 23.03 | 26 | N/A |
| Available candidates only | 34.85 | 213 | N/A |

- Potential over-abstention exact matches@800: 0 / 35 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 226 | 150 | 1 | 36 | 35 | 4 | 65.74 | 37.17 | 30.19 | N/A | 36.49 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9266 | 0.8694 | available |
| rrf_at_100 | 0.9243 | 0.8649 | available |
| bge_at_10 | 0.8188 | 0.7072 | available |
| bge_at_20 | 0.8716 | 0.7883 | available |
| bge_at_30 | 0.8968 | 0.8243 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 46 | 9 | 2 | 0.8070 |
| 2 | 107 | 19 | 1 | 0.8425 |
| 3 | 34 | 7 | 1 | 0.8095 |
