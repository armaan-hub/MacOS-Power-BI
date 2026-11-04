"""Iteration 137: Task 47 date-variance-37.

Tests for:
- Part A: VARX / STDEVX over a date body is computed in double arithmetic (sum of squares less the square of the mean for VAR.P;
  sum of squares less the square of the sum over n, divided by n - 1, for VAR.S), and refused when the body divides.
- Part B: VARX / STDEVX of one repeated fraction is the same double arithmetic (repeated rows add as count x value).
"""
import unittest
from decimal import Decimal

from analytics_studio import dax_math
from tools import dax_oracle_diff as dax


class DateVariance37Tests(unittest.TestCase):
    def test_double_statistic_date_rows(self) -> None:
        # the six serials of 2020-01-01 plus Quantity, in row order: VAR.P is the double 2.91666674613953 printed to 15 digits
        values = [Decimal(43831), Decimal(43832), Decimal(43833), Decimal(43834), Decimal(43835), Decimal(43836)]
        self.assertEqual("2.91666674613953", f"{float(dax_math.double_statistic('VARX.P', values)):.15G}")

    def test_double_statistic_repeated_fraction(self) -> None:
        # three rows of one repeated fraction: VAR.S is 2^-47, STDEV.S is its square root; VAR.P is 0
        values = [Decimal("6.3")] * 3
        self.assertEqual(Decimal("7.105427357601002E-15"), dax_math.double_statistic("VARX.S", values))
        self.assertEqual(Decimal(0), dax_math.double_statistic("VARX.P", values))
        self.assertEqual("8.42936970217881E-08", f"{float(dax_math.double_statistic('STDEVX.S', values)):.15G}")

    def test_part_a_date_bodies_match_power_bi(self) -> None:
        self.assertTrue(dax.same("2.91666674613953", dax.local("VARX.P(Facts,DATE(2020,1,1)+Facts[Quantity])")))
        self.assertTrue(dax.same("0.182291686534882", dax.local("VARX.P(Facts,DATE(1950,1,1)+0.5+Facts[Quantity]*0.25)")))
        self.assertTrue(dax.same("2.91666666666652", dax.local("VARX.P(Facts,DATE(1900,3,1)+Facts[Quantity])")))
        self.assertTrue(dax.same("0.666666746139526", dax.local("VARX.P({1,2,3},DATE(2020,1,1)+[Value])")))
        self.assertTrue(dax.same("4", dax.local("VARX.P({5,9},DATE(2000,1,1)+[Value])")))

    def test_part_a_conditional_date_body(self) -> None:
        self.assertTrue(dax.same(
            "2.91666674613953",
            dax.local("IF(COUNTROWS(Facts)>3,VARX.P(Facts,DATE(2020,1,1)+Facts[Quantity]),\"a\")"),
        ))

    def test_part_a_division_in_date_body_stays_refused(self) -> None:
        # Power BI divides in doubles; the decimal division differs in the last digit, so the row keeps refusing
        self.assertTrue(dax.local("VARX.P(Facts,DATE(1899,12,31)+Facts[Quantity]/3)").startswith("LOCAL-REJECT"))
        self.assertTrue(dax.local("STDEVX.P({5,9},DATE(1899,12,31)+[Value]/3)").startswith("LOCAL-REJECT"))

    def test_part_b_repeated_fraction_matches_power_bi(self) -> None:
        self.assertTrue(dax.same(
            "8.42936970217881E-08",
            dax.local('STDEVX.S(CALCULATETABLE(Facts,Facts[Region]="East"),AVERAGE(Facts[Sales]))'),
        ))
        self.assertTrue(dax.same(
            "7.105427357601E-15",
            dax.local('VARX.S(CALCULATETABLE(Facts,Facts[Region]="East"),AVERAGE(Facts[Sales]))'),
        ))
        self.assertTrue(dax.same(
            "0",
            dax.local('VARX.P(CALCULATETABLE(Facts,Facts[Region]="East"),AVERAGE(Facts[Sales]))'),
        ))


if __name__ == "__main__":
    unittest.main()
