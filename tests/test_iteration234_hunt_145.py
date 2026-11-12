"""Task 145 (dax-hunt-145): fresh Power BI hunt, seed 4501. Exact assertions per family, values copied from the measured Power BI answers.

Families done here: A (MROUND and FLOOR/CEILING with fractional significance in doubles, both signs), B (a text number in DIVIDE is a Double),
C (CONVERT to DATETIME keeps its value; the display of a value before 01/01/0100 is 01/01/0100), E (FV keeps its exact double result).
Not done: D (INFO.* refusal conflicts with locked measured answers), F (XIRR last digits), and the COS/SINH/TAN/BETA.INV last-digit rows (out of scope).
"""

import unittest
from decimal import Context, Decimal

from tools.dax_oracle_diff import local

_FIFTEEN = Context(prec=15)


def same15(text: str, expected: str) -> bool:
    """Equal at 15 significant digits, with the same sign (the hunt's rule for numbers)."""
    if text.startswith("LOCAL-"):
        return False
    return _FIFTEEN.plus(Decimal(text)) == _FIFTEEN.plus(Decimal(expected)) and Decimal(text).is_signed() == Decimal(expected).is_signed()


class TestIteration234Hunt145(unittest.TestCase):
    # Family A: MROUND, FLOOR and CEILING with a fractional significance are worked in doubles
    def test_family_a_mround_fractional_positive(self):
        self.assertTrue(same15(local("MROUND(7,1E-5)-7"), "8.88178419700125E-16"))
        self.assertTrue(same15(local("MROUND(0.3,0.1)-0.3"), "5.55111512312578E-17"))
        self.assertTrue(same15(local("MROUND(3,0.1)-3"), "0"))
        self.assertTrue(same15(local("MROUND(1,0.1)-1"), "0"))
        self.assertEqual(local("ODD(MROUND(7,1E-5))"), "9")
        self.assertEqual(local("ODD(MROUND(3,0.1))"), "3")
        self.assertEqual(local("EVEN(MROUND(8,1E-5))"), "8")

    def test_family_a_negative_significance_both_negative(self):
        self.assertTrue(same15(local("FLOOR(-7,-1E-5)+7"), "-8.88178419700125E-16"))
        self.assertTrue(same15(local("CEILING(-7,-1E-5)+7"), "-8.88178419700125E-16"))
        self.assertTrue(same15(local("MROUND(-7,-1E-5)+7"), "-8.88178419700125E-16"))
        self.assertEqual(local("ODD(FLOOR(-7,-1E-5))"), "-9")
        self.assertTrue(same15(local("MROUND(-0.3,-0.1)+0.3"), "-5.55111512312578E-17"))

    def test_family_a_positive_floor_ceiling_unchanged(self):
        self.assertTrue(same15(local("FLOOR(7,1E-5)-7"), "8.88178419700125E-16"))
        self.assertTrue(same15(local("CEILING(0.3,0.1)-0.3"), "5.55111512312578E-17"))
        self.assertEqual(local("ODD(FLOOR(7,0.1))"), "7")

    # Family B: a text number in DIVIDE is a Double
    def test_family_b_text_numerator_in_divide_is_double(self):
        self.assertTrue(same15(local('DIVIDE("12",123456789.123)'), "9.72000007876797E-08"))
        self.assertTrue(same15(local('DIVIDE("12",123456789.123,2.5)'), "9.72000007876797E-08"))
        self.assertEqual(local('DIVIDE("12",3)'), "4")

    # Family C: CONVERT to DATETIME keeps the value; a display before 01/01/0100 shows 01/01/0100
    def test_family_c_convert_datetime_keeps_value(self):
        self.assertTrue(same15(local("CONVERT(CONVERT(-1E15,DATETIME),DOUBLE)"), "-1E+15"))
        self.assertTrue(same15(local("CONVERT(CONVERT(-1E6,DATETIME),DOUBLE)"), "-1000000"))
        self.assertTrue(same15(local("CONVERT(CONVERT(-700000,DATETIME),DOUBLE)"), "-700000"))
        self.assertTrue(same15(local("CONVERT(CONVERT(-657435,DATETIME),DOUBLE)"), "-657435"))
        self.assertTrue(same15(local("CONVERT(CONVERT(1E15,DATETIME),DOUBLE)"), "1E+15"))

    def test_family_c_display_before_year_100_is_0100(self):
        self.assertEqual(local("CONVERT(-1E6,DATETIME)"), "01/01/0100 00:00:00")
        self.assertEqual(local("CONVERT(-1E15,DATETIME)"), "01/01/0100 00:00:00")

    # Family E: FV keeps its exact double result
    def test_family_e_fv_exact_double(self):
        self.assertTrue(same15(local("FV(0.05,1,6)+6"), "-5.32907051820075E-15"))


if __name__ == "__main__":
    unittest.main()
