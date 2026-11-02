"""Iteration 108: convert-currency-9 (Task 19).

Plan: docs/plans/2026-11-02-convert-currency-9.md
Parts:
  - Part G (piece 1): a Double of 1E15 or more concatenates with an exponent; an integer stays whole.
  - Part B: Currency with Infinity or NaN. * with a Currency and an Infinity or NaN is an error (either order, Currency 0 too);
    / with a Currency numerator and a NaN or 0 denominator is an error; + and - keep their answers; a DIVIDE that gives BLANK is
    BLANK; the type tests of these errors are errors; ISERROR is True and IFERROR takes the alternate; the errors stop row
    iterators; CONVERT of Infinity, NaN or 1E300 to CURRENCY or INTEGER is an error.
"""
from __future__ import annotations

import unittest
from decimal import Decimal, InvalidOperation

from tools import dax_oracle_diff as dax


def _local(expression: str) -> str:
    return dax.local(expression)


def _is_error(expression: str) -> bool:
    return _local(expression).startswith("LOCAL-REJECT")


def _number_is(expected: str, expression: str) -> bool:
    """A Currency shows four decimals (2.0000), so a number is compared as a number, and Infinity by its text."""
    actual = _local(expression)
    if actual.startswith("LOCAL-"):
        return False
    try:
        return Decimal(actual) == Decimal(expected)
    except InvalidOperation:
        return actual == expected


class PartBCurrencyTimesInfinityOrNaNTests(unittest.TestCase):
    """Part B: a Currency times Infinity or NaN is an error, in either order and for Currency 0."""

    def test_currency_times_infinity_or_nan_is_error(self) -> None:
        for expression in (
            "CURRENCY(2)*(1/0)", "(1/0)*CURRENCY(2)", "CURRENCY(0)*(1/0)", "(1/0)*CURRENCY(0)",
            "CURRENCY(2)*(0/0)", "(0/0)*CURRENCY(2)", "(0/0)*CURRENCY(0)", "CURRENCY(0)*(0/0)",
            "(1/0*0)*CURRENCY(2)", "CURRENCY(0)*(1/0*0)", "(0/0)*CURRENCY(2)*(2.5)",
            "(SUM(Facts[Quantity])*CURRENCY(1))*(1/0*0)", "CURRENCY(2)*(-1/0)",
        ):
            with self.subTest(expression):
                self.assertTrue(_is_error(expression), _local(expression))

    def test_error_is_seen_by_type_tests_and_ifs(self) -> None:
        for expression in (
            "ISNUMBER(CURRENCY(2)*(1/0))", "ISTEXT((1/0)*(CURRENCY(2)))", "ISLOGICAL(CURRENCY(2)*(0/0))",
            "ISDOUBLE((0/0)*(CURRENCY(2)))", "ISINT64((CURRENCY(2))*(0/0))",
            "ISCURRENCY((CURRENCY(2))*(0/0))", "IF((0/0)*(CURRENCY(0)),1,2)",
        ):
            with self.subTest(expression):
                self.assertTrue(_is_error(expression), _local(expression))

    def test_iserror_is_true_and_iferror_takes_alternate(self) -> None:
        self.assertEqual("True", _local("ISERROR(CURRENCY(2)*(1/0))"))
        self.assertEqual("True", _local("ISERROR((0/0)*(CURRENCY(0)))"))
        self.assertEqual("7", _local("IFERROR(CURRENCY(2)*(1/0),7)"))
        self.assertEqual("7", _local("IFERROR((0/0)*CURRENCY(0),7)"))

    def test_error_stops_row_iterators(self) -> None:
        for expression in (
            "SUMX(Facts,(0/0)*(CURRENCY(0)))", "MAXX(Facts,(1/0)*(CURRENCY(2)))", "AVERAGEX(Facts,(1/0)*(CURRENCY(2)))",
            "COUNTX(Facts,(CURRENCY(2))*(0/0))",
            "SUMX(ADDCOLUMNS(Facts,\"q\",(CURRENCY(2))*(0/0)),[q])", "MAXX(ADDCOLUMNS(Facts,\"q\",(CURRENCY(2))*(0/0)),[q])",
            "SUMX(FILTER(Facts,Facts[Quantity]>2),(0/0)*(CURRENCY(0)))",
            "MAXX(Facts,1/0)*CURRENCY(2)",
        ):
            with self.subTest(expression):
                self.assertTrue(_is_error(expression), _local(expression))


