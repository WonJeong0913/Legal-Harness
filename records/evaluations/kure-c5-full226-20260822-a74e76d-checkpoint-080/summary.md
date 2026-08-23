# Legal Harness development-run evaluation

> **Status: `VALIDATED_IDENTICAL_EXCEPT_RETRIEVER` (`DIAGNOSTIC_ONLY`).**
>
> Do not use this artifact for a clean retriever comparison. Reasons: recorded comparison validity failure.

- Questions: 80
- Supported-answer yield: 0.8500
- Provision micro P/R/F1: 0.6437 / 0.7179 / 0.6788
- Latency median/p95: 121526.351 ms / 238259.927 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 68 | 0.8500 |
| ABSTAIN | 12 | 0.1500 |
| EXECUTION_FAILURE | 0 | 0.0000 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 32.54 | 78 | 2 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 32.54 | 78 | 2 |
| ABSTAIN only (missing = 0) | 19.76 | 10 | 2 |
| ABSTAIN candidates only (available only) | 23.71 | 10 | N/A |
| Available candidates only | 33.37 | 78 | N/A |

- Potential over-abstention exact matches@800: 0 / 12 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 80 | 56 | 0 | 12 | 12 | 0 | 67.88 | 40.00 | 29.57 | N/A | 34.79 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9359 | 0.8875 | available |
| rrf_at_100 | 0.9359 | 0.8875 | available |
| bge_at_10 | 0.8205 | 0.7000 | available |
| bge_at_20 | 0.8846 | 0.8000 | available |
| bge_at_30 | 0.9167 | 0.8500 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 16 | 3 | 0 | 0.8421 |
| 2 | 40 | 8 | 0 | 0.8333 |
| 3 | 12 | 1 | 0 | 0.9231 |
