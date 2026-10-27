"""Iteration 92: scalar-misc-2 (IF.EAGER, ERROR, CUSTOMDATA, ISAFTER, NAMEOF, TABLEOF, EVALUATEANDLOG, ALLCROSSFILTERED).

Live answers frozen from Power BI Desktop (see tools/parity/dax_battery_scalar_misc2.json and docs/plans/2026-10-26-scalar-misc-2.md).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status


STAYS_REFUSED = [
    "ERROR(1)",
    'ERROR("x"&"y")',
    "CUSTOMDATA(1)",
    "NAMEOF(SUM(Facts[Quantity]))",
    "TABLEOF(Facts)",
    'ISAFTER(1,"a")',
    'IFERROR(EVALUATEANDLOG(ERROR("x")),5)',
    "COUNTROWS(ALLCROSSFILTERED(Facts))",
]


class ScalarMisc2Test(unittest.TestCase):
    def test_battery_items_match(self) -> None:
        """Every item in dax_battery_scalar_misc2.json must match Power BI (answers match, errors rejected)."""
        battery_path = Path(__file__).resolve().parents[1] / "tools" / "parity" / "dax_battery_scalar_misc2.json"
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

    def test_review_batteries_never_differ(self) -> None:
        """Claude's review probes (714 shapes beyond the plan): the app never answers differently from Power BI."""
        root = Path(__file__).resolve().parents[1] / "tools" / "parity"
        bad = []
        for name in ("dax_battery_scalar_misc2_extra", "dax_battery_scalar_misc2_extra2"):
            for item in json.loads((root / f"{name}.json").read_text())["items"]:
                actual = dax.local(item["expr"])
                if status(item["powerbi"], actual) in {"DIFF", "CRASH"}:
                    bad.append((item["expr"], item["powerbi"], actual))
        self.assertEqual([], bad)

    def test_review_refusals(self) -> None:
        """Shapes Power BI throws or orders by culture stay refused."""
        for expr in [
            'IFERROR(IF.EAGER(FALSE(),1,ERROR("x")),9)',
            'IFERROR(IF.EAGER(TRUE(),VALUE("x"),2),7)',
            'SUMX(Facts,IF.EAGER(Facts[Quantity]>10,ERROR("big"),1))',
            "CUSTOMDATA()=0",
            "MAX(CUSTOMDATA(),1)",
            "SUMX(Facts,CUSTOMDATA())",
            'ISAFTER("\u00e4","z")',
            'IFERROR(ISAFTER(1,1,5,2,1),TRUE())',
            "IF(FALSE(),ISAFTER(1,1,5,2,1),1)",
            'CONCATENATEX(TABLEOF(Facts[Region]),Facts[Region],",")',
            "EVALUATEANDLOG(1,Facts[Region])",
            '"a\u0308"="\u00e4"',
        ]:
            self.assertTrue(dax.local(expr).startswith("LOCAL-REJECT"), expr)


if __name__ == "__main__":
    unittest.main()
