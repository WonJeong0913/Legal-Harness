import sys
import unittest
from unittest.mock import patch

from scripts.run_local_harness import parse_args


class RunLocalHarnessArgumentTests(unittest.TestCase):
    def test_kure_is_the_default_retriever(self):
        with patch.object(sys, "argv", ["run_local_harness.py", "질문"]):
            args = parse_args()

        self.assertEqual(args.retriever, "kure")
        self.assertFalse(args.article_family_sibling_rerank_expansion)
        self.assertEqual(args.article_family_expansion_trigger_top_k, 3)
        self.assertEqual(args.article_family_expansion_max_siblings_per_root, 4)
        self.assertEqual(args.article_family_expansion_max_siblings_per_request, 8)

    def test_article_family_expansion_is_explicitly_opt_in(self):
        with patch.object(
            sys,
            "argv",
            [
                "run_local_harness.py", "질문",
                "--article-family-sibling-rerank-expansion",
                "--article-family-expansion-trigger-top-k", "2",
                "--article-family-expansion-max-siblings-per-root", "3",
                "--article-family-expansion-max-siblings-per-request", "5",
            ],
        ):
            args = parse_args()

        self.assertTrue(args.article_family_sibling_rerank_expansion)
        self.assertEqual(args.article_family_expansion_trigger_top_k, 2)
        self.assertEqual(args.article_family_expansion_max_siblings_per_root, 3)
        self.assertEqual(args.article_family_expansion_max_siblings_per_request, 5)


if __name__ == "__main__":
    unittest.main()
