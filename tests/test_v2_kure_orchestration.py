import hashlib
import importlib.util
import json
from pathlib import Path
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


orchestration = load_module("v2_kure_orchestration_test", "scripts/v2_kure_orchestration.py")
launcher = load_module("launch_v2_kure_tmux_test", "scripts/launch_v2_kure_tmux.py")


def fixture_configuration(retriever="kure"):
    config = {
        "condition": "fixture-%s-full226" % retriever,
        "retriever": retriever,
        "model": "legal-harness-qwen38-q8",
        "seed": 0,
        "num_ctx": 32768,
        "ollama_endpoint": "http://127.0.0.1:11435/api/generate",
        "runtime_determinism": {"num_parallel": 1, "seed_forwarding": "ollama_options_seed"},
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
        "model_provenance": dict(orchestration.QWEN_MODEL_PROVENANCE),
    }
    if retriever == "kure":
        config["retriever_provenance"] = {"model_id": "local-kure"}
    return config


def fixture_manifests():
    entries = [
        {"ordinal": ordinal, "question_id": "fixture_%03d" % ordinal, "n_hops": ((ordinal - 1) % 3) + 1}
        for ordinal in range(1, 227)
    ]
    return (
        {"name": "primary", "source_dataset": {"path": "data/fixture.parquet", "sha256": "a" * 64}, "frozen_configuration": fixture_configuration(), "entries": entries, "selection": {"entry_count": 226}},
        {"name": "reference", "source_dataset": {"path": "data/fixture.parquet", "sha256": "a" * 64}, "frozen_configuration": fixture_configuration("bm25"), "entries": entries, "selection": {"entry_count": 226}},
    )


class PartitionAndPolicyTests(unittest.TestCase):
    def test_full226_partition_is_exactly_twenty_question_boundaries(self):
        self.assertEqual(
            orchestration.chunks_for_entries(),
            ((1, 20), (21, 40), (41, 60), (61, 80), (81, 100), (101, 120), (121, 140), (141, 160), (161, 180), (181, 200), (201, 220), (221, 226)),
        )

    def test_v2_manifest_keeps_full_order_and_reindexes_smoke_execution_ordinals(self):
        primary, reference = fixture_manifests()
        primary["entries"][1]["n_hops"] = primary["entries"][2]["n_hops"] = primary["entries"][3]["n_hops"] = 1
        primary["entries"][4]["n_hops"] = 2
        primary["entries"][5]["n_hops"] = primary["entries"][6]["n_hops"] = primary["entries"][7]["n_hops"] = 2
        for item in primary["entries"][8:15]:
            item["n_hops"] = 2
        primary["entries"][15]["n_hops"] = 3
        reference["entries"] = [dict(item) for item in primary["entries"]]
        output = orchestration.build_v2_manifests(primary, reference)
        self.assertEqual(output["full"]["entries"], primary["entries"])
        self.assertEqual([item["ordinal"] for item in output["smoke"]["entries"]], [1, 2, 3])
        self.assertEqual([item["source_ordinal"] for item in output["smoke"]["entries"]], [1, 5, 16])
        self.assertEqual([item["question_id"] for item in output["smoke"]["entries"]], ["fixture_001", "fixture_005", "fixture_016"])
        self.assertEqual([item["n_hops"] for item in output["smoke"]["entries"]], [1, 2, 3])
        self.assertEqual(output["full"]["frozen_configuration"]["retriever"], "kure")
        self.assertEqual(output["full"]["frozen_configuration"]["model_provenance"], orchestration.QWEN_MODEL_PROVENANCE)
        self.assertEqual(output["reference"]["frozen_configuration"]["retriever"], "bm25")

    def test_c32_smoke_condition_requires_one_full226_token(self):
        self.assertEqual(
            orchestration._full_to_smoke_c32_condition("fixture-full226"),
            "fixture-smoke3"
            + orchestration.DIAGNOSTIC21_C31_CONDITION_SUFFIX
            + orchestration.DIAGNOSTIC21_C32_CONDITION_SUFFIX,
        )
        with self.assertRaisesRegex(orchestration.OrchestrationError, "exactly one full226"):
            orchestration._full_to_smoke_c32_condition("fixture")
        with self.assertRaisesRegex(orchestration.OrchestrationError, "exactly one full226"):
            orchestration._full_to_smoke_c32_condition("fixture-full226-full226")

    def test_c36_condition_overlay_is_idempotent_for_all_manifest_roles(self):
        self.assertEqual(
            orchestration._full_to_smoke_c36_condition("fixture-full226"),
            "fixture-smoke3"
            + orchestration.DIAGNOSTIC21_C31_CONDITION_SUFFIX
            + orchestration.DIAGNOSTIC21_C32_CONDITION_SUFFIX
            + orchestration.DIAGNOSTIC21_C33_CONDITION_SUFFIX
            + orchestration.DIAGNOSTIC21_C34_CONDITION_SUFFIX
            + orchestration.DIAGNOSTIC21_C35_CONDITION_SUFFIX
            + orchestration.DIAGNOSTIC21_C36_CONDITION_SUFFIX,
        )
        primary, reference = fixture_manifests()
        first = orchestration.build_v2_manifests(primary, reference)
        second = orchestration.build_v2_manifests(first["full"], first["reference"])
        for role in ("full", "reference", "smoke", "smoke_reference"):
            self.assertEqual(
                first[role]["frozen_configuration"]["condition"],
                second[role]["frozen_configuration"]["condition"],
            )
            self.assertTrue(
                first[role]["frozen_configuration"]["condition"].endswith(
                    orchestration.DIAGNOSTIC21_C36_CONDITION_SUFFIX
                )
            )

    def test_kure_only_and_external_score_guards_fail_closed(self):
        with self.assertRaisesRegex(orchestration.OrchestrationError, "only the KURE"):
            orchestration.assert_kure_only(fixture_configuration("bm25"))
        with self.assertRaisesRegex(orchestration.OrchestrationError, "never BM25"):
            orchestration.assert_kure_execution_command(["python", "runner", "--retriever", "bm25"])
        with self.assertRaisesRegex(orchestration.OrchestrationError, "LF-Eval"):
            orchestration.assert_no_external_score_injection(["python", "evaluate", "--lf-eval-scores", "scores.json"])


