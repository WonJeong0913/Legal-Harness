# Legal Harness development-run evaluation

> **Status: `VALIDATED_IDENTICAL_EXCEPT_RETRIEVER` (`DIAGNOSTIC_ONLY`).**
>
> Do not use this artifact for a clean retriever comparison. Reasons: recorded comparison validity failure.

- Questions: 200
- Supported-answer yield: 0.8400
- Provision micro P/R/F1: 0.6379 / 0.7036 / 0.6691
- Latency median/p95: 122443.327 ms / 242455.149 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 168 | 0.8400 |
| ABSTAIN | 29 | 0.1450 |
| EXECUTION_FAILURE | 3 | 0.0150 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 33.34 | 190 | 10 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 33.85 | 190 | 7 |
| ABSTAIN only (missing = 0) | 17.59 | 22 | 7 |
| ABSTAIN candidates only (available only) | 23.19 | 22 | N/A |
| Available candidates only | 35.10 | 190 | N/A |

- Potential over-abstention exact matches@800: 0 / 29 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 200 | 134 | 1 | 33 | 29 | 3 | 66.91 | 38.00 | 30.79 | N/A | 36.66 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9243 | 0.8680 | available |
| rrf_at_100 | 0.9217 | 0.8629 | available |
| bge_at_10 | 0.8251 | 0.7107 | available |
| bge_at_20 | 0.8773 | 0.7919 | available |
| bge_at_30 | 0.9008 | 0.8274 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 42 | 8 | 2 | 0.8077 |
| 2 | 96 | 16 | 0 | 0.8571 |
| 3 | 30 | 5 | 1 | 0.8333 |
