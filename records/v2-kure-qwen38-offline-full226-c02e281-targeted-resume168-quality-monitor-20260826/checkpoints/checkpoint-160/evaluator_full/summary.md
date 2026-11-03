# Legal Harness development-run evaluation

> **Status: `VALIDATED_IDENTICAL_EXCEPT_RETRIEVER` (`DIAGNOSTIC_ONLY`).**
>
> Do not use this artifact for a clean retriever comparison. Reasons: recorded comparison validity failure.

- Questions: 160
- Supported-answer yield: 0.8187
- Provision micro P/R/F1: 0.6975 / 0.6997 / 0.6986
- Latency median/p95: 108135.693 ms / 235500.465 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 131 | 0.8187 |
| ABSTAIN | 21 | 0.1313 |
| EXECUTION_FAILURE | 8 | 0.0500 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 34.49 | 148 | 12 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 36.30 | 148 | 4 |
| ABSTAIN only (missing = 0) | 17.80 | 17 | 4 |
| ABSTAIN candidates only (available only) | 21.99 | 17 | N/A |
| Available candidates only | 37.28 | 148 | N/A |

- Potential over-abstention exact matches@800: 0 / 21 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 160 | 103 | 0 | 28 | 21 | 8 | 69.86 | 41.88 | 32.15 | N/A | 39.27 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9226 | 0.8684 | available |
| rrf_at_100 | 0.9192 | 0.8618 | available |
| bge_at_10 | 0.7946 | 0.6447 | available |
| bge_at_20 | 0.8586 | 0.7566 | available |
| bge_at_30 | 0.8889 | 0.8092 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 32 | 7 | 2 | 0.7805 |
| 2 | 75 | 10 | 4 | 0.8427 |
| 3 | 24 | 4 | 2 | 0.8000 |
