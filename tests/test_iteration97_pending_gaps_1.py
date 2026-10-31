"""Iteration 97: pending-gaps-1 (Part A: VAR scoping; Part B: scalar subqueries in filters).

Live answers frozen from Power BI Desktop (see tools/parity/dax_battery_var_scoping.json,
dax_battery_sdet_filters.json, dax_battery_round2.json, dax_battery_round3.json
and docs/plans/2026-10-29-pending-gaps-1.md).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status


class PendingGaps1PartATest(unittest.TestCase):
    def test_battery_var_scoping_items_match(self) -> None:
        """All 90 items in dax_battery_var_scoping.json must match Power BI Desktop."""
        battery_path = Path(__file__).resolve().parents[1] / "tools" / "parity" / "dax_battery_var_scoping.json"
        saved = json.loads(battery_path.read_text())
        items = saved["items"]
        self.assertEqual(len(items), 90, f"Expected 90 items, found {len(items)}")

        mismatches = []
        for item in items:
            expr = item["expr"]
            expected = item["powerbi"]
            actual = dax.local(expr)
            st = status(expected, actual)
            if st != "match":
                mismatches.append((expr, expected, actual, st))
        self.assertEqual([], mismatches, f"Mismatches found in var_scoping: {len(mismatches)} of {len(items)}")


class PendingGaps1PartBTest(unittest.TestCase):
    MATCHING_EXPRS = [
        # computed since Task 12 (a Variant beside a text column), listed under refusals until then
        'CALCULATE(COUNTROWS(Facts),Facts[Region]=IF(TRUE(),1,"a"))',
        'CALCULATE(COUNTROWS(Facts),Facts[Region]>IF(TRUE(),1,"a"))',
        'CALCULATE(COUNTROWS(Facts),Facts[Quantity]>VAR x=COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East")) RETURN x-1)',
        'CALCULATETABLE(ROW("c",1),Facts[Quantity]>COUNTROWS(VALUES(Facts[Region])))',
        'CALCULATETABLE(ROW("c",1),Facts[Quantity]>COUNTROWS(ALL(Facts[Region])))',
        'CALCULATETABLE(ROW("c",1),Facts[Quantity]>COUNTROWS(DISTINCT(Facts[Region])))',
        'CALCULATETABLE(ROW("c",1),Facts[Quantity]>COUNTROWS(CALCULATETABLE(Facts)))',
        'CALCULATETABLE(ROW("c",1),Facts[Quantity]>COUNTROWS(UNION(VALUES(Facts[Region]),VALUES(Facts[Region]))))',
        'CALCULATETABLE(ROW("c",1),Facts[Quantity]>COUNTROWS(CROSSJOIN(VALUES(Facts[Region]),VALUES(Facts[Note]))))',
        'CALCULATETABLE(ROW("c",1),Facts[Quantity]>COUNTROWS(GENERATESERIES(1,3)))',
        'CALCULATETABLE(ROW("c",1),Facts[Quantity]>COUNTROWS(DATATABLE("a",INTEGER,{{1},{2}})))',
        'CALCULATETABLE(ROW("c",1),Facts[Quantity]>COUNTROWS(CALENDAR(DATE(2020,1,1),DATE(2020,1,3))))',
        'CALCULATETABLE(ROW("c",COUNTROWS(Facts)),Facts[Quantity]>COUNTROWS(VALUES(Facts[Region])))',
        "CALCULATE(COUNTROWS(Facts),Facts[Quantity]+CONCATENATEX(Facts,Facts[Quantity])>3)",
        'CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region]))-1)',
        'CALCULATE(COUNTROWS(Facts),Facts[Quantity]+COUNTROWS(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region]))>5)',
    ]

    REFUSED_EXPRS = [
        'CALCULATE(COUNTROWS(Facts),COUNTROWS(SUBSTITUTEWITHINDEX(VALUES(Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region]))>0)',
        'CALCULATE(COUNTROWS(Facts),Facts[Quantity]<IF(ISEMPTY(CALCULATETABLE(Facts,Facts[Region]="East")),1,4))',
        'CALCULATE(COUNTROWS(Facts),Facts[Quantity]<COUNTROWS(CALCULATETABLE(CALCULATETABLE(Facts,Facts[Region]="East"))))',
        'CALCULATE(COUNTROWS(Facts),Facts[Quantity]<COUNTROWS(CALCULATETABLE(CALCULATETABLE(Facts),Facts[Region]="East")))',
        'CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(VALUES(Facts[Region]),FILTER(Facts,Facts[Quantity]>1))))',
        "CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(VALUES(Facts[Region]),ALLSELECTED())))",
        "CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(VALUES(Facts[Region]),ALLSELECTED(Facts[Region]))))",
        'CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(CALCULATETABLE(VALUES(Facts[Region]),VAR x="East" RETURN Facts[Region]=x)))',
        "CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(INFO.TABLES()))",
        'CONCATENATEX(ADDCOLUMNS(ALL(Facts[Quantity]),"n",INDEX(1,ALL(Facts[Quantity]),ORDERBY(Facts[Quantity]))),[n],",",Facts[Quantity])',
        "CALCULATE(COUNTROWS(Facts),Facts[Quantity]>COUNTROWS(INFO.TABLES())-1)",
        "CALCULATE(COUNTROWS(Facts),Facts[Quantity]+COUNTROWS(INFO.TABLES())>5)",
    ]

    @classmethod
    def setUpClass(cls) -> None:
        parity_dir = Path(__file__).resolve().parents[1] / "tools" / "parity"
        cls.battery_items: dict[str, str] = {}
        for filename in ("dax_battery_sdet_filters.json", "dax_battery_round2.json", "dax_battery_round3.json"):
            data = json.loads((parity_dir / filename).read_text())
            for it in data["items"]:
                cls.battery_items[it["expr"]] = it["powerbi"]

    def test_part_b_matching_items(self) -> None:
        """Supported scalar subqueries in filters must match Power BI Desktop exactly."""
        mismatches = []
        for expr in self.MATCHING_EXPRS:
            expected = self.battery_items[expr]
            actual = dax.local(expr)
            st = status(expected, actual)
            if st != "match":
                mismatches.append((expr, expected, actual, st))
        self.assertEqual([], mismatches, f"Mismatches in Part B: {len(mismatches)}")

    def test_part_b_stays_refused_items(self) -> None:
        """Complex/unsupported shapes must stay refused with LOCAL-REJECT (gap-reject)."""
        bad = []
        for expr in self.REFUSED_EXPRS:
            expected = self.battery_items[expr]
            actual = dax.local(expr)
            st = status(expected, actual)
            if st != "gap-reject":
                bad.append((expr, expected, actual, st))
        self.assertEqual([], bad, f"Expected gap-reject for all refused shapes: {bad}")


if __name__ == "__main__":
    unittest.main()
