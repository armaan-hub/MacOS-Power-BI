"""A bare NOT (no parenthesis) is a prefix operator: looser than comparison and &, tighter than && and ||.

Every expected value is a live Power BI Desktop 2.157.879.0 answer (tools/dax_battery_not_operator.json).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from analytics_studio.measures import evaluate_measures
from tools.dax_oracle_diff import local

ANSWERS = json.loads((Path(__file__).parent / "fixtures_not_operator.json").read_text())


class NotOperatorTests(unittest.TestCase):
    def test_every_answer_matches_power_bi(self) -> None:
        for item in ANSWERS:
            with self.subTest(expression=item["expr"]):
                self.assertEqual(local(item["expr"]), item["powerbi"])

    def test_not_in_front_of_a_measure_reference(self) -> None:
        """`NOT [Measure]` is a negation, not a table called NOT (Power BI answers on measures worth 5 and 11)."""
        answers = {
            "NOT [mN] > 3": False, "NOT [mN] > 7": True, "NOT [mC] = 11": False, "NOT [mC] > 5 && [mN] = 5": False,
            "NOT [mC] > 50 && [mN] = 5": True, "NOT [mC] > 5 || [mN] = 4": False, "NOT [mN]": False, "NOT [mN] - 5": True,
            "NOT [mN] - 5 = 0": False,
        }
        for expression, expected in answers.items():
            with self.subTest(expression=expression):
                measures = [{"name": "mN", "expression": "5"}, {"name": "mC", "expression": "11"}, {"name": "P__", "expression": expression}]
                result = evaluate_measures(measures, [{"x": "1"}], ["x"], "T", measure_names=["mN", "mC", "P__"])
                self.assertEqual(result["P__"], expected)


if __name__ == "__main__":
    unittest.main()
