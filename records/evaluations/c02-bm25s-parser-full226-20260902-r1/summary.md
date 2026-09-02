# Legal Harness development-run evaluation

- Questions: 226
- Supported-answer yield: 0.6416
- Provision micro P/R/F1: 0.6847 / 0.5440 / 0.6063
- Latency median/p95: 156072.351 ms / 311320.588 ms

## Outcomes

| Outcome | Count | Rate |
| --- | ---: | ---: |
| ANSWER | 145 | 0.6416 |
| ABSTAIN | 64 | 0.2832 |
| EXECUTION_FAILURE | 17 | 0.0752 |

## ABSTAIN benchmark-candidate diagnostic

Candidate answers are diagnostic only: the public harness status remains `ABSTAIN` and candidate citations are not accepted evidence.

| Candidate Token-F1@800 scope | Score | Available | Missing |
| --- | ---: | ---: | ---: |
| All outcomes (missing/failure = 0) | 27.97 | 177 | 49 |
| Normal outcomes (ANSWER + ABSTAIN; missing = 0) | 30.25 | 177 | 32 |
| ABSTAIN only (missing = 0) | 12.61 | 32 | 32 |
| ABSTAIN candidates only (available only) | 25.23 | 32 | N/A |
| Available candidates only | 35.72 | 177 | N/A |

- Potential over-abstention exact matches@800: 0 / 64 (0.0000).

## KoBLEX-aligned metrics

All scores in this table use the 0--100 display scale; JSON keeps 0--1 values.

| Split | N | Full | Conditional | Limited | Abstain | Failure | Prov F1 | Prov EM | Token-F1@800 E2E | LF-Eval E2E | Token-F1@800 Answered | LF-Eval Answered |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| all | 226 | 97 | 0 | 48 | 64 | 17 | 60.63 | 28.76 | 24.40 | N/A | 38.03 | N/A |

## Retrieval stages

| Stage | Provision recall | Complete-evidence recall | Availability |
| --- | ---: | ---: | --- |
| first_stage_at_100 | 0.7279 | 0.6029 | available |
| rrf_at_100 | 0.7206 | 0.5933 | available |
| bge_at_10 | 0.6446 | 0.4976 | available |
| bge_at_20 | 0.6765 | 0.5407 | available |
| bge_at_30 | 0.7010 | 0.5742 | available |

## Hop strata

| Hop | ANSWER | ABSTAIN | FAILURE | Supported yield |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 33 | 22 | 2 | 0.5789 |
| 2 | 86 | 29 | 12 | 0.6772 |
| 3 | 26 | 13 | 3 | 0.6190 |
