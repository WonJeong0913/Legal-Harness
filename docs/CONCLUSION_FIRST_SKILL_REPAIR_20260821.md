# 결론 중심 S1/S2/S3 수정 및 실험 인계서

- 작성일: 2026-08-21
- 추가 수정일: 2026-08-22
- 작업 브랜치: `codex/conclusion-first-skills`
- 기준 커밋: `origin/main`의 `a6d76e5bb37174c4661ec7fe6dafa617f21cc119`
- 코드 상태: 수정 완료, 아직 커밋·푸시하지 않음
- 검증 상태: 이 환경에서는 모델 호출, 벤치마크, LF-Eval, 단위 테스트를 실행하지 않음
- 결과 상태: 아래 수치는 수정 전 저장 결과의 진단값이며, 수정 효과를 뜻하지 않음

## 1. 결론

이번에는 ABSTAIN 정책 자체를 먼저 느슨하게 만들지 않는다. 최신 226문항에서
공개 답변이 없었던 78건 중 40건은 정책상 ABSTAIN이 아니라
`EXECUTION_FAILURE`였다. 따라서 우선순위는 다음과 같다.

1. S1의 잘린 JSON과 중복 검색어를 줄여 실행 실패를 복구한다.
2. S1은 벤치마크 hop 수가 아니라 질문이 요구한 결론을 기준으로 최소 분해한다.
3. S2는 S1이 닫아 둔 요구사항만 판정하고, 설명문과 요구사항 ID를 혼동하지 않는다.
4. S3는 근거와 안전 메타데이터를 보존하되 공개 답변은 결론 중심으로 짧게 직렬화한다.
5. 공개 `ABSTAIN`의 `answer=null`은 유지하고, 후보 답변은 비공개 진단 점수에만 사용한다.
6. 주 검색기는 KURE로 고정하고, 기준선에서 사용한 질의 필드 우선순위·Top-k·
   BGE·정책 임계값을 바꾸지 않는다. KURE 질의 라우팅 변경은 스킬 수정과 섞지
   않고 별도 retrieval ablation으로만 시험한다.

### 1.1 보존해야 할 KURE 기준선 우위

먼저 이전 보고서의 `57.26 대 42.65`는 동일 21문항의 **BM25 D4**와 ParSeR
비교다. 현재 주 검색기인 KURE의 226문항 결과를 뜻하지 않는다. 다만 최신 KURE
226 결과에서 같은 21개 ID만 다시 뽑으면 KURE의 조문 Macro F1은 `61.49`,
ParSeR는 `42.65`다. 따라서 21문항의 조문 우위 자체는 KURE에서도 관측되지만,
BM25 수치를 KURE 수치라고 부르면 안 된다.

| 동일 21문항 | 조문 Precision | 조문 Recall | 조문 Macro F1 | 전체 조문 충족 |
| --- | ---: | ---: | ---: | ---: |
| BM25 D4 전체 | 50.26 | 75.40 | 57.26 | 61.90 |
| **현재 KURE D4 전체** | **58.41** | **73.81** | **61.49** | **66.67** |
| 재현 ParSeR | 50.40 | 38.89 | 42.65 | 19.05 |

전체 226문항에서는 ParSeR 오류 6건도 0점으로 포함해 분모를 맞췄다.

| 전체 226문항 | 조문 Precision | 조문 Recall | 조문 Macro F1 | 전체 조문 충족 |
| --- | ---: | ---: | ---: | ---: |
| **현재 KURE D4** | 54.27 | **69.69** | **58.44** | **60.62** |
| 재현 ParSeR, 오류 0점 포함 | **57.24** | 51.03 | 52.05 | 29.65 |
| KURE - ParSeR | -2.97%p | **+18.66%p** | **+6.39점** | **+30.97%p** |

냉정한 해석은 다음과 같다. 전체 226에서도 KURE의 조문 우위는 실제로 남아
있지만, `+14.60점`이 아니라 공정한 전체 분모 기준 `+6.39점`이다. KURE는
Precision을 약간 희생하는 대신 gold 조문 Recall과 complete-evidence 비율을 크게
높인다. 이번 수정의 제1 보호 지표는 이 **조문 회수 우위**이며, 답변 Token-F1을
올리기 위해 이를 희생하면 성공으로 판정하지 않는다.

