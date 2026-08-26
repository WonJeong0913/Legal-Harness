import json
import tempfile
import unittest
from pathlib import Path

from harness.contracts import QueryChannel, RetrievalRequest
from harness.run_state import RunState
from harness.state_update import register_retrieval_round
from harness.validation import (
    validate_retrieval_candidates,
    validate_retrieval_stage_records,
)
from retrieval.corpus import InMemoryProvisionCorpus, ProvisionDocument
from retrieval.pipeline import RetrievalPipeline
from retrieval.types import RetrievalHit


class ScriptedKureFamilyStage:
    """CPU-only KURE-capable fixture; it never loads KURE or vectors."""

    article_family_sibling_expansion_capability = "kure_exact"

    def __init__(self, documents, rankings):
        self.corpus = InMemoryProvisionCorpus(documents)
        self.documents = {
            document.provision_id: document for document in documents
        }
        self.rankings = rankings

    def search(self, request):
        provision_ids = self.rankings.get(request.request_id, [])
        return [
            RetrievalHit(
                self.documents[provision_id],
                float(len(provision_ids) - rank),
                request.request_id,
            )
            for rank, provision_id in enumerate(provision_ids)
        ]

    def article_family_members(self, provision_id):
        return self.corpus.article_family_members(provision_id)


class ScriptedNoFamilyStage:
    def search(self, request):
        del request
        return []


class RecordingReranker:
    def __init__(self, scores_by_query):
        self.scores_by_query = scores_by_query
        self.calls = []

    def rerank(self, query_text, hits, top_k):
        selected = list(hits[:top_k])
        self.calls.append((query_text, [hit.document.provision_id for hit in selected]))
        return [
            self.scores_by_query[query_text][hit.document.provision_id]
            for hit in selected
        ]


def request(request_id, evidence_id, query_text, issue_id="I1"):
    return RetrievalRequest(
        request_id=request_id,
        issue_id=issue_id,
        evidence_item_id=evidence_id,
        query_channel=QueryChannel.STATUTE_AWARE,
        query_text=query_text,
    )


