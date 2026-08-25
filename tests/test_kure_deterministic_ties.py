import unittest

import numpy as np

from retrieval.persistent import KureExactIndexSearcher


def provision_id_ranks(provision_ids):
    order = np.argsort(np.asarray(provision_ids), kind="stable")
    ranks = np.empty(len(provision_ids), dtype=np.int64)
    ranks[order] = np.arange(len(provision_ids))
    return ranks


def deterministic_provision_ids(rows, top_k):
    provision_ids = [provision_id for provision_id, _score in rows]
    scores = np.asarray([score for _provision_id, score in rows], dtype=np.float32)
    indexes = KureExactIndexSearcher._deterministic_top_k_indexes(
        scores,
        provision_id_ranks(provision_ids),
        top_k,
    )
    return [provision_ids[index] for index in indexes]


class KureDeterministicTieTests(unittest.TestCase):
    def test_exact_equal_scores_use_provision_id_ascending(self):
        rows = [("provision-c", 0.75), ("provision-a", 0.75), ("provision-b", 0.75)]
        self.assertEqual(
            deterministic_provision_ids(rows, 3),
            ["provision-a", "provision-b", "provision-c"],
        )

    def test_cutoff_tie_group_larger_than_k_is_fully_deterministic(self):
        rows = [
            ("provision-high", 0.90),
            ("provision-d", 0.50),
            ("provision-c", 0.50),
            ("provision-a", 0.50),
            ("provision-b", 0.50),
            ("provision-low", 0.10),
        ]
        self.assertEqual(
            deterministic_provision_ids(rows, 3),
            ["provision-high", "provision-a", "provision-b"],
        )

    def test_input_order_and_repeated_calls_do_not_change_tie_result(self):
        rows = [
            ("provision-30", 0.70),
            ("provision-10", 0.80),
            ("provision-20", 0.80),
            ("provision-40", 0.70),
        ]
        expected = ["provision-10", "provision-20", "provision-30"]
        self.assertEqual(deterministic_provision_ids(rows, 3), expected)
        self.assertEqual(deterministic_provision_ids(list(reversed(rows)), 3), expected)
        self.assertEqual(deterministic_provision_ids(rows, 3), expected)

    def test_unequal_scores_remain_descending(self):
        rows = [
            ("provision-low", 0.10),
            ("provision-top", 0.95),
            ("provision-middle", 0.50),
        ]
        self.assertEqual(
            deterministic_provision_ids(rows, 3),
            ["provision-top", "provision-middle", "provision-low"],
        )

    def test_non_finite_score_is_rejected(self):
        ranks = np.asarray([0, 1], dtype=np.int64)
        for score in (np.nan, np.inf, -np.inf):
            with self.subTest(score=score):
                with self.assertRaisesRegex(ValueError, "similarity scores must be finite"):
                    KureExactIndexSearcher._deterministic_top_k_indexes(
                        np.asarray([0.5, score], dtype=np.float32), ranks, 1
                    )


if __name__ == "__main__":
    unittest.main()
