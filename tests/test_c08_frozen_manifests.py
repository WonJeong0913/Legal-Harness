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
REPAIR_LIST_DEDUPE_CAPABILITIES = {
    "audit_kind": "deduplicated_repair_induced_list_values",
    "drop_scope": "only_collisions_newly_induced_by_article_neutralization",
    "fields": ["query_terms", "statute_hints"],
    "order": "stable_first",
    "raw_duplicates": "preserved_for_final_validator",
}
AXIS_CANONICAL_CAPABILITIES = {
    "allowed_tuple_projections": [
        {
            "legal_status": "covered",
            "applicability_status": "direct",
            "gap_type": "none",
            "derived_status": "covered",
            "derived_partial_kind": "not_applicable",
            "derived_governing_legal_regime": "direct_entailment",
        },
        {
            "legal_status": "covered",
            "applicability_status": "conditional",
            "gap_type": "missing_fact",
            "derived_status": "partially_covered",
            "derived_partial_kind": "factual_condition",
            "derived_governing_legal_regime": "direct_entailment",
        },
        {
            "legal_status": "partially_covered",
            "applicability_status": "not_assessed",
            "gap_type": "missing_statute",
            "derived_status": "partially_covered",
            "derived_partial_kind": "legal_support_gap",
            "derived_governing_legal_regime": "not_direct_entailment",
        },
        {
            "legal_status": "uncovered",
            "applicability_status": "not_assessed",
            "gap_type": "missing_statute",
            "derived_status": "uncovered",
            "derived_partial_kind": "not_applicable",
            "derived_governing_legal_regime": "not_direct_entailment",
        },
        {
            "legal_status": "conflicting",
            "applicability_status": "not_assessed",
            "gap_type": "conflict",
            "derived_status": "conflicting",
            "derived_partial_kind": "not_applicable",
            "derived_governing_legal_regime": "not_direct_entailment",
        },
        {
            "legal_status": "uncovered",
            "applicability_status": "not_assessed",
            "gap_type": "scope_excess",
            "scope_excess_critical": False,
            "derived_status": "uncovered",
            "derived_partial_kind": "not_applicable",
            "derived_governing_legal_regime": "not_direct_entailment",
        },
    ],
    "audit_event": "S2_LEGACY_PROJECTION_DERIVED",
    "invalid_partial_unsupported_or_semantic_tuple": "fail_closed",
    "legacy_derived_by_harness": [
        "status",
        "partial_kind",
        "governing_legal_regime",
        "missing_evidence_items",
        "evidence_conflicts",
    ],
    "no_runtime_state_or_role_union_mutation": True,
    "semantic_authority": {
        "atomic_axes": ["legal_status", "applicability_status", "gap_type"],
        "validated_with": ["criterion_results", "links", "roles"],
    },
    "scope_excess": "noncritical_only",
}


