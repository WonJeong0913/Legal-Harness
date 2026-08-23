# Legal Harness development-run evaluation

> **Status: `VALIDATED_IDENTICAL_EXCEPT_RETRIEVER` (`DIAGNOSTIC_ONLY`).**
>
> Do not use this artifact for a clean retriever comparison. Reasons: recorded comparison validity failure.

- Questions: 40
- Supported-answer yield: 0.8500
- Provision micro P/R/F1: 0.6667 / 0.7200 / 0.6923
- Latency median/p95: 102490.810 ms / 238259.927 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 34 | 0.8500 |
| ABSTAIN | 6 | 0.1500 |
| EXECUTION_FAILURE | 0 | 0.0000 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 29.55 | 38 | 2 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 29.55 | 38 | 2 |
| ABSTAIN only (missing = 0) | 11.66 | 4 | 2 |
| ABSTAIN candidates only (available only) | 17.49 | 4 | N/A |
| Available candidates only | 31.10 | 38 | N/A |

- Potential over-abstention exact matches@800: 0 / 6 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 40 | 29 | 0 | 5 | 6 | 0 | 69.23 | 45.00 | 27.80 | N/A | 32.71 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.9467 | 0.9000 | available |
| rrf_at_100 | 0.9467 | 0.9000 | available |
| bge_at_10 | 0.8133 | 0.7250 | available |
| bge_at_20 | 0.8800 | 0.8000 | available |
| bge_at_30 | 0.9200 | 0.8500 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 10 | 2 | 0 | 0.8333 |
| 2 | 19 | 3 | 0 | 0.8636 |
| 3 | 5 | 1 | 0 | 0.8333 |
