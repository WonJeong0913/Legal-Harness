import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from harness.contracts import QueryChannel, RetrievalRequest
from retrieval.corpus import ProvisionDocument
from retrieval.persistent import (
    Bm25sParSeRFirstStageSearcher,
    PARSER_BM25S_TOP_K,
    load_bm25s_parser_rows,
)
from runtime.comparison_guard import validate_bm25s_first_stage_ablation
from scripts import c02_bm25s_ablation as ablation
from scripts.evaluate_dev_runs import evaluate_batch


ASSET_ROOT = Path("/workspace/Legal-Harness")
STATUTE_PARQUET = ASSET_ROOT / "data/koblex/statute/corpus-00000-of-00001.parquet"
NORMALIZED_CORPUS = ASSET_ROOT / "data/koblex/normalized/statute.jsonl"


class _FakeBm25:
    def __init__(self, owner):
        self.owner = owner

    def index(self, tokens, **kwargs):
        self.owner.index_calls.append((tokens, kwargs))

    def retrieve(self, tokens, **kwargs):
        self.owner.retrieve_calls.append((tokens, kwargs))
        return [[2, 0, 1]], [[3.0, 2.0, 1.0]]


class _FakeBm25s:
    def __init__(self):
        self.tokenize_calls = []
        self.index_calls = []
        self.retrieve_calls = []

    def tokenize(self, texts, **kwargs):
        self.tokenize_calls.append((list(texts), dict(kwargs)))
        return ["TOKENS", *list(texts)]

    def BM25(self):
        return _FakeBm25(self)


def _request(*, top_k=PARSER_BM25S_TOP_K):
    return RetrievalRequest(
        request_id="RQ1",
        issue_id="I1",
        evidence_item_id="E1",
        query_channel=QueryChannel.PROVISION_STYLE,
        query_text="질의 본문",
        top_k=top_k,
        query_terms=["FTS5 확장 금지"],
        statute_hints=["법령 힌트 금지"],
    )


class Bm25sAdapterUnitTests(unittest.TestCase):
    def test_parsers_semantics_preserve_duplicate_source_indexes_and_ignore_harness_fields(self):
        fake = _FakeBm25s()
        rows = [
            ("동일 인덱스", ProvisionDocument("P1", "H1", "C1"), "H1C1"),
            ("동일 인덱스", ProvisionDocument("P2", "H2", "C2"), "H2C2"),
            ("다른 인덱스", ProvisionDocument("P3", "H3", "C3"), "H3C3"),
        ]
        searcher = Bm25sParSeRFirstStageSearcher(rows, bm25s_module=fake)

        hits = searcher.search(_request())

        self.assertEqual([hit.document.provision_id for hit in hits], ["P3", "P1", "P2"])
        self.assertEqual([hit.source_request_id for hit in hits], ["RQ1", "RQ1", "RQ1"])
        self.assertEqual(
            fake.tokenize_calls,
            [
                (["H1C1", "H2C2", "H3C3"], {"stopwords": "en", "show_progress": False}),
                (["질의 본문"], {"show_progress": False}),
            ],
        )
        self.assertEqual(fake.retrieve_calls[0][1], {"k": 100, "show_progress": False})

    def test_non_parser_top_k_fails_closed(self):
        fake = _FakeBm25s()
        searcher = Bm25sParSeRFirstStageSearcher(
            [("S", ProvisionDocument("P", "H", "C"), "HC")],
            bm25s_module=fake,
        )

        with self.assertRaisesRegex(ValueError, "top_k=100"):
            searcher.search(_request(top_k=99))


