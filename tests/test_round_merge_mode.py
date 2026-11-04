import json
import unittest
from pathlib import Path

from harness.contracts import QueryChannel, RetrievalRequest
from retrieval.corpus import ProvisionDocument
from retrieval.pipeline import RetrievalPipeline
from retrieval.types import RetrievalHit
from runtime.comparison_guard import validate_retriever_comparison
from runtime.source_snapshot import SourceSnapshot
from scripts.analyze_round_merge_ablation import (
    DEFAULT_BATCH_DIR,
    DEFAULT_CORPUS,
    DEFAULT_DATASET,
    DEFAULT_PAIRED_CSV,
    analyze,
)
from scripts.run_bm25_bge_pilot_batch import build_run_command
from scripts.run_local_harness import build_frozen_run_args


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ScriptedFirstStage:
    def __init__(self, documents, rankings):
        self.documents = {document.provision_id: document for document in documents}
        self.rankings = rankings

    def search(self, request):
        provision_ids = self.rankings[request.request_id]
        return [
            RetrievalHit(
                self.documents[provision_id],
                float(len(provision_ids) - rank),
                request.request_id,
            )
            for rank, provision_id in enumerate(provision_ids)
        ]


class QueryScores:
    def __init__(self, scores):
        self.scores = scores

    def rerank(self, query_text, hits, top_k):
        return [self.scores[query_text][hit.document.provision_id] for hit in hits[:top_k]]


