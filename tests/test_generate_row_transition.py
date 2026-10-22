"""ROW(...) inside GENERATE sees the row of the enclosing iteration (iteration 82).

Expected values are live Power BI Desktop 2.157.879.0 answers (Critic 3 corpus, Dim / Fact / Calendar model): a CALCULATE inside
the ROW of GENERATE(T, ROW(...)) transitions the current row of T, like a CALCULATE in ADDCOLUMNS does.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from tests.test_allselected_critic2 import ours
from tools.parity_check import status

FIXTURE = json.loads((Path(__file__).parent / "fixtures_generate_row.json").read_text())


class GenerateRowTransitionTests(unittest.TestCase):
    def test_a_calculate_in_row_transitions_the_generated_row(self) -> None:
        for expression, expected in {
            'SUMX(GENERATE(CB_Fact,ROW("z",CALCULATE(SUM(CB_Fact[Id])))),[z])': "91",
            'SUMX(GENERATE(CB_Dim,ROW("z",CALCULATE(COUNTROWS(CB_Dim)))),[z])': "5",
            'SUMX(GENERATE(CB_Dim,ROW("z",CALCULATE(COUNTROWS(CB_Fact)))),[z])': "13",
            'SUMX(GENERATE(CB_Fact,ROW("z",CALCULATE(COUNTROWS(CB_Dim)))),[z])': "13",
            'SUMX(GENERATE(CB_Fact,ROW("z",SUM(CB_Fact[Id]))),[z])': "1183",  # no CALCULATE: nothing transitions
        }.items():
            with self.subTest(expression=expression):
                self.assertEqual(expected, ours(expression).removesuffix(".0"))

    def test_sumx_of_dates_is_a_date(self) -> None:
        for expression, expected in {
            "SUMX(CB_Fact,CALCULATE(MAX(CB_Fact[Dt])))": "01/17/3510 00:00:00",
            "SUMX(CB_Fact,CB_Fact[Qty])": "39",
        }.items():
            with self.subTest(expression=expression):
                self.assertEqual(expected, ours(expression))

    def test_saved_power_bi_answers(self) -> None:
        failures = []
        for item in FIXTURE["items"]:
            answer = ours(item["expr"])
            if status(item["powerbi"], answer) != "match":
                failures.append((item["expr"], item["powerbi"], answer))
        self.assertEqual([], failures[:6], f"{len(failures)} of {len(FIXTURE['items'])} differ from Power BI")

    def test_fixture_is_not_vacuous(self) -> None:
        self.assertGreater(len(FIXTURE["items"]), 40)


if __name__ == "__main__":
    unittest.main()
