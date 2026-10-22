"""Critic 3 regressions of the expanded-table change (iteration 81): patterns iteration 80 answered like Power BI.

Expected values are live Power BI Desktop answers (Critic 3, 2026-10-22) on the CB_Dim / CB_Fact / CB_Cal model.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from analytics_studio import dax_dates
from analytics_studio.measures import MeasureError, evaluate_measures
from tests.critic3_models import ours_for
from tests.test_allselected_critic2 import MEASURES, RELATIONSHIPS, TABLES, ours
from tools.dax_oracle_diff import HEADERS, LOCAL_ROWS
from tools.parity_check import status

FIXTURE = json.loads((Path(__file__).parent / "fixtures_critic3_cb.json").read_text())


class AllSelectedInsideFactIterationTests(unittest.TestCase):
    """A fact-row transition also filters Dim and Cal; ALLSELECTED(table) must not keep those transition filters."""

    def check(self, cases: dict[str, str]) -> None:
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                self.assertEqual(expected, ours(expression).removesuffix(".0"))

    def test_allselected_of_a_table_ignores_the_row_transition_of_the_fact(self) -> None:
        self.check({
            "SUMX(CB_Fact,CALCULATE(COUNTROWS(ALLSELECTED(CB_Fact))))": "169",
            "MAXX(CB_Fact,CALCULATE(COUNTROWS(ALLSELECTED(CB_Fact[Reg]))))": "3",
            "AVERAGEX(CB_Fact,CALCULATE(COUNTROWS(ALLSELECTED(CB_Fact))))": "13",
            'CALCULATE(SUMX(ADDCOLUMNS(CB_Fact,"x",CALCULATE(COUNTROWS(ALLSELECTED(CB_Fact)))),[x]),CB_Dim[Cat]="A")': "64",
        })

    def test_saved_critic_answers(self) -> None:
        failures = []
        for item in FIXTURE["items"]:
            answer = ours(item["expr"])
            if status(item["powerbi"], answer) != "match":
                failures.append((item["expr"], item["powerbi"], answer))
        self.assertEqual([], failures[:6], f"{len(failures)} of {len(FIXTURE['items'])} differ from Power BI")


class DerivedFactTablesReachTheOneSideTests(unittest.TestCase):
    """A row of ADDCOLUMNS / GENERATE / CROSSJOIN over a fact table is a whole fact row (live Power BI: 13); SELECTCOLUMNS and
    SUMMARIZE lose that identity (65, 60)."""

    def test_row_identity(self) -> None:
        for expression, expected in {
            'SUMX(GENERATE(CB_Fact,ROW("z",1)),CALCULATE(COUNTROWS(CB_Dim)))': "13",
            'SUMX(ADDCOLUMNS(CB_Fact,"z",1),CALCULATE(COUNTROWS(CB_Dim)))': "13",
            'SUMX(CROSSJOIN(CB_Fact,ROW("z",1)),CALCULATE(COUNTROWS(CB_Dim)))': "13",
            'SUMX(ADDCOLUMNS(CB_Fact,"z",1),CALCULATE(COUNTROWS(CB_Cal)))': "13",
            'SUMX(SELECTCOLUMNS(CB_Fact,"p",CB_Fact[Prod],"d",CB_Fact[Dt]),CALCULATE(COUNTROWS(CB_Dim)))': "65",
            'SUMX(SUMMARIZE(CB_Fact,CB_Fact[Prod],CB_Fact[Dt]),CALCULATE(COUNTROWS(CB_Dim)))': "60",
            "SUMX(FILTER(CB_Fact,CB_Fact[Qty]>2),CALCULATE(COUNTROWS(CB_Dim)))": "6",
        }.items():
            with self.subTest(expression=expression):
                self.assertEqual(expected, ours(expression).removesuffix(".0"))


MODEL_FIXTURE = json.loads((Path(__file__).parent / "fixtures_critic3_models.json").read_text())


class CriticThreeModelsTests(unittest.TestCase):
    """The Critic's other models (bidirectional star, orphan keys, snowflake with two facts, one-to-one): saved Power BI answers."""

    def test_saved_power_bi_answers(self) -> None:
        failures = []
        for item in MODEL_FIXTURE["items"]:
            answer = ours_for(item["model"], item["expr"])
            if status(item["powerbi"], answer) != "match":
                failures.append((item["model"], item["expr"], item["powerbi"], answer))
        self.assertEqual([], failures[:6], f"{len(failures)} of {len(MODEL_FIXTURE['items'])} differ from Power BI")

    def test_fixtures_are_not_vacuous(self) -> None:
        self.assertGreater(len(MODEL_FIXTURE["items"]), 300)
        self.assertGreater(len(FIXTURE["items"]), 400)
        self.assertGreater(len({item["powerbi"] for item in MODEL_FIXTURE["items"]}), 40)


