import importlib.util
import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from harness.contracts import QueryChannel, RetrievalRequest
from retrieval.corpus import InMemoryProvisionCorpus, ProvisionDocument
from retrieval.types import RetrievalHit


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/replay_saved_c15_sibling_retrieval.py"
SPEC = importlib.util.spec_from_file_location("c15_replay", MODULE_PATH)
probe = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


class FakeKureStage:
    """CPU-only KURE-shaped fixture; no vector/model artifact is loaded."""

    article_family_sibling_expansion_capability = "kure_exact"

    def __init__(self, documents, ranked_ids):
        self.corpus = InMemoryProvisionCorpus(documents)
        self.documents = {document.provision_id: document for document in documents}
        self.ranked_ids = ranked_ids

    def search(self, request):
        ids = self.ranked_ids[request.request_id]
        return [
            RetrievalHit(self.documents[provision_id], float(len(ids) - rank), request.request_id)
            for rank, provision_id in enumerate(ids)
        ]

    def article_family_members(self, provision_id):
        return self.corpus.article_family_members(provision_id)


class FakeBgeReranker:
    """CPU-only score table replacing BGE; it records no external calls."""

    def __init__(self, scores):
        self.scores = scores

    def rerank(self, query_text, hits, top_k):
        return [self.scores[query_text][hit.document.provision_id] for hit in hits[:top_k]]


def request(request_id="RQ1", query="질의"):
    return RetrievalRequest(
        request_id=request_id,
        issue_id="I1",
        evidence_item_id="E1",
        query_channel=QueryChannel.STATUTE_AWARE,
        query_text=query,
        query_terms=["질의"],
        statute_hints=["형사소송법"],
    )


def configuration():
    return {
        "retriever": "kure", "rerank_pool_k": 2, "final_top_k": 2,
        "rerank_query_mode": "per_request", "candidate_selection": "global_top_k",
        "per_evidence_min_k": 1, "dedup_mode": "legal_text_alias",
        "candidate_budget_scope": "per_round", "round_merge_mode": "raw_score",
        "rerank_document_mode": "statute_and_body",
        "article_family_sibling_rerank_expansion": False,
        "article_family_expansion_trigger_top_k": 1,
        "article_family_expansion_max_siblings_per_root": 4,
        "article_family_expansion_max_siblings_per_request": 4,
        "article_family_expansion_max_family_members_scored": 128,
    }


def bundle_for(profile, query="질의"):
    return probe.SourceBundle(profile, (request(query=query),), configuration(), {"test": "binding"})


def factory_for(documents, ranked_ids, scores):
    def factory(config, trace):
        first = probe.RecordingFirstStage(FakeKureStage(documents, ranked_ids), trace)
        reranker = probe.RecordingReranker(FakeBgeReranker(scores), trace)
        return probe.pipeline_from_parts(config, first, reranker)
    return factory


