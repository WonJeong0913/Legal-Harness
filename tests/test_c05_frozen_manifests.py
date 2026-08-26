import hashlib
import json
from pathlib import Path
import unittest

from harness.skill_registry import SKILL_DIRECTORIES
from runtime.comparison_guard import validate_retriever_comparison


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FROZEN_ROOT = PROJECT_ROOT / "frozen_manifests"
KURE_FULL = FROZEN_ROOT / "v2_kure_full226.json"
BM25_FULL = FROZEN_ROOT / "v2_bm25_reference_full226.json"
KURE_SMOKE = FROZEN_ROOT / "v2_kure_smoke3.json"
BM25_SMOKE = FROZEN_ROOT / "v2_bm25_reference_smoke3.json"
SOURCE_METADATA = FROZEN_ROOT / "source_metadata.json"

EVIDENCE_ROLE_CAPABILITIES = {
    "accepted_provision_ids": "authorized_union",
    "direct_entailment_coverage_gate": "accepted_core_only",
    "official_provision_scoring": "core_only",
}
REPAIR_COLLISION_CAPABILITIES = {
    "all_dropped": "existing_limited_or_abstain_no_state_mutation",
    "bounded_neutral_replan": 1,
    "mixed": "novel_only_dispatch",
    "raw_history_duplicate": "invalid",
    "repair_induced_history_collision": "typed_recovery",
}


