import json
import tempfile
from unittest.mock import patch
import importlib.util
from pathlib import Path
import unittest

from scripts import v2_kure_orchestration as v2

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("linked_bm25s_lf_eval_test", ROOT / "scripts" / "run_adapted_local_lf_eval_bm25s.py")
adapter = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(adapter)


class LinkedBm25sLFEvalTests(unittest.TestCase):
    def test_stale_legacy_metadata_aggregate_hash_is_explicit_warning(self):
        warning = adapter.metadata_aggregate_warning({"aggregate_sha256": "old"}, "actual")
        self.assertEqual(warning["code"], "LEGACY_METADATA_AGGREGATE_SHA256_STALE")
        self.assertIn("receipt.json", warning["handling"])
        self.assertIsNone(adapter.metadata_aggregate_warning({"aggregate_sha256": "actual"}, "actual"))

    def test_bm25s_configuration_requires_parser_parity_contract(self):
        config = {
            "model": v2.EXPECTED_RUNTIME["model"], "ollama_endpoint": v2.EXPECTED_RUNTIME["endpoint"], "seed": 0,
            "retriever": "bm25s_parser", "model_provenance": dict(v2.QWEN_MODEL_PROVENANCE),
            "retriever_provenance": {"backend": "bm25s.BM25", "bm25s_version": "0.3.10",
                "corpus_tokenization": "bm25s.tokenize(corpus, stopwords='en')", "query_tokenization": "bm25s.tokenize([query])",
                "top_k": 100, "first_stage_provision_id_deduplication": "FORBIDDEN", "fts5_query_expansion": "FORBIDDEN",
                "statute_hint_recall_channel": "FORBIDDEN"},
        }
        adapter._configuration(config)
        config["retriever_provenance"]["top_k"] = 99
        with self.assertRaisesRegex(adapter.LinkedB25sLFEvalError, "top_k"):
            adapter._configuration(config)

    def test_execution_failure_is_unjudged_without_candidate(self):
        summary = {"status": "EXECUTION_FAILURE", "run_id": "r"}
        result = {"status": "EXECUTION_FAILURE", "run_id": "r", "answer": None, "candidate_answer": None,
                  "candidate_answer_status": None, "candidate_answer_basis": None}
        outcome = adapter._status_answer(result, summary, "q")
        self.assertIsNone(outcome["published_answer"])
        self.assertIsNone(outcome["candidate_answer"])


    def test_linked_writer_metadata_uses_actual_aggregate_file_sha(self):
        zero = {
            "status": "EXECUTION_FAILURE",
            "public_answer": {"available": False, "channel": "public_answer", "judge_invoked": False, "score_1_to_10": None, "end_to_end_score_0_to_10": 0},
            "candidate_answer": {"available": False, "channel": "candidate_answer", "judge_invoked": False, "score_1_to_10": None, "end_to_end_score_0_to_10": 0},
        }
        baseline = {condition: {"q": dict(zero)} for condition in adapter.BASELINE_CONDITIONS}
        outcome = {"q": {"status": "EXECUTION_FAILURE", "published_answer": None, "candidate_answer": None,
                           "candidate_answer_status": None, "candidate_answer_basis": None}}
        provenance = {"dataset_sha256": adapter.EXPECTED_DATASET_SHA256, "input_bundle_sha256": "bundle"}
        configuration = {"model": v2.EXPECTED_RUNTIME["model"]}
        gold = {"q": {"input": "Q", "expected_output": "A", "context": ["C"]}}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            with patch.object(adapter, "load_bm25s_condition", return_value=(["q"], outcome, provenance, configuration)), patch.object(
                adapter, "load_immutable_baseline", return_value=(baseline, {"receipt_sha256": "receipt"}, [])
            ), patch.object(adapter.base, "load_gold_items", return_value=gold), patch.object(
                adapter.base, "_verify_judge", return_value={"ready": True}
            ):
                adapter.run_linked_bm25s_lf_eval(Path("/input-a"), Path("/input-b"), Path("/dataset"), output)
            metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["aggregate_sha256"], adapter.base.sha256(output / "aggregate.json"))
            self.assertEqual(metadata["canonical_aggregate_sha256"], adapter.base.canonical_sha256(json.loads((output / "aggregate.json").read_text(encoding="utf-8"))))


if __name__ == "__main__":
    unittest.main()
