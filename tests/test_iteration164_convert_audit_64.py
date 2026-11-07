"""Iteration 164: Task 74 conversion audit (convert-audit-64).

Covers the live Power BI evidence in tools/parity/task74_convert_audit_spec.json (51 rows, 1,500-shape grid t74a):
- Part A: a text beyond the Double range ("1e400") is an error. In a numeric context it is "Cannot convert value ... to type Number."; in a
  logical context (AND, OR, NOT, CONVERT to BOOLEAN) it is "The following system error occurred: Out of present range."
- Part B: an Int64 from 2^53 up is read through a double by INT, TRUNC, ROUND, ISEVEN and ISODD; FIXED shows it to 15 significant digits;
  FORMAT "Standard" shows it exactly. The Int64 minimum is the error for ISEVEN and ISODD.
- Part C: TRUNC of -Infinity is NaN, FIXED of NaN with negative decimals is the conversion error, and FORMAT of a date under "@" is its date text.
"""
from __future__ import annotations

import unittest

from analytics_studio import dax_typed
from analytics_studio.measures import MeasureError
from tools import dax_oracle_diff as dax

_TOO_BIG = "The result of a conversion or arithmetic operation is either too large or too small."
_NUMBER = "Cannot convert value '1e400' of type Text to type Number."
_RANGE = "The following system error occurred: Out of present range."


def _rejected(expression: str) -> str:
    """The local answer when it is refused or errors: the LOCAL-REJECT text (empty when the expression evaluates)."""
    answer = dax.local(expression)
    return answer.split(":", 1)[1] if answer.startswith("LOCAL-REJECT:") else ""