class AllNoBlankRowTests(unittest.TestCase):
    """ALLNOBLANKROW(Fact) clears the expanded table but leaves only the one-side rows some fact row points at."""

    def test_the_one_side_tables_keep_only_referenced_rows(self) -> None:
        for expression, expected in {
            "CALCULATE(COUNTROWS(CB_Dim),ALLNOBLANKROW(CB_Fact))": "4",
            "CALCULATE(COUNTROWS(CB_Cal),ALLNOBLANKROW(CB_Fact))": "8",
            "SUMX(CB_Fact,CALCULATE(COUNTROWS(CB_Dim),ALLNOBLANKROW(CB_Fact)))": "52",
            'CALCULATE(COUNTROWS(CB_Dim),ALLNOBLANKROW(CB_Fact),CB_Dim[Cat]="C")': "BLANK",
            "CALCULATE(COUNTROWS(CB_Dim),ALL(CB_Fact))": "5",
        }.items():
            with self.subTest(expression=expression):
                self.assertEqual(expected, ours(expression).removesuffix(".0"))


class InvalidAllExceptIsACompileErrorTests(unittest.TestCase):
    """Power BI refuses an invalid ALLEXCEPT even in a branch that never runs."""

    def test_a_dead_branch_is_still_refused(self) -> None:
        for expression in (
            "IF(FALSE(),CALCULATE(SUM(CB_Fact[Amt]),ALLEXCEPT(CB_Dim,CB_Fact[Prod])),7)",
            "IF(TRUE(),7,CALCULATE(SUM(CB_Fact[Amt]),ALLEXCEPT(CB_Dim,CB_Cal[Year])))",
            "SWITCH(1,1,7,CALCULATE(SUM(CB_Fact[Amt]),ALLEXCEPT(CB_Dim,CB_Fact[Prod])))",
            "IF(FALSE(),CALCULATE(COUNTROWS(CB_Dim),ALLEXCEPT(CB_Dim,CB_Dim[Prod],CB_Dim[Cat],CB_Dim[Grp])),7)",
        ):
            with self.subTest(expression=expression):
                self.assertTrue(ours(expression).startswith("LOCAL-REJECT"), ours(expression))

    def test_a_valid_allexcept_in_a_dead_branch_is_fine(self) -> None:
        self.assertEqual("7", ours("IF(FALSE(),CALCULATE(SUM(CB_Fact[Amt]),ALLEXCEPT(CB_Fact,CB_Dim[Cat])),7)"))


def _ours_with(relationships: list[dict]) -> "callable":
    def run(expression: str) -> str:
        try:
            value = evaluate_measures(
                MEASURES + [{"name": "P__", "expression": expression}], LOCAL_ROWS, HEADERS, "Facts", measure_names=["P__"],
                table_context=TABLES, relationships=relationships, active_table_id="facts",
            )["P__"]
        except MeasureError as error:
            return f"LOCAL-REJECT:{error}"
        if isinstance(value, dax_dates.DaxDateTime):
            return dax_dates.oracle_text(value)
        return "BLANK" if value is None else str(value)
    return run


class OneToManyEncodingTests(unittest.TestCase):
    """The app stores a relationship dragged from the dimension to the fact as one_to_many: same model, same answers."""

    def test_the_orientation_of_the_relationship_does_not_matter(self) -> None:
        flipped = []
        for relationship in RELATIONSHIPS:
            flipped.append({
                **relationship, "from_table_id": relationship["to_table_id"], "to_table_id": relationship["from_table_id"],
                "from_column": relationship["to_column"], "to_column": relationship["from_column"],
                "from": relationship["to_column"], "to": relationship["from_column"], "cardinality": "one_to_many",
            })
        flipped_ours = _ours_with(flipped)
        for expression in (
            "SUMX(CB_Fact,CALCULATE(COUNTROWS(CB_Dim)))",
            'CALCULATE(SUMX(CB_Fact,CALCULATE(COUNTROWS(CB_Dim))),FILTER(ALL(CB_Dim[Cat]),CB_Dim[Cat]<>"B"))',
            'CALCULATE(CALCULATE(COUNTROWS(CB_Fact),ALL(CB_Fact)),CB_Dim[Cat]="A")',
            'CALCULATE(CALCULATE(COUNTROWS(CB_Dim),FILTER(ALL(CB_Fact),CB_Fact[Qty]>2)),CB_Cal[Year]=2024)',
        ):
            with self.subTest(expression=expression):
                self.assertEqual(ours(expression), flipped_ours(expression))


if __name__ == "__main__":
    unittest.main()
