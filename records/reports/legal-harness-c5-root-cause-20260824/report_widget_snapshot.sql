-- Report-widget materialization for the 2026-08-24 C5 root-cause analysis.
--
-- The authoritative upstream reconciliation is Python-based and reuses
-- scripts/evaluate_dev_runs.py against D4/C5 per_question.csv, the C5 raw
-- retrieval traces, result states, and the immutable KoBLEX test parquet.
-- These SQLite-compatible SELECTs are the final, independently executable
-- shaping layer used to verify the bounded datasets embedded in artifact.json.

-- Dataset: headline
SELECT
  29 AS paired_regressions,
  15 AS round_merge_losses,
  15.0 / 29.0 AS round_merge_share,
  2 AS actual_s2_losses,
  2.0 / 29.0 AS actual_s2_share,
  0.6705781927020865 AS c5_macro_f1,
  0.5844254811068971 AS d4_macro_f1;

-- Dataset: paired_loss_stage
WITH stage_counts(stage_order, stage, count) AS (
  VALUES
    (1, 'KURE@100 이전', 4),
    (2, 'BGE Top-30 밖', 2),
    (3, 'BGE rank 21–30', 2),
    (4, 'BGE rank 11–20', 4),
    (5, 'round_selected 병합', 15),
    (6, 'S2 accepted 링크', 2)
)
SELECT
  stage_order AS "order",
  stage,
  count,
  count * 1.0 / SUM(count) OVER () AS share
FROM stage_counts
ORDER BY stage_order;

-- Dataset: c5_actual_funnel
WITH funnel(stage_order, stage, complete_count, denominator) AS (
  VALUES
    (1, 'KURE@100', 193, 222),
    (2, 'RRF@100', 192, 222),
    (3, 'issue BGE@30', 183, 222),
    (4, 'issue BGE@20', 175, 222),
    (5, 'issue BGE@10', 157, 222),
    (6, '실제 S2 후보', 137, 222),
    (7, 'S2 accepted', 124, 222)
)
SELECT
  stage_order AS "order",
  stage,
  complete_count,
  complete_count * 1.0 / denominator AS complete_rate,
  denominator
FROM funnel
ORDER BY stage_order;

-- Dataset: diagnostic_examples
WITH examples(question_id, observed_stage, evidence, interpretation) AS (
  VALUES
    ('qa_130_2hop_501_rand', 'S1 → KURE@100', 'gold는 부정행위 신고 포상금인데 S1은 신고자 보호조치를 계획·검색', '질문의 법적 효과를 다른 효과로 바꾼 명확한 S1 의미 이동'),
    ('qa_192_2hop_334', 'round_selected 병합', '형법 제229조가 E2 issue BGE 1위였지만 실제 후보에서 누락; 다른 공통 후보 하나가 E1·E2 quota를 동시에 충족', 'S2 판단 전 구조적 crowd-out'),
    ('qa_244_2hop_931_rand', 'S2 accepted', 'gold 제29조 chunk는 ‘다음 각 호의 서류’ 도입문만 있고 실제 목록은 없음', 'S2의 uncovered 판단은 법적 충분성 관점에서 합리적이며 benchmark granularity와 충돌'),
    ('qa_343_2hop_541', 'S1 requirement → S2', '질문상 이자채권은 3년인데 S1 completion requirement가 5년이라고 고정', '표면상 S2 누락이지만 선행 S1 계약 오류가 직접 원인'),
    ('qa_356_2hop_565', 'S1 → BGE', '청구이의의 소·집행문부여 이의의 소를 재심청구·즉시항고로 변경', '검색어가 정확한 법적 절차에서 벗어난 명확한 S1 의미 이동')
)
SELECT question_id, observed_stage, evidence, interpretation
FROM examples
ORDER BY question_id;
