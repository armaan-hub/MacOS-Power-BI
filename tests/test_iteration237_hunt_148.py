"""Task 148 (dax-hunt-148): fresh Power BI hunt, batch 6. Exact assertions per family, values copied from the measured Power BI answers.

Family A: PMT, IPMT, PPMT, FV, PV, CUMIPMT, CUMPRINC, SLN, SYD, DB, DDB and VDB return a CURRENCY (4 decimal places, rounded half
away from zero) when an amount argument is CURRENCY; the result then behaves as a Currency (text, FORMAT, arithmetic).
Family B: SIN, COS, TAN and COT are refused at an argument within 4 ulp of a nonzero whole multiple of pi/4.
Family C: SIN, COS, TAN and COT are refused above pi/4 when the tiny sine or cosine would be below |x| * 1E-4.
Family D: a date-set function (ENDOFMONTH, FIRSTDATE, ...) over a column made by SELECTCOLUMNS is an error; the CALENDAR rows
that Power BI answers stay as they were.
Known limits left alone (still differ in the spec): COT(31.5), T.DIST.2T, T.INV.2T, POISSON.DIST, large-argument SIN / COS,
PMT with plain (non-currency) arguments in the 15th digit.
"""

import math
import unittest
from decimal import Decimal

from tools.dax_oracle_diff import local


def _same_15(expression: str, measured: str) -> bool:
    """The local answer and the measured Power BI answer agree to 15 significant digits."""
    return float(f"{float(local(expression)):.15g}") == float(f"{float(measured):.15g}")


def _refused(expression: str) -> bool:
    return local(expression).startswith("LOCAL-REJECT")


