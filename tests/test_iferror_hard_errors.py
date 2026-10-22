"""IFERROR / ISERROR do not catch an error thrown inside a row expression, a VAR or IN.

Every expected value below is a live Power BI Desktop 2.157.879.0 answer (see
tools/parity/dax_battery_iferror_hard_errors.json); an Infinity value is still caught.
"""
from __future__ import annotations

import unittest

from analytics_studio.measures import _HardError, evaluate_measures
from tools.dax_oracle_diff import HEADERS, LOCAL_ROWS, local


def refused(expression: str) -> bool:
    """True when the engine throws a hard error: IFERROR/ISERROR cannot catch it (not just any refusal)."""
    try:
        evaluate_measures(
            [{"name": "Probe__", "expression": expression}], LOCAL_ROWS, HEADERS, "Facts", measure_names=["Probe__"],
            table_context=[{
                "id": "facts", "name": "Facts", "headers": HEADERS, "rows": LOCAL_ROWS,
                "column_types": {"Sales": "decimal_number", "Quantity": "whole_number", "Region": "text", "Note": "text"},
            }],
            active_table_id="facts",
        )
    except _HardError:
        return True
    except Exception:  # any other outcome is not the behaviour under test
        return False
    return False


class IfErrorHardErrorTests(unittest.TestCase):
    def test_thrown_error_in_iterator_row_escapes_iferror(self) -> None:
        for expression in (
            'IFERROR(SUMX(Facts,VALUE(Facts[Region])),7)',
            'IFERROR(MAXX(Facts,SQRT(-Facts[Quantity])),7)',
            'IFERROR(COUNTX(Facts,VALUE(Facts[Region])),7)',
            'IFERROR(SUMX(Facts,IF(Facts[Quantity]>1,VALUE("a"),1)),7)',
            'ISERROR(SUMX(Facts,VALUE(Facts[Region])))',
            'IFERROR(COUNTROWS(FILTER(Facts,SQRT(-1)>1)),7)',
            'IFERROR(COUNTROWS(TOPN(1,Facts,VALUE(Facts[Region]))),7)',
        ):
            with self.subTest(expression):
                self.assertTrue(refused(expression), local(expression))

    def test_error_in_row_that_never_runs_is_fine(self) -> None:
        self.assertEqual(local('IFERROR(SUMX(Facts,IF(Facts[Quantity]>100,VALUE("a"),1)),7)'), "6")

    def test_inner_iferror_still_catches(self) -> None:
        self.assertEqual(local('IFERROR(SUMX(Facts,IFERROR(VALUE(Facts[Region]),0)),7)'), "0")

    def test_infinity_value_is_still_caught(self) -> None:
        for expression, expected in (
            ('IFERROR(SUMX(Facts,1/0),7)', "7"),
            ('IFERROR(SUMX(Facts,Facts[Quantity]/0),7)', "7"),
            ('IFERROR(SUMX(Facts,ROUNDDOWN(1/0,1)),7)', "7"),
            ('IFERROR(SUMX(Facts,TRUNC(1/0)),7)', "7"),
            ('IFERROR(SUMX(Facts,ABS(1/0)),7)', "7"),
            ('IFERROR(CONCATENATEX(Facts,SQRT(-Facts[Quantity])),7)', "7"),
        ):
            with self.subTest(expression):
                self.assertEqual(local(expression), expected)

    def test_function_that_rejects_infinity_inside_iterator(self) -> None:
        for expression in (
            'IFERROR(SUMX(Facts,INT(1/0)),7)',
            'IFERROR(SUMX(Facts,SQRT(1/0)),7)',
            'IFERROR(SUMX(Facts,FLOOR(1/0,1)),7)',
            'IFERROR(SUMX(Facts,ROUND(1/0,0)),7)',
            'IFERROR(SUMX(Facts,ROUNDUP(1/0,1)),7)',
        ):
            with self.subTest(expression):
                self.assertTrue(refused(expression), local(expression))
        self.assertEqual(local('IFERROR(CEILING(1/0,1),7)'), "7")  # outside an iterator it is caught

    def test_var_error_escapes_when_used(self) -> None:
        for expression in (
            'VAR x=VALUE("a") RETURN IFERROR(x,7)',
            'VAR x=SQRT(-1) RETURN IFERROR(x,7)',
            'VAR x=VALUE("a") RETURN ISERROR(x)',
            'IFERROR(VAR x=VALUE("a") RETURN x+1,7)',
        ):
            with self.subTest(expression):
                self.assertTrue(refused(expression), local(expression))
        self.assertEqual(local('VAR x=VALUE("a") RETURN 5'), "5")
        self.assertEqual(local('VAR x=VALUE("a") RETURN IF(TRUE(),5,x)'), "5")
        self.assertEqual(local('VAR x=1/0 RETURN IFERROR(x,7)'), "7")

    def test_calculate_filter_predicate_error_escapes(self) -> None:
        self.assertTrue(refused('IFERROR(CALCULATE(SUM(Facts[Sales]),Facts[Quantity]>VALUE("a")),7)'))
        self.assertEqual(local('IFERROR(CALCULATE(VALUE("a")),7)'), "7")

    def test_table_function_arguments_escape(self) -> None:
        for expression in (
            'IFERROR(COUNTROWS(ROW("x",VALUE("a"))),7)',
            'IFERROR(COUNTROWS(GENERATESERIES(1,VALUE("a"))),7)',
            'IFERROR(COUNTROWS(TOPN(VALUE("a"),Facts,Facts[Sales])),7)',
            'IFERROR(CONTAINS(Facts,Facts[Region],VALUE("a")),7)',
            'IFERROR(LOOKUPVALUE(Facts[Sales],Facts[Region],VALUE("a")),7)',
            'IFERROR(MAXX(ADDCOLUMNS(Facts,"x",VALUE(Facts[Region])),[x]),7)',
            'IFERROR(CALCULATE(SUM(Facts[Sales]),VALUE("a")<Facts[Quantity]),7)',
            'IFERROR(SUMX(Facts,TRUNC(1/0)+VALUE("a")),7)',
        ):
            with self.subTest(expression):
                self.assertTrue(refused(expression), local(expression))

    def test_unread_columns_and_blank_logarithms(self) -> None:
        self.assertEqual(local('COUNTROWS(ADDCOLUMNS(Facts,"x",SUMX(Facts,VALUE("a"))))'), "6")
        self.assertEqual(local('IFERROR(SUMX(Facts,IF(Facts[Quantity]=4,LN(BLANK()),1)),7)'), "7")
        self.assertEqual(local('IFERROR(SUMX(Facts,LOG10(BLANK())),7)'), "7")

    def test_in_and_containsrow_errors_escape(self) -> None:
        for expression in (
            'IFERROR(VALUE("a") IN {1,2},7)',
            'IFERROR(1 IN {VALUE("a")},7)',
            'IFERROR(CONTAINSROW({1,2},VALUE("a")),7)',
        ):
            with self.subTest(expression):
                self.assertTrue(refused(expression), local(expression))

    def test_top_level_scalar_errors_are_still_caught(self) -> None:
        for expression in ('IFERROR(VALUE("a"),7)', 'IFERROR(SQRT(-1),7)', 'IFERROR(VALUE("a")>1,7)',
                           'IFERROR(CALCULATE(VALUE("a")),7)', 'IFERROR(MAX(VALUE("a"),1),7)'):
            with self.subTest(expression):
                self.assertEqual(local(expression), "7")


if __name__ == "__main__":
    unittest.main()