class ResumeAndMetricTests(unittest.TestCase):
    def _plan(self, root):
        return {
            "mode": "full226",
            "exec_root": "/isolated/worktree",
            "source_snapshot": {"git_commit": "a" * 40, "git_tree": "b" * 40, "source_manifest_sha256": "c" * 64},
            "primary_manifest_sha256": "d" * 64,
            "reference_manifest_sha256": "e" * 64,
            "chunks": [{"start_ordinal": 1, "end_ordinal": 20}, {"start_ordinal": 21, "end_ordinal": 40}],
            "frozen_configuration": fixture_configuration(),
        }

    def test_resume_preserves_partial_attempt_and_rejects_ambiguous_completed_attempts(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary) / "outputs"
            paths = orchestration.plan_paths(output_root, "full226")
            plan = self._plan(output_root)
            self.assertEqual(orchestration.initialize_output(paths, plan, resume=False), 0)
            orchestration.write_json_new(paths["checkpoints"] / "checkpoint-020.json", {"checkpoint_status": "PASS", "completed_questions": 20})
            self.assertEqual(orchestration.assert_resume_state(paths, plan, resume=True), 20)
            partial = paths["batches"] / "chunk-021-040-attempt-interrupted"
            partial.mkdir()
            self.assertEqual(orchestration.assert_resume_state(paths, plan, resume=True), 20)
            self.assertTrue(partial.is_dir())
            completed = paths["batches"] / "chunk-021-040-attempt-complete"
            completed.mkdir()
            orchestration.write_json_new(completed / "metadata.json", {"start_ordinal": 21, "end_ordinal": 40, "completed_at_utc": "now"})
            orchestration.write_jsonl_new(completed / "summary.jsonl", [{"ordinal": ordinal} for ordinal in range(21, 41)])
            self.assertEqual(orchestration.completed_attempt_for(paths, 21, 40), completed)
            duplicate = paths["batches"] / "chunk-021-040-attempt-duplicate"
            duplicate.mkdir()
            orchestration.write_json_new(duplicate / "metadata.json", {"start_ordinal": 21, "end_ordinal": 40, "completed_at_utc": "now"})
            orchestration.write_jsonl_new(duplicate / "summary.jsonl", [{"ordinal": ordinal} for ordinal in range(21, 41)])
            with self.assertRaisesRegex(orchestration.OrchestrationError, "ambiguous"):
                orchestration.completed_attempt_for(paths, 21, 40)

    def test_progress_projection_uses_evaluator_aggregate_paths(self):
        projection = orchestration._metric_projection({
            "provision": {"macro": {"precision": .1, "recall": .2, "f1": .15}, "micro": {"f1": .25}, "complete_evidence": {"count": 3, "rate": .3}, "exact_match": {"count": 4, "rate": .4}},
            "answer_quality": {"token_f1_at_800": {"end_to_end": .5, "answered_only": .6}, "candidate_token_f1_at_800": {"all_outcomes": .7}, "answer_count": 8, "abstain_count": 2, "execution_failure_count": 0},
            "outcomes": {"ANSWER": {"count": 8}, "ABSTAIN": {"count": 2}},
            "citation_integrity": {"attempted": 8, "passed": 8, "pass_rate": 1.0},
            "efficiency": {"end_to_end_latency_ms": {"mean": 123.0, "median": 120.0, "p95": 150.0}},
        })
        self.assertEqual(projection["provision_macro_f1"], .15)
        self.assertEqual(projection["token_f1_candidate"], .7)
        self.assertEqual(projection["citation_integrity"]["pass_rate"], 1.0)
        self.assertEqual(projection["median_latency_ms"], 120.0)
        self.assertEqual(projection["p95_latency_ms"], 150.0)
        self.assertEqual(projection["complete_evidence_count"], 3)
        self.assertEqual(projection["provision_exact_match_count"], 4)
        self.assertEqual(((226 - 20) * 1000.0) / 1000.0, 206.0)