class RoundMergeModeTests(unittest.TestCase):
    def _requests(self):
        return [
            RetrievalRequest("RQ1", "I1", "E1", QueryChannel.SPARSE_KEYWORD, "q1"),
            RetrievalRequest("RQ2", "I2", "E2", QueryChannel.STATUTE_AWARE, "q2"),
        ]

    def _pipeline(self, mode="raw_score", selection="global_top_k"):
        documents = [
            ProvisionDocument("P1", "법1", "첫 번째"),
            ProvisionDocument("P2", "법1", "두 번째"),
            ProvisionDocument("P3", "법2", "세 번째"),
        ]
        return RetrievalPipeline(
            ScriptedFirstStage(
                documents,
                {"RQ1": ["P1", "P2"], "RQ2": ["P3"]},
            ),
            QueryScores({"q1": {"P1": 10.0, "P2": 9.0}, "q2": {"P3": 1.0}}),
            final_top_k=2,
            rerank_query_mode="per_request",
            candidate_selection=selection,
            candidate_budget_scope="per_round",
            round_merge_mode=mode,
        )

    def test_default_and_explicit_raw_score_are_selection_equivalent(self):
        default_pipeline = self._pipeline()
        explicit_pipeline = self._pipeline("raw_score")

        default = default_pipeline.retrieve(self._requests(), retrieval_round=1)
        explicit = explicit_pipeline.retrieve(self._requests(), retrieval_round=1)

        self.assertEqual(default, explicit)
        self.assertEqual(
            default_pipeline.last_stage_records,
            explicit_pipeline.last_stage_records,
        )
        self.assertEqual([candidate.provision_id for candidate in default], ["P1", "P2"])

    def test_guarded_swap_uses_request_local_rank_one_and_records_provenance(self):
        pipeline = self._pipeline("request_rank_top1_guarded_swap")

        candidates = pipeline.retrieve(self._requests(), retrieval_round=1)

        self.assertEqual([candidate.provision_id for candidate in candidates], ["P1", "P3"])
        self.assertEqual(
            candidates[-1].selection_reason,
            "round_request_rank_top1_guarded_swap:request_id=RQ2;rerank_rank=1",
        )
        selected_records = [
            record
            for record in pipeline.last_stage_records
            if record.candidate_stage == "round_selected"
        ]
        self.assertEqual(selected_records[-1].selection_reason, candidates[-1].selection_reason)

    def test_guarded_mode_requires_per_round_candidate_budgeting(self):
        with self.assertRaisesRegex(ValueError, "requires per_round"):
            RetrievalPipeline(
                ScriptedFirstStage([], {}),
                QueryScores({}),
                rerank_query_mode="per_request",
                candidate_budget_scope="per_issue",
                round_merge_mode="request_rank_top1_guarded_swap",
            )

    def test_guard_does_not_reintroduce_a_prior_round_alias(self):
        documents = [
            ProvisionDocument("P1", "공통법", "동일 본문"),
            ProvisionDocument("P2", "공통법", "동일 본문"),
            ProvisionDocument("P3", "별도법", "첫 번째"),
            ProvisionDocument("P4", "별도법", "두 번째"),
            ProvisionDocument("P5", "별도법", "세 번째"),
        ]
        pipeline = RetrievalPipeline(
            ScriptedFirstStage(
                documents,
                {
                    "RQ1": ["P1"],
                    "RQ2": ["P2", "P3"],
                    "RQ3": ["P2"],
                    "RQ4": ["P4", "P5"],
                },
            ),
            QueryScores(
                {
                    "q1": {"P1": 10.0},
                    "q2": {"P2": 9.0, "P3": 8.0},
                    "q3": {"P2": 10.0},
                    "q4": {"P4": 100.0, "P5": 99.0},
                }
            ),
            final_top_k=2,
            rerank_query_mode="per_request",
            candidate_budget_scope="per_round",
            dedup_mode="legal_text_alias",
            round_merge_mode="request_rank_top1_guarded_swap",
        )
        first_round = [
            RetrievalRequest("RQ1", "I1", "E1", QueryChannel.SPARSE_KEYWORD, "q1"),
            RetrievalRequest("RQ2", "I2", "E2", QueryChannel.STATUTE_AWARE, "q2"),
        ]
        second_round = [
            RetrievalRequest("RQ3", "I2", "E2", QueryChannel.SPARSE_KEYWORD, "q3"),
            RetrievalRequest("RQ4", "I3", "E3", QueryChannel.STATUTE_AWARE, "q4"),
        ]

        first = pipeline.retrieve(first_round, retrieval_round=1)

        self.assertEqual([candidate.provision_id for candidate in first], ["P1", "P3"])
        self.assertEqual(
            pipeline._prior_round_selected_provision_ids,
            {"P1", "P2", "P3"},
        )

        second = pipeline.retrieve(second_round, retrieval_round=2)
        self.assertEqual([candidate.provision_id for candidate in second], ["P4", "P5"])
        self.assertNotIn("guarded_swap", second[-1].selection_reason)

    def test_guard_requires_rank_one_and_is_deterministic(self):
        documents = [
            ProvisionDocument("P1", "법1", "첫 번째"),
            ProvisionDocument("P2", "법2", "두 번째"),
            ProvisionDocument("P3", "법3", "세 번째"),
        ]
        pipeline = RetrievalPipeline(
            ScriptedFirstStage(
                documents,
                {"RQ1": ["P1"], "RQ2": ["P2", "P3"]},
            ),
            QueryScores({"q1": {"P1": 10.0}, "q2": {"P2": 9.0, "P3": 8.0}}),
            final_top_k=2,
            rerank_query_mode="per_request",
            candidate_budget_scope="per_round",
            round_merge_mode="request_rank_top1_guarded_swap",
        )

        first = pipeline.retrieve(self._requests(), retrieval_round=1)
        first_records = tuple(pipeline.last_stage_records)
        second = pipeline.retrieve(self._requests(), retrieval_round=1)

        self.assertEqual([candidate.provision_id for candidate in first], ["P1", "P2"])
        self.assertEqual(first, second)
        self.assertEqual(first_records, tuple(pipeline.last_stage_records))
        self.assertNotIn("guarded_swap", first[-1].selection_reason)

    def test_guard_does_not_evict_a_critical_quota_slot(self):
        pipeline = self._pipeline(
            "request_rank_top1_guarded_swap",
            selection="evidence_balanced",
        )

        candidates = pipeline.retrieve(
            self._requests(),
            retrieval_round=1,
            critical_evidence_item_ids=["E1", "E2"],
        )

        self.assertEqual([candidate.provision_id for candidate in candidates], ["P1", "P3"])
        self.assertEqual(
            [candidate.selection_reason for candidate in candidates],
            ["critical_quota:E1", "critical_quota:E2"],
        )

    def test_cross_issue_alias_merge_unions_request_local_rank_provenance(self):
        documents = [
            ProvisionDocument("P1", "공통법", "동일 본문"),
            ProvisionDocument("P2", "공통법", "동일 본문"),
            ProvisionDocument("P3", "별도법", "별도 본문"),
        ]
        pipeline = RetrievalPipeline(
            ScriptedFirstStage(
                documents,
                {"RQ1": ["P1", "P3"], "RQ2": ["P2"]},
            ),
            QueryScores({"q1": {"P1": 10.0, "P3": 9.0}, "q2": {"P2": 1.0}}),
            final_top_k=2,
            rerank_query_mode="per_request",
            candidate_budget_scope="per_round",
            dedup_mode="legal_text_alias",
            round_merge_mode="request_rank_top1_guarded_swap",
        )
        requests = [
            RetrievalRequest("RQ1", "I1", "E1", QueryChannel.SPARSE_KEYWORD, "q1"),
            RetrievalRequest("RQ2", "I2", "E2", QueryChannel.STATUTE_AWARE, "q2"),
        ]

        candidates = pipeline.retrieve(requests, retrieval_round=1)

        self.assertEqual([candidate.provision_id for candidate in candidates], ["P1", "P3"])
        self.assertEqual(
            pipeline._request_rerank_ranks_by_candidate[("I1", "P1")],
            {"RQ1": 1, "RQ2": 1},
        )

    def test_frozen_config_and_subprocess_command_propagate_mode(self):
        configuration = {
            "condition": "C5-test",
            "retriever": "kure",
            "model": "legal-harness-qwen38-q8",
            "seed": 0,
            "num_ctx": 32768,
            "total_retrieval_rounds": 3,
            "total_retrieval_requests": 9,
            "round_merge_mode": "request_rank_top1_guarded_swap",
        }
        frozen = build_frozen_run_args(
            "question",
            "qa_test",
            configuration,
            PROJECT_ROOT / "records/runs/test",
            "commit",
            "manifest",
        )
        snapshot = SourceSnapshot("commit", "tree", "manifest")
        command = build_run_command(
            Path("/python"),
            "question",
            "qa_test",
            configuration,
            PROJECT_ROOT / "records/runs/test",
            snapshot,
        )

        self.assertEqual(frozen.round_merge_mode, "request_rank_top1_guarded_swap")
        mode_index = command.index("--round-merge-mode")
        self.assertTrue(all(isinstance(argument, str) for argument in command))
        self.assertEqual(command[mode_index + 1], "request_rank_top1_guarded_swap")
        legacy = build_frozen_run_args(
            "question",
            "qa_test",
            {key: value for key, value in configuration.items() if key != "round_merge_mode"},
            PROJECT_ROOT / "records/runs/test",
            "commit",
            "manifest",
        )
        self.assertEqual(legacy.round_merge_mode, "raw_score")

    def test_experimental_smoke_manifests_are_paired_for_validation(self):
        directory = PROJECT_ROOT / "records/launch/kure-c5-conclusion-first-qwen38-q8-20260822"
        primary = json_load(directory / "kure_c5_round_merge_guarded_smoke8_20260824.json")
        reference = json_load(
            directory / "bm25_reference_c5_round_merge_guarded_smoke8_20260824.json"
        )

        validation = validate_retriever_comparison(
            primary,
            reference,
            directory / "kure_c5_round_merge_guarded_smoke8_20260824.json",
            directory / "bm25_reference_c5_round_merge_guarded_smoke8_20260824.json",
        )

        self.assertEqual(validation["status"], "VALIDATED_IDENTICAL_EXCEPT_RETRIEVER")


