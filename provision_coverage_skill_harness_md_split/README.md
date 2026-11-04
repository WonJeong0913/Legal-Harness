---
project: "조문 근거 충족도 기반 스킬 하네스"
english_title: "A Provision-Evidence Coverage-Based Skill Harness for Korean Multi-Hop Statutory Question Answering"
document_type: "Split research and implementation handoff"
version: "1.0-handoff-split"
status: "Architecture and experimental contract consolidated; implementation and annotation pending"
last_updated: "2026-08-11"
primary_benchmark: "KoBLEX, 226 questions, 1/2/3-hop"
---

# 조문 근거 충족도 기반 스킬 하네스 — 분할 인수인계 문서

> **참고 (2026-11):** 이 폴더는 2026-08 설계 당시의 연구 설계서입니다. 아래 "현재 최우선 작업" 등 진행 상태 표시는 작성 시점 기준이며, 이후 구현·실험 결과는 [루트 README](../README.md)를 보세요.

> 다른 연구자·개발자·에이전트가 기존 대화 없이 연구 설계, 시스템 아키텍처, 구현, 실험, 평가 및 논문 작업을 이어갈 수 있도록 원본 인수인계 문서를 주제별 Markdown으로 분할한 패키지다. 각 문서의 번호 순서를 기본 읽기 순서로 사용한다.

## 가장 먼저 읽을 문서

1. [01 연구 정의·동결 결정](01_RESEARCH_DEFINITION_AND_FROZEN_DECISIONS.md)
2. [02 시스템 아키텍처·피겨 명세](02_SYSTEM_ARCHITECTURE_AND_FIGURE_SPEC.md)
3. [05 Run State·Policy·ABSTAIN](05_RUN_STATE_POLICY_AND_ABSTENTION.md)
4. [07 비교 실험 설계](07_EXPERIMENT_DESIGN_AND_BASELINES.md)
5. [10 로드맵·즉시 실행 작업](10_ROADMAP_AND_NEXT_ACTIONS.md)

## 전체 문서 목록

| 파일 | 원본 절 | 내용 |
|---|---:|---|
| [01_RESEARCH_DEFINITION_AND_FROZEN_DECISIONS.md](01_RESEARCH_DEFINITION_AND_FROZEN_DECISIONS.md) | § 1, 2 | 연구 정의·핵심 주장·동결 결정 |
| [02_SYSTEM_ARCHITECTURE_AND_FIGURE_SPEC.md](02_SYSTEM_ARCHITECTURE_AND_FIGURE_SPEC.md) | § 3, 4 | 최종 시스템 아키텍처·피겨 규칙 |
| [03_TERMINOLOGY_VARIABLES_AND_BLOCK_RESPONSIBILITIES.md](03_TERMINOLOGY_VARIABLES_AND_BLOCK_RESPONSIBILITIES.md) | § 5, 6 | 표기법·변수명·블록별 책임 |
| [04_DATA_CONTRACTS.md](04_DATA_CONTRACTS.md) | § 7 | 대표 데이터 계약 |
| [05_RUN_STATE_POLICY_AND_ABSTENTION.md](05_RUN_STATE_POLICY_AND_ABSTENTION.md) | § 8, 9 | Run State·제어 정책·ABSTAIN |
| [06_RETRIEVAL_SKILL_CONTRACTS_AND_INVARIANTS.md](06_RETRIEVAL_SKILL_CONTRACTS_AND_INVARIANTS.md) | § 10, 11, 12 | 검색 파이프라인·스킬 계약·실행 불변식 |
| [07_EXPERIMENT_DESIGN_AND_BASELINES.md](07_EXPERIMENT_DESIGN_AND_BASELINES.md) | § 13 | 비교 실험·기준선·제거 실험 |
| [08_DATA_ANNOTATION_EVALUATION_AND_STATISTICS.md](08_DATA_ANNOTATION_EVALUATION_AND_STATISTICS.md) | § 14, 15, 16, 17 | 데이터·주석·평가·통계·사람 평가 |
| [09_IMPLEMENTATION_LOGGING_AND_REPRODUCIBILITY.md](09_IMPLEMENTATION_LOGGING_AND_REPRODUCIBILITY.md) | § 18, 19, 20 | 실행 환경·로그·재현성·코드 구조 |
| [10_ROADMAP_AND_NEXT_ACTIONS.md](10_ROADMAP_AND_NEXT_ACTIONS.md) | § 21, 22 | 12주 로드맵·즉시 실행 작업 |
| [11_RELATED_WORK_CLAIM_BOUNDARIES_AND_THREATS.md](11_RELATED_WORK_CLAIM_BOUNDARIES_AND_THREATS.md) | § 23, 24, 25 | 선행연구·주장 경계·타당성 위협 |
| [12_MEETING_BRIEF_OPEN_DECISIONS_AND_HANDOFF_CHECKS.md](12_MEETING_BRIEF_OPEN_DECISIONS_AND_HANDOFF_CHECKS.md) | § 26, 27, 28, 29, 30 | 미팅 브리프·미결정 사항·최종 체크 |
| [99_FULL_CANONICAL_SOURCE.md](99_FULL_CANONICAL_SOURCE.md) | 전체 | 분할 전 원본의 무수정 보존본 |

## 자산

- [Figure 1 — 시스템 아키텍처](assets/figure_1_system_architecture.png)
- [아키텍처·분기·설계 근거 PDF](assets/architecture_design_reference.pdf)
- [질문 사용자 아이콘](assets/icon_user_question.png)
- [응답 사용자 아이콘](assets/icon_user_response.png)
- [LLM 아이콘](assets/icon_llm.png)
- [코퍼스·인덱스 아이콘](assets/icon_storage.png)

## 문서 사용 원칙

- **Source of truth:** 분할 파일들은 `99_FULL_CANONICAL_SOURCE.md`의 절을 순서대로 보존한다.
- **동결 결정:** 검색 후보, 스킬 구조, 실행 불변식, 실험 비교 조건은 변경 기록 없이 임의로 바꾸지 않는다.
- **아키텍처 변경:** `02_SYSTEM_ARCHITECTURE_AND_FIGURE_SPEC.md`, `05_RUN_STATE_POLICY_AND_ABSTENTION.md`, `06_RETRIEVAL_SKILL_CONTRACTS_AND_INVARIANTS.md`를 동시에 갱신한다.
- **변수명 변경:** `03_TERMINOLOGY_VARIABLES_AND_BLOCK_RESPONSIBILITIES.md`와 `04_DATA_CONTRACTS.md`를 먼저 갱신하고 피겨·Schema·로그에 전파한다.
- **실험 변경:** `07`, `08`, `09`, `10` 문서에 변경 이유와 동결 시점을 기록한다.

## 현재 최우선 작업

- BM25와 KURE-v1 검색 비교 구현
- S1·S2·S3 JSON Schema 확정
- KoBLEX 예비 20~30문항 근거 주석
- C3·C5·M smoke test
- 테스트 비열람 절차와 설정 해시 기록
