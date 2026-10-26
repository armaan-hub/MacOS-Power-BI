"""Iteration 91: xnpv 1 (the DAX function XNPV).

Live answers frozen from Power BI Desktop (see tools/parity/dax_battery_xnpv.json and docs/plans/2026-10-26-xnpv-1.md).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status


STAYS_REFUSED = [
    "XNPV()",
    "XNPV(1,2,3,4)",
    'XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),[v],[d],0.1,5)',
    'XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),[v],[d],-1)',
    'XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),[v],IF([n]=365,BLANK(),[d]),0.1)',
    'XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),[v],[d],"a")',
    'XNPV(Facts,Facts[Region],DATE(2020,1,1),0.1)',
]


class Xnpv1Test(unittest.TestCase):
    def test_battery_items_match(self) -> None:
        """Every item in dax_battery_xnpv.json must match Power BI (answers match, errors rejected)."""
        battery_path = Path(__file__).resolve().parents[1] / "tools" / "parity" / "dax_battery_xnpv.json"
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

    def test_whole_review_battery_never_differs(self) -> None:
        """Claude's review battery (258 live answers beyond the planned 107: types, untaken branches, date bounds, rate shapes) must never differ."""
        path = Path(__file__).resolve().parents[1] / "tools" / "parity" / "dax_battery_xnpv2.json"
        bad = []
        for item in json.loads(path.read_text())["items"]:
            actual = dax.local(item["expr"])
            if status(item["powerbi"], actual) in {"DIFF", "CRASH"}:
                bad.append((item["expr"], item["powerbi"], actual))
        self.assertEqual([], bad)

    def test_review_refusals(self) -> None:
        """Shapes Power BI answers erratically or in a type the app does not model stay refused."""
        table = 'ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365}}),"d",DATE(2020,1,1)+[n])'
        for expr in [
            f"XNPV({table},CURRENCY(5),[d],0.1)",
            f"XNPV({table},[v],0/0,0.1)",
            f"XNPV({table},[v],1E12,0.1)",
            f"XNPV({table},[v],2958466,0.1)",
            "XNPV(Facts,IF(Facts[Quantity]>10,\"a\",BLANK()),DATE(2020,1,1),0.1)",
            "IF(FALSE(),XNPV(Facts,Facts[Region],DATE(2020,1,1),0.1),1)",
            "IFERROR(1,XNPV(Facts,Facts[Region],DATE(2020,1,1),0.1))",
            "COALESCE(1,XNPV(Facts,Facts[Region],DATE(2020,1,1),0.1))",
            "IF(FALSE(),XNPV(Facts,Facts[Quantity],DATE(2020,1,1),Facts[Quantity]),1)",
        ]:
            self.assertTrue(dax.local(expr).startswith("LOCAL-REJECT"), expr)


if __name__ == "__main__":
    unittest.main()
