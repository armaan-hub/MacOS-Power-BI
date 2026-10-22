"""&&, ||, AND and OR evaluate both operands; only a plan-time constant can decide; FILTER/CALCULATE conjuncts run lazily.

Every expected value is a live Power BI Desktop 2.157.879.0 answer (tests/fixtures_evaluation_order.json, taken from the
2,437-probe set behind tools/parity/dax_battery_evaluation_order.json). A Power BI error must be an error in the app too.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.dax_oracle_diff import local, same

ANSWERS = json.loads((Path(__file__).parent / "fixtures_evaluation_order.json").read_text())


class EvaluationOrderTests(unittest.TestCase):
    def test_every_answer_matches_power_bi(self) -> None:
        for item in ANSWERS:
            with self.subTest(expression=item["expr"]):
                ours = local(item["expr"])
                if item["powerbi"].startswith("ERR"):
                    self.assertTrue(ours.startswith("LOCAL-REJECT"), ours)
                else:
                    self.assertTrue(same(item["powerbi"], ours), f"Power BI {item['powerbi']!r}, app {ours!r}")


if __name__ == "__main__":
    unittest.main()
