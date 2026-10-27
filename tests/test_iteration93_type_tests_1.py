"""Iteration 93: type-tests-1 (ISINTEGER, ISINT64, ISDOUBLE, ISDECIMAL, ISCURRENCY).

Live answers frozen from Power BI Desktop (see tools/parity/dax_battery_type_tests.json
and docs/plans/2026-10-26-type-tests-1.md).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

STAYS_REFUSED = [
    "ISINTEGER()",
    "ISINTEGER(1,2)",
    "ISDOUBLE()",
    "ISDECIMAL(1,2)",
    "ISCURRENCY()",
    "ISINT64(1,2)",
    "ISINTEGER(Facts)",
    "ISINTEGER(Facts[Quantity])",
    "ISDOUBLE(Facts[Sales])",
    'ISINTEGER(IF(TRUE(),1,"a"))',
    "ISCURRENCY(UNKNOWNFN(1))",
]


class TypeTests1Test(unittest.TestCase):
    def test_battery_items_match(self) -> None:
        """Every item in dax_battery_type_tests.json must match Power BI (answers match, errors rejected)."""
        battery_path = Path(__file__).resolve().parents[1] / "tools" / "parity" / "dax_battery_type_tests.json"
        saved = json.loads(battery_path.read_text())
        mismatches = []
        for item in saved["items"]:
            expr = item["expr"]
            expected = item["powerbi"]
            actual = dax.local(expr)
            st = status(expected, actual)
            if st != "match":
                mismatches.append((expr, expected, actual, st))
        self.assertEqual([], mismatches, f"Mismatches found: {len(mismatches)} of {len(saved['items'])}")

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
