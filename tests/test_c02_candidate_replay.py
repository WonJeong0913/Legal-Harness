import json
import tempfile
import unittest
from pathlib import Path

from scripts import evaluate_dev_runs as evaluator
from scripts import replay_c02_candidate_hypotheses as replay


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def write_jsonl(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(value, ensure_ascii=False) for value in values) + "\n",
        encoding="utf-8",
    )


class C02CandidateReplayTests(unittest.TestCase):
    def _result(self, status, candidates):
        return {
            "status": status,
            "state": {
                "query_history": [
                    {"request_id": "RQ1", "evidence_item_id": "E1"},
                    {"request_id": "RQ2", "evidence_item_id": "E2"},
                ],
                "required_evidence_items": [
                    {"evidence_item_id": "E1", "critical": True},
                    {"evidence_item_id": "E2", "critical": True},
                ],
                "candidate_provisions": [
                    {"provision_id": candidate} for candidate in candidates
                ],
            },
        }

    @staticmethod
    def _record(stage, provision_id, **extra):
        return {
            "candidate_stage": stage,
            "provision_id": provision_id,
            "retrieval_round": 1,
            "source_request_ids": extra.pop("source_request_ids", ["RQ1"]),
            "target_evidence_item_ids": extra.pop("target_evidence_item_ids", ["E1"]),
            "alias_provision_ids": extra.pop("alias_provision_ids", [provision_id]),
            "first_stage_rank": extra.pop("first_stage_rank", None),
            "first_stage_score": extra.pop("first_stage_score", None),
            "rerank_rank": extra.pop("rerank_rank", None),
            "rerank_score": extra.pop("rerank_score", None),
            "fusion_rank": extra.pop("fusion_rank", None),
            "selection_rank": extra.pop("selection_rank", None),
            "selection_reason": extra.pop("selection_reason", "request_top_k"),
            **extra,
        }

    def _stage_records(self):
        records = [
            self._record("first_stage", "P1-alias", alias_provision_ids=["P1", "P1-alias"], first_stage_rank=1, first_stage_score=0.9),
            self._record("first_stage", "P2", source_request_ids=["RQ2"], target_evidence_item_ids=["E2"], first_stage_rank=1, first_stage_score=0.8),
            self._record("first_stage", "P3", source_request_ids=["RQ1"], first_stage_rank=2, first_stage_score=0.7),
            self._record("request_rerank", "P1-alias", alias_provision_ids=["P1", "P1-alias"], rerank_rank=1, rerank_score=0.9),
            self._record("request_rerank", "P2", source_request_ids=["RQ2"], target_evidence_item_ids=["E2"], rerank_rank=1, rerank_score=0.8),
            self._record("request_rerank", "P3", rerank_rank=2, rerank_score=0.7),
            self._record("selected", "P1-alias", alias_provision_ids=["P1", "P1-alias"], rerank_rank=1, rerank_score=0.9, fusion_rank=1),
            self._record("selected", "P2", source_request_ids=["RQ2"], target_evidence_item_ids=["E2"], rerank_rank=1, rerank_score=0.8, fusion_rank=2),
            self._record("selected", "P3", rerank_rank=2, rerank_score=0.7, fusion_rank=3),
            self._record("round_selected", "P1-alias", alias_provision_ids=["P1", "P1-alias"], rerank_rank=1, rerank_score=0.9, fusion_rank=1, selection_rank=1, selection_reason="critical_quota:E1"),
            self._record("round_selected", "P2", source_request_ids=["RQ2"], target_evidence_item_ids=["E2"], rerank_rank=1, rerank_score=0.8, fusion_rank=2, selection_rank=2, selection_reason="critical_quota:E2"),
        ]
        return records

    def test_dynamic_top_k_formula_is_bounded(self):
        self.assertEqual(replay.dynamic_top_k(10, 20, 2, 3), 10)
        self.assertEqual(replay.dynamic_top_k(10, 20, 2, 6), 12)
        self.assertEqual(replay.dynamic_top_k(10, 11, 2, 8), 11)

    def test_variants_are_deterministic_and_carryover_is_excluded_without_s2_round_state(self):
        result = self._result("ANSWER", ["P1-alias", "P2"])
        first, provenance = replay._variant_rounds(
            self._stage_records(), result, top_k=2, dynamic_cap=4, evidence_quota=2, rrf_k=60
        )
        second, second_provenance = replay._variant_rounds(
            self._stage_records(), result, top_k=2, dynamic_cap=4, evidence_quota=2, rrf_k=60
        )
        self.assertEqual(first, second)
        self.assertEqual(provenance, second_provenance)
        self.assertEqual(first["current_trace"][1], ["P1-alias", "P2"])
        self.assertEqual(provenance["dynamic_top_k_by_round"], {"1": 4})
        self.assertEqual(provenance["carryover"]["status"], "UNVERIFIED")
        self.assertNotIn(provenance["carryover"]["variant_name"], first)

    def test_cohort_metrics_use_evaluator_alias_gold_grouping_and_keep_failure_appendix_separate(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            dataset_path = root / "dataset.json"
            corpus_path = root / "corpus.jsonl"
            rows = [
                {
                    "id": "q-normal", "question": "q", "answer": "a", "background": "b", "n_hops": 1,
                    "contexts": [{"index": "IDX-1", "hierarchy": "법 1조", "content": "본문1"}],
                },
                {
                    "id": "q-failure", "question": "q", "answer": "a", "background": "b", "n_hops": 2,
                    "contexts": [{"index": "IDX-2", "hierarchy": "법 2조", "content": "본문2"}],
                },
            ]
            write_json(dataset_path, {"rows": rows})
            write_jsonl(corpus_path, [
                {"provision_id": "P1", "source_index": "IDX-1", "statute_name": "법 1조", "provision_text": "본문1"},
                {"provision_id": "P1-alias", "source_index": "IDX-1", "statute_name": "법 1조", "provision_text": "본문1"},
                {"provision_id": "P2", "source_index": "IDX-2", "statute_name": "법 2조", "provision_text": "본문2"},
                {"provision_id": "P3", "source_index": "IDX-1", "statute_name": "법 3조", "provision_text": "본문3"},
            ])
            questions = evaluator.load_dataset(dataset_path)
            corpus = evaluator.load_corpus(corpus_path, {"IDX-1", "IDX-2"})
            groups = evaluator.build_gold_groups(questions, ["q-normal", "q-failure"], corpus)
            sources = []
            for ordinal, (question_id, status, candidates) in enumerate(
                [("q-normal", "ANSWER", ["P1-alias", "P2"]), ("q-failure", "EXECUTION_FAILURE", ["P1-alias", "P2"])], start=1
            ):
                run = root / question_id
                metadata = run / "metadata.json"
                write_json(metadata, {"run_id": question_id})
                write_json(run / "result.json", self._result(status, candidates))
                write_jsonl(run / "retrieval_stages.jsonl", self._stage_records())
                sources.append(replay.SourceRow(ordinal, question_id, status, metadata, "", "", "", "PRESENT_RECONCILED"))
            normal = replay._analyze_cohort("normal", sources[:1], questions, groups, 2, 4, 2, 60)
            appendix = replay._analyze_cohort("appendix", sources, questions, groups, 2, 4, 2, 60)
            self.assertEqual(normal["question_count"], 1)
            self.assertEqual(appendix["question_count"], 2)
            current = normal["variants"]["current_trace"]
            self.assertEqual(current["micro"]["true_positive"], 1)
            self.assertEqual(current["micro"]["recall"], 1.0)
            self.assertEqual(current["micro"]["candidate_precision"], 0.5)


if __name__ == "__main__":
    unittest.main()