class PartBCurrencyDivisionTests(unittest.TestCase):
    """Part B: / with a Currency numerator and a NaN or 0 denominator is an error; an Infinity denominator gives 0."""

    def test_currency_divided_by_nan_or_zero_is_error(self) -> None:
        for expression in ("MINX(Facts,(CURRENCY(0))/(1/0*0))", "CURRENCY(2)/(0/0)", "CURRENCY(-1)/(1/0*0)", "(CURRENCY(2))/(0/0)", "ISCURRENCY((CURRENCY(2))/(0/0))"):
            with self.subTest(expression):
                self.assertTrue(_is_error(expression), _local(expression))

    def test_currency_divided_by_infinity_is_zero(self) -> None:
        self.assertTrue(_number_is("0", "CURRENCY(2)/(1/0)"), _local("CURRENCY(2)/(1/0)"))

    def test_plus_and_minus_keep_their_answers(self) -> None:
        self.assertEqual("-Infinity", _local("CURRENCY(2)-(1/0)"))
        self.assertEqual("Infinity", _local("CURRENCY(2)+(1/0)"))

    def test_divide_that_gives_blank_is_blank(self) -> None:
        self.assertTrue(_number_is("2", "CURRENCY(2)-DIVIDE(1,0)"), _local("CURRENCY(2)-DIVIDE(1,0)"))


class PartBConvertOfInfinityTests(unittest.TestCase):
    """Part B: CONVERT to CURRENCY or INTEGER of Infinity, NaN or 1E300 is the 'too large or too small' error."""

    def test_convert_of_infinity_nan_or_huge_is_error(self) -> None:
        for expression in (
            "CONVERT(1/0,CURRENCY)", "CONVERT(0/0,CURRENCY)", "CONVERT(1E300,CURRENCY)", "CONVERT(1E300,INTEGER)",
            "CONVERT(1/0,INTEGER)", "CONVERT(0/0,INTEGER)",
        ):
            with self.subTest(expression):
                self.assertTrue(_is_error(expression), _local(expression))


if __name__ == "__main__":
    unittest.main()


