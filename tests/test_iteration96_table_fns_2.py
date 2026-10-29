"""Iteration 96: table-fns-2 (Part A: SUBSTITUTEWITHINDEX).

Live answers frozen from Power BI Desktop (see tools/parity/dax_battery_table_fns2.json
and docs/plans/2026-10-26-table-fns-2.md).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

# Valid in Power BI, refused here on purpose (review 2026-10-28): both sides carry a computed column of the same name ("s");
# Power BI joins on it for ADDCOLUMNS columns but not for SUMMARIZE columns, a rule that cannot be derived, so the shape is refused.
KNOWN_REFUSED = [
    'COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),Facts[Region]))',
]

STAYS_REFUSED_PART_A = [
    # Too few arguments (< 4)
    'COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region])))',
    # No common columns to join
    'COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Quantity]),Facts[Quantity]))',
    # More than one row in index table matches a row in original table
    'COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",SUMMARIZE(Facts,Facts[Region],Facts[Note]),Facts[Region],ASC,Facts[Note],DESC))',
    # Invalid order argument value (-1)
    'COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"i",VALUES(Facts[Region]),Facts[Region],-1))',
    # Added column name already exists
    'COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),"s",VALUES(Facts[Region]),Facts[Region]))',
    # Column name argument is not a valid column name (e.g. numeric literal 1)
    'COUNTROWS(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],"s",SUM(Facts[Quantity])),1,VALUES(Facts[Region]),Facts[Region]))',
]

# TOCSV / TOJSON of ADDMISSINGITEMS(... SUMMARIZECOLUMNS ...): the first build matched these nine only because the three groups of the
# saved data happened to come out in Power BI's order. Power BI lists SUMMARIZECOLUMNS groups in dictionary order (like SUMMARIZE), the local
# engine sorts them, and a fresh probe (West before North) printed the wrong order, so the order is refused (as TOCSV of SUMMARIZECOLUMNS is).
KNOWN_REFUSED_PART_B = 9

STAYS_REFUSED_PART_B = [
    # Missing table argument (too few arguments)
    'COUNTROWS(ADDMISSINGITEMS(Facts[Region]))',
    # ShowAll column not found as GroupBy column in argument number 1
    'COUNTROWS(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity]))))',
    # ShowAll column not found as GroupBy column in argument number 2
    'COUNTROWS(ADDMISSINGITEMS(Facts[Region],Facts[Note],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region]))',
    # String or numeric expression used where table expected
    'COUNTROWS(ADDMISSINGITEMS(Facts[Region],"a",SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region]))',
    'COUNTROWS(ADDMISSINGITEMS(1,SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Region]))',
    # ShowAll column Facts[Region] not in GroupBy Facts[Note]
    'TOCSV(ADDMISSINGITEMS(Facts[Region],SUMMARIZECOLUMNS(Facts[Region],FILTER(ALL(Facts),Facts[Quantity]>3),"s",SUM(Facts[Quantity])),Facts[Note]))',
]


class TableFns2PartATest(unittest.TestCase):
    def test_battery_part_a_substitutewithindex_items_match(self) -> None:
        """Every Part A item (SUBSTITUTEWITHINDEX) in dax_battery_table_fns2.json must match Power BI."""
        battery_path = Path(__file__).resolve().parents[1] / "tools" / "parity" / "dax_battery_table_fns2.json"
        saved = json.loads(battery_path.read_text())
        sub_items = [item for item in saved["items"] if "SUBSTITUTEWITHINDEX" in item["expr"]]
        self.assertEqual(len(sub_items), 82, f"Expected 82 Part A SUBSTITUTEWITHINDEX items, found {len(sub_items)}")
        
        mismatches = []
        for item in sub_items:
            expr = item["expr"]
            expected = item["powerbi"]
            actual = dax.local(expr)
            st = status(expected, actual)
            if st != "match" and expr not in KNOWN_REFUSED:
                mismatches.append((expr, expected, actual, st))
        self.assertEqual([], mismatches, f"Mismatches found in Part A SUBSTITUTEWITHINDEX: {len(mismatches)} of {len(sub_items)}")
        for expr in KNOWN_REFUSED:
            self.assertEqual("gap-reject", status(next(i["powerbi"] for i in sub_items if i["expr"] == expr), dax.local(expr)))

    def test_refusals_stay_refused(self) -> None:
        """Explicit check for refused negative cases in Part A."""
        for expr in STAYS_REFUSED_PART_A:
            res = dax.local(expr)
            self.assertTrue(
                res.startswith("LOCAL-REJECT") or res.startswith("ERR:"),
                f"Expected refusal (LOCAL-REJECT or ERR:) for {expr}, got {res}",
            )


class TableFns2PartBTest(unittest.TestCase):
    def test_battery_part_b_addmissingitems_items_match(self) -> None:
        """Every Part B item (ADDMISSINGITEMS) in dax_battery_table_fns2.json must match Power BI."""
        battery_path = Path(__file__).resolve().parents[1] / "tools" / "parity" / "dax_battery_table_fns2.json"
        saved = json.loads(battery_path.read_text())
        b_items = [item for item in saved["items"] if "ADDMISSINGITEMS" in item["expr"]]
        self.assertEqual(len(b_items), 61, f"Expected 61 Part B ADDMISSINGITEMS items, found {len(b_items)}")

        mismatches, refused = [], []
        for item in b_items:
            expr = item["expr"]
            expected = item["powerbi"]
            actual = dax.local(expr)
            st = status(expected, actual)
            if st == "gap-reject" and expr.startswith("TOCSV(") and "SUMMARIZECOLUMNS(" in expr:
                refused.append(expr)  # review 2026-10-28: see the comment on KNOWN_REFUSED_PART_B
            elif st != "match":
                mismatches.append((expr, expected, actual, st))
        self.assertEqual([], mismatches, f"Mismatches found in Part B ADDMISSINGITEMS: {len(mismatches)} of {len(b_items)}")
        self.assertEqual(KNOWN_REFUSED_PART_B, len(refused))

    def test_part_b_refusals_stay_refused(self) -> None:
        """Explicit check for refused negative cases in Part B."""
        for expr in STAYS_REFUSED_PART_B:
            res = dax.local(expr)
            self.assertTrue(
                res.startswith("LOCAL-REJECT") or res.startswith("ERR:"),
                f"Expected refusal (LOCAL-REJECT or ERR:) for {expr}, got {res}",
            )


STAYS_REFUSED_PART_C = [
    # KEEPFILTERS directly inside COUNTROWS (not a table scan function)
    'COUNTROWS(KEEPFILTERS(VALUES(Facts[Region])))',
    # ROLLUPGROUP directly inside SUMMARIZECOLUMNS (not inside ROLLUPADDISSUBTOTAL)
    'TOCSV(SUMMARIZECOLUMNS(ROLLUPGROUP(Facts[Region],Facts[Note]),"s",SUM(Facts[Quantity])))',
    # Standalone ROLLUP without SUMMARIZE
    'COUNTROWS(ROLLUP(Facts[Region]))',
    'TOCSV(ROLLUP(Facts[Region]))',
    # Standalone ROLLUPADDISSUBTOTAL without SUMMARIZECOLUMNS
    'COUNTROWS(ROLLUPADDISSUBTOTAL(Facts[Region],"t"))',
    'TOCSV(ROLLUPADDISSUBTOTAL(Facts[Region],"t"))',
    # Standalone ISSUBTOTAL outside SUMMARIZE
    'IF(FALSE(),ISSUBTOTAL(Facts[Region]))',
]


class TableFns2PartCTest(unittest.TestCase):
    def test_battery_part_c_items_match(self) -> None:
        """Every Part C item (ROLLUP family, KEEPFILTERS in iterators) in dax_battery_table_fns2.json must match Power BI."""
        battery_path = Path(__file__).resolve().parents[1] / "tools" / "parity" / "dax_battery_table_fns2.json"
        saved = json.loads(battery_path.read_text())
        c_items = [
            item for item in saved["items"]
            if "SUBSTITUTEWITHINDEX" not in item["expr"] and "ADDMISSINGITEMS" not in item["expr"]
        ]
        self.assertEqual(len(c_items), 23, f"Expected 23 Part C items, found {len(c_items)}")

        mismatches = []
        for item in c_items:
            expr = item["expr"]
            expected = item["powerbi"]
            actual = dax.local(expr)
            st = status(expected, actual)
            if st != "match":
                mismatches.append((expr, expected, actual, st))
        self.assertEqual([], mismatches, f"Mismatches found in Part C: {len(mismatches)} of {len(c_items)}")

    def test_part_c_refusals_stay_refused(self) -> None:
        """Explicit check for refused negative cases in Part C."""
        for expr in STAYS_REFUSED_PART_C:
            res = dax.local(expr)
            self.assertTrue(
                res.startswith("LOCAL-REJECT") or res.startswith("ERR:"),
                f"Expected refusal (LOCAL-REJECT or ERR:) for {expr}, got {res}",
            )


if __name__ == "__main__":
    unittest.main()