문항별 F1은 KURE 승 99 / 동률 46 / 패 81이고, Recall은 승 104 / 동률 82 /
패 40이다. 따라서 “모든 문항에서 압도”가 아니라 **완전 조문 충족 문항이
137/226 대 67/226으로 많고, recall 패배 문항이 상대적으로 적다**고 표현하는 것이
정확하다.

### 1.2 Hop별로 보면 보호 대상이 더 분명하다

| Hop | KURE F1 / Recall | ParSeR F1 / Recall | KURE complete | ParSeR complete | KURE 실행 실패 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1-hop, 57건 | 68.80 / 80.70 | 66.96 / 71.05 | 78.95% | 70.18% | 4 |
| **2-hop, 127건** | **66.40 / 80.71** | 48.66 / 45.80 | **69.29%** | 18.11% | 9 |
| 3-hop, 42건 | 20.33 / 21.43 | **42.04 / 39.68** | 9.52% | 9.52% | **27** |

우리 구조의 핵심 강점은 2-hop 조문 회수다. 반대로 3-hop 열세는 KURE 자체가
항상 약해서라기보다 42건 중 27건이 S1 단계에서 실행 실패한 영향이 지배한다.
실행에 성공한 3-hop 15건만의 KURE F1은 `56.94`지만 선택 편향이 있으므로 이를
전체 예상 성능으로 외삽하지 않는다. 결론은 S1의 설명문을 줄이되, 서로 다른
조문·예외·교차참조를 찾는 evidence 분해와 검색 요청 수는 보존해야 한다는 것이다.

## 2. 관측 근거

### 2.1 최신 KURE 226문항

출처는
`records/evaluations/kure-bge-abstain-repair-d4-qwen38-q8-226-20260820-reconciled-20260821/`이다.

| 관측값 | 수정 전 값 |
| --- | ---: |
| ANSWER | 148 / 226, 65.49% |
| ABSTAIN | 38 / 226, 16.81% |
| EXECUTION_FAILURE | 40 / 226, 17.70% |
| 공개 답변 없음 합계 | 78 / 226, 34.51% |
| 비답변 78건 중 실행 실패 비중 | 51.28% |
| 조문 micro Precision / Recall / F1 | 55.19 / 63.66 / 59.12 |
| 조문 macro Precision / Recall / F1 | 54.27 / 69.69 / 58.44 |
| Token-F1@800, end-to-end | 17.10 |
| Token-F1@800, ANSWER only | 26.11 |
| ABSTAIN 후보 Token-F1@800, available only | 15.11, 35건 |

Hop별로는 3-hop 42건 중 `ANSWER 10 / ABSTAIN 5 / FAILURE 27`이다. 3-hop의
낮은 산출률을 전부 검색 실패나 엄격한 정책 탓으로 해석하면 안 된다. 이 구간은
우선 실행 실패가 지배한다.

### 2.2 실행 실패 원인 분해

저장된 배치 `summary.jsonl`과 개별 로그의 최종 오류를 기준으로 40건을
분류했다.

| 실패 단계 | 건수 | 직접 원인 | 이번 대응 |
| --- | ---: | --- | --- |
| S1 | 37 | 잘리거나 닫히지 않은 JSON 35건, 중복 `query_terms` 2건 | 출력 간결화, S1 생성 한도 1600→3072, 명백한 문자열 중복 제거 |
| S2 | 1 | `missing_aspects`에 요구사항 ID 대신 설명문 사용 | ID 계약 명시, 완전한 `criterion_results`에서 ID 배열 결정론적 복구 |
| S3 | 2 | claim이 deferred/unknown target을 참조 | 답변 대상이 하나일 때만 claim scope를 그 유일한 target으로 복구 |

S1의 잘린 응답은 대체로 약 4,000~4,350자 부근에서 JSON을 닫지 못했다. 기존
런타임은 S1에만 1,600 생성 토큰을 주고 S2/S3에는 3,072 토큰을 주고 있었다.
긴 3-hop 계획과 이 한도의 결합이 3-hop 실행 실패 집중의 직접 후보 원인이다.

단, 생성 한도만 늘리면 장황한 계획을 허용할 수 있다. 그래서 한도 복구와 동시에
한 결론당 한 target, 최소 critical evidence, 짧은 서술 필드라는 S1 계약을 함께
적용했다.

