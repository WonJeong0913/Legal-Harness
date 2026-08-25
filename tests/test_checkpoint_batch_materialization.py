import hashlib
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from scripts import evaluate_dev_runs as evaluator
from scripts import materialize_checkpoint_batch as checkpoint


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CheckpointBatchMaterializationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.configuration = {
            "condition": "checkpoint-fixture",
            "retriever": "kure",
            "model": "legal-harness-qwen38-q8",
            "seed": 0,
            "num_ctx": 32768,
        }
        self.snapshot = {
            "git_commit": "a" * 40,
            "git_tree": "b" * 40,
            "source_manifest_sha256": "c" * 64,
        }
        self.entries = [
            {"ordinal": ordinal, "question_id": "q%d" % ordinal, "n_hops": 1}
            for ordinal in range(1, 5)
        ]

    def tearDown(self):
        self.temporary.cleanup()

    def _record(self, question_id, run_id, status, configuration, snapshot):
        record_directory = self.root / "records" / (question_id + "-" + run_id)
        write_json(
            record_directory / "metadata.json",
            {
                "run_id": run_id,
                "question_id": question_id,
                "configuration": configuration,
                "source_snapshot": snapshot,
            },
        )
        write_json(
            record_directory / "result.json",
            {
                "run_id": run_id,
                "status": status,
                "state": {"candidate_provisions": []},
            },
        )
        return record_directory

    def _batch(self, name, start, end, configuration=None, snapshot=None, run_ids=None):
        configuration = dict(configuration or self.configuration)
        snapshot = dict(snapshot or self.snapshot)
        run_ids = dict(run_ids or {})
        directory = self.root / name
        manifest = {
            "manifest_schema_version": "1.0",
            "name": name,
            "source_dataset": {"path": "data/test.parquet", "sha256": "d" * 64},
            "selection": {"entry_count": len(self.entries)},
            "frozen_configuration": configuration,
            "entries": self.entries,
        }
        write_json(directory / "manifest.json", manifest)
        rows = []
        for entry in self.entries[start - 1 : end]:
            ordinal = entry["ordinal"]
            status = "EXECUTION_FAILURE" if ordinal == 2 else "ANSWER"
            run_id = run_ids.get(ordinal, "run-%d" % ordinal)
            record_directory = self._record(
                entry["question_id"], run_id, status, configuration, snapshot
            )
            rows.append(
                {
                    "ordinal": ordinal,
                    "question_id": entry["question_id"],
                    "n_hops": entry["n_hops"],
                    "record_directory": str(record_directory),
                    "status": status,
                    "exit_code": 1 if status == "EXECUTION_FAILURE" else 0,
                    "errors": ["fixture failure"] if status == "EXECUTION_FAILURE" else [],
                }
            )
        write_jsonl(directory / "summary.jsonl", rows)
        write_json(
            directory / "metadata.json",
            {
                "batch_id": name,
                "configuration": configuration,
                "source_snapshot": snapshot,
                "start_ordinal": start,
                "end_ordinal": end,
                "entry_count": len(rows),
                "completed_at_utc": "2026-08-25T00:00:00+00:00",
                "batch_manifest_sha256": sha256(directory / "manifest.json"),
            },
        )
        return directory, rows

    def test_materializes_contiguous_chunks_with_absolute_records_and_provenance(self):
        first, first_rows = self._batch("chunk-001-002", 1, 2)
        second, second_rows = self._batch("chunk-003-004", 3, 4)
        stale_range_metadata = json.loads((second / "metadata.json").read_text(encoding="utf-8"))
        stale_range_metadata["start_ordinal"] = 1
        stale_range_metadata["end_ordinal"] = None
        write_json(second / "metadata.json", stale_range_metadata)
        source_paths = [
            path
            for batch_directory in (first, second)
            for path in (
                batch_directory / "manifest.json",
                batch_directory / "metadata.json",
                batch_directory / "summary.jsonl",
            )
        ]
        source_hashes = {path: sha256(path) for path in source_paths}
        output = self.root / "checkpoint-004"

        result = checkpoint.materialize_cumulative_batch([second, first], output)

        self.assertEqual(result["entry_count"], 4)
        self.assertEqual((result["ordinal_start"], result["ordinal_end"]), (1, 4))
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        rows = [
            json.loads(line)
            for line in (output / "summary.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual([entry["ordinal"] for entry in manifest["entries"]], [1, 2, 3, 4])
        self.assertEqual(manifest["selection"]["entry_count"], 4)
        self.assertEqual(rows, first_rows + second_rows)
        self.assertEqual(rows[1]["status"], "EXECUTION_FAILURE")
        self.assertEqual(rows[1]["record_directory"], first_rows[1]["record_directory"])
        self.assertEqual(
            [item["batch_directory"] for item in metadata["source_batches"]],
            [str(first.resolve()), str(second.resolve())],
        )
        self.assertEqual(
            [item["summary_sha256"] for item in metadata["source_batches"]],
            [sha256(first / "summary.jsonl"), sha256(second / "summary.jsonl")],
        )
        self.assertEqual(
            (metadata["source_batches"][1]["ordinal_start"], metadata["source_batches"][1]["ordinal_end"]),
            (3, 4),
        )
        self.assertEqual(metadata["source_batches"][1]["metadata_start_ordinal"], 1)
        self.assertTrue(metadata["has_execution_failure"])
        self.assertEqual({path: sha256(path) for path in source_paths}, source_hashes)

        questions = {
            entry["question_id"]: {"n_hops": entry["n_hops"]}
            for entry in self.entries
        }
        joined = evaluator._join_inputs(output, manifest, questions)
        self.assertEqual(len(joined), 4)
        self.assertEqual(str(joined[0][2]), first_rows[0]["record_directory"])

    def test_through_ordinal_materializes_exact_prefix_from_full_batch(self):
        full, rows = self._batch("full-001-004", 1, 4)
        output = self.root / "checkpoint-003"

        checkpoint.materialize_cumulative_batch(
            [full], output, through_ordinal=3
        )

        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        materialized_rows = [
            json.loads(line)
            for line in (output / "summary.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual([entry["ordinal"] for entry in manifest["entries"]], [1, 2, 3])
        self.assertEqual([row["ordinal"] for row in materialized_rows], [1, 2, 3])
        self.assertEqual(materialized_rows, rows[:3])
        self.assertEqual((metadata["ordinal_start"], metadata["ordinal_end"]), (1, 3))

        with self.assertRaisesRegex(
            checkpoint.CheckpointMaterializationError,
            "must contain every ordinal from 1 through 5",
        ):
            checkpoint.materialize_cumulative_batch(
                [full], self.root / "checkpoint-005", through_ordinal=5
            )

    def test_legacy_absolute_record_path_is_validated_without_rewriting_summary(self):
        first, rows = self._batch("chunk-001-002", 1, 2)
        legacy_run_id = "legacy-run"
        actual_directory = self.root / "records" / "runs" / "scope" / legacy_run_id
        write_json(
            actual_directory / "metadata.json",
            {
                "run_id": legacy_run_id,
                "question_id": "q1",
                "configuration": self.configuration,
                "source_snapshot": self.snapshot,
            },
        )
        write_json(
            actual_directory / "result.json",
            {
                "run_id": legacy_run_id,
                "status": "ANSWER",
                "state": {"candidate_provisions": []},
            },
        )
        legacy_directory = Path("/legacy/records/runs/scope") / legacy_run_id
        rows[0]["record_directory"] = str(legacy_directory)
        write_jsonl(first / "summary.jsonl", rows)
        output = self.root / "checkpoint-002"

        with patch.object(checkpoint, "PROJECT_ROOT", self.root):
            checkpoint.materialize_cumulative_batch([first], output)

        materialized_rows = [
            json.loads(line)
            for line in (output / "summary.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(materialized_rows[0]["record_directory"], str(legacy_directory))

    def test_rejects_incompatible_configuration_without_creating_output(self):
        first, _ = self._batch("chunk-001-002", 1, 2)
        changed = dict(self.configuration)
        changed["model"] = "different-model"
        second, _ = self._batch("chunk-003-004", 3, 4, configuration=changed)
        output = self.root / "checkpoint"

        with self.assertRaisesRegex(checkpoint.CheckpointMaterializationError, "model mismatch"):
            checkpoint.materialize_cumulative_batch([first, second], output)

        self.assertFalse(output.exists())

    def test_rejects_incompatible_source_snapshot_without_creating_output(self):
        first, _ = self._batch("chunk-001-002", 1, 2)
        changed = dict(self.snapshot)
        changed["git_tree"] = "d" * 40
        second, _ = self._batch("chunk-003-004", 3, 4, snapshot=changed)
        output = self.root / "checkpoint"

        with self.assertRaisesRegex(checkpoint.CheckpointMaterializationError, "source_snapshot mismatch"):
            checkpoint.materialize_cumulative_batch([first, second], output)

        self.assertFalse(output.exists())

    def test_rejects_ordinal_gap_duplicate_run_and_existing_output(self):
        first, _ = self._batch("chunk-001-002", 1, 2)
        gap, _ = self._batch("chunk-004-004", 4, 4)
        with self.assertRaisesRegex(checkpoint.CheckpointMaterializationError, "not contiguous"):
            checkpoint.materialize_cumulative_batch([first, gap], self.root / "gap")

        second, _ = self._batch("chunk-003-004", 3, 4, run_ids={3: "run-1"})
        with self.assertRaisesRegex(checkpoint.CheckpointMaterializationError, "duplicate ordinal, question_id, or run_id"):
            checkpoint.materialize_cumulative_batch([first, second], self.root / "duplicate-run")

        existing = self.root / "existing"
        existing.mkdir()
        with self.assertRaisesRegex(checkpoint.CheckpointMaterializationError, "refusing to overwrite"):
            checkpoint.materialize_cumulative_batch([first], existing)

    def test_rejects_relative_record_directory(self):
        first, rows = self._batch("chunk-001-002", 1, 2)
        rows[0]["record_directory"] = "records/not-absolute"
        write_jsonl(first / "summary.jsonl", rows)
        metadata = json.loads((first / "metadata.json").read_text(encoding="utf-8"))
        metadata["entry_count"] = len(rows)
        write_json(first / "metadata.json", metadata)

        with self.assertRaisesRegex(checkpoint.CheckpointMaterializationError, "must be absolute"):
            checkpoint.materialize_cumulative_batch([first], self.root / "relative")


if __name__ == "__main__":
    unittest.main()
