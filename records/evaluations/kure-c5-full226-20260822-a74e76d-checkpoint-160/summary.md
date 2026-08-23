# Legal Harness development-run evaluation

> **Status: `VALIDATED_IDENTICAL_EXCEPT_RETRIEVER` (`DIAGNOSTIC_ONLY`).**
>
> Do not use this artifact for a clean retriever comparison. Reasons: recorded comparison validity failure.

- Questions: 160
- Supported-answer yield: 0.8313
- Provision micro P/R/F1: 0.6510 / 0.7070 / 0.6779
- Latency median/p95: 122443.327 ms / 232984.788 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 133 | 0.8313 |
| ABSTAIN | 25 | 0.1562 |
| EXECUTION_FAILURE | 2 | 0.0125 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 33.05 | 153 | 7 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 33.47 | 153 | 5 |
| ABSTAIN only (missing = 0) | 17.92 | 20 | 5 |
| ABSTAIN candidates only (available only) | 22.40 | 20 | N/A |
| Available candidates only | 34.57 | 153 | N/A |

- Potential over-abstention exact matches@800: 0 / 25 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 160 | 108 | 0 | 25 | 25 | 2 | 67.79 | 38.12 | 30.26 | N/A | 36.40 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9258 | 0.8734 | available |
| rrf_at_100 | 0.9226 | 0.8671 | available |
| bge_at_10 | 0.8226 | 0.7089 | available |
| bge_at_20 | 0.8742 | 0.7911 | available |
| bge_at_30 | 0.8968 | 0.8228 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 31 | 7 | 1 | 0.7949 |
| 2 | 79 | 13 | 0 | 0.8587 |
| 3 | 23 | 5 | 1 | 0.7931 |
