import unittest
from pathlib import Path

from runtime.comparison_guard import (
    resolve_frozen_configuration,
    validate_retriever_comparison,
)


class RetrieverComparisonGuardTests(unittest.TestCase):
    @staticmethod
    def _manifest(retriever):
        configuration = {
            "condition": "condition-%s" % retriever,
            "retriever": retriever,
            "reranker": "bge",
            "model": "frozen-model",
            "seed": 0,
            "num_ctx": 32768,
            "total_retrieval_rounds": 3,
            "total_retrieval_requests": 9,
            "rerank_pool_k": 100,
            "final_top_k": 10,
        }
        if retriever == "kure":
            configuration["retriever_provenance"] = {
                "model_id": "nlpai-lab/KURE-v1",
                "weights_sha256": "a" * 64,
            }
        return {
            "source_dataset": {
                "path": "data/koblex/test.parquet",
                "sha256": "b" * 64,
            },
            "frozen_configuration": configuration,
            "entries": [
                {"ordinal": 1, "question_id": "q1", "n_hops": 1},
                {"ordinal": 2, "question_id": "q2", "n_hops": 2},
            ],
        }

    def test_only_retriever_condition_and_provenance_may_differ(self):
        primary = self._manifest("kure")
        reference = self._manifest("bm25")

        metadata = validate_retriever_comparison(
            primary,
            reference,
            Path("kure.json"),
            Path("bm25.json"),
        )

        self.assertEqual(
            metadata["status"], "VALIDATED_IDENTICAL_EXCEPT_RETRIEVER"
        )
        self.assertEqual(metadata["entry_count"], 2)
        self.assertEqual(metadata["primary_retriever"], "kure")
        self.assertEqual(len(metadata["comparable_configuration_sha256"]), 64)

    def test_model_or_budget_mismatch_fails_before_batch(self):
        for field, value in (
            ("model", "different-model"),
            ("total_retrieval_requests", 8),
            ("final_top_k", 20),
        ):
            with self.subTest(field=field):
                primary = self._manifest("kure")
                reference = self._manifest("bm25")
                primary["frozen_configuration"][field] = value
                with self.assertRaisesRegex(
                    RuntimeError,
                    "configuration mismatch outside allowed fields: %s" % field,
                ):
                    validate_retriever_comparison(
                        primary,
                        reference,
                        Path("kure.json"),
                        Path("bm25.json"),
                    )

    def test_ordered_question_mismatch_fails_before_batch(self):
        primary = self._manifest("kure")
        reference = self._manifest("bm25")
        reference["entries"] = reference["entries"][:1]

        with self.assertRaisesRegex(RuntimeError, "entry mismatch"):
            validate_retriever_comparison(
                primary,
                reference,
                Path("kure.json"),
                Path("bm25.json"),
            )

    def test_runtime_defaults_freeze_s1_s2_s3_and_stage_provenance(self):
        resolved = resolve_frozen_configuration({"retriever": "bm25"})

        self.assertEqual(resolved["s1_max_tokens"], 4096)
        self.assertEqual(resolved["s1_truncation_retry_max_tokens"], 8192)
        self.assertEqual(
            resolved["skill_max_tokens"]["provision_coverage_assessment"], 3072
        )
        self.assertEqual(
            resolved["skill_max_tokens"]["grounded_legal_answer_generation"], 3072
        )
        self.assertEqual(resolved["s3_public_answer_max_characters"], 800)
        self.assertTrue(
            resolved["retrieval_stage_provenance_required_for_evaluation"]
        )
        self.assertFalse(resolved["canonical_rerank_query_missing_only"])
        self.assertEqual(resolved["canonical_rerank_query_max_characters"], 512)
        self.assertEqual(resolved["canonical_rerank_query_max_token_like_units"], 96)

    def test_canonical_rerank_configuration_is_comparison_guarded(self):
        primary = self._manifest("kure")
        reference = self._manifest("bm25")
        primary["frozen_configuration"][
            "canonical_rerank_query_missing_only"
        ] = True

        with self.assertRaisesRegex(
            RuntimeError,
            "configuration mismatch outside allowed fields: canonical_rerank_query_missing_only",
        ):
            validate_retriever_comparison(
                primary, reference, Path("kure.json"), Path("bm25.json")
            )


if __name__ == "__main__":
    unittest.main()
