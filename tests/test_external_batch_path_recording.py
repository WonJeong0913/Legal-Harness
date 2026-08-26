import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.source_snapshot import SourceSnapshot
from scripts import run_bm25_bge_pilot_batch as batch


class ExternalBatchPathRecordingTests(unittest.TestCase):
    def test_external_manifest_and_log_paths_are_recorded_absolutely_without_execution(self):
        with (
            tempfile.TemporaryDirectory(dir=batch.PROJECT_ROOT) as project_temporary,
            tempfile.TemporaryDirectory() as external_temporary,
        ):
            project_root = Path(project_temporary)
            external_root = Path(external_temporary)
            dataset = project_root / "questions.parquet"
            dataset.write_bytes(b"fixture")
            manifest_path = external_root / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "name": "external-path-recording",
                        "source_dataset": {
                            "path": str(dataset.relative_to(batch.PROJECT_ROOT)),
                            "sha256": batch.sha256(dataset),
                        },
                        "frozen_configuration": {
                            "condition": "external-path-recording",
                            "retriever": "stub",
                            "model": "test-model",
                            "num_ctx": 32768,
                            "total_retrieval_rounds": 3,
                            "total_retrieval_requests": 9,
                            "seed": 0,
                            "ollama_endpoint": "http://127.0.0.1:11435/api/generate",
                        },
                        "entries": [
                            {"ordinal": 1, "question_id": "q1", "n_hops": 1}
                        ],
                    }
                ),
                encoding="utf-8",
            )
            batch_root = external_root / "batches"
            args = SimpleNamespace(
                manifest=manifest_path,
                start_ordinal=1,
                end_ordinal=1,
                batch_name="external-path",
                comparison_manifest=None,
                python=Path(sys.executable),
                record_root=external_root / "records",
                batch_log_root=batch_root,
                warm_resources=True,
            )
            snapshot = SourceSnapshot(
                git_commit="a" * 40,
                git_tree="b" * 40,
                source_manifest_sha256="c" * 64,
            )

            class Resources:
                def __init__(self, _args):
                    pass

            def build(question, question_id, _configuration, record_dir, *_snapshot):
                return SimpleNamespace(
                    question=question,
                    question_id=question_id,
                    record_dir=record_dir,
                )

            def run(run_args, **_kwargs):
                result_directory = run_args.record_dir / "run-q1"
                result_directory.mkdir(parents=True)
                (result_directory / "result.json").write_text(
                    json.dumps({"status": "ANSWER", "errors": []}),
                    encoding="utf-8",
                )
                return SimpleNamespace(exit_code=0, rendered_output="stubbed")

            warm_module = SimpleNamespace(
                PersistentHarnessResources=Resources,
                build_frozen_run_args=build,
                run_question=run,
            )
            with (
                patch.object(batch, "parse_args", return_value=args),
                patch.object(batch, "capture_clean_source_snapshot", return_value=snapshot),
                patch.object(batch, "assert_source_snapshot_unchanged"),
                patch.object(
                    batch,
                    "load_questions",
                    return_value={"q1": {"question": "one", "background": "", "n_hops": 1}},
                ),
                patch.object(batch, "_warm_harness_module", return_value=warm_module),
                patch.object(batch.uuid, "uuid4", return_value="batch-id"),
            ):
                self.assertEqual(batch.main(), 0)

            batch_dir = batch_root / "external-path-batch-id"
            metadata = json.loads((batch_dir / "metadata.json").read_text(encoding="utf-8"))
            row = json.loads((batch_dir / "summary.jsonl").read_text(encoding="utf-8"))
            self.assertEqual(metadata["manifest"], str(manifest_path.resolve()))
            self.assertEqual(row["log_file"], str((batch_dir / "01_q1.log").resolve()))


if __name__ == "__main__":
    unittest.main()