class PartAConvertTypingTests(unittest.TestCase):
    """Part A: a CONVERT has its target type statically, so the iterator type errors fire whatever the table or branch."""

    def test_string_or_boolean_body_is_error_even_when_branch_untaken_or_table_empty(self) -> None:
        for expression in (
            'SUMX({"a"},CONVERT(1,STRING))',
            'SUMX(FILTER(Facts,FALSE()),CONVERT(1,STRING))',
            'AVERAGEX({1},IF(FALSE(),CONVERT(1,STRING)))',
            'PRODUCTX({1},IF(FALSE(),CONVERT(1,STRING)))',
            'SUMX({1},VAR v=CONVERT(1,BOOLEAN) RETURN v)',
            'STDEVX.P({"a"},IFERROR(CONVERT(0||"",BOOLEAN),CONVERT(0||"",BOOLEAN)))',
            'VARX.S({1},COALESCE(CONVERT(1,STRING),CONVERT(1,STRING)))',
        ):
            with self.subTest(expression=expression):
                self.assertTrue(_is_error(expression))

    def test_date_body_errors_for_product_and_median(self) -> None:
        for expression in (
            'PRODUCTX({1},CONVERT(1,DATETIME))',
            'PRODUCTX({1},IF(TRUE(),CONVERT(1,DATETIME)))',
            'MEDIANX({1,2},IFERROR(CONVERT(0||"",DATETIME),CONVERT(0||"",DATETIME)))',
        ):
            with self.subTest(expression=expression):
                self.assertTrue(_is_error(expression))

    def test_convert_datetime_of_infinity_and_nan_stays_what_it_is(self) -> None:
        # live Power BI (Task 19 review): no clamp; the value stays Infinity or NaN and only prints as a date
        self.assertEqual(_local("-(CONVERT(-1/0,DATETIME))"), "Infinity")
        self.assertEqual(_local("ABS(CONVERT(0/0,DATETIME))"), "NaN")
        self.assertEqual(_local("AVERAGEX({1,2},IF(TRUE(),CONVERT(-1/0,DATETIME)))"), "-Infinity")
        self.assertEqual(_local("ISERROR(CONVERT(0/0,DATETIME))"), "True")
        self.assertEqual(_local('IFERROR(CONVERT(-1/0,DATETIME),"e")'), "e")
        self.assertEqual(_local('SUMX(Facts,IFERROR(CONVERT(Facts[Sales]/0,DATETIME),7))'), "35")

    def test_convert_datetime_too_large_is_refused_not_guessed(self) -> None:
        # Power BI gives 12/31/9999 23:59:59 for Infinity in a plain cell, but a locked item shows an error in CONCATENATEX
        # and BLANK in MINX, so the local engine refuses it until the iterator rule is known.
        self.assertTrue(_is_error("CONVERT(1E300,DATETIME)"))
        self.assertTrue(_is_error("CONVERT(1/0,DATETIME)"))

    def test_convert_boolean_of_blank_is_false_and_empty_text_is_blank(self) -> None:
        self.assertEqual(_local("CONVERT(BLANK(),BOOLEAN)"), "False")
        self.assertEqual(_local('COUNTAX({"a"},CONVERT(BLANK(),BOOLEAN))'), "1")
        self.assertEqual(_local('CONVERT("",BOOLEAN)'), "BLANK")

    def test_convert_boolean_of_spaces_is_error(self) -> None:
        self.assertTrue(_is_error('CONVERT(" ",BOOLEAN)'))

    def test_convert_to_currency_beyond_range_is_an_error_even_in_isblank(self) -> None:
        self.assertTrue(_is_error("ISBLANK(CONVERT(1E300,CURRENCY))"))

    def test_a_date_through_if_stays_a_date_and_variance_stays_numeric(self) -> None:
        self.assertEqual(_local('IF(TRUE(),CONVERT("1/2/2020",DATETIME))'), "01/02/2020 00:00:00")
        self.assertEqual(_local('MINX(VALUES(Facts[Region]),IF(TRUE(),CONVERT("1/2/2020",DATETIME)))'), "01/02/2020 00:00:00")
        self.assertTrue(_number_is("3.5", "VARX.S(Facts,IF(TRUE(),CONVERT(Facts[Quantity],DATETIME)))"))

    def test_type_tests_of_a_converted_date_are_false_without_converting(self) -> None:
        for test in ("ISINTEGER", "ISDOUBLE", "ISCURRENCY", "ISTEXT", "ISLOGICAL"):
            self.assertEqual(_local(f'{test}(CONVERT("3",DATETIME))'), "False", test)
        self.assertTrue(_is_error('ISNUMBER(CONVERT("3",DATETIME))'))

    def test_text_that_is_no_date_is_an_ordinary_error_so_iferror_catches_it(self) -> None:
        self.assertEqual(_local("SUMX(Facts,IFERROR(CONVERT(Facts[Region],DATETIME),7))"), "42")
        self.assertEqual(_local('SUMX(Facts,IFERROR(Facts[Quantity]&"/2/2020"+0,7))'), "42")
        self.assertEqual(_local('ISERROR(CONVERT("a",DATETIME))'), "True")
        self.assertTrue(_is_error('STDEVX.P(FILTER(Facts,FALSE()),VAR v=CONVERT("",DATETIME) RETURN v)'))

    def test_convert_boolean_of_number_text(self) -> None:
        self.assertEqual(_local('CONVERT("3",BOOLEAN)'), "True")
        self.assertEqual(_local('CONVERT("0",BOOLEAN)'), "False")

    def test_currency_sample_statistics_over_one_row_are_division_error(self) -> None:
        self.assertTrue(_is_error("STDEVX.S({1},CONVERT(0,CURRENCY))"))
        self.assertTrue(_is_error("VARX.S({1},CURRENCY(1))"))

    def test_currency_stdev_rounds_to_four_decimals(self) -> None:
        self.assertTrue(_number_is("0.7071", 'STDEVX.S({1,2},CONVERT([Value],CURRENCY))'))


