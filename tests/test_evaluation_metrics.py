import csv
import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import evaluate_dev_runs
from scripts.evaluate_dev_runs import (
    CorpusEntry,
    EvaluationError,
    GoldGroup,
    LFEvalScores,
    _aggregate_answer_quality,
    build_gold_groups,
    evaluate_batch,
    koblex_normalize,
    koblex_official_prediction,
    main as evaluate_main,
    koblex_token_f1,
    koblex_token_f1_at_800,
    load_evaluation_splits,
    load_round_selected_sets,
    load_lf_eval_scores,
    percentile_type7,
    precision_recall_f1,
    render_markdown,
    write_outputs,
)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class GoldMappingTests(unittest.TestCase):
    def test_exact_duplicate_composite_image_and_punctuation_mapping(self):
        questions = {
            "q-exact": {
                "contexts": [
                    {"index": "법A 1조", "hierarchy": "법A 1조", "content": "정답 조문"}
                ]
            },
            "q-composite": {
                "contexts": [
                    {
                        "index": "법B 2조",
                        "hierarchy": "법B 2조",
                        "content": "제2조(의무)\n① 신고한다.\n② 위반하면 처벌한다.",
                    }
                ]
            },
            "q-image": {
                "contexts": [
                    {
                        "index": "법C 3조",
                        "hierarchy": "법C 3조 1항",
                        "content": "① 금액은 다음 표와 같다. 표내용",
                    }
                ]
            },
            "q-period": {
                "contexts": [
                    {"index": "법D 4조", "hierarchy": "법D 4조", "content": "끝 문장"}
                ]
            },
        }
        corpus = [
            CorpusEntry("A1", "법A 1조", "법A 1조", "정답 조문"),
            CorpusEntry("A1-duplicate", "법A 1조", "법A 1조", "정답 조문"),
            # Identical text in another statute must never become a gold alias.
            CorpusEntry("WRONG-LAW", "법X 1조", "법X 1조", "정답 조문"),
            CorpusEntry("B-title", "법B 2조", "법B 2조", "제2조(의무)"),
            CorpusEntry("B-1", "법B 2조", "법B 2조 1항", "① 신고한다."),
            CorpusEntry("B-2", "법B 2조", "법B 2조 2항", "② 위반하면 처벌한다."),
            CorpusEntry(
                "C-1",
                "법C 3조",
                "법C 3조 1항",
                '① 금액은 다음 표와 같다. <img src="x">표내용</img>',
            ),
            CorpusEntry("D-1", "법D 4조", "법D 4조", "끝 문장."),
        ]

        groups = build_gold_groups(questions, list(questions), corpus)

        self.assertEqual(
            groups["q-exact"][0].acceptable_provision_ids, ("A1", "A1-duplicate")
        )
        self.assertEqual(groups["q-exact"][0].match_type, "exact_duplicate")
        self.assertNotIn("WRONG-LAW", groups["q-exact"][0].acceptable_provision_ids)
        self.assertEqual(
            set(groups["q-composite"][0].acceptable_provision_ids),
            {"B-title", "B-1", "B-2"},
        )
        self.assertEqual(groups["q-composite"][0].match_type, "composite")
        self.assertEqual(groups["q-image"][0].acceptable_provision_ids, ("C-1",))
        self.assertEqual(groups["q-image"][0].match_type, "normalized_image_tag")
        self.assertEqual(groups["q-period"][0].acceptable_provision_ids, ("D-1",))
        self.assertEqual(groups["q-period"][0].match_type, "terminal_punctuation")

    def test_unmapped_gold_fails_instead_of_using_fuzzy_content(self):
        questions = {
            "q": {
                "contexts": [
                    {"index": "법A 1조", "hierarchy": "법A 1조", "content": "같은 문구"}
                ]
            }
        }
        corpus = [CorpusEntry("X", "법X 1조", "법X 1조", "같은 문구")]

        with self.assertRaises(EvaluationError):
            build_gold_groups(questions, ["q"], corpus)


class MetricFunctionTests(unittest.TestCase):
    def test_duplicate_predictions_do_not_inflate_gold_true_positives(self):
        groups = [
            GoldGroup("q", "G1", "법A", "법A", "h1", ("P1", "P1-copy"), "exact_duplicate"),
            GoldGroup("q", "G2", "법B", "법B", "h2", ("P2",), "exact_single"),
        ]

        metric = precision_recall_f1({"P1", "P1-copy", "DISTRACTOR"}, groups)

        self.assertEqual(metric["true_positive"], 1)
        self.assertAlmostEqual(metric["precision"], 1 / 3)
        self.assertAlmostEqual(metric["recall"], 1 / 2)
        self.assertFalse(metric["complete"])
        self.assertFalse(metric["provision_em"])

    def test_complete_evidence_and_provision_em_have_different_meanings(self):
        groups = [
            GoldGroup("q", "G1", "법A", "법A", "h1", ("P1",), "exact_single"),
            GoldGroup("q", "G2", "법B", "법B", "h2", ("P2",), "exact_single"),
        ]

        metric = precision_recall_f1({"P1", "P2", "EXTRA"}, groups)

        self.assertTrue(metric["complete"])
        self.assertFalse(metric["provision_em"])

    def test_one_exact_duplicate_alias_is_one_gold_match(self):
        groups = [
            GoldGroup("q", "G1", "법A", "법A", "h1", ("P1", "P1-copy"), "exact_duplicate")
        ]

        metric = precision_recall_f1({"P1-copy"}, groups)

        self.assertEqual(metric["true_positive"], 1)
        self.assertTrue(metric["provision_em"])

    def test_empty_predictions_have_zero_precision_recall_and_f1(self):
        groups = [GoldGroup("q", "G1", "법A", "법A", "h", ("P1",), "exact_single")]

        metric = precision_recall_f1(set(), groups)

        self.assertEqual(metric["precision"], 0.0)
        self.assertEqual(metric["recall"], 0.0)
        self.assertEqual(metric["f1"], 0.0)

    def test_type7_percentile_is_deterministic(self):
        self.assertEqual(percentile_type7([100, 200, 300], 0.95), 290.0)
        self.assertEqual(percentile_type7([42], 0.95), 42.0)


