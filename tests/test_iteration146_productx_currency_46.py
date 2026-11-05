"""Iteration 146: Task 56 productx-currency-46.

- Part A: PRODUCTX over a Currency in a SWITCH or COALESCE body (no IF inside) multiplies the exact row values, and one row is one factor.
  PRODUCTX over a Currency in an IF body with several rows is still refused (Power BI adds 30 ulps of noise there, not modelled).
- Part B: no rule kept. A constant-first COALESCE was tried and reverted (date-first breaks locked answers; number-first has 3 spec rows).
"""
import unittest

from tools import dax_oracle_diff as dax


class ProductxCurrency46Tests(unittest.TestCase):
    def test_part_a_switch_currency_product_is_exact(self) -> None:
        self.assertTrue(dax.same("64", dax.local('PRODUCTX(ADDCOLUMNS(Facts,"z",1),SWITCH(TRUE(),TRUE(),CURRENCY(-2),1))')))
        self.assertTrue(dax.same("683.59375", dax.local("PRODUCTX(Facts,SWITCH(Facts[Quantity],2,CURRENCY(7),2.5))")))
        self.assertTrue(dax.same("-2", dax.local("PRODUCTX(Facts,SWITCH(Facts[Quantity],2,CURRENCY(-2),TRUE()))")))

    def test_part_a_coalesce_currency_product_is_exact(self) -> None:
        self.assertTrue(dax.same("2.32329891992486", dax.local("PRODUCTX(FILTER(Facts,Facts[Quantity]>1),COALESCE(CURRENCY(1.23456),1))")))
        self.assertTrue(dax.same("-1.331", dax.local("PRODUCTX({1,2,3},COALESCE(CURRENCY(-1.1),1))")))

    def test_part_a_one_row_currency_conditional(self) -> None:
        self.assertTrue(dax.same("1.2346", dax.local("PRODUCTX({TRUE()},IF(0,\"a\",CURRENCY(1.23456)))")))
        self.assertTrue(dax.same("1.5", dax.local("PRODUCTX(ROW(\"Value\",1),IF(TRUE(),CONVERT(CURRENCY(1.5),CURRENCY)))")))

    def test_part_a_multi_row_if_currency_stays_refused(self) -> None:
        self.assertTrue(str(dax.local("PRODUCTX(Facts,IF(1,CURRENCY(-2)))")).startswith("LOCAL-REJECT"))
        self.assertTrue(str(dax.local("PRODUCTX({0.5,4},IF(TRUE(),CURRENCY(7)))")).startswith("LOCAL-REJECT"))

    def test_part_b_text_first_coalesce_stays_refused(self) -> None:
        self.assertTrue(str(dax.local("COUNTX({1,2},COALESCE(LASTNONBLANK(Facts[Region],1),DATE(2020,1,1),LOG(-1)))")).startswith("LOCAL-REJECT"))


if __name__ == "__main__":
    unittest.main()