@unittest.skipUnless(STATUTE_PARQUET.is_file() and NORMALIZED_CORPUS.is_file(), "fixed C02 assets unavailable")
class C02AssetMappingTests(unittest.TestCase):
    def test_fixed_corpus_has_exact_233544_positional_mapping(self):
        rows = load_bm25s_parser_rows(STATUTE_PARQUET, NORMALIZED_CORPUS)

        self.assertEqual(len(rows), 233544)
        self.assertEqual(rows[0][1].provision_id, "국세징수법 시행령 1조#KOBLEX-000001")
        self.assertEqual(rows[0][2], "국세징수법 시행령 1조제1장 총칙")
        self.assertEqual(
            ablation._bm25s_corpus_mapping_sha256(rows),
            "087ba03a2b960fc8d567a43afcccac2a6a931e44115dede18c96a8bd4bdbdabd",
        )

    @unittest.skipUnless(importlib.util.find_spec("bm25s") is not None, "bm25s runtime unavailable")
    def test_three_saved_c02_queries_equal_parser_baseline_top100_source_indexes(self):
        from baselines.koblex_parser.retrieval import Bm25Retriever, load_statute_corpus

        baseline = Bm25Retriever(load_statute_corpus(STATUTE_PARQUET))
        searcher = Bm25sParSeRFirstStageSearcher.from_parquet(
            STATUTE_PARQUET, NORMALIZED_CORPUS
        )
        source_index_by_provision_id = {
            document.provision_id: source_index
            for source_index, document in zip(searcher.source_indexes, searcher.documents)
        }
        for fixture in ablation.PARSER_PARITY_FIXTURES:
            with self.subTest(query_sha256=fixture["query_sha256"]):
                hits = searcher.search(
                    RetrievalRequest(
                        "RQ", "I", "E", QueryChannel.PROVISION_STYLE,
                        fixture["query"], PARSER_BM25S_TOP_K,
                        query_terms=["must not affect bm25s"],
                        statute_hints=["must not affect bm25s"],
                    )
                )
                actual = [source_index_by_provision_id[hit.document.provision_id] for hit in hits]
                self.assertEqual(actual, [baseline.records[index].index for index in baseline.top_k(fixture["query"])])
                self.assertEqual(
                    ablation.canonical_sha256(actual),
                    fixture["canonical_source_index_list_sha256"],
                )
        # The third saved query intentionally contains duplicate raw parquet indexes.
        third = ablation.PARSER_PARITY_FIXTURES[2]
        hits = searcher.search(RetrievalRequest("RQ", "I", "E", QueryChannel.PROVISION_STYLE, third["query"], 100))
        source_indexes = [source_index_by_provision_id[hit.document.provision_id] for hit in hits[:10]]
        self.assertLess(len(set(source_indexes)), len(source_indexes))


class C02AblationGuardTests(unittest.TestCase):
    def _manifest(self, retriever):
        configuration = {
            "condition": "C02" if retriever == "kure" else "C02-bm25s",
            "retriever": retriever,
            "model": "legal-harness-qwen38-q8",
            "seed": 0,
            "num_ctx": 32768,
            "total_retrieval_rounds": 3,
            "total_retrieval_requests": 9,
            "rerank_pool_k": 100,
            "final_top_k": 10,
        }
        if retriever == "kure":
            configuration["retriever_provenance"] = {"backend": "KURE"}
        else:
            configuration["retriever_provenance"] = {
                "backend": "bm25s.BM25",
                "top_k": 100,
                "query_tokenization": "bm25s.tokenize([query])",
            }
        return {
            "source_dataset": {"path": "qa.parquet", "sha256": "a" * 64},
            "entries": [{"ordinal": 1, "question_id": "q1", "n_hops": 1}],
            "frozen_configuration": configuration,
        }

    def test_bm25s_guard_requires_explicit_backend_and_retriever_only_diff(self):
        receipt = validate_bm25s_first_stage_ablation(
            self._manifest("kure"), self._manifest("bm25s_parser"),
            Path("c02.json"), Path("bm25s.json"),
        )

        self.assertEqual(receipt["status"], "VALIDATED_C02_BM25S_FIRST_STAGE_ABLATION")

    def test_bm25s_guard_rejects_fts5_label_or_budget_drift(self):
        ablation_manifest = self._manifest("bm25s_parser")
        ablation_manifest["frozen_configuration"]["retriever_provenance"]["backend"] = "sqlite_fts5"
        with self.assertRaisesRegex(RuntimeError, "backend=bm25s.BM25"):
            validate_bm25s_first_stage_ablation(
                self._manifest("kure"), ablation_manifest, Path("c02.json"), Path("bm25s.json")
            )
        ablation_manifest = self._manifest("bm25s_parser")
        ablation_manifest["frozen_configuration"]["final_top_k"] = 20
        with self.assertRaisesRegex(RuntimeError, "outside allowed fields"):
            validate_bm25s_first_stage_ablation(
                self._manifest("kure"), ablation_manifest, Path("c02.json"), Path("bm25s.json")
            )