class PartCNeverBlankTests(unittest.TestCase):
    """Part C: ISBLANK of an expression that can never be blank is False without evaluating it (_never_blank)."""

    def test_never_blank_literals_and_functions_are_false(self) -> None:
        for expression in ("ISBLANK(LN(0))", "ISBLANK(SQRT(-1))", "ISBLANK(LOG10(0))", 'ISBLANK("a"*2)'):
            with self.subTest(expression):
                self.assertEqual("False", _local(expression))

    def test_function_of_blank_is_blank(self) -> None:
        self.assertEqual("True", _local("ISBLANK(SQRT(BLANK()))"))
        self.assertEqual("True", _local("ISBLANK(VALUE(BLANK()))"))

    def test_var_argument_is_judged_by_its_expression(self) -> None:
        self.assertEqual("False", _local("VAR q=(CURRENCY(0))/(1/0*0) RETURN ISBLANK(q)"))
        self.assertEqual("False", _local('VAR q=("a"*2) RETURN ISBLANK(q)'))

    def test_currency_divided_by_nan_is_error_inside_isblank(self) -> None:
        self.assertTrue(_is_error("ISBLANK(MAX(Facts[Sales])/LOG10(0))"))

    def test_text_number_currency_divided_by_zero_is_false_when_constant(self) -> None:
        self.assertEqual("False", _local('ISBLANK(("2"*CURRENCY(1))/0)'))


class PartDBlankThatNeedsNoScanCancelsTests(unittest.TestCase):
    """Part D: a BLANK whose working out scans no column values cancels an error or text beside it in * (either side) and in / (left side).

    A right-hand BLANK in / and any BLANK in + never cancel.
    """

    def test_no_scan_blank_cancels_error_or_text(self) -> None:
        for expression in (
            '"a"*SELECTEDVALUE(Facts[Region])', 'SELECTEDVALUE(Facts[Region])*"a"',
            '"a"*SELECTEDVALUE(Facts[Region],BLANK())', 'SELECTEDVALUE(Facts[Region])/"a"',
            '"a"*IF(ISFILTERED(Facts[Region]),1)', '"a"*IF(ISINSCOPE(Facts[Region]),1)',
            '"a"*IF(HASONEVALUE(Facts[Region]),1)', '"a"*(HASONEVALUE(Facts[Region])*BLANK())',
            '"a"*(ISBLANK(1)*BLANK())', '"a"*IF(COUNTROWS(Facts)=0,1)',
            '"a"*IF(SELECTEDVALUE(Facts[Region])="x",1)', '"a"*CALCULATE(IF(ISFILTERED(Facts[Region]),1))',
            '"a"*COALESCE(IF(ISINSCOPE(Facts[Region]),1),BLANK())', 'VAR b=SELECTEDVALUE(Facts[Region]) RETURN "a"*b',
        ):
            with self.subTest(expression):
                self.assertEqual("BLANK", _local(expression))

    def test_scanning_blank_or_right_hand_or_plus_stays_error(self) -> None:
        for expression in (
            '"a"*IF(SUM(Facts[Quantity])<-9,1)', '"a"*SWITCH(SUM(Facts[Quantity]),-9,1)',
            '"a"*IF(COUNTROWS(FILTER(Facts,FALSE()))=0,1)', '"a"*SELECTEDVALUE(Facts[Region],1)',
            '"a"*LOOKUPVALUE(Facts[Quantity],Facts[Region],"zz")',
            '"a"/IF(ISFILTERED(Facts[Region]),1)', '"a"/SELECTEDVALUE(Facts[Region])',
            '"a"+SELECTEDVALUE(Facts[Region])', 'SELECTEDVALUE(Facts[Region])+"a"',
        ):
            with self.subTest(expression):
                self.assertTrue(_is_error(expression), _local(expression))


