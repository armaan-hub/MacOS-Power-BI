"""Iteration 84: shapes where the local engine would answer differently from live Power BI are refused, not guessed.

Live Power BI answers (ZO / ZB / ZS models of tests/critic3_models.py):
  SUMX(ZS_Fact, CALCULATE(COUNTROWS(ZS_Dim)))                    -> 8     (fact-row pin through two routes to the dimension)
  CALCULATE(COUNTROWS(ALLSELECTED(ZB_Dim[Prod])), ZB_Cal[Year]=2023) -> 5 (both-way narrowing of the dimension is ignored)
  MAX(DATE(2023,1,1), 5) and IF(TRUE(), DATE(2023,1,1), 5)         -> 44927 (a date mixed with a number is a number)
"""
from __future__ import annotations

import unittest

from tests.critic3_models import ours_for


class RefusalTests(unittest.TestCase):
    def refused(self, model: str, expression: str) -> None:
        answer = ours_for(model, expression)
        self.assertTrue(answer.startswith("LOCAL-REJECT"), f"{expression} answered {answer!r}")

    def test_fact_row_transition_reading_a_table_behind_two_routes(self) -> None:
        self.refused("ZS", "SUMX(ZS_Fact,CALCULATE(COUNTROWS(ZS_Dim)))")
        self.refused("ZS", "COUNTX(ZS_Fact,CALCULATE(COUNTROWS(ZS_Fact2)))")
        self.refused("ZS", "SUMX(ZS_Fact,CALCULATE(SUM(ZS_Fact[Amt]),ZS_Dim[Cat]=\"A\"))")

    def test_fact_row_transition_reading_only_the_fact_and_calendar_still_answers(self) -> None:
        self.assertFalse(ours_for("ZS", "SUMX(ZS_Fact,CALCULATE(SUM(ZS_Fact[Amt]),DATESYTD(ZS_Cal[Date])))").startswith("LOCAL-REJECT"))
        self.assertFalse(ours_for("ZS", "SUMX(VALUES(ZS_Cal[Year]),CALCULATE(COUNTROWS(ZS_Dim)))").startswith("LOCAL-REJECT"))

    def test_allselected_column_under_both_way_narrowing(self) -> None:
        self.refused("ZB", "CALCULATE(COUNTROWS(ALLSELECTED(ZB_Dim[Prod])),ZB_Cal[Year]=2023)")
        self.refused("ZB", "CALCULATE(COUNTROWS(ALLSELECTED(ZB_Reg[Reg])),ZB_Cal[Year]=2023)")

    def test_date_mixed_with_a_number(self) -> None:
        # live Power BI (Task 13 review): a date beside a number is a number
        self.assertEqual("44927", ours_for("ZO", "MAX(DATE(2023,1,1),5)"))
        self.assertEqual("44927", ours_for("ZO", "MAX(5,DATE(2023,1,1))"))
        self.assertEqual("44927", ours_for("ZO", "IF(TRUE(),DATE(2023,1,1),5)"))
        self.assertFalse(ours_for("ZO", "MAX(DATE(2023,1,1),DATE(2024,1,1))").startswith("LOCAL-REJECT"))


if __name__ == "__main__":
    unittest.main()
