"""Task 209b: split steps that keep missing_part "" (old explicit default) emit and parse back unchanged."""

from __future__ import annotations

import unittest

from analytics_studio.power_query_m import parse_m_script, steps_to_m_script


BLANK_STEPS = [
    {"op": "split_column", "column": "A", "delimiter": ",", "missing_part": ""},
    {"op": "split_column_by_each_delimiter", "column": "A", "delimiter": ",", "missing_part": ""},
]


class BlankMissingPartRoundTripTests(unittest.TestCase):
    def test_emit_parse_emit_is_identical_for_both_ops(self) -> None:
        for step in BLANK_STEPS:
            with self.subTest(op=step["op"]):
                first = steps_to_m_script([step], "Q")
                self.assertTrue(first.count(', ""') >= 1, first)
                parsed = parse_m_script(first, "Q")
                self.assertEqual(steps_to_m_script(parsed, "Q"), first)

    def test_parse_keeps_blank_missing_part_for_both_ops(self) -> None:
        for step in BLANK_STEPS:
            with self.subTest(op=step["op"]):
                parsed = parse_m_script(steps_to_m_script([step], "Q"), "Q")
                self.assertEqual(len(parsed), 1)
                self.assertEqual(parsed[0].get("missing_part"), "")
                self.assertEqual(parsed[0]["op"], step["op"])

    def test_keyless_steps_emit_without_default_and_round_trip(self) -> None:
        for step in BLANK_STEPS:
            keyless = {k: v for k, v in step.items() if k != "missing_part"}
            with self.subTest(op=step["op"]):
                script = steps_to_m_script([keyless], "Q")
                self.assertFalse(script.rstrip().endswith(', "")'), script)
                parsed = parse_m_script(script, "Q")
                self.assertNotIn("missing_part", parsed[0])


if __name__ == "__main__":
    unittest.main()
