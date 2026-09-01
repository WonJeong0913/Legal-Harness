# KoBLEX Table 1–10 and C02/ParSeR Result Appendix

작성일: 2026-09-01

이 디렉터리는 KoBLEX 원 논문의 모든 benchmark table(Table 1–10), 고정 C02/KURE 결과, frozen ParSeR 재현 결과, 그리고 동일 local Qwen judge로 계산한 adapted legal-fidelity 결과를 한곳에서 검토하기 위한 자족형 결과 부록이다.

## 파일

- `report.html`: 브라우저에서 단독으로 열 수 있는 자족형 결과 보고서
- `data.json`: 보고서 표와 provenance의 구조화 원자료
- `SHA256SUMS`: 두 결과 파일의 SHA-256

## 수록 범위

- KoBLEX 원 논문 Table 1–10 전체(10/10)
- 원 논문 Table 2 기준값과 local C02/KURE·ParSeR 결과를 분리한 비교표
- public-answer와 candidate-answer 결과의 분리
- 동일 226문항 paired bootstrap 10,000회 결과
- C02, ParSeR, LF-Eval 입력과 산출물 provenance 및 SHA-256
- Table 9는 공식 점수와 구조를 유지하되 긴 원문은 짧은 독립 패러프레이즈로 제시

## Local adapted LF 결과

| 조건 | Public E2E | Public answered-only | Candidate E2E | Candidate available-only |
|---|---:|---:|---:|---:|
| C02/KURE | 6.274336 / 10 | 7.502646 / 10 | 6.738938 / 10 | 7.116822 / 10 |
| ParSeR reproduced | 6.238938 / 10 | 6.409091 / 10 | 6.238938 / 10 | 6.409091 / 10 |

이 점수는 `legal-harness-qwen38-q8` local alias를 judge로 사용한 `ADAPTED_LOCAL_QWEN38_LF_EVAL`이다. 관측된 모델 메타데이터는 `qwen35`, 26.9B, Q8_0이다. KoBLEX 공식 GPT-4o/DeepEval LF-Eval과 동등한 점수로 해석해서는 안 된다.

LF-Eval r1과 r2는 `aggregate.json`, `metadata.json`, `per_question.jsonl`, `receipt.json`이 모두 바이트 단위로 동일하다. 따라서 이 보고서의 LF 수치는 독립 r2 재실행에서도 그대로 재현됐다.

## 관련 결과 디렉터리

- `records/evaluations/kure-c02-qwen38-q8-full226-20260826/`
- `records/adapted-local-qwen38-lf-eval-c02-vs-parser-r1-20260901-a839228/`
- `records/adapted-local-qwen38-lf-eval-c02-vs-parser-r2-20260901-a839228/`

## 공식 출처

- 논문: <https://aclanthology.org/2025.emnlp-main.200/>
- 공식 코드: <https://github.com/daehuikim/KoBLEX>
- 공식 결과 디렉터리: <https://github.com/daehuikim/KoBLEX/tree/main/results>
