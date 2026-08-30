import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_module(name, relative):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


orchestration = load_module("c24_v2_kure_orchestration", "scripts/v2_kure_orchestration.py")
launcher = load_module("c24_launch_v2_kure_tmux", "scripts/launch_v2_kure_tmux.py")


def configuration(retriever="kure"):
    value = {
        "condition": "fixture-%s-full226" % retriever,
        "retriever": retriever,
        "model": orchestration.EXPECTED_RUNTIME["model"],
        "seed": 0,
        "num_ctx": 32768,
        "ollama_endpoint": orchestration.EXPECTED_RUNTIME["endpoint"],
        "runtime_determinism": {"num_parallel": 1, "seed_forwarding": "ollama_options_seed"},
        "model_provenance": dict(orchestration.QWEN_MODEL_PROVENANCE),
    }
    value["round_merge_mode"] = orchestration.DIAGNOSTIC21_RUNTIME_ROUND_MERGE_MODE
    if retriever == "kure":
        value["retriever_provenance"] = {
            "model_id": "fixture-kure",
            "normalized_corpus_path": "data/kure/corpus.jsonl",
            "vectors_path": "data/kure/vectors.f32.npy",
            "provision_ids_path": "data/kure/provision_ids.txt",
            "model_path": "models/huggingface/fixture-kure",
        }
    return value


def diagnostic_sources():
    entries = [
        {"ordinal": ordinal, "question_id": "fixture_%03d" % ordinal, "n_hops": ((ordinal - 1) % 3) + 1}
        for ordinal in range(1, orchestration.TOTAL_FULL226 + 1)
    ]
    for source_ordinal, question_id in orchestration.DIAGNOSTIC21_ROSTER:
        item = entries[source_ordinal - 1]
        item["question_id"] = question_id
        item["n_hops"] = int(question_id.split("_")[2].removesuffix("hop"))
    primary = {
        "name": "source-primary",
        "source_dataset": {"path": "data/fixture.parquet", "sha256": "a" * 64},
        "frozen_configuration": configuration(),
        "entries": entries,
    }
    reference = {
        "name": "source-reference",
        "source_dataset": {"path": "data/fixture.parquet", "sha256": "a" * 64},
        "frozen_configuration": configuration("bm25"),
        "entries": [dict(entry) for entry in entries],
    }
    return primary, reference


def diagnostic_manifests():
    primary, reference = diagnostic_sources()
    return orchestration.build_diagnostic21_manifests(
        primary,
        reference,
        orchestration.DIAGNOSTIC21_SOURCE_PRIMARY_SHA256,
        orchestration.DIAGNOSTIC21_SOURCE_REFERENCE_SHA256,
    )


def paired_c02_answer_cohort_metric(score=None):
    score = (
        orchestration.DIAGNOSTIC21_BASELINE["token_f1_answered_only"]
        if score is None else score
    )
    return {
        "definition": "mean current token_f1_at_800 over the predeclared C02 ANSWER cohort",
        "denominator": orchestration.DIAGNOSTIC21_ANSWER_YIELD_MINIMUM,
        "frozen_cohort_file": orchestration.DIAGNOSTIC21_C02_ANSWER_COHORT_FILE,
        "frozen_cohort_sha256": orchestration.DIAGNOSTIC21_C02_ANSWER_COHORT_SHA256,
        "provenance": dict(orchestration.DIAGNOSTIC21_C02_ANSWER_COHORT_PROVENANCE),
        "rows": [
            {"question_id": row["question_id"], "status": "ANSWER", "token_f1_at_800": score}
            for row in orchestration.DIAGNOSTIC21_C02_ANSWER_COHORT_ROWS
        ],
        "token_f1_at_800": score,
    }


def passing_metrics():
    return {
        "execution_failure_count": 0,
        "answer_count": 4,
        "abstain_count": 17,
        "citation_integrity": {"attempted": 4, "passed": 4, "pass_rate": 1.0},
        "paired_c02_answer_cohort": paired_c02_answer_cohort_metric(),
        **orchestration.DIAGNOSTIC21_NONREGRESSION_MINIMUMS,
    }


def passing_event():
    return {
        "checkpoint_status": "PASS",
        "completed_questions": 21,
        "validation_errors": [],
        "stage_provenance_missing": [],
        "public_abstain_missing_result_question_ids": [],
        "public_abstain_invalid_result_question_ids": [],
        "public_abstain_leak_question_ids": [],
        "bm25_execution": "FORBIDDEN",
        "lf_eval_score_injection": "FORBIDDEN",
        "metrics": passing_metrics(),
    }


