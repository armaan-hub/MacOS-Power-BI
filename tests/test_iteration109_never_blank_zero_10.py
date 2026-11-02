"""Iteration 109: never-blank-zero-10 (Task 20).

Plan: docs/plans/2026-11-02-never-blank-zero-10.md
Parts:
  - Part A: what ISBLANK evaluates. An argument that can never be BLANK (by the table of never-blank functions) is not evaluated;
    any other argument is evaluated and its error propagates.
"""
from __future__ import annotations

import unittest

from tools import dax_oracle_diff as dax


def _local(expression: str) -> str:
    return dax.local(expression)


def _is_error(expression: str) -> bool:
    return _local(expression).startswith("LOCAL-REJECT")


def _answer(expression: str, expected: str) -> bool:
    return _local(expression) == expected


class PartAIsBlankEvaluationTests(unittest.TestCase):
    """Part A: ISBLANK evaluates an argument unless it can never be BLANK."""

    def test_plain_error_argument_is_an_error(self) -> None:
        self.assertTrue(_is_error("ISBLANK(FACT(-1))"))

    def test_never_blank_domain_error_is_false(self) -> None:
        self.assertTrue(_answer("ISBLANK(SQRT(-1))", "False"))

    def test_if_with_three_arguments_needs_both_branches_never_blank(self) -> None:
        self.assertTrue(_is_error("ISBLANK(IF(TRUE(),SQRT(-1)))"))
        self.assertTrue(_answer("ISBLANK(IF(TRUE(),SQRT(-1),2))", "False"))

    def test_if_condition_is_not_looked_at(self) -> None:
        self.assertTrue(_answer("ISBLANK(IF(FACT(-1)>0,1,2))", "False"))

    def test_plus_is_never_blank_when_either_side_is(self) -> None:
        self.assertTrue(_answer("ISBLANK(1+FACT(-1))", "False"))
        self.assertTrue(_answer("ISBLANK(FACT(-1)+1)", "False"))

    def test_times_needs_both_sides_never_blank(self) -> None:
        self.assertTrue(_is_error("ISBLANK(FACT(-1)*2)"))
        self.assertTrue(_is_error("ISBLANK(2*FACT(-1))"))

    def test_divide_is_judged_by_its_left_side(self) -> None:
        self.assertTrue(_answer("ISBLANK(2/FACT(-1))", "False"))
        self.assertTrue(_is_error("ISBLANK(FACT(-1)/2)"))

    def test_first_argument_table_function(self) -> None:
        self.assertTrue(_is_error("ISBLANK(ABS(FACT(-1)))"))
        self.assertTrue(_answer('ISBLANK(LEFT("abc",FACT(-1)))', "False"))
        self.assertTrue(_answer("ISBLANK(MOD(1,FACT(-1)))", "False"))
        self.assertTrue(_is_error("ISBLANK(MOD(FACT(-1),1))"))

    def test_always_never_blank_function_ignores_its_arguments(self) -> None:
        self.assertTrue(_answer("ISBLANK(EXP(FACT(-1)))", "False"))
        self.assertTrue(_answer("ISBLANK(ISNUMBER(FACT(-1)))", "False"))

    def test_any_argument_never_blank_function(self) -> None:
        self.assertTrue(_answer('ISBLANK(CONCATENATE("a",FACT(-1)))', "False"))
        self.assertTrue(_is_error("ISBLANK(CONCATENATE(BLANK(),FACT(-1)))"))

    def test_third_argument_never_blank_function(self) -> None:
        self.assertTrue(_answer("ISBLANK(PMT(0.1,2,1,FACT(-1)))", "False"))
        self.assertTrue(_is_error("ISBLANK(PMT(0.1,2,FACT(-1)))"))

    def test_all_arguments_never_blank_function(self) -> None:
        self.assertTrue(_answer("ISBLANK(MAX(1,2))", "False"))
        self.assertTrue(_is_error("ISBLANK(MAX(1,FACT(-1)))"))

    def test_evaluated_function_propagates_its_error(self) -> None:
        self.assertTrue(_is_error("ISBLANK(SIN(FACT(-1)))"))
        self.assertTrue(_is_error("ISBLANK(DEGREES(FACT(-1)))"))

    def test_error_call_is_an_error(self) -> None:
        self.assertTrue(_is_error('ISBLANK(ERROR("x"))'))

    def test_in_operator_is_never_blank(self) -> None:
        self.assertTrue(_answer("ISBLANK(1 IN {1,2})", "False"))

    def test_unused_var_is_not_evaluated(self) -> None:
        self.assertTrue(_answer('ISBLANK(VAR y=BLANK()+ERROR("x") RETURN 1)', "False"))

    def test_used_var_error_propagates(self) -> None:
        self.assertTrue(_is_error('ISBLANK(VAR y=1+ERROR("x") RETURN ABS(y))'))


class PartAPowerWithNonFiniteOperandTests(unittest.TestCase):
    """Part A (plan block: x^y and POWER(x,y) with an infinite or NaN operand), measured in Power BI Desktop."""

    def test_finite_base_with_zero_or_negative_nan_or_infinite_exponent_is_zero(self) -> None:
        self.assertTrue(_answer("2^(0/0)", "0"))
        self.assertTrue(_answer("2^(-1/0)", "0"))
        self.assertTrue(_answer("0^(0/0)", "0"))
        self.assertTrue(_answer("0^(-1/0)", "0"))

    def test_finite_base_with_positive_infinite_exponent_is_error(self) -> None:
        self.assertTrue(_is_error("2^(1/0)"))
        self.assertTrue(_is_error("0^(1/0)"))

    def test_negative_base_with_nan_exponent_is_error(self) -> None:
        self.assertTrue(_is_error("(-2)^(0/0)"))

    def test_infinite_or_nan_base(self) -> None:
        self.assertTrue(_answer("(1/0)^0", "1"))
        self.assertTrue(_answer("(1/0)^-1", "0"))
        self.assertTrue(_is_error("(1/0)^0.5"))
        self.assertTrue(_answer("(0/0)^-1", "0"))

    def test_both_non_finite_is_error(self) -> None:
        self.assertTrue(_is_error("(0/0)^(0/0)"))
        self.assertTrue(_is_error("(1/0)^(-1/0)"))

    def test_blank_operands(self) -> None:
        self.assertTrue(_answer("BLANK()^(1/0)", "BLANK"))
        self.assertTrue(_answer("BLANK()^(0/0)", "BLANK"))
        self.assertTrue(_answer("(1/0)^BLANK()", "1"))

    def test_boolean_base_and_power_function(self) -> None:
        self.assertTrue(_answer("(1=1)^(0/0)", "0"))
        self.assertTrue(_answer("POWER(1/0,0)", "1"))

    def test_error_wrapped_and_tested(self) -> None:
        self.assertTrue(_answer('IFERROR(MAX(Facts[Quantity])^(0/0),"e")', "0"))
        self.assertTrue(_answer("SUMX(Facts,IFERROR((Facts[Sales])^(0/0),7))", "7"))
        self.assertTrue(_answer("ISERROR(2^(0/0))", "False"))


