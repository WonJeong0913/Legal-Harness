import hashlib
import json
import unittest
from pathlib import Path

from runtime.comparison_guard import validate_retriever_comparison


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAUNCH_ROOT = PROJECT_ROOT / "records/launch/kure-c5-conclusion-first-qwen38-q8-20260822"
SOURCE_FULL226 = LAUNCH_ROOT / "kure_c5_full226_20260822.json"
SMOKE8_MANIFEST = LAUNCH_ROOT / "kure_c5_seeded_direct_entailment_smoke8_20260824.json"
KURE_MANIFEST = LAUNCH_ROOT / "kure_c5_prompt_stable_deterministic_backend_full226_20260825.json"
BM25_MANIFEST = LAUNCH_ROOT / "bm25_reference_c5_prompt_stable_deterministic_backend_full226_20260825.json"
SOURCE_DATASET_SHA256 = "afdaff3a8000cdf5e0a64adbcfc8e6aff0042b318bf03718155f2b70f551c47b"



class PromptStableFull226ManifestTests(unittest.TestCase):
    @staticmethod
    def _read(path):
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _non_retriever_configuration(configuration):
        ignored = {"condition", "retriever", "retriever_provenance", "ollama_endpoint", "runtime_determinism"}
        return {key: value for key, value in configuration.items() if key not in ignored}

    def test_uses_exact_full226_source_dataset_and_ordered_entries(self):
        source = self._read(SOURCE_FULL226)
        kure = self._read(KURE_MANIFEST)
        bm25 = self._read(BM25_MANIFEST)

        self.assertEqual(len(source["entries"]), 226)
        self.assertEqual(kure["source_dataset"], source["source_dataset"])
        self.assertEqual(bm25["source_dataset"], source["source_dataset"])
        self.assertEqual(source["source_dataset"]["sha256"], SOURCE_DATASET_SHA256)
        source_path = PROJECT_ROOT / source["source_dataset"]["path"]
        self.assertEqual(
            hashlib.sha256(source_path.read_bytes()).hexdigest(), SOURCE_DATASET_SHA256
        )
        self.assertEqual(kure["entries"], source["entries"])
        self.assertEqual(bm25["entries"], source["entries"])
        self.assertEqual(kure["selection"]["entry_count"], 226)
        self.assertEqual(bm25["selection"]["entry_count"], 226)

    def test_pair_is_guard_compatible_and_records_deterministic_backend(self):
        kure = self._read(KURE_MANIFEST)
        bm25 = self._read(BM25_MANIFEST)
        smoke8 = self._read(SMOKE8_MANIFEST)

        comparison = validate_retriever_comparison(
            kure, bm25, KURE_MANIFEST, BM25_MANIFEST
        )
        self.assertEqual(comparison["status"], "VALIDATED_IDENTICAL_EXCEPT_RETRIEVER")
        self.assertEqual(comparison["entry_count"], 226)
        kure_config = kure["frozen_configuration"]
        bm25_config = bm25["frozen_configuration"]
        smoke8_config = smoke8["frozen_configuration"]
        self.assertEqual(
            self._non_retriever_configuration(kure_config),
            self._non_retriever_configuration(smoke8_config),
        )
        self.assertEqual(self._non_retriever_configuration(bm25_config), self._non_retriever_configuration(smoke8_config))
        self.assertEqual(kure_config["model"], "legal-harness-qwen38-q8")
        self.assertEqual(kure_config["seed"], 0)
        self.assertEqual(kure_config["num_ctx"], 32768)
        self.assertEqual(kure_config["ollama_endpoint"], "http://127.0.0.1:11435/api/generate")
        self.assertEqual(bm25_config["ollama_endpoint"], kure_config["ollama_endpoint"])
        self.assertEqual(
            kure_config["retriever_provenance"]["vectors_sha256"],
            "3e312dbf4cf24e7b91bc9833a9001416d85644e6868bdb657d889bd535a9d983",
        )
        self.assertEqual(
            kure_config["runtime_determinism"],
            {
                "ollama_version": "0.20.5",
                "flash_attention": False,
                "GGML_CUDA_DISABLE_GRAPHS": 1,
                "num_parallel": 1,
                "prompt_run_id_placeholder": "__HARNESS_RUN_ID__",
                "seed_forwarding": "ollama_options_seed",
            },
        )
        self.assertEqual(bm25_config["runtime_determinism"], kure_config["runtime_determinism"])
        self.assertNotIn("retriever_provenance", bm25_config)
        self.assertIn("must never be executed", bm25["purpose"].lower())
        self.assertIn("lf-eval is excluded", kure["purpose"].lower())


if __name__ == "__main__":
    unittest.main()