class Diagnostic21ManifestTests(unittest.TestCase):
    def test_exact_roster_hash_cohorts_lineage_and_bge_metadata_are_frozen(self):
        manifests = diagnostic_manifests()
        primary, reference = manifests["diagnostic21"], manifests["diagnostic21_reference"]
        orchestration.assert_diagnostic21_manifest_integrity(primary, reference)
        self.assertEqual(
            [(entry["source_ordinal"], entry["question_id"]) for entry in primary["entries"]],
            list(orchestration.DIAGNOSTIC21_ROSTER),
        )
        self.assertEqual([entry["ordinal"] for entry in primary["entries"]], list(range(1, 22)))
        self.assertEqual(
            primary["selection"]["cohort_counts"], orchestration.DIAGNOSTIC21_COHORT_COUNTS
        )
        self.assertEqual(
            primary["selection"]["roster_sha256"],
            orchestration.canonical_sha256({"roster": primary["selection"]["roster"]}),
        )
        self.assertEqual(primary["selection"]["condition_lineage"], orchestration.DIAGNOSTIC21_CONDITION_LINEAGE)
        self.assertEqual(
            primary["selection"]["condition_lineage"]["C25_C29_full_commit_lineage"],
            [
                "782e042eb986db88e37e35f0ba10556dfcfe7efe",
                "82ddba012d29ac8f497af2fa1e34f0c6241dc3ef",
                "64b3a11f1edb65a512f2c0487ebb3bf60aaa540e",
                "54d94d9f6c87a06a25d58cf162bc2f30c20f6a6f",
                "55d6a808eecf147372fec5f769d103497a608b13",
                "e6dfff14342b57b6cda4c3f1a37a333e6546b68f",
                "a604967a35649a6a5f5ccbbb59750f3ca594ec0b",
            ],
        )
        self.assertEqual(primary["selection"]["skill_files"], orchestration.DIAGNOSTIC21_SKILL_FILES)
        self.assertEqual(
            primary["selection"]["skill_files"],
            {
                "S1": {
                    "skill_path": "skills/legal_issue_and_query_planning/SKILL.md",
                    "skill_sha256": "6fc4008c72afd0a7e7d58f9214dee1eaa8af56de9c3ade5c920fb73d74f84094",
                    "validator_path": "skills/legal_issue_and_query_planning/scripts/validate_output.py",
                    "validator_sha256": "e1db2ec6a07fbac84a84280caaafc3ab1e95d912cec9ccc4a911382f84d9caba",
                },
                "S2": {
                    "skill_path": "skills/provision_coverage_assessment/SKILL.md",
                    "skill_sha256": "a1d0ede5f6d049e975b356e7325d4a6aef1122db33d023a34cf6f59c45d96e95",
                    "validator_path": "skills/provision_coverage_assessment/scripts/validate_output.py",
                    "validator_sha256": "2d63bd38df2b7b5eb57009b6c056908339aeee4f5f9eee4ad987405841c3b619",
                },
                "S3": {
                    "skill_path": "skills/grounded_legal_answer_generation/SKILL.md",
                    "skill_sha256": "a146c3c7a0910c43d3d0f84a7f347e747a193a5ba88dcf7af50a800379735eac",
                    "contract_path": "skills/grounded_legal_answer_generation/references/contract.md",
                    "contract_sha256": "f7a2760eb9a5a7aaefd09da4f1a322b90d4825bc25d78f9600fa79b0e71d083a",
                    "input_schema_path": "skills/grounded_legal_answer_generation/references/input.schema.json",
                    "input_schema_sha256": "575583d54580687f0d23e6adecf0d3a0f2dc3d5f0d3eacbad2dc010480daa527",
                    "validator_path": "skills/grounded_legal_answer_generation/scripts/validate_output.py",
                    "validator_sha256": "4b427f3232cd947a9678d68323f547bc0dcae7e03a2a26c2e6dbd0b9186462bd",
                },
            },
        )
        self.assertEqual(primary["selection"]["reranker_provenance"], orchestration.DIAGNOSTIC21_RERANKER_PROVENANCE)
        self.assertEqual(primary["selection"]["candidate_id"], orchestration.DIAGNOSTIC21_CANDIDATE_ID)
        self.assertEqual(primary["selection"]["c22_capability"], orchestration.DIAGNOSTIC21_C22_CAPABILITY)
        self.assertEqual(
            primary["selection"]["c28_capabilities"],
            orchestration.DIAGNOSTIC21_C28_CAPABILITIES,
        )
        self.assertEqual(
            primary["selection"]["c29_capabilities"],
            orchestration.DIAGNOSTIC21_C29_CAPABILITIES,
        )
        self.assertEqual(
            primary["selection"]["c30_capabilities"],
            orchestration.DIAGNOSTIC21_C30_CAPABILITIES,
        )
        self.assertEqual(
            primary["selection"]["c30_source_provenance"],
            orchestration.DIAGNOSTIC21_C30_SOURCE_PROVENANCE,
        )
        self.assertEqual(primary["selection"]["semantic_authority"], orchestration.DIAGNOSTIC21_SEMANTIC_AUTHORITY)
        self.assertEqual(
            primary["selection"]["c31_capabilities"],
            orchestration.DIAGNOSTIC21_C31_CAPABILITIES,
        )
        self.assertEqual(
            primary["selection"]["c31_source_provenance"],
            orchestration.DIAGNOSTIC21_C31_SOURCE_PROVENANCE,
        )
        self.assertEqual(primary["selection"]["c32_capabilities"], orchestration.DIAGNOSTIC21_C32_CAPABILITIES)
        self.assertEqual(primary["selection"]["c32_source_provenance"], orchestration.DIAGNOSTIC21_C32_SOURCE_PROVENANCE)
        self.assertEqual(primary["selection"]["c33_capabilities"], orchestration.DIAGNOSTIC21_C33_CAPABILITIES)
        self.assertEqual(primary["selection"]["c33_source_provenance"], orchestration.DIAGNOSTIC21_C33_SOURCE_PROVENANCE)
        self.assertEqual(primary["selection"]["c34_capabilities"], orchestration.DIAGNOSTIC21_C34_CAPABILITIES)
        self.assertEqual(primary["selection"]["c34_source_provenance"], orchestration.DIAGNOSTIC21_C34_SOURCE_PROVENANCE)
        self.assertEqual(primary["selection"]["c35_capabilities"], orchestration.DIAGNOSTIC21_C35_CAPABILITIES)
        self.assertEqual(primary["selection"]["c35_source_provenance"], orchestration.DIAGNOSTIC21_C35_SOURCE_PROVENANCE)
        self.assertEqual(primary["selection"]["c36_capabilities"], orchestration.DIAGNOSTIC21_C36_CAPABILITIES)
        self.assertEqual(primary["selection"]["c36_source_provenance"], orchestration.DIAGNOSTIC21_C36_SOURCE_PROVENANCE)
        self.assertEqual(primary["selection"]["c37_capabilities"], orchestration.DIAGNOSTIC21_C37_CAPABILITIES)
        self.assertEqual(primary["selection"]["c37_source_provenance"], orchestration.DIAGNOSTIC21_C37_SOURCE_PROVENANCE)
        self.assertEqual(primary["selection"]["c38_capabilities"], orchestration.DIAGNOSTIC21_C38_CAPABILITIES)
        self.assertEqual(primary["selection"]["c38_source_provenance"], orchestration.DIAGNOSTIC21_C38_SOURCE_PROVENANCE)
        self.assertEqual(primary["selection"]["c39_capabilities"], orchestration.DIAGNOSTIC21_C39_CAPABILITIES)
        self.assertEqual(primary["selection"]["c39_source_provenance"], orchestration.DIAGNOSTIC21_C39_SOURCE_PROVENANCE)
        self.assertEqual(primary["selection"]["c40_capabilities"], orchestration.DIAGNOSTIC21_C40_CAPABILITIES)
        self.assertEqual(primary["selection"]["c40_source_provenance"], orchestration.DIAGNOSTIC21_C40_SOURCE_PROVENANCE)
        self.assertEqual(primary["selection"]["c41_capabilities"], orchestration.DIAGNOSTIC21_C41_CAPABILITIES)
        self.assertEqual(primary["selection"]["c41_source_provenance"], orchestration.DIAGNOSTIC21_C41_SOURCE_PROVENANCE)
        self.assertEqual(
            primary["selection"]["runtime_artifact_path_provenance"]["qwen_ollama_blob_exact_local_runtime_exception"],
            orchestration.QWEN_MODEL_PROVENANCE["ollama_model_blob"],
        )
        self.assertFalse(primary["selection"]["round_merge_provenance"]["equivalence_claimed"])
        self.assertEqual(primary["selection"]["round_merge_provenance"]["c02_saved_stage_round_merge_mode"], "request_rank_top1_guarded_swap")
        self.assertEqual(primary["name"], "v2-kure-qwen38-q8-offline-diagnostic21-c41-20260830")
        self.assertEqual(reference["name"], "v2-bm25-reference-qwen38-q8-offline-diagnostic21-c41-20260830")
        self.assertEqual(
            primary["frozen_configuration"]["condition"],
            "fixture-kure-full226" + orchestration.DIAGNOSTIC21_C30_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C31_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C32_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C33_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C34_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C35_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C36_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C37_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C38_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C39_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C40_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C41_CONDITION_SUFFIX,
        )
        self.assertEqual(
            reference["frozen_configuration"]["condition"],
            "fixture-bm25-full226" + orchestration.DIAGNOSTIC21_C30_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C31_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C32_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C33_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C34_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C35_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C36_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C37_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C38_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C39_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C40_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C41_CONDITION_SUFFIX,
        )
        self.assertEqual(
            primary["selection"]["source_frozen_conditions"],
            {
                "primary": "fixture-kure-full226" + orchestration.DIAGNOSTIC21_C30_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C31_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C32_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C33_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C34_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C35_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C36_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C37_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C38_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C39_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C40_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C41_CONDITION_SUFFIX,
                "reference": "fixture-bm25-full226" + orchestration.DIAGNOSTIC21_C30_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C31_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C32_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C33_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C34_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C35_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C36_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C37_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C38_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C39_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C40_CONDITION_SUFFIX + orchestration.DIAGNOSTIC21_C41_CONDITION_SUFFIX,
            },
        )
        self.assertEqual(
            primary["selection"]["implementation_parent_commit"],
            "d1e78712d16ceea07d279b3cd9abc024b9e8515f",
        )
        self.assertIn("C41 adds a two-primary-attempt-only", primary["selection"]["method"])
        self.assertIn("C41 adds a two-primary-attempt-only", primary["purpose"])
        self.assertEqual(primary["frozen_configuration"].get("s3_public_answer_max_claims"), 4)
        self.assertEqual(primary["frozen_configuration"].get("s3_public_answer_format"), "conclusion_first_1_to_4_short_sentences")
        self.assertEqual(primary["frozen_configuration"]["reranker_provenance"], orchestration.DIAGNOSTIC21_RERANKER_PROVENANCE)
        self.assertEqual(reference["frozen_configuration"]["reranker_provenance"], orchestration.DIAGNOSTIC21_RERANKER_PROVENANCE)
        self.assertEqual(primary["frozen_configuration"]["retriever"], "kure")
        self.assertEqual(reference["frozen_configuration"]["retriever"], "bm25")
        self.assertIn("No BM25, ParSeR, or LF-Eval execution", primary["purpose"])

    def test_integrity_rejects_roster_and_policy_metadata_tampering(self):
        manifests = diagnostic_manifests()
        primary = json.loads(json.dumps(manifests["diagnostic21"]))
        reference = json.loads(json.dumps(manifests["diagnostic21_reference"]))
        primary["selection"]["cohort_counts"] = {"execution_failure": 9}
        with self.assertRaisesRegex(orchestration.OrchestrationError, "cohort count"):
            orchestration.assert_diagnostic21_manifest_integrity(primary, reference)
        primary = json.loads(json.dumps(manifests["diagnostic21"]))
        primary["frozen_configuration"]["reranker_provenance"]["device"] = "cpu"
        with self.assertRaisesRegex(orchestration.OrchestrationError, "reranker provenance"):
            orchestration.assert_diagnostic21_manifest_integrity(primary, reference)
        primary = json.loads(json.dumps(manifests["diagnostic21"]))
        reference = json.loads(json.dumps(manifests["diagnostic21_reference"]))
        reference["entries"][0]["diagnostic_cohort"] = "execution_failure"
        with self.assertRaisesRegex(orchestration.OrchestrationError, "entries differ"):
            orchestration.assert_diagnostic21_manifest_integrity(primary, reference)

        primary = json.loads(json.dumps(manifests["diagnostic21"]))
        reference = json.loads(json.dumps(manifests["diagnostic21_reference"]))
        primary["selection"]["c30_capabilities"]["c30_paired_c02_answer_cohort_gate"]["cohort_count"] = 5
        with self.assertRaisesRegex(orchestration.OrchestrationError, "C30 capability"):
            orchestration.assert_diagnostic21_manifest_integrity(primary, reference)

        primary = json.loads(json.dumps(manifests["diagnostic21"]))
        reference = json.loads(json.dumps(manifests["diagnostic21_reference"]))
        primary["frozen_configuration"]["condition"] = "fixture-kure"
        primary["selection"]["source_frozen_conditions"]["primary"] = "fixture-kure"
        with self.assertRaisesRegex(orchestration.OrchestrationError, "C30/C31/C32/C33/C34/C35/C36/C37/C38/C39/C40 source condition overlay"):
            orchestration.assert_diagnostic21_manifest_integrity(primary, reference)

    def test_generated_manifests_match_tracked_frozen_manifests_and_record_c30_provenance(self):
        primary_source = orchestration.read_json(PROJECT_ROOT / "frozen_manifests/v2_kure_full226.json")
        reference_source = orchestration.read_json(PROJECT_ROOT / "frozen_manifests/v2_bm25_reference_full226.json")
        c41_sources = orchestration.build_v2_manifests(primary_source, reference_source)
        generated = orchestration.build_diagnostic21_manifests(
            c41_sources["full"],
            c41_sources["reference"],
            orchestration.DIAGNOSTIC21_SOURCE_PRIMARY_SHA256,
            orchestration.DIAGNOSTIC21_SOURCE_REFERENCE_SHA256,
        )
        orchestration.assert_diagnostic21_manifest_integrity(generated["diagnostic21"], generated["diagnostic21_reference"])
        self.assertNotIn("/workspace", json.dumps(generated, ensure_ascii=False))
        tracked_primary = orchestration.read_json(
            PROJECT_ROOT / "frozen_manifests/v2_kure_diagnostic21.json"
        )
        tracked_reference = orchestration.read_json(
            PROJECT_ROOT / "frozen_manifests/v2_bm25_reference_diagnostic21.json"
        )
        self.assertEqual(generated["diagnostic21"], tracked_primary)
        self.assertEqual(generated["diagnostic21_reference"], tracked_reference)
        self.assertNotIn("/workspace", json.dumps(tracked_primary, ensure_ascii=False))
        self.assertNotIn("/workspace", json.dumps(tracked_reference, ensure_ascii=False))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            orchestration.write_v2_manifests(
                root,
                PROJECT_ROOT / "frozen_manifests/v2_kure_full226.json",
                PROJECT_ROOT / "frozen_manifests/v2_bm25_reference_full226.json",
            )
            source_metadata = orchestration.read_json(root / "frozen_manifests/source_metadata.json")
            emitted_cohort = orchestration.load_frozen_c02_answer_cohort(root)
            self.assertEqual(emitted_cohort, orchestration.DIAGNOSTIC21_C02_ANSWER_COHORT)
            self.assertEqual(
                orchestration.sha256(root / orchestration.DIAGNOSTIC21_C02_ANSWER_COHORT_FILE),
                orchestration.DIAGNOSTIC21_C02_ANSWER_COHORT_SHA256,
            )
        self.assertEqual(
            source_metadata["diagnostic21"]["c30_capabilities"],
            orchestration.DIAGNOSTIC21_C30_CAPABILITIES,
        )
        self.assertEqual(
            source_metadata["diagnostic21"]["c30_source_provenance"],
            orchestration.DIAGNOSTIC21_C30_SOURCE_PROVENANCE,
        )
        tracked_source_metadata = orchestration.read_json(
            PROJECT_ROOT / "frozen_manifests/source_metadata.json"
        )
        self.assertEqual(
            tracked_source_metadata["diagnostic21"]["c30_source_provenance"],
            orchestration.DIAGNOSTIC21_C30_SOURCE_PROVENANCE,
        )
        self.assertEqual(
            tracked_source_metadata["diagnostic21"]["generated_primary_manifest_sha256"],
            orchestration.sha256(PROJECT_ROOT / "frozen_manifests/v2_kure_diagnostic21.json"),
        )
        self.assertEqual(
            tracked_source_metadata["diagnostic21"]["generated_reference_manifest_sha256"],
            orchestration.sha256(PROJECT_ROOT / "frozen_manifests/v2_bm25_reference_diagnostic21.json"),
        )

    def test_direct_cli_bootstrap_initializes_cohort_before_main_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "bootstrap-root"
            command = [
                sys.executable,
                str(PROJECT_ROOT / "scripts/v2_kure_orchestration.py"),
                "bootstrap",
                "--exec-root", str(root),
                "--primary-source-manifest", str(PROJECT_ROOT / "frozen_manifests/v2_kure_full226.json"),
                "--reference-source-manifest", str(PROJECT_ROOT / "frozen_manifests/v2_bm25_reference_full226.json"),
            ]
            first = subprocess.run(command, cwd=PROJECT_ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(
                orchestration.sha256(root / orchestration.DIAGNOSTIC21_C02_ANSWER_COHORT_FILE),
                orchestration.DIAGNOSTIC21_C02_ANSWER_COHORT_SHA256,
            )
            second = subprocess.run(command, cwd=PROJECT_ROOT, text=True, capture_output=True, check=False)
            self.assertEqual(second.returncode, 2)
            self.assertIn("refusing to overwrite existing frozen_manifests", second.stderr)
            self.assertEqual(
                orchestration.sha256(root / orchestration.DIAGNOSTIC21_C02_ANSWER_COHORT_FILE),
                orchestration.DIAGNOSTIC21_C02_ANSWER_COHORT_SHA256,
            )

    def test_c41_bootstrap_is_idempotent_from_its_own_full_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_root, second_root = root / "first", root / "second"
            first = orchestration.write_v2_manifests(
                first_root,
                PROJECT_ROOT / "frozen_manifests/v2_kure_full226.json",
                PROJECT_ROOT / "frozen_manifests/v2_bm25_reference_full226.json",
            )
            second = orchestration.write_v2_manifests(
                second_root, first["full"], first["reference"]
            )
            for key in ("full", "reference", "smoke", "smoke_reference", "diagnostic21", "diagnostic21_reference"):
                self.assertEqual(orchestration.read_json(first[key]), orchestration.read_json(second[key]))
            self.assertEqual(
                orchestration.read_json(second_root / "frozen_manifests/source_metadata.json")["control_plane_release"],
                orchestration.DIAGNOSTIC21_C41_RELEASE,
            )

    def test_generic_build_does_not_inject_diagnostic_bge_metadata(self):
        primary, reference = diagnostic_sources()
        normal = orchestration.build_v2_manifests(primary, reference)
        self.assertNotIn("reranker_provenance", normal["full"]["frozen_configuration"])
        self.assertNotIn("reranker_provenance", normal["smoke"]["frozen_configuration"])

    def test_non_c02_bootstrap_preserves_four_manifest_output_and_metadata_shape(self):
        primary, reference = diagnostic_sources()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            primary_source, reference_source = root / "primary.json", root / "reference.json"
            orchestration.write_json_new(primary_source, primary)
            orchestration.write_json_new(reference_source, reference)
            paths = orchestration.write_v2_manifests(root, primary_source, reference_source)
            metadata = orchestration.read_json(root / "frozen_manifests/source_metadata.json")
        self.assertEqual(set(paths), {"full", "reference", "smoke", "smoke_reference"})
        self.assertNotIn("diagnostic21", metadata)
        self.assertNotIn("diagnostic21_available", metadata)

    def test_plan_has_fixed_chunks_and_explicitly_omits_idle_speed_metrics(self):
        manifests = diagnostic_manifests()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frozen = root / "frozen_manifests"
            frozen.mkdir()
            orchestration.write_json_new(frozen / "v2_kure_diagnostic21.json", manifests["diagnostic21"])
            orchestration.write_json_new(frozen / "v2_bm25_reference_diagnostic21.json", manifests["diagnostic21_reference"])
            with patch.object(orchestration, "source_snapshot_dict", return_value={"git_commit": "a" * 40}):
                plan = orchestration.make_plan(root, root / "records", "diagnostic21")
        self.assertEqual([(item["start_ordinal"], item["end_ordinal"]) for item in plan["chunks"]], [(1, 20), (21, 21)])
        self.assertTrue(plan["runtime"]["warm_persistent"])
        self.assertNotIn("gpu_idle_gate", plan["diagnostic21"])
        self.assertNotIn("speed_or_eta_metrics", plan["diagnostic21"])
        preflight_details = orchestration.diagnostic21_preflight_details({"git_commit": "a" * 40}, {}, {})
        self.assertNotIn("gpu_idle_gate", preflight_details)
        self.assertNotIn("speed_or_eta_metrics", preflight_details)
        self.assertEqual(preflight_details["semantic_authority"], orchestration.DIAGNOSTIC21_SEMANTIC_AUTHORITY)
        self.assertEqual(plan["execution_policy"]["bm25_execution"], "FORBIDDEN")
        self.assertEqual(plan["execution_policy"]["lf_eval_score_injection"], "FORBIDDEN")


    def test_cpu_preflight_rejects_a_matching_stale_public_answer_pair_before_artifact_checks(self):
        primary, reference = diagnostic_sources()
        for manifest in (primary, reference):
            manifest["frozen_configuration"].update({
                "s3_public_answer_max_characters": 800,
                "s3_public_answer_max_claims": 3,
                "s3_public_answer_format": "conclusion_first_1_to_3_short_sentences",
            })
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frozen = root / "frozen_manifests"
            frozen.mkdir()
            orchestration.write_json_new(frozen / "v2_kure_full226.json", primary)
            orchestration.write_json_new(frozen / "v2_bm25_reference_full226.json", reference)
            with self.assertRaisesRegex(
                RuntimeError, "frozen public-answer contract mismatch"
            ):
                orchestration.preflight(root, "full226", Path(sys.executable))
class Diagnostic21ControlPlaneTests(unittest.TestCase):
    def test_resume_accepts_the_fixed_twenty_then_one_checkpoint_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = orchestration.plan_paths(root / "records", "diagnostic21")
            plan = {
                "mode": "diagnostic21",
                "exec_root": "/isolated/worktree",
                "source_snapshot": {"git_commit": "a" * 40},
                "primary_manifest_sha256": "b" * 64,
                "reference_manifest_sha256": "c" * 64,
                "chunks": [{"start_ordinal": 1, "end_ordinal": 20}, {"start_ordinal": 21, "end_ordinal": 21}],
                "frozen_configuration": configuration(),
            }
            self.assertEqual(orchestration.initialize_output(paths, plan, resume=False), 0)
            with self.assertRaisesRegex(orchestration.OrchestrationError, "requires a PASS checkpoint-020"):
                orchestration.assert_resume_state(paths, plan, resume=True)
            orchestration.write_json_new(paths["checkpoints"] / "checkpoint-020.json", {"checkpoint_status": "PASS", "completed_questions": 20})
            with self.assertRaisesRegex(orchestration.OrchestrationError, "lacks its completed attempt: 001-020"):
                orchestration.assert_resume_state(paths, plan, resume=True)
            first_attempt = paths["batches"] / "chunk-001-020-attempt-complete"
            first_attempt.mkdir()
            orchestration.write_json_new(first_attempt / "metadata.json", {"start_ordinal": 1, "end_ordinal": 20, "completed_at_utc": "now"})
            orchestration.write_jsonl_new(first_attempt / "summary.jsonl", [{"ordinal": value} for value in range(1, 21)])
            self.assertEqual(orchestration.assert_resume_state(paths, plan, resume=True), 20)
            orchestration.write_json_new(paths["checkpoints"] / "checkpoint-021.json", {"checkpoint_status": "PASS", "completed_questions": 21})
            with self.assertRaisesRegex(orchestration.OrchestrationError, "lacks its completed attempt: 021-021"):
                orchestration.assert_resume_state(paths, plan, resume=True)
            final_attempt = paths["batches"] / "chunk-021-021-attempt-complete"
            final_attempt.mkdir()
            orchestration.write_json_new(final_attempt / "metadata.json", {"start_ordinal": 21, "end_ordinal": 21, "completed_at_utc": "now"})
            orchestration.write_jsonl_new(final_attempt / "summary.jsonl", [{"ordinal": 21}])
            self.assertEqual(orchestration.assert_resume_state(paths, plan, resume=True), 21)

    def test_diagnostic_execute_has_no_idle_gate_and_refuses_a_bypass_flag(self):
        with tempfile.TemporaryDirectory() as temporary:
            runtime_python = Path(temporary) / "python"
            runtime_python.write_text("", encoding="utf-8")
            paths = {"root": Path(temporary) / "out"}
            plan = {"source_snapshot": {"git_commit": "a" * 40}}
            with patch.dict(orchestration.os.environ, {"TMUX": "fixture"}, clear=False), patch.object(orchestration, "make_plan", return_value=plan), patch.object(orchestration, "plan_paths", return_value=paths), patch.object(orchestration, "initialize_output", return_value=0), patch.object(orchestration, "_finished_diagnostic21_gate", return_value=0), patch.object(orchestration, "wait_for_initial_gpu_idle") as idle:
                self.assertEqual(orchestration.execute_plan(Path("/exec"), Path("/out"), "diagnostic21", runtime_python, False), 0)
                idle.assert_not_called()
            with patch.object(orchestration, "make_plan") as make_plan, patch.object(orchestration, "initialize_output") as initialize:
                with self.assertRaisesRegex(orchestration.OrchestrationError, "does not accept --skip-gpu-idle-gate"):
                    orchestration.execute_plan(Path("/exec"), paths["root"], "diagnostic21", runtime_python, False, skip_gpu_idle_gate=True)
                make_plan.assert_not_called()
                initialize.assert_not_called()
                self.assertFalse(paths["root"].exists())

    def test_smoke_and_full_plans_omit_diagnostic_schema(self):
        with patch.object(orchestration, "source_snapshot_dict", return_value={"git_commit": "a" * 40}):
            smoke = orchestration.make_plan(PROJECT_ROOT, Path("/tmp/c24-smoke"), "smoke")
            full = orchestration.make_plan(PROJECT_ROOT, Path("/tmp/c24-full"), "full226")
        self.assertNotIn("diagnostic21", smoke)
        self.assertNotIn("diagnostic21", full)

    def test_launcher_accepts_diagnostic_without_smoke_prerequisite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exec_root, output_root = root / "worktree", root / "records"
            (exec_root / "scripts").mkdir(parents=True)
            (exec_root / ".venv/bin").mkdir(parents=True)
            (exec_root / "scripts/v2_kure_orchestration.py").write_text("# fixture\n", encoding="utf-8")
            (exec_root / ".venv/bin/python").write_text("", encoding="utf-8")
            launcher.assert_launchable(exec_root, output_root, "diagnostic21", resume=False)
            rendered = " ".join(launcher.build_tmux_command(exec_root, output_root, "diagnostic21", resume=False))
            with self.assertRaisesRegex(launcher.LaunchError, "does not accept"):
                launcher.build_tmux_command(exec_root, output_root, "diagnostic21", resume=False, skip_gpu_idle_gate=True)
            self.assertFalse(output_root.exists())
            self.assertFalse(launcher.log_path(output_root, "diagnostic21").exists())
        self.assertIn("--mode diagnostic21", rendered)
        self.assertNotIn("--skip-gpu-idle-gate", rendered)

    def test_diagnostic_gate_is_strict_about_all_required_checkpoint_fields(self):
        self.assertEqual(orchestration.diagnostic21_gate(passing_event())["status"], "PASS")
        zero_citation = passing_event()
        zero_citation["metrics"]["citation_integrity"] = {"attempted": 0, "passed": 0, "pass_rate": None}
        zero_citation_gate = orchestration.diagnostic21_gate(zero_citation)
        self.assertEqual(zero_citation_gate["status"], "FAIL")
        self.assertIn("citation_integrity", zero_citation_gate["reasons"])
        cases = (
            ("completed_questions", 20, "completed_questions_not_21"),
            ("checkpoint_status", "ERRORS_FOUND", "checkpoint_status_not_pass"),
            ("validation_errors", "not-a-list", "validation_errors_missing_or_nonlist"),
            ("stage_provenance_missing", None, "stage_provenance_missing_or_nonlist"),
            ("public_abstain_leak_question_ids", ["qa"], "public_abstain_leak"),
        )
        for field, replacement, reason in cases:
            with self.subTest(field=field):
                event = passing_event()
                event[field] = replacement
                gate = orchestration.diagnostic21_gate(event)
                self.assertEqual(gate["status"], "FAIL")
                self.assertIn(reason, gate["reasons"])
        event = passing_event()
        event["metrics"].pop("execution_failure_count")
        gate = orchestration.diagnostic21_gate(event)
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("normal_outcome_metric_missing_or_noninteger:execution_failure_count", gate["reasons"])
        event = passing_event()
        event["metrics"]["citation_integrity"] = {"attempted": "4", "passed": 4, "pass_rate": 1.0}
        self.assertEqual(orchestration.diagnostic21_gate(event)["status"], "FAIL")
        for value in (float("nan"), float("inf"), float("-inf")):
            event = passing_event()
            event["metrics"]["provision_macro_f1"] = value
            self.assertEqual(orchestration.diagnostic21_gate(event)["status"], "FAIL")

    def test_paired_c02_cohort_is_hash_bound_predeclared_and_fixed_denominator(self):
        cohort = orchestration.load_frozen_c02_answer_cohort(PROJECT_ROOT)
        orchestration.assert_frozen_c02_answer_cohort(cohort)
        self.assertEqual(
            cohort["provenance"]["published_per_question_csv_sha256"],
            "b0828c0d194aac9d59d3ad5894aae6220b8eaabc2c21959feabd76b5ac43e3f6",
        )
        self.assertEqual(
            cohort["provenance"]["per_question_csv_path"],
            "records/evaluations/kure-c02-qwen38-q8-full226-20260826/per_question.csv",
        )
        self.assertEqual(
            tuple(row["source_ordinal"] for row in cohort["rows"]), (17, 25, 51, 52)
        )
        self.assertEqual(
            tuple(row["question_id"] for row in cohort["rows"]),
            orchestration.DIAGNOSTIC21_C02_ANSWER_COHORT_QUESTION_IDS,
        )
        self.assertTrue(cohort["derivation"]["evaluation_only"])
        self.assertEqual(cohort["cohort_count"], 4)
        self.assertEqual(
            cohort["baseline_mean_token_f1_at_800"],
            orchestration.DIAGNOSTIC21_BASELINE["token_f1_answered_only"],
        )

    def test_frozen_cohort_is_the_answer_filter_of_the_published_c02_per_question_artifact(self):
        cohort = orchestration.load_frozen_c02_answer_cohort(PROJECT_ROOT)
        provenance = cohort["provenance"]
        source = subprocess.run(
            [
                "git", "show",
                "%s:%s" % (provenance["published_result_commit"], provenance["per_question_csv_path"]),
            ],
            cwd=PROJECT_ROOT, capture_output=True, check=False,
        )
        self.assertEqual(source.returncode, 0, source.stderr.decode("utf-8"))
        self.assertEqual(
            hashlib.sha256(source.stdout).hexdigest(),
            provenance["published_per_question_csv_sha256"],
        )
        diagnostic_ids = {question_id for _, question_id in orchestration.DIAGNOSTIC21_ROSTER}
        rows = [
            row for row in csv.DictReader(io.StringIO(source.stdout.decode("utf-8")))
            if row["question_id"] in diagnostic_ids and row["status"] == "ANSWER"
        ]
        observed = [
            {
                "source_ordinal": int(row["ordinal"]),
                "question_id": row["question_id"],
                "n_hops": int(row["n_hops"]),
                "status": row["status"],
                "token_f1_at_800": float(row["token_f1_at_800"]),
            }
            for row in rows
        ]
        self.assertEqual(observed, cohort["rows"])

    def test_paired_c02_score_refuses_missing_rows_scores_and_execution_failures(self):
        baseline_score = orchestration.DIAGNOSTIC21_BASELINE["token_f1_answered_only"]
        with tempfile.TemporaryDirectory() as temporary:
            csv_path = Path(temporary) / "per_question.csv"

            def write_rows(rows):
                csv_path.write_text(
                    "question_id,status,token_f1_at_800\n" + "\n".join(
                        "%s,%s,%s" % (row["question_id"], row["status"], row["token_f1_at_800"])
                        for row in rows
                    ) + "\n",
                    encoding="utf-8",
                )

            rows = [
                {"question_id": question_id, "status": "ANSWER", "token_f1_at_800": baseline_score}
                for question_id in orchestration.DIAGNOSTIC21_C02_ANSWER_COHORT_QUESTION_IDS
            ]
            rows.append({"question_id": "out_of_cohort", "status": "ANSWER", "token_f1_at_800": 1.0})
            write_rows(rows)
            paired = orchestration.paired_c02_answer_cohort_score(csv_path, PROJECT_ROOT)
            self.assertEqual(paired["denominator"], 4)
            self.assertEqual(paired["token_f1_at_800"], baseline_score)
            self.assertEqual(len(paired["rows"]), 4)

            write_rows(rows[:-2])
            with self.assertRaisesRegex(orchestration.OrchestrationError, "missing cohort row"):
                orchestration.paired_c02_answer_cohort_score(csv_path, PROJECT_ROOT)

            invalid = [dict(row) for row in rows[:-1]]
            invalid[0]["token_f1_at_800"] = ""
            write_rows(invalid)
            with self.assertRaisesRegex(orchestration.OrchestrationError, "missing or invalid"):
                orchestration.paired_c02_answer_cohort_score(csv_path, PROJECT_ROOT)

            failed = [dict(row) for row in rows[:-1]]
            failed[0]["status"] = "EXECUTION_FAILURE"
            write_rows(failed)
            with self.assertRaisesRegex(orchestration.OrchestrationError, "cohort execution failure"):
                orchestration.paired_c02_answer_cohort_score(csv_path, PROJECT_ROOT)

    def test_paired_gate_rejects_composition_substitution_and_non_kure_policy(self):
        event = passing_event()
        event["metrics"]["token_f1_answered_only"] = 1.0
        event["metrics"]["paired_c02_answer_cohort"] = paired_c02_answer_cohort_metric(0.0)
        gate = orchestration.diagnostic21_gate(event)
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("paired_c02_answer_cohort_token_f1_at_800", gate["reasons"])

        event = passing_event()
        event["bm25_execution"] = "EXECUTED"
        gate = orchestration.diagnostic21_gate(event)
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("bm25_execution_not_forbidden", gate["reasons"])

    def test_no_c02_threshold_is_lowered_and_full226_requires_final_proof(self):
        self.assertNotIn("token_f1_answered_only", orchestration.DIAGNOSTIC21_NONREGRESSION_MINIMUMS)
        self.assertEqual(
            orchestration.DIAGNOSTIC21_C02_ANSWER_COHORT["baseline_mean_token_f1_at_800"],
            0.42378933767566984,
        )
        self.assertEqual(
            orchestration.FULL226_C02_NONREGRESSION_MINIMUMS,
            {"token_f1_answered_only": 0.388839104735601, "token_f1_candidate": 0.34864352525272263},
        )
        full_provenance = orchestration.FULL226_C02_BASELINE_PROVENANCE
        strict_paired_event = passing_event()
        strict_paired_event["metrics"]["paired_c02_answer_cohort"] = paired_c02_answer_cohort_metric(
            orchestration.DIAGNOSTIC21_C02_ANSWER_COHORT["baseline_mean_token_f1_at_800"] - 1e-15
        )
        self.assertEqual(orchestration.diagnostic21_gate(strict_paired_event)["status"], "FAIL")

        aggregate_source = subprocess.run(
            [
                "git", "show",
                "%s:%s" % (full_provenance["published_result_commit"], full_provenance["published_aggregate_json_path"]),
            ],
            cwd=PROJECT_ROOT, capture_output=True, check=False,
        )
        self.assertEqual(aggregate_source.returncode, 0, aggregate_source.stderr.decode("utf-8"))
        self.assertEqual(
            hashlib.sha256(aggregate_source.stdout).hexdigest(),
            full_provenance["published_aggregate_json_sha256"],
        )
        published_metrics = json.loads(aggregate_source.stdout.decode("utf-8"))
        self.assertEqual(
            published_metrics["answer_quality"]["token_f1_at_800"]["answered_only"],
            orchestration.FULL226_C02_NONREGRESSION_MINIMUMS["token_f1_answered_only"],
        )
        self.assertEqual(
            published_metrics["answer_quality"]["candidate_token_f1_at_800"]["all_outcomes"],
            orchestration.FULL226_C02_NONREGRESSION_MINIMUMS["token_f1_candidate"],
        )
        full_event = {
            "checkpoint_status": "PASS",
            "completed_questions": 226,
            "validation_errors": [],
            "stage_provenance_missing": [],
            "bm25_execution": "FORBIDDEN",
            "lf_eval_score_injection": "FORBIDDEN",
            "metrics": {
                **orchestration.FULL226_C02_NONREGRESSION_MINIMUMS,
                "citation_integrity": {"attempted": 1, "passed": 1, "pass_rate": 1.0},
            },
        }
        self.assertEqual(orchestration.full226_gate(full_event)["status"], "PASS")
        full_event["metrics"]["token_f1_candidate"] = orchestration.FULL226_C02_NONREGRESSION_MINIMUMS["token_f1_candidate"] - 1e-15
        self.assertEqual(orchestration.full226_gate(full_event)["status"], "FAIL")
        full_event = dict(full_event)
        full_event["metrics"] = dict(full_event["metrics"])
        full_event["metrics"]["token_f1_candidate"] = orchestration.FULL226_C02_NONREGRESSION_MINIMUMS["token_f1_candidate"]
        full_event["bm25_execution"] = "EXECUTED"
        full_gate = orchestration.full226_gate(full_event)
        self.assertEqual(full_gate["status"], "FAIL")
        self.assertIn("bm25_execution_not_forbidden", full_gate["reasons"])

    def test_checkpoint_audits_abstain_result_json_and_omits_speed_eta_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = orchestration.plan_paths(root / "records", "diagnostic21")
            for key in ("root", "records", "batches", "checkpoints", "evaluations"):
                paths[key].mkdir(parents=True, exist_ok=True)
            attempt = paths["batches"] / "chunk-001-020-attempt-complete"
            attempt.mkdir()
            leak = root / "leak"
            invalid = root / "invalid"
            missing = root / "missing"
            leak.mkdir(); invalid.mkdir(); missing.mkdir()
            (leak / "result.json").write_text(json.dumps({"answer": ""}), encoding="utf-8")
            (invalid / "result.json").write_text("not-json", encoding="utf-8")
            rows = [
                {"ordinal": 1, "question_id": "qa-leak", "status": "ABSTAIN", "exit_code": 1, "errors": [], "record_directory": str(leak)},
                {"ordinal": 2, "question_id": "qa-invalid", "status": "ABSTAIN", "exit_code": 1, "errors": [], "record_directory": str(invalid)},
                {"ordinal": 3, "question_id": "qa-missing", "status": "ABSTAIN", "exit_code": 1, "errors": [], "record_directory": str(missing)},
            ]
            manifest_path = root / "diagnostic.json"
            orchestration.write_json_new(manifest_path, {"name": "diagnostic-fixture"})
            plan = {"mode": "diagnostic21", "entry_count": 21, "primary_manifest": str(manifest_path)}
            def fake_materialize(chunk_dirs, batch_directory, **unused):
                batch_directory.mkdir(parents=True)
                orchestration.write_jsonl_new(batch_directory / "summary.jsonl", rows)
            def fake_evaluator(command, **unused):
                output = Path(command[command.index("--output-dir") + 1])
                output.mkdir(parents=True)
                aggregate = {
                    "provision": {
                        "macro": {"f1": orchestration.DIAGNOSTIC21_BASELINE["provision_macro"]["f1"]},
                        "complete_evidence": {"count": 7},
                        "exact_match": {"count": 2},
                    },
                    "answer_quality": {
                        "token_f1_at_800": {"end_to_end": orchestration.DIAGNOSTIC21_BASELINE["token_f1_end_to_end"], "answered_only": orchestration.DIAGNOSTIC21_BASELINE["token_f1_answered_only"]},
                        "candidate_token_f1_at_800": {"all_outcomes": orchestration.DIAGNOSTIC21_BASELINE["candidate_token_f1"]["all_outcomes"]},
                        "execution_failure_count": 0, "answer_count": 4, "abstain_count": 17,
                    },
                    "citation_integrity": {"attempted": 4, "passed": 4, "pass_rate": 1.0},
                    "retrieval": {name: {"available": True} for name in ("first_stage_at_100", "rrf_at_100", "bge_at_10", "bge_at_20", "bge_at_30")},
                    "efficiency": {"end_to_end_latency_ms": {"mean": 1.0, "median": 1.0, "p95": 1.0}},
                }
                (output / "aggregate.json").write_text(json.dumps(aggregate), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")
            from scripts import materialize_checkpoint_batch
            with patch.object(materialize_checkpoint_batch, "materialize_cumulative_batch", side_effect=fake_materialize), patch.object(orchestration.subprocess, "run", side_effect=fake_evaluator):
                event = orchestration.evaluate_checkpoint(root, paths, plan, [attempt], 20, Path("/runtime/python"))
        self.assertEqual(event["event"], "DIAGNOSTIC21_CHECKPOINT20_COMPLETED")
        self.assertEqual(event["diagnostic21_checkpoint_role"], "FIRST_CHUNK_COVERAGE_CHECKPOINT_NOT_A_FINAL_GATE")
        self.assertEqual(event["checkpoint_status"], "ERRORS_FOUND")
        self.assertEqual(event["public_abstain_leak_question_ids"], ["qa-leak"])
        self.assertEqual(event["public_abstain_invalid_result_question_ids"], ["qa-invalid"])
        self.assertEqual(event["public_abstain_missing_result_question_ids"], ["qa-missing"])
        self.assertNotIn("mean_latency_ms", event["metrics"])
        self.assertNotIn("evaluator_elapsed_seconds", event)
        self.assertNotIn("remaining_eta_seconds", event)


if __name__ == "__main__":
    unittest.main()
