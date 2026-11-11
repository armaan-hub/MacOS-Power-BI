"""Iteration 104: typed-columns-5 (Task 15).

Plan: docs/plans/2026-10-31-typed-columns-5.md
Parts:
  - Part A1: True/False BLANK in table columns (ADDCOLUMNS, table constructor)
  - Part A2: ISLOGICAL over logical operators
  - Part B1: Currency in conditionals inside statistical iterators
  - Part B2: Date in VARX / STDEVX
  - Part C1: Types of added columns (ISDOUBLE, ISINT64, ISDECIMAL, ISCURRENCY)
  - Part D1: FILTER over no rows with table/text predicate; IFERROR with VAR
  - Part D2: Table variables in CALCULATE filters and DISTINCT; constructor in FILTER over no rows
  - Part D3: COALESCE / IFERROR with earlier failing argument in iterators
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_MISC3_PATH = ROOT / "tests" / "fixtures_misc3_alt.json"
FIXTURES_VARIANT2_PATH = ROOT / "tests" / "fixtures_variant2_review_alt.json"
FIXTURES_TYPED3_PATH = ROOT / "tests" / "fixtures_typed3_review_alt.json"
FIXTURES_LOGIC4_PATH = ROOT / "tests" / "fixtures_logic4_review_alt.json"


def _local_on(rows: list[tuple[str, ...] | list[str]], expression: str) -> str:
    saved = (dax.ROWS, dax.LOCAL_ROWS)
    dax.ROWS = [tuple(r) for r in rows]
    dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, row)} for row in rows]
    try:
        return dax.local(expression)
    finally:
        dax.ROWS, dax.LOCAL_ROWS = saved


class PartA1TableColumnLogicalBlankTest(unittest.TestCase):
    """Part A1: In table columns, a logical blank stays typed True/False."""

    def test_addcolumns_logical_blank(self) -> None:
        self.assertEqual("6", dax.local('COUNTROWS(ADDCOLUMNS(Facts,"q",2.5&&""))'))
        self.assertEqual("BLANK", dax.local('COUNTAX(ADDCOLUMNS(Facts,"q",2.5&&""),[q])'))
        self.assertEqual("BLANK", dax.local('COUNTAX(ADDCOLUMNS(Facts,"q",OR(0,UPPER(""))),[q])'))
        self.assertEqual("z|z|z|z|z|z", dax.local('CONCATENATEX(ADDCOLUMNS(Facts,"q",2.5&&""),[q]&"z","|")'))
        # MAXX over a Boolean column fails with exact Power BI message
        res = dax.local('MAXX(ADDCOLUMNS(Facts,"q",2.5&&""),[q])')
        self.assertTrue(res.startswith("LOCAL-REJECT") and "cannot work with values of type Boolean" in res, res)

    def test_tableconstructor_logical_blank(self) -> None:
        self.assertEqual("1", dax.local('COUNTROWS({2.5&&""})'))
        self.assertEqual("1", dax.local('COUNTAX({1&&""},[Value])'))
        self.assertEqual("2", dax.local('SUMX({OR("false","")},IF([Value],1,2))'))
        self.assertEqual("BLANK", dax.local('COUNTROWS(FILTER({1&&LEFT("a",0)},[Value]))'))
        self.assertEqual("1", dax.local('COUNTAX({"TRUE"&&""},[Value])'))
        self.assertEqual("1", dax.local('COUNTAX({BLANK()||""},[Value])'))


class PartCAddedColumnsTypingTest(unittest.TestCase):
    """Part C: ISINT64, ISDOUBLE, ISDECIMAL, ISCURRENCY of added columns derive from expression, never name."""

    def test_added_column_types(self) -> None:
        cases = [
            ('ISDOUBLE(MAXX(ADDCOLUMNS(Facts,"Slope1",1),[Slope1]))', "False"),
            ('ISDOUBLE(MAXX(ADDCOLUMNS(Facts,"Slope1",1.5),[Slope1]))', "True"),
            ('ISINT64(MAXX(ADDCOLUMNS(Facts,"Slope1",1),[Slope1]))', "True"),
            ('ISDOUBLE(MAXX(ADDCOLUMNS(Facts,"Intercept",1.5),[Intercept]))', "True"),
            ('ISINT64(MAXX(ADDCOLUMNS(Facts,"DegreesOfFreedom",CURRENCY(1)),[DegreesOfFreedom]))', "False"),
            ('ISCURRENCY(MAXX(ADDCOLUMNS(Facts,"DegreesOfFreedom",CURRENCY(1)),[DegreesOfFreedom]))', "True"),
            ('ISDOUBLE(MAXX(SELECTCOLUMNS(Facts,"q",1.5),[q]))', "True"),
            ('ISDOUBLE(MAXX(SELECTCOLUMNS(Facts,"q",1),[q]))', "False"),
            ('ISINT64(MAXX(SELECTCOLUMNS(Facts,"q",1),[q]))', "True"),
            ('ISDOUBLE(MAXX(ADDCOLUMNS(LINESTX(Facts,Facts[Quantity],Facts[Sales]),"z",[Slope1]),[z]))', "True"),
            ('ISDOUBLE(MAXX(ADDCOLUMNS(LINESTX(Facts,Facts[Quantity],Facts[Sales]),"z",[DegreesOfFreedom]),[z]))', "True"),
            ('ISDOUBLE(MAXX(ADDCOLUMNS(LINESTX(Facts,Facts[Quantity],Facts[Sales]),"z",1),[z]))', "False"),
            ('ISDOUBLE(MAXX(ADDCOLUMNS(LINESTX(Facts,Facts[Quantity],Facts[Sales]),"z",2.5),[z]))', "True"),
            ('ISDOUBLE(VAR t=LINESTX(Facts,Facts[Quantity],Facts[Sales]) RETURN MAXX(t,[Slope1]))', "True"),
            ('ISCURRENCY(CURRENCY(10.00005)+BLANK())', "True"),
            ('ISCURRENCY(BLANK()+CURRENCY(10.00005))', "True"),
        ]
        for expr, expected in cases:
            self.assertEqual(expected, dax.local(expr), expr)


class PartD1FilterNoRowsTest(unittest.TestCase):
    """Part D1: FILTER over no rows with predicate that is table or text; IFERROR with VAR."""

    def test_filter_over_no_rows(self) -> None:
        cases = [
            ('COUNTROWS(FILTER(FILTER(Facts,FALSE()),ALL(Facts[Region])))', "BLANK"),
            ('COUNTROWS(FILTER(FILTER(Facts,1=0),ALL(Facts[Region])))', "BLANK"),
            ('COUNTROWS(FILTER(CALCULATETABLE(Facts,LEN(Facts[Region])>100),"a"))', "BLANK"),
            ('COUNTROWS(FILTER(TOPN(0,Facts),ALL(Facts[Region])))', "BLANK"),
            ('COUNTROWS(FILTER(EXCEPT(Facts,Facts),ALL(Facts[Region])))', "BLANK"),
            ('COUNTROWS(FILTER(GENERATESERIES(1,0),ALL(Facts[Region])))', "BLANK"),
            ('COUNTROWS(FILTER(CALCULATETABLE(Facts,Facts[Region]="Nowhere"),ALL(Facts[Region])))', "BLANK"),
            ('COUNTROWS(FILTER(CALCULATETABLE(Facts,Facts[Quantity]>100),""))', "BLANK"),
            ('COUNTROWS(FILTER(CALCULATETABLE(Facts,Facts[Region]>"zzz"),"a"))', "BLANK"),
            ('COUNTROWS(FILTER(CALCULATETABLE(Facts,Facts[Region]<>Facts[Region]),"a"))', "BLANK"),
        ]
        for expr, expected in cases:
            self.assertEqual(expected, dax.local(expr), expr)

    def test_iferror_and_var(self) -> None:
        self.assertEqual("True", dax.local('ISERROR("a"&&VAR y="b" RETURN y)'))
        self.assertEqual("7", dax.local('IFERROR("a"&&VAR y="b" RETURN y,7)'))
        self.assertEqual("7", dax.local('IFERROR(AND(MAX(Facts[Region]),VAR y="b" RETURN y),7)'))
        self.assertEqual("7", dax.local('IFERROR(OR(MAX(Facts[Region]),VAR y="b" RETURN y),7)'))
        # Hard errors (like ERROR("x")) remain uncatchable
        res = dax.local('IFERROR("a"&&VAR y=ERROR("x") RETURN y,7)')
        self.assertTrue(res.startswith("LOCAL-REJECT"), res)


class PartD2TableVariablesAndConstructorsTest(unittest.TestCase):
    """Part D2: Table variables in CALCULATE and DISTINCT; constructor as FILTER predicate over empty."""

    def test_calculate_table_variable(self) -> None:
        self.assertEqual("3", dax.local('CALCULATE(COUNTROWS(Facts),VAR t=FILTER(Facts,Facts[Quantity]>2) RETURN t)'))
        self.assertEqual("12", dax.local('CALCULATE(SUM(Facts[Quantity]),VAR t=FILTER(Facts,Facts[Quantity]>2) RETURN t)'))
        self.assertEqual("4", dax.local('CALCULATE(COUNTROWS(Facts),VAR a=1 VAR t=FILTER(Facts,Facts[Quantity]>a) RETURN t)'))
        self.assertEqual("12", dax.local('CALCULATE(SUM(Facts[Quantity]),KEEPFILTERS(VAR t=FILTER(Facts,Facts[Quantity]>2) RETURN t))'))

    def test_distinct_table_variable(self) -> None:
        self.assertEqual("2", dax.local('COUNTROWS(DISTINCT(VAR r="West" RETURN FILTER(VALUES(Facts[Region]),Facts[Region]<>r)))'))
        self.assertEqual("3", dax.local('COUNTROWS(DISTINCT(VAR t=FILTER(Facts,Facts[Quantity]>2) RETURN t))'))
        self.assertEqual("6", dax.local('COUNTROWS(DISTINCT(VAR t=Facts RETURN t))'))

    def test_filter_empty_with_constructor_predicate(self) -> None:
        self.assertEqual("BLANK", dax.local('COUNTROWS(FILTER(FILTER(Facts,FALSE()),{1,2}))'))
        self.assertEqual("BLANK", dax.local('COUNTROWS(FILTER(FILTER(Facts,1=0),{1,2}))'))
        self.assertEqual("BLANK", dax.local('COUNTROWS(FILTER(TOPN(0,Facts),{1,2}))'))
        self.assertEqual("BLANK", dax.local('COUNTROWS(FILTER(EXCEPT(Facts,Facts),{1,2}))'))
        self.assertEqual("BLANK", dax.local('COUNTROWS(FILTER(GENERATESERIES(1,0),{1,2}))'))


class PartD3CoalesceInIteratorsTest(unittest.TestCase):
    """Part D3: COALESCE with earlier failing argument inside iterators."""

    def test_coalesce_in_iterators(self) -> None:
        cases = [
            ('MAXX(Facts,COALESCE(CUSTOMDATA(),"d"))', "d"),
            ('MINX(Facts,COALESCE(CUSTOMDATA(),"d"))', "d"),
            ('COUNTX(Facts,COALESCE(CUSTOMDATA(),"d"))', "6"),
            ('COUNTAX(Facts,COALESCE(LEFT(Facts[Region],1),0))', "6"),
            ('SUMX(Facts,IF(VAR t=TRUE() RETURN COALESCE(t,0)="",1,0))', "0"),
            ('MAXX(Facts,COALESCE(AVERAGEX(Facts,DATE(2020,1,1)+Facts[Quantity]),"a"))', "43833.5"),
            ('COUNTX(DISTINCT(Facts),IFERROR(FORMAT(1,"0"),NOT(TRUE())))', "BLANK"),
        ]
        for expr, expected in cases:
            self.assertEqual(expected, dax.local(expr), expr)


class PartBStatisticalIteratorsTest(unittest.TestCase):
    """Part B: Statistical iterators with currency / date conditionals."""

    def test_zero_variance_dates(self) -> None:
        self.assertEqual("0", dax.local('VARX.P(CALCULATETABLE(Facts,Facts[Region]="East"),DATE(2020,1,1))'))
        self.assertEqual("0", dax.local('VARX.P(CALCULATETABLE(Facts,Facts[Region]="East"),DATE(2020,1,1)+1)'))
        self.assertEqual("0", dax.local('VARX.P(Facts,IFERROR(DATE(2020,1,1),1+1))'))
        self.assertEqual("BLANK", dax.local('VARX.P(DISTINCT(Facts),IF(1=2,DATE(2020,1,1)+Facts[Quantity]))'))

    def test_currency_in_iterators(self) -> None:
        # Currency in conditionals inside statistical iterators produces mixed float/integer scales in Power BI
        # (e.g. 6.09924039791019E-320), so the local engine honestly refuses them per Rule 3.
        # live Power BI (Task 131 review, 2026-11-11): these are now modelled and match Power BI
        self.assertTrue(dax.same("216", dax.local('PRODUCTX(ALL(Facts),IF.EAGER(Facts[Region]="East",CURRENCY(3),1+1))')))
        self.assertTrue(dax.same("243", dax.local('PRODUCTX(Facts,VAR x=CURRENCY(3) RETURN IF(Facts[Quantity],x,Facts[Quantity]>2))')))
        # Empty iterations over currency conditional:
        self.assertEqual("BLANK", dax.local('PRODUCTX(TOPN(0,Facts),CURRENCY(1.23456))'))


class AlternateTablesCrossValidationTest(unittest.TestCase):
    """Rule 2: Check rules across alternate datasets (A, B, N) to guarantee semantics are general."""

    def test_on_alternate_tables(self) -> None:
        with open(FIXTURES_MISC3_PATH) as f:
            misc3_data = json.load(f)["datasets"]
        with open(FIXTURES_TYPED3_PATH) as f:
            typed3_data = json.load(f)["datasets"]

        for ds_name, rows in [("misc3_A", misc3_data["A"]["rows"]), ("misc3_B", misc3_data["B"]["rows"]),
                              ("typed3_N", typed3_data["N"]["rows"]), ("typed3_A", typed3_data["A"]["rows"]), ("typed3_B", typed3_data["B"]["rows"])]:
            n = str(len(rows))
            # Part A1 on alternate table:
            self.assertEqual(n, _local_on(rows, 'COUNTROWS(ADDCOLUMNS(Facts,"q",2.5&&""))'))
            self.assertEqual("BLANK", _local_on(rows, 'COUNTAX(ADDCOLUMNS(Facts,"q",2.5&&""),[q])'))
            # Table constructor is independent of table rows:
            self.assertEqual("1", _local_on(rows, 'COUNTROWS({2.5&&""})'))
            self.assertEqual("1", _local_on(rows, 'COUNTAX({1&&""},[Value])'))
            # Part C on alternate table:
            self.assertEqual("True", _local_on(rows, 'ISDOUBLE(MAXX(ADDCOLUMNS(Facts,"Slope1",1.5),[Slope1]))'))
            self.assertEqual("False", _local_on(rows, 'ISDOUBLE(MAXX(ADDCOLUMNS(Facts,"Slope1",1),[Slope1]))'))
            # Part D1 on alternate table:
            self.assertEqual("BLANK", _local_on(rows, 'COUNTROWS(FILTER(FILTER(Facts,FALSE()),ALL(Facts[Region])))'))
            self.assertEqual("BLANK", _local_on(rows, 'COUNTROWS(FILTER(CALCULATETABLE(Facts,Facts[Quantity]>1000),""))'))
            # Part D2 on alternate table:
            self.assertEqual("BLANK", _local_on(rows, 'COUNTROWS(FILTER(FILTER(Facts,FALSE()),{1,2}))'))


if __name__ == "__main__":
    unittest.main()
