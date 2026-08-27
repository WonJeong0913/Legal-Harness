import importlib.util
import json
from pathlib import Path
import subprocess
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
        "condition": "fixture-%s" % retriever,
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


def passing_metrics():
    return {
        "execution_failure_count": 0,
        "answer_count": 4,
        "abstain_count": 17,
        "citation_integrity": {"attempted": 4, "passed": 4, "pass_rate": 1.0},
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
        self.assertEqual(primary["selection"]["skill_files"], orchestration.DIAGNOSTIC21_SKILL_FILES)
        self.assertEqual(primary["selection"]["reranker_provenance"], orchestration.DIAGNOSTIC21_RERANKER_PROVENANCE)
        self.assertEqual(primary["selection"]["candidate_id"], orchestration.DIAGNOSTIC21_CANDIDATE_ID)
        self.assertEqual(primary["selection"]["c22_capability"], orchestration.DIAGNOSTIC21_C22_CAPABILITY)
        self.assertEqual(primary["selection"]["semantic_authority"], orchestration.DIAGNOSTIC21_SEMANTIC_AUTHORITY)
        self.assertEqual(
            primary["selection"]["runtime_artifact_path_provenance"]["qwen_ollama_blob_exact_local_runtime_exception"],
            orchestration.QWEN_MODEL_PROVENANCE["ollama_model_blob"],
        )
        self.assertFalse(primary["selection"]["round_merge_provenance"]["equivalence_claimed"])
        self.assertEqual(primary["selection"]["round_merge_provenance"]["c02_saved_stage_round_merge_mode"], "request_rank_top1_guarded_swap")
        self.assertEqual(primary["frozen_configuration"]["condition"], "fixture-kure")
        self.assertEqual(reference["frozen_configuration"]["condition"], "fixture-bm25")
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

    def test_tracked_manifests_match_exact_sources_and_have_no_workspace_paths(self):
        primary_source = orchestration.read_json(PROJECT_ROOT / "frozen_manifests/v2_kure_full226.json")
        reference_source = orchestration.read_json(PROJECT_ROOT / "frozen_manifests/v2_bm25_reference_full226.json")
        generated = orchestration.build_diagnostic21_manifests(
            primary_source,
            reference_source,
            orchestration.sha256(PROJECT_ROOT / "frozen_manifests/v2_kure_full226.json"),
            orchestration.sha256(PROJECT_ROOT / "frozen_manifests/v2_bm25_reference_full226.json"),
        )
        for filename, key in (("v2_kure_diagnostic21.json", "diagnostic21"), ("v2_bm25_reference_diagnostic21.json", "diagnostic21_reference")):
            tracked = orchestration.read_json(PROJECT_ROOT / "frozen_manifests" / filename)
            self.assertEqual(tracked, generated[key])
            orchestration.assert_diagnostic21_manifest_integrity(generated["diagnostic21"], generated["diagnostic21_reference"])
            self.assertNotIn("/workspace", json.dumps(tracked, ensure_ascii=False))

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
        self.assertEqual(orchestration.diagnostic21_gate(zero_citation)["status"], "PASS")
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
