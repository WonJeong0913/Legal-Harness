# Legal Harness development-run evaluation

> **Status: `VALIDATED_IDENTICAL_EXCEPT_RETRIEVER` (`DIAGNOSTIC_ONLY`).**
>
> Do not use this artifact for a clean retriever comparison. Reasons: recorded comparison validity failure.

- Questions: 140
- Supported-answer yield: 0.8357
- Provision micro P/R/F1: 0.6968 / 0.7070 / 0.7018
- Latency median/p95: 111330.926 ms / 251841.430 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 117 | 0.8357 |
| ABSTAIN | 16 | 0.1143 |
| EXECUTION_FAILURE | 7 | 0.0500 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 33.70 | 129 | 11 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 35.47 | 129 | 4 |
| ABSTAIN only (missing = 0) | 15.07 | 12 | 4 |
| ABSTAIN candidates only (available only) | 20.10 | 12 | N/A |
| Available candidates only | 36.57 | 129 | N/A |

- Potential over-abstention exact matches@800: 0 / 16 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 140 | 91 | 0 | 26 | 16 | 7 | 70.18 | 42.86 | 31.97 | N/A | 38.26 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9151 | 0.8571 | available |
| rrf_at_100 | 0.9112 | 0.8496 | available |
| bge_at_10 | 0.7915 | 0.6466 | available |
| bge_at_20 | 0.8571 | 0.7594 | available |
| bge_at_30 | 0.8764 | 0.7895 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 29 | 5 | 2 | 0.8056 |
| 2 | 66 | 8 | 3 | 0.8571 |
| 3 | 22 | 3 | 2 | 0.8148 |
