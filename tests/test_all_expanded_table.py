"""ALL / REMOVEFILTERS / ALLEXCEPT on a table that has related one-side tables (iteration 81).

Expected values are live Power BI Desktop 2.157.879.0 answers measured by the fact-table reverse-engineering agent on the
Dim / Fact / Calendar model of tests/test_allselected_critic2.py (Fact->Dim on Prod, Fact.Dt->Cal active, Fact.Ship->Cal
inactive). The rule they pin: ALL(T), REMOVEFILTERS(T) and ALLEXCEPT(T, ...) act on T *and on every table on the one side
reachable from T through active relationships* (a filter on Dim[Cat] is a filter of the expanded Fact table), never on the
many side; ALL(column) removes exactly that physical column; ALLEXCEPT may keep columns of any table of the expansion.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.test_allselected_critic2 import ours
from tools.parity_check import status

FIXTURE = json.loads((Path(__file__).parent / "fixtures_fact_all.json").read_text())


def _count(modifier: str, outer: str, measure: str = "COUNTROWS(CB_Fact)") -> str:
    return f"CALCULATE(CALCULATE({measure},{modifier}),{outer})"


class ExpandedTableClearTests(unittest.TestCase):
    def check(self, cases: dict[str, str]) -> None:
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                self.assertEqual(expected, ours(expression).removesuffix(".0"))

    def test_all_of_the_fact_table_clears_the_related_filters(self) -> None:
        self.check({
            _count("ALL(CB_Fact)", 'CB_Dim[Cat]="A"'): "13",
            _count("ALL(CB_Fact)", 'CB_Dim[Cat]="A"', "SUM(CB_Fact[Amt])"): "375",
            _count("ALL(CB_Fact)", 'CB_Dim[Grp]="X"'): "13",
            _count("ALL(CB_Fact)", "CB_Cal[Year]=2024"): "13",
            _count("REMOVEFILTERS(CB_Fact)", 'CB_Dim[Cat]="A"'): "13",
            _count("ALLNOBLANKROW(CB_Fact)", 'CB_Dim[Cat]="A"'): "13",
            _count("ALL(CB_Fact)", "CB_Fact[Qty]>2"): "13",
            _count("ALL(CB_Fact)", 'CB_Dim[Cat]="A"', "COUNTROWS(CB_Dim)"): "5",
        })

    def test_all_of_a_one_side_table_leaves_the_many_side(self) -> None:
        self.check({
            _count("ALL(CB_Dim)", 'CB_Dim[Cat]="A"'): "13",
            _count("ALL(CB_Dim)", "CB_Fact[Qty]>2"): "6",
            _count("ALL(CB_Dim)", "CB_Cal[Year]=2024"): "8",
            _count("ALL(CB_Cal)", "CB_Cal[Year]=2024"): "13",
            _count("ALL(CB_Cal)", 'CB_Dim[Cat]="A"'): "8",
        })

    def test_all_of_a_column_is_that_physical_column_only(self) -> None:
        self.check({
            _count("ALL(CB_Fact[Prod])", 'CB_Dim[Prod]="P1"'): "5",
            _count("ALL(CB_Dim[Prod])", 'CB_Fact[Prod]="P1"'): "5",
            _count("ALL(CB_Fact[Prod])", 'CB_Dim[Cat]="A"'): "8",
            _count("ALL(CB_Dim[Cat])", 'CB_Dim[Cat]="A"'): "13",
            _count("ALL(CB_Dim[Cat])", 'CB_Dim[Grp]="X"'): "8",
        })

    def test_allexcept_keeps_columns_of_any_table_of_the_expansion(self) -> None:
        self.check({
            _count("ALLEXCEPT(CB_Fact,CB_Dim[Cat])", 'CB_Dim[Cat]="A"'): "8",
            _count("ALLEXCEPT(CB_Fact,CB_Dim[Cat])", 'CB_Dim[Grp]="X"'): "13",
            _count("ALLEXCEPT(CB_Fact,CB_Dim[Cat])", "CB_Fact[Qty]>2"): "13",
            _count("ALLEXCEPT(CB_Fact,CB_Fact[Qty])", 'CB_Dim[Cat]="A"'): "13",
            _count("ALLEXCEPT(CB_Fact,CB_Fact[Qty])", "CB_Fact[Qty]>2"): "6",
            _count("ALLEXCEPT(CB_Fact,CB_Cal[Year])", "CB_Cal[Year]=2024"): "8",
            _count("ALLEXCEPT(CB_Fact,CB_Cal[Year])", 'CB_Dim[Cat]="A"'): "13",
            _count("ALLEXCEPT(CB_Fact,CB_Fact[Prod])", 'CB_Dim[Prod]="P1"'): "13",
            _count("ALLEXCEPT(CB_Dim,CB_Dim[Cat])", "CB_Fact[Qty]>2"): "6",
            _count("ALLEXCEPT(CB_Fact,CB_Dim)", 'CB_Dim[Cat]="A"'): "8",  # a bare table keeps all of its columns
            _count("ALLEXCEPT(CB_Fact,CB_Dim)", "CB_Fact[Qty]>2"): "13",
            _count("ALLEXCEPT(CB_Fact,CB_Dim[Cat])", 'CB_Dim[Cat]="A"', "SUM(CB_Fact[Amt])"): "160",
            "CALCULATE(SUM(CB_Fact[Amt]),ALLEXCEPT(CB_Fact,CB_Dim[Cat]))": "375",
        })

    def test_a_column_outside_the_expansion_is_refused_like_power_bi(self) -> None:
        for expression in (
            _count("ALLEXCEPT(CB_Dim,CB_Fact[Prod])", 'CB_Dim[Cat]="A"'),
            _count("ALLEXCEPT(CB_Cal,CB_Fact[Qty])", "CB_Cal[Year]=2024"),
        ):
            with self.subTest(expression=expression):
                self.assertTrue(ours(expression).startswith("LOCAL-REJECT"), ours(expression))

    def test_an_inactive_relationship_is_not_part_of_the_expansion(self) -> None:
        self.check({
            # Cal is reached only through Fact.Ship (inactive) unless the enclosing CALCULATE activates it
            "CALCULATE(CALCULATE(COUNTROWS(CB_Fact),ALL(CB_Fact)),CB_Cal[Year]=2024,USERELATIONSHIP(CB_Fact[Ship],CB_Cal[Date]))": "13",
        })

    def test_removals_run_before_the_new_filters(self) -> None:
        self.check({
            _count("ALL(CB_Fact),CB_Dim[Cat]=\"B\"", 'CB_Dim[Cat]="A"'): "5",
            _count("CB_Dim[Cat]=\"B\",ALL(CB_Fact)", 'CB_Dim[Cat]="A"'): "5",
            _count("ALL(CB_Fact),CB_Fact[Qty]>2", 'CB_Dim[Cat]="A"'): "6",
            _count("ALL(CB_Fact),CB_Cal[Year]=2024", 'CB_Dim[Cat]="A"'): "8",
            _count("ALL(CB_Fact),ALL(CB_Dim)", 'CB_Dim[Cat]="A"'): "13",
        })

    def test_the_transition_of_a_dimension_row_is_wiped_by_all_of_the_fact(self) -> None:
        self.check({
            "SUMX(SELECTCOLUMNS(CB_Dim,\"p\",CB_Dim[Prod]),CALCULATE(SUM(CB_Fact[Amt]),ALL(CB_Fact)))": "1875",
            "SUMX(CB_Dim,CALCULATE(COUNTROWS(CB_Dim),ALL(CB_Fact)))": "25",
            'CALCULATE(SUMX(VALUES(CB_Dim[Cat]),CALCULATE(COUNTROWS(CB_Fact),ALL(CB_Fact))),CB_Dim[Cat]="A")': "13",
            'CALCULATE(SUMX(VALUES(CB_Dim[Cat]),CALCULATE(COUNTROWS(CB_Fact),ALLEXCEPT(CB_Fact,CB_Dim[Cat]))),CB_Dim[Cat]="A")': "8",
        })

    def test_table_values_ignore_every_filter(self) -> None:
        self.check({
            'CALCULATE(COUNTROWS(ALL(CB_Fact)),CB_Dim[Cat]="A")': "13",
            'CALCULATE(COUNTROWS(ALL(CB_Dim)),CB_Fact[Qty]>2)': "5",
        })

    def test_saved_power_bi_answers(self) -> None:
        failures = []
        for item in FIXTURE["items"]:
            answer = ours(item["expr"])
            if status(item["powerbi"], answer) != "match":
                failures.append((item["expr"], item["powerbi"], answer))
        self.assertEqual([], failures[:5], f"{len(failures)} of {len(FIXTURE['items'])} differ from Power BI")

    def test_fixture_is_not_vacuous(self) -> None:
        self.assertGreater(len(FIXTURE["items"]), 300)
        self.assertGreater(len({item["powerbi"] for item in FIXTURE["items"]}), 15)


if __name__ == "__main__":
    unittest.main()
