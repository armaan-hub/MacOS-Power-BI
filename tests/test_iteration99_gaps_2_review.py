"""Iteration 99 review (Task 11, gaps-2): fresh shapes against live Power BI Desktop (2.157.879.0).

Two review batteries (shapes that are not in the saved battery; answers frozen from Power BI) and the same kinds of shapes asked on three other
Facts tables (rows in another order) never differ from Power BI. What the fresh shapes showed about the first build:
  - an iterator over a table with no rows compiles its expression all the same: a name that exists nowhere is an error at any depth (a nested
    SUMX, a CALCULATE filter inside the body), a table where one value is wanted is an error, the body of SUMX / AVERAGEX / PRODUCTX / MEDIANX /
    the statistical iterators may not be text or True/False (COUNTX not True/False), PRODUCTX / MEDIANX / GEOMEANX / PERCENTILEX not a date;
    a FILTER predicate written as text that is no True/False ("a") is an error, text read from a column is not; the type comes from the expression (MAX of a text column, CALCULATE of it), never from a value;
  - the same text / Boolean rules for a table with rows (GEOMEANX / STDEVX / VARX over FORMAT(...) are errors), GEOMEAN of negative values
    keeps the sign of the product, Infinity or NaN beside the statistical iterators and one repeated fraction are not modelled;
  - an IF / SWITCH whose branches differ in type is a Variant, which every iterator takes.
Open (logged in HANDOFF.md): a computed SELECTCOLUMNS column of an empty table has no type of its own, NOW() and LASTNONBLANK walks.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import dax_oracle_diff as dax
from tools.parity_check import status

ROOT = Path(__file__).resolve().parents[1]
PARITY = ROOT / "tools" / "parity"
EMPTY = 'FILTER(Facts,FALSE())'


def _replay(name: str) -> tuple[int, list[tuple[str, str, str, str]]]:
    saved = json.loads((PARITY / f"{name}.json").read_text())
    matched, bad = 0, []
    for item in saved["items"]:
        actual = dax.local(item["expr"])
        outcome = status(item["powerbi"], actual)
        if outcome == "match":
            matched += 1
        elif outcome != "gap-reject":
            bad.append((item["expr"], item["powerbi"], actual, outcome))
    return matched, bad


def _local_on(rows: list[tuple[str, ...]], expression: str) -> str:
    saved = (dax.ROWS, dax.LOCAL_ROWS)
    dax.ROWS = rows
    dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, row)} for row in rows]
    try:
        return dax.local(expression)
    finally:
        dax.ROWS, dax.LOCAL_ROWS = saved


def _refused(test: unittest.TestCase, expressions: list[str]) -> None:
    for expression in expressions:
        test.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"), expression)


class Gaps2ReviewTest(unittest.TestCase):
    def test_review_batteries_never_differ_from_power_bi(self) -> None:
        for name, floor in (("dax_battery_gaps2_extra", FLOOR_EXTRA), ("dax_battery_gaps2_extra2", FLOOR_EXTRA2)):
            matched, bad = _replay(name)
            self.assertEqual([], bad, name)
            self.assertGreaterEqual(matched, floor, name)

    def test_other_facts_tables_never_differ_from_power_bi(self) -> None:
        fixture = json.loads((ROOT / "tests" / "fixtures_gaps2_review_alt.json").read_text())
        for key, dataset in fixture["datasets"].items():
            rows = [tuple(row) for row in dataset["rows"]]
            bad = [
                (item["expr"], item["powerbi"])
                for item in dataset["items"]
                if status(item["powerbi"], _local_on(rows, item["expr"])) == "DIFF"
            ]
            self.assertEqual([], bad, key)
            self.assertGreaterEqual(len(dataset["items"]), 1000)

    def test_names_and_tables_are_resolved_at_any_depth_over_an_empty_table(self) -> None:
        _refused(self, [
            f"SUMX({EMPTY},SUMX(Facts,[c]))",
            f"MAXX({EMPTY},CALCULATE(SUM(Facts[Quantity]),Facts[Region]=[c]))",
            f"SUMX({EMPTY},Facts)",
            f"COUNTROWS(FILTER({EMPTY},Facts))",
            f"COUNTROWS(ADDCOLUMNS({EMPTY},\"q\",SUMX(Facts,[c])))",
        ])
        self.assertEqual("BLANK", dax.local(f"SUMX({EMPTY},SUMX(Facts,Facts[Quantity]))"))

    def test_body_types_over_an_empty_table_follow_the_function(self) -> None:
        for function in ("SUMX", "AVERAGEX", "PRODUCTX", "MEDIANX", "GEOMEANX", "STDEVX.S", "VARX.P"):
            _refused(self, [f'{function}({EMPTY},"a")', f"{function}({EMPTY},TRUE())", f"{function}({EMPTY},CALCULATE(MAX(Facts[Region])))"])
        _refused(self, [f"COUNTX({EMPTY},Facts[Quantity]>1)", f"MAXX({EMPTY},TRUE())", f"PRODUCTX({EMPTY},DATE(2020,1,1))", f"GEOMEANX({EMPTY},DATE(2020,1,1))"])
        for answer in (
            f'COUNTAX({EMPTY},Facts[Quantity]>1)', f'COUNTX({EMPTY},"a")', f"STDEVX.S({EMPTY},DATE(2020,1,1))", f"SUMX({EMPTY},DATE(2020,1,1))",
            f"SUMX({EMPTY},IF(TRUE(),1,\"a\"))", f"SUMX({EMPTY},VAR v=ISBLANK(Facts[Sales]) RETURN IF(Facts[Quantity]>1,v,1))",
        ):
            self.assertEqual("BLANK", dax.local(answer), answer)

    def test_filter_predicate_of_type_text_is_an_error_also_over_an_empty_table(self) -> None:
        _refused(self, [f'COUNTROWS(FILTER({EMPTY},"a"))', f'COUNTROWS(FILTER({EMPTY},IF(TRUE(),"a","b")))'])
        for answered in (f'COUNTROWS(FILTER({EMPTY},"1"))', f"COUNTROWS(FILTER({EMPTY},Facts[Region]))", f'COUNTROWS(FILTER({EMPTY},IF(Facts[Quantity]>1,"a","b")))'):
            self.assertEqual("BLANK", dax.local(answered), answered)  # text read from a row only fails when a row meets it

    def test_text_column_against_a_text_aggregate_and_countrows_is_typed(self) -> None:
        _refused(self, [
            "COUNTROWS(TOPN(0,Facts))>MAX(Facts[Region])",
            "IF(COUNTROWS(FILTER(Facts,FALSE()))=MAX(Facts[Region]),1,2)",
            'CALCULATE(COUNTROWS(Facts),Facts[Region]=COUNTROWS(CALCULATETABLE(Facts,Facts[Region]="East")))',
        ])

    def test_statistical_iterators_with_rows(self) -> None:
        east = 'CALCULATETABLE(Facts,Facts[Region]="East")'
        _refused(self, [
            f'GEOMEANX({east},FORMAT(Facts[Quantity],"0"))', f'STDEVX.S({east},FORMAT(Facts[Quantity],"0"))', f'VARX.P({east},IF(Facts[Quantity]>1,"1","2"))',
            f"MEDIANX({east},1/0)", f"STDEVX.P({east},1/0)", f"STDEVX.S({east},AVERAGE(Facts[Sales]))",
            f"COUNTROWS(TOPN(1,{east},IF(Facts[Quantity]>1,1,\"a\")))",
        ])
        self.assertEqual("BLANK", dax.local(f"MEDIANX({east},DIVIDE(1,0))"))
        self.assertEqual("BLANK", dax.local(f"PERCENTILEX.INC({east},DIVIDE(1,0),0.5)"))

    def test_geomean_keeps_the_sign_of_the_product(self) -> None:
        self.assertEqual("match", status("5.67816341394225", dax.local("GEOMEANX(Facts,Facts[Sales]-5)")))
        self.assertEqual("match", status("-2.15443469003188", dax.local('GEOMEANX(CALCULATETABLE(Facts,Facts[Region]="East"),-Facts[Quantity])')))


FLOOR_EXTRA = 8500
FLOOR_EXTRA2 = 11500

if __name__ == "__main__":
    unittest.main()