### 2.3 과잉 엄격도와 답변 품질은 별개 문제다

- 정책 ABSTAIN 38건 중 18건은 accepted provision이 gold 조문을 모두 포함했다.
  이 18건은 S1이 benchmark에 필요하지 않은 critical requirement를 만들었거나,
  S2가 이미 있는 근거를 과도하게 불충족으로 판정했을 가능성이 큰 우선 감사군이다.
  나머지는 gold 일부만 수용한 14건과 accepted 조문이 없는 6건이므로 같은 완화
  규칙을 일괄 적용하면 안 된다.
- 완전 gold인데 ABSTAIN한 18건의 candidate Token-F1@800 평균은 19.10이다.
  답변 가능성은 있지만, gold 조문 완전 포함만으로 법적 답변 안전성이 증명되지는
  않으므로 C3에서 requirement별 판정 전환을 전수 감사한다.
- ABSTAIN 후보 35건의 available-only Token-F1@800은 15.11이다. 모든 반려를
  그대로 답변으로 바꾸는 것만으로는 품질 문제가 해결되지 않는다.
- 재현 ParSeR 226문항은 answered-only Token-F1 43.6, end-to-end 42.4,
  retrieval Macro F1 53.5/52.1이었다. 최신 하네스는 전체 분모 조문 Macro F1
  58.44인데 ANSWER-only
  Token-F1@800은 26.11이다. 파이프라인과 검색기가 달라 공식 우열 비교는
  아니지만, 조문을 찾은 뒤 결론을 쓰는 S3 단계에도 큰 손실이 있음을 보여 준다.
- 기존 S3 답변 148건 중 137건에 `전제:` 또는 `한계:`가 있었고, 핵심 claim
  부분은 평균 약 231자였다. 안전 고지를 통째로 버릴 근거는 없으므로 결론 claim을
  먼저 두고, generic disclaimer와 중복 설명만 생성하지 않게 한다. 결론을 바꾸는
  전제·한계는 공개 답변 뒤에 보존한다.

따라서 정책 안전성과 답변 정밀도를 같은 스위치로 다루지 않는다. 공개 ABSTAIN은
유지하면서, 답변이 허가된 경우의 S3 표현을 먼저 개선한다.

## 3. 수정 내용과 이유

### 3.1 S1: hop 중심 분해에서 결론 중심 최소 계획으로

변경 파일:

- `skills/legal_issue_and_query_planning/SKILL.md`
- `skills/legal_issue_and_query_planning/references/contract.md`
- `runtime/local_ollama_executor.py`

변경 내용:

- 질문이 하나의 결론을 요구하면 여러 조문이 필요해도 하나의 answer target을 우선한다.
- 벤치마크의 hop 수에 맞추려고 issue/evidence를 하나씩 만들지 않는다.
- 한 조문이 규칙·통상 요건·효과를 함께 정하면 별도 critical item으로 쪼개지 않는다.
- 정의·배경·절차는 질문이 요구하거나 결론을 바꾸는 경우에만 critical로 둔다.
- 각 서술 필드는 한 문장으로 제한하고 질문·근거 설명의 반복을 금지한다.
- `query_terms`는 2~6개의 짧고 중복 없는 법률어로 지시한다.
- 런타임은 NFKC·대소문자·공백을 정규화했을 때 같은 `query_terms`와
  `statute_hints`만 순서 보존 중복 제거한다.
- S1 생성 한도를 1,600에서 3,072 토큰으로 맞췄다.
- 이후 잘린 JSON은 Ollama의 `done_reason`, `eval_count`, `num_predict`를 오류에
  기록해 실제 토큰 한도 종료와 다른 JSON 오류를 구분한다.

이 변경은 검색 결과를 정답으로 간주하거나 법적 쟁점을 삭제하지 않는다. 모델이
만든 계획의 과잉 구조와 전송 중복만 줄인다.

### 3.2 S2: 열린 법률 의견이 아니라 닫힌 요구사항 충족 판정

변경 파일:

- `skills/provision_coverage_assessment/SKILL.md`
- `skills/provision_coverage_assessment/references/contract.md`
- `runtime/local_ollama_executor.py`

변경 내용:

- S1이 공급한 `completion_requirements`만 판정한다.
- 완전한 법률 의견에 있으면 좋은 정의·배경·절차를 새 결손으로 만들지 않는다.
- 단순 관련 조문이 아니라 요구사항을 실제 충족하는 최소 조문 집합만 링크한다.
- `satisfied_aspects`와 `missing_aspects`에는 설명문이 아니라 공급된
  `requirement_id`만 넣는다.
- `criterion_results`가 모든 공급 ID를 정확히 한 번씩 포함할 때만, 런타임이 그
  결과에서 aspect ID 배열을 다시 만든다.

마지막 복구는 법적 상태를 새로 판단하지 않는다. 모델이 이미 낸 각 criterion의
상태를 구조 필드로 옮기는 경우에만 작동한다. ID가 누락·중복되면 기존처럼
validator가 실패시켜 재시도하게 한다.

### 3.3 S3: 근거 보존, 공개 답변은 결론 중심

변경 파일:

- `skills/grounded_legal_answer_generation/SKILL.md`
- `skills/grounded_legal_answer_generation/references/contract.md`
- `runtime/local_ollama_executor.py`

변경 내용:

- 요청된 결론을 첫 문장에 놓고, target마다 필요한 최소 claim을 사용한다.
- 정확성을 해치지 않는 범위에서 규칙과 직접 적용을 한 claim으로 합친다.
- 전체 조문 인용, 배경 강의, 같은 결론의 반복을 금지한다.
- 공개 `GENERATE_ANSWER`의 기존 6,000자 안전 한도는 유지하고, 비공개 benchmark
  candidate만 800자로 제한한다. 공식 Token-F1@800은 공개 답변의 첫 800자를
  그대로 평가한다.
- 공개 문자열은 `claim text + citation marker`를 먼저 직렬화하고, 결론을 바꾸는
  material `assumptions`와 `limitations`를 뒤에 보존한다.
- generic disclaimer와 claim을 반복한 감사 문구는 생성하지 않게 지시한다.
- 결론을 바꾸는 조건은 반드시 cited conditional claim에도 직접 쓴다.
- limited 모드는 입력에서 이미 확정된 deferred target 이름을 `제외: ...`로 공개
  문자열에 붙이고 material limitation도 보존한다.
- 답변 target이 정확히 하나일 때 claim의 target이 비었거나 범위를 벗어나면 그
  유일한 target으로 복구한다. 여러 target에서는 추측하지 않고 validator에 맡긴다.
- 길이 초과 모델 원문을 조용히 되돌리지 않고, 정규화된 답변을 validator가 명확한
  길이 오류로 판정하여 재시도하게 한다.

### 3.4 매니페스트와 candidate 경계 동기화

`skills/skill-pack-manifest.json`을 pack `1.3.0`, Qwen3.8-27B 기준으로 갱신하고
S3의 `GENERATE_BENCHMARK_CANDIDATE` 모드를 실제 스키마·런타임과 맞췄다.

JSON 입출력 모양은 바꾸지 않았으므로 `contract_version`과 schema version은
`1.0`을 유지한다. 공개 ABSTAIN의 `answer=null`과 structured withholding reason도
그대로다. candidate는 다음 조건을 모두 지켜야 한다.

- harness의 별도 diagnostic authorization이 있어야 한다.
- public policy outcome은 계속 ABSTAIN이다.
- candidate provision은 accepted provision으로 승격되지 않는다.
- candidate answer와 citation은 사용자에게 게시할 수 없다.

### 3.5 실제 실패만 남긴 스킬 축약, KURE 설정은 동결

2026-08-22 추가 수정에서는 스킬이 길어질수록 모델의 핵심 판단이 흐려질 수
있다는 운영 경험을 반영했다. 스키마·검증기·어댑터가 이미 강제하는 형식 규칙과
예외 설명은 SKILL 본문에서 반복하지 않고, 각 스킬에는 다음 의미 판단만 남겼다.

- S1: 요청 결론, 독립적으로 필요한 critical evidence, 간결한 검색 요청
- S2: 닫힌 requirement 단위 법적 충족과 missing fact/statute 구분
- S3: 허가된 범위의 결론 우선 최소 cited claim