class C05FrozenManifestTests(unittest.TestCase):
    @staticmethod
    def _read(path):
        return json.loads(path.read_text(encoding="utf-8"))

    def test_all_four_manifests_are_c05_with_c04_role_lineage_and_collision_failsafe(self):
        for path in (KURE_FULL, BM25_FULL, KURE_SMOKE, BM25_SMOKE):
            manifest = self._read(path)
            configuration = manifest["frozen_configuration"]

            self.assertEqual(manifest["manifest_schema_version"], "1.0")
            self.assertIn("c05-repair-collision-failsafe-v1", manifest["name"])
            self.assertIn("c05", manifest["purpose"].lower())
            self.assertIn("c04 core/auxiliary", manifest["purpose"].lower())
            self.assertIn("c05-repair-collision-failsafe-v1", configuration["condition"].lower())
            self.assertIn("c04-core-auxiliary-roles-v1", configuration["condition"])
            self.assertIn("s1-neutral-single-issue-fusion-top10", configuration["condition"])
            self.assertEqual(configuration["evidence_role_contract"], "c04_core_auxiliary_roles_v1")
            self.assertEqual(configuration["evidence_role_capabilities"], EVIDENCE_ROLE_CAPABILITIES)
            self.assertEqual(configuration["repair_collision_contract"], "c05_repair_collision_failsafe_v1")
            self.assertEqual(configuration["repair_collision_capabilities"], REPAIR_COLLISION_CAPABILITIES)
            self.assertEqual(
                configuration["contextual_query_dedup"],
                "same_output_after_context_history_duplicate_invalid",
            )
            self.assertEqual(configuration["round_merge_mode"], "single_issue_fusion_top_k")
            self.assertEqual(configuration["candidate_selection"], "evidence_balanced")
            self.assertEqual(configuration["final_top_k"], 10)
            self.assertEqual(configuration["model"], "legal-harness-qwen38-q8")
            self.assertEqual(configuration["seed"], 0)
            self.assertEqual(configuration["num_ctx"], 32768)
            self.assertEqual(configuration["total_retrieval_rounds"], 3)
            self.assertEqual(configuration["total_retrieval_requests"], 9)
            self.assertEqual(configuration["model_provenance"]["alias"], "legal-harness-qwen38-q8")
            self.assertEqual(configuration["model_provenance"]["quantization"], "Q8_0")
            self.assertEqual(configuration["runtime_determinism"]["seed_forwarding"], "ollama_options_seed")
            self.assertEqual(configuration["runtime_determinism"]["num_parallel"], 1)
            self.assertIn("lf-eval", manifest["purpose"].lower())
            self.assertIn("parser", manifest["purpose"].lower())

    def test_full_and_smoke_orders_are_frozen_and_paired(self):
        kure_full = self._read(KURE_FULL)
        bm25_full = self._read(BM25_FULL)
        kure_smoke = self._read(KURE_SMOKE)
        bm25_smoke = self._read(BM25_SMOKE)

        self.assertEqual(kure_full["entries"], bm25_full["entries"])
        self.assertEqual(len(kure_full["entries"]), 226)
        self.assertEqual([entry["ordinal"] for entry in kure_full["entries"]], list(range(1, 227)))
        self.assertEqual(kure_smoke["entries"], bm25_smoke["entries"])
        self.assertEqual([entry["ordinal"] for entry in kure_smoke["entries"]], [1, 2, 3])
        self.assertEqual([entry["source_ordinal"] for entry in kure_smoke["entries"]], [1, 5, 16])
        self.assertEqual([entry["n_hops"] for entry in kure_smoke["entries"]], [1, 2, 3])
        for smoke_entry in kure_smoke["entries"]:
            source_entry = kure_full["entries"][smoke_entry["source_ordinal"] - 1]
            self.assertEqual(smoke_entry["question_id"], source_entry["question_id"])
            self.assertEqual(smoke_entry["n_hops"], source_entry["n_hops"])

    def test_kure_primary_bm25_reference_only_and_metadata_hashes(self):
        metadata = self._read(SOURCE_METADATA)
        expected_hash_paths = {
            "full": KURE_FULL,
            "reference": BM25_FULL,
            "smoke": KURE_SMOKE,
            "smoke_reference": BM25_SMOKE,
        }
        self.assertEqual(
            metadata["execution_policy"],
            {
                "bm25_execution": "FORBIDDEN",
                "lf_eval_score_injection": "FORBIDDEN",
                "network": "OFFLINE_ONLY",
                "parser_execution": "FORBIDDEN",
                "primary_retriever": "kure",
                "repair_collision_failsafe": "REQUIRED",
            },
        )
        self.assertEqual(metadata["lineage"]["c04_evidence_role_contract"], "c04_core_auxiliary_roles_v1")
        self.assertEqual(metadata["lineage"]["c05_source_commit"], "b27024cd15bf2692345670865c754608784ed7c4")
        self.assertEqual(metadata["lineage"]["c05_source_tree"], "797897a99ec9e3da622aa313ce4bb3616c179423")
        self.assertEqual(metadata["repair_collision_contract"], REPAIR_COLLISION_CAPABILITIES)
        for label, path in expected_hash_paths.items():
            generated = metadata["generated"][label]
            self.assertEqual(generated["path"], str(path.relative_to(PROJECT_ROOT)))
            self.assertEqual(generated["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())

        for kure_path, bm25_path in ((KURE_FULL, BM25_FULL), (KURE_SMOKE, BM25_SMOKE)):
            kure = self._read(kure_path)
            bm25 = self._read(bm25_path)
            comparison = validate_retriever_comparison(kure, bm25, kure_path, bm25_path)
            self.assertEqual(comparison["status"], "VALIDATED_IDENTICAL_EXCEPT_RETRIEVER")
            self.assertEqual(kure["frozen_configuration"]["retriever"], "kure")
            self.assertIn("retriever_provenance", kure["frozen_configuration"])
            self.assertEqual(bm25["frozen_configuration"]["retriever"], "bm25")
            self.assertNotIn("retriever_provenance", bm25["frozen_configuration"])
            self.assertEqual(bm25["selection"]["execution_role"], "COMPARISON_REFERENCE_ONLY_MUST_NEVER_BE_EXECUTED")
            self.assertIn("must never be executed", bm25["purpose"].lower())

        kure_full = self._read(KURE_FULL)
        self.assertEqual(kure_full["selection"]["execution_role"], "PRIMARY_KURE_EXECUTION")
        self.assertEqual(self._read(KURE_SMOKE)["selection"]["execution_role"], "OPERATIONAL_SMOKE_ONLY_NOT_BENCHMARK_EVIDENCE")

    def test_exactly_three_skills_keep_the_s1_s2_s3_order(self):
        skill_root = PROJECT_ROOT / "skills"
        self.assertEqual(
            sorted(path.name for path in skill_root.iterdir() if path.is_dir()),
            sorted([
                "legal_issue_and_query_planning",
                "provision_coverage_assessment",
                "grounded_legal_answer_generation",
            ]),
        )
        self.assertEqual(
            list(SKILL_DIRECTORIES),
            [
                "legal_issue_and_query_planning",
                "provision_coverage_assessment",
                "grounded_legal_answer_generation",
            ],
        )


if __name__ == "__main__":
    unittest.main()