class PartAFilterArgumentsAreNotCrashesTests(unittest.TestCase):
    """A value that is not a column or table is an error (Power BI), never an internal crash."""

    def test_filter_functions_refuse_a_text_value(self) -> None:
        for function in ("ISFILTERED", "ISCROSSFILTERED", "ISINSCOPE", "HASONEFILTER"):
            with self.subTest(function=function):
                self.assertTrue(_is_error(f'ISBLANK({function}(("a"&ERROR("x"))))'))

    def test_lookupvalue_refuses_a_value_as_result_column(self) -> None:
        self.assertTrue(_is_error('ISBLANK(LOOKUPVALUE(("a"&ERROR("x")),(1+ERROR("x")),(1+ERROR("x"))))'))


class PartAIsBlankNeverBlankArgumentsAreNotEvaluatedTests(unittest.TestCase):
    """A never-blank argument of ISBLANK is answered without evaluating it, its static checks included."""

    def test_in_operator_is_never_blank(self) -> None:
        self.assertTrue(_answer('ISBLANK((1+ERROR("x")) IN {1,2})', "False"))
        self.assertTrue(_answer('ISBLANK(1 IN {1+ERROR("x")})', "False"))

    def test_three_argument_if_condition_is_not_looked_at(self) -> None:
        self.assertTrue(_answer('ISBLANK(IF(1+ERROR("x")>0,1,2))', "False"))

    def test_type_tests_of_an_error_are_never_blank(self) -> None:
        self.assertTrue(_answer('ISBLANK(ISCURRENCY(1+ERROR("x")))', "False"))
        self.assertTrue(_answer('ISBLANK(ISDECIMAL(1+ERROR("x")))', "False"))


class PartCLogicalBlankTests(unittest.TestCase):
    """Part C: a logical operator's BLANK (1&&"") is a BLANK typed True/False. It cancels an error like a BLANK that scans nothing, and a left side that
    needs a scan gives False instead of a BLANK."""

    def test_typed_blank_cancels_an_error_on_both_sides_of_times(self) -> None:
        self.assertTrue(_answer('(1&&"")*ERROR("x")', "BLANK"))
        self.assertTrue(_answer('ERROR("x")*(1&&"")', "BLANK"))
        self.assertTrue(_answer('ERROR("x")*(1&&TRIM(""))', "BLANK"))

    def test_typed_blank_cancels_an_error_on_the_left_of_divide(self) -> None:
        self.assertTrue(_answer('(1&&"")/ERROR("x")', "BLANK"))

    def test_typed_blank_cancels_an_error_inside_iferror(self) -> None:
        self.assertTrue(_answer('IFERROR((1&&"")*SQRT(-1),7)', "BLANK"))
        self.assertTrue(_answer('(IFERROR((1&&"")*SQRT(-1),7))+0', "0"))
        self.assertTrue(_answer('IFERROR((ERROR("x"))*(0||""),7)', "BLANK"))

    def test_iserror_of_a_typed_blank_times_an_error_is_false(self) -> None:
        self.assertTrue(_answer('ISERROR((0||"")*ERROR("x"))', "False"))
        self.assertTrue(_answer('ISERROR((1&&"")*ERROR("x"))', "False"))

    def test_static_type_of_a_typed_blank_stays(self) -> None:
        self.assertTrue(_answer('ISBLANK((1&&"")*2)', "False"))
        self.assertTrue(_answer('ISBLANK((1&&"")*"a")', "False"))

    @unittest.expectedFailure
    def test_open_static_type_of_typed_blank_arithmetic_is_numeric(self) -> None:
        """Open (Task 20 Part C, not modelled): ISNUMBER of a typed BLANK times a constant is True in Power BI, but the rule that says so does not
        fit the locked answers (ISNUMBER((2.5&&"")*(LN(0))) is False), so it is not implemented."""
        self.assertTrue(_answer('ISNUMBER((1&&"")*2)', "True"))

    def test_left_side_that_needs_a_scan_gives_false(self) -> None:
        self.assertTrue(_answer('(SUM(Facts[Sales]))&&""', "False"))
        self.assertTrue(_answer('AND(SUM(Facts[Sales]),"")', "False"))
        self.assertTrue(_answer('OR(SUM(Facts[Sales])<-1000,"")', "False"))
        self.assertTrue(_answer('(1+SUM(Facts[Sales]))&&""', "False"))
        self.assertTrue(_answer('(CALCULATE(COUNTROWS(Facts),Facts[Region]="East"))&&""', "False"))

    def test_a_var_is_followed_to_the_expression_it_holds(self) -> None:
        self.assertTrue(_answer('VAR s=SUM(Facts[Sales]) RETURN s&&""', "False"))
        self.assertTrue(_answer('VAR c=MAX(Facts[Sales]) RETURN c&&""', "BLANK"))

    def test_column_read_in_a_row_context_is_a_scan(self) -> None:
        self.assertTrue(_answer('COUNTAX(Facts,Facts[Sales]&&"")', "6"))
        self.assertTrue(_answer('SUMX(Facts,IF(ISNUMBER((Facts[Sales]&&"")*2),1,2))', "6"))

    def test_left_side_that_needs_no_scan_keeps_the_blank(self) -> None:
        self.assertTrue(_answer('(COUNTROWS(Facts))&&""', "BLANK"))
        self.assertTrue(_answer('(MAX(Facts[Sales]))&&""', "BLANK"))
        self.assertTrue(_answer('(COUNTROWS(FILTER(Facts,FALSE())))||""', "False"))
        self.assertTrue(_answer('(0>1)&&""', "False"))


if __name__ == "__main__":
    unittest.main()


