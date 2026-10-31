"""Iteration 102: logic-tables-4 (Task 14).

Plan: docs/plans/2026-10-31-logic-tables-4.md
Specification: tools/parity/task14_logic_tables_spec.json (817 items)
Parts:
  - Part A1: Empty text in logical operators (310 items)
  - Part A2: Text on the left that cannot convert (40 items)
  - Part B1: VAR block as table of iterator or table function (170 items)
  - Part B2: Text predicate in FILTER over an empty table (44 items)
  - Part B3: Many-valued table as FILTER predicate over tables empty by construction (23 items)
  - Part C1: Bodies checked too early / nested VAR definitions (121 items)
  - Part D1: ISDOUBLE / ISINT64 of LINEST statistics (56 items)
  - Part D2: XNPV over Currency values computed with arithmetic (48 items)
  - Part E: Five wrong answers to fix (5 items)
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "tools" / "parity" / "task14_logic_tables_spec.json"
FIXTURES_MISC3_PATH = ROOT / "tests" / "fixtures_misc3_alt.json"
FIXTURES_VARIANT2_PATH = ROOT / "tests" / "fixtures_variant2_review_alt.json"
FIXTURES_TYPED3_PATH = ROOT / "tests" / "fixtures_typed3_review_alt.json"


def _local_on(rows: list[tuple[str, ...]], expression: str) -> str:
    saved = (dax.ROWS, dax.LOCAL_ROWS)
    dax.ROWS = rows
    dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, row)} for row in rows]
    try:
        return dax.local(expression)
    finally:
        dax.ROWS, dax.LOCAL_ROWS = saved


class LogicTables4PartATest(unittest.TestCase):
    """Part A1: Empty text in logical operators; Part A2: Text that cannot convert."""

    def test_part_a1_empty_text_logical(self) -> None:
        cases = [
            ('2.5&&IF(TRUE(),"")', "BLANK"),
            ('OR(FALSE(),IF(TRUE(),"","a"))', "BLANK"),
            ('BLANK()||IF(TRUE(),"","a")', "BLANK"),
            ('"0"||VAR y="" RETURN y', "BLANK"),
            ('IF(1&&IF(TRUE(),"","a"),1,2)', "2"),
            ('IF(2.5&&LEFT("a",0),1,2)', "2"),
            ('IF(0||"",1,2)', "2"),
            ('("1"&&VAR y="" RETURN y)&"z"', "z"),
            ('("0"||VAR y="" RETURN y)&"z"', "z"),
            ('(TRUE()&&VAR y=IF(TRUE(),"","a") RETURN y)&"z"', "z"),
            ('ISBLANK("0"||VAR y=IF(TRUE(),"","a") RETURN y)', "False"),
            ('ISBLANK("1"&&VAR y=IF(TRUE(),"","a") RETURN y)', "False"),
            ('ISBLANK(""||VAR y=LEFT("a",0) RETURN y)', "False"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual("match", status(expected, actual), f"{expr}: expected {expected}, got {actual}")

    def test_part_a2_unconvertible_text(self) -> None:
        cases = [
            ('"a"&&VAR y="" RETURN y', "False"),
            ('AND("a",IF(TRUE(),""))', "False"),
            ('"a"&&LEFT("a",0)', "False"),
            ('IF("a"&&IF(TRUE(),""),1,2)', "2"),
            ('("a"&&VAR y=IF(TRUE(),"") RETURN y)&"z"', "FALSEz"),
            ('"a"&&(VAR y=IF(TRUE(),"","a") RETURN y)', "False"),
            ('ISBLANK("1"&&VAR y=MAX(Facts[Region]) RETURN y)', "False"),
            ('ISBLANK(""||VAR y=MAX(Facts[Region]) RETURN y)', "False"),
            ('ISBLANK("a"||VAR y=ERROR("x") RETURN y)', "False"),
            ('ISBLANK("a"&&VAR y=ERROR("x") RETURN y)', "False"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual("match", status(expected, actual), f"{expr}: expected {expected}, got {actual}")


class LogicTables4PartBTest(unittest.TestCase):
    """Part B1: Table variables; Part B2: Text predicate in FILTER; Part B3: Multi-valued table in FILTER."""

    def test_part_b1_table_variables(self) -> None:
        cases = [
            ('MAXX(VAR t=FILTER(Facts,FALSE()) RETURN t,Facts[Note])', "BLANK"),
            ('SUMX(VAR t=FILTER(Facts,FALSE()) RETURN t,Facts[Quantity])', "BLANK"),
            ('COUNTAX(VAR t=FILTER(Facts,FALSE()) RETURN t,Facts[Region])', "BLANK"),
            ('CONCATENATEX(VAR t=FILTER(Facts,FALSE()) RETURN t,FORMAT(Facts[Quantity],"0"),"|")', "BLANK"),
            ('COUNTROWS(ADDCOLUMNS(VAR t=FILTER(Facts,FALSE()) RETURN t,"q",1))', "BLANK"),
            ('COUNTROWS(FILTER(VAR t=FILTER(Facts,FALSE()) RETURN t,TRUE()))', "BLANK"),
            ('COUNTROWS(VAR t=FILTER(Facts,Facts[Quantity]>2) RETURN t)', "3"),
            ('SUMX(VAR t=FILTER(Facts,Facts[Quantity]>2) RETURN t,Facts[Quantity])', "12"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual("match", status(expected, actual), f"{expr}: expected {expected}, got {actual}")

    def test_part_b2_text_predicate_empty_filter(self) -> None:
        cases = [
            ('COUNTROWS(FILTER(FILTER(ALL(Facts),FALSE()),"a"))', "BLANK"),
            ('COUNTROWS(FILTER(TOPN(0,Facts),"a"))', "BLANK"),
            ('COUNTROWS(FILTER(ADDCOLUMNS(FILTER(Facts,FALSE()),"w",2),"a"))', "BLANK"),
            ('COUNTROWS(FILTER(EXCEPT(Facts,Facts),MAXX(Facts,Facts[Region])))', "BLANK"),
            ('COUNTROWS(FILTER(GENERATESERIES(1,0),"a"))', "BLANK"),
            ('COUNTROWS(FILTER(FILTER(Facts,FALSE()),IF(TRUE(),"a","b")))', "BLANK"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual("match", status(expected, actual), f"{expr}: expected {expected}, got {actual}")

    def test_part_b3_multivalued_table_empty_filter(self) -> None:
        cases = [
            ('COUNTROWS(FILTER(TOPN(0,Facts),VALUES(Facts[Region])))', "BLANK"),
            ('COUNTROWS(FILTER(EXCEPT(Facts,Facts),VALUES(Facts[Region])))', "BLANK"),
            ('COUNTROWS(FILTER(FILTER(Facts,FALSE()),DISTINCT(Facts[Region])))', "BLANK"),
            ('COUNTROWS(FILTER(GENERATESERIES(1,0),VALUES(Facts[Region])))', "BLANK"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual("match", status(expected, actual), f"{expr}: expected {expected}, got {actual}")

        # Over a table empty only because data did not match, multiple values remain an error
        error_cases = [
            'COUNTROWS(FILTER(FILTER(ALL(Facts),Facts[Quantity]>100),VALUES(Facts[Region])))',
            'COUNTROWS(FILTER(CALCULATETABLE(VALUES(Facts[Region]),Facts[Quantity]>100),VALUES(Facts[Region])))',
        ]
        for expr in error_cases:
            actual = dax.local(expr)
            self.assertTrue("single value" in actual.lower() or "LOCAL-REJECT" in actual or "ERR:" in actual,
                            f"{expr}: expected error, got {actual}")


class LogicTables4PartCTest(unittest.TestCase):
    """Part C1: Bodies checked too early / nested VAR declarations."""

    def test_part_c1_early_type_checks_and_nested_vars(self) -> None:
        cases = [
            ('COUNTX(Facts,IF(Facts[Quantity]>2,INT(DATE(2020,1,1)),1))', "6"),
            ('COUNTX(CALCULATETABLE(Facts,Facts[Region]="West"),MAX("a","b"))', "2"),
            ('MAXX(EXCEPT(Facts,Facts),VAR q=Facts[Quantity] RETURN q*2)', "BLANK"),
            ('COUNTAX(FILTER(Facts,FALSE()),ABS(DATEVALUE("2020-01-01")))', "BLANK"),
            ('MINX(Facts,ABS(TIME(6,0,0)))', "0.25"),
            ('COUNTX(Facts,SQRT(TIME(6,0,0)))', "6"),
            ('VAR z=VAR a=1 RETURN a RETURN z&&VAR y=BLANK() RETURN y<>"a"', "True"),
            ('VAR z=VAR a=1 RETURN a RETURN z||VAR y=-1 RETURN y*y', "True"),
            ('VAR z=VAR a=1 RETURN a RETURN z&&VAR y=TRUE() RETURN ISBLANK(y)', "False"),
            ('ISBLANK(2.5&&VAR y=ERROR("x") RETURN y)', "False"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual("match", status(expected, actual), f"{expr}: expected {expected}, got {actual}")


class LogicTables4PartDTest(unittest.TestCase):
    """Part D1: LINEST typing; Part D2: XNPV Currency arithmetic."""

    def test_part_d1_linest_typing(self) -> None:
        cases = [
            ('ISDOUBLE(MAXX(LINESTX(Facts,Facts[Quantity],Facts[Sales]),[StandardErrorIntercept]))', "True"),
            ('ISINT64(MAXX(LINESTX(Facts,Facts[Quantity],Facts[Sales]),[DegreesOfFreedom]))', "False"),
            ('ISDOUBLE(MAXX(LINESTX(Facts,Facts[Quantity],Facts[Sales]),[DegreesOfFreedom]))', "True"),
            ('ISDOUBLE(MAXX(LINESTX(Facts,Facts[Quantity],Facts[Sales]),[Slope1]))', "True"),
            ('ISINT64(MAXX(LINESTX(Facts,Facts[Quantity],Facts[Sales]),[Slope1]))', "False"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual("match", status(expected, actual), f"{expr}: expected {expected}, got {actual}")

    def test_part_d2_xnpv_currency_arithmetic(self) -> None:
        cases = [
            ('XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),CURRENCY([v])/3,1E15,0.1)', "0"),
            ('XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),CURRENCY([v])/3,[n],0)', "66.6667"),
            ('XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),CURRENCY([v])/3,DATE(9999,12,31)+[n],0)', "66.6667"),
            ('XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),CURRENCY([v])/3,[n]-3000000,-0.5)', "1733.3335"),
            ('XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n]),CURRENCY([v])/3,-[n],-0.5)', "-1833.3331"),
        ]
        for expr, expected in cases:
            actual = dax.local(expr)
            self.assertEqual("match", status(expected, actual), f"{expr}: expected {expected}, got {actual}")


class LogicTables4PartETest(unittest.TestCase):
    """Part E: Five wrong answers to fix."""

    def test_part_e_fixes(self) -> None:
        # 1. Added column has type even over empty table -> MAXX rejects Boolean
        actual1 = dax.local('MAXX(ADDCOLUMNS(EXCEPT(Facts,Facts),"q",ISBLANK(VALUES(Facts[Region]))),[q])')
        self.assertTrue("cannot work with values of type Boolean" in actual1, f"expected boolean rejection, got {actual1}")

        actual1b = dax.local('MAXX(ADDCOLUMNS(EXCEPT(Facts,Facts),"q",ISBLANK(VALUES(Facts[Note]))),[q])')
        self.assertTrue("cannot work with values of type Boolean" in actual1b, f"expected boolean rejection, got {actual1b}")

        # 2. Every branch is compiled -> column iterated rows lack is an error
        actual2 = dax.local('MAXX(SUMMARIZE(Facts,Facts[Region]),IF(COUNTROWS(Facts)>3,Facts[Region],Facts[Sales]))')
        self.assertTrue("single value for column 'Sales'" in actual2, f"expected single value error, got {actual2}")

        # 3. Negated typed blank date is 0
        actual3 = dax.local('-MIN(DATE(1899,12,30),BLANK())')
        self.assertEqual("match", status("0", actual3), f"expected 0, got {actual3}")

        # 4. Double precision
        actual4 = dax.local('LEN(GEOMEANX(VALUES(Facts[Region]),LASTNONBLANK(Facts[Sales],"a")))')
        self.assertEqual("match", status("16", actual4), f"expected 16, got {actual4}")


class AlternateTablesTest(unittest.TestCase):
    """Test consistency across alternate Facts tables in fixtures."""

    def test_alternate_tables_consistency(self) -> None:
        misc3 = json.loads(FIXTURES_MISC3_PATH.read_text())
        for key, dataset in misc3["datasets"].items():
            rows = [tuple(r) for r in dataset["rows"]]
            self.assertEqual("match", status("BLANK", _local_on(rows, '2.5&&IF(TRUE(),"")')))
            self.assertEqual("match", status("2", _local_on(rows, 'IF(1&&IF(TRUE(),"","a"),1,2)')))
            self.assertEqual("match", status("BLANK", _local_on(rows, 'MAXX(VAR t=FILTER(Facts,FALSE()) RETURN t,Facts[Note])')))

        variant2 = json.loads(FIXTURES_VARIANT2_PATH.read_text())
        for key, dataset in variant2["datasets"].items():
            rows = [tuple(r) for r in dataset["rows"]]
            self.assertEqual("match", status("BLANK", _local_on(rows, '2.5&&IF(TRUE(),"")')))
            self.assertEqual("match", status("False", _local_on(rows, 'ISBLANK("1"&&VAR y=MAX(Facts[Region]) RETURN y)')))
            self.assertEqual("match", status("BLANK", _local_on(rows, 'COUNTROWS(FILTER(TOPN(0,Facts),"a"))')))

        typed3 = json.loads(FIXTURES_TYPED3_PATH.read_text())
        for key, dataset in typed3["datasets"].items():
            rows = [tuple(r) for r in dataset["rows"]]
            self.assertEqual("match", status("BLANK", _local_on(rows, '2.5&&IF(TRUE(),"")')))
            self.assertEqual("match", status("True", _local_on(rows, 'VAR z=VAR a=1 RETURN a RETURN z&&VAR y=BLANK() RETURN y<>"a"')))
            self.assertEqual("match", status("0", _local_on(rows, '-MIN(DATE(1899,12,30),BLANK())')))


if __name__ == "__main__":
    unittest.main()