S1은 검색 요청을 더 짧게 만들지만, 어느 질의 필드를 KURE에 전달할지는 스킬이
아니라 고정된 실험 하네스가 결정한다. 기준선에서 사용한 필드 우선순위를 이번
본 패치에서 바꾸지 않았다. 의미 질의만 KURE에 직접 전달하는 라우팅은 합리적인
후보지만 검색 결과를 바꾸므로 별도 `R1` 조건으로 분리한다. 출력 스키마와 공개
ABSTAIN/candidate 경계도 변경하지 않았다. 실제 입력 JSON이 함께 제공되므로 생성
프롬프트에서는 장황한 입력 스키마 반복을 제거하고, 출력 스키마와 동적 식별자
제약만 유지했다.

여기서 축약 대상은 설명문의 길이와 반복이다. 별도 조문·예외·교차참조가 필요한
critical evidence나 그 항목별 최소 1개 검색 요청은 줄이지 않는다. KURE 2-hop의
높은 recall이 이 구조적 query diversity에서 왔을 가능성을 보호하기 위해서다.

추가로 저장 결과에서 드러난 과잉 엄격도와 낮은 답변 점수를 직접 겨냥해 의미
판정 규칙을 다음처럼 좁혔다.

- S1은 예상 조문 수와 requirement 수를 일대일로 맞추지 않는다. 질문에 이미 주어진
  사실은 조문 검색 requirement로 만들지 않고, 요청 결론을 바꾸는 법적 명제만
  critical로 둔다.
- S2는 각 requirement가 표현한 법적 명제 범위에서 충족 여부를 판정한다. 한 조문이
  다른 requirement나 최종 답변 전체를 혼자 해결하지 못한다는 이유로 이미 충족한
  requirement를 missing으로 내리지 않는다. 반대로 단순 관련성은 support가 아니다.
- 법은 완전하고 질문 사실만 적용 분기를 고르는 경우 S2는
  `covered + conditional + missing_fact`를 사용한다. `scope_excess`는 비핵심 문맥
  진단에만 쓰며, 지원되지 않은 critical evidence를 숨기는 수단으로 쓰지 않는다.
- S3의 첫 claim은 조문 설명이 아니라 요청된 결과를 직접 답한다. target당 원칙적으로
  한 claim만 쓰고, 결론을 바꾸는 조건은 note가 아니라 cited conditional claim 안에
  넣는다.

이는 `38 ABSTAIN 중 complete-gold 18건`을 무조건 ANSWER로 승격하는 완화가 아니다.
동일 S2 입력 재생에서 requirement별 false negative만 교정하고, 단순 관련 조문을
covered로 올리는 false positive는 그대로 실패로 판정한다.

### 3.6 변경별 원인 가설과 반증 조건

| 변경 | 저장 결과에서 관측된 원인 | 성공하면 먼저 움직여야 할 값 | 반증 또는 실패 판정 |
| --- | --- | --- | --- |
| S1 출력 축약 + 3,072 토큰 | S1 실패 37건 중 잘린 JSON 35건; 3-hop 실패 집중 | S1 malformed/truncation, execution failure 감소 | JSON 실패가 유지되거나 first-stage/BGE 조문 recall이 하락 |
| S1 결론 중심 evidence 분해 | hop 수에 맞춘 과잉 target과 반복 설명이 출력 길이를 키울 가능성 | 서술 길이·중복어 감소, 독립 critical item과 gold 조문 recall 유지 | 계획은 짧아졌지만 독립 조문 요청이나 gold 조문 누락 증가 |
| S2 closed-requirement 판정 | 이미 있는 근거에도 완전한 법률 의견 기준으로 결손을 확장하는 과잉 엄격도 | false `missing_statute`, policy ABSTAIN 감소 | 무관 조문을 covered로 바꾸거나 provision precision/F1 하락 |
| S3 결론 우선 직렬화 | 전제·한계 반복으로 첫 800자 정답 토큰 정밀도 저하 | 동일 accepted 조문에서 Token-F1@800·LF-Eval 상승 | citation integrity 저하 또는 법적 조건 소실 |
| 단일 target transport 복구 | S3 2건이 존재하지 않는 target을 참조 | 해당 contract failure 0건 | 다중 target을 추측해 잘못 복구 |

이 표의 목적은 사후에 좋은 수치만 고르는 것을 막는 것이다. 예를 들어 S2 수정
뒤 ANSWER 비율만 오르고 조문 Precision/F1이 내려가면 과잉 엄격도 수리가 아니라
판정 완화에 불과하다. S3 수정 뒤 조문 지표가 바뀐다면 고정 입력 재생이 깨진
것이므로 해당 비교 자체가 무효다.

