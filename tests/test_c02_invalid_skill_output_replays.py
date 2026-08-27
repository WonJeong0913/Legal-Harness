import json
from pathlib import Path
import unittest


FIXTURE = Path(__file__).parent / "fixtures/c02_invalid_skill_output_replays.json"


class C02InvalidSkillOutputReplayFixtureTests(unittest.TestCase):
    def test_all_retained_c02_invalid_output_replays_have_a_current_guard(self):
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

        self.assertEqual(
            fixture["schema_version"], "c22_c02_invalid_skill_output_replays_v1"
        )
        self.assertEqual(
            {
                item["ordinal"]: (item["question_id"], item["guard"])
                for item in fixture["cases"]
            },
            {
                42: ("qa_406_2hop_622", "C05"),
                54: ("qa_99_1hop_167", "C05"),
                65: ("qa_286_2hop_1091_rand", "C09"),
                83: ("qa_460_3hop_730", "C05"),
                99: ("qa_168_3hop_301", "C06"),
                120: ("qa_116_1hop_207", "C10"),
                152: ("qa_273_2hop_431", "C05"),
                202: ("qa_102_2hop_400_rand", "C22"),
            },
        )
        self.assertEqual(
            [item["guard"] for item in fixture["cases"]].count("C22"), 1
        )


if __name__ == "__main__":
    unittest.main()
