"""Task 156 (dax-hunt-156): fresh Power BI hunt, batch 10. Exact assertions per family, values copied from the measured Power BI answers.

Family A: ISEVEN / ISODD of a TEXT argument read it with the half-to-even text-to-integer rule (ISEVEN("2.5") is True); numbers stay half away from zero.
Family B: CONTAINSROW with a number of values that is not the number of columns is a query-level error (IFERROR and an untaken IF do not catch it).
Family C: PRODUCTX over the rows of a model table is a Double, exp of the sum of the logarithms with the sign tracked; over a table constructor it is the
plain double product; a double underflow is 0.
Family D: ISBOOLEAN(CONVERT(FORMAT(BLANK(),"General Date"),DOUBLE)) is the error (the FORMAT of BLANK is a run-time "" that CONVERT fails on).
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


class TestIteration245Hunt156(unittest.TestCase):
    # Family A: a text argument rounds half to even; a number rounds half away from zero
    def test_family_a_text_half_to_even(self):
        self.assertTrue(_matches_power_bi(local('ISEVEN("2.5")'), "True"))
        self.assertTrue(_matches_power_bi(local('ISODD("2.5")'), "False"))
        self.assertTrue(_matches_power_bi(local('ISEVEN("4.5")'), "True"))
        self.assertTrue(_matches_power_bi(local('ISODD("4.5")'), "False"))
        self.assertTrue(_matches_power_bi(local('ISEVEN("0.5")'), "True"))
        self.assertTrue(_matches_power_bi(local('ISODD("0.5")'), "False"))
        self.assertTrue(_matches_power_bi(local('ISODD("-2.5")'), "False"))
        self.assertTrue(_matches_power_bi(local('ISEVEN("-3.5")'), "True"))
        self.assertTrue(_matches_power_bi(local('ISEVEN("1.5")'), "True"))
        self.assertTrue(_matches_power_bi(local('ISEVEN("2.5e0")'), "True"))
        self.assertTrue(_matches_power_bi(local('ISEVEN("2.4")'), "True"))
        self.assertTrue(_matches_power_bi(local('ISODD("2.6")'), "True"))

    def test_family_a_text_non_numeric_is_an_error(self):
        self.assertEqual(local('IFERROR(ISEVEN("abc"),"E")'), "E")

    def test_family_a_numbers_keep_half_away_from_zero(self):
        self.assertTrue(_matches_power_bi(local("ISEVEN(2.5)"), "False"))
        self.assertTrue(_matches_power_bi(local("ISODD(2.5)"), "True"))
        self.assertTrue(_matches_power_bi(local("ISEVEN(-2.5)"), "False"))
        self.assertTrue(_matches_power_bi(local("ISEVEN(3.5)"), "True"))
        self.assertTrue(_matches_power_bi(local("ISEVEN(2.9)"), "False"))
        self.assertTrue(_matches_power_bi(local("ISEVEN(CURRENCY(2.5))"), "False"))
        self.assertTrue(_matches_power_bi(local("ISEVEN(BLANK())"), "True"))
        self.assertTrue(_matches_power_bi(local("ISEVEN(TRUE())"), "False"))

    # Family B: a wrong number of values is a query-level error, never caught by IFERROR
    def test_family_b_wrong_value_count_is_a_query_error(self):
        for expr in (
            'IFERROR(CONTAINSROW(Facts,"East"),"E")',
            "IFERROR(CONTAINSROW(Facts,1,2),\"E\")",
            "IFERROR(CONTAINSROW({1,2},1,2),\"E\")",
            "IFERROR(CONTAINSROW({(1,2)},1),\"E\")",
            'IF(FALSE(),CONTAINSROW({1},1,2),1)',
            'IFERROR(CONTAINSROW(SELECTCOLUMNS(Facts,"r",Facts[Region]),"East",1),"E")',
        ):
            with self.subTest(expr=expr):
                self.assertTrue(local(expr).startswith("LOCAL-REJECT"), local(expr))

    def test_family_b_right_value_count_is_kept(self):
        self.assertEqual(local('CONTAINSROW(SELECTCOLUMNS(Facts,"r",Facts[Region]),"East")'), "True")
        self.assertEqual(local("CONTAINSROW({(1,2)},1,2)"), "True")

    # Family C: a product over model-table rows is exp(sum(ln|x|)) as a Double; a table constructor is the double product
    def test_family_c_model_table_rows_are_exp_log_doubles(self):
        self.assertTrue(_matches_power_bi(local("PRODUCTX(CALCULATETABLE(Facts,Facts[Sales]>=2.5),Facts[Sales]*5)"), "65625.0000000001"))
        self.assertTrue(_matches_power_bi(local("PRODUCTX(FILTER(Facts,Facts[Sales]>0),Facts[Sales]*5)"), "65625.0000000001"))
        self.assertTrue(_matches_power_bi(local("PRODUCTX(CALCULATETABLE(Facts,Facts[Sales]>=2.5),Facts[Sales])"), "525"))

    def test_family_c_zero_factor_is_zero(self):
        self.assertTrue(_matches_power_bi(local("PRODUCTX(Facts,Facts[Sales])"), "0"))
        self.assertTrue(_matches_power_bi(local("PRODUCTX(Facts,Facts[Sales]*5)"), "0"))

    def test_family_c_table_constructor_is_plain_double_product(self):
        self.assertTrue(_matches_power_bi(local("PRODUCTX({12.5,52.5,100},[Value])"), "65625"))
        self.assertTrue(_matches_power_bi(local("PRODUCTX({1.1,1.1,1.1,1.1},[Value])"), "1.4641"))
        self.assertTrue(_matches_power_bi(local("PRODUCTX({-2.5,10.5,20},[Value]*5)"), "-65625"))
        self.assertEqual(local("PRODUCTX({1E100,1E200,1E10},[Value])"), "Infinity")
        self.assertTrue(_matches_power_bi(local("PRODUCTX({CURRENCY(2.5),CURRENCY(10.5)},[Value])"), "26.25"))

    def test_family_c_double_underflow_is_zero(self):
        self.assertTrue(_matches_power_bi(local("PRODUCTX({1E-200,1E-200},[Value])"), "0"))

    # Family D: FORMAT(BLANK(),..) is a run-time "" that CONVERT(..., DOUBLE) fails on, and the type test shows it
    def test_family_d_type_test_of_format_blank_conversion_is_an_error(self):
        self.assertEqual(local('IFERROR(ISBOOLEAN(CONVERT(FORMAT(BLANK(),"General Date"),DOUBLE)),"E")'), "E")

    def test_family_d_kept_shapes(self):
        self.assertEqual(local('IFERROR(ISBOOLEAN(CONVERT("",DOUBLE)),"E")'), "False")
        self.assertEqual(local('IFERROR(CONVERT(FORMAT(BLANK(),"General Date"),DOUBLE),"E")'), "E")
        self.assertEqual(local('FORMAT(BLANK(),"General Date")&"z"'), "z")
        self.assertEqual(local('IFERROR(CONVERT("",BOOLEAN),"E")'), "BLANK")


if __name__ == "__main__":
    unittest.main()
