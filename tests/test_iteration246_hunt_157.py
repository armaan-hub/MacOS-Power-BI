"""Task 157 (dax-hunt-157): fresh Power BI hunt, batch 11. Exact assertions per family, values copied from the measured Power BI answers.

Family A: QUOTIENT divides two IEEE doubles and truncates toward zero (QUOTIENT(0.3,0.1) is 2, QUOTIENT(1,1E-5) is 99999).
Family B: TRUNC(x) rounds x to 15 significant digits first, then truncates (TRUNC(0.3/0.1) is 3, TRUNC(1/1E-5) is 100000).
Family C: BETA.INV with a tiny standardized result is refused (Power BI's solver gives other answers there).
Family D: CONTAINSROW with the wrong number of values over VALUES, DISTINCT, ALL, SUMMARIZE, ADDCOLUMNS is a query-level error, also in an untaken branch.
Family E: ISBOOLEAN(CONVERT(text joined from FORMAT(BLANK(),..) with & , DOUBLE)) is the error, so IFERROR shows "E".
"""

import unittest
from decimal import Context, Decimal, InvalidOperation

from tools.dax_oracle_diff import local

ROUND15 = Context(prec=15)


def _matches_power_bi(got, power_bi):
    """The hunt scorer's rule: the same text, or the same value to 15 significant digits with the same sign."""
    if got == power_bi:
        return True
    if got.lower() in ("true", "false") and got.lower() == power_bi.lower():
        return True
    try:
        a, b = Decimal(power_bi), Decimal(got)
    except InvalidOperation:
        return False
    return ROUND15.plus(a) == ROUND15.plus(b) and a.is_signed() == b.is_signed()


