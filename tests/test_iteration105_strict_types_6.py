"""Iteration 105: strict-types-6 (Task 16).

Plan: docs/plans/2026-11-01-strict-types-6.md
Parts:
  - Part A1: Strict comparison (==) between column and True/False/number/text
  - Part A2: Text ordering ignores hyphens
  - Part A3: Currency arithmetic and division by zero over added columns
  - Part A4: Typed BLANK through IF, SWITCH, and in table columns
  - Part B: Static types of added / transformed table columns (CROSSJOIN, UNION, tableconstructor)
  - Part C: ISLOGICAL over logical operators that give BLANK
  - Part D: Typed BLANK beside text or date in table constructors
  - Part E: Strict comparison (==) over blank columns
  - Part F: Tables and VARs as CALCULATE filters; == with LASTNONBLANKVALUE
  - Part G: COALESCE whose earlier argument can fail in iterators
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_MISC3_PATH = ROOT / "tests" / "fixtures_misc3_alt.json"
FIXTURES_LOGIC4_PATH = ROOT / "tests" / "fixtures_logic4_review_alt.json"


def _local_on(rows: list[tuple[str, ...] | list[str]], expression: str) -> str:
    saved = (dax.ROWS, dax.LOCAL_ROWS)
    dax.ROWS = [tuple(r) for r in rows]
    dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, row)} for row in rows]
    try:
        return dax.local(expression)
    finally:
        dax.ROWS, dax.LOCAL_ROWS = saved


class PartA1StrictComparisonTypeMismatchTest(unittest.TestCase):
    """Part A1: == between columns and scalars of mismatched types raises DAX comparison error."""

    def test_integer_column_against_boolean_raises(self) -> None:
        for expr in (
            'SUMX({2.5&&"",1},IF([Value]==FALSE(),1,2))',
            'SUMX(ADDCOLUMNS({1,2},"Value2",2.5&&""),IF([Value]==FALSE(),1,2))',
            'SUMX({1,2},IF([Value]==FALSE(),1,2))',
        ):
            res = dax.local(expr)
            self.assertTrue(
                res.startswith("LOCAL-REJECT") and "DAX comparison operations do not support comparing values of type Integer with values of type True/False" in res,
                f"Expected Integer vs True/False mismatch in {expr}, got {res}",
            )


class PartA2TextOrderingHyphenTest(unittest.TestCase):
    """Part A2: Text ordering ignores hyphens at primary collation level."""

    def test_hyphen_ignored_in_text_ordering(self) -> None:
        self.assertEqual("-1", dax.local('MAXX({"-1","0"},[Value])'))
        self.assertEqual("0", dax.local('MINX({"-1","0"},[Value])'))
        self.assertEqual("a-b", dax.local('MAXX({"a-b","ab"},[Value])'))
        self.assertEqual("2", dax.local('MAXX({"-1","0","2"},[Value])'))
        self.assertEqual("-1", dax.local('MAXX({2.5&&"",TRUE()},FORMAT([Value],"General Number"))'))


class PartA3CurrencyAddedColumnTest(unittest.TestCase):
    """Part A3: Currency over added columns raises division by zero and preserves 4 decimal places."""

    def test_division_by_zero_over_added_currency(self) -> None:
        for expr in (
            'SUMX(ADDCOLUMNS(Facts,"c",CURRENCY(1)),[c]/0)',
            'MAXX(ADDCOLUMNS(Facts,"c",CURRENCY(1)),[c]/0)',
            'SUMX(ADDCOLUMNS(Facts,"c",CURRENCY(1)),[c]/BLANK())',
            'ISERROR(SUMX(ADDCOLUMNS(Facts,"c",CURRENCY(1)),[c]/0))',
        ):
            res = dax.local(expr)
            self.assertTrue(
                res.startswith("LOCAL-REJECT") and "A division by zero has been encountered" in res,
                f"Expected division by zero in {expr}, got {res}",
            )

    def test_currency_division_digits_preserved(self) -> None:
        self.assertEqual("-5.7167", dax.local('SUMX(ADDCOLUMNS(Facts,"c",CURRENCY(1)),IFERROR([c]/Facts[Quantity]-Facts[Quantity],7))'))


class PartA4TypedBlankThroughIfTest(unittest.TestCase):
    """Part A4: A typed BLANK through IF or SWITCH is a plain BLANK."""

    def test_typed_blank_through_if(self) -> None:
        self.assertEqual("BLANK", dax.local('COUNTAX(ADDCOLUMNS(Facts,"q",IF(TRUE(),2.5&&"")),[q])'))
        self.assertEqual("6", dax.local('SUMX(ADDCOLUMNS(Facts,"q",IF(TRUE(),2.5&&"")),IF(ISBLANK([q]),1,2))'))
        self.assertEqual("BLANK", dax.local('COUNTAX({IF(TRUE(),2.5&&"")},[Value])'))
        self.assertEqual("True", dax.local('ISBLANK(IF(TRUE(),2.5&&""))'))
        self.assertEqual("False", dax.local('ISLOGICAL(IF(TRUE(),2.5&&""))'))
        self.assertEqual("True", dax.local('ISBLANK(SWITCH(TRUE(),TRUE(),2.5&&""))'))
        self.assertEqual("False", dax.local('ISLOGICAL(SWITCH(TRUE(),TRUE(),2.5&&""))'))
        # Column still recognized as Boolean type by MAXX
        res = dax.local('MAXX({COALESCE(2.5&&"",FALSE())},[Value])')
        self.assertTrue(res.startswith("LOCAL-REJECT") and "cannot work with values of type Boolean" in res, res)


class PartBStaticColumnTypesTest(unittest.TestCase):
    """Part B: Static types of derived and transformed table columns."""

    def test_blank_and_date_arithmetic_types(self) -> None:
        self.assertEqual("False", dax.local('ISINT64(MAXX(SELECTCOLUMNS(Facts,"Quantity",BLANK()-DATE(2020,1,1)),[Quantity]))'))
        self.assertEqual("True", dax.local('ISDOUBLE(MAXX(SELECTCOLUMNS(Facts,"Quantity",BLANK()-DATE(2020,1,1)),[Quantity]))'))
        self.assertEqual("False", dax.local('ISINT64(MAXX(SELECTCOLUMNS(Facts,"Quantity",DATE(2020,1,1)+BLANK()),[Quantity]))'))
        self.assertEqual("False", dax.local('ISDOUBLE(MAXX(SELECTCOLUMNS(Facts,"Quantity",DATE(2020,1,1)+BLANK()),[Quantity]))'))
        self.assertEqual("False", dax.local('ISINT64(MAXX(SELECTCOLUMNS(Facts,"Quantity",BLANK()+BLANK()),[Quantity]))'))
        self.assertEqual("False", dax.local('ISDOUBLE(MAXX(SELECTCOLUMNS(Facts,"Quantity",BLANK()+BLANK()),[Quantity]))'))

    def test_crossjoin_and_union_static_types(self) -> None:
        self.assertEqual("False", dax.local('ISINT64(MAXX(CROSSJOIN(SELECTCOLUMNS(Facts,"Other",CURRENCY(1)),{1}),[Other]))'))
        self.assertEqual("False", dax.local('ISINT64(MAXX(UNION(SELECTCOLUMNS(Facts,"Other",CURRENCY(1)),SELECTCOLUMNS(Facts,"Other",CURRENCY(1))),[Other]))'))
        self.assertEqual("True", dax.local('ISINT64(MAXX(CROSSJOIN(SELECTCOLUMNS(Facts,"Other",1),{1}),[Other]))'))
        self.assertEqual("True", dax.local('ISINT64(MAXX(UNION(SELECTCOLUMNS(Facts,"Other",1),SELECTCOLUMNS(Facts,"Other",1)),[Other]))'))

    def test_tableconstructor_static_types(self) -> None:
        self.assertEqual("True", dax.local('ISINT64(MAXX({2.5&&"",3},[Value]))'))
        self.assertEqual("False", dax.local('ISINT64(MAXX({2.5&&"",3.5},[Value]))'))
        self.assertEqual("False", dax.local('ISINT64(MAXX({2.5&&"",CURRENCY(3)},[Value]))'))
        self.assertEqual("True", dax.local('ISINT64(MAXX({2.5&&"",0},[Value]))'))


class PartDTypedBlankBesideTextOrDateTest(unittest.TestCase):
    """Part D: A logical operator giving BLANK beside text or date is kept refused (Rule 3)."""

    def test_typed_blank_beside_text_or_date_refused(self) -> None:
        refusal = "A logical operator that gives BLANK beside a text or a date in a table constructor is not modelled by the local engine."
        self.assertIn(refusal, dax.local('SUMX({2.5&&"","a"},IF(ISBLANK([Value]),1,2))'))
        self.assertIn(refusal, dax.local('MAXX({2.5&&"",DATE(2020,1,1)},[Value])'))


class PartEStrictEqualBlankColumnTest(unittest.TestCase):
    """Part E: == over blank columns evaluates without raising type-unknown refusal."""

    def test_strict_equal_over_blank_column(self) -> None:
        self.assertEqual("4", dax.local('SUMX({2.5&&"",BLANK()},IF([Value]==FALSE(),1,2))'))
        self.assertEqual("12", dax.local('SUMX(ADDCOLUMNS(Facts,"Value",2.5&&""),IF([Value]==FALSE(),1,2))'))
        self.assertEqual("12", dax.local('SUMX(SELECTCOLUMNS(Facts,"Value",2.5&&""),IF([Value]==FALSE(),1,2))'))


class PartFCalculateFiltersTest(unittest.TestCase):
    """Part F: Tables and VARs as CALCULATE filters; == with LASTNONBLANKVALUE."""

    def test_calculate_table_var_filters(self) -> None:
        self.assertEqual("1", dax.local('CALCULATE(COUNTROWS(Facts),Facts[Quantity]==LASTNONBLANKVALUE(Facts[Quantity],MAX(Facts[Quantity])))'))
        self.assertEqual("2", dax.local('CALCULATE(COUNTROWS(Facts),VAR t=TOPN(2,Facts,Facts[Quantity],DESC,Facts[Sales],ASC,Facts[Region],ASC) RETURN t)'))
        self.assertEqual("6", dax.local('CALCULATE(COUNTROWS(Facts),VAR t=ADDCOLUMNS(Facts,"q",Facts[Quantity]*2) RETURN t)'))
        self.assertEqual("6", dax.local('CALCULATE(COUNTROWS(Facts),VAR t=SUMMARIZE(Facts,Facts[Region]) RETURN t)'))
        self.assertEqual("9", dax.local('CALCULATE(SUM(Facts[Quantity]),VAR t=TOPN(2,Facts,Facts[Quantity],DESC,Facts[Sales],ASC,Facts[Region],ASC) RETURN t)'))

    def test_calculate_var_with_calculate_scalar(self) -> None:
        self.assertEqual("1", dax.local('CALCULATE(COUNTROWS(Facts),VAR m=CALCULATE(MAX(Facts[Quantity])) RETURN FILTER(Facts,Facts[Quantity]=m))'))


class PartGCoalesceFailingArgumentTest(unittest.TestCase):
    """Part G: COALESCE with earlier argument in iterators."""

    def test_coalesce_with_table_iterators_stays_refused(self) -> None:
        # Part G stays refused: widening the guard gave wrong answers on fresh probes (Task 16 review)
        for expr in (
            'MAXX(Facts,COALESCE(BLANK(),SUMX(VALUES(Facts[Region]),DATE(2020,1,1)),1))',
            'SUMX(Facts,COALESCE(BLANK(),SUMX(VALUES(Facts[Region]),DATE(2020,1,1)),1))',
            'MAXX(Facts,COALESCE(SUMX(VALUES(Facts[Region]),DATE(2020,1,1)),"a"))',
            'MAXX(Facts,COALESCE(FIRSTNONBLANKVALUE(Facts[Quantity],BLANK()),"a"))',
        ):
            self.assertIn("COALESCE", dax.local(expr), expr)


class AlternateTablesTest(unittest.TestCase):
    """Rule 2: Check rules across alternate fixture tables."""

    def test_rules_on_alternate_tables(self) -> None:
        if not FIXTURES_MISC3_PATH.exists():
            self.skipTest("alternate fixtures not found")
        fixture = json.loads(FIXTURES_MISC3_PATH.read_text())
        for key in ("A", "B"):
            dataset = fixture["datasets"][key]
            rows = dataset["rows"]
            # Currency over added column on alt table
            self.assertTrue(
                _local_on(rows, 'SUMX(ADDCOLUMNS(Facts,"c",CURRENCY(1)),[c]/0)').startswith("LOCAL-REJECT")
            )
            # Table VAR filter on alt table
            res = _local_on(rows, 'CALCULATE(COUNTROWS(Facts),VAR t=ADDCOLUMNS(Facts,"q",Facts[Quantity]*2) RETURN t)')
            self.assertEqual(str(len(rows)), res)


if __name__ == "__main__":
    unittest.main()
