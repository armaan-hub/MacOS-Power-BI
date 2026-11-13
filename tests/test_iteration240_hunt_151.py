"""Task 151 (dax-hunt-151): fresh Power BI hunt, batch 9. Exact assertions per family, values copied from the measured Power BI answers.

Family A: FLOOR, CEILING, MROUND and ISO.CEILING with a CURRENCY significance give a Currency: the multiple is converted from its double
(double times 10000, rounded half away from zero to ten-thousandths), and a numerator or result beyond the Currency range is the overflow error.
Family B: DIVIDE of a CURRENCY by a number whose Currency quotient is beyond the range is the overflow error, as "/" is; DIVIDE by zero is unchanged.
"""

import unittest

from tools.dax_oracle_diff import local

OVERFLOW = "LOCAL-REJECT:The result of a conversion or arithmetic operation is either too large or too small."


class TestIteration240Hunt151(unittest.TestCase):
    # Family A: the Currency multiple, converted from its double
    def test_family_a_currency_multiple_from_double(self):
        self.assertEqual(local("FLOOR(1E14,CURRENCY(1.23456))"), "99999999999999.2832")
        self.assertEqual(local("FLOOR(9.2E14,CURRENCY(1.23456))"), "919999999999999.8976")
        self.assertEqual(local("CEILING(9.2E14,CURRENCY(1.23456))"), "919999999999999.8976")
        self.assertEqual(local("MROUND(9.2E14,CURRENCY(1.23456))"), "919999999999999.8976")
        self.assertEqual(local("ISO.CEILING(9.2E14,CURRENCY(1.23456))"), "919999999999999.8976")
        self.assertEqual(local("FLOOR(-9.2E14,CURRENCY(1.5))"), "-919999999999999.4880")
        self.assertEqual(local("CEILING(9.2E14,CURRENCY(3))"), "920000000000001.0240")

    def test_family_a_int_numerator_at_the_edge(self):
        for function in ("FLOOR", "CEILING", "MROUND", "ISO.CEILING"):
            self.assertEqual(local(f"{function}(922337203685477,CURRENCY(1.23456))"), "922337203685477.4784", function)

    def test_family_a_numerator_beyond_currency_range_is_overflow(self):
        for expression in (
            "FLOOR(1E15,CURRENCY(1.23456))",
            "CEILING(1E15,CURRENCY(1.23456))",
            "MROUND(1E15,CURRENCY(1.23456))",
            "ISO.CEILING(1E15,CURRENCY(1.23456))",
            "FLOOR(-1E15,CURRENCY(1.23456))",
            "CEILING(-1E15,CURRENCY(1.23456))",
            "MROUND(-1E15,CURRENCY(1.23456))",
            "ISO.CEILING(-1E15,CURRENCY(1.23456))",
            "FLOOR(922337203685478,CURRENCY(1.23456))",
            "CEILING(922337203685478,CURRENCY(1.23456))",
            "MROUND(922337203685478,CURRENCY(1.23456))",
            "ISO.CEILING(922337203685478,CURRENCY(1.23456))",
            "FLOOR(-922337203685478,CURRENCY(1.23456))",
            "CEILING(-922337203685478,CURRENCY(1.23456))",
            "ISO.CEILING(-922337203685478,CURRENCY(1.23456))",
            "FLOOR(1E16,CURRENCY(1.23456))",
            "CEILING(1E16,CURRENCY(1.23456))",
            "MROUND(1E16,CURRENCY(1.23456))",
            "ISO.CEILING(1E16,CURRENCY(1.23456))",
        ):
            self.assertEqual(local(expression), OVERFLOW, expression)
        self.assertEqual(local('IFERROR(FLOOR(1E15,CURRENCY(1.23456)),"E")'), "E")
        self.assertEqual(local('IFERROR(FLOOR(922337203685478,CURRENCY(1.23456)),"E")'), "E")
        self.assertEqual(local('IFERROR(FLOOR(-1E15,CURRENCY(1.23456)),"E")'), "E")

    # Family B: a Currency quotient beyond the range is the overflow error
    def test_family_b_divide_currency_overflow(self):
        for expression in (
            "DIVIDE(CURRENCY(1.23456),1/1E15)",
            "DIVIDE(CURRENCY(1.23456),1/-1E15)",
            "DIVIDE(CURRENCY(1.23456),1/922337203685477)",
            "DIVIDE(CURRENCY(1.23456),1/922337203685478)",
            "DIVIDE(CURRENCY(1.23456),1/-922337203685478)",
            "DIVIDE(CURRENCY(1.23456),1/1E16)",
        ):
            self.assertEqual(local(expression), OVERFLOW, expression)

    def test_family_b_divide_by_zero_and_small_quotients_unchanged(self):
        self.assertEqual(local("DIVIDE(1,0)"), "BLANK")
        self.assertEqual(local("DIVIDE(CURRENCY(1.23456),0,7)"), "7")
        self.assertEqual(local("DIVIDE(CURRENCY(1.23456),2)"), "0.6173")


if __name__ == "__main__":
    unittest.main()
