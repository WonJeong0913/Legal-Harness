# Legal-Harness

**조문 근거 충족도 기반 스킬 하네스 — 한국어 다중 홉 법령 질의응답(KoBLEX)**

*A provision-evidence coverage-based skill harness for Korean multi-hop statutory QA. Research code and frozen result records for a KCI paper in preparation. Results here are development results on the 226-question KoBLEX test set, not an official leaderboard submission.*

---

## 이 저장소는

- 단일 LLM이 세 개의 스킬(S1 쟁점·질의 계획 → S2 조문 근거 충족도 평가 → S3 근거 기반 답변 생성)을 순서대로 수행하고, 조문 근거가 부족하면 답하지 않고 **보류(ABSTAIN)** 하는 하네스의 구현입니다.
- 논문에 쓰는 실험 결과를 **원자료(문항별 기록·집계·해시)와 함께** 보관합니다.
- 비교 기준선으로 KoBLEX 논문의 ParSeR를 **독립 재현한 코드**(`baselines/koblex_parser/`)가 들어 있습니다. 공식 구현을 그대로 실행한 것이 아니므로 **"ParSeR (Reproduced)"** 로 표기합니다.

> 현재 상태: 논문 작성 중. 아래 수치는 단일 실행(seed 0)의 개발 결과이며, 해석 시 [주의사항](#결과를-읽을-때-주의할-점)을 함께 봐 주세요.

## 핵심 결과 (KoBLEX test 226문항)

세 조건 모두 같은 226문항, 같은 생성 모델(Qwen3.8-27B Q8_0, 로컬 Ollama)을 사용했습니다. 점수는 0–100 (LF만 0–10) 척도입니다.

| 지표 | C02 + KURE | C02 + BM25s | ParSeR (Reproduced) |
|---|---:|---:|---:|
| 응답 / 보류 / 실행 실패 | 189 / 29 / 8 | 145 / 64 / 17 | 220 / 0 / 6 |
| 조문 macro F1 ¹ | 65.96 | 54.39 | 52.05 |
| 조문 micro F1 ¹ | 64.29 | 56.60 | 49.64 |
| 조문 완전 일치(EM) ¹ | 39.38 (89/226) | 26.55 (60/226) | 25.66 (58/226) |
| Token-F1@800 — 공개 답변 기준 ² | 32.52 | 24.40 | 42.44 |
| Token-F1@800 — 평가용 후보 포함 ³ | 34.86 | 27.97 | — |
| 로컬 Qwen LF (/10) — 공개 답변 기준 ² ⁴ | 6.274 | 4.487 | 6.239 |
| 로컬 Qwen LF (/10) — 평가용 후보 포함 ³ ⁴ | 6.739 | 5.261 | 6.239 |

1. **세 조건 모두 KoBLEX 공식 규칙**(공식 저장소 `experiments/lf-eval/eval_pipeline.py`의 `evaluate_retrieval`)으로 채점했습니다. 정답과 예측을 `hierarchy + content` 문자열 집합으로 보고, 문자열이 완전히 같을 때만 맞은 것으로 셉니다. 문항별 P/R/F1/EM을 226문항에 대해 평균하며, micro F1은 전체 TP로 계산한 보조값입니다. C02의 예측은 각 실행이 채택한 조문 ID를 원본 법령 parquet의 같은 행 문자열로 바꿔 채점했습니다(`scripts/score_koblex_official_provision_rule.py`, GPU·모델 미사용). 보류·실행 실패 문항도 분모에 들어가고, 저장된 채택 조문이 있으면 그대로 채점합니다. ParSeR 실패 6문항은 선택 조문이 없어 0점이고, C02 실패 문항 중 BM25s 11/17, KURE 4/8은 0점이 아닙니다.
   하네스 평가기(`scripts/evaluate_dev_runs.py`)의 조문 규칙은 정답 인정 범위가 더 넓습니다(조문 ID 묶음, 정규화, 조 단위 정답의 항 단위 일치 인정). 그래서 값이 더 높고(macro F1 KURE 70.22, BM25s 57.63, ParSeR 55.01 / EM 42.04, 28.76, 26.99) 보조 지표로만 씁니다. 각 결과 디렉터리의 README와 `summary.md`에 나오는 조문 점수는 이 하네스 규칙 값입니다.
2. 하네스가 실제로 반환한 답변만 채점하고, 보류·실행 실패는 0점입니다.
3. 보류 문항에 대해 하네스가 내부적으로 만든 **평가용 후보 답변**을 채점에 넣고, 후보가 없거나 실행이 실패한 문항은 0점입니다. 후보 답변은 공개 답변이 아니며 사용자에게 반환되지 않습니다. 논문의 대표 기준(공개 답변 vs 후보 포함)은 아직 확정하지 않았습니다.
4. **KoBLEX 공식 LF-Eval(GPT-4o + DeepEval)이 아닙니다.** 공식 루브릭과 투영 방식을 따르되 judge를 로컬 Qwen3.8-27B(temperature 0, seed 0)로 바꾼 적응형 평가이며, 원 논문의 LF-Eval 수치와 직접 비교할 수 없습니다.

ParSeR (Reproduced)는 보류를 하지 않기 때문에 공개 답변 기준 Token-F1에서 C02보다 높습니다. 보류 정책이 Token-F1을 낮추는 효과는 결과의 일부이며 숨기지 않습니다.

### 짝비교 신뢰구간 (공식 규칙, 226문항)

| 비교 | 조문 F1 차이 [95% CI] | EM 차이 [95% CI] |
|---|---:|---:|
| C02 + KURE − ParSeR | +13.91 [+8.64, +19.16] | +13.72 [+7.08, +20.35] |
| C02 + BM25s − ParSeR | +2.34 [−3.00, +7.64] | +0.88 [−4.87, +6.64] |
| C02 + KURE − C02 + BM25s | +11.57 [+6.90, +16.23] | +12.83 [+6.64, +19.03] |

226문항을 짝지어 10,000번 복원 추출한 백분위 부트스트랩입니다(NumPy `default_rng`, seed 20260901, 모든 비교에 같은 추출 인덱스 사용). 2026-09-01 보고서와 같은 절차이며, 스크립트가 그 보고서의 저장값을 먼저 재현한 뒤 계산합니다. **BM25s와 ParSeR의 차이는 두 지표 모두 구간이 0을 포함합니다.** KURE가 포함된 두 비교는 6개 구간에 Bonferroni 보정을 적용해도 0을 포함하지 않습니다. 문항별 승/무/패, 보정 구간은 공식 규칙 기록의 `aggregate.json`에 있습니다.

### 결과 출처

| 결과 | 기록 위치 | 생성 코드 커밋 |
|---|---|---|
| C02 + KURE 226문항 | [`records/evaluations/kure-c02-qwen38-q8-full226-20260826/`](records/evaluations/kure-c02-qwen38-q8-full226-20260826/) | `c02e281` |
| C02 + BM25s 226문항 (같은 하네스, 1단계 검색기만 교체) | [`records/reports/c02-bm25s-parser-ablation-qwen38-20260902/`](records/reports/c02-bm25s-parser-ablation-qwen38-20260902/README.md) | 실행 `edc9da4`, 기준 `c02e281` |
| KURE 비교용 재평가 (BM25s와 같은 평가기) | [`records/evaluations/c02-kure-full226-comparable-20260902-r1/`](records/evaluations/c02-kure-full226-comparable-20260902-r1/) | 평가기 `edc9da4` |
| 세 조건 로컬 LF | [`records/adapted-local-qwen38-lf-eval-c02-bm25s-linked-r1-20260902/`](records/adapted-local-qwen38-lf-eval-c02-bm25s-linked-r1-20260902/) | `c1eb0c4` |
| C02 vs ParSeR 로컬 LF (r1, r2 바이트 동일) | [`records/adapted-local-qwen38-lf-eval-c02-vs-parser-r1-20260901-a839228/`](records/adapted-local-qwen38-lf-eval-c02-vs-parser-r1-20260901-a839228/) | `a839228` |
| ParSeR (Reproduced) 226문항 | [`records/baselines/koblex-parser-reproduced-qwen38-q8-226-23f5c9ae-…/`](records/baselines/koblex-parser-reproduced-qwen38-q8-226-23f5c9ae-45a5-4d7e-a88f-fbcfb5320185/), [재현 노트](docs/KOBLEX_PARSER_BASELINE_REPRODUCTION_NOTES.md) | — |
| **공식 규칙 조문 점수·짝비교 신뢰구간** (세 조건) | [`records/evaluations/koblex-official-provision-rule-20261104/`](records/evaluations/koblex-official-provision-rule-20261104/) | `c629c53` |
| (보조) ParSeR 하네스 규칙 재채점 | [`records/evaluations/koblex-parser-reproduced-harness-provision-rule-20261104/`](records/evaluations/koblex-parser-reproduced-harness-provision-rule-20261104/) | `8aa86fe` |
| KoBLEX 원 논문 Table 1–10 대조 보고서 | [`records/reports/koblex-paper-tables-c02-parser-20260901/`](records/reports/koblex-paper-tables-c02-parser-20260901/README.md) | — |

각 결과 디렉터리에는 `aggregate.json`, 문항별 기록(`per_question.*`), 실행 메타데이터, SHA-256 영수증이 있습니다. **결과를 재현하려면 표의 커밋을 체크아웃하세요.** `main`의 코드는 그 이후 수정이 반영된 최신 상태이므로 결과 생성 시점의 코드와 다를 수 있습니다.

논문 인용용 고정 지점은 태그 [`kci-results-v3`](https://github.com/WonJeong0913/Legal-Harness/tree/kci-results-v3)입니다.

## 결과를 읽을 때 주의할 점

- **단일 실행입니다.** 모든 조건이 seed 0 한 번 실행입니다. bootstrap 신뢰구간은 문항 표본 불확실성만 반영하며, 모델 실행 간 변동은 측정하지 않았습니다.
- **2026-09-01 KoBLEX 대조 보고서**(`records/reports/koblex-paper-tables-c02-parser-20260901/`)의 조문 점수와 짝비교 신뢰구간은 C02(하네스 규칙)와 ParSeR(공식 규칙)를 섞어 계산한 값이라 현재 기준과 다릅니다. 같은 보고서의 "실행 실패=0" 설명도 C02 조건에는 맞지 않습니다. 현재 기준은 공식 규칙 기록입니다.
- **C02 + KURE 226문항은 이어붙인 실행입니다.** 원 체크포인트 58문항, 재시도 2문항, 이어 실행 166문항을 같은 커밋·설정으로 합쳤고, 문항별 출처는 `audit/source-row-map.json`에 있습니다.
- **BM25가 두 종류입니다.**
  - 논문의 BM25 비교 조건은 ParSeR와 같은 **`bm25s` 0.3.10** 기반입니다(`scripts/c02_bm25s_ablation.py`). ParSeR의 `Bm25Retriever`와 상위 100개 순서가 일치하는지는 **실제 C02 질의 3개**에 대해 확인했습니다.
  - `scripts/build_koblex_indexes.py`가 만드는 기본 BM25 인덱스와, 이를 쓴 초기 기록(`records/runs/bm25-*`, `bm25-effective184` 등)은 **SQLite FTS5** 기반입니다. 두 BM25 결과를 섞어 해석하지 마세요.
- **모델 이름:** 별칭 `legal-harness-qwen38-q8`의 "qwen38"은 **Qwen3.8**(27B)을 뜻하며 8B 모델이 아닙니다. GGUF 메타데이터의 아키텍처 태그는 `qwen35`, 양자화는 Q8_0, blob SHA-256은 `f5c702d8…e4c8`입니다. thinking은 비활성화했습니다. 정의 파일은 [`configs/ollama/Qwen3.8-27B-Q8_0.Modelfile`](configs/ollama/Qwen3.8-27B-Q8_0.Modelfile)입니다.
- `records/baselines/koblex-parser-baseline-qwen38-q8-226-f3e8ee44-…/`는 재순위 질의를 잘못 넣은 **무효 실행**(35/226에서 중단)이며, 같은 디렉터리의 `INVALID_RUN_NOTE.md`에 사유가 있습니다. 비교에 쓰지 않습니다.
- **지연 시간(latency)** 필드는 기록돼 있지만, 이어 실행을 합친 결과라 속도 비교 근거로 쓰지 않습니다.
- 메타데이터에 남은 `/root/...`, `/workspace/...` 절대 경로는 감사 추적용이며 다른 환경에서는 그대로 동작하지 않습니다.

## 저장소 구조

| 경로 | 내용 |
|---|---|
| `harness/`, `runtime/`, `retrieval/` | 하네스 상태 기계, 로컬 Ollama 실행기, 검색 파이프라인(KURE·BM25 → RRF → BGE 재순위) |
| `skills/` | S1·S2·S3 스킬 정의(`SKILL.md`), 입출력 스키마, 출력 검증기 |
| `baselines/koblex_parser/` | ParSeR (Reproduced) — 하네스와 독립된 코드 경로 |
| `scripts/` | 실행·평가·인덱스 구축·LF 후처리 스크립트 |
| `frozen_manifests/` | BM25s ablation과 KURE 조건의 고정 실행 매니페스트 |
| `records/` | 실험 기록. 논문 결과는 위 [결과 출처](#결과-출처) 표의 디렉터리 |
| `data/koblex/manifests/` | 데이터·실행 매니페스트(원본 데이터 자체는 미포함) |
| `docs/` | 프로토콜·재현 노트·작업 기록 — [문서 안내](docs/README.md) |
| `provision_coverage_skill_harness_md_split/` | 연구 설계서(2026-08 설계 당시 문서) |
| `tests/` | 단위 테스트 |

## 포함하지 않은 것

| 항목 | 이유 | 얻는 방법 |
|---|---|---|
| KoBLEX QA·법령 원본 및 정규화 코퍼스 (`data/koblex/{qa,statute,normalized}`) | 재배포 조건을 확인하지 못함 | [KoBLEX 공식 저장소](https://github.com/daehuikim/KoBLEX) 안내, 법령 코퍼스는 Hugging Face `JihyungL/KoBLEX-statute`. 사용한 파일의 SHA-256은 각 결과의 `metadata.json`에 있음 |
| 검색 인덱스 (`data/koblex/indexes`, 약 1.1 GB) | 용량 | `scripts/build_koblex_indexes.py`, `scripts/build_kure_exact_index.py`로 재생성 |
| 모델 가중치 (`models/`) | 용량·라이선스 | KURE `nlpai-lab/KURE-v1`, 재순위기 `dragonkue/bge-reranker-v2-m3-ko`, 생성 모델 Qwen3.8-27B Q8_0 GGUF (blob SHA-256으로 확인) |
| 실행별 원시 검색 추적 (C02 약 62 MB, BM25s 약 250 MB) | 용량 | 집계·문항별 결과·영수증은 포함 |

## 재평가 예시

데이터를 복원한 뒤, 저장된 C02 + KURE 배치를 다시 채점합니다(결과 생성 커밋 `c02e281`에서 실행).

```bash
git checkout c02e281
python3 scripts/evaluate_dev_runs.py \
  --batch-dir records/evaluations/kure-c02-qwen38-q8-full226-20260826/batch \
  --dataset data/koblex/qa/test-00000-of-00001.parquet \
  --corpus data/koblex/normalized/statute.jsonl \
  --output-dir /tmp/legal-harness-c02-reevaluation \
  --require-stage-provenance
```

`aggregate.json`, `per_question.csv`, `summary.md`는 같은 디렉터리의 `SHA256SUMS`와 일치해야 합니다(메타데이터 타임스탬프는 달라짐). 실행 환경 정보는 각 실행의 계획 파일(`plan.json`, `execution-plan.json`)과 배치 메타데이터에 기록돼 있습니다. 별도의 `requirements` 파일은 아직 없습니다.

## 브랜치와 태그

- `main`: 논문 결과를 만든 코드(C02, BM25s ablation, LF 후처리)와 결과 기록을 합친 기준 브랜치.
- `kci-results-v3`: 논문 인용용 고정 태그. 세 조건을 KoBLEX 공식 조문 규칙으로 채점한 기준.
- `kci-results-v2`: 이전 고정 지점. 세 조건을 하네스 규칙으로 맞춘 상태(ParSeR 55.01 / 26.99)로, 현재는 보조 지표입니다.
- `kci-results-v1`: 이전 고정 지점. C02는 하네스 규칙, ParSeR는 공식 규칙으로 채점 규칙이 섞여 있던 상태로, 비교에 쓰지 않습니다.
- `archive/*` 태그: 개발 중 실험 브랜치(c04–c48 등)의 보존본입니다. **논문 결과의 근거가 아니며**, 실패했거나 채택하지 않은 시도도 포함합니다. `archive/wip/*`는 커밋하지 않았던 로컬 작업을 그대로 보존한 스냅샷으로, 검토되지 않은 상태입니다.

## 출처

- KoBLEX: Lee, Kim, Hwang, Kim, Lee. *KoBLEX: Open Legal Question Answering with Multi-hop Reasoning.* EMNLP 2025. <https://aclanthology.org/2025.emnlp-main.200/>
- 이 저장소는 팀 저장소 [`uminlee02/Legal-Harness`](https://github.com/uminlee02/Legal-Harness)에서 정리한 사본입니다.

라이선스는 아직 정하지 않았습니다. 코드를 재사용하려면 먼저 문의해 주세요.
