"""Iteration 100: variant-iterators-2 (Task 12).

Plan: docs/plans/2026-10-30-variant-iterators-2.md
Specification: tools/parity/task12_variant2_spec.json (1,161 items)
Parts:
  - Part A: VAR block as right operand of && and || (293 items)
  - Part B1: IF / IF.EAGER / SWITCH bodies with branches of different types in MAXX/MINX (490 items)
  - Part B2: MAXX / MINX of text that finds no value (282 items)
  - Part B3: MAXX / MINX / COUNTX / COUNTAX over a text aggregate body (96 items)
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "tools" / "parity" / "task12_variant2_spec.json"
FIXTURES_PATH = ROOT / "tests" / "fixtures_misc3_alt.json"


def _local_on(rows: list[tuple[str, ...]], expression: str) -> str:
    saved = (dax.ROWS, dax.LOCAL_ROWS)
    dax.ROWS = rows
    dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, row)} for row in rows]
    try:
        return dax.local(expression)
    finally:
        dax.ROWS, dax.LOCAL_ROWS = saved


class VariantIterators2PartATest(unittest.TestCase):
    """Part A: VAR block as the right operand of &&, ||, and ^."""

    def test_var_as_right_operand_of_logical_and_or(self) -> None:
        cases = [
            ('TRUE()||VAR y=1.5 RETURN y&"z"', "True"),
            ("10&&VAR y=-1 RETURN y+1", "False"),
            ("0&&VAR y=BLANK() RETURN ISBLANK(y)", "False"),
            ('10||VAR y="b" RETURN y*y', "True"),
            ('2.5&&VAR y="2" RETURN y*y', "True"),
            ("TRUE()||VAR y=2 RETURN ISBLANK(y)", "True"),
            ("1&&VAR y=-1 RETURN LEN(y)", "True"),
            ("TRUE()&&VAR y=DATE(2020,1,1) RETURN y*y", "True"),
            ("2.5||VAR y=1.5 RETURN IF(y,1,2)", "True"),
            ("BLANK()||VAR y=TRUE() RETURN y=y", "True"),
            ('1||VAR y=2 RETURN y&"z"', "True"),
            ('2.5||VAR y="2" RETURN y=y', "True"),
            ('"a"&&VAR y=0 RETURN ISBLANK(y)', "False"),
            ("BLANK()||VAR y=DATE(2020,1,1) RETURN LEN(y)", "True"),
            ("1&&VAR y=2 RETURN LEN(y)", "True"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual(
                "match",
                status(expected, actual),
                f"Expression: {expr}, Expected: {expected}, Got: {actual}",
            )

    def test_var_as_right_operand_of_power(self) -> None:
        cases = [
            ("3^VAR y=2 RETURN NOT(y)", "1"),
            ("VAR z=3 RETURN z^VAR y=2 RETURN ROUND(y,0)+z", "243"),
            ("3^VAR y=BLANK() RETURN y&&TRUE()", "1"),
            ("VAR z=3 RETURN z^VAR y=BLANK() RETURN -y+z", "27"),
            ("VAR z=3 RETURN z^VAR y=BLANK() RETURN y&&TRUE()+z", "1"),
            ("VAR z=3 RETURN z^VAR y=BLANK() RETURN y/0+z", "27"),
            ("VAR z=3 RETURN z^VAR y=BLANK() RETURN y^2+z", "27"),
            ("3^VAR y=BLANK() RETURN y^2", "1"),
            ("VAR z=3 RETURN z^VAR y=TRUE() RETURN y*2+z", "243"),
            ("3^VAR y=BLANK() RETURN -y", "1"),
            ("VAR z=3 RETURN z^VAR y=2 RETURN NOT(y)+z", "1"),
            ("VAR z=3 RETURN z^VAR y=TRUE() RETURN y&&TRUE()+z", "3"),
            ("3^VAR y=TRUE() RETURN y*2", "9"),
            ("3^VAR y=BLANK() RETURN y/0", "1"),
            ("3^VAR y=TRUE() RETURN y&&TRUE()", "3"),
            ("3^VAR y=2 RETURN y IN {1,2,3}", "3"),
            ("3^VAR y=2 RETURN ROUND(y,0)", "9"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual(
                "match",
                status(expected, actual),
                f"Expression: {expr}, Expected: {expected}, Got: {actual}",
            )

    def test_part_a_on_alternate_facts_tables(self) -> None:
        fixture = json.loads(FIXTURES_PATH.read_text())
        cases = [
            ('TRUE()||VAR y=1.5 RETURN y&"z"', "True"),
            ("10&&VAR y=-1 RETURN y+1", "False"),
            ("0&&VAR y=BLANK() RETURN ISBLANK(y)", "False"),
            ('10||VAR y="b" RETURN y*y', "True"),
            ("3^VAR y=2 RETURN NOT(y)", "1"),
            ("VAR z=3 RETURN z^VAR y=2 RETURN ROUND(y,0)+z", "243"),
        ]
        for key in ("A", "B"):
            dataset = fixture["datasets"][key]
            rows = [tuple(r) for r in dataset["rows"]]
            for expr, expected in cases:
                actual = _local_on(rows, expr)
                self.assertEqual(
                    "match",
                    status(expected, actual),
                    f"Dataset {key}, Expr: {expr}, Expected: {expected}, Got: {actual}",
                )


class VariantIterators2PartB1Test(unittest.TestCase):
    """Part B1: IF / IF.EAGER / SWITCH bodies with branches of different types in MAXX/MINX."""

    def test_maxx_minx_variant_bodies_numbers_and_dates(self) -> None:
        cases = [
            ("MAXX(Facts,IF.EAGER(TRUE(),1,DATE(2020,1,1)))", "1"),
            ("MAXX(Facts,IF.EAGER(TRUE(),2.5,TRUE()))", "2.5"),
            ('MAXX(Facts,IF.EAGER(TRUE(),"a",Facts[Sales]))', "BLANK"),
            ('MAXX(Facts,EVALUATEANDLOG(DATE(2020,1,1)+0.5,"a"))', "01/01/2020 12:00:00"),
            ('MAXX(Facts,IF.EAGER(TRUE(),Facts[Quantity],"a"))', "5"),
            ("MAXX(Facts,IF.EAGER(TRUE(),Facts[Region],TRUE()))", "West"),
            ("MAXX(Facts,IF.EAGER(TRUE(),Facts[Note],1))", "Paid"),
            ("MAXX(Facts,IF.EAGER(TRUE(),Facts[Sales],Facts[Region]))", "20"),
            ("MAXX(Facts,IF.EAGER(FALSE(),2.5,Facts[Region]))", "West"),
            ("MAXX(Facts,IF.EAGER(FALSE(),Facts[Quantity],Facts[Note]))", "Paid"),
            ("MAXX(Facts,IF.EAGER(FALSE(),Facts[Sales],Facts[Region]))", "West"),
            ("MAXX(Facts,IF.EAGER(Facts[Quantity]>2,1,Facts[Region]))", "1"),
            ("MAXX(Facts,IF.EAGER(Facts[Quantity]>2,2.5,Facts[Region]))", "2.5"),
            ("MAXX(Facts,IF.EAGER(Facts[Quantity]>2,Facts[Quantity],Facts[Region]))", "5"),
            ("MAXX(Facts,IF.EAGER(Facts[Quantity]>2,Facts[Sales],Facts[Note]))", "20"),
            ("MAXX(Facts,IF.EAGER(Facts[Quantity]>2,Facts[Region],DATE(2022,2,2)))", "02/02/2022 00:00:00"),
            ("MINX(Facts,IF.EAGER(Facts[Sales]>1,DATE(2020,1,1),TRUE()))", "01/01/2020 00:00:00"),
            ("MINX(Facts,IF.EAGER(TRUE(),INT(2.5),DATE(2020,1,1)))", "2"),
            ("MINX(Facts,IF.EAGER(TRUE(),DATE(2020,1,1),1))", "43831"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual(
                "match",
                status(expected, actual),
                f"Expression: {expr}, Expected: {expected}, Got: {actual}",
            )

    def test_variant_comparisons_in_calculate_filters_and_coalesce(self) -> None:
        cases = [
            ('CALCULATE(COUNTROWS(Facts),Facts[Region]=IF(TRUE(),1,"a"))', "BLANK"),
            ('CALCULATE(COUNTROWS(Facts),Facts[Region]>IF(TRUE(),1,"a"))', "6"),
            ("SUMX(FILTER(Facts,VAR t = \"East\" RETURN COALESCE(t,0)>1),Facts[Quantity])", "15"),
            ("CALCULATE(COUNTROWS(Facts),VAR t = Facts[Region] RETURN COALESCE(t,0)>1)", "6"),
            ("COUNTROWS(FILTER(Facts,VAR t = TRUE() RETURN COALESCE(t,0)>1))", "6"),
            ("COUNTROWS(CALCULATETABLE(Facts,VAR t = Facts[Region] RETURN COALESCE(t,0)>1))", "6"),
            ("SUMX(FILTER(Facts,VAR t = TRUE() RETURN COALESCE(t,0)>1),Facts[Quantity])", "15"),
            ("CALCULATE(COUNTROWS(Facts),NOT(VAR t = Facts[Note] RETURN COALESCE(t,0)>1))", "2"),
            ("CALCULATE(COUNTROWS(Facts),FILTER(ALL(Facts),VAR t = TRUE() RETURN COALESCE(t,0)>1))", "6"),
            ("COUNTROWS(FILTER(Facts,VAR t = Facts[Region] RETURN COALESCE(t,0)>1))", "6"),
            ("CALCULATE(COUNTROWS(Facts),FILTER(ALL(Facts),VAR t = \"East\" RETURN COALESCE(t,0)>1))", "6"),
            ("CALCULATE(COUNTROWS(Facts),NOT(VAR t = Facts[Region] RETURN COALESCE(t,0)>1))", "BLANK"),
            ("SUMX(FILTER(Facts,VAR t = Facts[Region] RETURN COALESCE(t,0)>1),Facts[Quantity])", "15"),
            ("CALCULATE(SUM(Facts[Quantity]),VAR t = Facts[Note] RETURN COALESCE(t,0)>1)", "7"),
            ("COUNTROWS(FILTER(Facts,VAR t = Facts[Note] RETURN COALESCE(t,0)>1))", "4"),
            ("CALCULATE(SUM(Facts[Quantity]),VAR t = Facts[Region] RETURN COALESCE(t,0)>1)", "15"),
            ("COUNTROWS(CALCULATETABLE(Facts,VAR t = Facts[Note] RETURN COALESCE(t,0)>1))", "4"),
            ("COUNTROWS(FILTER(Facts,VAR t = \"East\" RETURN COALESCE(t,0)>1))", "6"),
            ("CALCULATE(COUNTROWS(Facts),FILTER(ALL(Facts),VAR t = Facts[Region] RETURN COALESCE(t,0)>1))", "6"),
            ("SUMX(FILTER(Facts,VAR t = Facts[Note] RETURN COALESCE(t,0)>1),Facts[Quantity])", "7"),
            ("CALCULATE(COUNTROWS(Facts),VAR t = Facts[Note] RETURN COALESCE(t,0)>1)", "4"),
            ("CALCULATE(COUNTROWS(Facts),FILTER(ALL(Facts),VAR t = Facts[Note] RETURN COALESCE(t,0)>1))", "4"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual(
                "match",
                status(expected, actual),
                f"Expression: {expr}, Expected: {expected}, Got: {actual}",
            )

    def test_part_b1_on_alternate_facts_tables(self) -> None:
        fixture = json.loads(FIXTURES_PATH.read_text())
        for key, expected_region in (("A", "West"), ("B", "Mid")):
            dataset = fixture["datasets"][key]
            rows = [tuple(r) for r in dataset["rows"]]
            cases = [
                ("MAXX(Facts,IF.EAGER(TRUE(),1,DATE(2020,1,1)))", "1"),
                ("MAXX(Facts,IF.EAGER(TRUE(),2.5,TRUE()))", "2.5"),
                ('MAXX(Facts,IF.EAGER(TRUE(),"a",Facts[Sales]))', "BLANK"),
                ('MAXX(Facts,EVALUATEANDLOG(DATE(2020,1,1)+0.5,"a"))', "01/01/2020 12:00:00"),
                ("MAXX(Facts,IF.EAGER(TRUE(),Facts[Region],TRUE()))", expected_region),
                ("MAXX(Facts,IF.EAGER(Facts[Quantity]>2,1,Facts[Region]))", "1"),
                ("MAXX(Facts,IF.EAGER(Facts[Quantity]>2,2.5,Facts[Region]))", "2.5"),
            ]
            for expr, expected in cases:
                actual = _local_on(rows, expr)
                self.assertEqual(
                    "match",
                    status(expected, actual),
                    f"Dataset {key}, Expr: {expr}, Expected: {expected}, Got: {actual}",
                )


class VariantIterators2PartB2Test(unittest.TestCase):
    """Part B2: MAXX / MINX of text that finds no value."""

    def test_text_maxx_minx_empty_or_no_value_returns_blank(self) -> None:
        cases = [
            ("MAXX(Facts,IF.EAGER(FALSE(),Facts[Region]))", "BLANK"),
            ("MAXX(Facts,IF.EAGER(FALSE(),Facts[Note]))", "BLANK"),
            ('MAXX(Facts,IF.EAGER(FALSE(),"a"))', "BLANK"),
            ('MAXX(Facts,IF.EAGER(TRUE(),BLANK(),"a"))', "BLANK"),
            ("MAXX(Facts,IF.EAGER(BLANK(),Facts[Region]))", "BLANK"),
            ("MAXX(Facts,IF.EAGER(0,Facts[Region]))", "BLANK"),
            ("MINX(FILTER(Facts,FALSE()),Facts[Region])", "BLANK"),
            ("MAXX(FILTER(Facts,FALSE()),Facts[Region])", "BLANK"),
            ("MINX(FILTER(ALL(Facts),Facts[Quantity]>100),Facts[Region])", "BLANK"),
            ("MAXX(TOPN(0,Facts),Facts[Region])", "BLANK"),
            ("MINX(EXCEPT(Facts,Facts),Facts[Region])", "BLANK"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual(
                "match",
                status(expected, actual),
                f"Expression: {expr}, Expected: {expected}, Got: {actual}",
            )

    def test_part_b2_on_alternate_facts_tables(self) -> None:
        fixture = json.loads(FIXTURES_PATH.read_text())
        cases = [
            ("MAXX(Facts,IF.EAGER(FALSE(),Facts[Region]))", "BLANK"),
            ("MINX(FILTER(Facts,FALSE()),Facts[Region])", "BLANK"),
            ("MAXX(FILTER(Facts,FALSE()),Facts[Region])", "BLANK"),
        ]
        for key in ("A", "B"):
            dataset = fixture["datasets"][key]
            rows = [tuple(r) for r in dataset["rows"]]
            for expr, expected in cases:
                actual = _local_on(rows, expr)
                self.assertEqual(
                    "match",
                    status(expected, actual),
                    f"Dataset {key}, Expr: {expr}, Expected: {expected}, Got: {actual}",
                )


class VariantIterators2PartB3Test(unittest.TestCase):
    """Part B3: MAXX / MINX / COUNTX / COUNTAX over a text aggregate body."""

    def test_text_aggregate_in_iterators(self) -> None:
        cases = [
            ('MAXX(CALCULATETABLE(Facts,Facts[Region]="East"),MAX(Facts[Region]))', "West"),
            ('MAXX(CALCULATETABLE(Facts,Facts[Region]="East"),MIN(Facts[Region]))', "East"),
            ('COUNTX(CALCULATETABLE(Facts,Facts[Region]="East"),MIN(Facts[Region]))', "3"),
            ('COUNTX(CALCULATETABLE(Facts,Facts[Region]="East"),MAX(Facts[Region]))', "3"),
            ('COUNTX(CALCULATETABLE(Facts,Facts[Region]="East"),CALCULATE(MAX(Facts[Region])))', "3"),
            ('COUNTAX(CALCULATETABLE(Facts,Facts[Region]="East"),MAX(Facts[Region]))', "3"),
            ('COUNTAX(CALCULATETABLE(Facts,Facts[Region]="East"),MIN(Facts[Region]))', "3"),
            ('COUNTAX(CALCULATETABLE(Facts,Facts[Region]="East"),CALCULATE(MAX(Facts[Region])))', "3"),
            ("MAXX(EXCEPT(Facts,Facts),MIN(Facts[Region]))", "BLANK"),
            ("MINX(FILTER(Facts,FALSE()),CALCULATE(MAX(Facts[Region])))", "BLANK"),
            ("COUNTX(EXCEPT(Facts,Facts),CALCULATE(MAX(Facts[Region])))", "BLANK"),
            ("COUNTX(TOPN(0,Facts),MAX(Facts[Region]))", "BLANK"),
            ("COUNTAX(FILTER(Facts,FALSE()),CALCULATE(MAX(Facts[Region])))", "BLANK"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual(
                "match",
                status(expected, actual),
                f"Expression: {expr}, Expected: {expected}, Got: {actual}",
            )

    def test_text_aggregate_in_sumx_remains_refused(self) -> None:
        # SUMX over text aggregate is rejected in Power BI (Task 11)
        refused = [
            'SUMX(CALCULATETABLE(Facts,Facts[Region]="East"),MAX(Facts[Region]))',
            'AVERAGEX(CALCULATETABLE(Facts,Facts[Region]="East"),MAX(Facts[Region]))',
        ]
        for expr in refused:
            actual = dax.local(expr)
            self.assertTrue(
                actual.startswith("LOCAL-REJECT:"),
                f"Expression {expr} should be refused, got: {actual}",
            )

    def test_part_b3_on_alternate_facts_tables(self) -> None:
        fixture = json.loads(FIXTURES_PATH.read_text())
        cases = [
            ("MAXX(EXCEPT(Facts,Facts),MIN(Facts[Region]))", "BLANK"),
            ("MINX(FILTER(Facts,FALSE()),CALCULATE(MAX(Facts[Region])))", "BLANK"),
            ("COUNTX(EXCEPT(Facts,Facts),CALCULATE(MAX(Facts[Region])))", "BLANK"),
        ]
        for key in ("A", "B"):
            dataset = fixture["datasets"][key]
            rows = [tuple(r) for r in dataset["rows"]]
            for expr, expected in cases:
                actual = _local_on(rows, expr)
                self.assertEqual(
                    "match",
                    status(expected, actual),
                    f"Dataset {key}, Expr: {expr}, Expected: {expected}, Got: {actual}",
                )


class Task12SpecCoverageTest(unittest.TestCase):
    """Replay all 1,161 items from task12_variant2_spec.json.

    Every item must be 'match' or refused with a true reason ('gap-reject').
    Nothing may be 'DIFF' or 'CRASH'.
    """

    def test_all_1161_spec_items(self) -> None:
        spec = json.loads(SPEC_PATH.read_text())
        items = spec["items"]
        diffs = []
        crashes = []
        matches = 0
        refusals = 0

        for it in items:
            expr = it["expr"]
            pbi = it["powerbi"]
            actual = dax.local(expr)
            outcome = status(pbi, actual)
            if outcome == "match":
                matches += 1
            elif outcome == "gap-reject":
                refusals += 1
            elif outcome == "DIFF":
                diffs.append((it["part"], expr, pbi, actual))
            else:
                crashes.append((it["part"], expr, pbi, actual))

        self.assertEqual([], diffs, f"Total DIFF items: {len(diffs)}")
        self.assertEqual([], crashes, f"Total CRASH items: {len(crashes)}")
        print(f"\nSpec replay summary: {matches} matches, {refusals} gap-rejects out of {len(items)} items.")


if __name__ == "__main__":
    unittest.main()
