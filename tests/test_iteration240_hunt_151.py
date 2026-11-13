"""Task 151 (dax-hunt-151): fresh Power BI hunt, batch 9. Exact assertions per family, values copied from the measured Power BI answers.

Family A: FLOOR, CEILING, MROUND and ISO.CEILING with a CURRENCY significance give a Currency: the multiple is converted from its double
(double times 10000, rounded half away from zero to ten-thousandths), and a numerator or result beyond the Currency range is the overflow error.
Family B: DIVIDE of a CURRENCY by a number whose Currency quotient is beyond the range is the overflow error, as "/" is; DIVIDE by zero is unchanged.
"""

import unittest
from decimal import Context, Decimal, InvalidOperation

from tools.dax_oracle_diff import local

OVERFLOW = "LOCAL-REJECT:The result of a conversion or arithmetic operation is either too large or too small."
ROUND15 = Context(prec=15)


def _matches_power_bi(got, power_bi):
    """The hunt scorer's rule: the same text, or the same value to 15 significant digits with the same sign."""
    if got == power_bi:
        return True
    try:
        a, b = Decimal(power_bi), Decimal(got)
    except InvalidOperation:
        return False
    return ROUND15.plus(a) == ROUND15.plus(b) and a.is_signed() == b.is_signed()


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


    # Family C: a CURRENCY significance makes FLOOR, CEILING, MROUND and ISO.CEILING a Currency whatever the multiple's type,
    # so the rules that follow the static type (multiply, MOD, PMT, MEDIANX, SUMX, ROUND, concatenation, overflow) apply to it.
    # Each row is the measured Power BI answer, compared as the hunt scorer compares (equal text, or equal to 15 significant digits).
    def test_family_c_currency_significance_static_type(self):
        cases = [
            ('FLOOR(CURRENCY(5.55555),0.1)', '5.5'),
            ('FLOOR(7.3,CURRENCY(2))&"z"', '6z'),
            ('CEILING(-7.3,CURRENCY(2))', '-6'),
            ('MROUND(10,CURRENCY(3))', '9'),
            ('ISO.CEILING(-4.5,CURRENCY(2))', '-4'),
            ('IFERROR(FLOOR(DATE(2020,1,5),CURRENCY(2)),"E")', '43834'),
            ('FLOOR(BLANK(),CURRENCY(2))', 'BLANK'),
            ('FLOOR(TRUE(),CURRENCY(1))', '1'),
            ('FLOOR("5.5",CURRENCY(1))', '5'),
            ('IFERROR(FLOOR(5.5,CURRENCY(0)),"E")', 'E'),
            ('IFERROR(MROUND(5,CURRENCY(-2)),"E")', 'E'),
            ('FLOOR(1/3,CURRENCY(0.0001))', '0.3333'),
            ('IFERROR(FLOOR(1/3,CURRENCY(0.00001)),"E")', 'E'),
            ('IFERROR(CEILING(9.2E14,CURRENCY(1.5)),"E")', '919999999999999.488'),
            ('IFERROR(FLOOR(-922337203685477,CURRENCY(7)),"E")', 'E'),
            ('IFERROR(DIVIDE(CURRENCY(1E14),0.01),"E")', 'E'),
            ('IFERROR(DIVIDE(CURRENCY(-1E14),0.05),"E")', 'E'),
            ('DIVIDE(CURRENCY(5),3)&"z"', '1.6667z'),
            ('FLOOR(SUM(Facts[Sales]),CURRENCY(10))', '30'),
            ('MROUND(CURRENCY(7.5),CURRENCY(2))', '8'),
            ('CEILING(5.5,CURRENCY(2))*0.33333', '2'),
            ('FORMAT(FLOOR(7.3,CURRENCY(2)),"0.000000")', '6.000000'),
            ('FLOOR(7.3,CONVERT(2,CURRENCY))&"z"', '6z'),
            ('FLOOR(7.3,CURRENCY(2)+0.5)&"z"', '5z'),
            ('FLOOR(7.3,CURRENCY(2)*2)&"z"', '4z'),
            ('IFERROR(IF(TRUE(),FLOOR(1E16,CURRENCY(1)),1),"E")', 'E'),
            ('IFERROR(MROUND(1E16,CURRENCY(1)),"E")', 'E'),
            ('SUMX({1,2,3},FLOOR([Value]*1.37,CURRENCY(0.25)))', '7.75'),
            ('MEDIANX({1,2},FLOOR([Value]*1.37,CURRENCY(0.25)))', '1.875'),
            ('AVERAGEX({1,2},CEILING([Value]*1.37777,CURRENCY(0.0003)))', '2.0669'),
            ('FLOOR(1/7,CURRENCY(0.0003))', '0.1428'),
            ('CEILING(2/7,CURRENCY(0.0007))&"z"', '0.2863z'),
            ('MROUND(123456.78901,CURRENCY(0.0007))', '123456.7887'),
            ('ISO.CEILING(1/9,CURRENCY(0.0002))&"z"', '0.1112z'),
            ('IFERROR(ISO.CEILING(1E16,CURRENCY(2)),"E")', 'E'),
            ('FLOOR(-1/7,CURRENCY(0.0003))', '-0.1431'),
            ('IFERROR(FLOOR(-5,CURRENCY(2)),"E")', '-6'),
            ('IFERROR(FLOOR(5,CURRENCY(-2)),"E")', 'E'),
            ('CEILING(MAX(Facts[Quantity])/3,CURRENCY(0.5))', '2'),
            ('IFERROR(DIVIDE(1E15,CURRENCY(0.1)),"E")', '1E+16'),
            ('IFERROR(DIVIDE(CURRENCY(9E14),CURRENCY(0.01)),"E")', '9E+16'),
            ('FLOOR(7.3,CURRENCY(2))*0.33333', '2'),
            ('MROUND(7.3,CURRENCY(2))/3', '2.6667'),
            ('CEILING(5.5,CURRENCY(2))+0.00001', '6.00001'),
            ('IF(TRUE(),FLOOR(7.3,CURRENCY(2)),0.5)*0.33333', '1.99998'),
            ('MOD(FLOOR(7.65432,CURRENCY(0.0001)),0.7)', '0.654300000000001'),
            ('MOD(CEILING(7.3,CURRENCY(2)),0.7)', '0.3'),
            ('PMT(0.05,2,FLOOR(1.23456,CURRENCY(0.0001)),FLOOR(0.5,CURRENCY(0.25)))', '-0.9078'),
            ('PMT(0.05,2,CURRENCY(1.23456),CEILING(0.6,CURRENCY(0.5)))', '-1.1518'),
            ('MEDIANX({1,2},FLOOR([Value]*7.65432,CURRENCY(0.0001))*1)', '11.4815'),
            ('ISO.CEILING(5.5,CURRENCY(2))*0.33333', '2'),
            ('FLOOR(7.3,CURRENCY(2))*CURRENCY(0.33333)&"z"', '1.9998z'),
            ('CEILING(5.5,CURRENCY(2))*0.33333&"z"', '2z'),
            ('SUMX({1,2},CEILING(5.5,CURRENCY(2))*0.33333)', '4'),
            ('DIVIDE(FLOOR(7.3,CURRENCY(2)),3)', '2'),
            ('FLOOR(7.3,CURRENCY(2))/3&"z"', '2z'),
            ('ROUND(CEILING(5.5,CURRENCY(2))*0.33333,6)', '2'),
            ('CEILING(5.5,CURRENCY(2))*1E-5', '0.0001'),
            ('CEILING(5.5,CURRENCY(2))*1E-5&"z"', '0.0001z'),
            ('IFERROR(CEILING(5.5,CURRENCY(2))*1E15,"E")', 'E'),
            ('FLOOR(CURRENCY(7.3),CURRENCY(2))*0.33333', '2'),
        ]
        for expression, power_bi in cases:
            self.assertTrue(_matches_power_bi(local(expression), power_bi), expression)


if __name__ == "__main__":
    unittest.main()
