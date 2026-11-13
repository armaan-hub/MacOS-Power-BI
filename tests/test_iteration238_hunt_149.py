"""Task 149 (dax-hunt-149): fresh Power BI hunt, batch 7. Exact assertions per family, values copied from the measured Power BI answers.

Family A: MOD with a CURRENCY dividend and a non-CURRENCY (Double) divisor is computed as a Double MOD (IEEE fmod, sign of the divisor).
A CURRENCY divisor or an integer divisor keeps the CURRENCY result.
Family B: MEDIANX over a body that builds a CURRENCY, with an even count, is a CURRENCY: the midpoint is rounded to four places with ties
toward +infinity (AVERAGEX keeps its own rule, half away from zero).
"""

import unittest
from decimal import Decimal

from tools.dax_oracle_diff import local


def _same_15(expression: str, measured: str) -> bool:
    """The local answer and the measured Power BI answer agree to 15 significant digits."""
    return float(f"{float(local(expression)):.15g}") == float(f"{float(measured):.15g}")


class TestIteration238Hunt149(unittest.TestCase):
    # Family A: a Double MOD for a CURRENCY dividend over a Double divisor
    def test_family_a_mod_currency_dividend_double_divisor(self):
        self.assertTrue(_same_15("MOD(CURRENCY(-7.65432),0.7)", "0.0456999999999994"))
        self.assertTrue(_same_15("MOD(CURRENCY(7.65432),-0.7)", "-0.0456999999999994"))
        self.assertTrue(_same_15("MOD(CURRENCY(-1.23456),0.1)", "0.0654000000000002"))
        self.assertTrue(_same_15("MOD(CURRENCY(123456.7891),0.13)", "0.0790999999902878"))
        self.assertTrue(_same_15("MOD(CURRENCY(7.65432),0.7)", "0.654300000000001"))
        self.assertTrue(_same_15("MOD(CURRENCY(-10.1),0.2)", "0.100000000000001"))
        self.assertEqual(local('MOD(CURRENCY(-7.65432),0.7)&"z"'), "4.56999999999994E-02z")

    def test_family_a_mod_currency_stays_currency(self):
        self.assertEqual(Decimal(local("MOD(CURRENCY(-7.65432),CURRENCY(0.7))")), Decimal("0.0457"))
        self.assertEqual(Decimal(local("MOD(CURRENCY(-7.65432),2)")), Decimal("0.3457"))
        self.assertEqual(Decimal(local("MOD(CURRENCY(5.5),2.5)")), Decimal("0.5"))
        self.assertEqual(Decimal(local("MOD(CURRENCY(-5.5),2.5)")), Decimal("2"))
        self.assertTrue(_same_15("MOD(0.7,CURRENCY(0.3))", "0.1"))
        self.assertTrue(_same_15("MOD(CURRENCY(7.65432),0.3)", "0.1543"))

    # Family B: a CURRENCY median of two values, midpoint rounded toward +infinity
    def test_family_b_medianx_currency_midpoint(self):
        self.assertEqual(Decimal(local("MEDIANX({1,2},CURRENCY(-7.65432)*[Value])")), Decimal("-11.4814"))
        self.assertEqual(Decimal(local("MEDIANX({1,2},CURRENCY(7.65432)*[Value])")), Decimal("11.4815"))
        self.assertEqual(Decimal(local("MEDIANX({1,2},CURRENCY(1.00005)*[Value])")), Decimal("1.5002"))
        self.assertEqual(Decimal(local("MEDIANX({1,2},CURRENCY(-1.00005)*[Value])")), Decimal("-1.5001"))
        self.assertEqual(Decimal(local("MEDIANX({1,2},CURRENCY(0.0001)*[Value])")), Decimal("0.0002"))
        self.assertEqual(Decimal(local("MEDIANX({1,2},CURRENCY(-0.0001)*[Value])")), Decimal("-0.0001"))
        self.assertEqual(Decimal(local("MEDIANX({1,2},CURRENCY(0.0003)*[Value])")), Decimal("0.0005"))
        self.assertEqual(Decimal(local("MEDIANX({1,2},CURRENCY(-0.0003)*[Value])")), Decimal("-0.0004"))
        self.assertEqual(local('MEDIANX({1,2},CURRENCY(-7.65432)*[Value])&"z"'), "-11.4814z")

    def test_family_b_averagex_keeps_half_away(self):
        self.assertEqual(Decimal(local("AVERAGEX({1,2},CURRENCY(-7.65432)*[Value])")), Decimal("-11.4815"))

    def test_family_b_medianx_double_body_unchanged(self):
        # a body that is a Double (LOG of a CURRENCY) is not rounded to four places
        self.assertTrue(_same_15("MEDIANX(Facts,LOG(CURRENCY(2)))", "0.301029995663981"))
        self.assertTrue(_same_15("MEDIANX(Facts,LOG(DATE(2020,1,1),CURRENCY(2)))", "15.4196639737345"))


if __name__ == "__main__":
    unittest.main()
