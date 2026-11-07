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


if __name__ == "__main__":
    unittest.main()