class TestIteration246Hunt157(unittest.TestCase):
    # Family A: QUOTIENT of the double quotient, truncated
    def test_family_a_quotient_double_division(self):
        self.assertTrue(_matches_power_bi(local("QUOTIENT(0.3,0.1)"), "2"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(-0.3,0.1)"), "-2"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(0.7,0.1)"), "6"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(4.6,0.2)"), "22"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(1.2,0.4)"), "2"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(-1.2,0.4)"), "-2"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(0.6,0.2)"), "2"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(-1,1E-5)"), "-99999"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(1,1E-5)"), "99999"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(3E-1,1E-1)"), "2"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(0.3,0.1)+0"), "2"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(CURRENCY(0.3),CURRENCY(0.1))"), "2"))

    def test_family_a_kept_exact_answers(self):
        self.assertTrue(_matches_power_bi(local("QUOTIENT(1,0.1)"), "10"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(1,0.3)"), "3"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(7,0.7)"), "10"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(5.5,1.1)"), "5"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(-5.5,1.1)"), "-5"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(1E15,3)"), "333333333333333"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(3,1E-15)"), "3000000000000000"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(1,3E-16)"), "3333333333333333"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(-7,2)"), "-3"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(7,-2)"), "-3"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(1,CURRENCY(0.0001))"), "10000"))
        self.assertTrue(_matches_power_bi(local('QUOTIENT("1","0.1")'), "10"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(TRUE(),0.1)"), "10"))
        self.assertTrue(_matches_power_bi(local('IFERROR(QUOTIENT(1,0),"E")'), "E"))
        self.assertTrue(_matches_power_bi(local("QUOTIENT(0.3+0,0.1)"), "2"))

    # Family B: TRUNC pre-rounds a Double to 15 significant digits, as INT does
    def test_family_b_trunc_fifteen_digits(self):
        self.assertTrue(_matches_power_bi(local("TRUNC(0.3/0.1)"), "3"))
        self.assertTrue(_matches_power_bi(local("TRUNC(1.2/0.4)"), "3"))
        self.assertTrue(_matches_power_bi(local("TRUNC(0.6/0.2)"), "3"))
        self.assertTrue(_matches_power_bi(local("TRUNC(4.6/0.2)"), "23"))
        self.assertTrue(_matches_power_bi(local("TRUNC(1/1E-5)"), "100000"))
        self.assertTrue(_matches_power_bi(local("TRUNC(-1/1E-5)"), "-100000"))
        self.assertTrue(_matches_power_bi(local("TRUNC(-1/0.00001)"), "-100000"))
        self.assertTrue(_matches_power_bi(local("TRUNC(-1/1E-5+0)"), "-100000"))

    def test_family_b_kept_answers(self):
        self.assertTrue(_matches_power_bi(local("INT(0.7/0.1)"), "7"))
        self.assertTrue(_matches_power_bi(local("ROUNDDOWN(0.3/0.1,0)"), "3"))
        self.assertTrue(_matches_power_bi(local("TRUNC(DIVIDE(0.3,0.1))"), "3"))
        self.assertTrue(_matches_power_bi(local("TRUNC(CURRENCY(0.3)/CURRENCY(0.1))"), "3"))
        self.assertTrue(_matches_power_bi(local("TRUNC(1/3*3)"), "1"))
        self.assertTrue(_matches_power_bi(local("(0.3/0.1)-3"), "-4.44089209850063E-16"))

    # Family C: a tiny standardized BETA.INV result is refused
    def test_family_c_beta_inv_tiny_results_refused(self):
        for expression in (
            "BETA.INV(0.05,1E-5,1E15)",
            "BETA.INV(0.5,1E-5,1E15)",
            "BETA.INV(0.05,1E-3,1E10)",
            "BETA.INV(0.05,1E-5,1E12)",
            "BETA.INV(0.05,1E-4,1E15)",
            "BETA.INV(0.001,1E-5,1E15)",
            "BETA.INV(0.95,1E-5,1E15)",
            "BETA.INV(0.05,1E-5,1E15,0,10)",
            "BETA.INV(0.05,1E-5,1E5)",
            "BETA.INV(0.05,1E-5,1)",
            "BETA.INV(0.05,1E-5,1E8)",
            "BETA.INV(0.05,1E-5,1E-5)",
        ):
            with self.subTest(expression=expression):
                self.assertTrue(local(expression).startswith("LOCAL-REJECT"))

    def test_family_c_ordinary_beta_inv_kept(self):
        self.assertTrue(_matches_power_bi(local("BETA.INV(0.05,2,3)"), "0.09761146288641447"))

    # Family D: CONTAINSROW width over VALUES, DISTINCT, ALL, SUMMARIZE, ADDCOLUMNS, FILTER, SELECTCOLUMNS, TOPN
    def test_family_d_static_width_refuses_untaken_branch(self):
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(VALUES(Facts[Region]),"East","x"))').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(DISTINCT(Facts[Region]),"East","x"))').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(VALUES(Facts),"East","x"))').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(ALL(Facts[Region],Facts[Sales]),"East","x"))') == "1")
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,Facts[Region],"n",COUNTROWS(Facts)),"East","x"))') == "1")
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(SUMMARIZE(Facts,Facts[Region],"n",COUNTROWS(Facts)),"East"))').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(FILTER(Facts,TRUE()),"East","x"))').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(SELECTCOLUMNS(Facts,"a",Facts[Region]),"East","x"))').startswith("LOCAL-REJECT"))
        self.assertTrue(local('IF(TRUE(),1,CONTAINSROW(TOPN(2,Facts),"East","x"))').startswith("LOCAL-REJECT"))

    def test_family_d_matching_width_kept(self):
        self.assertEqual(local('IF(TRUE(),1,CONTAINSROW(VALUES(Facts[Region]),"East"))'), "1")
        self.assertEqual(local('IF(TRUE(),1,CONTAINSROW(ADDCOLUMNS(Facts,"a",1),1,2,3,4,5))'), "1")
        self.assertEqual(local('IF(TRUE(),1,CONTAINSROW(ADDCOLUMNS(Facts,"a",1,"b",2),1,2,3,4,5,6))'), "1")

    # Family E: a type test of CONVERT of a & join of FORMAT(BLANK(),..) and text shows the error
    def test_family_e_convert_format_blank_concatenation(self):
        self.assertEqual(local('IFERROR(ISBOOLEAN(CONVERT(FORMAT(BLANK(),"0")&"",DOUBLE)),"E")'), "E")
        self.assertEqual(local('IFERROR(ISBOOLEAN(CONVERT(""&FORMAT(BLANK(),"0")&"x",DOUBLE)),"E")'), "E")
        self.assertEqual(local('IFERROR(ISBOOLEAN(CONVERT("a"&FORMAT(BLANK(),"0")&"b"&("c"&FORMAT(BLANK(),"0")),DOUBLE)),"E")'), "E")

    def test_family_e_literal_convert_kept(self):
        self.assertEqual(local('IFERROR(ISBOOLEAN(CONVERT("",DOUBLE)),"E")'), "False")
        self.assertEqual(local('IFERROR(ISBOOLEAN(CONVERT("1"&"",DOUBLE)),"E")'), "False")


if __name__ == "__main__":
    unittest.main()