class ResumeAndEvaluatorCompatibilityTests(unittest.TestCase):
    @staticmethod
    def _sha256(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _configuration():
        return {
            "condition": "C02-bm25s-test",
            "retriever": "bm25s_parser",
            "model": "legal-harness-qwen38-q8",
            "seed": 0,
            "ollama_endpoint": "http://127.0.0.1:11435/api/generate",
            "num_ctx": 32768,
            "total_retrieval_rounds": 3,
            "total_retrieval_requests": 9,
            "rerank_pool_k": 100,
            "final_top_k": 10,
            "rerank_query_mode": "per_request",
            "candidate_selection": "evidence_balanced",
            "per_evidence_min_k": 1,
            "candidate_budget_scope": "per_round",
            "round_merge_mode": "request_rank_top1_guarded_swap",
            "dedup_mode": "legal_text_alias",
            "rerank_document_mode": "statute_and_body",
            "input_format": "koblex_background_plus_question",
            "s1_max_tokens": 4096,
            "s1_truncation_retry_max_tokens": 8192,
            "source_manifest_sha256": "b" * 64,
        }

    @staticmethod
    def _normal_harness_row(records, *, ordinal, status, configuration, snapshot):
        question_id = "q%d" % ordinal
        run_id = "normal-%d" % ordinal
        directory = records / run_id
        directory.mkdir()
        ablation._write_runtime_json(directory / "metadata.json", {
            "run_id": run_id,
            "question_id": question_id,
            "configuration": configuration,
            "source_snapshot": snapshot,
            "record_schema_version": "1.4",
            "skill_sha256": {"legal_issue_and_query_planning/SKILL.md": "a" * 64},
        })
        ablation._write_runtime_json(directory / "result.json", {
            "run_id": run_id,
            "status": status,
            "termination_reason": "INVALID_SKILL_OUTPUT" if status == "EXECUTION_FAILURE" else "COMPLETED",
        })
        return {
            "ordinal": ordinal,
            "question_id": question_id,
            "n_hops": ordinal,
            "status": status,
            "record_directory": str(directory),
            "record_result_file": str(directory / "result.json"),
            "run_id": run_id,
        }

    def test_smoke_gate_allows_durable_harness_failure_but_rejects_synthetic_or_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            records = Path(directory) / "records"
            records.mkdir()
            configuration = self._configuration()
            snapshot = {"git_commit": "c" * 40, "git_tree": "d" * 40, "source_manifest_sha256": "b" * 64}
            manifest = {"entries": [
                {"ordinal": 1, "question_id": "q1", "n_hops": 1},
                {"ordinal": 2, "question_id": "q2", "n_hops": 2},
                {"ordinal": 3, "question_id": "q3", "n_hops": 3},
            ]}
            rows = [
                self._normal_harness_row(records, ordinal=1, status="ANSWER", configuration=configuration, snapshot=snapshot),
                self._normal_harness_row(records, ordinal=2, status="ABSTAIN", configuration=configuration, snapshot=snapshot),
                self._normal_harness_row(records, ordinal=3, status="EXECUTION_FAILURE", configuration=configuration, snapshot=snapshot),
            ]
            ablation._assert_completed_rows(rows, manifest, records, configuration, snapshot)
            final = {
                "status": "COMPLETED_WITH_EXPLICIT_OUTCOMES", "entry_count": 3,
                "outcomes": ablation._outcome_counts(rows),
                "execution_failure_audit": ablation._execution_failure_audit(rows),
            }
            requirements = ablation._smoke3_gate_requirements(final, 3)
            self.assertEqual(final["execution_failure_audit"]["harness_execution_failure_count"], 1)
            self.assertTrue(ablation._smoke3_gate_policy_satisfied(final, requirements, 3))

            synthetic = ablation._synthetic_execution_failure_record(
                records, question_id="q3", record_configuration=configuration,
                source_snapshot=snapshot, error=RuntimeError("launcher failure"),
            )
            rows[2] = {"ordinal": 3, "question_id": "q3", "n_hops": 3, **synthetic}
            final["outcomes"] = ablation._outcome_counts(rows)
            final["execution_failure_audit"] = ablation._execution_failure_audit(rows)
            requirements = ablation._smoke3_gate_requirements(final, 3)
            self.assertEqual(requirements["synthetic_launcher_or_infrastructure_failure_count"], 1)
            self.assertFalse(ablation._smoke3_gate_policy_satisfied(final, requirements, 3))

            metadata = ablation.read_json(Path(rows[2]["record_directory"]) / "metadata.json")
            metadata.pop("record_kind")
            ablation._write_runtime_json(Path(rows[2]["record_directory"]) / "metadata.json", metadata)
            final["execution_failure_audit"] = ablation._execution_failure_audit(rows)
            requirements = ablation._smoke3_gate_requirements(final, 3)
            self.assertEqual(requirements["unclassified_execution_failure_count"], 1)
            self.assertFalse(ablation._smoke3_gate_policy_satisfied(final, requirements, 3))

    def test_explicit_failure_resume_prefix_is_evaluator_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "dataset.json"
            dataset.write_text(json.dumps([{
                "id": "q1", "background": "", "question": "Q", "answer": "A", "n_hops": 1,
                "contexts": [{"index": "법 1조", "hierarchy": "법 1조", "content": "내용"}],
            }]), encoding="utf-8")
            corpus = root / "corpus.jsonl"
            corpus.write_text(json.dumps({
                "provision_id": "P1", "source_index": "법 1조",
                "statute_name": "법 1조", "provision_text": "내용",
            }, ensure_ascii=False) + "\n", encoding="utf-8")
            configuration = self._configuration()
            manifest = {
                "name": "test", "source_dataset": {"path": str(dataset), "sha256": self._sha256(dataset)},
                "entries": [{"ordinal": 1, "question_id": "q1", "n_hops": 1}],
                "frozen_configuration": configuration,
                "selection": {"entry_count": 1},
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            snapshot = {"git_commit": "c" * 40, "git_tree": "d" * 40, "source_manifest_sha256": "b" * 64}
            output = root / "output"
            records, batch, rows = ablation._initialize_or_resume_output(
                output, manifest=manifest, manifest_path=manifest_path, mode="smoke3",
                asset_provenance={"assets": {}}, configuration=configuration,
                record_configuration=configuration, source_snapshot=snapshot,
                model_readiness={"status": "PASS"}, resume=False,
            )
            self.assertEqual(rows, [])
            outcome = ablation._synthetic_execution_failure_record(
                records, question_id="q1", record_configuration=configuration,
                source_snapshot=snapshot, error=RuntimeError("fixture failure"),
            )
            row = {"ordinal": 1, "source_ordinal": 1, "question_id": "q1", "n_hops": 1, **outcome}
            (batch / "summary.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
            records2, batch2, resumed = ablation._initialize_or_resume_output(
                output, manifest=manifest, manifest_path=manifest_path, mode="smoke3",
                asset_provenance={"assets": {}}, configuration=configuration,
                record_configuration=configuration, source_snapshot=snapshot,
                model_readiness={"status": "PASS"}, resume=True,
            )
            self.assertEqual((records2, batch2, len(resumed)), (records, batch, 1))
            aggregate, per_question, _metadata = evaluate_batch(
                batch, dataset, corpus, require_stage_provenance=True
            )
            self.assertEqual(per_question[0]["status"], "EXECUTION_FAILURE")
            self.assertEqual(per_question[0]["token_f1_at_800"], 0.0)
            self.assertEqual(aggregate["outcomes"]["EXECUTION_FAILURE"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
