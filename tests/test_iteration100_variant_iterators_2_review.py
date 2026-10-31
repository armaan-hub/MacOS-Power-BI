"""Claude's review of Task 12: rules measured on Power BI that the saved items did not show.

Power BI answers: tests/fixtures_variant2_review_alt.json (three other Facts tables) and dax_battery_variant2_extra (the standard one).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from analytics_studio.measures import MeasureError, evaluate_measures
from tools import dax_oracle_diff as dax
from tools.parity_check import status
from tests.test_iteration100_variant_iterators_2 import _local_on

ROOT = Path(__file__).resolve().parents[1]
R = "Facts[Region]"


def _refused(case: unittest.TestCase, expressions: list[str]) -> None:
    for expression in expressions:
        case.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"), expression)


class OtherTablesTest(unittest.TestCase):
    def test_power_bi_answers_on_three_other_facts_tables(self) -> None:
        fixture = json.loads((ROOT / "tests" / "fixtures_variant2_review_alt.json").read_text())
        for key, dataset in fixture["datasets"].items():
            rows = [tuple(row) for row in dataset["rows"]]
            bad = [
                (item["expr"], item["powerbi"])
                for item in dataset["items"]
                if status(item["powerbi"], _local_on(rows, item["expr"])) == "DIFF"
            ]
            self.assertEqual([], bad, key)
            self.assertGreaterEqual(len(dataset["items"]), 1000)


class ConstantIfTest(unittest.TestCase):
    def test_if_reduces_to_a_text_column_beside_any_branch(self) -> None:
        for other in ("7", "TRUE()", "Facts[Quantity]*2", "DATE(2020,1,1)+Facts[Quantity]", "1/0", 'VALUE("x")'):
            self.assertEqual("West", dax.local(f"MAXX(Facts,IF(TRUE(),{R},{other}))"), other)
            self.assertEqual("East", dax.local(f"MINX(Facts,IF(FALSE(),{other},{R}))"), other)
            self.assertEqual("6", dax.local(f"COUNTX(Facts,IF(TRUE(),{R},{other}))"), other)

    def test_a_condition_that_reads_no_row_decides(self) -> None:
        for condition in ("1=1", "NOT(FALSE())", "COUNTROWS(Facts)>0", "MAX(Facts[Quantity])>1", '"TRUE"', "DATE(2020,1,1)", "1/0", "0/0"):
            self.assertEqual("West", dax.local(f"MAXX(Facts,IF({condition},{R},1))"), condition)
        for condition in ("1=2", '""', "BLANK()", "0"):
            self.assertEqual("West", dax.local(f"MAXX(Facts,IF({condition},1,{R}))"), condition)

    def test_if_eager_reduces_only_beside_a_literal_like_branch(self) -> None:
        for other in ("2.5", "-7", "+7", "TRUE()", "NOT(TRUE())", "1=1", "TRUE()&&FALSE()", "DATE(2020,1,1)", "TIME(1,0,0)", "CURRENCY(3)", "Facts[Quantity]", "BLANK()"):
            self.assertEqual("West", dax.local(f"MAXX(Facts,IF.EAGER(TRUE(),{R},{other}))"), other)
        for other in ("1+1", "-Facts[Quantity]", "NOT(0)", "PI()", "ROUND(2.5,0)", 'VALUE("1")', "Facts[Quantity]>2", "DATE(2020,1,1)+1"):
            self.assertEqual("BLANK", dax.local(f"MAXX(Facts,IF.EAGER(TRUE(),{R},{other}))"), other)

    def test_text_literals_and_computed_text_stay_a_variant(self) -> None:
        self.assertEqual("BLANK", dax.local('MAXX(Facts,IF(TRUE(),"a",1))'))
        self.assertEqual("BLANK", dax.local(f"MAXX(Facts,IF(TRUE(),UPPER({R}),1))"))
        self.assertEqual("BLANK", dax.local(f"MAXX(Facts,SWITCH(TRUE(),TRUE(),{R},1))"))
        self.assertEqual("BLANK", dax.local(f"MAXX(Facts,VAR c=1 RETURN IF(TRUE(),{R},c))"))
        _refused(self, [f'MAXX(Facts,EVALUATEANDLOG(IF(TRUE(),{R},1),"a"))'])  # BLANK in Power BI: not reduced either, refused here

    def test_the_scan_decides_and_differs_by_function(self) -> None:
        body = f"IF(TRUE(),{R},1)"
        for table in ("ALL(Facts)", "VALUES(Facts[Region])", "DISTINCT(Facts)", f"SUMMARIZE(Facts,{R},Facts[Note])", "FILTER(Facts,TRUE())", "CALCULATETABLE(Facts)"):
            self.assertEqual("West", dax.local(f"MAXX({table},{body})"), table)
        for table in ("FILTER(Facts,Facts[Quantity]>2)", 'CALCULATETABLE(Facts,Facts[Region]="West")', "ADDCOLUMNS(Facts,\"w\",1)", "UNION(Facts,Facts)"):
            self.assertEqual("BLANK", dax.local(f"MAXX({table},{body})"), table)
        self.assertEqual("3", dax.local(f"COUNTX(FILTER(Facts,Facts[Quantity]>2),{body})"))
        self.assertEqual("BLANK", dax.local(f"COUNTX(DISTINCT(Facts),{body})"))
        self.assertEqual("BLANK", dax.local(f"SUMX(Facts,{body})"))

    def test_an_outer_filter_or_row_stops_the_reduction_unless_all_clears_it(self) -> None:
        body = f"IF(TRUE(),{R},1)"
        self.assertEqual("BLANK", dax.local(f"CALCULATE(MAXX(Facts,{body}),Facts[Quantity]>2)"))
        self.assertEqual("BLANK", dax.local(f"CALCULATE(MAXX(SUMMARIZE(Facts,{R}),{body}),Facts[Quantity]>2)"))
        self.assertEqual("West", dax.local(f"CALCULATE(MAXX(ALL(Facts),{body}),Facts[Quantity]>2)"))
        self.assertEqual("BLANK", dax.local(f"MAXX(VALUES(Facts[Note]),MAXX(Facts,{body}))"))

    def test_the_reduced_body_is_typed_as_text(self) -> None:
        self.assertEqual("Westz", dax.local(f'MAXX(Facts,IF(TRUE(),{R},1))&"z"'))
        self.assertEqual("4", dax.local(f"LEN(MINX(Facts,IF(FALSE(),2,Facts[Note])))"))
        _refused(self, [f"MAXX(Facts,IF(TRUE(),{R},1))+1", f"VALUE(MAXX(Facts,IF(TRUE(),{R},1)))"])

    def test_a_scan_that_was_not_measured_is_refused(self) -> None:
        _refused(self, [f"MAXX(FILTER(Facts,1=1),IF(TRUE(),{R},1))"])


class InfinityAndNanInVariantsTest(unittest.TestCase):
    def test_infinity_counts_where_a_number_body_would_be_blank(self) -> None:
        self.assertEqual("BLANK", dax.local("MAXX(Facts,-1/0)"))
        self.assertEqual("-Infinity", dax.local('MAXX(Facts,IF(TRUE(),-1/0,"a"))'))
        self.assertEqual("Infinity", dax.local('MINX(Facts,IF(Facts[Quantity]>2,"a",1/0))'))

    def test_nothing_but_nan_is_nan_and_reads_as_power_bi_prints_it(self) -> None:
        self.assertEqual("BLANK", dax.local("MAXX(Facts,0/0)"))
        body = 'MAXX(Facts,IF(TRUE(),0/0,"a"))'
        self.assertEqual("NaN", dax.local(body))
        self.assertEqual("False", dax.local(f"ISBLANK({body})"))
        self.assertEqual("9", dax.local(f"LEN({body})"))
        self.assertEqual("-nan(ind)", dax.local(f'FORMAT({body},"0")'))

    def test_nan_beside_other_numbers_depends_on_the_walk_and_is_refused(self) -> None:
        # Power BI: Infinity with a text column in the other branch (the walk follows it), NaN with a literal
        _refused(self, [f"MAXX(Facts,IF(Facts[Quantity]>2,{R},Facts[Quantity]/0))", 'MAXX(Facts,IF(Facts[Quantity]>2,"a",Facts[Quantity]/0))'])

    def test_value_cannot_read_infinity_or_nan(self) -> None:
        _refused(self, ["VALUE(1/0)", 'VALUE(MAXX(Facts,IF(TRUE(),0/0,"a")))'])


class VarInABranchTest(unittest.TestCase):
    def test_a_variable_keeps_its_type_in_a_variant_body(self) -> None:
        self.assertEqual("3", dax.local('SUMX(Facts,VAR v=1 RETURN IF(Facts[Quantity]>2,v,"5"))'))
        self.assertEqual("01/06/2020 00:00:00", dax.local('MAXX(Facts,VAR v=DATE(2020,1,1)+Facts[Quantity] RETURN IF(Facts[Quantity]>2,v,"5"))'))
        self.assertTrue(dax.local("MINX(Facts,VAR v=TRUE() RETURN IF(Facts[Quantity]>2,v,CURRENCY(3)))").startswith("3"))

    def test_a_mixed_body_never_crashes_the_text_ordering(self) -> None:
        self.assertNotIn("LOCAL-CRASH", dax.local(f"MINX(Facts,VAR v={R} RETURN IF(Facts[Quantity]>2,v,Facts[Quantity]))"))


class LogicalOperatorsTest(unittest.TestCase):
    def test_an_empty_text_on_the_left_is_false(self) -> None:
        self.assertEqual("False", dax.local('""&&TRUE()'))
        self.assertEqual("True", dax.local('""||TRUE()'))
        self.assertEqual("False", dax.local('""&&""'))

    def test_an_empty_text_on_the_right_of_an_undecided_left_is_refused(self) -> None:
        # Power BI displays BLANK, yet ISBLANK of it is False
        _refused(self, ['TRUE()&&""', 'FALSE()||""', 'FALSE()||VAR y="" RETURN y', 'AND(TRUE(),"")', 'OR(BLANK(),"")', '""||""'])
        self.assertEqual("True", dax.local('TRUE()||""'))
        self.assertEqual("False", dax.local('FALSE()&&""'))


class TypingTest(unittest.TestCase):
    def test_first_and_last_non_blank_are_typed_at_compile_time(self) -> None:
        _refused(self, [
            "SUMX(TOPN(0,Facts),FIRSTNONBLANKVALUE(Facts[Region],MAX(Facts[Note])))",
            "MEDIANX(FILTER(Facts,FALSE()),FIRSTNONBLANK(Facts[Region],1))",
            "PRODUCTX(Facts,LASTNONBLANK(Facts[Note],1))",
        ])
        self.assertEqual("15", dax.local("SUMX(Facts,FIRSTNONBLANK(Facts[Quantity],1))"))

    def test_currency_averages_are_refused(self) -> None:
        _refused(self, ["AVERAGEX(Facts,SWITCH(Facts[Quantity],1,CURRENCY(3),Facts[Quantity]*2))"])

    def test_a_date_past_the_display_range_is_refused_by_the_evaluator(self) -> None:
        # raised while a card formatted the value, it broke every later measure in the real app
        for expression in ("TIME(6,0,0)-1", "MAXX(Facts,TIME(6,0,0)-1)", "DATE(2020,1,1)+3000000"):
            with self.assertRaises(MeasureError, msg=expression):
                evaluate_measures(
                    [{"name": "Probe__", "expression": expression}], dax.LOCAL_ROWS, dax.HEADERS, "Facts", measure_names=["Probe__"],
                    table_context=[{
                        "id": "facts", "name": "Facts", "headers": dax.HEADERS, "rows": dax.LOCAL_ROWS,
                        "column_types": {"Sales": "decimal_number", "Quantity": "whole_number", "Region": "text", "Note": "text"},
                    }],
                    active_table_id="facts",
                )

    def test_concatenatex_walks_in_an_unmodelled_order_are_refused(self) -> None:
        _refused(self, [
            f'CONCATENATEX(Facts,MAX({R},"a"))',
            "CONCATENATEX(Facts,LASTNONBLANK(Facts[Note],1))",
            "CONCATENATEX(Facts,IF(1=1,Facts[Quantity],Facts[Sales]))",
            "CONCATENATEX(Facts,IF(TRUE(),DATE(2020,1,1),Facts[Sales]))",
        ])


if __name__ == "__main__":
    unittest.main()
