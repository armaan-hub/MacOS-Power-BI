"""Iteration 98: scalar-misc-3.

Live answers frozen from Power BI Desktop (see tools/parity/dax_battery_scalar_misc2_extra.json,
dax_battery_scalar_misc2_extra2.json, dax_battery_xnpv2.json
and docs/plans/2026-10-29-scalar-misc-3.md).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status


class ScalarMisc3PartATest(unittest.TestCase):
    def test_allcrossfiltered_battery_items_match(self) -> None:
        """ALLCROSSFILTERED items in dax_battery_scalar_misc2_extra.json must match Power BI Desktop."""
        battery_path = (
            Path(__file__).resolve().parents[1]
            / "tools"
            / "parity"
            / "dax_battery_scalar_misc2_extra.json"
        )
        saved = json.loads(battery_path.read_text())
        items = [
            item for item in saved["items"]
            if "ALLCROSSFILTERED" in item["expr"]
        ]
        self.assertGreaterEqual(len(items), 30, f"Expected at least 30 items, found {len(items)}")

        mismatches = []
        for item in items:
            expr = item["expr"]
            expected = item["powerbi"]
            actual = dax.local(expr)
            st = status(expected, actual)
            if st != "match":
                mismatches.append((expr, expected, actual, st))
        self.assertEqual([], mismatches, f"Mismatches found in ALLCROSSFILTERED: {len(mismatches)} of {len(items)}")


class ScalarMisc3PartBTest(unittest.TestCase):
    def test_evaluateandlog_if_eager_customdata_tableof_items_match(self) -> None:
        """EVALUATEANDLOG, IF.EAGER, CUSTOMDATA, TABLEOF items in extra & extra2 must match Power BI Desktop."""
        mismatches = []
        for filename in ("dax_battery_scalar_misc2_extra.json", "dax_battery_scalar_misc2_extra2.json"):
            battery_path = Path(__file__).resolve().parents[1] / "tools" / "parity" / filename
            saved = json.loads(battery_path.read_text())
            for item in saved["items"]:
                expr = item["expr"]
                if (
                    "EVALUATEANDLOG" in expr
                    or "IF.EAGER" in expr
                    or "CUSTOMDATA" in expr
                    or "TABLEOF" in expr
                ):
                    expected = item["powerbi"]
                    actual = dax.local(expr)
                    st = status(expected, actual)
                    if st != "match":
                        mismatches.append((expr, expected, actual, st))
        self.assertEqual([], mismatches, f"Mismatches in Part B: {len(mismatches)}")


class ScalarMisc3PartCTest(unittest.TestCase):
    def test_xnpv_battery_items_match(self) -> None:
        """All items in dax_battery_xnpv2.json must match Power BI Desktop."""
        battery_path = (
            Path(__file__).resolve().parents[1]
            / "tools"
            / "parity"
            / "dax_battery_xnpv2.json"
        )
        saved = json.loads(battery_path.read_text())
        items = saved["items"]
        self.assertEqual(len(items), 258, f"Expected 258 items, found {len(items)}")

        mismatches = []
        for item in items:
            expr = item["expr"]
            expected = item["powerbi"]
            actual = dax.local(expr)
            st = status(expected, actual)
            if st != "match":
                mismatches.append((expr, expected, actual, st))
        self.assertEqual([], mismatches, f"Mismatches found in xnpv2: {len(mismatches)} of {len(items)}")


class ScalarMisc3PartDTest(unittest.TestCase):
    def test_text_collation_items_match(self) -> None:
        """Text collation items in extra & extra2 must match Power BI Desktop."""
        mismatches = []
        for filename in ("dax_battery_scalar_misc2_extra.json", "dax_battery_scalar_misc2_extra2.json"):
            battery_path = Path(__file__).resolve().parents[1] / "tools" / "parity" / filename
            saved = json.loads(battery_path.read_text())
            for item in saved["items"]:
                expr = item["expr"]
                if any(c in expr for c in ("é", "ä", "æ", "ǆ", "ö")) or "ISAFTER(\"e" in expr:
                    expected = item["powerbi"]
                    actual = dax.local(expr)
                    st = status(expected, actual)
                    if st != "match":
                        mismatches.append((expr, expected, actual, st))
        self.assertEqual([], mismatches, f"Mismatches in Part D: {len(mismatches)}")

    def test_non_latin_text_collation_refused(self) -> None:
        """Unclassifiable non-Latin text comparison must stay refused with MeasureError."""
        for expr in (
            '"α" < "β"',  # Greek
            '"д" < "ж"',  # Cyrillic
            '"中" < "文"',  # CJK
        ):
            actual = dax.local(expr)
            self.assertTrue(actual.startswith("LOCAL-REJECT:"), f"Expected refusal for {expr}, got: {actual}")


if __name__ == "__main__":
    unittest.main()