class PartBSignOfZeroAndNaNTests(unittest.TestCase):
    """Part B: the sign of zero and NaN. A Decimal keeps both signs; only a result whose static type is Double shows -0 in text.
    A bare result prints 0 for any zero and NaN for any NaN."""

    def test_integer_zero_has_no_sign(self) -> None:
        for expression in ("0*-1", "-(0)", "-(1-1)", "(1-1)*-1", "-(COUNTROWS(Facts)*0)"):
            with self.subTest(expression):
                self.assertEqual("0", _local(expression))
                self.assertEqual("0z", _local(f'({expression})&"z"'))

    def test_double_zero_is_minus_zero_in_text(self) -> None:
        for expression in ("0.0*-1", "0*-1.0", "-(0.0)", "(0/-1)", "((1-1)/-1)", "(-(SUM(Facts[Sales])*0))/(7)"):
            with self.subTest(expression):
                self.assertEqual("-0z", _local(f'({expression})&"z"'))
        self.assertEqual("0", _local("-(0.0)"))  # a bare result prints 0 whatever its sign

    def test_sign_through_plus_minus_and_times(self) -> None:
        self.assertEqual("0z", _local('(-(0.0)+0)&"z"'))
        self.assertEqual("-0z", _local('(-(0.0)-0)&"z"'))
        self.assertEqual("0z", _local('(-(0.0)*-1)&"z"'))

    def test_division_uses_the_sign_of_the_divisor(self) -> None:
        self.assertEqual("-Infinity", _local("1/-(0.0)"))
        self.assertEqual("Infinity", _local("1/(0*-1)"))
        self.assertEqual("-Infinity", _local("1/(0/-1)"))
        self.assertEqual("-infz", _local('(1/-(0.0))&"z"'))

    def test_nan_text_follows_its_sign(self) -> None:
        self.assertEqual("-nan(ind)z", _local('(0/0)&"z"'))
        self.assertEqual("nanz", _local('(-(0/0))&"z"'))
        self.assertEqual("nanz", _local('(1/-(1/0*0))&"z"'))
        self.assertEqual("nanz", _local('((-(1-1))/-(0/0))&"z"'))

    def test_nan_from_unary_minus_and_a_nan_operand(self) -> None:
        self.assertEqual("nanz", _local('(-(1)/(0/0))&"z"'))
        self.assertEqual("nanz", _local('(-(0/0)/(1E20))&"z"'))
        self.assertEqual("nanz", _local('((0/-1)*-(0/0))&"z"'))

    def test_unary_minus_applies_to_the_whole_quotient(self) -> None:
        self.assertEqual("-0z", _local('(-(0)/(COUNTROWS(Facts)))&"z"'))
        self.assertEqual("-0z", _local('(-(-(1-1))/(1234567.891))&"z"'))
        self.assertEqual("0z", _local('((-(0))/(COUNTROWS(Facts)))&"z"'))

    def test_format_prints_nan_without_indeterminate_suffix(self) -> None:
        self.assertEqual("nan", _local('FORMAT(-(0.0*-1)/(-(0.0)),"0.00")'))
        self.assertEqual("nan", _local('FORMAT(-(0/0)/(2),"0.00")'))

    def test_sign_kept_by_sqrt_and_dropped_by_abs(self) -> None:
        self.assertEqual("-0z", _local('(SQRT(-(0.0)))&"z"'))
        self.assertEqual("0z", _local('(ABS(-(0.0)))&"z"'))

    def test_sign_of_zero_for_sign_max_min_and_comparison(self) -> None:
        self.assertEqual("-1", _local("SIGN(-(0.0))"))
        self.assertEqual("1", _local("MAX(1,0/0)"))
        self.assertEqual("True", _local("-(0.0)=0"))
        self.assertEqual("-0z", _local('(MAX(-(0.0),0))&"z"'))
        self.assertEqual("0z", _local('(MIN(0,-(0.0)))&"z"'))

    def test_underflow_is_a_signed_zero(self) -> None:
        self.assertEqual("0", _local("(-1E-200)*1E-200"))
        self.assertEqual("-0z", _local('((-1E-200)*1E-200)&"z"'))


class PartDCurrencyLimitsTests(unittest.TestCase):
    """Part D: a sign binds the whole product or quotient after * or /; Currency + - * wrap at 64 bits; Currency / and CURRENCY() overflow."""

    def test_sign_after_divide_binds_the_whole_product(self) -> None:
        self.assertEqual(_local("1/-(2*3)"), _local("1/-2*3"))
        self.assertTrue(_local("1/-2*3").startswith("-0.16666666666666"))

    def test_currency_times_wraps_at_64_bits(self) -> None:
        self.assertTrue(_answer("CURRENCY(1E14)*10", "-844674407370955.1616"))
        self.assertTrue(dax.same("776627963145224.192", _local("CURRENCY(1E14)*100")))
        self.assertEqual("-844674407370955.1616z", _local('(CURRENCY(1E14)*10)&"z"'))
        self.assertTrue(_answer("CURRENCY(5E14)*2", "-844674407370955.1616"))

    def test_currency_plus_wraps_and_carries_on(self) -> None:
        self.assertTrue(_answer("CURRENCY(922337203685477)+1", "-922337203685477.1616"))
        self.assertTrue(dax.same("-1.1616", _local("CURRENCY(922337203685477)*2")))
        self.assertTrue(_answer("CURRENCY(922337203685477)+CURRENCY(1)", "-922337203685477.1616"))

    def test_currency_times_currency_is_a_double_without_wrap(self) -> None:
        self.assertTrue(dax.same("9E+16", _local("CURRENCY(9E14)*CURRENCY(100)")))

    def test_currency_division_out_of_range_is_an_error(self) -> None:
        self.assertTrue(_is_error("CURRENCY(1E14)/0.01"))

    def test_currency_of_out_of_range_value_is_still_a_currency(self) -> None:
        # saved Power BI answers (dax_battery_type_tests_extra) say ISCURRENCY(CURRENCY(1E15)) is True; the Part D range rule for CURRENCY() contradicts them
        self.assertTrue(_answer("ISCURRENCY(CURRENCY(1E15))", "True"))


