"""Task 163 (dax-hunt-163): fresh-probe wrong answers.

Family A: INFO.CULTURES and INFO.ANNOTATIONS hold one row in Power BI (measured COUNTROWS 1); the local engine has no such row,
so both are refused rather than answered with an empty table.
Family B (not changed): LN of an integer is a 28-digit Decimal in the engine; a double LN breaks the locked
EXP(LN(3))/3-1 answer (0 in Power BI), so LN(COUNTROWS(Facts)) stays a known wrong row (1.79175946922805 in Power BI).
Family D: FLOOR, CEILING and MROUND Double results (and FIXED of a number from 1E15 to 2^53) are shown at 15 significant digits,
half away from zero, whole or not; an Int64 result from 2^53 up stays exact.
Values copied from the measured Power BI answers.
"""

import unittest
from decimal import Decimal

from tools.dax_oracle_diff import local


def _fifteen(text: str) -> str:
    return format(float(text), ".15g")


class TestIteration251Hunt163(unittest.TestCase):
    def test_info_cultures_and_annotations_are_refused(self):
        # Power BI: COUNTROWS of each is 1 (measured); the local engine refuses instead of an empty table
        for expression in (
            "COUNTROWS(INFO.CULTURES())",
            "COUNTROWS(INFO.ANNOTATIONS())",
            'IFERROR(COUNTROWS(INFO.CULTURES()),"E")',
        ):
            self.assertTrue(local(expression).startswith("LOCAL-REJECT"), expression)

    def test_info_empty_tables_measured_as_blank_stay_blank(self):
        # Power BI answers BLANK for these empty tables (measured), so the empty-table answer is kept
        self.assertEqual(local("COUNTROWS(INFO.VARIATIONS())"), "BLANK")
        self.assertEqual(local("COUNTROWS(INFO.CALCULATIONGROUPS())"), "BLANK")

    def test_ln_still_refuses_zero_and_negative(self):
        self.assertTrue(local("LN(0)").startswith("LOCAL-REJECT"))
        self.assertTrue(local("LN(-1)").startswith("LOCAL-REJECT"))

    def test_floor_beyond_1e15_non_whole_is_shown_at_fifteen_digits(self):
        # Power BI -1,000,000,000,000,000.000 (measured); the 16-digit double is shown at 15 significant digits
        self.assertEqual(local('IFERROR(FIXED(FLOOR(EVEN(-1E15),"1.5"),3),"E")'), "-1,000,000,000,000,000.000")
        # Power BI 2.7E+15z and 2.25179981368526E+15z (measured)
        self.assertEqual(local('FLOOR(2.7E15+0.25,3.5)&"z"'), "2.7E+15z")
        self.assertEqual(local('FLOOR(2^51+3+7,0.25)&"z"'), "2.25179981368526E+15z")

    def test_fifteen_digit_floor_ceiling_mround_results(self):
        # Power BI 15-significant-digit results, half away from zero (measured 2026-11-15, t168 probes)
        self.assertEqual(local("FIXED(FLOOR(2.5E15+0.25,1.5),3)"), "2,500,000,000,000,010.000")
        self.assertEqual(local("FIXED(FLOOR(4.5E15,3.5),3)"), "4,500,000,000,000,020.000")
        self.assertEqual(local("FIXED(FLOOR(1E15+0.3,7),3)"), "1,000,000,000,000,000.000")
        self.assertEqual(local("FIXED(MROUND(9.99E14+0.5,0.25),3)"), "999,000,000,000,001.000")
        self.assertEqual(local("FIXED(MROUND(1E15+0.3,0.1),3)"), "1,000,000,000,000,000.000")

    def test_ceiling_beyond_1e15_on_a_whole_number_stays_exact(self):
        # Power BI -1000000000000000 (measured, a 15-digit result)
        self.assertEqual(local("CEILING(-1E15,1)"), "-1000000000000000")
        self.assertEqual(local("FLOOR(-1E15,1)"), "-1000000000000000")


if __name__ == "__main__":
    unittest.main()
