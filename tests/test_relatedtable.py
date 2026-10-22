"""RELATEDTABLE(table): CALCULATETABLE(table) with the row context of the enclosing iterator as the filter.

Saved answers are live Power BI Desktop 2.157.879.0 results on the ZO model (tests/fixtures_relatedtable.json). Items marked
"pending" in the fixture need the unknown-member (virtual BLANK row for orphan keys) rewrite or hit a CALCULATE filter-subset gap
that is not RELATEDTABLE's; they are not asserted here, only checked not to crash.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from analytics_studio.measures import MeasureError, evaluate_measures
from tests.critic3_models import build, ours_for
from tools.dax_oracle_diff import HEADERS, LOCAL_ROWS
from tools.parity_check import status

FIXTURE = json.loads((Path(__file__).parent / "fixtures_relatedtable.json").read_text())


class SavedPowerBiAnswersTests(unittest.TestCase):
    def test_every_matching_item_still_matches(self) -> None:
        failures = []
        for item in FIXTURE["items"]:
            if item["status"] != "match":
                continue
            answer = ours_for(item["model"], item["expr"])
            if status(item["powerbi"], answer) != "match":
                failures.append((item["expr"], item["powerbi"], answer))
        self.assertEqual([], failures[:6], f"{len(failures)} saved Power BI answers regressed")

    def test_pending_items_do_not_crash_or_reject_the_function(self) -> None:
        for item in [i for i in FIXTURE["items"] if i["status"] == "pending"][::6]:
            answer = ours_for(item["model"], item["expr"])
            with self.subTest(expression=item["expr"]):
                self.assertFalse(answer.startswith("LOCAL-CRASH"), answer)
                self.assertNotIn("RELATEDTABLE", answer)

    def test_fixture_is_not_vacuous(self) -> None:
        matching = [i for i in FIXTURE["items"] if i["status"] == "match"]
        self.assertGreater(len(FIXTURE["items"]), 350)
        self.assertGreater(len(matching), 150)


class RowContextTests(unittest.TestCase):
    """Hand-derived on the ZB bidirectional star (10 fact rows; Dt is the active date relationship, Ship the inactive one)."""

    def check(self, cases: dict[str, str]) -> None:
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                self.assertEqual(expected, ours_for("ZB", expression).removesuffix(".0"))

    def test_one_side_row_to_its_fact_rows(self) -> None:
        self.check({
            "SUMX(ZB_Dim,COUNTROWS(RELATEDTABLE(ZB_Fact)))": "10",
            "SUMX(ZB_Reg,COUNTROWS(RELATEDTABLE(ZB_Fact)))": "10",
            "SUMX(ZB_Dim,SUMX(RELATEDTABLE(ZB_Fact),ZB_Fact[Amt]))": "300",
            "MAXX(ZB_Dim,COUNTROWS(RELATEDTABLE(ZB_Fact)))": "3",
            "AVERAGEX(ZB_Dim,COUNTROWS(RELATEDTABLE(ZB_Fact)))": "2",
            'CONCATENATEX(ZB_Dim,COUNTROWS(RELATEDTABLE(ZB_Fact)),",",ZB_Dim[Prod])': "3,2,2,2,1",
        })

    def test_many_side_row_to_its_one_side_row(self) -> None:
        self.check({
            "SUMX(ZB_Fact,COUNTROWS(RELATEDTABLE(ZB_Dim)))": "10",
            "SUMX(ZB_Fact,COUNTROWS(RELATEDTABLE(ZB_Reg)))": "10",
            "SUMX(ZB_Fact,COUNTROWS(FILTER(RELATEDTABLE(ZB_Dim),ZB_Dim[Cat]=\"A\")))": "5",
        })

    def test_works_as_the_table_argument_of_other_table_functions(self) -> None:
        self.check({
            "SUMX(ZB_Dim,COUNTROWS(FILTER(RELATEDTABLE(ZB_Fact),ZB_Fact[Qty]>2)))": "5",
            "SUMX(ZB_Dim,SUMX(TOPN(1,RELATEDTABLE(ZB_Fact),ZB_Fact[Amt]),ZB_Fact[Amt]))": "195",
            "SUMX(ZB_Dim,COUNTROWS(DISTINCT(RELATEDTABLE(ZB_Fact))))": "10",
            'SUMX(ADDCOLUMNS(ZB_Dim,"n",COUNTROWS(RELATEDTABLE(ZB_Fact))),[n])': "10",
            "SUMX(ZB_Dim,COUNTROWS(RELATEDTABLE(ZB_Fact)))+COUNTROWS(RELATEDTABLE(ZB_Fact))": "20",
        })

    def test_without_a_row_context_it_is_the_table_in_the_outer_filter_context(self) -> None:
        self.check({
            "COUNTROWS(RELATEDTABLE(ZB_Fact))": "10",
            'CALCULATE(COUNTROWS(RELATEDTABLE(ZB_Fact)),ZB_Dim[Cat]="A")': "5",
        })

    def test_row_context_overrides_the_outer_filter_on_its_own_table_only(self) -> None:
        self.check({
            'CALCULATE(SUMX(ZB_Dim,COUNTROWS(RELATEDTABLE(ZB_Fact))),ZB_Dim[Cat]="A")': "5",
            'CALCULATE(SUMX(ALL(ZB_Dim),COUNTROWS(RELATEDTABLE(ZB_Fact))),ZB_Dim[Cat]="A")': "10",
            "CALCULATE(SUMX(ZB_Dim,COUNTROWS(RELATEDTABLE(ZB_Fact))),ZB_Cal[Year]=2024)": "6",
            "CALCULATE(SUMX(ALL(ZB_Dim),COUNTROWS(RELATEDTABLE(ZB_Fact))),ZB_Cal[Year]=2024)": "6",
        })

    def test_userelationship_in_an_enclosing_calculate_chooses_the_relationship(self) -> None:
        day = "FILTER(ZB_Cal,ZB_Cal[Date]=DATE(2024,1,6))"
        self.check({
            f"SUMX({day},COUNTROWS(RELATEDTABLE(ZB_Fact)))": "BLANK",
            f"CALCULATE(SUMX({day},COUNTROWS(RELATEDTABLE(ZB_Fact))),USERELATIONSHIP(ZB_Fact[Ship],ZB_Cal[Date]))": "1",
            f"SUMX({day},CALCULATE(COUNTROWS(RELATEDTABLE(ZB_Fact)),USERELATIONSHIP(ZB_Fact[Ship],ZB_Cal[Date])))": "1",
        })

    def test_equals_the_calculate_equivalent_on_other_models(self) -> None:
        twins = [
            ("ZS", "SUMX(ZS_Sup,COUNTROWS(RELATEDTABLE(ZS_Fact)))", "SUMX(ZS_Sup,CALCULATE(COUNTROWS(ZS_Fact)))"),
            ("ZS", "SUMX(ZS_Reg,COUNTROWS(RELATEDTABLE(ZS_Dim)))", "SUMX(ZS_Reg,CALCULATE(COUNTROWS(ZS_Dim)))"),
            ("ZS", "SUMX(ZS_Reg,SUMX(RELATEDTABLE(ZS_Fact),ZS_Fact[Amt]))", "SUMX(ZS_Reg,CALCULATE(SUM(ZS_Fact[Amt])))"),
            ("ZS", "SUMX(ZS_Dim,COUNTROWS(RELATEDTABLE(ZS_Fact2)))", "SUMX(ZS_Dim,CALCULATE(COUNTROWS(ZS_Fact2)))"),
            ("ZM", "SUMX(ZM_A,COUNTROWS(RELATEDTABLE(ZM_B)))", "SUMX(ZM_A,CALCULATE(COUNTROWS(ZM_B)))"),
            ("ZM", "SUMX(ZM_B,COUNTROWS(RELATEDTABLE(ZM_A)))", "SUMX(ZM_B,CALCULATE(COUNTROWS(ZM_A)))"),
            ("ZM", "SUMX(ZM_U,SUMX(RELATEDTABLE(ZM_F),ZM_F[Amt]))", "SUMX(ZM_U,CALCULATE(SUM(ZM_F[Amt])))"),
        ]
        for model, expression, twin in twins:
            with self.subTest(expression=expression):
                answer = ours_for(model, expression)
                self.assertFalse(answer.startswith("LOCAL"), answer)
                self.assertEqual(ours_for(model, twin), answer)


class RejectionTests(unittest.TestCase):
    def reject(self, expression: str) -> str:
        tables, relationships, measures = build("ZB")
        with self.assertRaises(MeasureError) as caught:
            evaluate_measures(
                [{"name": "P__", "expression": expression, "home_table_id": "facts"}], LOCAL_ROWS, HEADERS, "Facts",
                measure_names=["P__"], table_context=tables, relationships=relationships, active_table_id="facts",
            )
        return str(caught.exception)

    def test_a_table_in_a_scalar_branch_is_refused_even_when_never_evaluated(self) -> None:
        """Saved Power BI answers (tools/parity/dax_battery_evaluation_order.json): an error for each of these."""
        for expression in ("IF(FALSE(),RELATEDTABLE(ZB_Fact),1)", "IF(TRUE(),1,RELATEDTABLE(ZB_Fact))", "SWITCH(1,1,1,RELATEDTABLE(ZB_Fact))",
                           "SUMX(ZB_Dim,IF(FALSE(),RELATEDTABLE(ZB_Fact),1))"):
            with self.subTest(expression=expression):
                self.assertIn("table", self.reject(expression))

    def test_needs_exactly_one_table(self) -> None:
        for expression in ("COUNTROWS(RELATEDTABLE())", "COUNTROWS(RELATEDTABLE(ZB_Fact,ZB_Dim))", "SUMX(ZB_Dim,RELATEDTABLE(ZB_Fact[Amt]))"):
            with self.subTest(expression=expression):
                self.assertIn("RELATEDTABLE", self.reject(expression))


if __name__ == "__main__":
    unittest.main()
