"""Iteration 99: gaps-2 (errors the app misses: iterators over an empty table, a text column against COUNTROWS).

Plan: docs/plans/2026-10-29-gaps-2.md
Specification:
  - tools/parity/dax_battery_gaps2.json (1,476 items on standard Facts table)
  - tests/fixtures_gaps2_alt.json (1,476 items on Facts table "N")
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

ROOT = Path(__file__).resolve().parents[1]


class Gaps2PartATest(unittest.TestCase):
    def test_empty_table_iterator_column_and_type_checks(self) -> None:
        """Iterators over an empty table must validate column references and static expression types."""
        # Bare column that does not exist in the walked table or model measures
        self.assertTrue(dax.local("SUMX(FILTER(Facts,FALSE()),[c])").startswith("LOCAL-REJECT:"))
        self.assertTrue(dax.local("SUMX(CALCULATETABLE(Facts,Facts[Region]=\"Nowhere\"),[c])").startswith("LOCAL-REJECT:"))
        self.assertTrue(dax.local("SUMX(TOPN(0,Facts,Facts[Quantity]),[c])").startswith("LOCAL-REJECT:"))
        self.assertTrue(dax.local("SUMX(EXCEPT(Facts,Facts),[c])").startswith("LOCAL-REJECT:"))
        self.assertTrue(dax.local("SUMX(FILTER(Facts,Facts[Quantity]>100),Facts[Quantity]+[Nope])").startswith("LOCAL-REJECT:"))
        self.assertTrue(dax.local("SUMX(KEEPFILTERS(FILTER(Facts,FALSE())),[c])").startswith("LOCAL-REJECT:"))
        self.assertTrue(dax.local("CONCATENATEX(FILTER(Facts,FALSE()),[c],\"|\")").startswith("LOCAL-REJECT:"))

        # SELECTCOLUMNS unkept column vs ADDCOLUMNS added column
        self.assertTrue(dax.local("SUMX(SELECTCOLUMNS(FILTER(Facts,FALSE()),\"z\",1),[Sales])").startswith("LOCAL-REJECT:"))
        self.assertEqual("BLANK", dax.local("SUMX(SELECTCOLUMNS(FILTER(Facts,FALSE()),\"z\",1),[z])"))
        self.assertEqual("BLANK", dax.local("SUMX(ADDCOLUMNS(FILTER(Facts,FALSE()),\"z\",1),[z])"))

        # Valid expressions over empty table still return BLANK
        self.assertEqual("BLANK", dax.local("SUMX(FILTER(Facts,FALSE()),Facts[Quantity])"))
        self.assertEqual("BLANK", dax.local("SUMX(FILTER(Facts,FALSE()),1)"))

        # Type checks on empty table iterators: COUNTX does not work with Boolean
        self.assertTrue(dax.local("COUNTX(FILTER(Facts,FALSE()),Facts[Region]=\"East\")").startswith("LOCAL-REJECT:"))


class Gaps2PartBTest(unittest.TestCase):
    def test_text_column_against_countrows_is_typed_integer(self) -> None:
        """COUNTROWS has static type Integer, so comparing a text column against it is an error even when table is empty."""
        alt_fixture = ROOT / "tests" / "fixtures_gaps2_alt.json"
        data = json.loads(alt_fixture.read_text())
        dataset_n = data["datasets"]["N"]
        rows_n = dataset_n["rows"]

        saved = (dax.ROWS, dax.LOCAL_ROWS)
        dax.ROWS = rows_n
        dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, r)} for r in rows_n]
        try:
            # On table N, CALCULATETABLE(Facts,Facts[Region]="East") is empty (no East rows).
            # The static type is Integer, so comparison with Facts[Region] / Facts[Note] must fail.
            exprs = [
                "CALCULATE(COUNTROWS(Facts),Facts[Region]=COUNTROWS(CALCULATETABLE(Facts,Facts[Region]=\"East\")))",
                "CALCULATE(COUNTROWS(Facts),Facts[Region]<>COUNTROWS(CALCULATETABLE(Facts,Facts[Region]=\"East\")))",
                "CALCULATE(COUNTROWS(Facts),Facts[Region]<COUNTROWS(CALCULATETABLE(Facts,Facts[Region]=\"East\")))",
                "CALCULATE(COUNTROWS(Facts),Facts[Region]>=COUNTROWS(CALCULATETABLE(Facts,Facts[Region]=\"East\")))",
                "COUNTROWS(FILTER(Facts,Facts[Region]=COUNTROWS(CALCULATETABLE(Facts,Facts[Region]=\"East\"))))",
                "SUMX(Facts,IF(Facts[Region]=COUNTROWS(CALCULATETABLE(Facts,Facts[Region]=\"East\")),1,0))",
                "COUNTROWS(FILTER(Facts,Facts[Region]=VAR k=COUNTROWS(CALCULATETABLE(Facts,Facts[Region]=\"East\")) RETURN k))",
                "CALCULATE(COUNTROWS(Facts),Facts[Note]=COUNTROWS(CALCULATETABLE(Facts,Facts[Region]=\"East\")))",
            ]
            for expr in exprs:
                actual = dax.local(expr)
                self.assertTrue(
                    actual.startswith("LOCAL-REJECT:"),
                    f"Expected LOCAL-REJECT on Table N for {expr}, got: {actual}",
                )
        finally:
            dax.ROWS, dax.LOCAL_ROWS = saved


class Gaps2BatteryReplayTest(unittest.TestCase):
    def test_standard_table_battery_gaps2_has_zero_diff(self) -> None:
        """All 1,476 items in dax_battery_gaps2.json must match Power BI Desktop."""
        battery_path = ROOT / "tools" / "parity" / "dax_battery_gaps2.json"
        saved = json.loads(battery_path.read_text())
        items = saved["items"]
        self.assertEqual(len(items), 1476, f"Expected 1,476 items, found {len(items)}")

        mismatches = []
        for item in items:
            expr = item["expr"]
            expected = item["powerbi"]
            actual = dax.local(expr)
            st = status(expected, actual)
            if st not in {"match", "gap-reject"}:
                mismatches.append((expr, expected, actual, st))
        self.assertEqual([], mismatches, f"Mismatches on standard table: {len(mismatches)} of {len(items)}")

    def test_table_n_fixture_gaps2_has_zero_diff(self) -> None:
        """All 1,476 items in fixtures_gaps2_alt.json on Table N must match Power BI Desktop."""
        alt_fixture = ROOT / "tests" / "fixtures_gaps2_alt.json"
        data = json.loads(alt_fixture.read_text())
        dataset_n = data["datasets"]["N"]
        rows_n = dataset_n["rows"]
        items = dataset_n["items"]
        self.assertEqual(len(items), 1476, f"Expected 1,476 items, found {len(items)}")

        saved = (dax.ROWS, dax.LOCAL_ROWS)
        dax.ROWS = rows_n
        dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, r)} for r in rows_n]

        mismatches = []
        try:
            for item in items:
                expr = item["expr"]
                expected = item["powerbi"]
                actual = dax.local(expr)
                st = status(expected, actual)
                if st not in {"match", "gap-reject"}:
                    mismatches.append((expr, expected, actual, st))
        finally:
            dax.ROWS, dax.LOCAL_ROWS = saved

        self.assertEqual([], mismatches, f"Mismatches on Table N: {len(mismatches)} of {len(items)}")


if __name__ == "__main__":
    unittest.main()
