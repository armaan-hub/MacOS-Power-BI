"""Task 165 (dax-hunt-165): fresh Power BI hunt, batch 22. Assertions copied from the measured Power BI answers (2026-11-15).

Families done here: A (a date operand of * or / gives a Double; PV and FV with a fractional nper use the correctly rounded power),
C (ACOSH is LN(x+SQRT(x*x-1)) in doubles), D (BETA.INV at the upper bound is the bound).
Not done: B (CONVERT(-1E15,DATETIME) inside IFERROR is a query error, but the locked Task 145 answer for the plain CONVERT is 01/01/0100, and
CONVERT(-1E200,DATETIME) is locked as 01/01/0100 too: the two cannot both be met by a general rule without more probes), E (last-digit statistics).
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


class TestIteration253Hunt165(unittest.TestCase):
    # Family A: * and / with a date operand are Doubles (no 28-digit Decimal quotient)
    def test_family_a_average_over_date_is_double(self):
        self.assertTrue(same15(local('IFERROR(AVERAGE(Facts[Quantity])/(DATE(2020,2,29)),"E")'), "5.69605832763727E-05"))

    def test_family_a_date_times_and_over_numbers_are_doubles(self):
        self.assertTrue(same15(local("DATE(2020,1,1)/3"), "14610.3333333333"))
        self.assertTrue(same15(local("DATE(2020,1,1)*(1/3)"), "14610.3333333333"))
        self.assertTrue(same15(local("DATE(2020,1,1)*(TIME(1,0,0))"), "1826.29166666667"))

    def test_family_a_date_plus_stays_a_date(self):
        self.assertEqual(local("DATE(2020,1,1)+0.1"), "01/01/2020 02:24:00")

    # Family A: PV and FV with a fractional nper use the correctly rounded double power
    def test_family_a_pv_fractional_nper(self):
        self.assertTrue(same15(local("PV(1,0.5,1)"), "-0.292893218813453"))
        self.assertTrue(same15(local("PV(-0.5,2.5,-1000)"), "9313.70849898476"))

    def test_family_a_fv_fractional_nper(self):
        self.assertTrue(same15(local("FV(-0.5,2.5,-1000)"), "1646.44660940673"))
        self.assertTrue(same15(local("FV(1,0.5,1)"), "-0.414213562373095"))

    def test_family_a_pv_whole_nper_unchanged(self):
        self.assertTrue(same15(local("PV(1E-8,360,-1000)"), "359999.346407639"))

    # Family C: ACOSH in doubles, LN(x+SQRT(x*x-1))
    def test_family_c_acosh_of_coth(self):
        self.assertTrue(same15(local("POWER(ACOSH(COTH(7)),1)"), "0.00182376443662588"))

    def test_family_c_acosh_values(self):
        self.assertEqual(local("ACOSH(1)"), "0")
        self.assertTrue(same15(local("ACOSH(2.5)"), "1.56679923697241"))
        self.assertTrue(same15(local("ACOSH(10)"), "2.99322284612638"))

    def test_family_c_acosh_refusals_stay(self):
        self.assertTrue(local("ACOSH(0.5)").startswith("LOCAL-"))
        self.assertEqual(local("ISERROR(ACOSH(1.35E154))"), "True")
        self.assertEqual(local("ISERROR(ACOSH(1.3E154))"), "False")

    # Family D: BETA.INV at the upper bound of the solver is the bound
    def test_family_d_beta_inv_upper_bound(self):
        self.assertTrue(same15(local("BETA.INV(0.25,0.1,1E-5)"), "1"))
        self.assertEqual(local("BETA.INV(1-1E-10,0.1,0.1)"), "1")


if __name__ == "__main__":
    unittest.main()
