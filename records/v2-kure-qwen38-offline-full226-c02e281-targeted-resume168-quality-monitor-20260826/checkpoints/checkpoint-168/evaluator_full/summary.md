# Legal Harness development-run evaluation

> **Status: `VALIDATED_IDENTICAL_EXCEPT_RETRIEVER` (`DIAGNOSTIC_ONLY`).**
>
> Do not use this artifact for a clean retriever comparison. Reasons: recorded comparison validity failure.

- Questions: 168
- Supported-answer yield: 0.8095
- Provision micro P/R/F1: 0.6706 / 0.6867 / 0.6786
- Latency median/p95: 112883.585 ms / 250881.690 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 136 | 0.8095 |
| ABSTAIN | 24 | 0.1429 |
| EXECUTION_FAILURE | 8 | 0.0476 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 33.72 | 156 | 12 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 35.40 | 156 | 4 |
| ABSTAIN only (missing = 0) | 17.39 | 20 | 4 |
| ABSTAIN candidates only (available only) | 20.87 | 20 | N/A |
| Available candidates only | 36.31 | 156 | N/A |

- Potential over-abstention exact matches@800: 0 / 24 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 168 | 106 | 0 | 30 | 24 | 8 | 67.86 | 40.48 | 31.23 | N/A | 38.58 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9177 | 0.8562 | available |
| rrf_at_100 | 0.9146 | 0.8500 | available |
| bge_at_10 | 0.7816 | 0.6312 | available |
| bge_at_20 | 0.8513 | 0.7375 | available |
| bge_at_30 | 0.8797 | 0.7875 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 32 | 7 | 2 | 0.7805 |
| 2 | 79 | 11 | 4 | 0.8404 |
| 3 | 25 | 6 | 2 | 0.7576 |