def _serial(year: int, month: int, day: int) -> Decimal:
    from datetime import date

    return Decimal((date(year, month, day) - date(1899, 12, 30)).days)


class PartETextDatesTests(unittest.TestCase):
    """Part E: text that is a date or a time is a number in arithmetic, VALUE and CONVERT to DOUBLE; CONVERT of text to DATETIME is strict."""

    def test_text_date_is_its_serial_number_in_arithmetic(self) -> None:
        for expression, expected in (
            ('VALUE("2020-01-02")', "43832"), ('"2020-01-02"+0', "43832"), ('0+"2020-01-02"', "43832"),
            ('"2020-01-02"*1', "43832"), ('-"2020-01-02"', "-43832"), ('"2020-01-02"+"2020-01-02"', "87664"),
            ('"1/2/2020"+0', "43832"), ('"13/1/2020"+0', "43843"), ('CONVERT("2020-01-02",DOUBLE)', "43832"),
        ):
            with self.subTest(expression):
                self.assertTrue(_number_is(expected, expression), _local(expression))

    def test_text_time_is_a_fraction_of_a_day(self) -> None:
        for expression in ('"12:30"+0', 'VALUE("12:30")', 'CONVERT("12:30",DOUBLE)'):
            with self.subTest(expression):
                actual = _local(expression)
                self.assertFalse(actual.startswith("LOCAL-"), actual)
                self.assertLess(abs(Decimal(actual) - Decimal("12.5") / Decimal(24)), Decimal("1E-12"), actual)

    def test_date_minus_text_is_a_date_and_text_minus_date_a_number(self) -> None:
        self.assertEqual(_local('DATE(2020,1,1)-"2020-01-02"'), "12/29/1899 00:00:00")
        self.assertEqual(_local('DATE(2020,1,1)+"2020-01-02"'), "01/04/2140 00:00:00")
        self.assertTrue(_number_is("1", '"2020-01-02"-DATE(2020,1,1)'), _local('"2020-01-02"-DATE(2020,1,1)'))
        self.assertEqual(_local('ISDATETIME(DATE(2020,1,1)-"2020-01-02")'), "True")
        self.assertEqual(_local('ISDATETIME("2020-01-02"+0)'), "False")
        self.assertEqual(_local('ISDATETIME("2020-01-02"-DATE(2020,1,1))'), "False")

    def test_text_date_stays_error_for_integer_currency_and_comparison(self) -> None:
        for expression in ('CONVERT("2020-01-02",INTEGER)', 'CONVERT("2020-01-02",CURRENCY)', '"2020-01-02"=43832'):
            with self.subTest(expression):
                self.assertTrue(_is_error(expression), _local(expression))

    def test_text_that_is_no_date_or_time_stays_error(self) -> None:
        for text in ("5%", "TRUE", "", "Jan", "2020-13-01", "2020-01-02T03:04:05"):
            expression = f'"{text}"+0'
            with self.subTest(expression):
                self.assertIn("Cannot convert value", _local(expression))

    def test_month_and_day_text_uses_the_current_year(self) -> None:
        for text in ("1/2", "1-2"):
            expression = f'"{text}"+0'
            with self.subTest(expression):
                self.assertTrue(_number_is(str(_serial(date_today_year(), 1, 2)), expression), _local(expression))
        self.assertEqual(_local('CONVERT("1/2",DATETIME)'), f"01/02/{date_today_year()} 00:00:00")

    def test_convert_datetime_of_text_is_strict(self) -> None:
        self.assertEqual(_local('CONVERT("2020-01-02",DATETIME)'), "01/02/2020 00:00:00")
        self.assertEqual(_local('CONVERT("12:30",DATETIME)'), "12/30/1899 12:30:00")
        for text, shown in (("3", "3"), ("2020", "2020"), (" 7 ", "7"), ("-3", "-3"), ("$5", "$5"), ("1e3", "1e3")):
            expression = f'CONVERT("{text}",DATETIME)'
            with self.subTest(expression):
                self.assertIn(f"Cannot convert value '{shown}' of type Text to type Date.", _local(expression))

    def test_convert_datetime_of_unreadable_text_is_refused(self) -> None:
        for expression in ('CONVERT("1,000",DATETIME)', 'CONVERT("1 1/2",DATETIME)', '"1 1/2"+0'):
            with self.subTest(expression):
                self.assertIn("does not model", _local(expression), _local(expression))