## 4. 의도적으로 바꾸지 않은 것

- KURE 모델·인덱스, BGE reranker, Top-k, fusion 방식
- KURE에 전달하는 질의 필드의 기준선 우선순위
- 비교용 BM25 구현과 기존 BM25 질의 호환 경로
- 최대 retrieval round와 no-progress 종료 규칙
- critical blocker가 남았을 때의 공개 ABSTAIN 정책
- accepted provision reducer와 citation-integrity validator
- 다중 target의 의미적 scope 판단
- LF-Eval judge 또는 KoBLEX 평가 코드

최신 226 결과에는 `STAGE_PROVENANCE_UNAVAILABLE` 경고가 있어 KURE의
first-stage/RRF/BGE 단계별 recall을 이 결과만으로 확정할 수 없다. 검색기나 질의
라우팅까지 동시에 바꾸면 S1/S2/S3 수정 효과와 검색기 효과가 섞인다.

## 5. 추가한 회귀 테스트 정의

`tests/test_local_ollama_executor.py`와 `tests/test_retrieval_algorithms.py`에 다음
테스트를 추가하거나 갱신했다. 이 환경에서는 실행하지 않았다.

- S1 query term/statute hint 중복 제거와 3,072 token budget
- Ollama `done_reason=length` JSON 실패의 `MODEL_OUTPUT_TRUNCATED` 진단
- S2의 완전한 criterion 결과에서 aspect ID 배열 복구
- S3 단일 target scope 복구
- 결론 claim이 먼저 나오고 material assumptions/limitations가 뒤에 보존됨
- limited 모드에서 deferred target 이름이 `제외:`로 직렬화됨
- 공개 답변 6,000자와 비공개 benchmark candidate 800자 경계

## 6. 실험자 실행 순서

### 단계 A: 정적·계약 회귀

1. skill schema/semantic validator 테스트를 실행한다.
2. `tests/test_local_ollama_executor.py`를 실행한다.
3. candidate output이 public answer 필드로 유출되지 않는지 확인한다.
4. citation marker와 accepted/candidate provision 경계를 확인한다.

### 단계 B: 원인 재현 smoke

같은 Qwen3.8 revision, temperature, corpus, KURE/BGE 설정으로 아래 저장 실패를
먼저 재실행한다.

- S1 truncation 대표: `qa_213_2hop_812_rand`, `qa_140_3hop_540_rand`,
  `qa_32_3hop_125_rand`
- S1 duplicate 대표: `qa_125_1hop_225`, `qa_136_2hop_523_rand`
- S2 aspect ID 대표: `qa_3_2hop_6`
- S3 target scope 대표: `qa_365_2hop_578`, `qa_244_2hop_931_rand`

판정은 단순 ANSWER 여부가 아니라 각 실패 class가 사라졌는지로 한다.

### 단계 C: 단계별 ablation

한 번에 한 원인만 바꾼다. S1은 검색 요청을 생성하므로 검색 결과까지 달라질 수
있지만, S2와 S3는 저장된 입력을 재생하여 앞 단계를 완전히 고정할 수 있다.

| 조건 | 바꾸는 것 | 고정하는 것 | 원인 판정 |
| --- | --- | --- | --- |
| C0 | 없음 | origin/main 전체 | 수정 전 기준 |
| C1 | token budget·중복 제거·안전한 ID/scope transport 복구 | 기존 S1/S2/S3 지시와 KURE 설정 | 실행/계약 실패 수리 효과 |
| C2 | 축약된 결론 중심 S1 | KURE 모델·질의 우선순위·Top-k·BGE·정책 | 계획 축약이 검색 recall을 보존하는지 |
| C3 | closed-requirement S2 | 같은 S1 결과와 같은 candidate provisions 재생 | coverage false-negative 수리 효과 |
| C4 | concise conclusion-first S3 | 같은 accepted provisions와 같은 answer authorization 재생 | 최종 답변 표현 효과 |
| C5 | C1+C2+C3+C4 | 같은 실행 설정 | 상호작용을 포함한 전체 효과 |
| R1, 별도 | KURE semantic `query_text` 라우팅 | C5 스킬·정책·Top-k·BGE | 검색 질의 라우팅 효과 |

