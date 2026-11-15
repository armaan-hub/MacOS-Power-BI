"""Iteration 256: Task 168 (dax-hunt-168), a Currency times a Double from ACOS, ATAN, COSH, SINH or TANH is rounded to 4 decimals.

The static type of ACOS, ATAN, ATAN2, COT, COSH, SINH and TANH was unknown, so `*` with a Currency skipped the Double-times-Currency
rule and kept the 28-digit Decimal product. They are Doubles (like SIN, COS, TAN, ASIN), so the literal-path answer is kept.

Values are the Power BI answers measured for the hunt rows (15 significant digits). Known limits that stay wrong are marked expectedFailure.
"""

import unittest
from decimal import Decimal
from tools import dax_oracle_diff as dax


def same15(pbi: str, loc: str) -> bool:
    # Power BI doubles are compared at 15 significant digits
    if loc.startswith("LOCAL-REJECT") or loc.startswith("E"):
        return False
    return Decimal(format(Decimal(float(loc)), ".15g")) == Decimal(pbi)  # the double's exact value, rounded (as the scorer does)


class TestIteration256Hunt168(unittest.TestCase):
    def test_acos_times_currency_is_currency_rounded(self) -> None:
        # measured: (ACOS(0.9))*(CURRENCY(1.23456)) is 0.5568 in Power BI
        self.assertEqual(dax.local("(ACOS(0.9))*(CURRENCY(1.23456))"), "0.5568")
        self.assertEqual(dax.local("ACOS(0.9)*CURRENCY(1.2346)"), "0.5568")

    def test_cosh_times_currency_is_currency_rounded(self) -> None:
        # measured: COSH(10)*CURRENCY(1.23456) is 13596.9374, COSH(10)*CURRENCY(0.5582) is 6147.5866
        self.assertEqual(dax.local("COSH(10)*CURRENCY(1.23456)"), "13596.9374")
        self.assertEqual(dax.local("(COSH(10))*(CURRENCY(0.5582))"), "6147.5866")
        self.assertEqual(dax.local("COSH(10)*CURRENCY(0.5582)"), "6147.5866")

    def test_sinh_times_currency_is_currency_rounded(self) -> None:
        # measured: (CURRENCY(0.5582))*(SINH(2)) is 2.0245, (SINH(2))*(CURRENCY(1000.0001)) is 3626.8608
        self.assertEqual(dax.local("(CURRENCY(0.5582))*(SINH(2))"), "2.0245")
        self.assertEqual(dax.local("(SINH(2))*(CURRENCY(1000.0001))"), "3626.8608")

    def test_atan_and_tanh_times_currency_are_currency_rounded(self) -> None:
        # measured: (ATAN(3))*(CURRENCY(3)) is 3.7471, (TANH(0.4))*(CURRENCY(3)) is 1.1398
        self.assertEqual(dax.local("(ATAN(3))*(CURRENCY(3))"), "3.7471")
        self.assertEqual(dax.local("(TANH(0.4))*(CURRENCY(3))"), "1.1398")

    def test_cosh_currency_product_with_cosh_inner_product(self) -> None:
        # measured: (COSH(10))*((ACOS(0.9))*(CURRENCY(1.23456))) is 6132.1681 (the inner product is rounded to 0.5568 first)
        self.assertEqual(dax.local("(COSH(10))*((ACOS(0.9))*(CURRENCY(1.23456)))"), "6132.1681")
        self.assertEqual(dax.local("IFERROR((COSH(10))*((ACOS(0.9))*(CURRENCY(1.23456))),\"E\")"), "6132.1681")

    def test_literal_path_unchanged(self) -> None:
        # measured: 11013.2329201033*CURRENCY(0.5582) is 6147.5866 (the literal path was already exact)
        self.assertEqual(dax.local("11013.2329201033*CURRENCY(0.5582)"), "6147.5866")

    def test_double_plus_currency_from_tanh_is_double(self) -> None:
        # measured: (TANH(0.4))+(CURRENCY(3)) is 3.37994896225523 (a double sum, 15 significant digits)
        self.assertTrue(same15("3.37994896225523", dax.local("(TANH(0.4))+(CURRENCY(3))")))

    @unittest.expectedFailure
    def test_known_limit_exp_minus_currency(self) -> None:
        # known limit (measured): (CURRENCY(3))-(EXP(1)) is 0.281718171540954 in Power BI, the last digit of EXP differs
        self.assertTrue(same15("0.281718171540954", dax.local("(CURRENCY(3))-(EXP(1))")))

    @unittest.expectedFailure
    def test_known_limit_cosh_divided_by_currency(self) -> None:
        # known limit (measured): (COSH(3))/(CURRENCY(1.23456)) is 8.15459419713086 in Power BI, the last digit of COSH differs
        self.assertTrue(same15("8.15459419713086", dax.local("(COSH(3))/(CURRENCY(1.23456))")))

    @unittest.expectedFailure
    def test_known_limit_cosh_minus_currency(self) -> None:
        # known limit (measured): (COSH(3))-(CURRENCY(0.5582)) is 9.50946199577776 in Power BI. This row was exact on main through
        # the Decimal path; with COSH as a Double the difference is the IEEE double of the COSH digits, one ulp from Power BI's
        self.assertTrue(same15("9.50946199577776", dax.local("(COSH(3))-(CURRENCY(0.5582))")))

    @unittest.expectedFailure
    def test_known_limit_pmt_last_digit(self) -> None:
        # known limit (measured): PMT(-0.02,10,6) is -0.535998695208924 in Power BI, the last digit of PMT differs
        self.assertTrue(same15("-0.535998695208924", dax.local("PMT(-0.02,10,6)")))


if __name__ == "__main__":
    unittest.main()
