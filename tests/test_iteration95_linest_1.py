"""Iteration 95: linest-1 (LINEST and LINESTX).

Live answers frozen from Power BI Desktop (see tools/parity/dax_battery_linest.json
and docs/plans/2026-10-26-linest-1.md).

Power BI solves the regression in binary doubles and its last digits are rounding noise that cannot be reproduced,
so the text of a whole result (TOCSV, LEN(TOCSV)) stays refused. Every single value and every error must match.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

STAYS_REFUSED = [
    "TOCSV(LINEST())",
    "MAXX(LINEST(Facts[Quantity],Facts[Sales]),[Nope])",
    "TOCSV(LINESTX(Facts,Facts[Quantity],Facts[Region]))",
    "MAXX(LINEST(Facts[Sales],Facts[Quantity],FALSE()),[Intercept])",
]


class Linest1Test(unittest.TestCase):
    def test_battery_items_match(self) -> None:
        """Every item in dax_battery_linest.json is a match, or a refusal of the whole-result text; never a difference."""
        battery_path = Path(__file__).resolve().parents[1] / "tools" / "parity" / "dax_battery_linest.json"
        saved = json.loads(battery_path.read_text())
        wrong, matched = [], 0
        for item in saved["items"]:
            expr = item["expr"]
            actual = dax.local(expr)
            st = status(item["powerbi"], actual)
            if st == "match":
                matched += 1
            elif not (st == "gap-reject" and (expr.startswith("TOCSV(") or expr.startswith("LEN(TOCSV("))):
                wrong.append((expr, item["powerbi"], actual, st))
        self.assertEqual([], wrong)
        self.assertGreaterEqual(matched, 182)

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
