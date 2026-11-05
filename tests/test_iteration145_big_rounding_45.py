"""Iteration 145: Task 55 big-rounding-45.

FLOOR and CEILING of a power result from 1E15 to 2^53 cut x/significance to 15 digits, then floor or ceil, then multiply by the significance in doubles.
MROUND and CONVERT, INT and QUOTIENT read the power as its double; a whole result from 2^52 to 2^53 that is odd goes up by one. The expected texts are
Power BI answers measured on the saved spec tools/parity/task55_big_rounding2_spec.json (220 rows, 0 wrong).
"""
import unittest

from tools import dax_oracle_diff as dax


class BigRoundingFortyFiveTests(unittest.TestCase):
    def assert_power_bi(self, expression: str, expected: str) -> None:
        self.assertTrue(dax.same(expected, dax.local(expression)), f"{expression}: local {dax.local(expression)} Power BI {expected}")

    def test_floor_and_ceiling_cut_quotient_to_15_digits(self) -> None:
        self.assert_power_bi('FLOOR(2^52,3)&"z"', "4503599627370510z")
        self.assert_power_bi('FLOOR(2^52,7)&"z"', "4503599627370494z")
        self.assert_power_bi('CEILING(2^52+0.25,7)&"z"', "4503599627370494z")
        self.assert_power_bi('CEILING(6^20,3)&"z"', "3656158440062970z")

    def test_floor_and_ceiling_non_integer_significance_is_a_double(self) -> None:
        self.assert_power_bi('FLOOR(7*2^50+0.5,1.5)&"z"', "7.88129934789837E+15z")
        self.assert_power_bi('CEILING(7*2^50+0.5,0.5)&"z"', "7.88129934789835E+15z")

    def test_mround_odd_product_from_2_52_goes_up(self) -> None:
        self.assert_power_bi('MROUND(4.6E15,3)&"z"', "4600000000000000z")
        self.assert_power_bi('MROUND(4.9E15,13)&"z"', "4900000000000002z")
        self.assert_power_bi('MROUND(2^52,3)&"z"', "4503599627370495z")
        self.assert_power_bi('MROUND(4503599627370497,13)&"z"', "4503599627370493z")

    def test_convert_and_int_of_power_band(self) -> None:
        self.assert_power_bi('(CONVERT(2^52+1,INTEGER))&"z"', "4503599627370498z")
        self.assert_power_bi('(CONVERT(2^52-0.5,INTEGER))&"z"', "4503599627370496z")
        self.assert_power_bi('(CONVERT(2^51+0.5,INTEGER))&"z"', "2251799813685249z")
        self.assert_power_bi('INT(2^52-0.5)&"z"', "4503599627370495z")

    def test_quotient_of_power_band(self) -> None:
        self.assert_power_bi('QUOTIENT(2^52+1,1)&"z"', "4503599627370498z")
        self.assert_power_bi('QUOTIENT(2^52+1,1.5)&"z"', "3002399751580331z")
        self.assert_power_bi('QUOTIENT(7*2^50+0.5,3)&"z"', "2627099782632789z")
        self.assert_power_bi('QUOTIENT(POWER(7,14)*POWER(2,14)+1,1.5)&"z"', "7408004550372012z")
        self.assert_power_bi('QUOTIENT(2^52*3+1,2)&"z"', "6755399441055744z")

    def test_errors_are_not_raised(self) -> None:
        self.assert_power_bi('ISERROR(MROUND(2^52,3))', "False")


if __name__ == "__main__":
    unittest.main()
