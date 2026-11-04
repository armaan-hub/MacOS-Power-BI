"""Iteration 138: Task 48 old-times-38.

Date/time values before December 30, 1899 (OLE Automation serials below zero):
- Part A: the date is the serial truncated toward zero and the time of day is the absolute value of the fraction, shown with
  FORMAT, the text of a date and the date parts (YEAR, MONTH, DAY, WEEKDAY), settled away from midnight.
- Part B: CONCATENATEX over such values.
- Part C: HOUR, MINUTE and SECOND round the time of day up to the next whole second; an exact half second is a tie that stays refused.
"""
import unittest

from tools import dax_oracle_diff as dax


class OldTimes38Tests(unittest.TestCase):
    def assertRefused(self, expression: str) -> None:
        self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT:"), f"{expression} -> {dax.local(expression)}")

    def test_time_of_day_before_day_zero_uses_absolute_fraction(self) -> None:
        # (-1)+TIME(6,0,0) is -0.75: the date is day zero and the time of day is 6:00 PM
        self.assertEqual("6:00:00 PMz", dax.local('((-1)+(TIME(6,0,0)))&"z"'))
        self.assertEqual("1899-12-30 18:00:00", dax.local('FORMAT((-1)+(TIME(6,0,0)),"yyyy-mm-dd hh:nn:ss")'))
        self.assertEqual("1700-06-16 00:00:01", dax.local('FORMAT(DATE(1700,6,15)+TIME(23,59,59),"yyyy-mm-dd hh:nn:ss")'))
        self.assertEqual("1899-12-28 00:00:01", dax.local('FORMAT(-3+0.999989,"yyyy-mm-dd hh:nn:ss")'))
        self.assertEqual("1899-09-22 23:59:59", dax.local('FORMAT(-100+0.00001,"yyyy-mm-dd hh:nn:ss")'))

    def test_fraction_rounds_to_nearest_second_off_the_tie(self) -> None:
        self.assertEqual("1700-06-16 00:00:01", dax.local('FORMAT(DATE(1700,6,15)+0.999989,"yyyy-mm-dd hh:nn:ss")'))
        self.assertEqual("1899-09-22 23:59:59", dax.local('FORMAT(-100+0.0000115,"yyyy-mm-dd hh:nn:ss")'))

    def test_date_parts_settled_away_from_midnight(self) -> None:
        self.assertEqual("1850", dax.local("YEAR(DATE(1850,7,4)+1-1/86400)"))
        self.assertEqual("0", dax.local("HOUR(DATE(1800,1,1)+0.999989)"))
        self.assertEqual("0", dax.local("MINUTE(DATE(1850,7,4)+0.999989)"))
        self.assertEqual("5", dax.local("WEEKDAY(DATE(1800,1,1)+TIME(0,0,1))"))

    def test_hour_minute_second_round_the_time_up(self) -> None:
        self.assertEqual("27", dax.local("SECOND(-3+0.999)"))
        self.assertEqual("0", dax.local("SECOND(-100+0.00001)"))
        self.assertEqual("0", dax.local("HOUR(-100+0.00001)"))
        self.assertEqual("0", dax.local("MINUTE(-3+0.00001)"))

    def test_concatenatex_over_time_before_day_zero(self) -> None:
        self.assertEqual("6:00:00 PM", dax.local("CONCATENATEX({1},(TIME(6,0,0))-(1))"))

    def test_exact_half_second_before_day_zero_stays_refused(self) -> None:
        for expression in (
            '(DATE(1800,1,1)+1.5/86400)&"z"',
            '(DATE(1850,7,4)+0.5/86400)&"z"',
            'FORMAT(DATE(1850,7,4)+0.5/86400,"yyyy-mm-dd hh:nn:ss")',
            'FORMAT(-0.5/86400,"yyyy-mm-dd hh:nn:ss")',
        ):
            self.assertRefused(expression)

    def test_date_parts_within_a_second_of_midnight_stay_refused(self) -> None:
        self.assertRefused("DAY(-100+0.99999)")
        self.assertRefused("WEEKDAY(-3+0.00001)")

    def test_date_part_on_an_exact_half_second_keeps_its_date(self) -> None:
        # the date does not depend on the rounding of the time of day: the tie is refused only where the time is shown
        self.assertEqual("2", dax.local("DAY(DATE(1800,1,1)+1.5/86400)"))

    def test_fraction_before_1700_keeps_its_measured_rule(self) -> None:
        # the rounding is measured from 1700 onward: a fraction of a second before it keeps the earlier 1/300 s rule (saved answers of 1661 and 1619)
        self.assertEqual("04/22/1661 00:01:26", dax.local("CONVERT((0.999)-(DATE(2019,5,5))*2,DATETIME)"))
        self.assertEqual("12/23/1619 06:07:46", dax.local('IFERROR(CURRENCY(-3.33335)*DATE(2020,1,1)+DATE(2020,1,1),"e")'))
        self.assertRefused('FORMAT(DATE(1600,1,1)+0.5/86400,"yyyy-mm-dd hh:nn:ss")')
        self.assertRefused("SECOND(DATE(1600,1,1)+0.25/86400)")


if __name__ == "__main__":
    unittest.main()
