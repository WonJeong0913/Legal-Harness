# Fixed-input C5 round-merge ablation

**Development ablation only.** The rule was chosen while inspecting the same full226 traces, so this is not new held-out evidence. S2/S3 were not replayed; these candidate metrics are not final answer-quality evidence and must not replace the official C5 score.

| Variant | Complete | Macro precision | Macro recall | Gains | Losses |
| --- | ---: | ---: | ---: | ---: | ---: |
| actual_trace | 137 | 0.1043 | 0.7830 | 0 | 0 |
| hybrid_preserve_5_fill_5 | 139 | 0.1080 | 0.7995 | 14 | 12 |
| hybrid_preserve_9_fill_1 | 140 | 0.1064 | 0.7913 | 6 | 3 |
| rank_normalized | 140 | 0.1086 | 0.8033 | 14 | 11 |
| raw_score_reconstructed | 137 | 0.1043 | 0.7830 | 0 | 0 |
| request_rank_round_robin | 139 | 0.1082 | 0.8011 | 14 | 12 |
| request_rank_top1_guarded_swap | 142 | 0.1059 | 0.7935 | 5 | 0 |

## Trace fidelity

- Normal sidecar-backed questions: 222
- Cumulative `round_selected` union matched final state candidates: 222
- Candidate-state mismatch IDs: none
- Raw-score reconstruction exactly matched all round selections: 222
- Raw-score reconstruction mismatch IDs: none

## Paired regression cohort

- D4 accepted-complete / C5 accepted-incomplete (2-hop): 29
- BGE@10-complete round-merge losses: 15

## Corrected historical hand analysis

- The earlier 93/34/15/80 first-complete split and 80 two-hop count were corrected after exact raw trace parity, request ordering, and cross-issue alias rank unioning.
