"""Iteration 94: tocsv-tojson-1 (TOCSV and TOJSON).

Live answers frozen from Power BI Desktop (see tools/parity/dax_battery_tocsv_tojson.json,
tools/parity/dax_battery_round2.json, and docs/plans/2026-10-26-tocsv-tojson-1.md).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

STAYS_REFUSED = [
    'TOCSV("a")',
    'TOCSV(ROW("a",1,"a",2))',
    "TOJSON(Facts,1,2)",
    "COUNTROWS(TOJSON(Facts))",
    'TOJSON(ROW("a",UNICHAR(1)))',
]


class TocsvTojson1Test(unittest.TestCase):
    def test_battery_items_match(self) -> None:
        """Every item in dax_battery_tocsv_tojson.json must match Power BI."""
        battery_path = Path(__file__).resolve().parents[1] / "tools" / "parity" / "dax_battery_tocsv_tojson.json"
        saved = json.loads(battery_path.read_text())
        mismatches = []
        for item in saved["items"]:
            expr = item["expr"]
            expected = item["powerbi"]
            actual = dax.local(expr)
            st = status(expected, actual)
            if st != "match":
                mismatches.append((expr, expected, actual, st))
        self.assertEqual([], mismatches, f"Mismatches found in dax_battery_tocsv_tojson: {len(mismatches)} of {len(saved['items'])}")

    def test_round2_items_match(self) -> None:
        """The 8 TOCSV/TOJSON answer items from dax_battery_round2.json must match Power BI."""
        battery_path = Path(__file__).resolve().parents[1] / "tools" / "parity" / "dax_battery_round2.json"
        saved = json.loads(battery_path.read_text())
        mismatches = []
        round2_items = [
            item for item in saved["items"]
            if ("TOCSV" in item["expr"] or "TOJSON" in item["expr"])
            and not item["powerbi"].startswith("ERR:")
        ]
        self.assertEqual(len(round2_items), 8, f"Expected 8 round2 TOCSV/TOJSON items, found {len(round2_items)}")
        for item in round2_items:
            expr = item["expr"]
            expected = item["powerbi"]
            actual = dax.local(expr)
            st = status(expected, actual)
            if st != "match":
                mismatches.append((expr, expected, actual, st))
        self.assertEqual([], mismatches, f"Mismatches found in round2: {len(mismatches)} of {len(round2_items)}")

    def test_negative_cases_stay_refused(self) -> None:
        """Explicit check for refused negative cases."""
        for expr in STAYS_REFUSED:
            res = dax.local(expr)
            self.assertTrue(
                res.startswith("LOCAL-REJECT"),
                f"Expected LOCAL-REJECT for {expr}, got {res}",
            )


if __name__ == "__main__":
    unittest.main()
