"""Text functions count UTF-16 code units, not code points, and UNICHAR/FIND follow Power BI's validity rules.

Every expected value is a live Power BI Desktop 2.157.879.0 answer (tests/fixtures_utf16_text.json); an ERR answer
must be refused by the app too.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools.dax_oracle_diff import local, same

ANSWERS = json.loads((Path(__file__).parent / "fixtures_utf16_text.json").read_text())


class Utf16TextTests(unittest.TestCase):
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
