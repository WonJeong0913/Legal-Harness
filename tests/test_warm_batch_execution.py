import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts import run_bm25_bge_pilot_batch as batch
from scripts import run_local_harness as local
from runtime.source_snapshot import SourceSnapshot


def frozen_configuration(retriever="kure"):
    return {
        "condition": "C5",
        "seed": 0,
        "retriever": retriever,
        "model": "model",
        "num_ctx": 32768,
        "total_retrieval_rounds": 3,
        "total_retrieval_requests": 9,
        "rerank_pool_k": 100,
        "final_top_k": 10,
        "rerank_query_mode": "combined_issue",
        "candidate_selection": "global_top_k",
        "per_evidence_min_k": 1,
        "candidate_budget_scope": "per_issue",
        "dedup_mode": "none",
        "rerank_document_mode": "body_only",
        "input_format": "koblex_background_plus_question",
    }

class KureProvenanceValidationTests(unittest.TestCase):
    def _configuration(self, project_root: Path):
        provenance = {}
        files = {}
        for index, (path_key, sha256_key) in enumerate(batch.KURE_PROVENANCE_ARTIFACTS):
            relative_path = Path("artifacts") / (path_key + ".bin")
            artifact_path = project_root / relative_path
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            contents = ("artifact-%d" % index).encode("utf-8")
            artifact_path.write_bytes(contents)
            provenance[path_key] = str(relative_path)
            provenance[sha256_key] = batch.sha256(artifact_path)
            files[path_key] = artifact_path
        return {"retriever": "kure", "retriever_provenance": provenance}, files

    def test_matching_artifacts_are_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            configuration, _ = self._configuration(Path(temporary))
            batch.verify_kure_retriever_provenance(configuration, Path(temporary))


    def test_project_relative_symlinked_artifacts_are_accepted(self):
        with tempfile.TemporaryDirectory() as root_directory, tempfile.TemporaryDirectory() as canonical_directory:
            root = Path(root_directory)
            configuration, _ = self._configuration(Path(canonical_directory))
            shared_artifacts = root / "shared-artifacts"
            shared_artifacts.symlink_to(Path(canonical_directory) / "artifacts", target_is_directory=True)
            provenance = configuration["retriever_provenance"]
            for path_key, _ in batch.KURE_PROVENANCE_ARTIFACTS:
                provenance[path_key] = str(Path("shared-artifacts") / (path_key + ".bin"))
            batch.verify_kure_retriever_provenance(configuration, root)
    def test_hash_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            configuration, files = self._configuration(Path(temporary))
            files["vectors_path"].write_bytes(b"changed")

            with self.assertRaisesRegex(RuntimeError, "SHA256 mismatch for vectors_path"):
                batch.verify_kure_retriever_provenance(configuration, Path(temporary))

    def test_missing_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            configuration, files = self._configuration(Path(temporary))
            files["provision_ids_path"].unlink()

            with self.assertRaisesRegex(RuntimeError, "artifact is missing for provision_ids_path"):
                batch.verify_kure_retriever_provenance(configuration, Path(temporary))


    def test_non_kure_configuration_skips_provenance_validation(self):
        batch.verify_kure_retriever_provenance({"retriever": "bm25"}, Path("/unused"))

