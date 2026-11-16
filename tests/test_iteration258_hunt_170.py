"""Iteration 258: Task 170 (dax-hunt-170), a bare column in a value argument of ROW is refused before evaluation.

Power BI validates the whole query before it runs it. ROW does not create a row context, so a bare column in one of its value
arguments (positions 2, 4, 6 ...) with no row context is a query error, even in an IF branch that is never taken or an
IFERROR / COALESCE fallback that is never reached. The static check that refuses bare columns outside a row context now
descends into ROW's value arguments, and into COUNTROWS's table argument, and keeps the row context of enclosing iterators.

Values are the Power BI answers measured for the hunt rows. Refusals are checked by the LOCAL-REJECT prefix of dax.local.
"""

import unittest

from tools import dax_oracle_diff as dax


class TestIteration258Hunt170(unittest.TestCase):
    def test_iferror_comparison_in_row_value_is_refused(self) -> None:
        # measured: ROW("a",IFERROR(1,Facts[Sales]>0)) is a query error in Power BI
        self.assertTrue(dax.local('ROW("a",IFERROR(1,Facts[Sales]>0))').startswith("LOCAL-REJECT"))

    def test_iferror_switch_fallback_in_row_value_is_refused(self) -> None:
        # measured: ROW("a",IFERROR(SUMX(Facts,Facts[Quantity]*5),SWITCH(TRUE(),Facts[Sales]>0,0,-0.5))) is a query error in Power BI
        self.assertTrue(
            dax.local('ROW("a",IFERROR(SUMX(Facts,Facts[Quantity]*5),SWITCH(TRUE(),Facts[Sales]>0,0,-0.5)))').startswith("LOCAL-REJECT")
        )

    def test_untaken_if_branch_in_row_value_is_refused(self) -> None:
        # measured: ROW("a",IF(TRUE(),1,Facts[Sales])) is a query error in Power BI
        self.assertTrue(dax.local('ROW("a",IF(TRUE(),1,Facts[Sales]))').startswith("LOCAL-REJECT"))

    def test_coalesce_fallback_in_row_value_is_refused(self) -> None:
        # measured: ROW("a",COALESCE(1,Facts[Sales])) is a query error in Power BI
        self.assertTrue(dax.local('ROW("a",COALESCE(1,Facts[Sales]))').startswith("LOCAL-REJECT"))

    def test_untaken_if_branch_in_countrows_of_row_is_refused(self) -> None:
        # measured: COUNTROWS(ROW("a",IF(TRUE(),1,Facts[Sales]))) is a query error in Power BI
        self.assertTrue(dax.local('COUNTROWS(ROW("a",IF(TRUE(),1,Facts[Sales])))').startswith("LOCAL-REJECT"))

    def test_variable_return_branch_in_row_value_is_refused(self) -> None:
        # measured: ROW("a",VAR v=1 RETURN IF(TRUE(),v,Facts[Sales])) is a query error in Power BI
        self.assertTrue(dax.local('ROW("a",VAR v=1 RETURN IF(TRUE(),v,Facts[Sales]))').startswith("LOCAL-REJECT"))

    def test_calculate_untaken_branch_in_row_value_is_refused(self) -> None:
        # measured: ROW("a",CALCULATE(IF(TRUE(),1,Facts[Sales]))) is a query error in Power BI
        self.assertTrue(dax.local('ROW("a",CALCULATE(IF(TRUE(),1,Facts[Sales])))').startswith("LOCAL-REJECT"))

    def test_comparison_in_row_value_is_refused(self) -> None:
        # measured: ROW("a",IFERROR(1,Facts[Region]="a")) is a query error in Power BI
        self.assertTrue(dax.local('ROW("a",IFERROR(1,Facts[Region]="a"))').startswith("LOCAL-REJECT"))

    def test_untaken_if_false_arithmetic_in_row_value_is_refused(self) -> None:
        # measured: ROW("a",1+IF(FALSE(),Facts[Sales],0)) is a query error in Power BI
        self.assertTrue(dax.local('ROW("a",1+IF(FALSE(),Facts[Sales],0))').startswith("LOCAL-REJECT"))

    def test_selectedvalue_in_row_value_still_answers(self) -> None:
        # measured: ROW("a",IFERROR(1,SELECTEDVALUE(Facts[Sales]))) is 1 in Power BI
        self.assertEqual(dax.local('ROW("a",IFERROR(1,SELECTEDVALUE(Facts[Sales])))'), "1")

    def test_row_context_of_sumx_makes_bare_column_valid_in_row_still_answers(self) -> None:
        # measured: ROW("a",SUMX(Facts,IF(TRUE(),1,Facts[Sales]))) is 6 in Power BI
        self.assertEqual(dax.local('ROW("a",SUMX(Facts,IF(TRUE(),1,Facts[Sales])))'), "6")

    def test_iferror_over_sumx_row_context_still_answers(self) -> None:
        # measured: SUMX(Facts,IFERROR(1,Facts[Sales]>0)) is 6 in Power BI
        self.assertEqual(dax.local('SUMX(Facts,IFERROR(1,Facts[Sales]>0))'), "6")

    def test_iferror_over_countrows_filter_still_answers(self) -> None:
        # measured: IFERROR(1,COUNTROWS(FILTER(Facts,Facts[Sales]>0))) is 1 in Power BI
        self.assertEqual(dax.local('IFERROR(1,COUNTROWS(FILTER(Facts,Facts[Sales]>0)))'), "1")

    def test_sumx_over_row_with_untaken_if_is_refused(self) -> None:
        # measured (t217): SUMX(ROW("a",IF(FALSE(),Facts[Sales],2)),[a]) is a query error in Power BI (the table argument has no row context)
        self.assertTrue(dax.local('SUMX(ROW("a",IF(FALSE(),Facts[Sales],2)),[a])').startswith("LOCAL-REJECT"))

    def test_maxx_over_row_with_untaken_if_is_refused(self) -> None:
        # measured (t217 variant): MAXX(ROW("a",IF(FALSE(),Facts[Sales],2)),[a]) is a query error in Power BI
        self.assertTrue(dax.local('MAXX(ROW("a",IF(FALSE(),Facts[Sales],2)),[a])').startswith("LOCAL-REJECT"))

    def test_averagex_over_row_with_untaken_if_is_refused(self) -> None:
        # measured (t217 variant): AVERAGEX(ROW("a",IF(FALSE(),Facts[Sales],2)),[a]) is a query error in Power BI
        self.assertTrue(dax.local('AVERAGEX(ROW("a",IF(FALSE(),Facts[Sales],2)),[a])').startswith("LOCAL-REJECT"))

    def test_sumx_expression_countrows_of_row_still_answers(self) -> None:
        # measured (t217): SUMX(Facts,COUNTROWS(ROW("a",Facts[Sales]))) is 6 in Power BI (the expression keeps the row context of SUMX)
        self.assertEqual(dax.local('SUMX(Facts,COUNTROWS(ROW("a",Facts[Sales])))'), "6")