class KoBLEXAnswerMetricTests(unittest.TestCase):
    def test_token_f1_uses_official_normalization_and_exact_match(self):
        self.assertEqual(koblex_normalize("  법률, ABC!  "), "법률 abc")
        self.assertEqual(koblex_token_f1("법률, ABC!", "법률 abc"), 1.0)

    def test_empty_prediction_has_zero_token_f1(self):
        self.assertEqual(koblex_token_f1("", "정답 문구"), 0.0)

    def test_official_token_f1_removes_thinking_and_truncates_to_800_characters(self):
        prediction = "정답" + "x" * 900 + "<\think>숨은 추론"
        self.assertEqual(koblex_official_prediction(prediction), ("정답" + "x" * 798))
        self.assertEqual(koblex_token_f1_at_800("정답<\think>숨은 추론", "정답"), 1.0)

    def test_e2e_zeroes_abstain_and_keeps_answered_only_separate(self):
        scores = LFEvalScores(
            judge_model="frozen-judge",
            judge_revision="r1",
            prompt_sha256="a" * 64,
            scale="0_10",
            raw_scores={"q1": 8.0},
            normalized_scores={"q1": 0.8},
        )
        quality = _aggregate_answer_quality(
            [
                {
                    "status": "ANSWER",
                    "token_f1": 0.8,
                    "answer_mode": "full",
                    "lf_eval_score_normalized": 0.8,
                },
                {
                    "status": "ABSTAIN",
                    "token_f1": 0.0,
                    "answer_mode": None,
                    "lf_eval_score_normalized": None,
                },
            ],
            scores,
        )

        self.assertAlmostEqual(quality["token_f1"]["end_to_end"], 0.4)
        self.assertAlmostEqual(quality["token_f1"]["answered_only"], 0.8)
        self.assertAlmostEqual(quality["lf_eval"]["end_to_end"], 0.4)
        self.assertAlmostEqual(quality["lf_eval"]["answered_only"], 0.8)
        self.assertEqual(quality["answer_modes"]["full"], 1)

    def test_lf_eval_scale_normalization_and_missing_scores_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            score_path = Path(directory) / "lf_eval.json"
            write_json(
                score_path,
                {
                    "judge_model": "frozen-judge",
                    "judge_revision": "r1",
                    "prompt_sha256": "b" * 64,
                    "scale": "0_10",
                    "scores": {"q1": 8.0},
                },
            )
            scores = load_lf_eval_scores(score_path)

        self.assertAlmostEqual(scores.normalized_scores["q1"], 0.8)
        quality = _aggregate_answer_quality(
            [
                {
                    "status": "ANSWER",
                    "token_f1": 0.8,
                    "answer_mode": "full",
                    "lf_eval_score_normalized": 0.8,
                },
                {
                    "status": "ANSWER",
                    "token_f1": 0.5,
                    "answer_mode": "limited",
                    "lf_eval_score_normalized": None,
                },
            ],
            scores,
        )

        self.assertFalse(quality["lf_eval"]["available"])
        self.assertIsNone(quality["lf_eval"]["end_to_end"])
        self.assertIsNone(quality["lf_eval"]["answered_only"])
        self.assertEqual(quality["lf_eval"]["unavailable_reason"], "MISSING_ANSWER_SCORES")


class SplitManifestTests(unittest.TestCase):
    def test_development_held_out_and_all_splits_are_representable(self):
        with tempfile.TemporaryDirectory() as directory:
            split_path = Path(directory) / "splits.json"
            write_json(
                split_path,
                {
                    "splits": {
                        "development": {"question_ids": ["q1"]},
                        "held_out": {"question_ids": ["q2", "q3"]},
                        "all": {"question_ids": ["q1", "q2", "q3"]},
                    }
                },
            )
            splits = load_evaluation_splits(split_path, ["q1", "q2", "q3"])

        self.assertEqual(splits["development"], ("q1",))
        self.assertEqual(splits["held_out"], ("q2", "q3"))
        self.assertEqual(splits["all"], ("q1", "q2", "q3"))