class PartFLogicalOperatorNeverBlankTests(unittest.TestCase):
    """Part F: a logical operator, AND/OR/NOT and a comparison are never BLANK; COALESCE of such an argument is that argument;
    a logical operator's BLANK cancels an error on the left of * or /, or on the right of *, like Part D."""

    def test_isblank_of_logical_product_is_false(self) -> None:
        self.assertEqual("False", _local('ISBLANK((0||"")*(1&&""))'))
        self.assertEqual("False", _local('ISBLANK((1&&"")/(0/0))'))

    def test_coalesce_of_never_blank_first_argument_is_that_argument(self) -> None:
        self.assertEqual("BLANK", _local('COALESCE((2.5&&"")*CURRENCY(2),5)'))
        self.assertEqual("BLANK", _local('COALESCE(1&&"",5)'))
        self.assertEqual("x", _local('COALESCE("x"&(1&&""),5)'))

    def test_logical_blank_cancels_error_on_left_of_divide_and_right_of_times(self) -> None:
        self.assertEqual("BLANK", _local('IFERROR((2.5&&"")/SQRT(-1),"e")'))
        self.assertIn("is not modelled", _local('"a"*(1&&"")'))  # beside a text the logical BLANK is refused, as on main
        self.assertEqual("False", _local('ISERROR((1&&"")/("a"*2))'))

    def test_logical_blank_plus_text_stays_refused(self) -> None:
        self.assertIn("is not modelled", _local('(2.5&&"")+"a"'))


class PartGSignOfZeroNaNAndLargeDoublesTests(unittest.TestCase):
    """Part G: a Double of 1E15 or more in size concatenates with an exponent; an integer stays whole."""

    def test_double_of_1e15_or_more_concatenates_with_exponent(self) -> None:
        self.assertEqual("-3E+15z", _local('((3)*-(1E15))&"z"'))
        self.assertEqual("5E+15z", _local('((1E16)/(2))&"z"'))
        self.assertEqual("1.5E+15z", _local('((1E16)*-(1.5))/-(1E1)&"z"'))

    def test_integer_typed_value_stays_whole(self) -> None:
        self.assertEqual("10000000000000000z", _local('10000000000000000&"z"'))
        self.assertEqual("3000000000000000z", _local('(3000000000000000)&"z"'))


@unittest.expectedFailure  # Part G piece 2 is open: see the report; the Int64 zero has no sign, so the sign needs static types
class PartGSignOfZeroAndNaNOpenTests(unittest.TestCase):
    """Part G piece 2 (open): -0 and NaN text. The Double zero keeps its sign; a NaN prints with or without its sign."""

    def test_signed_zero_concatenates_as_minus_zero(self) -> None:
        self.assertEqual("-0z", _local('((1E-3)*-(0.0))&"z"'))
        self.assertEqual("-0z", _local('(-(0.0))&"z"'))
        self.assertEqual("-0z", _local('((-(0.0))/(0.05))&"z"'))
        self.assertEqual("0z", _local('(0.0)&"z"'))

    def test_division_by_minus_zero_is_minus_infinity(self) -> None:
        self.assertEqual("-infz", _local('(1/(-(0.0)))&"z"'))
        self.assertEqual("infz", _local('(1/(0.0))&"z"'))

    def test_nan_sign_is_kept_by_text(self) -> None:
        self.assertEqual("-nan(ind)z", _local('(0/0)&"z"'))
        self.assertEqual("nanz", _local('(-(0/0))&"z"'))
        self.assertEqual("nanz", _local('(0/-(0.0))&"z"'))
        self.assertEqual("nanz", _local('(1/-(1/0*0))&"z"'))

    def test_format_prints_nan_without_indeterminate_suffix(self) -> None:
        self.assertEqual("nan", _local('FORMAT(-(0.0*-1)/(-(0.0)),"0.00")'))


