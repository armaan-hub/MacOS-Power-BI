"""Iteration 102 review (Task 14 logic-tables-4): the rules Power BI showed on fresh probes, not on the saved items.

Power BI answers: tests/fixtures_logic4_review_alt.json (another Facts table) and dax_battery_logic4_extra (the standard table).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

ROOT = Path(__file__).resolve().parents[1]


def _on(rows: list[tuple[str, ...]], expression: str) -> str:
    saved = (dax.ROWS, dax.LOCAL_ROWS)
    dax.ROWS = rows
    dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, row)} for row in rows]
    try:
        return dax.local(expression)
    finally:
        dax.ROWS, dax.LOCAL_ROWS = saved


class LogicalBlankTest(unittest.TestCase):
    """&& / || / AND / OR with an undecided left and an empty text on the right: a BLANK typed True/False, not a value of its own."""

    def test_functions_read_a_blank(self) -> None:
        for expression, answer in (
            ('LEN(2.5&&"")', "BLANK"), ('(2.5&&"")*2', "BLANK"), ('-(2.5&&"")', "BLANK"), ('UPPER(2.5&&"")', "BLANK"), ('CONVERT(2.5&&"",DOUBLE)', "BLANK"),
            ('(2.5&&"")=BLANK()', "True"), ('SWITCH(2.5&&"",BLANK(),1,2)', "1"), ('ISBLANK(CALCULATE(2.5&&""))', "True"), ('(2.5&&"")&"z"', "z"),
        ):
            self.assertEqual(answer, dax.local(expression), expression)

    def test_isblank_coalesce_and_strict_equality_go_by_the_type(self) -> None:
        for expression, answer in (
            ('ISBLANK(2.5&&"")', "False"), ('VAR x=2.5&&"" RETURN ISBLANK(x)', "False"), ('COALESCE(2.5&&"",5)', "BLANK"), ('(2.5&&"")==BLANK()', "True"), ('(2.5&&"")==FALSE()', "False"),
            ('TRUE()&&(2.5&&"")', "BLANK"),
        ):
            self.assertEqual(answer, dax.local(expression), expression)

    def test_a_comparison_with_a_number_is_an_error_not_a_crash(self) -> None:
        self.assertTrue(dax.local('(2.5&&"")>0').startswith("LOCAL-REJECT"))

    def test_in_a_table_column_it_stays_true_false(self) -> None:
        self.assertEqual("1", dax.local('COUNTAX({2.5&&""},[Value])'))  # live Power BI (Task 15 review): the constructor holds False
        self.assertEqual("True", dax.local('ISLOGICAL(2.5&&"")'))  # live Power BI (Task 16 review): the empty text is folded when the query compiles
        self.assertTrue(dax.local('MAXX(ADDCOLUMNS(Facts,"q",2.5&&""),[q])').startswith("LOCAL-REJECT"))

    def test_a_row_that_failed_is_not_mistaken_for_it(self) -> None:
        self.assertEqual("6", dax.local('COUNTROWS(ADDCOLUMNS(Facts,"x",Facts[Quantity]>10&&SQRT(-1)>0))'))

    def test_isblank_of_an_operator_keeps_compile_errors(self) -> None:
        for expression in ("ISBLANK(TRUE()&&[nope])", "ISBLANK(TRUE()&&Facts)"):
            self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"), expression)

    def test_error_of_a_var_block_beside_a_failed_left_is_not_caught(self) -> None:
        self.assertTrue(dax.local('IFERROR("a"&&VAR y=ERROR("x") RETURN y,7)').startswith("LOCAL-REJECT"))
        self.assertEqual("True", dax.local('IFERROR(("a")||(VAR y=ERROR("x") RETURN 1),7)'))


class FilterOverNoRowsTest(unittest.TestCase):
    """A predicate that reads no row is evaluated before the rows only when a scan of a stored table really ran."""

    def test_no_scan_ran(self) -> None:
        for table in ('FILTER(Facts,FALSE())', 'FILTER(Facts,1=0)', 'TOPN(0,Facts)', 'EXCEPT(Facts,Facts)', 'GENERATESERIES(1,0)', 'FILTER(Facts,Facts[Region]="Elsewhere")', 'FILTER(Facts,Facts[Quantity]=100)',
                      'FILTER(Facts,Facts[Region] IN {"a","b"})', 'FILTER(Facts,Facts[Region]="West"&&Facts[Region]="East")', 'CALCULATETABLE(Facts,Facts[Region]="Nowhere")', 'ADDCOLUMNS(FILTER(Facts,Facts[Quantity]>100),"w",2)',
                      'VAR t=FILTER(Facts,Facts[Quantity]>100) RETURN t', 'TOPN(3,FILTER(Facts,Facts[Quantity]>100))'):
            for predicate in ('"a"', 'VALUES(Facts[Region])', 'ERROR("x")'):
                expression = f"COUNTROWS(FILTER({table},{predicate}))"
                self.assertEqual("BLANK", dax.local(expression), expression)

    def test_a_scan_ran(self) -> None:
        for table in ('FILTER(Facts,Facts[Quantity]>100)', 'FILTER(ALL(Facts),Facts[Quantity]>100)', 'FILTER(Facts,Facts[Quantity]=1.5)', 'FILTER(Facts,Facts[Region]="West"&&Facts[Quantity]>100)', 'CALCULATETABLE(Facts,Facts[Quantity]>100)',
                      'SUMMARIZE(FILTER(Facts,Facts[Quantity]>100),Facts[Region])', 'KEEPFILTERS(FILTER(Facts,Facts[Quantity]>100))', 'DISTINCT(FILTER(Facts,Facts[Quantity]>100))'):
            for predicate in ('"a"', 'VALUES(Facts[Region])', 'ERROR("x")'):
                expression = f"COUNTROWS(FILTER({table},{predicate}))"
                self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"), expression)

    def test_what_a_column_holds_decides_not_the_text_of_the_filter(self) -> None:
        rows = [("1", "4", "Nowhere", "x"), ("2", "5", "East", "y")]
        self.assertEqual("BLANK", dax.local('COUNTROWS(FILTER(FILTER(Facts,Facts[Region]="Nowhere"),"a"))'))
        self.assertEqual("BLANK", _on(rows, 'COUNTROWS(FILTER(FILTER(Facts,Facts[Region]="West"),"a"))'))
        self.assertTrue(_on(rows, 'COUNTROWS(FILTER(FILTER(Facts,Facts[Region]="Nowhere"&&Facts[Quantity]>9),"a"))').startswith("LOCAL-REJECT"))

    def test_topn(self) -> None:
        for expression, answer in (("COUNTROWS(TOPN(-1,Facts))", "6"), ("COUNTROWS(TOPN(-5,Facts))", "BLANK"), ("COUNTROWS(TOPN(-1,Facts,Facts[Quantity]))", "BLANK"), ("COUNTROWS(TOPN(0.5,Facts))", "1")):
            self.assertEqual(answer, dax.local(expression), expression)


class CurrencyTest(unittest.TestCase):
    def test_conversion_is_a_double_multiply(self) -> None:
        for number, answer in (("10.00005", "10.0001"), ("20.12345", "20.1234"), ("0.00015", "0.0001"), ("0.00025", "0.0003"), ("-7.77775", "-7.7778")):
            self.assertEqual("match", status(answer, dax.local(f"CURRENCY({number})")), number)

    def test_each_step_keeps_its_type(self) -> None:
        for expression, answer in (
            ("CURRENCY(10.00005)/3", "3.3334"), ("CURRENCY(0.00015)*2.5", "0.0003"), ("CURRENCY(0.00015)*1.5/3", "0.0001"), ("DIVIDE(CURRENCY(10.00005),3)", "3.3334"),
            ("CURRENCY(1)+0.00005", "1.00005"), ("CURRENCY(10.00005)/CURRENCY(3)", "3.33336666666667"), ("3/CURRENCY(0.00025)", "10000"),
        ):
            self.assertEqual("match", status(answer, dax.local(expression)), expression)

    def test_xnpv_takes_the_type_of_its_values(self) -> None:
        table = 'ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{{-1000,0},{300,365},{400,730},{500,1095}}),"d",DATE(2020,1,1)+[n])'
        self.assertEqual("match", status("-21.0366400826449", dax.local(f"XNPV({table},CURRENCY([v])+0.00005,[d],0.1)")))
        self.assertEqual("match", status("True", dax.local(f"ISCURRENCY(XNPV({table},CURRENCY([v])/3,[d],0.1))")))

    def test_a_blank_currency_in_xnpv_stays_refused(self) -> None:
        rows = [("", "1", "East", ""), ("5", "2", "West", "")]
        self.assertTrue(_on(rows, 'XNPV(ADDCOLUMNS(Facts,"d",DATE(2020,1,1)+Facts[Quantity]),CURRENCY(Facts[Sales])/3,[d],0.1)').startswith("LOCAL-REJECT"))

    def test_text_beside_a_currency_is_an_error(self) -> None:
        self.assertTrue(dax.local('MIN(CURRENCY(0),"a")').startswith("LOCAL-REJECT"))


class TypingTest(unittest.TestCase):
    def test_linest_columns_are_double_by_their_table_not_their_name(self) -> None:
        for expression, answer in (
            ("ISINT64(MAXX(LINEST(Facts[Quantity],Facts[Sales]),1))", "True"), ("ISDOUBLE(MAXX(LINEST(Facts[Quantity],Facts[Sales]),[DegreesOfFreedom]))", "True"),
            ("ISINT64(MAXX(LINEST(Facts[Quantity],Facts[Sales]),INT([DegreesOfFreedom])))", "True"),
        ):
            self.assertEqual(answer, dax.local(expression), expression)

    def test_a_column_named_like_a_linest_column_is_not_a_double(self) -> None:
        self.assertNotEqual("False", dax.local('ISINT64(MAXX(ADDCOLUMNS(Facts,"Slope1",1),[Slope1]))'))  # Power BI: True; its type is not known here, so it is refused

    def test_min_max_of_two_equal_values(self) -> None:
        for expression, answer in (('ISBLANK(MIN("",BLANK()))', "True"), ('ISBLANK(MAX("",BLANK()))', "False"), ('LEN(MIN("",""))', "0"), ("-MIN(DATE(1899,12,30),BLANK())", "0")):
            self.assertEqual(answer, dax.local(expression), expression)

    def test_second_argument_of_min_types_the_body(self) -> None:
        self.assertTrue(dax.local('SUMX(Facts,MIN(BLANK(),"a"))').startswith("LOCAL-REJECT"))

    def test_nested_var_blocks(self) -> None:
        for expression, answer in (("VAR a=VAR b=1 RETURN b+1 RETURN a*2", "4"), ("VAR a=1 VAR b=VAR c=a RETURN c+1 RETURN b", "2"), ("SUMX(Facts,VAR a=VAR b=Facts[Quantity] RETURN b*2 RETURN a+1)", "36")):
            self.assertEqual(answer, dax.local(expression), expression)

    def test_iseven_rounds_first(self) -> None:
        for expression, answer in (("ISEVEN(TIME(6,0,0))", "True"), ("ISEVEN(2.5)", "False"), ("ISEVEN(1.5)", "True"), ("ISODD(2.5)", "True")):
            self.assertEqual(answer, dax.local(expression), expression)

    def test_a_var_that_reads_no_row_fails_over_no_rows(self) -> None:
        self.assertTrue(dax.local('SUMX(FILTER(Facts,FALSE()),VAR q=ERROR("x") RETURN q)').startswith("LOCAL-REJECT"))
        self.assertEqual("BLANK", dax.local('SUMX(FILTER(Facts,FALSE()),VAR q=ERROR("x") RETURN 1)'))


class FreshProbesTest(unittest.TestCase):
    def test_fresh_probes_on_other_tables_match_or_are_refused(self) -> None:
        fixture = json.loads((ROOT / "tests" / "fixtures_logic4_review_alt.json").read_text())
        for key, dataset in fixture["datasets"].items():
            rows = [tuple(row) for row in dataset["rows"]]
            wrong = [(item["expr"], item["powerbi"][:60]) for item in dataset["items"] if status(item["powerbi"], _on(rows, item["expr"])) not in {"match", "gap-reject"}]
            self.assertEqual([], wrong[:10], key)


if __name__ == "__main__":
    unittest.main()