class PartESmallRulesTests(unittest.TestCase):
    """Part E: filter-context BLANKs cancel errors under CALCULATE; arithmetic on text is a Double; Double text; FORMAT of huge numbers."""

    def test_filter_context_blank_cancels_error_under_calculate(self) -> None:
        self.assertTrue(_answer('CALCULATE(ISERROR((IF(ISFILTERED(Facts[Region]),1))/(ERROR("x"))),Facts[Quantity]=2)', "False"))
        self.assertTrue(_answer('CALCULATE(ISERROR((ERROR("x"))*(IF(ISFILTERED(Facts[Region]),1))),Facts[Quantity]=2)', "False"))

    def test_filter_context_blank_cancels_error_under_isinscope(self) -> None:
        self.assertTrue(_answer('CALCULATE(ISERROR((IF(ISINSCOPE(Facts[Region]),1))/(SQRT(-1))),ALL(Facts),Facts[Region]="East")', "False"))

    def test_text_arithmetic_is_a_double_in_text(self) -> None:
        self.assertEqual("1E+15z", _local('("1E15"+0)&"z"'))
        self.assertEqual("1E+15z", _local('("1000000000000000"+0)&"z"'))
        self.assertEqual("5", _local('LEN("1E15"+0)'))

    # Part E item 3 (Double text from the shortest digits) is dropped: it breaks saved answers (dax_battery_convert9_extra)

    def test_format_of_a_huge_double_has_no_nan(self) -> None:
        self.assertEqual("1" + "0" * 300, _local('FORMAT(1E300,"0")'))

    def test_convert_to_datetime_of_blank_is_a_date_under_plus(self) -> None:
        self.assertEqual("12/31/1899 00:00:00", _local("CONVERT(BLANK(),DATETIME)+1"))
        self.assertEqual("12/31/1899 00:00:00", _local('CONVERT(1&&"",DATETIME)+1'))

    def test_sumx_of_a_non_finite_datetime_shows_the_end_of_the_range(self) -> None:
        self.assertEqual("12/30/1899 00:00:00", _local("SUMX(Facts,CONVERT(Facts[Quantity]/0,DATETIME))"))
        self.assertEqual("12/31/9999 23:59:59", _local("SUMX(Facts,IF(Facts[Quantity]>2,CONVERT(Facts[Sales]/0,DATETIME)))"))
        self.assertEqual("01/01/0100 00:00:00", _local("SUMX(VALUES(Facts[Region]),IFERROR(CONVERT(-1/0,DATETIME),CONVERT(-1/0,DATETIME)))"))


class FixF1SignAfterPowerTests(unittest.TestCase):
    """F1: a sign after ^ binds the whole product or quotient that follows, like a sign after * or /."""

    def test_sign_covers_the_following_product(self) -> None:
        self.assertEqual("0.125", _local("2^-1*3"))
        self.assertEqual("8", _local("2^+1*3"))
        self.assertEqual("0.0625", _local("2^-2/2*4"))
        self.assertEqual("0.375", _local("3*2^-1*3"))
        self.assertEqual("8", _local("1/2^-1*3"))

    def test_sign_stops_at_plus_and_minus_and_power_chains(self) -> None:
        self.assertEqual("1.5", _local("2^-1+1"))
        self.assertEqual("0.5", _local("2^-1^2"))
        self.assertEqual("32", _local("2^3*4"))
        self.assertEqual("1", _local("2^-MAX(Facts[Quantity])*0"))


class FixF2NonFinitePowerTests(unittest.TestCase):
    """F2: x^y with an infinite or NaN operand."""

    def test_finite_base_with_nan_exponent_uses_the_sign_of_the_nan(self) -> None:
        self.assertEqual("0", _local("1^(0/0)"))
        self.assertTrue(_is_error("1^-(0/0)"))
        self.assertEqual("0", _local("0^(0/0)"))
        self.assertTrue(_is_error("0^-(0/0)"))
        self.assertTrue(_is_error("2^(1/0)"))
        self.assertEqual("0", _local("2^(-1/0)"))
        self.assertTrue(_is_error("(-1)^(0/0)"))

    def test_non_finite_base_with_finite_exponent(self) -> None:
        self.assertEqual("1", _local("(1/0)^0"))
        self.assertEqual("0", _local("(1/0)^-1"))
        self.assertEqual("0", _local("(1/0)^(-1.5)"))
        self.assertEqual("0", _local("(1/0)^(-1E15)"))
        self.assertTrue(_is_error("(1/0)^(-0.5)"))
        self.assertTrue(_is_error("(1/0)^2"))
        self.assertEqual("0", _local("(-1/0)^-3"))
        self.assertEqual("0", _local("(0/0)^-2"))
        self.assertTrue(_is_error("(-1/0)^(-1.5)"))
        self.assertTrue(_is_error("(0/0)^(-1E-200)"))
        self.assertTrue(_is_error("(0/0)^(-1E15)"))
        self.assertTrue(_is_error("(1/0)^(1/0)"))

    def test_a_huge_whole_exponent_for_a_nan_base_is_refused_not_guessed(self) -> None:
        self.assertTrue(_local('IFERROR((0/0)^(-1E10),"e")').startswith("LOCAL-REJECT"))  # refused, not a runtime error that IFERROR would catch
        self.assertEqual("e", _local('IFERROR((0/0)^(-1E15),"e")'))

    def test_double_minus_zero_to_the_power_zero_is_one(self) -> None:
        self.assertEqual("1", _local("(0.0*-1)^0"))
        self.assertEqual("1", _local("(-(0.0))^0"))
        self.assertTrue(_is_error("0^0"))
        self.assertTrue(_is_error("0.0^0"))
        self.assertTrue(_is_error("(0*-1)^0"))
        self.assertEqual("0", _local("(0.0*-1)^0.5"))


class FixF3NonFiniteFunctionTests(unittest.TestCase):
    """F3: functions given an Infinity or a NaN."""

    def test_functions_that_answer_a_fixed_value(self) -> None:
        for argument in ("0/0", "-(0/0)", "1/0", "-1/0"):
            self.assertEqual("0", _local(f"DEGREES({argument})"))
            self.assertEqual("0", _local(f"RADIANS({argument})"))
            self.assertEqual("1", _local(f"TANH({argument})"))
            self.assertEqual("0", _local(f"ODD({argument})"))
        self.assertEqual("Infinity", _local("EVEN(1/0)"))
        self.assertEqual("-Infinity", _local("EVEN(-1/0)"))
        self.assertEqual("NaN", _local("EVEN(0/0)"))
        self.assertEqual("1.5707963267948966", _local("ATAN(1/0)"))
        self.assertEqual("-1.5707963267948966", _local("ATAN(-1/0)"))

    def test_atan_of_nan_is_refused_not_an_error(self) -> None:
        self.assertTrue(_local("ATAN(0/0)").startswith("LOCAL-REJECT"))
        self.assertTrue(_local("ISERROR(ATAN(0/0))").startswith("LOCAL-REJECT"))  # a runtime error would make ISERROR say True

    def test_iseven_and_isodd_of_nan_are_the_error_not_a_crash(self) -> None:
        for function in ("ISEVEN", "ISODD"):
            self.assertTrue(_is_error(f"{function}(0/0)"))
            self.assertTrue(_is_error(f"{function}(-(0/0))"))
            self.assertEqual("True", _local(f"ISERROR({function}(0/0))"))

    def test_ceiling_of_zero_by_infinity_and_divide_by_nan(self) -> None:
        self.assertEqual("0", _local("CEILING(0,1/0)"))
        self.assertTrue(_is_error("CEILING(1,1/0)"))
        self.assertEqual("BLANK", _local("DIVIDE(1,0/0)"))
        self.assertEqual("0", _local("DIVIDE(1,1/0)"))
        self.assertEqual("True", _local("ISBLANK(DIVIDE(1,0/0))"))

    def test_quotient_of_a_non_finite_number_is_the_error(self) -> None:
        self.assertTrue(_is_error("ISBLANK(IF(TRUE(),QUOTIENT(0/0,1)))"))
        self.assertTrue(_is_error("ISBLANK(IF(TRUE(),QUOTIENT(1,0/0)))"))
        self.assertEqual("0", _local("QUOTIENT(1,1/0)"))

    def test_acot_of_the_two_nans(self) -> None:
        self.assertEqual("3.141592653589793", _local("ACOT(0/0)"))
        self.assertEqual("0", _local("ACOT(-(0/0))"))