class PersistentResourceTests(unittest.TestCase):
    def test_expensive_components_are_initialized_once_and_records_get_distinct_sinks(self):
        args = SimpleNamespace(
            skills_root=Path("/skills"),
            retriever="kure",
            rerank_document_mode="body_only",
            rerank_pool_k=100,
            final_top_k=10,
            rerank_query_mode="combined_issue",
            candidate_selection="global_top_k",
            per_evidence_min_k=1,
            dedup_mode="none",
            candidate_budget_scope="per_issue",
            model="model",
            ollama_endpoint="http://endpoint",
            num_ctx=32768,
            s1_max_tokens=4096,
            s1_truncation_retry_max_tokens=8192,
            rounds=3,
            requests=9,
        )
        corpus, executor, retriever = object(), SimpleNamespace(), object()
        first = SimpleNamespace(
            record_skill_attempt=Mock(),
            trace_sink=object(),
        )
        second = SimpleNamespace(
            record_skill_attempt=Mock(),
            trace_sink=object(),
        )
        with (
            patch.object(local, "assert_skill_layout_complete"),
            patch.object(
                local.InMemoryProvisionCorpus,
                "from_jsonl",
                return_value=corpus,
            ) as corpus_load,
            patch.object(local, "KureExactIndexSearcher", return_value=object()) as kure,
            patch.object(local, "LocalBgeCrossEncoderReranker", return_value=object()) as bge,
            patch.object(local, "RetrievalPipeline", return_value=retriever),
            patch.object(local, "_build_skill_executor", return_value=executor) as skill_load,
            patch.object(local, "CitationIntegrityChecker"),
        ):
            resources = local.PersistentHarnessResources(args)
            first_runner = resources.build_runner(args, first)
            second_runner = resources.build_runner(args, second)
        self.assertEqual(corpus_load.call_count, 1)
        self.assertEqual(kure.call_count, 1)
        self.assertEqual(bge.call_count, 1)
        self.assertEqual(skill_load.call_count, 1)
        self.assertIs(first_runner.retriever, retriever)
        self.assertIs(second_runner.retriever, retriever)
        self.assertIsNot(first_runner.skill_executor, second_runner.skill_executor)
        first_runner.skill_executor.diagnostic_sink({"run": "one"})
        second_runner.skill_executor.diagnostic_sink({"run": "two"})
        first.record_skill_attempt.assert_called_once()
        second.record_skill_attempt.assert_called_once()


