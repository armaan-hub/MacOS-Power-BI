"""Iteration 101: iterators-typed-3 (Task 13).

Plan: docs/plans/2026-10-30-iterators-typed-3.md
Specification: tools/parity/task13_typed3_spec.json (1,180 items)
Parts:
  - Part A1: Variant bodies with Infinity, NaN in SUMX, AVERAGEX, COUNTX, COUNTAX (207 items)
  - Part A2: Constant IF reduction in COUNTX (91 items)
  - Part B1: BLANK() as body of PRODUCTX, MEDIANX, VARX.P, AVERAGEX, PERCENTILEX.INC (201 items)
  - Part B2: One-column table where one value is wanted (235 items)
  - Part C1: == between Variants (79 items)
  - Part C2: Date beside number in Variant (32 items)
  - Part C3: Text or date condition in iterator body (61 items)
  - Part C4: FIRSTNONBLANK and relatives in comparisons and iterators (66 items)
  - Part C5: PRODUCTX / MEDIANX of constant IF over text column (80 items)
  - Part D1: VAR block computing filter value (58 items)
  - Part D2: KEEPFILTERS around table or inside EVALUATEANDLOG (70 items)
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "tools" / "parity" / "task13_typed3_spec.json"
FIXTURES_MISC3_PATH = ROOT / "tests" / "fixtures_misc3_alt.json"
FIXTURES_VARIANT2_PATH = ROOT / "tests" / "fixtures_variant2_review_alt.json"


def _local_on(rows: list[tuple[str, ...]], expression: str) -> str:
    saved = (dax.ROWS, dax.LOCAL_ROWS)
    dax.ROWS = rows
    dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, row)} for row in rows]
    try:
        return dax.local(expression)
    finally:
        dax.ROWS, dax.LOCAL_ROWS = saved


class IteratorsTyped3PartATest(unittest.TestCase):
    """Part A1: Variant bodies with Infinity/NaN; Part A2: Constant IF in COUNTX."""

    def test_part_a1_infinity_nan_variants(self) -> None:
        cases = [
            ('SUMX(Facts,IF(Facts[Region]="East","",1/0))', "Infinity"),
            ('AVERAGEX(Facts,IF.EAGER(Facts[Quantity]>2,"5",-1/0))', "-Infinity"),
            ('AVERAGEX(Facts,IF.EAGER(TRUE(),Facts[Sales]/Facts[Quantity],TRUE()))', "NaN"),
            ('COUNTX(Facts,IF(Facts[Quantity]>2,1/0,UPPER(Facts[Region])))', "3"),
            ('COUNTAX(Facts,IF(Facts[Quantity]>2,Facts[Quantity]/0,"5"))', "6"),
            ('COUNTAX(Facts,SWITCH(TRUE(),Facts[Sales]>1,0/0,NOT(TRUE())))', "6"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual("match", status(expected, actual), f"{expr}: expected {expected}, got {actual}")

    def test_part_a2_constant_if_in_countx(self) -> None:
        cases = [
            ("COUNTX(Facts,IF(TRUE(),TRUE(),Facts[Note]))", "6"),
            ("COUNTX(Facts,IF(TRUE(),NOT(TRUE()),1/0))", "6"),
            ("COUNTX(Facts,IF(1=1,TRUE(),Facts[Sales]))", "6"),
            ('COUNTX(Facts,IF.EAGER(TRUE(),TRUE(),"a"))', "6"),
            ('COUNTX(Facts,IF.EAGER(TRUE(),TRUE(),"5"))', "6"),
            ("COUNTX(Facts,IF.EAGER(TRUE(),TRUE(),1/0))", "BLANK"),
            ("COUNTX(Facts,SWITCH(TRUE(),TRUE(),NOT(TRUE()),1/0))", "BLANK"),
            ("COUNTX(Facts,SWITCH(TRUE(),TRUE(),Facts[Quantity]>2,Facts[Region]))", "BLANK"),
            ('COUNTX(Facts,IF.EAGER(TRUE(),Facts[Quantity]>2,Facts[Region]))', "BLANK"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual("match", status(expected, actual), f"{expr}: expected {expected}, got {actual}")


class IteratorsTyped3PartBTest(unittest.TestCase):
    """Part B1: BLANK() in iterators; Part B2: One-column tables in scalar positions."""

    def test_part_b1_blank_in_iterators(self) -> None:
        cases = [
            ("MEDIANX(FILTER(Facts,FALSE()),BLANK())", "BLANK"),
            ('MEDIANX(CALCULATETABLE(Facts,Facts[Region]="East"),BLANK())', "BLANK"),
            ("PRODUCTX(GENERATESERIES(1,0),BLANK())", "BLANK"),
            ('VARX.P(CALCULATETABLE(Facts,Facts[Region]="East"),BLANK())', "BLANK"),
            ('COUNTX(Facts,IF(BLANK(),VALUE("x"),DATE(2020,1,1)+Facts[Quantity]))', "6"),
            ("COUNTAX(Facts,IF(BLANK(),2.5,Facts[Note]))", "4"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual("match", status(expected, actual), f"{expr}: expected {expected}, got {actual}")

    def test_part_b2_one_column_tables_in_scalar_positions(self) -> None:
        cases = [
            ("CALCULATE(COUNTROWS(Facts),VAR t = 2 RETURN ALL(Facts))", "6"),
            ("CALCULATE(SUM(Facts[Quantity]),VAR t = 2 RETURN ALL(Facts))", "15"),
            ('CALCULATE(COUNTROWS(Facts),Facts[Region]="East",VAR t = 2 RETURN ALL(Facts))', "3"),
            ("SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),VAR t = 2 RETURN ALL(Facts)))", "18"),
            ("COUNTAX(TOPN(0,Facts),VALUES(Facts[Region]))", "BLANK"),
            ("MINX(UNION(FILTER(Facts,FALSE()),FILTER(Facts,FALSE())),VALUES(Facts[Region]))", "BLANK"),
            ("MAXX(EXCEPT(Facts,Facts),VALUES(Facts[Region]))", "BLANK"),
            ('COUNTROWS(ADDCOLUMNS(CALCULATETABLE(Facts,Facts[Region]="East"),"q",VALUES(Facts[Region])))', "3"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual("match", status(expected, actual), f"{expr}: expected {expected}, got {actual}")


class IteratorsTyped3PartCTest(unittest.TestCase):
    """Part C1: == between Variants; Part C2: Date beside number; Part C3: Text/date conditions; Part C4: FIRSTNONBLANK; Part C5: PRODUCTX/MEDIANX constant IF."""

    def test_part_c1_strict_equal_between_variants(self) -> None:
        cases = [
            ('IF(MAX(Facts[Region])==IF(FALSE(),TRUE(),1),1,2)', "2"),
            ('IF(FALSE(),1,"a")==DATE(2020,1,1)', "False"),
            ('IF(TRUE(),TRUE(),"a")==SWITCH(TRUE(),TRUE(),1,"a")', "False"),
            ('IF(TRUE()==IF.EAGER(FALSE(),1,"a"),1,2)', "2"),
            ('FALSE()==COALESCE(1,"a")', "False"),
            ('COALESCE("a",1)==DATE(2020,1,1)', "False"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual("match", status(expected, actual), f"{expr}: expected {expected}, got {actual}")

    def test_part_c2_date_beside_number(self) -> None:
        cases = [
            ("IF(FALSE(),-3,DATE(2020,1,1)+0.5)", "43831.5"),
            ('CALCULATE(IF(TRUE(),DATE(2020,1,1)+0.5,-3),Facts[Region]="East")', "43831.5"),
            ('CALCULATE(IF(TRUE(),DATE(2020,1,1)+0.5,1),Facts[Region]="East")', "43831.5"),
            ("IF(1,DATE(2020,1,1),-3)", "43831"),
            ('IF(TRUE(),DATE(2020,1,1),1)>IF(1=1,5,"x")', "True"),
            ("IF(TRUE(),TIME(6,0,0)+TRUE(),1)", "1.25"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual("match", status(expected, actual), f"{expr}: expected {expected}, got {actual}")

    def test_part_c3_text_or_date_condition_in_if(self) -> None:
        cases = [
            ('MAXX(Facts,IF.EAGER("",PI(),Facts[Region]))', "BLANK"),
            ('MAXX(Facts,IF("TRUE",NOT(Facts[Quantity]>2),Facts[Region]))', "BLANK"),
            ('MAXX(Facts,IF.EAGER(DATE(2020,1,1),ROUND(2.5,0),Facts[Region]))', "3"),
            ('MAXX(Facts,IF.EAGER("TRUE",PI(),Facts[Region]))', "3.14159265358979"),
            ('MAXX(Facts,IF("TRUE",LEFT("a",1),Facts[Region]))', "a"),
            ('MAXX(Facts,IF.EAGER(DATE(2020,1,1),1=1,Facts[Region]))', "BLANK"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual("match", status(expected, actual), f"{expr}: expected {expected}, got {actual}")

    def test_part_c4_firstnonblank_in_comparisons(self) -> None:
        cases = [
            ("CALCULATE(COUNTROWS(Facts),Facts[Quantity]<FIRSTNONBLANKVALUE(Facts[Quantity],MAX(Facts[Quantity])))", "BLANK"),
            ("CALCULATE(SUM(Facts[Quantity]),Facts[Quantity]>FIRSTNONBLANKVALUE(Facts[Quantity],SUM(Facts[Quantity])))", "15"),
            ("CALCULATE(COUNTROWS(Facts),Facts[Sales]<FIRSTNONBLANKVALUE(Facts[Quantity],SUM(Facts[Quantity])))", "1"),
            ("CALCULATE(COUNTROWS(Facts),Facts[Quantity]=FIRSTNONBLANKVALUE(Facts[Quantity],SUM(Facts[Quantity])))", "1"),
            ('MAXX(Facts,FIRSTNONBLANK(Facts[Region],1))', "West"),
            ('COUNTROWS(FILTER(VALUES(Facts[Note]),FIRSTNONBLANK(Facts[Region],1)="West"))', "BLANK"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual("match", status(expected, actual), f"{expr}: expected {expected}, got {actual}")

    def test_part_c5_productx_medianx_constant_if_text(self) -> None:
        cases = [
            ("MEDIANX(Facts,IF(TRUE(),Facts[Region],+7))", "BLANK"),
            ("PRODUCTX(Facts,IF(1=1,Facts[Region],TRUE()&&FALSE()))", "BLANK"),
            ("MEDIANX(Facts,IF.EAGER(FALSE(),-7,Facts[Region]))", "BLANK"),
            ("PRODUCTX(Facts,IF.EAGER(1=1,Facts[Region],2.5))", "BLANK"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual("match", status(expected, actual), f"{expr}: expected {expected}, got {actual}")


class IteratorsTyped3PartDTest(unittest.TestCase):
    """Part D1: VAR in filters; Part D2: KEEPFILTERS around table or inside EVALUATEANDLOG."""

    def test_part_d1_var_in_filters(self) -> None:
        cases = [
            ("CALCULATE(COUNTROWS(Facts),VAR t = COUNTROWS(Facts) RETURN Facts[Quantity]>t)", "BLANK"),
            ("SUMX(VALUES(Facts[Region]),CALCULATE(COUNTROWS(Facts),VAR t = 2*3 RETURN Facts[Quantity]<t))", "6"),
            ("CALCULATE(COUNTROWS(Facts),VAR t=VALUES(Facts[Region]) RETURN COUNTROWS(t)<Facts[Quantity])", "2"),
            ("CALCULATE(SUM(Facts[Quantity]),VAR t = COUNTROWS(VALUES(Facts[Region])) RETURN Facts[Quantity]>t)", "9"),
            ("CALCULATE(COUNTROWS(Facts),VAR t = 2 VAR u = t+1 RETURN Facts[Quantity]>u)", "2"),
            ('CALCULATE(COUNTROWS(Facts),Facts[Region]="East",VAR t = IF(TRUE(),2,3) RETURN Facts[Quantity]>t)', "1"),
            ('CALCULATE(COUNTROWS(Facts),VAR t = IF(TRUE(),2,3) RETURN Facts[Quantity]>t)', "3"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual("match", status(expected, actual), f"{expr}: expected {expected}, got {actual}")

    def test_part_d2_keepfilters(self) -> None:
        cases = [
            ('CALCULATE(COUNTROWS(Facts),EVALUATEANDLOG(KEEPFILTERS(Facts[Region]="East")))', "3"),
            ('CALCULATE(COUNTROWS(Facts),EVALUATEANDLOG(KEEPFILTERS(Facts[Region]="East"),"lbl"))', "3"),
            ('CALCULATE(COUNTROWS(Facts),EVALUATEANDLOG(EVALUATEANDLOG(KEEPFILTERS(Facts[Region]="East"))))', "3"),
            ('CALCULATE(SUM(Facts[Quantity]),EVALUATEANDLOG(KEEPFILTERS(Facts[Region]="East")))', "8"),
            ('COUNTROWS(ADDCOLUMNS(KEEPFILTERS(CALCULATETABLE(Facts,Facts[Region]="Nowhere")),"q",TRUE()))', "BLANK"),
            ('COUNTROWS(FILTER(KEEPFILTERS(FILTER(Facts,FALSE())),Facts[Sales]))', "BLANK"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual("match", status(expected, actual), f"{expr}: expected {expected}, got {actual}")


class AlternateTablesTest(unittest.TestCase):
    """Test on alternate Facts tables: fixtures_misc3_alt.json and fixtures_variant2_review_alt.json."""

    def test_alternate_tables_rules_consistency(self) -> None:
        misc3 = json.loads(FIXTURES_MISC3_PATH.read_text())
        for key, dataset in misc3["datasets"].items():
            rows = [tuple(r) for r in dataset["rows"]]
            # Spot check Part A2, C2, C5 on alternate tables
            self.assertEqual("match", status("BLANK", _local_on(rows, "PRODUCTX(Facts,IF.EAGER(1=1,Facts[Region],2.5))")))
            self.assertEqual("match", status("43831", _local_on(rows, "IF(1,DATE(2020,1,1),-3)")))

        variant2 = json.loads(FIXTURES_VARIANT2_PATH.read_text())
        for key, dataset in variant2["datasets"].items():
            rows = [tuple(r) for r in dataset["rows"]]
            self.assertEqual("match", status("BLANK", _local_on(rows, "PRODUCTX(Facts,IF.EAGER(1=1,Facts[Region],2.5))")))
            self.assertEqual("match", status("43831", _local_on(rows, "IF(1,DATE(2020,1,1),-3)")))
            self.assertEqual("match", status("BLANK", _local_on(rows, "MEDIANX(FILTER(Facts,FALSE()),BLANK())")))
            self.assertEqual("match", status("False", _local_on(rows, 'IF(FALSE(),1,"a")==DATE(2020,1,1)')))
            self.assertEqual("match", status("a", _local_on(rows, 'MAXX(Facts,IF("TRUE",LEFT("a",1),Facts[Region]))')))


if __name__ == "__main__":
    unittest.main()