class FixF4BlankFirstArgumentTests(unittest.TestCase):
    """F4: a BLANK first argument does not skip the second."""

    def test_rounding_and_text_and_date_functions_read_the_second_argument(self) -> None:
        for function in ("ROUND", "ROUNDUP", "ROUNDDOWN", "LEFT", "RIGHT", "REPT", "EDATE", "EOMONTH"):
            for bad in ("0/0", "1/0", '"a"', '""'):
                self.assertEqual("e", _local(f'IFERROR({function}(BLANK(),{bad}),"e")'), f"{function}(BLANK(),{bad})")
            self.assertEqual("BLANK", _local(f'IFERROR({function}(BLANK(),BLANK()),"e")'))
            self.assertEqual("BLANK", _local(f'IFERROR({function}(BLANK(),1),"e")'))

    def test_a_negative_second_argument(self) -> None:
        self.assertEqual("e", _local('IFERROR(LEFT(BLANK(),-1),"e")'))
        self.assertEqual("e", _local('IFERROR(RIGHT(BLANK(),-1),"e")'))
        self.assertEqual("BLANK", _local('IFERROR(REPT(BLANK(),-1),"e")'))
        self.assertEqual("BLANK", _local('IFERROR(ROUND(BLANK(),-1),"e")'))

    def test_quotient_and_mround_with_a_text_second_argument(self) -> None:
        for function in ("QUOTIENT", "MROUND"):
            self.assertEqual("e", _local(f'IFERROR({function}(BLANK(),"a"),"e")'))
            self.assertEqual("BLANK", _local(f'IFERROR({function}(BLANK(),0/0),"e")'))
        self.assertEqual("e", _local('IFERROR(QUOTIENT(BLANK(),BLANK()),"e")'))
        self.assertEqual("BLANK", _local('IFERROR(MROUND(BLANK(),BLANK()),"e")'))

    def test_mod_ceiling_floor_bitand_are_blank_beside_a_non_finite_second(self) -> None:
        for function in ("MOD", "CEILING", "FLOOR", "BITAND"):
            self.assertEqual("BLANK", _local(f'IFERROR({function}(BLANK(),0/0),"e")'))
            self.assertEqual("BLANK", _local(f'IFERROR({function}(BLANK(),1/0),"e")'))
            self.assertEqual("e", _local(f'IFERROR({function}(BLANK(),"a"),"e")') if function != "BITAND" else "e")
        self.assertEqual("BLANK", _local('IFERROR(BITAND(BLANK(),"a"),"e")'))
        self.assertEqual("e", _local('IFERROR(MOD(BLANK(),BLANK()),"e")'))
        self.assertEqual("BLANK", _local('IFERROR(CEILING(BLANK(),BLANK()),"e")'))


class FixF5CurrencyTests(unittest.TestCase):
    """F5: Currency range, wrap and type."""

    def test_currency_times_a_double_date_or_text_is_checked_for_range(self) -> None:
        for expression in ("CURRENCY(9E14)*2.0", "CURRENCY(1E14)*SUM(Facts[Sales])", "CURRENCY(1)*1E15", 'CURRENCY(1)*"1E15"',
                           "CURRENCY(1E14)*DATE(2020,1,1)", "CURRENCY(1E14)*1E300"):
            self.assertTrue(_is_error(expression), expression)
        self.assertEqual("900000000000000", _local("CURRENCY(1)*9E14").split(".")[0])

    def test_currency_times_a_whole_number_still_wraps(self) -> None:
        self.assertEqual("-844674407370955.1616", _local("CURRENCY(1E14)*10"))

    def test_sumx_and_averagex_of_a_currency_body_wrap(self) -> None:
        self.assertEqual("-844674407370955.1616", _local("SUMX({1,2},CURRENCY(5E14))"))
        self.assertEqual("-422337203685477.5808", _local("AVERAGEX({1,2},CURRENCY(5E14))"))
        self.assertEqual("-1.1616", _local("SUMX({1,2},CURRENCY(922337203685477))"))

    def test_currency_of_a_double_out_of_range_is_the_error_a_whole_number_wraps(self) -> None:
        self.assertTrue(_is_error("CURRENCY(1E15)"))
        self.assertTrue(_is_error("CONVERT(1E15,CURRENCY)"))
        self.assertEqual("True", _local("ISERROR(CURRENCY(1E15))"))
        self.assertEqual("-922337203685477.1616", _local("CURRENCY(922337203685478)"))
        self.assertEqual("922337203685477.1616", _local("CURRENCY(-922337203685478)"))

    def test_a_type_test_of_a_constant_is_not_evaluated_but_one_that_reads_data_is(self) -> None:
        self.assertEqual("True", _local("ISCURRENCY(CURRENCY(1E15))"))
        self.assertTrue(_is_error("ISCURRENCY(CURRENCY(MAX(Facts[Quantity])*1E15))"))

    def test_currency_type_sees_through_a_sign(self) -> None:
        self.assertEqual("1.3333", _local('IFERROR(+CURRENCY(2)/- 1.5*-TRUE(),"e")'))

    def test_arithmetic_overflow_inside_a_type_test_is_still_an_error(self) -> None:
        self.assertTrue(_is_error("ISNUMBER((1/0)*(CURRENCY(2)))"))
        self.assertTrue(_is_error("ISNUMBER(CURRENCY(1E15)*2)"))


_ARITHMETIC_ERROR = "LOCAL-REJECT"


def _numeric_equal(expression: str, expected: str) -> bool:
    return float(_local(expression)) == float(expected)


class FixBitHugeValueTests(unittest.TestCase):
    """A value far outside the Int64 range is the too-large error in every bit function, not a crash."""

    def test_huge_values_are_the_error_in_either_position(self) -> None:
        for function in ("BITAND", "BITOR", "BITXOR", "BITLSHIFT", "BITRSHIFT"):
            for expression in (f"{function}(1E300,1)", f"{function}(1,1E300)", f"{function}(1E19,1)", f"{function}(1,1E19)"):
                result = _local(expression)
                self.assertTrue(result.startswith("LOCAL-REJECT"), f"{expression}: {result}")
                self.assertIn("too large or too small", result, expression)

    def test_ordinary_values_still_work(self) -> None:
        self.assertEqual("8", _local("BITAND(12,10)"))
        self.assertEqual("14", _local("BITOR(12,10)"))


