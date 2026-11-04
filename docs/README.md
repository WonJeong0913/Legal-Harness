# 문서 안내

논문 결과와 해석 기준은 [루트 README](../README.md)를 먼저 보세요. 이 폴더의 문서는 작성 시점이 서로 다르며, 일부는 이후 실험으로 내용이 갱신되었습니다.

| 문서 | 성격 | 비고 |
|---|---|---|
| [EXPERIMENT_PROTOCOL.md](EXPERIMENT_PROTOCOL.md) | 실험 프로토콜 | 226문항을 held-out 벤치마크로 다루는 원칙 |
| [ADAPTED_LOCAL_LF_EVAL_PROTOCOL.md](ADAPTED_LOCAL_LF_EVAL_PROTOCOL.md) | 로컬 Qwen LF 평가 프로토콜 | 공식 GPT-4o LF-Eval이 아님. 본문의 C36 입력 예시는 초기 버전 기준 |
| [KOBLEX_PARSER_BASELINE_REPRODUCTION_NOTES.md](KOBLEX_PARSER_BASELINE_REPRODUCTION_NOTES.md) | ParSeR 재현 노트 | 공식 코드와 의도적으로 다른 점 기록 |
| [KOBLEX_PARSER_BASELINE_RESULTS_226_20260819.md](KOBLEX_PARSER_BASELINE_RESULTS_226_20260819.md) | ParSeR (Reproduced) 결과 (2026-08-19) | ParSeR 자체 평가기 기준 수치 |
| [CONCLUSION_FIRST_SKILL_REPAIR_20260821.md](CONCLUSION_FIRST_SKILL_REPAIR_20260821.md) | 작업 기록 (2026-08-21) | 개발 과정 기록. 최종 결과 아님 |
| [HANDOFF_TO_CLAUDE_CODE_20260819.md](HANDOFF_TO_CLAUDE_CODE_20260819.md) | 작업 인계서 (2026-08-19) | 개발 과정 기록. 이후 C02·BM25s 실험 이전 시점 |

작업 기록과 인계서에 나오는 BM25는 대부분 SQLite FTS5 기반 기본 인덱스를 가리킵니다. 논문의 BM25 비교 조건(`bm25s` 0.3.10)과 다릅니다.
