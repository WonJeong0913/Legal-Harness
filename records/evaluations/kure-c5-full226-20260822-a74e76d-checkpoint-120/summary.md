# Legal Harness development-run evaluation

> **Status: `VALIDATED_IDENTICAL_EXCEPT_RETRIEVER` (`DIAGNOSTIC_ONLY`).**
>
> Do not use this artifact for a clean retriever comparison. Reasons: recorded comparison validity failure.

- Questions: 120
- Supported-answer yield: 0.8333
- Provision micro P/R/F1: 0.6654 / 0.7269 / 0.6948
- Latency median/p95: 121526.351 ms / 232984.788 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 100 | 0.8333 |
| ABSTAIN | 18 | 0.1500 |
| EXECUTION_FAILURE | 2 | 0.0167 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 33.05 | 115 | 5 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 33.61 | 115 | 3 |
| ABSTAIN only (missing = 0) | 19.81 | 15 | 3 |
| ABSTAIN candidates only (available only) | 23.77 | 15 | N/A |
| Available candidates only | 34.48 | 115 | N/A |

- Potential over-abstention exact matches@800: 0 / 18 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 120 | 84 | 0 | 16 | 18 | 2 | 69.48 | 39.17 | 30.07 | N/A | 36.09 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9359 | 0.8898 | available |
| rrf_at_100 | 0.9316 | 0.8814 | available |
| bge_at_10 | 0.8291 | 0.7119 | available |
| bge_at_20 | 0.8761 | 0.7881 | available |
| bge_at_30 | 0.9060 | 0.8305 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 23 | 5 | 1 | 0.7931 |
| 2 | 57 | 11 | 0 | 0.8382 |
| 3 | 20 | 2 | 1 | 0.8696 |