class EvaluationFixture:
    def __init__(self, root, include_stages, include_labels=False):
        self.root = root
        self.batch = root / "records/batches/batch-1"
        self.runs = root / "records/runs"
        self.dataset = root / "qa.json"
        self.corpus = root / "corpus.jsonl"
        self.labels = root / "answer_labels.json" if include_labels else None
        dataset_rows = [
            {
                "id": "q1",
                "question": "질문1",
                "answer": "정답1",
                "background": "",
                "n_hops": 1,
                "contexts": [
                    {"index": "법A 1조", "hierarchy": "법A 1조", "content": "정답 A"}
                ],
            },
            {
                "id": "q2",
                "question": "질문2",
                "answer": "정답2",
                "background": "",
                "n_hops": 2,
                "contexts": [
                    {
                        "index": "법B 2조",
                        "hierarchy": "법B 2조",
                        "content": "제2조\n① 의무\n② 처벌",
                    }
                ],
            },
            {
                "id": "q3",
                "question": "질문3",
                "answer": "정답3",
                "background": "",
                "n_hops": 3,
                "contexts": [
                    {"index": "법C 3조", "hierarchy": "법C 3조", "content": "정답 C"}
                ],
            },
        ]
        write_json(self.dataset, dataset_rows)
        write_jsonl(
            self.corpus,
            [
                {
                    "provision_id": "P1",
                    "source_index": "법A 1조",
                    "statute_name": "법A 1조",
                    "provision_text": "정답 A",
                },
                {
                    "provision_id": "P1-copy",
                    "source_index": "법A 1조",
                    "statute_name": "법A 1조",
                    "provision_text": "정답 A",
                },
                {
                    "provision_id": "P2-title",
                    "source_index": "법B 2조",
                    "statute_name": "법B 2조",
                    "provision_text": "제2조",
                },
                {
                    "provision_id": "P2-duty",
                    "source_index": "법B 2조",
                    "statute_name": "법B 2조 1항",
                    "provision_text": "① 의무",
                },
                {
                    "provision_id": "P2-penalty",
                    "source_index": "법B 2조",
                    "statute_name": "법B 2조 2항",
                    "provision_text": "② 처벌",
                },
                {
                    "provision_id": "P3",
                    "source_index": "법C 3조",
                    "statute_name": "법C 3조",
                    "provision_text": "정답 C",
                },
            ],
        )
        manifest = {
            "manifest_schema_version": "1.0",
            "name": "fixture-batch",
            "source_dataset": {"path": str(self.dataset), "sha256": sha256(self.dataset)},
            "selection": {"entry_count": 3},
            "frozen_configuration": {"condition": "B0", "retriever": "bm25"},
            "entries": [
                {"ordinal": 1, "question_id": "q1", "n_hops": 1},
                {"ordinal": 2, "question_id": "q2", "n_hops": 2},
                {"ordinal": 3, "question_id": "q3", "n_hops": 3},
            ],
        }
        write_json(self.batch / "manifest.json", manifest)
        specs = [
            ("q1", "run-1", "ANSWER", "COMPLETED", "P1", 100.0),
            ("q2", "run-2", "ABSTAIN", "MAX_RETRIEVAL_ROUNDS_REACHED", None, 200.0),
            ("q3", "run-3", "EXECUTION_FAILURE", "INVALID_SKILL_OUTPUT", None, 300.0),
        ]
        summaries = []
        for ordinal, (question_id, run_id, status, reason, accepted, latency) in enumerate(
            specs, start=1
        ):
            run = self.runs / run_id
            candidates = []
            if question_id == "q1":
                candidates = [
                    {"provision_id": "P1"},
                    {"provision_id": "DISTRACTOR"},
                ]
            elif question_id == "q2":
                candidates = [{"provision_id": "P2-duty"}]
            state = {
                "accepted_provision_ids": [accepted] if accepted else [],
                "candidate_provisions": candidates,
                "query_history": [{"request_id": "RQ-%s" % question_id}],
                "retrieval_rounds_used": ordinal,
                "last_validated_event": "D4.CITATION_INTEGRITY_PASS"
                if status == "ANSWER"
                else "S2.ASSESS_COVERAGE",
                "action_trace": [
                    {
                        "event": "INITIAL_RETRIEVAL_VALIDATED",
                        "details": {"candidate_count": len(candidates)},
                    }
                ],
            }
            write_json(
                run / "metadata.json",
                {
                    "record_schema_version": "1.0",
                    "run_id": run_id,
                    "question_id": question_id,
                    "configuration": {"condition": "B0", "retriever": "bm25", "seed": 0},
                },
            )
            write_json(
                run / "result.json",
                {
                    "record_schema_version": "1.0",
                    "run_id": run_id,
                    "status": status,
                    "answer": "정답1" if question_id == "q1" else None,
                    "termination_reason": reason,
                    "abstention_reason": "INSUFFICIENT_CRITICAL_EVIDENCE"
                    if status == "ABSTAIN"
                    else None,
                    "end_to_end_latency_ms": latency,
                    "state": state,
                },
            )
            summaries.append(
                {
                    "ordinal": ordinal,
                    "question_id": question_id,
                    "n_hops": ordinal,
                    "record_directory": str(run),
                    "status": status,
                }
            )
        write_jsonl(self.batch / "summary.jsonl", summaries)
        if include_stages:
            stage_rows = {
                "run-1": [
                    {"stage": "first_stage", "rank": 1, "provision_id": "P1"},
                    {"stage": "fusion", "rank": 1, "provision_id": "P1"},
                    {"stage": "rerank", "rank": 1, "provision_id": "P1"},
                ],
                "run-2": [
                    {"stage": "first_stage", "rank": 100, "provision_id": "P2-duty"},
                    {"stage": "fusion", "rank": 100, "provision_id": "P2-duty"},
                    {"stage": "rerank", "rank": 11, "provision_id": "P2-duty"},
                ],
                "run-3": [
                    {"stage": "first_stage", "rank": 101, "provision_id": "P3"},
                    {"stage": "fusion", "rank": 1, "provision_id": "P3"},
                    {"stage": "rerank", "rank": 31, "provision_id": "P3"},
                ],
            }
            for run_id, rows in stage_rows.items():
                write_jsonl(self.runs / run_id / "retrieval_stages.jsonl", rows)
        if include_labels:
            write_json(self.labels, {"labels": {"q1": {"false_supported": True}}})


