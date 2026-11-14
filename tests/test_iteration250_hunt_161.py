"""Task 161 (dax-hunt-161): financial function precision.

Power BI computes the financial functions in IEEE doubles and shows 15 significant digits. The local engine used to
return the 28-digit Decimal of a wrapper arithmetic (PPMT(...)*1, ABS(CUMIPMT(...))) and YIELDDISC / INTRATE computed
(price / investment minus 1) first, which cancels digits. Values copied from the measured Power BI answers.
"""

import unittest
from decimal import Decimal

from tools.dax_oracle_diff import local


def _fifteen(text: str) -> str:
    return format(float(text), ".15g")


class TestIteration250Hunt161(unittest.TestCase):
    def test_intrate_is_the_investment_gain_over_the_investment(self):
        # Power BI 0.05768 (the subtraction is taken before the division, so no cancellation digits)
        self.assertEqual(_fifteen(local("INTRATE(DATE(2008,2,15),DATE(2008,5,15),1000000,1014420,2)")), "0.05768")
        self.assertEqual(_fifteen(local("INTRATE(DATE(2008,2,15),DATE(2008,5,15),1000000,1014420,2)*1.1")), "0.063448")

    def test_yielddisc_matches_power_bi_to_fifteen_digits(self):
        # Power BI 0.0528225719868583
        self.assertEqual(_fifteen(local("YIELDDISC(DATE(2008,2,16),DATE(2008,3,1),99.795,100,2)")), "0.0528225719868583")

    def test_wrapper_of_a_double_is_computed_on_the_double(self):
        # PPMT is a Double: *1 keeps the exact binary value, it is not re-rounded to 28 digits
        plain = local("PPMT(0.05,2,10,7)")
        self.assertEqual(local("PPMT(0.05,2,10,7)*1"), plain)
        self.assertEqual(Decimal(plain), Decimal(float(plain)))
        self.assertEqual(local("ABS(PPMT(0.05,2,10,7))"), plain.lstrip("-"))

    def test_abs_of_a_cumulative_interest_keeps_the_double_digits(self):
        text = local("ABS(CUMIPMT(0.05,10,1000,1,2,0))")
        self.assertEqual(Decimal(text), Decimal(float(text)))
        self.assertEqual(text, local("CUMIPMT(0.05,10,1000,1,2,0)").lstrip("-"))

    def test_double_difference_of_a_future_value_keeps_cancellation_digits(self):
        # Power BI -5.32907051820075E-15 (Task 145 family E, still measured)
        self.assertEqual(_fifteen(local("FV(0.05,1,6)+6")), "-5.32907051820075e-15")

    def test_whole_number_future_value_stays_exact(self):
        self.assertEqual(local("FV(0,10,-5)*1"), "50")
        self.assertEqual(local("PV(0,10,-5)"), "50")


if __name__ == "__main__":
    unittest.main()