class PreflightAndTmuxTests(unittest.TestCase):
    def test_gpu_idle_gate_requires_two_stable_samples_after_thirty_minute_poll(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = orchestration.plan_paths(Path(temporary), "smoke")
            states = iter([
                {"gpus": [{"utilization_percent": 100, "used_memory_mib": 49400}], "max_utilization_percent": 100, "max_used_memory_mib": 49400},
                {"gpus": [{"utilization_percent": 0, "used_memory_mib": 1024}], "max_utilization_percent": 0, "max_used_memory_mib": 1024},
                {"gpus": [{"utilization_percent": 0, "used_memory_mib": 1024}], "max_utilization_percent": 0, "max_used_memory_mib": 1024},
            ])
            with patch.object(orchestration, "query_gpu_state", side_effect=lambda: next(states)) as query, patch.object(orchestration.time, "sleep") as sleep:
                event = orchestration.wait_for_initial_gpu_idle(paths)
            self.assertEqual(query.call_count, 3)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [1800, 30])
            self.assertTrue(event["idle"])
            self.assertEqual(event["stable_samples"], 2)
            self.assertEqual(len(orchestration._jsonl_rows(paths["progress_jsonl"])), 3)


    def test_smoke_then_full_calls_idle_gate_path_only_for_smoke(self):
        with patch.object(orchestration, "execute_plan", side_effect=[0, 0]) as execute:
            self.assertEqual(orchestration.execute_smoke_then_full(Path("/worktree"), Path("/outputs"), Path("/venv/python")), 0)
        self.assertEqual(execute.call_args_list[0].args[2], "smoke")
        self.assertIn("gpu_poll_seconds", execute.call_args_list[0].kwargs)
        self.assertEqual(execute.call_args_list[1].args[2], "full226")
        self.assertNotIn("gpu_poll_seconds", execute.call_args_list[1].kwargs)

    def test_kure_artifact_preflight_hashes_local_files_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            provenance = {}
            for key in ("normalized_corpus_path", "vectors_path", "provision_ids_path"):
                path = root / "artifacts" / (key + ".bin")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(key.encode("utf-8"))
                provenance[key] = str(path.relative_to(root))
                provenance[key.replace("_path", "_sha256")] = hashlib.sha256(path.read_bytes()).hexdigest()
            config = fixture_configuration()
            weights = root / "models/huggingface/nlpai-lab--KURE-v1/model.safetensors"
            weights.parent.mkdir(parents=True)
            weights.write_bytes(b"kure-model")
            provenance["model_path"] = "models/huggingface/nlpai-lab--KURE-v1"
            provenance["model_weights_sha256"] = hashlib.sha256(weights.read_bytes()).hexdigest()
            config["retriever_provenance"] = provenance
            self.assertIn("model.safetensors", orchestration.verify_kure_artifacts(config, root))
            weights.write_bytes(b"changed")
            with self.assertRaisesRegex(orchestration.OrchestrationError, "model.safetensors hash mismatch"):
                orchestration.verify_kure_artifacts(config, root)

    def test_tmux_dry_run_command_is_detached_offline_and_has_no_execution_side_effect(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exec_root, output_root = root / "worktree", root / "outputs"
            (exec_root / "scripts").mkdir(parents=True)
            (exec_root / ".venv/bin").mkdir(parents=True)
            (exec_root / "scripts/v2_kure_orchestration.py").write_text("# fixture\n", encoding="utf-8")
            (exec_root / ".venv/bin/python").write_text("", encoding="utf-8")
            launcher.assert_launchable(exec_root, output_root, "smoke", resume=False)
            command = launcher.build_tmux_command(exec_root, output_root, "smoke", resume=False)
            rendered = " ".join(command)
            self.assertIn("new-session", rendered)
            self.assertIn("HF_HUB_OFFLINE=1", rendered)
            self.assertIn("OLLAMA_NUM_PARALLEL=1", rendered)
            self.assertIn("OLLAMA_NO_CLOUD=1", rendered)
            self.assertIn("--mode smoke", rendered)
            self.assertFalse(output_root.exists())

    def test_launcher_refuses_existing_mode_output_without_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exec_root, output_root = root / "worktree", root / "outputs"
            (exec_root / "scripts").mkdir(parents=True)
            (exec_root / ".venv/bin").mkdir(parents=True)
            (exec_root / "scripts/v2_kure_orchestration.py").write_text("# fixture\n", encoding="utf-8")
            (exec_root / ".venv/bin/python").write_text("", encoding="utf-8")
            (output_root / "smoke").mkdir(parents=True)
            with self.assertRaisesRegex(launcher.LaunchError, "overwrite"):
                launcher.assert_launchable(exec_root, output_root, "smoke", resume=False)


    def test_full_launcher_accepts_smoke_gate_but_not_existing_full_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exec_root, output_root = root / "worktree", root / "outputs"
            (exec_root / "scripts").mkdir(parents=True)
            (exec_root / ".venv/bin").mkdir(parents=True)
            (exec_root / "scripts/v2_kure_orchestration.py").write_text("# fixture\n", encoding="utf-8")
            (exec_root / ".venv/bin/python").write_text("", encoding="utf-8")
            (output_root / "smoke").mkdir(parents=True)
            (output_root / "smoke/gate.json").write_text("{\"status\":\"PASS\"}", encoding="utf-8")
            launcher.assert_launchable(exec_root, output_root, "full226", resume=False)
            (output_root / "full226").mkdir()
            with self.assertRaisesRegex(launcher.LaunchError, "overwrite"):
                launcher.assert_launchable(exec_root, output_root, "full226", resume=False)


class NewV2RunnerSafetyTests(unittest.TestCase):
    def test_readiness_accepts_only_actual_latest_alias_with_frozen_digest_and_details(self):
        class Response:
            def __init__(self, item):
                self.item = item
            def read(self):
                return json.dumps({"models": [self.item]}).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *unused):
                return False
        valid = {
            "name": "legal-harness-qwen38-q8:latest",
            "model": "legal-harness-qwen38-q8:latest",
            "digest": "91f49c230b9d1fd034414b1035b361cfe4ad1c89f7076012b10420edea8b78ff",
            "details": {"family": "qwen35", "parameter_size": "26.9B", "quantization_level": "Q8_0"},
        }
        with patch.object(orchestration, "urlopen", return_value=Response(valid)) as request:
            ready = orchestration.check_local_ollama_readiness(fixture_configuration())
        self.assertTrue(ready["tags_url"].endswith("/api/tags"))
        self.assertEqual(ready["resolved_model_name"], "legal-harness-qwen38-q8:latest")
        self.assertEqual(request.call_args.args[0], ready["tags_url"])
        for field, bad in (("digest", "0" * 64), ("details", {"family": "qwen35", "parameter_size": "26.9B", "quantization_level": "Q4_0"})):
            invalid = dict(valid)
            invalid[field] = bad
            with patch.object(orchestration, "urlopen", return_value=Response(invalid)):
                with self.assertRaisesRegex(orchestration.OrchestrationError, "provenance does not match"):
                    orchestration.check_local_ollama_readiness(fixture_configuration())
        tagged = dict(valid)
        tagged["name"] = tagged["model"] = "legal-harness-qwen38-q8:other"
        with patch.object(orchestration, "urlopen", return_value=Response(tagged)):
            with self.assertRaisesRegex(orchestration.OrchestrationError, "alias is unavailable"):
                orchestration.check_local_ollama_readiness(fixture_configuration())
        with patch.dict(orchestration.os.environ, {"OLLAMA_NO_CLOUD": "0", "HF_HUB_OFFLINE": "0"}, clear=False):
            values = orchestration.enforce_offline_environment()
            self.assertEqual(values["OLLAMA_NO_CLOUD"], "1")
            self.assertEqual(orchestration.os.environ["HF_HUB_OFFLINE"], "1")

    def test_execute_plan_forces_offline_environment_before_model_capable_path(self):
        with patch.dict(orchestration.os.environ, {"TMUX": "fixture", "OLLAMA_NO_CLOUD": "0"}, clear=False):
            def stop(*unused):
                self.assertEqual(orchestration.os.environ["OLLAMA_NO_CLOUD"], "1")
                self.assertEqual(orchestration.os.environ["HF_HUB_OFFLINE"], "1")
                raise orchestration.OrchestrationError("stop")
            with tempfile.TemporaryDirectory() as temporary:
                runtime_python = Path(temporary) / "python"
                runtime_python.write_text("", encoding="utf-8")
                with patch.object(orchestration, "make_plan", side_effect=stop):
                    with self.assertRaisesRegex(orchestration.OrchestrationError, "stop"):
                        orchestration.execute_plan(Path("/exec"), Path("/output"), "smoke", runtime_python, False)

    def test_smoke_gate_requires_real_answer_zero_failures_and_passing_citations(self):
        event = {
            "validation_errors": [], "stage_provenance_missing": [],
            "metrics": {"answer_count": 1, "execution_failure_count": 0, "citation_integrity": {"attempted": 1, "pass_rate": 1.0}},
        }
        self.assertEqual(orchestration.smoke_gate(event)["status"], "PASS")
        for replacement in (
            {"answer_count": 0},
            {"execution_failure_count": None},
            {"citation_integrity": {"attempted": 0, "pass_rate": 1.0}},
        ):
            failing = {**event, "metrics": {**event["metrics"], **replacement}}
            self.assertEqual(orchestration.smoke_gate(failing)["status"], "FAIL")

    def test_all_resume_is_supported_and_preserves_warm_flow(self):
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary) / "durable"
            (output_root / "smoke").mkdir(parents=True)
            (output_root / "full226").mkdir()
            with patch.object(orchestration, "execute_plan", side_effect=[0, 0]) as execute:
                self.assertEqual(orchestration.execute_smoke_then_full(Path("/worktree"), output_root, Path("/venv/python"), resume=True), 0)
        self.assertTrue(execute.call_args_list[0].kwargs["resume"])
        self.assertTrue(execute.call_args_list[1].kwargs["resume"])
        self.assertNotIn("gpu_poll_seconds", execute.call_args_list[1].kwargs)

    def test_launcher_all_resume_is_permitted_for_durable_records_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exec_root, output_root = root / "worktree", root / "records" / "new-v2"
            (exec_root / "scripts").mkdir(parents=True)
            (exec_root / ".venv/bin").mkdir(parents=True)
            (exec_root / "scripts/v2_kure_orchestration.py").write_text("# fixture\n", encoding="utf-8")
            (exec_root / ".venv/bin/python").write_text("", encoding="utf-8")
            (output_root / "smoke").mkdir(parents=True)
            launcher.assert_launchable(exec_root, output_root, "all", resume=True)
            rendered = " ".join(launcher.build_tmux_command(exec_root, output_root, "all", True))
            self.assertIn("--mode all --resume", rendered)

    def test_execute_chunk_runs_selected_smoke_ordinals_not_source_ordinal_ranges(self):
        from runtime import source_snapshot
        from scripts import run_local_harness
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exec_root, output_root = root / "snapshot", root / "durable-records"
            exec_root.mkdir()
            paths = orchestration.plan_paths(output_root, "smoke")
            paths["root"].mkdir(parents=True)
            for key in ("records", "batches", "checkpoints", "evaluations"):
                paths[key].mkdir(parents=True)
            entries = [
                {"ordinal": 1, "source_ordinal": 1, "question_id": "fixture_001", "n_hops": 1},
                {"ordinal": 2, "source_ordinal": 5, "question_id": "fixture_005", "n_hops": 2},
                {"ordinal": 3, "source_ordinal": 16, "question_id": "fixture_016", "n_hops": 3},
            ]
            manifest_path = root / "smoke-manifest.json"
            manifest_path.write_text(json.dumps({"frozen_configuration": fixture_configuration(), "entries": entries}), encoding="utf-8")
            snapshot_data = {"git_commit": "a" * 40, "git_tree": "b" * 40, "source_manifest_sha256": "c" * 64}
            plan = {"primary_manifest": str(manifest_path), "source_snapshot": snapshot_data}
            questions = {item["question_id"]: {"background": "", "question": item["question_id"], "n_hops": item["n_hops"]} for item in entries}
            snapshot = type("Snapshot", (), {"to_dict": lambda self: snapshot_data})()
            def fake_build(question, question_id, configuration, record_root, supplied_snapshot):
                return type("RunArgs", (), {"question_id": question_id, "record_root": record_root})()
            def fake_run(args, **unused):
                record = args.record_root / ("record-" + args.question_id)
                record.mkdir()
                (record / "result.json").write_text(json.dumps({"status": "ANSWER", "run_id": args.question_id, "errors": []}), encoding="utf-8")
                return type("Execution", (), {"rendered_output": "ok", "exit_code": 0})()
            with patch.object(source_snapshot, "capture_clean_source_snapshot", return_value=snapshot), patch.object(source_snapshot, "assert_source_snapshot_unchanged"), patch.object(orchestration, "_build_v2_run_args", side_effect=fake_build), patch.object(run_local_harness, "run_question", side_effect=fake_run):
                attempt, failed = orchestration.execute_chunk(exec_root, paths, plan, 1, 3, object(), questions)
            self.assertFalse(failed)
            rows = orchestration._jsonl_rows(attempt / "summary.jsonl")
            self.assertEqual([row["ordinal"] for row in rows], [1, 2, 3])
            self.assertEqual([row["source_ordinal"] for row in rows], [1, 5, 16])

    def test_evaluator_retry_uses_completed_attempt_without_rerunning_chunk(self):
        import subprocess
        from scripts import materialize_checkpoint_batch
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = orchestration.plan_paths(root / "durable-records", "full226")
            for key in ("root", "records", "batches", "checkpoints", "evaluations"):
                paths[key].mkdir(parents=True, exist_ok=True)
            attempt = paths["batches"] / "chunk-001-020-attempt-complete"
            attempt.mkdir()
            orchestration.write_json_new(attempt / "metadata.json", {"start_ordinal": 1, "end_ordinal": 20, "completed_at_utc": "now"})
            orchestration.write_jsonl_new(attempt / "summary.jsonl", [{"ordinal": ordinal, "question_id": "q%d" % ordinal, "status": "ANSWER", "exit_code": 0, "errors": []} for ordinal in range(1, 21)])
            plan = {"mode": "full226", "entry_count": 226}
            def fake_materialize(chunk_dirs, batch_directory, **unused):
                self.assertEqual(list(chunk_dirs), [attempt])
                orchestration.write_jsonl_new(batch_directory / "summary.jsonl", orchestration._jsonl_rows(attempt / "summary.jsonl"))
            def fake_evaluator(command, **unused):
                out = Path(command[command.index("--output-dir") + 1])
                out.mkdir(parents=True)
                aggregate = {
                    "provision": {"macro": {}, "micro": {}, "complete_evidence": {}, "exact_match": {}},
                    "answer_quality": {"answer_count": 20, "abstain_count": 0, "execution_failure_count": 0},
                    "citation_integrity": {"attempted": 20, "pass_rate": 1.0},
                    "retrieval": {name: {"available": True} for name in ("first_stage_at_100", "rrf_at_100", "bge_at_10", "bge_at_20", "bge_at_30")},
                    "efficiency": {"end_to_end_latency_ms": {"mean": 1000.0, "median": 1000.0, "p95": 1000.0}},
                }
                (out / "aggregate.json").write_text(json.dumps(aggregate), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")
            with patch.object(materialize_checkpoint_batch, "materialize_cumulative_batch", side_effect=fake_materialize), patch.object(orchestration.subprocess, "run", side_effect=fake_evaluator):
                event = orchestration.evaluate_checkpoint(root, paths, plan, [attempt], 20, Path("/runtime/python"))
            self.assertEqual(event["checkpoint_status"], "PASS")
            self.assertEqual(event["remaining_eta_seconds"], 206.0)
            self.assertNotIn("diagnostic21_checkpoint_role", event)
            self.assertNotIn("public_abstain_leak_question_ids", event)
            self.assertNotIn("public_abstain_missing_result_question_ids", event)
            self.assertNotIn("public_abstain_invalid_result_question_ids", event)
            self.assertTrue((paths["checkpoints"] / "checkpoint-020.json").is_file())


if __name__ == "__main__":
    unittest.main()
