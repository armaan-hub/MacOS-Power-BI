"""Critic-4 fixes (iteration 83): PARALLELPERIOD year shifts, SUMX typing, USERELATIONSHIP + table filter, ALLSELECTED and the unknown member.

Cases that quote a Power BI answer use the Critic-4 measurements on the ZO model (fact rows with orphan keys); the CB cases follow from the
same rules on a calendar covering 2023-2024.
"""
from __future__ import annotations

import unittest

from tests.critic3_models import ours_for
from tests.test_allselected_critic2 import ours as cb_ours
from tools.parity_check import status


class ParallelPeriodTests(unittest.TestCase):
    def test_a_year_shifted_outside_the_calendar_filters_everything_out(self) -> None:
        # 2023 shifted by -1 year is 2022: no calendar rows. (The year end was once computed as start + 366 days and leaked 2023.)
        self.assertEqual("BLANK", cb_ours("CALCULATE(CALCULATE(COUNTROWS(CB_Cal),PARALLELPERIOD(CB_Cal[Date],-1,YEAR)),CB_Cal[Year]=2023)"))
        self.assertEqual("365", cb_ours("CALCULATE(CALCULATE(COUNTROWS(CB_Cal),PARALLELPERIOD(CB_Cal[Date],-1,YEAR)),CB_Cal[Year]=2024)"))

    def test_the_prior_year_per_year_row_counts_only_the_years_that_have_one(self) -> None:
        self.assertEqual("365", cb_ours("SUMX(VALUES(CB_Cal[Year]),CALCULATE(COUNTROWS(CB_Cal),PARALLELPERIOD(CB_Cal[Date],-1,YEAR)))"))


class SumxTypeTests(unittest.TestCase):
    def test_sumx_of_a_date_is_a_date(self) -> None:
        self.assertRegex(cb_ours("SUMX(CB_Fact,CB_Fact[Dt])"), r"^\d\d/\d\d/\d{4} ")

    def test_a_number_branch_makes_the_iterated_value_a_number(self) -> None:
        for expression in (
            "SUMX(CB_Fact,IF(ISBLANK(CB_Fact[Dt]),0,CB_Fact[Dt]))",
            "SUMX(CB_Fact,COALESCE(CB_Fact[Dt],0))",
            "SUMX(CB_Fact,SWITCH(TRUE(),CB_Fact[Qty]>2,CB_Fact[Dt],0))",
        ):
            with self.subTest(expression=expression):
                self.assertNotRegex(cb_ours(expression), r"\d\d/\d\d/\d{4}")


class UserelationshipTableFilterTests(unittest.TestCase):
    def test_it_still_works_when_every_row_matches_the_calendar(self) -> None:
        self.assertEqual("35", cb_ours(
            "CALCULATE(SUM(CB_Fact[Amt]),USERELATIONSHIP(CB_Fact[Ship],CB_Cal[Date]),FILTER(CB_Fact,CB_Fact[Qty]<=3))").removesuffix(".0"))

    def test_it_is_refused_instead_of_guessed_when_rows_match_no_calendar_date(self) -> None:
        # Power BI 35 for this ZO expression; the unknown-member case is not modelled, so it must not answer 190.
        answer = ours_for("ZO", "CALCULATE(SUM(ZO_Fact[Amt]),USERELATIONSHIP(ZO_Fact[Ship],ZO_Cal[Date]),FILTER(ZO_Fact,ZO_Fact[Qty]<=3))")
        self.assertTrue(answer.startswith("LOCAL-REJECT"), answer)


class AllSelectedUnknownMemberTests(unittest.TestCase):
    def test_the_shares_of_a_selection_that_includes_the_blank_member_add_up(self) -> None:
        # every row of VALUES(Cat) (B, C and the blank member) sees the same ALLSELECTED(Cat) denominator
        self.assertEqual("705", ours_for("ZO",
            'CALCULATE(SUMX(VALUES(ZO_Dim[Cat]),CALCULATE(SUM(ZO_Fact[Amt]),ALLSELECTED(ZO_Dim[Cat]))),ZO_Dim[Cat]<>"A")').removesuffix(".0"))
        self.assertEqual("match", status("1", ours_for("ZO",  # Power BI 1 (Critic 4)
            'CALCULATE(CALCULATE(SUMX(VALUES(ZO_Dim[Cat]),[mShareCat]),ZO_Dim[Cat]<>"A"),ZO_Dim[Cat]<>"A")')))


if __name__ == "__main__":
    unittest.main()