class WarmBatchTests(unittest.TestCase):
    def test_warm_batch_keeps_order_and_continues_after_one_question_failure(self):
        with tempfile.TemporaryDirectory(dir=batch.PROJECT_ROOT) as temporary:
            root = Path(temporary)
            dataset = root / "questions.parquet"
            dataset.write_bytes(b"fixture")
            configuration = frozen_configuration("bm25")
            manifest = {
                "name": "warm",
                "source_dataset": {
                    "path": str(dataset.relative_to(batch.PROJECT_ROOT)),
                    "sha256": batch.sha256(dataset),
                },
                "frozen_configuration": configuration,
                "entries": [
                    {"ordinal": 1, "question_id": "q1", "n_hops": 1},
                    {"ordinal": 2, "question_id": "q2", "n_hops": 1},
                    {"ordinal": 3, "question_id": "q3", "n_hops": 2},
                ],
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            questions = {
                "q1": {"question": "one", "background": "", "n_hops": 1},
                "q2": {"question": "two", "background": "", "n_hops": 1},
                "q3": {"question": "three", "background": "", "n_hops": 2},
            }
            resource_args, calls = [], []
            class Resources:
                def __init__(self, value):
                    resource_args.append(value)
            def build(
                question,
                question_id,
                _configuration,
                record_dir,
                *_snapshot,
            ):
                return SimpleNamespace(
                    question=question,
                    question_id=question_id,
                    record_dir=record_dir,
                )
            def run(run_args, **_kwargs):
                calls.append(run_args.question_id)
                if run_args.question_id == "q2":
                    raise RuntimeError("isolated failure")
                directory = run_args.record_dir / ("run-" + run_args.question_id)
                directory.mkdir(parents=True)
                (directory / "result.json").write_text(
                    json.dumps({"status": "ANSWER", "errors": []}),
                    encoding="utf-8",
                )
                return SimpleNamespace(
                    exit_code=0,
                    rendered_output="completed " + run_args.question_id,
                )
            warm_module = SimpleNamespace(
                PersistentHarnessResources=Resources,
                build_frozen_run_args=build,
                run_question=run,
            )
            args = SimpleNamespace(
                manifest=manifest_path,
                start_ordinal=1,
                end_ordinal=None,
                batch_name="warm",
                comparison_manifest=None,
                python=Path(__file__),
                record_root=root / "records",
                batch_log_root=root / "batches",
                warm_resources=True,
            )
            snapshot = SourceSnapshot(
                git_commit="a" * 40,
                git_tree="b" * 40,
                source_manifest_sha256="c" * 64,
            )
            with (
                patch.object(batch, "parse_args", return_value=args),
                patch.object(batch, "capture_clean_source_snapshot", return_value=snapshot),
                patch.object(batch, "assert_source_snapshot_unchanged"),
                patch.object(batch, "load_questions", return_value=questions),
                patch.object(batch, "_warm_harness_module", return_value=warm_module),
                patch.object(batch.uuid, "uuid4", return_value="batch-id"),
            ):
                code = batch.main()
            batch_dir = root / "batches" / "warm-batch-id"
            rows = [
                json.loads(line)
                for line in (batch_dir / "summary.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]
            self.assertEqual(code, 1)
            self.assertEqual(len(resource_args), 1)
            self.assertEqual(calls, ["q1", "q2", "q3"])
            self.assertEqual([row["ordinal"] for row in rows], [1, 2, 3])
            self.assertEqual(
                [row["status"] for row in rows],
                ["ANSWER", "NO_UNIQUE_RECORD", "ANSWER"],
            )
            self.assertTrue((root / "records" / "run-q1" / "result.json").is_file())
            self.assertTrue((root / "records" / "run-q3" / "result.json").is_file())
            self.assertIn(
                "isolated failure",
                (batch_dir / "02_q2.log").read_text(encoding="utf-8"),
            )
            metadata = json.loads(
                (batch_dir / "metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                metadata["execution_mode"],
                "warm_persistent",
            )


class LocalRunIsolationTests(unittest.TestCase):
    def test_shared_resources_still_create_independent_run_ids_and_records(self):
        configuration = frozen_configuration()
        first_args = local.build_frozen_run_args(
            "first",
            "q1",
            configuration,
            Path("/records"),
            "a" * 40,
            "c" * 64,
        )
        second_args = local.build_frozen_run_args(
            "second",
            "q2",
            configuration,
            Path("/records"),
            "a" * 40,
            "c" * 64,
        )
        snapshot = SourceSnapshot(
            git_commit="a" * 40,
            git_tree="b" * 40,
            source_manifest_sha256="c" * 64,
        )
        records = []
        def make_record(**kwargs):
            record = SimpleNamespace(
                directory=Path("/records") / kwargs["run_id"],
                trace_sink=object(),
                record_skill_attempt=Mock(),
            )
            record.finalize = Mock(return_value=record.directory / "result.json")
            records.append(record)
            return record
        def outcome(run_id):
            return SimpleNamespace(
                status=local.OutcomeStatus.ANSWER,
                termination_reason=None,
                abstention_reason=None,
                state=SimpleNamespace(
                    run_id=run_id,
                    retrieval_rounds_used=1,
                    accepted_provision_ids=set(),
                ),
                candidate_answer_status=None,
                candidate_answer_basis=None,
                errors=[],
                answer="answer",
                candidate_answer=None,
            )
        runner = Mock()
        runner.run.side_effect = lambda _question, run_id: outcome(run_id)
        resources = SimpleNamespace(build_runner=Mock(return_value=runner))
        with (
            patch.object(local, "ExperimentRecord", side_effect=make_record),
            patch.object(local, "HarnessRunner", return_value=runner),
            patch.object(local, "CitationIntegrityChecker"),
            patch.object(local, "assert_source_snapshot_unchanged"),
            patch.object(local.uuid, "uuid4", side_effect=["run-one", "run-two"]),
        ):
            first = local.run_question(
                first_args,
                source_snapshot=snapshot,
                resources=resources,
            )
            second = local.run_question(
                second_args,
                source_snapshot=snapshot,
                resources=resources,
            )
        self.assertEqual(
            [first.summary["run_id"], second.summary["run_id"]],
            ["run-one", "run-two"],
        )
        self.assertEqual(
            [str(record.directory) for record in records],
            ["/records/run-one", "/records/run-two"],
        )
        self.assertEqual(runner.run.call_args_list[0].kwargs["run_id"], "run-one")
        self.assertEqual(runner.run.call_args_list[1].kwargs["run_id"], "run-two")
        self.assertEqual(resources.build_runner.call_count, 2)


class FrozenArgumentParityTests(unittest.TestCase):
    def test_direct_warm_args_mirror_every_legacy_child_configuration_flag(self):
        configuration = frozen_configuration()
        configuration.update(
            {
                "model": "frozen-model",
                "ollama_endpoint": "http://endpoint",
                "s1_max_tokens": 5000,
                "s1_truncation_retry_max_tokens": 9000,
                "rerank_pool_k": 120,
                "final_top_k": 20,
                "rerank_query_mode": "per_request",
                "candidate_selection": "evidence_balanced",
                "per_evidence_min_k": 2,
                "candidate_budget_scope": "per_round",
                "dedup_mode": "legal_text_alias",
                "rerank_document_mode": "statute_and_body",
            }
        )
        snapshot = SourceSnapshot(
            git_commit="a" * 40,
            git_tree="b" * 40,
            source_manifest_sha256="c" * 64,
        )
        command = batch.build_run_command(
            Path("/python"),
            "question",
            "q1",
            configuration,
            Path("/records"),
            snapshot,
        )
        args = local.build_frozen_run_args(
            "question",
            "q1",
            configuration,
            Path("/records"),
            snapshot.git_commit,
            snapshot.source_manifest_sha256,
        )
        child_values = {
            command[index]: command[index + 1]
            for index in range(3, len(command), 2)
        }
        expected = {
            "--retriever": args.retriever,
            "--model": args.model,
            "--ollama-endpoint": args.ollama_endpoint,
            "--num-ctx": args.num_ctx,
            "--s1-max-tokens": args.s1_max_tokens,
            "--s1-truncation-retry-max-tokens": (
                args.s1_truncation_retry_max_tokens
            ),
            "--rounds": args.rounds,
            "--requests": args.requests,
            "--question-id": args.question_id,
            "--condition": args.condition,
            "--seed": args.seed,
            "--rerank-pool-k": args.rerank_pool_k,
            "--final-top-k": args.final_top_k,
            "--rerank-query-mode": args.rerank_query_mode,
            "--candidate-selection": args.candidate_selection,
            "--per-evidence-min-k": args.per_evidence_min_k,
            "--candidate-budget-scope": args.candidate_budget_scope,
            "--dedup-mode": args.dedup_mode,
            "--rerank-document-mode": args.rerank_document_mode,
            "--input-format": args.input_format,
            "--record-dir": args.record_dir,
            "--expected-git-commit": args.expected_git_commit,
            "--expected-source-manifest-sha256": (
                args.expected_source_manifest_sha256
            ),
        }
        for flag, value in expected.items():
            self.assertEqual(child_values[flag], str(value), flag)
        self.assertEqual(args.skills_root, local.PROJECT_ROOT / "skills")
        self.assertIsNone(args.result_file)

    def test_canonical_rerank_cli_rejects_nonpositive_bounds(self):
        with patch(
            "sys.argv",
            [
                "run_local_harness.py",
                "question",
                "--canonical-rerank-query-max-characters",
                "0",
            ],
        ):
            with self.assertRaises(SystemExit):
                local.parse_args()

    def test_canonical_rerank_opt_in_is_frozen_for_direct_and_child_paths(self):
        configuration = frozen_configuration()
        configuration.update({
            "canonical_rerank_query_missing_only": True,
            "canonical_rerank_query_max_characters": 321,
            "canonical_rerank_query_max_token_like_units": 45,
        })
        snapshot = SourceSnapshot("a" * 40, "b" * 40, "c" * 64)
        command = batch.build_run_command(
            Path("/python"), "question", "q1", configuration, Path("/records"), snapshot
        )
        args = local.build_frozen_run_args(
            "question", "q1", configuration, Path("/records"),
            snapshot.git_commit, snapshot.source_manifest_sha256,
        )

        self.assertIn("--canonical-rerank-query-missing-only", command)
        self.assertEqual(
            command[command.index("--canonical-rerank-query-max-characters") + 1],
            "321",
        )
        self.assertEqual(
            command[
                command.index("--canonical-rerank-query-max-token-like-units") + 1
            ],
            "45",
        )
        self.assertTrue(args.canonical_rerank_query_missing_only)
        self.assertEqual(args.canonical_rerank_query_max_characters, 321)
        self.assertEqual(args.canonical_rerank_query_max_token_like_units, 45)