class FixedInputRoundMergeAblationTests(unittest.TestCase):
    @unittest.skipUnless(
        DEFAULT_BATCH_DIR.is_dir() and DEFAULT_DATASET.is_file() and DEFAULT_CORPUS.is_file(),
        "requires immutable C5 trace, dataset, and corpus fixtures",
    )
    def test_c5_trace_parity_and_guarded_swap_core_values(self):
        summary = analyze(
            DEFAULT_BATCH_DIR,
            DEFAULT_DATASET,
            DEFAULT_CORPUS,
            DEFAULT_PAIRED_CSV,
            10,
        )

        self.assertTrue(summary["documented_c5_expected_matches"])
        self.assertEqual(summary["schema_version"], "1.1")
        self.assertEqual(
            summary["trace_fidelity"][
                "round_selected_matches_final_candidate_count"
            ],
            222,
        )
        self.assertEqual(
            summary["trace_fidelity"]["raw_score_exact_question_count"],
            222,
        )
        observed = summary["observed_c5"]
        self.assertEqual(observed["actual_complete"], 137)
        self.assertEqual(observed["guarded_complete"], 142)
        self.assertEqual(observed["guarded_gains"], 5)
        self.assertEqual(observed["guarded_losses"], 0)
        self.assertEqual(summary["paired_regression"]["count"], 29)
        self.assertEqual(summary["round_merge_loss"]["count"], 15)


def json_load(path):
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