class FixQuotientBlankNumeratorTests(unittest.TestCase):
    """A BLANK numerator: the divisor only has to convert; a zero divisor is fine, an actual BLANK divisor is the error."""

    def test_any_convertible_divisor_gives_blank(self) -> None:
        for divisor in ("0", '"0"', "FALSE()", "0.0*-1", "1/0", "0/0", "2", '"2"', "TRUE()", "0.5"):
            self.assertEqual("BLANK", _local(f"QUOTIENT(BLANK(),{divisor})"), divisor)

    def test_a_blank_divisor_and_a_text_divisor_are_errors(self) -> None:
        self.assertIn("Division by zero", _local("QUOTIENT(BLANK(),BLANK())"))
        self.assertIn("Cannot convert", _local('QUOTIENT(BLANK(),"a")'))

    def test_every_kind_of_blank_numerator(self) -> None:
        for numerator in ("IF(1=2,1)", "COUNTROWS(FILTER(Facts,FALSE()))", "SELECTEDVALUE(Facts[Region])", "MIN(Facts[Quantity])*BLANK()"):
            self.assertEqual("BLANK", _local(f"QUOTIENT({numerator},0)"), numerator)

    def test_a_zero_numerator_and_a_blank_divisor_stay_errors(self) -> None:
        self.assertTrue(_is_error("QUOTIENT(0,0)"))
        self.assertTrue(_is_error("QUOTIENT(1,BLANK())"))

    def test_no_top_level_refusal_around_it(self) -> None:
        self.assertEqual("z", _local('QUOTIENT(BLANK(),0)&"z"'))
        self.assertEqual("x", _local('COALESCE(QUOTIENT(BLANK(),0),"x")'))
        self.assertEqual("BLANK", _local('IFERROR(QUOTIENT(BLANK(),0),"e")'))
        self.assertEqual("True", _local("ISBLANK(QUOTIENT(BLANK(),0))"))
        self.assertEqual("False", _local("ISERROR(QUOTIENT(BLANK(),0))"))


_SCANNED_BLANKS = (
    "COUNTROWS(FILTER(Facts,FALSE()))",
    "COUNTROWS(FILTER(ALL(Facts),1=2))",
    "SUMX(FILTER(Facts,FALSE()),1)",
    "MAXX(FILTER(Facts,FALSE()),1)",
    "COUNTX(FILTER(Facts,FALSE()),1)",
    "COUNTROWS(FILTER(Facts,FALSE()))*1",
    "COALESCE(COUNTROWS(FILTER(Facts,FALSE())),BLANK())",
)
_STATIC_BLANKS = (
    "BLANK()",
    "BLANK()+BLANK()",
    "SUM(Facts[Quantity])*BLANK()",
    "MAX(Facts[Quantity])*BLANK()",
    "COUNTROWS(FILTER(Facts,FALSE()))*BLANK()",
    "IF(1=2,1)",
    "IF(1=2,SUM(Facts[Quantity]))",
    "IF(1=1,BLANK())",
    "SELECTEDVALUE(Facts[Region])",
)


class FixBitBlankKindTests(unittest.TestCase):
    """BITAND / BITLSHIFT / BITRSHIFT beside a static BLANK skip the other operand; beside a scanned BLANK they validate it."""

    def test_static_blank_skips_the_other_operand_in_bitand_either_position(self) -> None:
        for blank in _STATIC_BLANKS:
            for other in ('"a"', "1/0", "0/0", "1E300", "2^63", "1", "TRUE()"):
                self.assertEqual("BLANK", _local(f"BITAND({blank},{other})"), f"BITAND({blank},{other})")
                self.assertEqual("BLANK", _local(f"BITAND({other},{blank})"), f"BITAND({other},{blank})")

    def test_static_blank_first_position_of_the_shifts(self) -> None:
        for function in ("BITLSHIFT", "BITRSHIFT"):
            for blank in _STATIC_BLANKS:
                for other in ('"a"', "0/0", "1/0", "1E300"):
                    self.assertEqual("BLANK", _local(f"{function}({blank},{other})"), f"{function}({blank},{other})")

    def test_a_var_holding_a_static_blank(self) -> None:
        self.assertEqual("BLANK", _local('VAR b=BLANK() RETURN BITAND(b,"a")'))
        self.assertEqual("BLANK", _local('VAR b=BLANK() RETURN BITLSHIFT(b,1/0)'))
        self.assertEqual("BLANK", _local('VAR b=BLANK() RETURN BITAND(1E300,b)'))

    def test_the_other_operand_is_not_even_evaluated(self) -> None:
        self.assertEqual("False", _local('ISERROR(BITAND(BLANK(),ERROR("x")))'))
        self.assertEqual("False", _local('ISERROR(BITLSHIFT(BLANK(),ERROR("x")))'))
        self.assertEqual("False", _local('ISERROR(BITAND(ERROR("x"),BLANK()))'))

    def test_scanned_blank_validates_the_other_operand(self) -> None:
        for blank in _SCANNED_BLANKS:
            for bad, text in (('"a"', "Cannot convert"), ("0/0", "too large"), ("1/0", "too large"), ("1E300", "too large")):
                for expression in (f"BITAND({blank},{bad})", f"BITAND({bad},{blank})", f"BITLSHIFT({blank},{bad})", f"BITRSHIFT({blank},{bad})"):
                    result = _local(expression)
                    self.assertTrue(result.startswith("LOCAL-REJECT") and text in result, f"{expression}: {result}")
            for good in ('"2"', "1.5", "1", "TRUE()"):
                for expression in (f"BITAND({blank},{good})", f"BITAND({good},{blank})", f"BITLSHIFT({blank},{good})", f"BITRSHIFT({blank},{good})"):
                    self.assertEqual("BLANK", _local(expression), expression)

    def test_a_var_holding_a_scanned_blank(self) -> None:
        self.assertIn("Cannot convert", _local('VAR c=COUNTROWS(FILTER(Facts,FALSE())) RETURN BITAND(c,"a")'))
        self.assertEqual("BLANK", _local('VAR c=COUNTROWS(FILTER(Facts,FALSE())) RETURN BITAND(c,"2")'))

    def test_shifts_with_a_blank_second_operand_are_unchanged(self) -> None:
        self.assertEqual("1", _local("BITLSHIFT(1,BLANK())"))
        self.assertEqual("1", _local("BITRSHIFT(1,BLANK())"))
        for expression in ('BITLSHIFT("a",BLANK())', 'BITLSHIFT("a",COUNTROWS(FILTER(Facts,FALSE())))', "BITLSHIFT(0/0,BLANK())",
                           "BITLSHIFT(1E300,BLANK())", "BITRSHIFT(1E300,COUNTROWS(FILTER(Facts,FALSE())))"):
            self.assertTrue(_is_error(expression), expression)

    def test_bitor_and_bitxor_are_the_same_for_both_kinds_of_blank(self) -> None:
        for blank in ("BLANK()", "COUNTROWS(FILTER(Facts,FALSE()))"):
            for function in ("BITOR", "BITXOR"):
                self.assertEqual("1", _local(f"{function}({blank},1)"))
                self.assertTrue(_is_error(f'{function}({blank},"a")'))
                self.assertTrue(_is_error(f"{function}({blank},1E300)"))


