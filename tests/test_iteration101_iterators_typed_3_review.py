"""Claude's review of Task 13: rules measured on Power BI that the saved items did not show.

Power BI answers: tests/fixtures_typed3_review_alt.json (three other Facts tables) and dax_battery_typed3_extra (the standard table).
The build matched its 1,180 items; about 128,000 fresh answers then found 556 wrong ones on the standard table alone.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

ROOT = Path(__file__).resolve().parents[1]
Q = "Facts[Quantity]"
R = "Facts[Region]"


def _local_on(rows: list[tuple[str, ...]], expression: str) -> str:
    saved = (dax.ROWS, dax.LOCAL_ROWS)
    dax.ROWS = rows
    dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, row)} for row in rows]
    try:
        return dax.local(expression)
    finally:
        dax.ROWS, dax.LOCAL_ROWS = saved


def _refused(case: unittest.TestCase, expressions: list[str]) -> None:
    for expression in expressions:
        case.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"), expression)


class OtherTablesTest(unittest.TestCase):
    def test_power_bi_answers_on_three_other_facts_tables(self) -> None:
        fixture = json.loads((ROOT / "tests" / "fixtures_typed3_review_alt.json").read_text())
        for key, dataset in fixture["datasets"].items():
            rows = [tuple(row) for row in dataset["rows"]]
            bad = [
                (item["expr"], item["powerbi"])
                for item in dataset["items"]
                if status(item["powerbi"], _local_on(rows, item["expr"])) == "DIFF"
            ]
            self.assertEqual([], bad[:5], key)
            self.assertGreaterEqual(len(dataset["items"]), 1900)


class DatesInIteratorsTest(unittest.TestCase):
    """Found by the gate (test_iteration84_critic) after the first review pass, then asked of Power BI as a 4,300-expression grid on two tables."""

    def test_a_sum_of_dates_is_a_date_and_a_number_beside_it_makes_a_number(self) -> None:
        self.assertEqual("01/11/2620 00:00:00", dax.local("SUMX(Facts,DATE(2020,1,1))"))
        self.assertEqual("262986", dax.local("IF(FALSE(),1,SUMX(Facts,DATE(2020,1,1)))"))
        self.assertEqual("262986", dax.local("IF(COUNTROWS(Facts)>3,SUMX(Facts,DATE(2020,1,1)),SUM(Facts[Quantity]))"))

    def test_an_empty_sum_of_dates_is_day_zero_in_arithmetic(self) -> None:
        self.assertEqual("12/31/1899 00:00:00", dax.local("(SUMX(FILTER(Facts,FALSE()),DATE(2020,1,1)))+1"))
        self.assertEqual("12/31/1899 00:00:00", dax.local("(MIN(SUMX(FILTER(Facts,FALSE()),DATE(2020,1,1)),DATE(2021,1,1)))+1"))

    def test_an_average_or_variance_of_dates_is_a_number(self) -> None:
        self.assertEqual("44197", dax.local("IF(TRUE(),DATE(2021,1,1),AVERAGEX(Facts,TIME(6,0,0)))"))
        self.assertEqual("44197", dax.local(f"IF(TRUE(),DATE(2021,1,1),VARX.P(Facts,DATE(2020,1,1)+{Q}))"))

    def test_a_date_body_fails_to_compile_even_in_a_branch_not_taken(self) -> None:
        for function in ("PRODUCTX(Facts,DATE(2000,1,1))", "MEDIANX(Facts,DATE(2020,1,1))", "GEOMEANX(Facts,DATE(2020,1,1))", "PERCENTILEX.INC(Facts,DATE(2020,1,1),0.5)"):
            _refused(self, [f"IF(TRUE(),1,{function})", f"IF(FALSE(),{function},1)", f"SUMX(Facts,IF(FALSE(),{function}))"])


class DateBesideNumberTest(unittest.TestCase):
    def test_any_number_makes_a_number_whichever_branch_runs(self) -> None:
        for expression in (
            "IF(TRUE(),DATE(2020,1,1),COUNTROWS(Facts))",
            "SWITCH(1,1,DATE(2020,1,1),2,COUNTROWS(Facts))",
            "IFERROR(DATE(2020,1,1),INT(1.5))",
            "COALESCE(DATE(2020,1,1),CURRENCY(2))",
            "MAX(DATE(2020,1,1),COUNTROWS(Facts))",
            "MAX(BLANK(),DATE(2020,1,1))",
        ):
            self.assertEqual("43831", dax.local(expression), expression)

    def test_beside_text_it_is_a_variant_and_stays_a_date(self) -> None:
        self.assertEqual("01/01/2020 00:00:00", dax.local('IF(TRUE(),DATE(2020,1,1),IF(TRUE(),1,"a"))'))

    def test_two_dates_stay_a_date(self) -> None:
        self.assertEqual("01/01/2021 00:00:00", dax.local("MAX(DATE(2020,1,1),DATE(2021,1,1))"))

    def test_a_date_typed_blank_counts_as_day_zero(self) -> None:
        self.assertEqual("12/31/1899 00:00:00", dax.local("SWITCH(1,1,BLANK(),2,DATE(2020,1,1))+1"))


class ScanTest(unittest.TestCase):
    """A stored scan skips NaN, a row set the formula engine builds does not."""

    STORED = ("Facts", "ALL(Facts)", "VALUES(Facts)", "FILTER(Facts,TRUE())", "CALCULATETABLE(Facts)")
    ROW_SETS = ("DISTINCT(Facts)", 'ADDCOLUMNS(Facts,"z",1)', "TOPN(100,Facts,Facts[Quantity])", "UNION(Facts,FILTER(Facts,FALSE()))")

    def test_nan_in_count_and_average(self) -> None:
        for table in self.STORED:
            self.assertEqual("0", dax.local(f"COUNTX({table},0/0)"), table)
            self.assertEqual("0", dax.local(f"AVERAGEX({table},0/0)"), table)
        for table in self.ROW_SETS:
            self.assertEqual("6", dax.local(f"COUNTX({table},0/0)"), table)
            self.assertEqual("NaN", dax.local(f"AVERAGEX({table},0/0)"), table)

    def test_a_variant_counts_its_nan_unless_a_plain_if_folds_it(self) -> None:
        self.assertEqual("0", dax.local('COUNTX(Facts,IF(TRUE(),0/0,"a"))'))
        self.assertEqual("6", dax.local('COUNTX(Facts,IF.EAGER(TRUE(),0/0,"a"))'))
        self.assertEqual("6", dax.local('COUNTX(Facts,VAR x=0/0 RETURN IF(TRUE(),x,"a"))'))

    def test_maxx_and_minx_over_a_row_set_keep_nan_and_infinity(self) -> None:
        self.assertEqual("BLANK", dax.local("MINX(Facts,1/0)"))
        self.assertEqual("Infinity", dax.local("MINX(TOPN(2,Facts,Facts[Quantity]),1/0)"))
        self.assertEqual("BLANK", dax.local("MAXX(Facts,0/0)"))
        self.assertEqual("NaN", dax.local('MAXX(ADDCOLUMNS(Facts,"z",1),0/0)'))
        _refused(self, [f'MAXX(ADDCOLUMNS(Facts,"z",1),{Q}/0)'])  # NaN beside Infinity depends on the walk

    def test_countx_counts_a_true_false_only_when_the_plan_folds_it(self) -> None:
        for body in ("IF(TRUE(),TRUE(),7)", "IF.EAGER(TRUE(),TRUE(),7)", "COALESCE(TRUE(),7)", "IFERROR(TRUE(),7)", f"IFERROR(IF({Q}>2,FALSE()),7)"):
            self.assertEqual("6", dax.local(f"COUNTX(Facts,{body})"), body)
            self.assertEqual("BLANK", dax.local(f"COUNTX(DISTINCT(Facts),{body})"), body)
        for body in ("IF.EAGER(TRUE(),TRUE(),1+1)", "SWITCH(TRUE(),TRUE(),TRUE(),7)", "COALESCE(BLANK(),TRUE(),7)", f"IFERROR({Q}>2,7)", f"IFERROR(IF({Q}>2,TRUE()),7)", "IFERROR(VALUE(\"x\"),TRUE())"):
            self.assertEqual("BLANK", dax.local(f"COUNTX(Facts,{body})"), body)
        self.assertEqual("3", dax.local(f"COUNTX(Facts,IF({Q}>2,TRUE(),7))"))


class CompileTimeTest(unittest.TestCase):
    def test_switch_values_of_another_type_are_an_error_nothing_catches(self) -> None:
        _refused(self, [
            'IFERROR(SWITCH(TRUE(),"TRUE",1,2),9)',
            'SUMX(FILTER(Facts,FALSE()),SWITCH(TRUE(),1/0,UPPER(Facts[Region]),0/0))',
            'ISERROR(SWITCH(TRUE(),"",SUM(Facts[Quantity]),2))',
        ])

    def test_min_and_max_of_booleans_or_a_date_beside_text(self) -> None:
        _refused(self, ["IFERROR(MIN(TRUE(),1),1)", 'IFERROR(MIN(DATE(2020,1,1),"a"),1)'])

    def test_every_branch_is_compiled(self) -> None:
        _refused(self, [f'COUNTX(VALUES({R}),IF(LEN("a"),{R},{Q}>2))', f"COUNTX(VALUES({R}),COALESCE(UPPER({R}),Facts[Sales]/0))"])

    def test_true_false_body_over_an_empty_table(self) -> None:
        _refused(self, ["COUNTX(FILTER(Facts,FALSE()),IF(FALSE(),TRUE(),BLANK()))", "COUNTX(EXCEPT(Facts,Facts),LASTNONBLANKVALUE(Facts[Quantity],TRUE()))"])


class FirstNonBlankTest(unittest.TestCase):
    def test_typing(self) -> None:
        _refused(self, [
            f'FIRSTNONBLANKVALUE({R},BLANK())="West"',
            f'FIRSTNONBLANK(FILTER(VALUES({R}),{R}<>"East"),BLANK())=1',
            f'STDEVX.P(Facts,FIRSTNONBLANK(FILTER(VALUES({R}),{R}<>"East"),BLANK()))',
        ])

    def test_on_a_row_it_transitions(self) -> None:
        self.assertEqual("6", dax.local(f"COUNTROWS(FILTER(Facts,FIRSTNONBLANKVALUE({Q},MAX({Q}))>={Q}))"))
        _refused(self, [f"CALCULATE(COUNTROWS(Facts),{Q}+FIRSTNONBLANKVALUE({Q},MAX({Q}))>3)"])


class TopnKeyTest(unittest.TestCase):
    def test_a_key_of_several_values_ties_every_row(self) -> None:
        self.assertEqual("6", dax.local(f"COUNTROWS(TOPN(1,Facts,VALUES({Q})))"))
        self.assertEqual("3", dax.local(f"COUNTROWS(TOPN(1,VALUES({R}),VALUES({R})))"))


class FilterTest(unittest.TestCase):
    def test_keepfilters_inside_evaluateandlog_replaces(self) -> None:
        self.assertEqual("8", dax.local(f'CALCULATE(CALCULATE(SUM({Q}),EVALUATEANDLOG(KEEPFILTERS({R}="East"))),{R}="West")'))
        self.assertEqual("BLANK", dax.local(f'CALCULATE(CALCULATE(SUM({Q}),KEEPFILTERS({R}="East")),{R}="West")'))
        self.assertEqual("BLANK", dax.local(f'CALCULATE(CALCULATE(SUM({Q}),KEEPFILTERS(EVALUATEANDLOG({R}="East"))),{R}="West")'))

    def test_a_variable_in_a_filter(self) -> None:
        _refused(self, [
            "CALCULATE(COUNTROWS(Facts),VAR t = ALL(Facts) VAR u = t+1 RETURN t)",
            f"CALCULATE(SUM({Q}),VAR t = {Q} RETURN ALL({R}))",
            f"COUNTROWS(CALCULATETABLE(Facts,EVALUATEANDLOG(VAR t = {Q} RETURN FILTER(Facts,{Q}>t))))",
        ])


class RefusalsTest(unittest.TestCase):
    def test_walks_the_engine_decides(self) -> None:
        _refused(self, [
            f'CONCATENATEX(Facts,COALESCE(BLANK(),{Q}>2,Facts[Sales]),"|")',
            f'CONCATENATEX(DISTINCT(Facts),IF({Q}>2,1,2),"|")',
            f'CONCATENATEX(TOPN(2,Facts,{Q}),COALESCE(Facts[Sales],1),"|")',
            f'CONCATENATEX(Facts,IF(MAX({Q})>3,{Q}>2,UPPER({R})),"|")',
        ])

    def test_statistics_the_engine_computes_otherwise(self) -> None:
        _refused(self, [
            "GEOMEANX(Facts,IFERROR(CURRENCY(3),FALSE()))",
            f"STDEVX.S(Facts,IF(FALSE(),Facts[Sales]/0,DATE(2020,1,1)+{Q}))",
            f"MEDIANX(FILTER(Facts,{Q}>2),IF(ISBLANK(Facts[Sales]),1))",
        ])


if __name__ == "__main__":
    unittest.main()
