"""Task 171 (dax-hunt-171): a number converted to DATETIME keeps its time of day in 1/300 s ticks.

Power BI holds the time of day of a DATETIME in ticks of 1/300 s, so CONVERT(number, DATETIME) rounds the time of day to the
nearest tick (the day is the floor, the recombination is in double arithmetic). VALUE of a datetime reads its text, so it
gives whole seconds. Values copied from the measured Power BI answers.
"""

import unittest

from tools.dax_oracle_diff import local


def _fifteen(text: str) -> str:
    return format(float(text), ".15g")


class TestIteration259Hunt171(unittest.TestCase):
    def test_convert_to_datetime_rounds_the_time_of_day_to_ticks(self):
        # Power BI 9.99228395061728E-06 (1E-5 is 0.864 s, 0.2592 ticks per millisecond, rounded to 259 ticks)
        self.assertEqual(_fifteen(local("CONVERT(CONVERT(1E-5,DATETIME),DOUBLE)")), _fifteen("9.99228395061728E-06"))
        self.assertEqual(_fifteen(local("CONVERT(1E-5,DATETIME)*1")), _fifteen("9.99228395061728E-06"))
        # Power BI 0.500009992283951
        self.assertEqual(_fifteen(local("CONVERT(CONVERT(0.5+1E-5,DATETIME),DOUBLE)")), _fifteen("0.500009992283951"))
        # Power BI 45000.1234567901
        self.assertEqual(_fifteen(local("CONVERT(CONVERT(45000.123456789,DATETIME),DOUBLE)")), _fifteen("45000.1234567901"))

    def test_convert_to_datetime_of_a_negative_number_is_recombined_in_doubles(self):
        # Power BI -9.99228395059948E-06 (last digits differ from +1E-5)
        self.assertEqual(_fifteen(local("CONVERT(CONVERT(-1E-5,DATETIME),DOUBLE)")), _fifteen("-9.99228395059948E-06"))
        # Power BI -0.500009992283951
        self.assertEqual(_fifteen(local("CONVERT(CONVERT(-0.5-1E-5,DATETIME),DOUBLE)")), _fifteen("-0.500009992283951"))

    def test_sub_tick_fractions_round_to_zero_or_one_tick(self):
        # 0.001 s and 0.48 tick round to 0 ticks
        self.assertEqual(_fifteen(local("CONVERT(CONVERT(1/86400000,DATETIME),DOUBLE)")), "0")
        self.assertEqual(_fifteen(local("CONVERT(CONVERT(0.0016/86400,DATETIME),DOUBLE)")), "0")
        # 0.51 tick rounds to 1 tick, 1.5 ticks to 2 ticks
        self.assertEqual(_fifteen(local("CONVERT(CONVERT(0.0017/86400,DATETIME),DOUBLE)")), _fifteen("3.85802469135802E-08"))
        self.assertEqual(_fifteen(local("CONVERT(CONVERT(0.005/86400,DATETIME),DOUBLE)")), _fifteen("7.71604938271605E-08"))

    def test_rounding_up_into_the_next_day(self):
        # Power BI 1 (0.99999999 rounds up into the next day)
        self.assertEqual(_fifteen(local("CONVERT(CONVERT(0.99999999,DATETIME),DOUBLE)")), "1")

    def test_other_fractions_are_rounded_to_ticks(self):
        # Power BI 0.123456790123457 and 2.00000100308642
        self.assertEqual(_fifteen(local("CONVERT(CONVERT(0.123456789,DATETIME),DOUBLE)")), _fifteen("0.123456790123457"))
        self.assertEqual(_fifteen(local("CONVERT(CONVERT(2.000001,DATETIME),DOUBLE)")), _fifteen("2.00000100308642"))

    def test_value_of_a_datetime_reads_its_text_in_whole_seconds(self):
        # Power BI 1.15740740740741E-05 (VALUE reads "12:00:01 AM", 1/86400)
        self.assertEqual(_fifteen(local("VALUE(CONVERT(1E-5,DATETIME))")), _fifteen("1.15740740740741E-05"))

    def test_date_arithmetic_is_unchanged(self):
        # Power BI 43831.0000099923 and 9.99228395061728E-06 (already exact on main)
        self.assertEqual(_fifteen(local("CONVERT(DATE(2020,1,1)+1E-5,DOUBLE)")), _fifteen("43831.0000099923"))
        self.assertEqual(_fifteen(local("CONVERT(TIME(0,0,0)+1E-5,DOUBLE)")), _fifteen("9.99228395061728E-06"))

    def test_constant_sources_are_rounded_to_the_tick_whatever_the_function(self):
        # Power BI 9.99228395061728E-06 for ABS, SQRT, DIVIDE, POWER and a VAR bound to a constant
        for expression in (
            "CONVERT(CONVERT(ABS(1E-5),DATETIME),DOUBLE)",
            "CONVERT(CONVERT(SQRT(1E-10),DATETIME),DOUBLE)",
            "CONVERT(CONVERT(DIVIDE(1,1E5),DATETIME),DOUBLE)",
            "CONVERT(CONVERT(POWER(10,-5),DATETIME),DOUBLE)",
            "VAR x=1E-5 RETURN CONVERT(CONVERT(x,DATETIME),DOUBLE)",
        ):
            self.assertEqual(_fifteen(local(expression)), _fifteen("9.99228395061728E-06"), expression)
        # Power BI 6.01851851851852E-06 (LEN of a constant text)
        self.assertEqual(_fifteen(local('CONVERT(CONVERT(LEN("abcdef")*1E-6,DATETIME),DOUBLE)')), _fifteen("6.01851851851852E-06"))

    def test_a_non_constant_sub_tick_value_is_refused_not_guessed(self):
        # Power BI rounds these in some query plans and not in others, so the local engine refuses them (no answer is given)
        for expression in (
            "CONVERT(CONVERT(COUNTROWS(Facts)*1E-5,DATETIME),DOUBLE)",
            "CONVERT(CONVERT(MAX(Facts[Quantity])*1E-6,DATETIME),DOUBLE)",
            "CONVERT(CONVERT(SUM(Facts[Quantity])*0+1E-5,DATETIME),DOUBLE)",
            "CONVERT(DATE(2020,1,1)+COUNTROWS(Facts)*1E-5,DOUBLE)",
            "CONVERT(DATE(2020,1,1)+SUM(Facts[Sales])/1E6,DOUBLE)",
            "CONVERT(TIME(0,0,0)+COUNTROWS(Facts)*1E-5,DOUBLE)",
        ):
            self.assertTrue(local(expression).startswith("LOCAL-REJECT"), expression)

    def test_a_value_already_on_a_tick_is_returned_as_it_is(self):
        # 0.25 is 6480000 ticks: no rounding changes it, so even a non-constant expression keeps it
        self.assertEqual(_fifteen(local("CONVERT(CONVERT(SUM(Facts[Sales])*0+0.25,DATETIME),DOUBLE)")), _fifteen("0.25"))
        self.assertEqual(_fifteen(local("CONVERT(CONVERT(0.5,DATETIME),DOUBLE)")), _fifteen("0.5"))

    def test_the_largest_datetime_clamps_to_the_last_tick_of_the_year_9999(self):
        # Power BI 2958465.99999996 (the last tick of 12/31/9999, not the next day)
        self.assertEqual(_fifteen(local("CONVERT(CONVERT(2958465.99999999,DATETIME),DOUBLE)")), _fifteen("2958465.99999996"))


if __name__ == "__main__":
    unittest.main()
