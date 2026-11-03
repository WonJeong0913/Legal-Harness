-- Legal-Harness speed-quality diagnostic, 2026-08-24.
--
-- The upstream analysis is the executed speed_quality_diagnostic.ipynb. It
-- reads immutable D4/C5/ParSeR evaluations, C5 raw run records, and reuses the
-- official Legal-Harness gold-group evaluator. These SQLite-compatible
-- statements are the bounded final shaping layer embedded in artifact.json.

-- Dataset: headline
SELECT
  8.709196 AS c5_wall_hours,
  138.730553 AS c5_wall_seconds_per_item,
  127.717 AS warm_estimated_seconds_per_item,
  0.079 AS warm_estimated_reduction,
  0.834 AS s1_s2_recorded_latency_share,
  49 AS later_round_new_complete_items;

-- Dataset: system_comparison
WITH systems(system_order, system, answer_rate, failure_rate,
             provision_f1, provision_recall, complete_rate,
             token_f1_e2e, recorded_mean_seconds, wall_hours,
             comparison_note) AS (
  VALUES
    (1, 'KURE D4', 0.6549, 0.1770, 0.584425, 0.696903, 0.6062,
     0.17097, 341.4478, NULL,
     '기록된 inner latency; clean batch wall은 mixed provenance 때문에 없음'),
    (2, 'KURE C5', 0.8274, 0.0177, 0.670578, 0.721976, 0.5487,
     0.30193, 136.3282, 8.7092,
     '공식 226 batch wall과 evaluator latency 모두 확인됨'),
    (3, 'ParSeR Reproduced', 0.9735, 0.0265, 0.5208, 0.5101, NULL,
     0.4244, 30.2310, 2.2012,
     '220 success를 226 분모로 조정; abstention·citation 계약 없음')
)
SELECT * FROM systems ORDER BY system_order;

-- Dataset: latency_by_round
WITH rounds(retrieval_rounds, items, mean_latency_seconds,
            median_latency_seconds, mean_attempts, mean_generated_tokens,
            accepted_complete_rate) AS (
  VALUES
    (0, 2, 61.158, 61.158, 2.000, 2314.000, 0.000),
    (1, 96, 83.352, 82.016, 3.083, 2976.479, 0.740),
    (2, 52, 141.252, 135.483, 5.327, 5154.808, 0.423),
    (3, 76, 201.855, 195.367, 7.224, 7535.697, 0.408)
)
SELECT * FROM rounds ORDER BY retrieval_rounds;

-- Dataset: stage_time
WITH stages(stage_order, stage, attempts, generated_tokens,
            total_interval_seconds, recorded_latency_share) AS (
  VALUES
    (1, 'S1 initial plan', 251, 299100, 9378.910, 0.304),
    (2, 'S1 gap plan', 204, 113553, 3030.283, 0.098),
    (3, 'S2 coverage', 437, 508201, 13306.264, 0.432),
    (4, 'S3 answer', 188, 179182, 4074.727, 0.132),
    (5, 'S3 benchmark candidate', 46, 31097, 907.926, 0.029)
)
SELECT * FROM stages ORDER BY stage_order;

-- Dataset: round_gold_gain
WITH gains(cumulative_round, candidate_complete_items,
           candidate_complete_rate, candidate_macro_recall,
           new_complete_at_round) AS (
  VALUES
    (1, 89, 0.393805, 0.595133, 89),
    (2, 122, 0.539823, 0.727876, 33),
    (3, 138, 0.610619, 0.775811, 16)
)
SELECT * FROM gains ORDER BY cumulative_round;

-- Dataset: speed_scenarios
WITH scenarios(scenario_order, scenario, evidence_class,
               mean_seconds_per_item, full226_hours, quality_risk) AS (
  VALUES
    (1, 'Observed C5', '검증된 관측값', 138.731, 8.709,
     '관측 결과'),
    (2, 'Warm persistent resources only', '측정 구성요소 기반 추정', 127.717, 8.018,
     '객체 상태 격리와 replay 동등성 필요'),
    (3, 'Ideal 2-way after warm-up', '이론적 하한', 63.859, 4.009,
     'GPU 경합·결정성·실제 continuous batching 미반영'),
    (4, 'Ideal 4-way after warm-up', '이론적 하한', 31.929, 2.004,
     '실측 전 예상값으로 사용할 수 없음'),
    (5, 'Observed ParSeR batch wall', '검증된 관측값', 35.064, 2.201,
     'C5와 다른 abstention·citation 계약')
)
SELECT * FROM scenarios ORDER BY scenario_order;