class TestIteration164ConvertAudit64(unittest.TestCase):
    # Part A: text beyond the Double range
    def test_part_a_numeric_context_raises_the_number_conversion_error(self) -> None:
        for expression in ('VALUE("1e400")', 'ABS("1e400")', 'SQRT("1e400")', 'SIGN("1e400")', 'LN("1e400")', 'ROUND("1e400",0)',
                           'POWER("1e400",0.5)', 'DIVIDE("1e400",1)', 'FIXED("1e400",2)', 'CONVERT("1e400",DOUBLE)'):
            with self.subTest(expression=expression):
                self.assertEqual(_rejected(expression), _NUMBER)

    def test_part_a_logical_context_raises_the_out_of_range_error(self) -> None:
        for expression in ('NOT("1e400")', 'AND("1e400",TRUE())', 'OR("1e400","")', 'CONVERT("1e400",BOOLEAN)'):
            with self.subTest(expression=expression):
                self.assertEqual(_rejected(expression), _RANGE)

    def test_part_a_a_text_inside_the_double_range_still_converts(self) -> None:
        self.assertEqual(str(dax.local('VALUE("1e300")')), "1E+300")
        self.assertEqual(str(dax.local('NOT("1e300")')), "False")

    def test_part_a_the_conversion_helper_raises_on_overflow_only(self) -> None:
        with self.assertRaises(MeasureError):
            dax_typed.text_to_number("1e400")
        self.assertEqual(str(dax_typed.text_to_number("1e300")), "1E+300")

    # Part B: int64 extremes
    def test_part_b_int_trunc_and_round_of_the_maximum_are_the_conversion_error(self) -> None:
        for expression in ("INT(9223372036854775807)", "TRUNC(9223372036854775807)", "ROUND(9223372036854775807,0)",
                           "ROUND(9223372036854775807,-2)", "ROUND(9223372036854775807,1)", "INT(9223372036854775807)&\"\""):
            with self.subTest(expression=expression):
                self.assertEqual(_rejected(expression), _TOO_BIG)

    def test_part_b_iseven_and_isodd_of_the_maximum_use_its_double(self) -> None:
        self.assertEqual(str(dax.local("ISEVEN(9223372036854775807)")), "True")
        self.assertEqual(str(dax.local("ISODD(9223372036854775807)")), "False")

    def test_part_b_iseven_and_isodd_of_the_minimum_are_the_conversion_error(self) -> None:
        self.assertEqual(_rejected("ISEVEN(-9223372036854775808)"), _TOO_BIG)
        self.assertEqual(_rejected("ISODD(-9223372036854775808)"), _TOO_BIG)

    def test_part_b_trunc_of_the_minimum_stays_a_double(self) -> None:
        self.assertEqual(_rejected("TRUNC(-9223372036854775808)"), "")
        self.assertTrue(dax.same("-9.22337203685478E+18", dax.local("TRUNC(-9223372036854775808)")))

    def test_part_b_fixed_shows_an_int64_to_fifteen_significant_digits(self) -> None:
        self.assertEqual(dax.local("FIXED(9223372036854775807,0)"), "9,223,372,036,854,780,000")
        self.assertEqual(dax.local("FIXED(9223372036854775807,2)"), "9,223,372,036,854,780,000.00")
        self.assertEqual(dax.local("FIXED(9223372036854775807,-1)"), "9,223,372,036,854,780,000")
        self.assertEqual(dax.local("FIXED(-9223372036854775808,1)"), "-9,223,372,036,854,780,000.0")

    def test_part_b_format_standard_shows_an_int64_exactly(self) -> None:
        self.assertEqual(dax.local('FORMAT(9223372036854775807,"Standard")'), "9,223,372,036,854,775,807.00")

    def test_part_b_format_standard_of_a_double_keeps_fifteen_digits(self) -> None:
        self.assertEqual(dax.local('FORMAT(9.2233720368547758E18,"Standard")'), "9,223,372,036,854,780,000.00")

    # Part C: other
    def test_part_c_trunc_of_negative_infinity_is_nan(self) -> None:
        self.assertEqual(dax.local("TRUNC(-1/0)"), "NaN")
        self.assertEqual(dax.local("TRUNC(1/0)"), "NaN")

    def test_part_c_fixed_of_nan_with_negative_decimals_is_the_conversion_error(self) -> None:
        self.assertEqual(_rejected("FIXED(0/0,-1)"), _TOO_BIG)

    def test_part_c_fixed_of_nan_with_zero_or_positive_decimals_is_nan(self) -> None:
        self.assertEqual(dax.local("FIXED(0/0,1)"), "-nan(ind)")

    def test_part_c_format_of_a_date_under_at_is_its_date_text(self) -> None:
        self.assertEqual(dax.local('FORMAT(DATE(2024,1,1),"@")'), "1/1/2024")

    # Review round (held-out grids t74a and t74b): a text is a Double that underflows; an Int64 wraps, it never raises on + - *
    def test_review_a_text_underflow_reads_as_zero(self) -> None:
        self.assertEqual(str(dax.local('SIGN("1e-400")')), "0")
        self.assertEqual(str(dax.local('NOT("1e-400")')), "True")
        self.assertEqual(str(dax.local('AND(1/0,"1e-400")')), "False")
        self.assertEqual(str(dax.local('1/0*"1e-400"')), "NaN")
        self.assertEqual(str(dax.local('SIGN("1e-300")')), "1")
        self.assertEqual(str(dax_typed.text_to_number("1e-400")), "0")
        self.assertEqual(str(dax_typed.text_to_number("1e-300")), "1E-300")

    def test_review_a_text_underflow_is_a_zero_for_ln_and_power(self) -> None:
        self.assertIn("LN", _rejected('LN("1e-400")'))
        self.assertTrue(_rejected('POWER("1e-400",0)'))
        self.assertEqual(str(dax.local('POWER("1e-400",2)')), "0")

    def test_review_a_zero_text_makes_or_read_every_argument(self) -> None:
        self.assertEqual(_rejected('OR("abc","1e-400")'), "Cannot convert value 'abc' of type Text to type True/False.")
        self.assertEqual(str(dax.local('OR("abc","2")')), "True")

    def test_review_a_negative_underflow_is_refused(self) -> None:
        self.assertIn("negative zero", _rejected('SIGN("-1e-400")'))

    def test_review_b_wrapped_minimum_differs_from_the_double_literal(self) -> None:
        # the wrapped Int64 minimum: ROUND, INT and TRUNC are the error, ISEVEN is True (measured)
        for expression in ("ROUND(4611686018427387904*2,1)", "ROUND(4611686018427387904*2,-1)", "INT(4611686018427387904*2)", "TRUNC(-9223372036854775807)"):
            with self.subTest(expression=expression):
                self.assertEqual(_rejected(expression), _TOO_BIG)
        self.assertEqual(str(dax.local("ISEVEN(4611686018427387904*2)")), "True")
        self.assertEqual(str(dax.local("ISODD(4611686018427387904*2)")), "False")
        self.assertEqual(str(dax.local("ISEVEN(-9223372036854775807)")), "True")
        # the Double literal -9223372036854775808: ROUND and TRUNC answer, ISEVEN is the error
        self.assertEqual(_rejected("ROUND(-9223372036854775808,1)"), "")
        self.assertEqual(_rejected("ISEVEN(-9223372036854775808)"), _TOO_BIG)

    def test_review_b_int64_arithmetic_wraps(self) -> None:
        self.assertEqual(str(dax.local("4611686018427387904*2+1")), "-9223372036854775807")
        self.assertEqual(str(dax.local("-9223372036854775807*-9223372036854775807")), "1")

    def test_review_b_iseven_of_a_number_text_from_2_pow_63_is_the_range_error(self) -> None:
        self.assertEqual(_rejected('ISEVEN("9223372036854775808")'), _RANGE)
        self.assertEqual(str(dax.local('ISEVEN("1e-400")')), "True")
        self.assertIn("not modelled", _rejected('ISEVEN("-9223372036854775808")'))

    # Rounds 3 and 4 (grids t74c, t74d): a text that reads as a subnormal Double is refused, except in + - * and in ABS, VALUE and LN
    def test_round4_subnormal_text_is_refused_outside_the_answered_functions(self) -> None:
        for expression in ('SIGN("2e-310")', 'SIGN("-7e-315")', 'DIVIDE(1,"2e-310")', 'POWER("4.9e-324",0)', 'INT("-7e-315")', 'MOD("2e-310",2)',
                           'ROUND("2e-310",-1)', 'FIXED("2e-310",0)', 'CURRENCY("3e-320")', 'CONVERT("2e-310",BOOLEAN)', '"2e-310"/2'):
            with self.subTest(expression=expression):
                self.assertIn("subnormal text conversion", _rejected(expression))

    def test_round4_subnormal_text_is_answered_in_plus_minus_times_abs_value_and_ln(self) -> None:
        self.assertTrue(dax.same("-744.440071921381", dax.local('LN("4.9e-324")')))
        self.assertTrue(dax.same("-713.108231647594", dax.local('LN("2e-310")')))
        self.assertTrue(dax.same("1.99999999999999E-310", dax.local('ABS("2e-310")')))
        self.assertTrue(dax.same("4.94065645841247E-324", dax.local('VALUE("4.9e-324")')))
        self.assertTrue(dax.same("9.99999999999997E-310", dax.local('"2e-310"*"$5"')))
        self.assertTrue(dax.same("5", dax.local('"$5"+"4.9e-324"')))

    def test_round4_a_text_underflowing_to_zero_is_zero(self) -> None:
        self.assertEqual(str(dax.local('SIGN("1e-400")')), "0")
        self.assertEqual(str(dax.local('SIGN("1e-300")')), "1")
        self.assertIn("subnormal text conversion", _rejected('SIGN("2.2250738585072014e-308")'))  # the smallest normal double is refused too (t74e)
        self.assertIn("subnormal text conversion", _rejected('DIVIDE(DATE(2024,1,1),"2.2250738585072014e-308")'))
        self.assertIn("subnormal text conversion", _rejected('MOD("2.2250738585072014e-308",-3)'))

    def test_round4_the_double_maximum_text(self) -> None:
        self.assertTrue(dax.local('FIXED("1.7976931348623157e308",0)').startswith("179,769,313,486,232,000,000"))
        self.assertTrue(_rejected('FIXED("1.7976931348623157e308",-1)'))
        for expression in ('ROUND("1.7976931348623157e308",1)', 'TRUNC("1.7976931348623157e308")'):
            with self.subTest(expression=expression):
                self.assertTrue(_rejected(expression))

    def test_round5_a_currency_text_goes_to_the_whole_number_half_to_even(self) -> None:
        self.assertEqual(str(dax.local('ISEVEN("$12.5")')), "True")
        self.assertEqual(str(dax.local('ISODD("$12.5")')), "False")
        self.assertEqual(str(dax.local('ISEVEN("$0.5")')), "True")
        self.assertEqual(str(dax.local('ISEVEN("$12")')), "True")
        self.assertEqual(str(dax.local('CONVERT("$0.5",INTEGER)')), "0")
        self.assertEqual(str(dax.local('CONVERT("$1.5",INTEGER)')), "2")
        self.assertEqual(str(dax.local('CONVERT("0.5",INTEGER)')), "1")  # a text without the currency sign still rounds half away
        self.assertEqual(str(dax.local("ISEVEN(0.5)")), "False")


if __name__ == "__main__":
    unittest.main()