class ArticleFamilySiblingRerankExpansionTests(unittest.TestCase):
    def test_jsonl_loader_preserves_authoritative_optional_source_index(self):
        records = [
            {
                "provision_id": "WITH-SOURCE-INDEX",
                "statute_name": "법 제1조",
                "provision_text": "본문",
                "source_index": "법 제1조 source index",
            },
            {
                "provision_id": "WITHOUT-SOURCE-INDEX",
                "statute_name": "법 제2조",
                "provision_text": "본문",
            },
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "normalized.jsonl"
            path.write_text(
                "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
                encoding="utf-8",
            )
            corpus = InMemoryProvisionCorpus.from_jsonl(path)

        self.assertEqual(
            corpus.get("WITH-SOURCE-INDEX").source_index,
            "법 제1조 source index",
        )
        self.assertIsNone(corpus.get("WITHOUT-SOURCE-INDEX").source_index)

    def test_source_index_family_collapses_exact_snapshot_aliases_without_id_inference(self):
        documents = [
            ProvisionDocument("ROOT-A", "법 제1조", "같은 법문", "법 제1조 제목"),
            ProvisionDocument("ROOT-B", "법 제1조", "같은 법문", "법 제1조 제목"),
            ProvisionDocument("SIBLING", "법 제1조", "별도 항", "법 제1조 제목"),
            ProvisionDocument("EMPTY", "법 제1조", "빈 family", "  "),
            ProvisionDocument("UNKNOWN", "법 제2조", "unknown family"),
        ]
        corpus = InMemoryProvisionCorpus(documents)
        self.assertFalse(corpus.article_family_index_built)

        members = corpus.article_family_members("ROOT-B")
        self.assertTrue(corpus.article_family_index_built)

        self.assertEqual([member.document.provision_id for member in members], ["ROOT-A", "SIBLING"])
        self.assertEqual(members[0].alias_provision_ids, ("ROOT-A", "ROOT-B"))
        self.assertEqual(members[0].family_key, "법 제1조 제목")
        self.assertEqual(documents[0].source_index, "법 제1조 제목")
        self.assertEqual(corpus.article_family_members("EMPTY"), [])
        self.assertEqual(corpus.article_family_members("UNKNOWN"), [])

    def test_empty_and_single_member_unknown_families_fail_closed_to_baseline(self):
        documents = [
            ProvisionDocument("EMPTY-SOURCE", "법 제1조", "empty source"),
            ProvisionDocument("UNKNOWN-SOURCE", "법 제2조", "only member", "unique family"),
            ProvisionDocument("UNRELATED", "법 제3조", "unrelated", "other family"),
        ]
        pipeline = RetrievalPipeline(
            ScriptedKureFamilyStage(
                documents, {"RQ": ["EMPTY-SOURCE", "UNKNOWN-SOURCE"]}
            ),
            RecordingReranker({
                "q": {"EMPTY-SOURCE": 10.0, "UNKNOWN-SOURCE": 9.0}
            }),
            rerank_pool_k=2,
            final_top_k=2,
            rerank_query_mode="per_request",
            article_family_sibling_rerank_expansion=True,
            article_family_expansion_trigger_top_k=2,
            article_family_expansion_max_siblings_per_root=2,
            article_family_expansion_max_siblings_per_request=2,
        )

        candidates = pipeline.retrieve([request("RQ", "E1", "q")], retrieval_round=1)

        self.assertEqual(
            [candidate.provision_id for candidate in candidates],
            ["EMPTY-SOURCE", "UNKNOWN-SOURCE"],
        )
        self.assertFalse(any(
            record.candidate_stage == "article_family_sibling_rerank"
            for record in pipeline.last_stage_records
        ))
        triggers = [
            record for record in pipeline.last_stage_records
            if record.candidate_stage == "article_family_expansion_trigger"
        ]
        self.assertEqual([record.provision_id for record in triggers], ["UNKNOWN-SOURCE"])
        self.assertEqual(triggers[0].article_family_sibling_candidate_count, 0)

    def test_default_disabled_preserves_baseline_candidates_and_stage_records(self):
        documents = [
            ProvisionDocument("ROOT", "법 제1조", "root", "법 제1조 제목"),
            ProvisionDocument("SIBLING", "법 제1조", "sibling", "법 제1조 제목"),
            ProvisionDocument("OTHER", "다른법", "other", "다른법 제1조"),
        ]
        requests = [request("RQ1", "E1", "q")]
        rankings = {"RQ1": ["ROOT", "OTHER"]}
        scores = {"q": {"ROOT": 10.0, "OTHER": 9.0, "SIBLING": 8.0}}
        baseline = RetrievalPipeline(
            ScriptedKureFamilyStage(documents, rankings),
            RecordingReranker(scores),
            rerank_pool_k=2,
            final_top_k=2,
            rerank_query_mode="per_request",
        )
        explicit_disabled = RetrievalPipeline(
            ScriptedKureFamilyStage(documents, rankings),
            RecordingReranker(scores),
            rerank_pool_k=2,
            final_top_k=2,
            rerank_query_mode="per_request",
            article_family_sibling_rerank_expansion=False,
            article_family_expansion_trigger_top_k=1,
            article_family_expansion_max_siblings_per_root=1,
            article_family_expansion_max_siblings_per_request=1,
        )

        baseline_candidates = baseline.retrieve(requests, retrieval_round=1)
        explicit_candidates = explicit_disabled.retrieve(requests, retrieval_round=1)

        self.assertEqual(baseline_candidates, explicit_candidates)
        self.assertEqual(baseline.last_stage_records, explicit_disabled.last_stage_records)
        self.assertEqual([candidate.provision_id for candidate in baseline_candidates], ["ROOT", "OTHER"])
        self.assertFalse(any(
            record.candidate_stage.startswith("article_family_")
            for record in baseline.last_stage_records
        ))

    def test_default_disabled_does_not_build_the_family_index(self):
        documents = [
            ProvisionDocument("ROOT", "법", "root", "family"),
            ProvisionDocument("SIBLING", "법", "sibling", "family"),
        ]
        stage = ScriptedKureFamilyStage(documents, {"RQ": ["ROOT"]})
        pipeline = RetrievalPipeline(
            stage,
            RecordingReranker({"q": {"ROOT": 10.0}}),
            rerank_pool_k=1,
            final_top_k=1,
            rerank_query_mode="per_request",
        )

        self.assertFalse(stage.corpus.article_family_index_built)
        pipeline.retrieve([request("RQ", "E1", "q")], retrieval_round=1)
        self.assertFalse(stage.corpus.article_family_index_built)

    def test_enabled_fails_closed_without_kure_capability_or_per_request_rerank(self):
        with self.assertRaisesRegex(ValueError, "requires KURE corpus capability"):
            RetrievalPipeline(
                ScriptedNoFamilyStage(),
                RecordingReranker({}),
                rerank_query_mode="per_request",
                article_family_sibling_rerank_expansion=True,
            )
        with self.assertRaisesRegex(ValueError, "requires per_request reranking"):
            RetrievalPipeline(
                ScriptedKureFamilyStage([], {}),
                RecordingReranker({}),
                rerank_query_mode="combined_issue",
                article_family_sibling_rerank_expansion=True,
            )

    def test_qa125_shape_reranks_source_index_sibling_without_first_stage_fabrication(self):
        family_key = "형사소송법 361조 5 상고심의 판결"
        documents = [
            ProvisionDocument("#232721", "형사소송법 제361조의5", "root header", family_key),
            ProvisionDocument("#232732", "형사소송법 제361조의5", "relevant sibling", family_key),
            ProvisionDocument("#232733", "형사소송법 제361조의5", "irrelevant sibling", family_key),
            ProvisionDocument("OTHER", "별도법 제1조", "baseline other", "별도법 제1조"),
        ]
        query = "상고심 판단 질의"
        retriever = ScriptedKureFamilyStage(
            documents, {"RQ125": ["#232721", "OTHER"]}
        )
        reranker = RecordingReranker({
            query: {
                "#232721": 10.0,
                "#232732": 9.5,
                "#232733": -5.0,
                "OTHER": 9.0,
            }
        })
        pipeline = RetrievalPipeline(
            retriever,
            reranker,
            rerank_pool_k=2,
            final_top_k=2,
            rerank_query_mode="per_request",
            dedup_mode="legal_text_alias",
            article_family_sibling_rerank_expansion=True,
            article_family_expansion_trigger_top_k=1,
            article_family_expansion_max_siblings_per_root=2,
            article_family_expansion_max_siblings_per_request=2,
        )
        requests = [request("RQ125", "E125", query)]

        candidates = pipeline.retrieve(requests, retrieval_round=1)

        self.assertEqual([candidate.provision_id for candidate in candidates], ["#232721", "#232732"])
        self.assertNotIn("#232733", [candidate.provision_id for candidate in candidates])
        self.assertEqual([query for query, _ in reranker.calls], [query, query])
        self.assertEqual(reranker.calls[0][1], ["#232721", "OTHER"])
        self.assertEqual(reranker.calls[1][1], ["#232732", "#232733"])
        self.assertIsNone(candidates[1].first_stage_rank)
        self.assertIsNone(candidates[1].first_stage_score)
        first_stage_ids = {
            record.provision_id
            for record in pipeline.last_stage_records
            if record.candidate_stage == "first_stage"
        }
        self.assertNotIn("#232732", first_stage_ids)
        self.assertNotIn("#232733", first_stage_ids)
        sibling_records = [
            record for record in pipeline.last_stage_records
            if record.candidate_stage == "article_family_sibling_rerank"
        ]
        self.assertEqual([record.provision_id for record in sibling_records], ["#232732", "#232733"])
        self.assertTrue(all(record.article_family_key == family_key for record in sibling_records))
        self.assertTrue(all(record.article_family_root_provision_id == "#232721" for record in sibling_records))
        self.assertTrue(all(record.source_request_ids == ["RQ125"] for record in sibling_records))
        self.assertTrue(all(record.target_evidence_item_ids == ["E125"] for record in sibling_records))
        validate_retrieval_stage_records(pipeline.last_stage_records, requests, 1)

    def test_long_family_cap_and_score_id_ties_are_deterministic(self):
        family_key = "긴 family"
        documents = [
            ProvisionDocument("ROOT", "법 제1조", "root", family_key),
            ProvisionDocument("A", "법 제1조", "a", family_key),
            ProvisionDocument("B", "법 제1조", "b", family_key),
            ProvisionDocument("C", "법 제1조", "c", family_key),
        ]
        query = "tie query"
        pipeline = RetrievalPipeline(
            ScriptedKureFamilyStage(documents, {"RQ": ["ROOT"]}),
            RecordingReranker({query: {"ROOT": 10.0, "A": 5.0, "B": 5.0, "C": 5.0}}),
            rerank_pool_k=3,
            final_top_k=3,
            rerank_query_mode="per_request",
            article_family_sibling_rerank_expansion=True,
            article_family_expansion_trigger_top_k=1,
            article_family_expansion_max_siblings_per_root=2,
            article_family_expansion_max_siblings_per_request=2,
        )
        requests = [request("RQ", "E1", query)]

        candidates = pipeline.retrieve(requests, retrieval_round=1)

        self.assertEqual([candidate.provision_id for candidate in candidates], ["ROOT", "A", "B"])
        trigger = next(
            record for record in pipeline.last_stage_records
            if record.candidate_stage == "article_family_expansion_trigger"
        )
        self.assertEqual(trigger.article_family_sibling_candidate_count, 3)
        self.assertEqual(trigger.article_family_sibling_selected_count, 2)
        self.assertEqual(trigger.article_family_sibling_dropped_count, 1)
        self.assertEqual(trigger.article_family_sibling_per_root_cap, 2)
        self.assertEqual(trigger.article_family_sibling_per_request_cap, 2)
        sibling_records = {
            record.provision_id: record
            for record in pipeline.last_stage_records
            if record.candidate_stage == "article_family_sibling_rerank"
        }
        self.assertEqual(list(sibling_records), ["A", "B", "C"])
        self.assertTrue(sibling_records["A"].article_family_sibling_selected)
        self.assertTrue(sibling_records["B"].article_family_sibling_selected)
        self.assertFalse(sibling_records["C"].article_family_sibling_selected)
        self.assertEqual(
            sibling_records["C"].article_family_sibling_dropped_reason,
            "per_root_cap",
        )

    def test_qa125_sixteen_member_family_scores_semantic_sibling_before_cap(self):
        family_key = "형사소송법 361조 5 항소이유"
        documents = [
            ProvisionDocument("#232721", "형사소송법 제361조의5", "root", family_key)
        ] + [
            ProvisionDocument(
                "#%d" % provision_number,
                "형사소송법 제361조의5",
                "sibling %d" % provision_number,
                family_key,
            )
            for provision_number in range(232722, 232737)
        ]
        query = "qa125-shaped semantic query"
        scores = {"#232721": 10.0}
        scores.update({
            "#%d" % provision_number: -float(provision_number)
            for provision_number in range(232722, 232737)
        })
        scores["#232732"] = 100.0
        reranker = RecordingReranker({query: scores})
        pipeline = RetrievalPipeline(
            ScriptedKureFamilyStage(documents, {"RQ125": ["#232721"]}),
            reranker,
            rerank_pool_k=2,
            final_top_k=2,
            rerank_query_mode="per_request",
            article_family_sibling_rerank_expansion=True,
            article_family_expansion_trigger_top_k=1,
            article_family_expansion_max_siblings_per_root=4,
            article_family_expansion_max_siblings_per_request=4,
            article_family_expansion_max_family_members_scored=128,
        )
        requests = [request("RQ125", "E125", query)]

        candidates = pipeline.retrieve(requests, retrieval_round=1)

        self.assertEqual(
            [candidate.provision_id for candidate in candidates],
            ["#232732", "#232721"],
        )
        self.assertEqual(len(reranker.calls), 2)
        self.assertEqual(len(reranker.calls[1][1]), 15)
        self.assertIn("#232732", reranker.calls[1][1])
        relevant_candidate = candidates[0]
        self.assertIsNone(relevant_candidate.first_stage_rank)
        self.assertIsNone(relevant_candidate.first_stage_score)
        self.assertEqual(relevant_candidate.rerank_score, 100.0)
        sibling_records = {
            record.provision_id: record
            for record in pipeline.last_stage_records
            if record.candidate_stage == "article_family_sibling_rerank"
        }
        self.assertEqual(len(sibling_records), 15)
        relevant = sibling_records["#232732"]
        self.assertTrue(relevant.article_family_sibling_selected)
        self.assertEqual(relevant.article_family_sibling_selection_rank, 1)
        self.assertEqual(relevant.rerank_score, 100.0)
        self.assertIsNone(relevant.first_stage_rank)
        self.assertIsNone(relevant.first_stage_score)
        self.assertIsNone(relevant.fusion_rank)
        self.assertIsNone(relevant.fusion_score)
        self.assertIsNotNone(relevant.article_family_root_first_stage_score)
        self.assertIsNotNone(relevant.article_family_root_fusion_score)
        self.assertEqual(relevant.article_family_sibling_candidate_count, 15)
        self.assertEqual(relevant.article_family_sibling_scored_count, 15)
        self.assertEqual(relevant.article_family_sibling_selected_count, 4)
        self.assertEqual(relevant.article_family_sibling_dropped_count, 11)
        self.assertFalse(sibling_records["#232736"].article_family_sibling_selected)
        self.assertEqual(
            sibling_records["#232736"].article_family_sibling_dropped_reason,
            "per_root_cap",
        )
        validate_retrieval_candidates(candidates, requests, 1)
        validate_retrieval_stage_records(pipeline.last_stage_records, requests, 1)

    def test_request_cap_uses_global_sibling_score_not_root_processing_order(self):
        documents = [
            ProvisionDocument("ROOT-A", "법 A", "root A", "family A"),
            ProvisionDocument("SIBLING-A", "법 A", "sibling A", "family A"),
            ProvisionDocument("ROOT-B", "법 B", "root B", "family B"),
            ProvisionDocument("SIBLING-B", "법 B", "sibling B", "family B"),
        ]
        query = "global score query"
        pipeline = RetrievalPipeline(
            ScriptedKureFamilyStage(
                documents, {"RQ": ["ROOT-A", "ROOT-B"]}
            ),
            RecordingReranker({query: {
                "ROOT-A": 10.0,
                "ROOT-B": 9.0,
                "SIBLING-A": 1.0,
                "SIBLING-B": 100.0,
            }}),
            rerank_pool_k=2,
            final_top_k=2,
            rerank_query_mode="per_request",
            article_family_sibling_rerank_expansion=True,
            article_family_expansion_trigger_top_k=2,
            article_family_expansion_max_siblings_per_root=1,
            article_family_expansion_max_siblings_per_request=1,
        )

        candidates = pipeline.retrieve([request("RQ", "E1", query)], retrieval_round=1)

        self.assertEqual(candidates[0].provision_id, "SIBLING-B")
        sibling_records = {
            record.provision_id: record
            for record in pipeline.last_stage_records
            if record.candidate_stage == "article_family_sibling_rerank"
        }
        self.assertTrue(sibling_records["SIBLING-B"].article_family_sibling_selected)
        self.assertFalse(sibling_records["SIBLING-A"].article_family_sibling_selected)
        self.assertEqual(
            sibling_records["SIBLING-A"].article_family_sibling_dropped_reason,
            "per_request_cap",
        )

    def test_family_scoring_bound_is_positive_and_fails_closed_before_truncation(self):
        documents = [
            ProvisionDocument("ROOT", "법", "root", "family"),
            ProvisionDocument("SIBLING-A", "법", "a", "family"),
            ProvisionDocument("SIBLING-B", "법", "b", "family"),
        ]
        for invalid_maximum in (0, True):
            with self.assertRaisesRegex(ValueError, "bounds must be positive"):
                RetrievalPipeline(
                    ScriptedKureFamilyStage(documents, {"RQ": ["ROOT"]}),
                    RecordingReranker({"q": {"ROOT": 1.0}}),
                    rerank_query_mode="per_request",
                    article_family_expansion_max_family_members_scored=invalid_maximum,
                )
        pipeline = RetrievalPipeline(
            ScriptedKureFamilyStage(documents, {"RQ": ["ROOT"]}),
            RecordingReranker({"q": {"ROOT": 1.0}}),
            rerank_pool_k=1,
            final_top_k=1,
            rerank_query_mode="per_request",
            article_family_sibling_rerank_expansion=True,
            article_family_expansion_max_family_members_scored=2,
        )

        with self.assertRaisesRegex(ValueError, "exceeds max_family_members_scored"):
            pipeline.retrieve([request("RQ", "E1", "q")], retrieval_round=1)

    def test_multiple_requests_inherit_each_request_and_evidence_provenance(self):
        documents = [
            ProvisionDocument("ROOT-1", "법1", "root1", "family-1"),
            ProvisionDocument("SIBLING-1", "법1", "sibling1", "family-1"),
            ProvisionDocument("ROOT-2", "법2", "root2", "family-2"),
            ProvisionDocument("SIBLING-2", "법2", "sibling2", "family-2"),
        ]
        requests = [request("RQ1", "E1", "q1"), request("RQ2", "E2", "q2")]
        pipeline = RetrievalPipeline(
            ScriptedKureFamilyStage(
                documents, {"RQ1": ["ROOT-1"], "RQ2": ["ROOT-2"]}
            ),
            RecordingReranker({
                "q1": {"ROOT-1": 10.0, "SIBLING-1": 9.0},
                "q2": {"ROOT-2": 8.0, "SIBLING-2": 7.0},
            }),
            rerank_pool_k=2,
            final_top_k=2,
            rerank_query_mode="per_request",
            article_family_sibling_rerank_expansion=True,
            article_family_expansion_trigger_top_k=1,
            article_family_expansion_max_siblings_per_root=1,
            article_family_expansion_max_siblings_per_request=1,
        )

        pipeline.retrieve(requests, retrieval_round=1)

        sibling_records = {
            record.provision_id: record
            for record in pipeline.last_stage_records
            if record.candidate_stage == "article_family_sibling_rerank"
        }
        self.assertEqual(sibling_records["SIBLING-1"].source_request_ids, ["RQ1"])
        self.assertEqual(sibling_records["SIBLING-1"].target_evidence_item_ids, ["E1"])
        self.assertEqual(sibling_records["SIBLING-2"].source_request_ids, ["RQ2"])
        self.assertEqual(sibling_records["SIBLING-2"].target_evidence_item_ids, ["E2"])
        validate_retrieval_stage_records(pipeline.last_stage_records, requests, 1)

    def test_round_merge_keeps_expansion_provenance_append_only_without_candidate_overwrite(self):
        documents = [
            ProvisionDocument("ROOT", "법 제1조", "root", "family"),
            ProvisionDocument("SIBLING", "법 제1조", "sibling", "family"),
        ]
        query = "round query"
        pipeline = RetrievalPipeline(
            ScriptedKureFamilyStage(documents, {"RQ": ["ROOT"]}),
            RecordingReranker({query: {"ROOT": 10.0, "SIBLING": 9.0}}),
            rerank_pool_k=2,
            final_top_k=2,
            rerank_query_mode="per_request",
            candidate_budget_scope="per_round",
            round_merge_mode="single_issue_fusion_top_k",
            article_family_sibling_rerank_expansion=True,
            article_family_expansion_trigger_top_k=1,
            article_family_expansion_max_siblings_per_root=1,
            article_family_expansion_max_siblings_per_request=1,
        )
        requests = [request("RQ", "E1", query)]
        state = RunState(question="질문", normalized_question="질문", run_id="run")

        first = pipeline.retrieve(requests, retrieval_round=1)
        first_records = list(pipeline.last_stage_records)
        register_retrieval_round(
            state, requests, first, is_gap=False, candidate_stage_records=first_records
        )
        second = pipeline.retrieve(requests, retrieval_round=2)
        second_records = list(pipeline.last_stage_records)
        register_retrieval_round(
            state, requests, second, is_gap=True, candidate_stage_records=second_records
        )

        self.assertEqual([candidate.provision_id for candidate in first], ["ROOT", "SIBLING"])
        self.assertEqual([candidate.provision_id for candidate in second], ["ROOT", "SIBLING"])
        self.assertEqual([candidate.provision_id for candidate in state.candidate_provisions], ["ROOT", "SIBLING"])
        self.assertEqual(state.corpus_text_snapshots["SIBLING"], "sibling")
        self.assertEqual(
            [record.retrieval_round for record in state.retrieval_stage_records
             if record.candidate_stage == "article_family_sibling_rerank"],
            [1, 2],
        )


if __name__ == "__main__":
    unittest.main()