class C08FrozenManifestTests(unittest.TestCase):
    @staticmethod
    def _read(path):
        return json.loads(path.read_text(encoding="utf-8"))

    def test_all_four_manifests_bind_exact_c04_c05_c06_c08_capabilities(self):
        for path in (KURE_FULL, BM25_FULL, KURE_SMOKE, BM25_SMOKE):
            manifest = self._read(path)
            configuration = manifest["frozen_configuration"]

            self.assertEqual(manifest["manifest_schema_version"], "1.0")
            self.assertIn("c08-s1-repair-list-dedupe-v1", manifest["name"])
            self.assertIn("c06-s2-axis-canonical-projection-v1", manifest["name"])
            self.assertIn("c08", manifest["purpose"].lower())
            self.assertIn("c06", manifest["purpose"].lower())
            self.assertIn("BM25 is reference-only", manifest["purpose"])
            self.assertIn("must never be executed", manifest["purpose"].lower())
            for release in (
                "c04-core-auxiliary-roles-v1",
                "c05-repair-collision-failsafe-v1",
                "c06-s2-axis-canonical-projection-v1",
                "c08-s1-repair-list-dedupe-v1",
                "s1-neutral-single-issue-fusion-top10",
            ):
                self.assertIn(release, configuration["condition"])
            self.assertEqual(configuration["evidence_role_contract"], "c04_core_auxiliary_roles_v1")
            self.assertEqual(configuration["evidence_role_capabilities"], EVIDENCE_ROLE_CAPABILITIES)
            self.assertEqual(configuration["repair_collision_contract"], "c05_repair_collision_failsafe_v1")
            self.assertEqual(configuration["repair_collision_capabilities"], REPAIR_COLLISION_CAPABILITIES)
            self.assertEqual(
                configuration["s2_axis_canonical_projection_contract"],
                "c06_s2_axis_canonical_projection_v1",
            )
            self.assertEqual(
                configuration["s2_axis_canonical_projection_capabilities"],
                AXIS_CANONICAL_CAPABILITIES,
            )
            self.assertEqual(
                configuration["repair_induced_retrieval_list_dedupe_contract"],
                "c08_repair_induced_retrieval_list_dedupe_v1",
            )
            self.assertEqual(
                configuration["repair_induced_retrieval_list_dedupe_capabilities"],
                REPAIR_LIST_DEDUPE_CAPABILITIES,
            )
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

    def test_kure_only_policy_lineage_hashes_and_pair_guard(self):
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
                "full226_execution_failure_collection": "EXPLICIT_ZERO_SCORED_TERMINAL_RECORD_CONTINUES_COLLECTION",
                "lf_eval_score_injection": "FORBIDDEN",
                "network": "OFFLINE_ONLY",
                "parser_execution": "FORBIDDEN",
                "primary_retriever": "kure",
                "repair_collision_failsafe": "REQUIRED",
                "repair_induced_list_dedupe": "REQUIRED",
                "s2_axis_canonical_projection": "REQUIRED",
            },
        )
        self.assertEqual(metadata["lineage"]["c04_evidence_role_contract"], "c04_core_auxiliary_roles_v1")
        self.assertEqual(metadata["lineage"]["c05_source_commit"], "b27024cd15bf2692345670865c754608784ed7c4")
        self.assertEqual(metadata["lineage"]["c05_source_tree"], "797897a99ec9e3da622aa313ce4bb3616c179423")
        self.assertEqual(metadata["lineage"]["c06_protocol_commit"], "3ab2388881322d9f08dc001e9a3764472cc89343")
        self.assertEqual(metadata["lineage"]["c06_implementation_commit"], "3569f8d44dc57ddb49c4fbb9e43f540e308cd17c")
        self.assertEqual(metadata["lineage"]["c08_candidate_commit"], "6ae1f3c13aafbd1c23ba7106f8f9d9d96aab04db")
        self.assertEqual(metadata["lineage"]["c08_candidate_tree"], "bb102d7728512b803973c02769b171d78975b273")
        self.assertEqual(metadata["repair_collision_contract"], REPAIR_COLLISION_CAPABILITIES)
        self.assertEqual(
            metadata["repair_induced_retrieval_list_dedupe_contract"],
            {"contract": "c08_repair_induced_retrieval_list_dedupe_v1", **REPAIR_LIST_DEDUPE_CAPABILITIES},
        )
        self.assertEqual(
            metadata["s2_axis_canonical_projection_contract"],
            {
                "contract": "c06_s2_axis_canonical_projection_v1",
                "audit_event": "S2_LEGACY_PROJECTION_DERIVED",
                "invalid_partial_unsupported_or_semantic_tuple": "fail_closed",
                "legacy_derived_by_harness": AXIS_CANONICAL_CAPABILITIES["legacy_derived_by_harness"],
                "no_runtime_state_or_role_union_mutation": True,
                "scope_excess": "noncritical_only",
            },
        )
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

        self.assertEqual(self._read(KURE_FULL)["selection"]["execution_role"], "PRIMARY_KURE_EXECUTION")
        self.assertEqual(self._read(KURE_SMOKE)["selection"]["execution_role"], "OPERATIONAL_SMOKE_ONLY_NOT_BENCHMARK_EVIDENCE")

    def test_exactly_three_skills_keep_s1_s2_s3_order(self):
        expected = [
            "legal_issue_and_query_planning",
            "provision_coverage_assessment",
            "grounded_legal_answer_generation",
        ]
        self.assertEqual(
            sorted(path.name for path in (PROJECT_ROOT / "skills").iterdir() if path.is_dir()),
            sorted(expected),
        )
        self.assertEqual(list(SKILL_DIRECTORIES), expected)


if __name__ == "__main__":
    unittest.main()