class FixNegativeZeroPowerTests(unittest.TestCase):
    """A Double minus zero (0.0*-1) to a positive power."""

    _WRONG = "wrong data type"

    def test_one_half_gives_zero_other_fractions_are_the_error(self) -> None:
        self.assertEqual("0", _local("(0.0*-1)^0.5"))
        self.assertEqual("0", _local("POWER(0.0*-1,0.5)"))
        for exponent in ("0.25", "0.75", "1.5", "2.5", "1E-5", "1E-200", "20.5", "41.5"):
            for expression in (f"(0.0*-1)^{exponent}", f"POWER(0.0*-1,{exponent})"):
                result = _local(expression)
                self.assertTrue(result.startswith("LOCAL-REJECT") and self._WRONG in result, f"{expression}: {result}")

    def test_whole_powers(self) -> None:
        for exponent in ("1", "2", "3", "3E9"):
            self.assertEqual("0", _local(f"(0.0*-1)^{exponent}"))
            self.assertEqual("0", _local(f"POWER(0.0*-1,{exponent})"))
        for exponent in ("1E14", "1E15"):
            for expression in (f"(0.0*-1)^{exponent}", f"POWER(0.0*-1,{exponent})"):
                result = _local(expression)
                self.assertTrue(result.startswith("LOCAL-REJECT") and self._WRONG in result, f"{expression}: {result}")
        self.assertEqual("1", _local("(0.0*-1)^0"))
        self.assertEqual("1", _local("POWER(0.0*-1,0)"))

    def test_the_unmeasured_stretch_is_refused_not_guessed(self) -> None:
        for exponent in ("1E10", "1E13", "5E9"):
            result = _local(f"(0.0*-1)^{exponent}")
            self.assertTrue(result.startswith("LOCAL-REJECT") and "not modelled" in result, f"{exponent}: {result}")

    def test_negative_exponent_keeps_its_refusal(self) -> None:
        self.assertTrue(_is_error("(0.0*-1)^-1"))
        self.assertTrue(_is_error("(0.0*-1)^-0.5"))

    def test_a_plain_zero_is_unchanged(self) -> None:
        self.assertEqual("0", _local("0^0.5"))
        self.assertEqual("0", _local("0^1.5"))
        self.assertEqual("0", _local("(0*-1)^0.25"))
        self.assertTrue(_is_error("(-1)^1E14"))

    def test_consequences(self) -> None:
        self.assertTrue(_local("(0.0*-1)^(0.0*-1)^1E15").startswith("LOCAL-REJECT"))
        self.assertTrue(_numeric_equal("((0.0*-1)^(0.0*-1))^1E15", "1"))
        self.assertEqual("1", _local("(0.0*-1)^(0.0*-1)^41"))
        self.assertTrue(_local("(0.0*-1)^SUM(Facts[Sales])").startswith("LOCAL-REJECT"))
        self.assertEqual("e", _local('IFERROR((0.0*-1)^1E-200-(0*-1)+COUNTROWS(Facts),"e")'))
        self.assertTrue(_local("(0.0*-1)^0.5^- 1.5").startswith("LOCAL-REJECT"))
        self.assertEqual("True", _local("ISNUMBER((0.0*-1)^0.25)"))
        self.assertEqual("False", _local("ISBLANK((0.0*-1)^0.25)"))


class FixTypeTestOfOperatorOverflowTests(unittest.TestCase):
    """A type test answers by the static type when the arithmetic, ^ or POWER inside it fails; a function argument failure still propagates."""

    def test_power_failures(self) -> None:
        for expression, expected in (
            ("ISNUMBER(0^-1)", "True"), ("ISNUMBER(0^-3E15)", "True"), ("ISDOUBLE(0^-1)", "True"), ("ISDOUBLE(POWER(0,-1))", "True"),
            ("ISINT64(0^-1)", "False"), ("ISTEXT(0^-1)", "False"), ("ISLOGICAL(0^-1)", "False"), ("ISERROR(ISNUMBER(0^-1))", "False"),
            ("ISNUMBER(DATE(2020,1,1)^-1.5*- 1E15)", "True"), ("ISNUMBER((1-1)^+3*-1E15)", "True"),
        ):
            self.assertEqual(expected, _local(expression), expression)

    def test_currency_range_failures(self) -> None:
        for expression, expected in (
            ("ISNUMBER(CURRENCY(1E15)*1E10)", "True"), ("ISCURRENCY((1E300)*(CURRENCY(5E14)))", "True"),
            ("ISCURRENCY((CURRENCY(9E14))*(1.5))", "True"), ("ISCURRENCY((1E19)*(CURRENCY(1)))", "True"),
            ("ISINT64((CURRENCY(9E14))*(2.0))", "False"), ("ISDOUBLE((CURRENCY(1))*(-1E15))", "False"),
            ("ISCURRENCY(CURRENCY(1E15)*1E10+1)", "True"), ("ISCURRENCY(ABS(CURRENCY(1E15)*1E10))", "True"),
        ):
            self.assertEqual(expected, _local(expression), expression)

    def test_a_function_argument_failure_still_propagates(self) -> None:
        self.assertTrue(_is_error("ISNUMBER(SQRT(-1))"))
        self.assertTrue(_is_error("ISNUMBER((1/0)*(CURRENCY(2)))"))
        self.assertTrue(_is_error("ISNUMBER(CURRENCY(1E15)*2)"))
        self.assertTrue(_is_error("ISCURRENCY(CURRENCY(MAX(Facts[Quantity])*1E15))"))

    def test_a_bare_failure_is_unchanged(self) -> None:
        self.assertTrue(_is_error("CURRENCY(1E15)*1E10"))
        self.assertTrue(_is_error("0^-1"))
        self.assertEqual("True", _local("ISERROR(0^-1)"))
        self.assertEqual("e", _local('IFERROR(CURRENCY(1E15)*1E10,"e")'))


