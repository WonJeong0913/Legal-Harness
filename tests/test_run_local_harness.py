import sys
import unittest
from unittest.mock import patch

from scripts.run_local_harness import parse_args


class RunLocalHarnessArgumentTests(unittest.TestCase):
    def test_kure_is_the_default_retriever(self):
        with patch.object(sys, "argv", ["run_local_harness.py", "질문"]):
            args = parse_args()

        self.assertEqual(args.retriever, "kure")


if __name__ == "__main__":
    unittest.main()