class EndToEndEvaluationTests(unittest.TestCase):
    @staticmethod
    def _write_replacement_batch(batch, manifest, summaries):
        write_json(batch / "manifest.json", manifest)
        write_jsonl(batch / "summary.jsonl", summaries)

    def test_legacy_records_keep_stage_metrics_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = EvaluationFixture(Path(directory), include_stages=False)

            aggregate, rows, _ = evaluate_batch(
                fixture.batch,
                fixture.dataset,
                fixture.corpus,
                require_stage_provenance=False,
            )

            self.assertEqual(aggregate["outcomes"]["ANSWER"]["count"], 1)
            self.assertEqual(aggregate["outcomes"]["ABSTAIN"]["count"], 1)
            self.assertEqual(aggregate["outcomes"]["EXECUTION_FAILURE"]["count"], 1)
            self.assertAlmostEqual(aggregate["answers"]["supported_answer_yield"], 1 / 3)
            self.assertIsNone(aggregate["answers"]["false_supported_answer_count"])
            self.assertFalse(aggregate["retrieval"]["first_stage_at_100"]["available"])
            self.assertIsNone(
                aggregate["retrieval"]["first_stage_at_100"]["provision_recall_micro"]
            )
            self.assertIn("STAGE_PROVENANCE_UNAVAILABLE", aggregate["warnings"])
            self.assertTrue(all(not row["stage_provenance_available"] for row in rows))
            self.assertFalse(aggregate["retrieval_loss"]["available"])
            self.assertEqual(
                aggregate["retrieval_loss"]["unavailable_reason"],
                "INCOMPLETE_ROUND_SELECTED_PROVENANCE",
            )
            self.assertEqual(
                [row["retrieval_loss_provenance_available"] for row in rows],
                [False, False, None],
            )
            self.assertAlmostEqual(
                aggregate["answer_quality"]["token_f1"]["end_to_end"], 1 / 3
            )
            self.assertEqual(
                aggregate["answer_quality"]["token_f1"]["answered_only"], 1.0
            )
            self.assertFalse(aggregate["answer_quality"]["lf_eval"]["available"])
            self.assertEqual(
                aggregate["answer_quality"]["unrecorded_answer_mode_count"], 1
            )
            candidate = aggregate["answer_quality"]["candidate_token_f1_at_800"]
            self.assertAlmostEqual(candidate["all_outcomes"], 1 / 3)
            self.assertAlmostEqual(candidate["normal_outcomes"], 1 / 2)
            self.assertEqual(candidate["available_count"], 1)
            self.assertEqual(candidate["missing_count"], 1)

    def test_abstain_candidate_is_scored_separately_from_published_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = EvaluationFixture(Path(directory), include_stages=False)
            result_path = fixture.runs / "run-2/result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result.update(
                {
                    "candidate_answer": "정답2",
                    "candidate_answer_status": "GENERATED",
                    "candidate_answer_basis": "retrieved_candidates",
                    "candidate_answer_termination_reason": None,
                    "candidate_answer_error": None,
                }
            )
            write_json(result_path, result)

            aggregate, rows, _ = evaluate_batch(
                fixture.batch,
                fixture.dataset,
                fixture.corpus,
                require_stage_provenance=False,
            )

            self.assertEqual(rows[1]["status"], "ABSTAIN")
            self.assertIsNone(rows[1]["answer_mode"])
            self.assertEqual(rows[1]["candidate_answer_status"], "GENERATED")
            self.assertEqual(rows[1]["candidate_answer"], "정답2")
            self.assertEqual(rows[1]["candidate_token_f1_at_800"], 1.0)
            self.assertEqual(aggregate["answer_quality"]["token_f1"]["end_to_end"], 1 / 3)
            candidate = aggregate["answer_quality"]["candidate_token_f1_at_800"]
            self.assertAlmostEqual(candidate["all_outcomes"], 2 / 3)
            self.assertEqual(candidate["available_count"], 2)
            self.assertEqual(candidate["abstain_available_count"], 1)
            self.assertEqual(candidate["abstain_available_only"], 1.0)
            self.assertEqual(
                aggregate["answer_quality"]["over_abstention_exact_match_at_800"]["count"],
                1,
            )
            markdown = render_markdown(aggregate, rows)
            self.assertIn("Token-F1@800 E2E", markdown)
            self.assertIn("ABSTAIN candidates only (available only)", markdown)

    def test_candidate_status_and_basis_must_match_public_outcome(self):
        invalid_cases = (
            (
                "run-2",
                {
                    "candidate_answer": "정답2",
                    "candidate_answer_status": "PUBLISHED_ANSWER",
                    "candidate_answer_basis": "published_answer",
                },
                "ABSTAIN must not use a published candidate answer",
            ),
            (
                "run-1",
                {
                    "candidate_answer": "정답1",
                    "candidate_answer_status": "GENERATED",
                    "candidate_answer_basis": "retrieved_candidates",
                },
                "ANSWER must not use an abstain candidate basis",
            ),
        )
        for run_id, update, message in invalid_cases:
            with self.subTest(run_id=run_id), tempfile.TemporaryDirectory() as directory:
                fixture = EvaluationFixture(Path(directory), include_stages=False)
                result_path = fixture.runs / run_id / "result.json"
                result = json.loads(result_path.read_text(encoding="utf-8"))
                result.update(update)
                write_json(result_path, result)

                with self.assertRaisesRegex(EvaluationError, message):
                    evaluate_batch(
                        fixture.batch,
                        fixture.dataset,
                        fixture.corpus,
                        require_stage_provenance=False,
                    )

    def test_answer_modes_lf_eval_and_split_output_are_additive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = EvaluationFixture(root, include_stages=False)
            result_path = fixture.runs / "run-1/result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result.update(
                {
                    "answer_mode": "full",
                    "answered_target_ids": ["T1"],
                    "deferred_target_ids": [],
                }
            )
            write_json(result_path, result)
            lf_eval_path = root / "lf_eval.json"
            split_path = root / "splits.json"
            write_json(
                lf_eval_path,
                {
                    "judge_model": "frozen-judge",
                    "judge_revision": "r1",
                    "prompt_sha256": "c" * 64,
                    "scale": "0_10",
                    "scores": {"q1": 8.0},
                },
            )
            write_json(
                split_path,
                {
                    "splits": {
                        "development": {"question_ids": ["q1"]},
                        "held_out": {"question_ids": ["q2", "q3"]},
                        "all": {"question_ids": ["q1", "q2", "q3"]},
                    }
                },
            )

            aggregate, rows, metadata = evaluate_batch(
                fixture.batch,
                fixture.dataset,
                fixture.corpus,
                require_stage_provenance=False,
                lf_eval_scores_path=lf_eval_path,
                split_manifest_path=split_path,
            )

            self.assertEqual(rows[0]["answer_mode"], "full")
            self.assertEqual(rows[0]["answered_target_ids"], ["T1"])
            self.assertEqual(rows[0]["split_memberships"], ["all", "development"])
            self.assertEqual(aggregate["answer_quality"]["answer_modes"]["full"], 1)
            self.assertAlmostEqual(
                aggregate["answer_quality"]["lf_eval"]["end_to_end"], 0.8 / 3
            )
            self.assertAlmostEqual(
                aggregate["splits"]["development"]["metrics"]["answer_quality"]["token_f1"]["end_to_end"],
                1.0,
            )
            self.assertEqual(metadata["lf_eval"]["input_scale"], "0_10")

    def test_comparison_invalid_status_propagates_to_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = EvaluationFixture(Path(directory), include_stages=False)
            validity = {
                "status": "INVALID_FOR_CLEAN_RETRIEVER_COMPARISON",
                "use": "DIAGNOSTIC_ONLY",
                "reasons": [
                    {"code": "S1_JSON_FAILURES", "affected_runs": 35},
                    {"code": "CODE_PROVENANCE_MISMATCH"},
                ],
            }
            write_json(
                fixture.batch / "metadata.json",
                {"comparison_validity": validity},
            )

            aggregate, rows, metadata = evaluate_batch(
                fixture.batch,
                fixture.dataset,
                fixture.corpus,
                require_stage_provenance=False,
            )

            self.assertEqual(aggregate["comparison_validity"], validity)
            self.assertEqual(metadata["comparison_validity"], validity)
            markdown = render_markdown(aggregate, rows)
            self.assertIn("INVALID_FOR_CLEAN_RETRIEVER_COMPARISON", markdown)
            self.assertIn("S1_JSON_FAILURES", markdown)
            self.assertIn("CODE_PROVENANCE_MISMATCH", markdown)

    def test_stage_boundaries_labels_hops_and_efficiency(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = EvaluationFixture(
                Path(directory), include_stages=True, include_labels=True
            )
            (fixture.runs / "run-3/retrieval_stages.jsonl").unlink()

            aggregate, rows, metadata = evaluate_batch(
                fixture.batch,
                fixture.dataset,
                fixture.corpus,
                answer_labels_path=fixture.labels,
            )

            self.assertAlmostEqual(
                aggregate["retrieval"]["first_stage_at_100"]["provision_recall_micro"],
                1.0,
            )
            self.assertAlmostEqual(
                aggregate["retrieval"]["rrf_at_100"]["complete_evidence_recall"],
                1.0,
            )
            self.assertAlmostEqual(
                aggregate["retrieval"]["bge_at_10"]["provision_recall_micro"],
                1 / 2,
            )
            self.assertAlmostEqual(
                aggregate["retrieval"]["bge_at_20"]["provision_recall_micro"],
                1.0,
            )
            self.assertAlmostEqual(
                aggregate["retrieval"]["bge_at_30"]["provision_recall_micro"],
                1.0,
            )
            self.assertEqual(
                aggregate["retrieval"]["first_stage_at_100"]["question_count"],
                2,
            )
            self.assertIsNone(rows[2]["stage_provenance_available"])
            self.assertEqual(aggregate["answers"]["false_supported_answer_count"], 1)
            self.assertEqual(aggregate["answers"]["false_supported_answer_rate"], 1.0)
            self.assertEqual(aggregate["citation_integrity"]["attempted"], 1)
            self.assertEqual(aggregate["citation_integrity"]["pass_rate"], 1.0)
            self.assertEqual(aggregate["by_hop"]["1"]["outcomes"]["ANSWER"]["count"], 1)
            self.assertEqual(aggregate["by_hop"]["2"]["outcomes"]["ABSTAIN"]["count"], 1)
            self.assertEqual(
                aggregate["by_hop"]["3"]["outcomes"]["EXECUTION_FAILURE"]["count"],
                1,
            )
            self.assertEqual(
                aggregate["efficiency"]["end_to_end_latency_ms"]["median"], 200.0
            )
            self.assertEqual(
                aggregate["efficiency"]["end_to_end_latency_ms"]["p95"], 290.0
            )
            self.assertEqual(metadata["validation"]["joined_results"], 3)
            self.assertEqual([row["ordinal"] for row in rows], [1, 2, 3])

    def test_writes_json_csv_markdown_and_metadata_in_ordinal_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = EvaluationFixture(root, include_stages=False)
            aggregate, rows, metadata = evaluate_batch(
                fixture.batch,
                fixture.dataset,
                fixture.corpus,
                require_stage_provenance=False,
            )
            output = root / "evaluation"

            write_outputs(output, aggregate, list(reversed(rows)), metadata)

            self.assertTrue((output / "aggregate.json").is_file())
            self.assertTrue((output / "per_question.csv").is_file())
            self.assertTrue((output / "summary.md").is_file())
            self.assertTrue((output / "metadata.json").is_file())
            with (output / "per_question.csv").open(encoding="utf-8") as handle:
                csv_rows = list(csv.DictReader(handle))
            self.assertEqual([row["question_id"] for row in csv_rows], ["q1", "q2", "q3"])
            self.assertEqual(csv_rows[0]["first_stage_recall_at_100"], "")
            self.assertIn("Retrieval stages", (output / "summary.md").read_text(encoding="utf-8"))
            with self.assertRaises(FileExistsError):
                write_outputs(output, aggregate, rows, metadata)

    def test_subset_replacement_replaces_failure_and_uses_retry_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = EvaluationFixture(root, include_stages=False)
            retry_batch = root / "records/batches/retry-q3"
            retry_run = root / "records/retry-runs/retry-q3"
            manifest = json.loads(
                (fixture.batch / "manifest.json").read_text(encoding="utf-8")
            )
            self._write_replacement_batch(
                retry_batch,
                manifest,
                [
                    {
                        "ordinal": 3,
                        "question_id": "q3",
                        "n_hops": 3,
                        "record_directory": str(retry_run),
                        "status": "ANSWER",
                    }
                ],
            )
            state = {
                "accepted_provision_ids": ["P3"],
                "candidate_provisions": [{"provision_id": "P3"}],
                "query_history": [{"request_id": "RQ-q3-retry"}],
                "retrieval_rounds_used": 1,
                "last_validated_event": "D4.CITATION_INTEGRITY_PASS",
                "action_trace": [],
            }
            write_json(
                retry_run / "metadata.json",
                {
                    "record_schema_version": "1.0",
                    "run_id": "retry-q3",
                    "question_id": "q3",
                    "configuration": {
                        "condition": "B0-retry",
                        "retriever": "bm25",
                        "seed": 0,
                    },
                },
            )
            write_json(
                retry_run / "result.json",
                {
                    "record_schema_version": "1.0",
                    "run_id": "retry-q3",
                    "status": "ANSWER",
                    "answer": "정답3",
                    "termination_reason": "COMPLETED",
                    "abstention_reason": None,
                    "end_to_end_latency_ms": 111.0,
                    "state": state,
                },
            )

            aggregate, rows, metadata = evaluate_batch(
                fixture.batch,
                fixture.dataset,
                fixture.corpus,
                require_stage_provenance=False,
                replacement_batch_directories=[retry_batch],
            )

            retry_row = next(row for row in rows if row["question_id"] == "q3")
            self.assertEqual(retry_row["status"], "ANSWER")
            self.assertEqual(retry_row["record_directory"], str(retry_run.resolve()))
            self.assertEqual(aggregate["outcomes"]["EXECUTION_FAILURE"]["count"], 0)
            self.assertEqual(aggregate["replacements"]["question_ids"], ["q3"])
            self.assertEqual(
                metadata["inputs"]["replacements"]["source_record_directories"]["q3"],
                str(retry_run.resolve()),
            )

    def test_unknown_or_duplicate_replacement_rows_fail_closed(self):
        cases = (
            (
                [{"question_id": "not-in-primary", "status": "ANSWER"}],
                "replacement summary references non-primary question",
            ),
            (
                [
                    {"question_id": "q3", "status": "ANSWER"},
                    {"question_id": "q3", "status": "ANSWER"},
                ],
                "duplicate replacement summary row: q3",
            ),
        )
        for summaries, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fixture = EvaluationFixture(root, include_stages=False)
                manifest = json.loads(
                    (fixture.batch / "manifest.json").read_text(encoding="utf-8")
                )
                retry_batch = root / "records/batches/retry-invalid"
                self._write_replacement_batch(retry_batch, manifest, summaries)

                with self.assertRaisesRegex(EvaluationError, message):
                    evaluate_batch(
                        fixture.batch,
                        fixture.dataset,
                        fixture.corpus,
                        replacement_batch_directories=[retry_batch],
                    )

    def test_missing_manifest_result_is_an_input_error_not_an_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = EvaluationFixture(Path(directory), include_stages=False)
            summaries = [
                row
                for row in json.loads("[" + ",".join(
                    line for line in (fixture.batch / "summary.jsonl").read_text().splitlines()
                ) + "]")
                if row["question_id"] != "q3"
            ]
            write_jsonl(fixture.batch / "summary.jsonl", summaries)

            with self.assertRaises(EvaluationError):
                evaluate_batch(fixture.batch, fixture.dataset, fixture.corpus)


class RunDirectoryResolutionTests(unittest.TestCase):
    def test_rebases_legacy_absolute_path_with_nested_run_root(self):
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            expected = (
                project_root
                / "records/runs/kure-c5-full226-20260822-a74e76d"
                / "run-uuid"
            )
            expected.mkdir(parents=True)
            legacy_path = Path(
                "/root/Legal Harness/records/runs/"
                "kure-c5-full226-20260822-a74e76d/run-uuid"
            )

            with patch.object(evaluate_dev_runs, "PROJECT_ROOT", project_root):
                resolved = evaluate_dev_runs._resolve_run_directory(
                    project_root / "records/batches/c5",
                    {"question_id": "q1", "record_directory": str(legacy_path)},
                )

            self.assertEqual(resolved, expected.resolve())

    def test_rebase_rejects_path_traversal_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            project_root = Path(directory)
            (project_root / "records/outside").mkdir(parents=True)
            legacy_path = "/old/records/runs/group/../outside"

            with patch.object(evaluate_dev_runs, "PROJECT_ROOT", project_root):
                with self.assertRaises(EvaluationError):
                    evaluate_dev_runs._resolve_run_directory(
                        project_root / "records/batches/c5",
                        {"question_id": "q1", "record_directory": legacy_path},
                    )


class RetrievalLossFunnelTests(unittest.TestCase):
    @staticmethod
    def _add_round_selected_sidecars(fixture):
        by_run = {
            "run-1": (
                [
                    {"provision_id": "P1", "retrieval_round": 1},
                    {"provision_id": "DISTRACTOR", "retrieval_round": 1},
                ],
                [
                    {"provision_id": "P1", "retrieval_round": 1},
                    {"provision_id": "DISTRACTOR", "retrieval_round": 1},
                ],
            ),
            "run-2": (
                [
                    {"provision_id": "DISTRACTOR-2", "retrieval_round": 1},
                    {"provision_id": "P2-duty", "retrieval_round": 2},
                ],
                [
                    {"provision_id": "DISTRACTOR-2", "retrieval_round": 1},
                    {"provision_id": "P2-duty", "retrieval_round": 2},
                ],
            ),
        }
        for run_id, (candidates, selected) in by_run.items():
            result_path = fixture.runs / run_id / "result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["state"]["candidate_provisions"] = candidates
            write_json(result_path, result)

            stage_path = fixture.runs / run_id / "retrieval_stages.jsonl"
            stages = [
                json.loads(line)
                for line in stage_path.read_text(encoding="utf-8").splitlines()
            ]
            stages.extend(
                {
                    "candidate_stage": "round_selected",
                    "provision_id": row["provision_id"],
                    "retrieval_round": row["retrieval_round"],
                    "selection_rank": selection_rank,
                }
                for selection_rank, row in enumerate(selected, start=1)
            )
            write_jsonl(stage_path, stages)

    def test_round_selected_funnel_aggregates_and_flattens_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = EvaluationFixture(root, include_stages=True)
            self._add_round_selected_sidecars(fixture)

            aggregate, rows, metadata = evaluate_batch(
                fixture.batch,
                fixture.dataset,
                fixture.corpus,
            )
            by_question = {row["question_id"]: row for row in rows}
            loss = aggregate["retrieval_loss"]

            self.assertEqual(metadata["evaluation_schema_version"], "1.5")
            self.assertTrue(by_question["q1"]["stage_provenance_available"])
            self.assertTrue(by_question["q1"]["retrieval_loss_provenance_available"])
            self.assertEqual(
                by_question["q2"]["first_round_selected_complete_round"],
                2,
            )
            self.assertEqual(by_question["q2"]["first_candidate_complete_round"], 2)
            self.assertTrue(
                by_question["q2"]["round_selected_final_metrics"]["complete"]
            )
            self.assertFalse(by_question["q2"]["accepted_metrics"]["complete"])
            self.assertTrue(
                by_question["q1"]["round_selected_matches_final_candidate"]
            )
            self.assertTrue(loss["available"])
            self.assertEqual(loss["normal_outcome_questions"], 2)
            self.assertEqual(loss["available_questions"], 2)
            self.assertEqual(
                loss["round_selected_cumulative"]["1"]["complete_evidence"]["count"],
                1,
            )
            self.assertEqual(
                loss["round_selected_cumulative"]["2"]["complete_evidence"]["count"],
                2,
            )
            self.assertEqual(loss["final_candidate"]["complete_evidence"]["count"], 2)
            self.assertEqual(loss["accepted"]["complete_evidence"]["count"], 1)
            self.assertEqual(
                loss["round_selected_matches_final_candidate"]["match_count"],
                2,
            )

            output = root / "evaluation"
            write_outputs(output, aggregate, rows, metadata)
            with (output / "per_question.csv").open(encoding="utf-8") as handle:
                csv_rows = {row["question_id"]: row for row in csv.DictReader(handle)}
            self.assertEqual(csv_rows["q1"]["round_selected_final_recall"], "1.0")
            self.assertEqual(
                csv_rows["q1"]["round_selected_final_complete_evidence"],
                "True",
            )
            self.assertEqual(csv_rows["q2"]["first_candidate_complete_round"], "2")
            self.assertEqual(
                csv_rows["q2"]["round_selected_matches_final_candidate"],
                "True",
            )
            self.assertNotIn("round_selected_cumulative_metrics", csv_rows["q1"])

    def test_round_selected_candidate_mismatch_is_reported_not_rewritten(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = EvaluationFixture(Path(directory), include_stages=True)
            self._add_round_selected_sidecars(fixture)
            result_path = fixture.runs / "run-1/result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["state"]["candidate_provisions"] = [
                {"provision_id": "P1", "retrieval_round": 1}
            ]
            write_json(result_path, result)

            aggregate, rows, _ = evaluate_batch(
                fixture.batch,
                fixture.dataset,
                fixture.corpus,
            )

            row = next(row for row in rows if row["question_id"] == "q1")
            self.assertFalse(row["round_selected_matches_final_candidate"])
            self.assertIn(
                "ROUND_SELECTED_FINAL_CANDIDATE_MISMATCH",
                aggregate["warnings"],
            )
            self.assertEqual(
                aggregate["retrieval_loss"]["round_selected_matches_final_candidate"],
                {"match_count": 1, "mismatch_count": 1},
            )


class EvidenceRoleEvaluationTests(unittest.TestCase):
    @staticmethod
    def _evaluate(fixture):
        return evaluate_batch(
            fixture.batch,
            fixture.dataset,
            fixture.corpus,
            require_stage_provenance=False,
        )

    def test_legacy_accepted_evidence_falls_back_to_core_without_metric_change(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = EvaluationFixture(Path(directory), include_stages=False)

            aggregate, rows, metadata = self._evaluate(fixture)

            q1 = next(row for row in rows if row["question_id"] == "q1")
            self.assertFalse(q1["evidence_role_schema_available"])
            self.assertEqual(
                q1["provision_score_source"], "legacy_accepted_provision_ids"
            )
            self.assertEqual(q1["accepted_count"], 1)
            self.assertEqual(q1["core_accepted_count"], 1)
            self.assertEqual(q1["authorized_provision_count"], 1)
            self.assertEqual(q1["auxiliary_provision_count"], 0)
            self.assertEqual(q1["auxiliary_citation_count"], 0)
            self.assertEqual(aggregate["provision"]["micro"]["predicted"], 1)
            self.assertEqual(aggregate["provision"]["micro"]["true_positive"], 1)
            self.assertEqual(
                aggregate["evidence_roles"]["legacy_fallback_question_count"], 3
            )
            self.assertEqual(
                aggregate["evidence_roles"]["core"]["per_question_unique_total"],
                1,
            )
            self.assertIn(
                "neither derives roles from KoBLEX gold",
                metadata["evidence_roles"]["role_decision_boundary"],
            )

    def test_core_only_scoring_preserves_auxiliary_evidence_and_citations(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = EvaluationFixture(Path(directory), include_stages=False)
            result_path = fixture.runs / "run-1/result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            state = result["state"]
            state["accepted_provision_ids"] = ["P1", "DISTRACTOR"]
            state["core_accepted_provision_ids"] = ["P1"]
            state["supplemental_provision_ids"] = ["DISTRACTOR"]
            state["qualifying_provision_ids"] = ["P1"]
            state["alternative_provision_ids"] = ["DISTRACTOR"]
            result["claim_citations"] = [
                {
                    "claim_id": "C1",
                    "provision_id": "DISTRACTOR",
                    "evidence_role": "supplemental",
                }
            ]
            write_json(result_path, result)

            aggregate, rows, _ = self._evaluate(fixture)

            q1 = next(row for row in rows if row["question_id"] == "q1")
            self.assertTrue(q1["evidence_role_schema_available"])
            self.assertEqual(
                q1["provision_score_source"], "core_accepted_provision_ids"
            )
            self.assertEqual(q1["accepted_count"], 1)
            self.assertEqual(q1["authorized_provision_count"], 2)
            self.assertEqual(q1["core_accepted_count"], 1)
            self.assertEqual(q1["supplemental_provision_count"], 1)
            self.assertEqual(q1["qualifying_provision_count"], 1)
            self.assertEqual(q1["alternative_provision_count"], 1)
            self.assertEqual(q1["auxiliary_provision_count"], 2)
            self.assertEqual(q1["auxiliary_citation_count"], 1)
            self.assertEqual(q1["provision_precision"], 1.0)
            self.assertEqual(
                aggregate["evidence_roles"]["role_schema_available_question_count"],
                1,
            )
            self.assertEqual(
                aggregate["evidence_roles"]["authorized_union"][
                    "per_question_unique_total"
                ],
                2,
            )
            self.assertEqual(
                aggregate["evidence_roles"]["auxiliary_citations"]["count"], 1
            )
            output = fixture.root / "evaluation"
            write_outputs(output, aggregate, rows, {"fixture": "evidence-roles"})
            with (output / "per_question.csv").open(encoding="utf-8") as handle:
                csv_rows = {row["question_id"]: row for row in csv.DictReader(handle)}
            self.assertEqual(csv_rows["q1"]["authorized_provision_count"], "2")
            self.assertEqual(csv_rows["q1"]["core_accepted_count"], "1")
            self.assertEqual(csv_rows["q1"]["auxiliary_citation_count"], "1")
            self.assertIn(
                "## Evidence roles",
                (output / "summary.md").read_text(encoding="utf-8"),
            )

    def test_role_ids_must_be_candidates_and_authorized(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = EvaluationFixture(Path(directory), include_stages=False)
            result_path = fixture.runs / "run-1/result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            state = result["state"]
            state["candidate_provisions"] = [{"provision_id": "P1"}]
            state["accepted_provision_ids"] = ["P1", "OUTSIDE"]
            write_json(result_path, result)

            with self.assertRaisesRegex(
                EvaluationError, "authorized provision is absent from candidates"
            ):
                self._evaluate(fixture)

        with tempfile.TemporaryDirectory() as directory:
            fixture = EvaluationFixture(Path(directory), include_stages=False)
            result_path = fixture.runs / "run-1/result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            state = result["state"]
            state["core_accepted_provision_ids"] = ["P1"]
            state["supplemental_provision_ids"] = ["NOT-A-CANDIDATE"]
            state["qualifying_provision_ids"] = []
            state["alternative_provision_ids"] = []
            write_json(result_path, result)

            with self.assertRaisesRegex(
                EvaluationError, "supplemental provision is absent from candidates"
            ):
                self._evaluate(fixture)

        with tempfile.TemporaryDirectory() as directory:
            fixture = EvaluationFixture(Path(directory), include_stages=False)
            result_path = fixture.runs / "run-1/result.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            state = result["state"]
            state["core_accepted_provision_ids"] = ["P1"]
            state["supplemental_provision_ids"] = ["DISTRACTOR"]
            state["qualifying_provision_ids"] = []
            state["alternative_provision_ids"] = []
            write_json(result_path, result)

            with self.assertRaisesRegex(
                EvaluationError,
                "supplemental provision is absent from authorized union",
            ):
                self._evaluate(fixture)


class ImmutableC5ProvenanceTests(unittest.TestCase):
    def test_normal_c5_round_selected_union_matches_final_candidates(self):
        project_root = Path(__file__).resolve().parents[1]
        batch = (
            project_root
            / "records/batches/kure-c5-full226-20260822-a74e76d"
            / "combined-checkpoint-226"
        )
        summary_path = batch / "summary.jsonl"
        if not summary_path.is_file():
            self.skipTest("immutable C5 checkpoint is not present")

        runs_root = project_root / "records/runs/kure-c5-full226-20260822-a74e76d"
        normal_count = 0
        matching_count = 0
        for line in summary_path.read_text(encoding="utf-8").splitlines():
            summary = json.loads(line)
            if summary.get("status") not in {"ANSWER", "ABSTAIN"}:
                continue
            run_id = Path(str(summary["record_directory"])).name
            run_directory = runs_root / run_id
            result = json.loads(
                (run_directory / "result.json").read_text(encoding="utf-8")
            )
            selected_by_round, warnings = load_round_selected_sets(run_directory)
            self.assertEqual(warnings, [], summary["question_id"])
            self.assertIsNotNone(selected_by_round, summary["question_id"])
            selected = set().union(*selected_by_round.values())
            candidates = result["state"]["candidate_provisions"]
            candidate_ids = {
                candidate["provision_id"]
                for candidate in candidates
                if candidate.get("provision_id")
            }
            self.assertEqual(selected, candidate_ids, summary["question_id"])
            normal_count += 1
            matching_count += 1

        self.assertEqual(normal_count, 222)
        self.assertEqual(matching_count, 222)


class OfflineEvaluatorCliTests(unittest.TestCase):
    def test_cli_without_lf_eval_remains_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = EvaluationFixture(root, include_stages=False)
            output = root / "evaluation"
            argv = [
                "evaluate_dev_runs.py",
                "--batch-dir",
                str(fixture.batch),
                "--dataset",
                str(fixture.dataset),
                "--corpus",
                str(fixture.corpus),
                "--allow-missing-stage-provenance",
                "--output-dir",
                str(output),
            ]

            with patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                self.assertEqual(evaluate_main(), 0)

            aggregate = json.loads(
                (output / "aggregate.json").read_text(encoding="utf-8")
            )
            metadata = json.loads(
                (output / "metadata.json").read_text(encoding="utf-8")
            )
            self.assertFalse(aggregate["answer_quality"]["lf_eval"]["available"])
            self.assertEqual(
                aggregate["answer_quality"]["lf_eval"]["unavailable_reason"],
                "LF_EVAL_NOT_PROVIDED",
            )
            self.assertIsNone(metadata["inputs"]["lf_eval_scores"])


if __name__ == "__main__":
    unittest.main()