class SavedC15SiblingRetrievalTests(unittest.TestCase):
    def qa125_fixture(self, *, composite_ids=False):
        """Bare IDs exercise static suffix bindings; composite IDs mirror KURE."""
        family = "형사소송법 361조 5 항소심의 판결"
        def provision_id(number):
            suffix = "KOBLEX-%d" % number
            return "형사소송법 361조 5 항소이유#" + suffix if composite_ids else suffix
        documents = [ProvisionDocument(provision_id(232721), "형사소송법", "root", family)]
        documents.extend(
            ProvisionDocument(provision_id(number), "형사소송법", "sibling-%d" % number, family)
            for number in range(232722, 232737)
        )
        documents.append(ProvisionDocument("OTHER", "다른 법", "other", "다른 법 제1조"))
        scores = {"질의": {document.provision_id: 1.0 for document in documents}}
        scores["질의"][provision_id(232721)] = 10.0
        scores["질의"][provision_id(232732)] = 9.5
        scores["질의"]["OTHER"] = 9.0
        return documents, {"RQ1": [provision_id(232721), "OTHER"]}, scores

    def test_static_allowlist_is_exact_and_excludes_wrong_qa125(self):
        self.assertEqual(set(probe.SOURCE_PROFILES), {
            "qa_125_2hop_226", "qa_68_1hop_100", "qa_435_2hop_678",
        })
        profile = probe.SOURCE_PROFILES["qa_125_2hop_226"]
        self.assertEqual((profile.sequence, profile.ordinal, profile.run_id), (
            48, 106, "ce09d435-580f-4b0e-8f2d-fc08a5a3a9d6",
        ))
        self.assertEqual(profile.expected_scored_sibling_ids, tuple(
            "KOBLEX-%d" % item for item in range(232722, 232737)
        ))

    def test_qa125_bare_suffix_fixture_preserves_request_query_bytes_and_audits_every_sibling(self):
        source = bundle_for(probe.SOURCE_PROFILES["qa_125_2hop_226"])
        documents, ranked_ids, scores = self.qa125_fixture()
        result = probe.run_retrieval_only_probe(
            source, factory_for(documents, ranked_ids, scores), {"fixture": "hash"}
        )
        baseline = result["baseline_feature_disabled"]
        enabled = result["enabled_c15_1"]
        self.assertEqual(baseline["query_trace"]["kure_queries"], enabled["query_trace"]["kure_queries"])
        self.assertEqual(baseline["query_trace"]["bge_request_queries"], enabled["query_trace"]["bge_request_queries"])
        self.assertEqual([item["provision_id"] for item in baseline["candidates"]], ["KOBLEX-232721", "OTHER"])
        self.assertIn("KOBLEX-232732", [item["provision_id"] for item in enabled["candidates"]])
        audit = enabled["sibling_audit"]
        self.assertEqual({item["provision_id"] for item in audit["sibling_records"]}, set(
            "KOBLEX-%d" % item for item in range(232722, 232737)
        ))
        self.assertEqual(audit["hard_family_member_bound"], 128)
        self.assertEqual(result["candidate_code"], {"commit": probe.C15_1_COMMIT, "tree": probe.C15_1_TREE})

    def test_qa125_composite_kure_ids_match_the_static_suffix_audit(self):
        source = bundle_for(probe.SOURCE_PROFILES["qa_125_2hop_226"])
        documents, ranked_ids, scores = self.qa125_fixture(composite_ids=True)
        result = probe.run_retrieval_only_probe(
            source, factory_for(documents, ranked_ids, scores), {"fixture": "composite-hash"}
        )
        root = "형사소송법 361조 5 항소이유#KOBLEX-232721"
        available = "형사소송법 361조 5 항소이유#KOBLEX-232732"
        self.assertEqual(result["baseline_feature_disabled"]["candidates"][0]["provision_id"], root)
        audit = result["enabled_c15_1"]["sibling_audit"]
        self.assertIn(available, [item["provision_id"] for item in audit["sibling_records"]])
        self.assertEqual({item["provision_id"].rsplit("#", 1)[-1] for item in audit["sibling_records"]}, set(
            "KOBLEX-%d" % item for item in range(232722, 232737)
        ))

    def test_qa125_ambiguous_composite_suffix_fails_closed(self):
        profile = probe.SOURCE_PROFILES["qa_125_2hop_226"]
        stages = [
            {"candidate_stage": "article_family_expansion_trigger", "provision_id": "법 A#KOBLEX-232721", "article_family_sibling_candidate_count": 1},
            {"candidate_stage": "article_family_expansion_trigger", "provision_id": "법 B#KOBLEX-232721", "article_family_sibling_candidate_count": 1},
        ]
        with self.assertRaisesRegex(probe.ProbeSafetyError, "ambiguous canonical KOBLEX identifier"):
            probe.audit_siblings(profile, stages, enabled=True)

    def test_qa68_and_qa435_use_the_generic_family_audit(self):
        docs = [
            ProvisionDocument("ROOT", "법", "root", "법 제1조"),
            ProvisionDocument("SIBLING", "법", "sibling", "법 제1조"),
        ]
        scores = {"질의": {"ROOT": 10.0, "SIBLING": 9.0}}
        for question_id in ("qa_68_1hop_100", "qa_435_2hop_678"):
            with self.subTest(question_id=question_id):
                result = probe.run_retrieval_only_probe(
                    bundle_for(probe.SOURCE_PROFILES[question_id]),
                    factory_for(docs, {"RQ1": ["ROOT"]}, scores), {"fixture": "hash"},
                )
                self.assertEqual(result["enabled_c15_1"]["sibling_audit"]["max_observed_family_members"], 2)

    def test_overbound_family_fails_closed_before_sibling_scoring(self):
        docs = [ProvisionDocument("ROOT", "법", "root", "family")]
        docs.extend(ProvisionDocument("S%03d" % index, "법", "body%d" % index, "family") for index in range(128))
        scores = {"질의": {document.provision_id: 1.0 for document in docs}}
        source = bundle_for(probe.SOURCE_PROFILES["qa_68_1hop_100"])
        enabled = configuration(); enabled["article_family_sibling_rerank_expansion"] = True
        with self.assertRaisesRegex(ValueError, "max_family_members_scored"):
            probe.run_condition(source, enabled, factory_for(docs, {"RQ1": ["ROOT"]}, scores))

    def test_corpus_observed_family_cap_is_checked_before_future_execution(self):
        records = [
            {"provision_id": "A", "statute_name": "법", "provision_text": "a", "source_index": "family"},
            {"provision_id": "B", "statute_name": "법", "provision_text": "b", "source_index": "family"},
        ]
        with tempfile.TemporaryDirectory() as temporary_directory:
            corpus = Path(temporary_directory) / "statute.jsonl"
            corpus.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
            with mock.patch.object(probe, "CORPUS_OBSERVED_MAX_FAMILY_MEMBERS", 2):
                self.assertEqual(probe.audit_corpus_family_bound(corpus), 2)
            with mock.patch.object(probe, "CORPUS_OBSERVED_MAX_FAMILY_MEMBERS", 2), mock.patch.object(probe, "FAMILY_MEMBER_BOUND", 1):
                with self.assertRaisesRegex(probe.ProbeSafetyError, "hard scoring bound"):
                    probe.audit_corpus_family_bound(corpus)

    def test_initial_request_extraction_excludes_gap_repair_requests(self):
        result = {"state": {"query_history": [
            {"request_id": "RQ1", "issue_id": "I1", "evidence_item_id": "E1", "query_channel": "statute_aware", "query_text": "one", "top_k": 100},
            {"request_id": "GRQ-R2-1", "issue_id": "I1", "evidence_item_id": "E1", "query_channel": "statute_aware", "query_text": "forbidden", "top_k": 100},
        ]}}
        requests = probe.initial_requests_from_result(result)
        self.assertEqual([item.request_id for item in requests], ["RQ1"])

    def test_no_overwrite_resume_and_workspace_output_guard(self):
        result = {"immutable_binding_sha256": "binding"}
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "output"
            self.assertEqual(probe.write_result(output, result, False), output / "probe.json")
            self.assertEqual(probe.write_result(output, result, True), output / "probe.json")
            with self.assertRaisesRegex(probe.ProbeSafetyError, "refusing overwrite"):
                probe.write_result(output, result, False)
            with self.assertRaisesRegex(probe.ProbeSafetyError, "resume binding mismatch"):
                probe.write_result(output, {"immutable_binding_sha256": "different"}, True)
        with self.assertRaisesRegex(probe.ProbeSafetyError, "workspace"):
            probe.assert_safe_output(Path("/workspace/probe-output"))

    def test_resume_verifies_binding_without_a_pipeline_factory(self):
        source = bundle_for(probe.SOURCE_PROFILES["qa_68_1hop_100"])
        artifacts = {"fixture": "hash"}
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "sealed"
            output.mkdir()
            binding = probe.immutable_binding(source, artifacts)
            (output / "probe.json").write_text(json.dumps({
                "immutable_binding_sha256": probe.canonical_sha256(binding),
            }), encoding="utf-8")
            self.assertEqual(probe.verify_resume(output, source, artifacts), output / "probe.json")

    def test_gold_is_separated_from_retrieval_and_source_has_no_forbidden_runner_import(self):
        with self.assertRaisesRegex(probe.ProbeSafetyError, "after retrieval is sealed"):
            probe.score_post_hoc_gold({"retrieval_sealed": False}, Path("missing.jsonl"))
        source = MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in ("run_local_harness", "LocalOllama", "SqliteFts5Bm25Searcher", "import harness.evaluator"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