class FixAPowerFailureInTypeTestsTests(unittest.TestCase):
    """A: a ^ or POWER failure is hidden from a type test only when both operands are finite constants."""

    def test_finite_constant_operands_answer_statically(self) -> None:
        for expression in ("ISNUMBER((-1)^0.5)", "ISNUMBER(2^1E5)", "ISNUMBER(1E300^1E300)", "ISNUMBER(DATE(2020,1,1)^1E15)",
                           "ISNUMBER((0.0*-1)^0.25)", "ISNUMBER(0^-1)", "ISDOUBLE(POWER((-1),0.5))",
                           "ISNUMBER((1/0)^-2)", "ISNUMBER((1/0)^0)", "ISNUMBER((0/0)^-2)"):
            self.assertEqual("True", _local(expression), expression)
        self.assertEqual("False", _local("ISCURRENCY((-1)^0.5)"))

    def test_a_non_finite_operand_lets_the_error_through(self) -> None:
        for expression in ("ISNUMBER((1/0)^2)", "ISNUMBER((0/0)^0.5)", "ISNUMBER((0/0)^1E15)", "ISNUMBER((-1/0)^-1.5)", "ISNUMBER(2^-(0/0))",
                           "ISCURRENCY((1/0)^2)", "ISNUMBER(POWER(2,1/0))", "ISNUMBER((1/0)^0.5+1)", "ISCURRENCY(CURRENCY(-1)^(1/0))",
                           "ISCURRENCY((1/0)^CURRENCY(922337203685477))", "ISCURRENCY((0/0)^(CURRENCY(9E14)))"):
            self.assertTrue(_is_error(expression), expression)

    def test_a_row_dependent_operand_lets_the_error_through(self) -> None:
        for expression in ("ISNUMBER(SUM(Facts[Sales])^1E5)", "ISNUMBER(MIN(Facts[Sales])^0.5)", "ISNUMBER(POWER(MIN(Facts[Sales]),1.5))",
                           "ISDOUBLE(MIN(Facts[Sales])^0.5)", "ISNUMBER(COUNTROWS(Facts)/SUM(Facts[Sales])*+MIN(Facts[Sales])^0.5)"):
            self.assertTrue(_is_error(expression), expression)
        self.assertEqual("False", _local("ISCURRENCY(SUM(Facts[Sales])^1E5)"))
        self.assertIn("not modelled", _local("ISNUMBER(MIN(Facts[Sales])^0.5+1)"))  # Power BI: True, but ISNUMBER(2/0+0.0^0.0) is the error

    def test_arithmetic_around_a_failing_power_is_refused(self) -> None:
        for expression in ("ISNUMBER(+1.5+0^+COUNTROWS(Facts)^1*-0)", "ISNUMBER(2/0+0.0^+(0.0*-1))", "ISNUMBER(1.5^- 0.0^-1E15/2)", "ISNUMBER(0^(BLANK()/2))"):
            self.assertIn("not modelled", _local(expression), expression)
        self.assertEqual("False", _local("ISNUMBER(COUNTROWS(FILTER(Facts,FALSE()))^-1)"))


class FixBPowerUnderflowTests(unittest.TestCase):
    def test_a_result_below_the_double_range_is_zero(self) -> None:
        self.assertEqual("0z", _local('IFERROR(1E-200^2&"z","e")'))
        self.assertEqual("0z", _local('IFERROR(1E-200^3&"z","e")'))
        self.assertEqual("0", _local("POWER(1E-200,3)"))
        self.assertEqual("0z", _local('IFERROR((-1E-200)^2&"z","e")'))

    def test_a_negative_power_is_one_over_the_positive_one(self) -> None:
        self.assertEqual("0z", _local('(2^-0.5-(0.7071067811865475))&"z"'))
        self.assertTrue(_is_error("POWER(1E-200,-1.6)"))

    def test_a_negative_result_is_refused(self) -> None:
        self.assertIn("not modelled", _local("(-1E-200)^3"))


class FixCDoubleTextTests(unittest.TestCase):
    """C: a Double prints from its exact binary value, rounded half away from zero at 15 significant digits."""

    def test_rows(self) -> None:
        for expression, expected in (
            ("(999999999999998.5)", "999999999999999z"), ("(123456789012344.5)", "123456789012345z"), ("(99999999999999.45)", "99999999999999.5z"),
            ("(0.1234567890123455)", "0.123456789012345z"), ("(0.5+CURRENCY(-922337203685477))", "-922337203685477z"),
            ("(CURRENCY(9E14)-1.5)", "899999999999999z"), ("(0.5+CURRENCY(1E14))", "100000000000001z"), ("(1E15-1.5)", "999999999999999z"),
            ("(1E15-1.5+0)", "999999999999999z"), ("(-1.5/(0/0)^-0.0+1E15)", "999999999999999z"), ("(1.5+CURRENCY(9E14))", "900000000000002z"),
            ("(123456789012345.5)", "123456789012346z"),
        ):
            self.assertEqual(expected, _local(f'{expression}&"z"'), expression)

    def test_currency_text_is_unchanged(self) -> None:
        self.assertEqual("-844674407370955.1616", _local("SUMX({1,2},CURRENCY(5E14))"))


class FixDSignedZeroThroughLogicalOperandsTests(unittest.TestCase):
    def test_double_minus_zero(self) -> None:
        for expression in ("(-(TRUE())*0.0)", "(TRUE()*(0.0*-1))", "(-TRUE()*0.0)", "(- TRUE()*SUM(Facts[Sales])^+(0/0))",
                           "(- COUNTROWS(Facts)*TRUE()/(1/0))", "(FALSE()/CURRENCY(-9E14))", "(FALSE()/-5)", "(-(FALSE())*0.0)"):
            self.assertEqual("-0z", _local(f'{expression}&"z"'), expression)

    def test_unsigned_zero_stays(self) -> None:
        for expression in ("(TRUE()*0.0)", "(-(1*0))", "(-TRUE()*0)", "(-(TRUE()*0))", "(-FALSE())"):
            self.assertEqual("0z", _local(f'{expression}&"z"'), expression)
        for expression in ("(-(1*0.0))", "(-1*0.0)", "(0/-5)", "(0/CURRENCY(-9E14))"):
            self.assertEqual("-0z", _local(f'{expression}&"z"'), expression)


class FixEStaticTypeOfLogicalArithmeticTests(unittest.TestCase):
    def test_true_false_in_arithmetic_is_int64(self) -> None:
        self.assertEqual("True", _local("ISINT64(TRUE()*1)"))
        self.assertEqual("False", _local("ISDOUBLE(TRUE()*1)"))
        self.assertEqual("True", _local("ISINT64(TRUE()+1)"))
        self.assertEqual("False", _local("ISDOUBLE(TRUE()+1)"))