`R1`은 C5에 포함하지 않는다. R1이 좋아도 “스킬 수정으로 향상”이라고 쓰지 않고,
나빠도 S1/S2/S3 수리를 기각하는 근거로 쓰지 않는다.

S2 C3의 판정은 action 변화만 보지 않는다. C0에서 `uncovered/ABSTAIN`, C3에서
`covered/ANSWER`로 뒤집힌 문항을 전수 확인해, gold 조문 또는 판례 근거상 원래
false negative였는지 기록한다. S3 C4에서 provision 지표가 달라지면 입력 동결
실패이므로 결과를 폐기한다.

### 단계 D: 전체 226문항

smoke와 개발 ablation을 통과한 뒤에만 전체 226문항을 실행한다. 최소 보고 항목은
다음과 같다.

- ANSWER / ABSTAIN / EXECUTION_FAILURE와 실패 stage·class
- 실행 실패를 제외한 policy ABSTAIN rate와 전체 end-to-end rate
- provision Precision / Recall / F1 / EM
- Token-F1@800 end-to-end / answered-only / candidate diagnostic
- LF-Eval end-to-end / answered-only / candidate frozen input 결과
- 1/2/3-hop 분해
- first-stage@100, RRF@100, BGE@10/20/30 provenance와 recall
- citation-integrity pass rate
- 문항별 C0↔C5 paired delta와 별도 R1 delta

## 7. 수용 기준

다음 조건을 모두 확인하기 전에는 성능 개선으로 보고하지 않는다.

1. smoke에서 위 8개 대표 실패의 같은 contract error가 재발하지 않는다.
2. public ABSTAIN은 계속 `answer=null`이고 candidate leakage가 0건이다.
3. ANSWER의 citation-integrity pass rate가 기존 수준을 유지한다.
4. S1 malformed/truncation 35건과 총 execution failure 40건이 감소한다. 실패가
   `ABSTAIN`으로 재분류된 것만으로는 수리로 세지 않는다.
5. 동일 21문항 KURE 개발 gate에서 C5의 조문 Macro Recall/F1/전체 조문 충족이
   KURE 기준선 `73.81/61.49/66.67`을 하회하지 않는다. BM25 D4 기준선
   `75.40/57.26/61.90`은 보조 열로만 유지한다.
6. 전체 226 공식 비교에서 KURE 기준선 `Recall 69.69 / Macro F1 58.44 /
   complete 60.62`와 2-hop 기준선 `80.71 / 66.40 / 69.29`를 함께 보호한다.
   문항별 paired bootstrap 95% 신뢰구간과 provision Macro F1 비열등성 한계
   `-2.0%p`를 사전 등록하고, 낮은 F1을 ANSWER rate 상승으로 상쇄하지 않는다.
7. C4의 동일 입력 재생에서 answered-only Token-F1@800과 LF-Eval이 개선되고,
   citation integrity와 조건부 결론 보존이 유지된다.
8. 개선 주장은 C0-C5의 동일 문항 paired 결과로 제시하고 R1은 별도 열로 쓴다.

## 8. 해석 한계

- 최신 226 평가는 reconciled record이며 evaluator worktree가 dirty였다고 metadata에
  기록되어 있다.
- retrieval stage provenance가 불완전해 최신 KURE 단계별 성능은 아직 공식 비교할 수 없다.
- LF-Eval score는 공급되지 않았다. Token-F1만으로 법률 결론의 의미 정확성을
  확정하면 안 된다.
- ParSeR 비교는 검색기·정책·출력 구조가 다른 구조 비교이지 S3 단독 ablation이 아니다.
- `+14.60`은 BM25 D4의 동일 21문항 값이다. KURE는 같은 21문항에서 `+18.84`,
  전체 226 오류 포함 분모에서 `+6.39` F1 우위를 보였다. 어느 값도 검색기·정책·
  selected/accepted 단계 차이를 통제한 공식 인과 효과는 아니다. 최종 주장은
  held-out와 LF-Eval 전에는 “저장 결과에서 recall 주도 우위”로 한정한다.
- 이 문서는 코드 수정과 실험 계획까지의 상태다. 새 모델 실행 결과나 공식 점수는 없다.
