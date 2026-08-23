# KURE C5 full226 final report

- Status: COMPLETED_WITH_ERRORS (final gate: FAIL)
- Sequence: smoke8 PASS -> dev21 skipped -> KURE full226
- BM25 inference: not executed; reference manifest used only for configuration validation
- Provenance: a74e76d1c8fade04486b681974475d8c88f7f136 / 9a775367bc138124d5d5c678c1436161262f2110ecd5f7a1bc26ac1cc77d6297
- Outcomes: ANSWER 187, ABSTAIN 35, EXECUTION_FAILURE 4
- Citation integrity: 187/187 (100.0%)
- Stage provenance complete: True
- Public ABSTAIN leakage: 0

## Checkpoints

| Completed | Status | Failures | Recall | F1 | Complete | ETA (UTC) |
|---:|---|---:|---:|---:|---:|---|
| 40 | PASS | 0 | 0.766667 | 0.724683 | 0.600000 | 2026-08-22T14:42:15.990495+00:00 |
| 80 | PASS | 0 | 0.745833 | 0.701229 | 0.575000 | 2026-08-22T15:13:03.818222+00:00 |
| 120 | ERRORS_FOUND | 2 | 0.754167 | 0.708676 | 0.575000 | 2026-08-22T15:06:22.157558+00:00 |
| 160 | ERRORS_FOUND | 2 | 0.734375 | 0.687876 | 0.562500 | 2026-08-22T15:15:33.002634+00:00 |
| 200 | ERRORS_FOUND | 3 | 0.730000 | 0.680491 | 0.560000 | 2026-08-22T15:21:15.171931+00:00 |
| 226 | ERRORS_FOUND | 4 | 0.721976 | 0.670578 | 0.548673 | 2026-08-22T15:30:55.469844+00:00 |

## Final errors

- qa_309_3hop_881_rand2: legal_issue_and_query_planning did not produce a valid INITIAL_PLAN result after 2 attempts: question_anchor is not a question substring: T1
- qa_116_1hop_207: legal_issue_and_query_planning did not produce a valid INITIAL_PLAN result after 2 attempts: question_anchor is not a question substring: T1
- qa_85_1hop_135: provision_coverage_assessment did not produce a valid ASSESS_COVERAGE result after 2 attempts: legacy status conflicts with coverage axes; partially_covered requires a valid partial_kind: E1; legacy status conflicts with coverage axes; missing_evidence_items must equal all non-covered assessments; legacy status conflicts with coverage axes
- qa_549_2hop_834: provision_coverage_assessment did not produce a valid ASSESS_COVERAGE result after 2 attempts: legacy status conflicts with coverage axes; partially_covered requires a valid partial_kind: E1; legacy status conflicts with coverage axes; missing_evidence_items must equal all non-covered assessments; legacy status conflicts with coverage axes

## Final metrics and gate

- Macro recall: 0.721976 (gate 0.6969: PASS)
- Macro F1: 0.670578 (noninferiority gate 0.5644: PASS)
- Complete evidence: 0.548673 (gate 0.6062: FAIL)
- 2-hop recall: 0.721785 (gate 0.8071: FAIL)
- 2-hop F1: 0.672553 (noninferiority gate 0.6440: PASS)
- 2-hop complete evidence: 0.543307 (gate 0.6929: FAIL)

## Timing

- Full226: 31353.105 seconds (8.709 hours)
- Smoke + full: 32796.925 seconds (9.110 hours)
- Smoke-based estimate: 10.16 hours; actual completion was 1.454 hours earlier.