def date_today_year() -> int:
    from datetime import date

    return date.today().year


class ReviewCorrectionsTests(unittest.TestCase):
    """Corrections after the review of Task 19, each measured in Power BI on three tables."""

    def test_blank_cancels_in_plain_iterators_but_not_beside_a_calculate_in_a_row(self) -> None:
        for expression in (
            'SUMX(Facts,IFERROR(SELECTEDVALUE(Facts[Quantity])*"a",7))',
            'SUMX(VALUES(Facts[Region]),IFERROR(SELECTEDVALUE(Facts[Quantity])*"a",7))',
            'MAXX(ADDCOLUMNS(VALUES(Facts[Region]),"q",IFERROR(SELECTEDVALUE(Facts[Quantity])*"a",7)),[q])',
            'IFERROR(CALCULATE(SELECTEDVALUE(Facts[Quantity]))*"a",7)',
        ):
            with self.subTest(expression):
                self.assertEqual("BLANK", _local(expression))
        for expression in (
            'SUMX(VALUES(Facts[Region]),CALCULATE(IFERROR(SELECTEDVALUE(Facts[Quantity])*"a",7)))',
            'SUMX(VALUES(Facts[Region]),IFERROR(CALCULATE(SELECTEDVALUE(Facts[Quantity]))*"a",7))',
        ):
            with self.subTest(expression):
                self.assertEqual("21", _local(expression))

    def test_calculate_with_only_all_filters_does_not_block_the_cancel(self) -> None:
        self.assertEqual("BLANK", _local('CALCULATE(IFERROR(SQRT(-1)*SELECTEDVALUE(Facts[Region]),"e"),ALL(Facts))'))
        self.assertEqual("7", _local('CALCULATE(IFERROR(SELECTEDVALUE(Facts[Quantity])*"a",7),Facts[Region]="East")'))

    def test_isblank_of_a_never_blank_sum_with_data_is_false(self) -> None:
        for expression in (
            "ISBLANK(LN(0)+SUM(Facts[Sales]))", "ISBLANK(MAX(Facts[Sales])+SQRT(-1))",
            "ISBLANK(SQRT(-1)/SELECTEDVALUE(Facts[Quantity],1))",
        ):
            with self.subTest(expression):
                self.assertEqual("False", _local(expression))

    def test_isblank_still_sees_a_currency_division_by_zero_of_data(self) -> None:
        self.assertTrue(_is_error("ISBLANK((CURRENCY(Facts[Quantity])/0)+1)"))
        self.assertTrue(_is_error("ISBLANK(2/(CURRENCY(Facts[Quantity])/0))"))

    def test_currency_power_of_infinity_is_not_refused(self) -> None:
        self.assertEqual("True", _local("ISERROR(CURRENCY(2)^(1/0))"))
        self.assertEqual("False", _local("ISBLANK((0/0)^(CURRENCY(2)))"))

    def test_a_double_of_1e15_or_more_is_text_with_an_exponent_everywhere(self) -> None:
        for expression, expected in (
            ("LEFT(1E15,3)", "1E+"), ("LEN(1E16)", "5"), ('SUBSTITUTE(1E16,"1","x")', "xE+x6"),
            ('EXACT(1E15*1,"1E+15")', "True"), ('CONCATENATE(1E15+1,"z")', "1E+15z"), ("CONVERT(1E15,STRING)", "1E+15"),
            ("LEN(MAX(1E15,1))", "5"), ("LEN(VAR v=1E15 RETURN v)", "5"), ("LEN(IF(TRUE(),1E15))", "5"), ("UPPER(1E15)", "1E+15"),
            ('CONCATENATEX(Facts,1E16,"|",Facts[Quantity],ASC,Facts[Sales],ASC)', "|".join(["1E+16"] * 6)),
        ):
            with self.subTest(expression):
                self.assertEqual(expected, _local(expression))

    def test_integer_values_of_that_size_stay_whole_in_text_functions(self) -> None:
        self.assertEqual("16", _local("LEN(1000000000000000)"))
        self.assertEqual("1E+15", _local("1E15+1&\"\""))