class TestIteration237Hunt148(unittest.TestCase):
    # Family A: the Currency result, 4 decimal places
    def test_family_a_pmt_pv_fv_currency_amount(self):
        self.assertEqual(Decimal(local("PMT(0.05,2,CURRENCY(1.23456))")), Decimal("-0.664"))
        self.assertEqual(Decimal(local("PMT(0.05,2,CURRENCY(0.00005))")), Decimal("-0.0001"))
        self.assertEqual(Decimal(local("PMT(0.05,2,CURRENCY(0.00004))")), Decimal("0"))
        self.assertEqual(Decimal(local("PMT(0.05,2,100,CURRENCY(5))")), Decimal("-56.2195"))
        self.assertEqual(Decimal(local("FV(0.05,2,-1,CURRENCY(1.23456))")), Decimal("0.6889"))
        self.assertEqual(Decimal(local("PV(0.05,2,0,CURRENCY(1.23456))")), Decimal("-1.1198"))
        self.assertEqual(Decimal(local("PMT(0.05,2,CURRENCY(1.23456),CURRENCY(1.23456))")), Decimal("-1.2662"))
        self.assertEqual(Decimal(local("PV(0.05,2,-1,CURRENCY(1.23456))")), Decimal("0.7396"))
        self.assertEqual(Decimal(local("FV(0.05,2,CURRENCY(1.23456),CURRENCY(1.23456))")), Decimal("-3.8921"))

    def test_family_a_interest_and_cumulative_currency_amount(self):
        self.assertEqual(Decimal(local("IPMT(0.05,2,2,CURRENCY(1.23456))")), Decimal("-0.0316"))
        self.assertEqual(Decimal(local("PPMT(0.05,2,2,CURRENCY(1.23456))")), Decimal("-0.6324"))
        self.assertEqual(Decimal(local("PPMT(0.05,1,2,100,CURRENCY(1.23456))")), Decimal("-49.3827"))
        self.assertEqual(Decimal(local("CUMIPMT(0.05,2,CURRENCY(100),1,2,0)")), Decimal("-7.561"))
        self.assertEqual(Decimal(local("CUMIPMT(0.05,3,CURRENCY(100.12345),1,3,1)")), Decimal("-4.9228"))

    def test_family_a_straight_line_and_declining_balance_currency_amount(self):
        self.assertEqual(Decimal(local("SLN(1000,CURRENCY(100.12345),3)")), Decimal("299.9588"))
        self.assertEqual(Decimal(local("SYD(CURRENCY(1000.12345),100,3,1)")), Decimal("450.0618"))
        self.assertEqual(Decimal(local("DB(CURRENCY(1000.12345),100,3,1)")), Decimal("536.0662"))
        self.assertEqual(Decimal(local("DDB(1000,CURRENCY(100.12345),3,1)")), Decimal("666.6667"))
        self.assertEqual(Decimal(local("VDB(1000,CURRENCY(100.12345),3,0,1)")), Decimal("666.6667"))
        self.assertEqual(Decimal(local("SLN(CURRENCY(1000.12345),CURRENCY(1.23456),3)")), Decimal("332.963"))
        self.assertEqual(Decimal(local("SLN(CURRENCY(1000.12345),100,CURRENCY(3))")), Decimal("300.0412"))
        self.assertEqual(Decimal(local("DDB(CURRENCY(1000.12345),100,3,2,1.5)")), Decimal("250.0309"))
        self.assertEqual(Decimal(local("VDB(CURRENCY(1000.12345),100,3,1,2,1.5,TRUE())")), Decimal("250.0309"))

    def test_family_a_not_currency_without_a_currency_amount(self):
        self.assertTrue(_same_15("PMT(CURRENCY(0.05),2,100)", "-53.780487804878"))
        self.assertTrue(_same_15("SLN(1000.12345,100,CURRENCY(3))", "300.04115"))

    def test_family_a_currency_result_behaves_as_currency(self):
        self.assertEqual(local('PMT(0.05,2,CURRENCY(1.23456))&"z"'), "-0.664z")
        self.assertEqual(local('FORMAT(PMT(0.05,2,CURRENCY(1.23456)),"0.000000")'), "-0.664000")
        self.assertEqual(Decimal(local("PMT(0.05,2,CURRENCY(1.23456))*3")), Decimal("-1.992"))
        self.assertTrue(_same_15("PMT(0.05,2,CURRENCY(1.23456))+0.00001", "-0.66399"))
        self.assertTrue(_same_15("PMT(0.05,2,CURRENCY(1.23456))*1", "-0.664"))
        self.assertTrue(_same_15("PMT(0.05,2,CURRENCY(-922337203685477))", "496037447347921.1008"))

    def test_family_a_currency_conversion_is_double_times_10000(self):
        # Power BI: n = round_half_away(double result * 10000.0), shown as n / 10000 with 4 places
        self.assertEqual(local("PMT(0.05,2,CURRENCY(-922337203685477))"), "496037447347921.1008")
        self.assertEqual(local("FV(0.1,3,CURRENCY(1E14))"), "-331000000000000.3584")
        self.assertEqual(Decimal(local("PV(0.05,2,CURRENCY(1E14))")), Decimal("-185941043083900.288"))
        self.assertEqual(Decimal(local("SYD(1000,CURRENCY(100.12345),3,1)")), Decimal("449.9383"))

    # Family B: SIN, COS and TAN at an exact multiple of the double pi/4 take the engine's octant value (TAN's is a division by zero)
    def test_family_b_trig_at_exact_quarter_pi_multiples_follows_the_octant(self):
        self.assertTrue(_same_15("SIN(PI())", "-0.707106781186548"))
        self.assertTrue(_same_15("SIN(4.71238898038469)", "-0.707106781186548"))
        self.assertTrue(_same_15("SIN(-4*PI()/4)", "0.707106781186548"))
        self.assertTrue(_same_15("SIN(9*PI()/4)", "1"))
        self.assertTrue(_same_15("SIN(3*PI()/4)", "0"))
        self.assertTrue(_same_15("COS(4*PI()/4)", "-0.707106781186548"))
        self.assertTrue(_refused("COS(13*PI()/4)"))  # not an exact double multiple (2 ulps or more off), refused
        self.assertTrue(_same_15("COS(14*PI()/4)", "0.707106781186548"))
        self.assertTrue(_same_15("TAN(-4*PI()/4)", "-1"))
        self.assertTrue(_same_15("TAN(3*PI()/4)", "0"))
        self.assertTrue(_same_15("TAN(14*PI()/4)", "-1"))
        self.assertTrue(_same_15("TAN(0.785398163397448)", "0.999999999999999"))
        self.assertEqual(local("IFERROR(TAN(PI()/2),\"E\")"), "E")
        self.assertEqual(local("IFERROR(TAN(ACOS(0)),\"E\")"), "E")
        self.assertTrue(_refused("TAN(PI()/4)"))
        self.assertTrue(_refused("TAN(ACOS(0))"))

    def test_family_b_trig_near_but_not_at_a_multiple_is_refused(self):
        # one ulp beyond the double 3 * pi/4: within 2 ulps of the true multiple, not an exact double multiple
        x = math.nextafter(3 * math.pi / 4, 10)
        self.assertTrue(_refused(f"SIN({x!r})"))
        self.assertTrue(_refused(f"COS({x!r})"))

    def test_family_c_trig_with_tiny_result_refused(self):
        for expression in [
            "COS(1.5707963267949)", "COS(1.57079632679)", "SIN(3.14159265358979)", "SIN(6.28318530717959)",
            "SIN(3.1415926535898)", "TAN(1.5707963267949)",
        ]:
            with self.subTest(expression=expression):
                self.assertTrue(_refused(expression))

    def test_family_b_c_literals_further_from_a_multiple_keep_their_answers(self):
        self.assertTrue(_same_15("SIN(0.7853981633974)", "0.707106781186513"))

    # Family D: a date set over a column made by SELECTCOLUMNS is an error; CALENDAR rows keep their answers
    def test_family_d_date_set_over_selectcolumns_is_an_error(self):
        self.assertTrue(_refused('COUNTROWS(ENDOFMONTH(SELECTCOLUMNS(CALENDAR(DATE(2020,1,1),DATE(2020,3,1)),"d",[Date])))'))

    def test_family_d_calendar_rows_that_power_bi_answers_stay(self):
        self.assertEqual(local("IFERROR(1,FIRSTDATE(CALENDAR(DATE(2020,1,1),DATE(2020,3,1))))"), "1")
        self.assertEqual(local("IF(TRUE(),1,ENDOFMONTH(CALENDAR(DATE(2020,1,1),DATE(2020,3,1))))"), "1")


if __name__ == "__main__":
    unittest.main()
