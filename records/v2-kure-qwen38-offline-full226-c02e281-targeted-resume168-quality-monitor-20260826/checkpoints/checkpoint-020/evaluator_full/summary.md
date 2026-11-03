# Legal Harness development-run evaluation

> **Status: `VALIDATED_IDENTICAL_EXCEPT_RETRIEVER` (`DIAGNOSTIC_ONLY`).**
>
> Do not use this artifact for a clean retriever comparison. Reasons: recorded comparison validity failure.

- Questions: 20
- Supported-answer yield: 0.8000
- Provision micro P/R/F1: 0.7568 / 0.7000 / 0.7273
- Latency median/p95: 127876.778 ms / 218550.256 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 16 | 0.8000 |
| ABSTAIN | 1 | 0.0500 |
| EXECUTION_FAILURE | 3 | 0.1500 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 31.31 | 17 | 3 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 36.84 | 17 | 0 |
| ABSTAIN only (missing = 0) | 12.90 | 1 | 0 |
| ABSTAIN candidates only (available only) | 12.90 | 1 | N/A |
| Available candidates only | 36.84 | 17 | N/A |

- Potential over-abstention exact matches@800: 0 / 1 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 20 | 12 | 0 | 4 | 1 | 3 | 72.73 | 40.00 | 30.67 | N/A | 38.33 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.8571 | 0.7647 | available |
| rrf_at_100 | 0.8571 | 0.7647 | available |
| bge_at_10 | 0.7714 | 0.5882 | available |
| bge_at_20 | 0.8000 | 0.6471 | available |
| bge_at_30 | 0.8286 | 0.7059 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 2 | 0 | 1 | 0.6667 |
| 2 | 11 | 1 | 2 | 0.7857 |
| 3 | 3 | 0 | 0 | 1.0000 |