class SecondReviewCorrectionsTests(unittest.TestCase):
    """Corrections after the second fresh batch against Power BI."""

    def test_isblank_does_not_swallow_a_column_read_without_a_row_context(self) -> None:
        for expression in (
            'ISBLANK(-((VALUE("x"))&(CURRENCY(Facts[Quantity]))))',
            'VAR q=(VALUE("x"))-(CURRENCY(Facts[Quantity])) RETURN ISBLANK(q)',
            'ISBLANK(("a"*2-CURRENCY(Facts[Quantity]))+1)',
        ):
            with self.subTest(expression):
                self.assertIn("A single value for column 'Quantity'", _local(expression))

    def test_coalesce_of_a_var_is_judged_by_its_expression(self) -> None:
        self.assertEqual("BLANK", _local('VAR q=(1&&"")/(SIN("a")) RETURN COALESCE(q,5)'))
        self.assertEqual("BLANK", _local('VAR q=(1&&"")/(MAX(Facts[Quantity])) RETURN COALESCE(q,5)'))

    def test_abs_is_never_blank_by_its_operand(self) -> None:
        self.assertEqual("False", _local('ISBLANK(ABS((1&&"")/(VALUE("x"))))'))

    def test_date_made_from_numbers_keeps_variance_numeric_over_a_column(self) -> None:
        self.assertAlmostEqual(2.91666666666667, float(_local("VARX.P(Facts,COALESCE(CONVERT(Facts[Quantity],DATETIME),0))")), places=10)
        self.assertAlmostEqual(1.87082869338697, float(_local("STDEVX.S(Facts,1+IF(TRUE(),CONVERT(Facts[Quantity],DATETIME)))")), places=10)
        self.assertIn("not exact", _local("VARX.S(Facts,DATE(2020,1,1)+Facts[Quantity])"))

    def test_calculate_of_all_like_filters_or_over_a_constructor_does_not_block(self) -> None:
        for expression in (
            'CALCULATE(IFERROR(ERROR("x")*SELECTEDVALUE(Facts[Region]),7),ALLSELECTED(Facts))',
            'CALCULATE(IFERROR(ERROR("x")*SELECTEDVALUE(Facts[Region]),7),REMOVEFILTERS(Facts))',
            'SUMX({1,2},CALCULATE(IFERROR(SELECTEDVALUE(Facts[Quantity])/MAX(Facts[Note]),7)))',
            'SUMX(Facts,CALCULATE(IFERROR(SELECTEDVALUE(Facts[Quantity])/MAX(Facts[Note]),7),ALL(Facts)))',
        ):
            with self.subTest(expression):
                self.assertEqual("BLANK", _local(expression))
        self.assertEqual("21", _local('SUMX(VALUES(Facts[Region]),CALCULATE(IFERROR(SELECTEDVALUE(Facts[Quantity])/MAX(Facts[Note]),7)))'))

    def test_more_double_to_text_places(self) -> None:
        self.assertEqual("True", _local('CONTAINSSTRING(1E15+1,"E")'))
        self.assertEqual("True", _local('CONTAINSSTRING(COALESCE(1E15,1),"E")'))
        self.assertEqual("1E+15|a", _local('COMBINEVALUES("|",ROUND(1E15,0),"a")'))
        self.assertEqual("5", _local('LEN(FORMAT(ROUND(1E15,0),"General Number"))'))
