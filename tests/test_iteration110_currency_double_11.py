"""Task 21 (currency-double-11): Power BI answers measured on 2026-11-02 (tools/parity/task21_currency_double_spec.json).

Every expected value is Power BI's answer. Code is not allowed to read the spec; these are the examples the tests check.
"""
from __future__ import annotations

import unittest

from tools import dax_oracle_diff as dax
from tools.parity_check import status


def _matches(expression: str, powerbi: str) -> bool:
    return status(powerbi, dax.local(expression)) == "match"


def _not_wrong(expression: str, powerbi: str) -> bool:
    """A shape the local engine refuses is an honest result; only a wrong answer fails."""
    return status(powerbi, dax.local(expression)) in {"match", "gap-reject"}


class PartACurrencyWithDoubleTest(unittest.TestCase):
    def test_currency_times_and_over_a_double_round_on_doubles(self) -> None:
        self.assertTrue(_matches('(CURRENCY(1E14)/1.5)&"z"', "66666666666666.6624z"))
        self.assertTrue(_matches('(CURRENCY(1E14)/7)&"z"', "14285714285714.2864z"))
        self.assertTrue(_matches('(0.01*CURRENCY(922337203685477))&"z"', "9223372036854.7696z"))
        self.assertTrue(_matches('(CURRENCY(922337203685477)*0.3)&"z"', "276701161105643.0592z"))
        self.assertTrue(_matches('(CURRENCY(922337203685477)/3)&"z"', "307445734561825.6384z"))
        self.assertTrue(_matches('(CURRENCY(922337203685477)/MAX(Facts[Quantity]))&"z"', "184467440737095.3984z"))

    def test_both_orders_of_times_agree(self) -> None:
        self.assertTrue(_matches('(1.5*CURRENCY(1E14))&"z"', "150000000000000z"))
        self.assertTrue(_matches('(CURRENCY(1234.5678)*1.5)&"z"', "1851.8517z"))

    def test_int64_operand_keeps_the_wrap(self) -> None:
        self.assertTrue(_matches('(CURRENCY(5E14)*3)&"z"', "-344674407370955.1616z"))

    def test_a_double_over_a_currency_is_a_plain_double(self) -> None:
        self.assertTrue(_matches('(0.1/CURRENCY(1234.5678))&"z"', "8.10000066420006E-05z"))
        self.assertTrue(_matches('(CURRENCY(1)/DATE(2020,1,1))&"z"', "0z"))
        self.assertTrue(_matches('(CURRENCY(1234.5678)/DATE(2020,1,1))&"z"', "0.0282z"))

    def test_range_error_of_a_double_product(self) -> None:
        self.assertTrue(_matches('IFERROR(CURRENCY(1E14)*1E4,"e")', "e"))
        self.assertTrue(_matches('IFERROR(CURRENCY(922337203685477)*2.0,"e")', "e"))


class PartCCurrencyOfTextAndNonFiniteTest(unittest.TestCase):
    def test_text_within_the_range_is_a_currency(self) -> None:
        self.assertTrue(_matches('CURRENCY("922337203685477.5807")', "922337203685477.5807"))
        self.assertTrue(_matches('CURRENCY("9E14")', "900000000000000"))
        self.assertTrue(_matches('CONVERT("0.00005",CURRENCY)', "0"))
        self.assertTrue(_matches('CURRENCY("0.00005")', "0"))

    def test_text_beyond_the_range_is_the_error(self) -> None:
        self.assertTrue(_matches('CURRENCY("1E15")', 'ERR:Exception calling "Read": Out of present range.'))
        self.assertTrue(_matches('ISERROR(CURRENCY("922337203685478"))', "True"))
        self.assertTrue(_matches('ISERROR(CURRENCY("922337203685477.5808"))', "True"))
        self.assertTrue(_matches('IFERROR(CURRENCY("-1E15"),"e")', "e"))

    def test_non_finite_currency_is_the_error(self) -> None:
        self.assertTrue(_matches('COALESCE(CURRENCY(1/0),5)', 'ERR:Exception calling "Read": too large or too small.'))
        self.assertTrue(_matches('CURRENCY(0/0)', 'ERR:Exception calling "Read": too large or too small.'))
        self.assertTrue(_matches('ISCURRENCY(CURRENCY(0/0))', "True"))
        self.assertTrue(_matches('ISERROR(CURRENCY(-1/0))', "True"))


class PartBStaticTypesTest(unittest.TestCase):
    def test_text_plus_currency_is_a_double(self) -> None:
        self.assertTrue(_matches('ISDOUBLE("2"+CURRENCY(1))', "True"))
        self.assertTrue(_matches('ISCURRENCY("2"+CURRENCY(1))', "False"))
        self.assertTrue(_matches('("1E15"+CURRENCY(1))&"z"', "1E+15z"))

    def test_text_times_currency_is_a_currency(self) -> None:
        self.assertTrue(_matches('ISCURRENCY("2"*CURRENCY(1))', "True"))
        self.assertTrue(_matches('ISCURRENCY("1E15"*CURRENCY(1))', "True"))

    def test_currency_over_a_date_or_text_is_a_currency(self) -> None:
        self.assertTrue(_matches('ISCURRENCY(CURRENCY(1E14)/DATE(2020,1,1))', "True"))
        self.assertTrue(_matches('ISCURRENCY(CURRENCY(1E14)/"3")', "True"))

    def test_a_double_divisor_is_evaluated(self) -> None:
        self.assertTrue(_matches('ISCURRENCY(CURRENCY(1E14)/0.1)', 'ERR:Exception calling "Read": too large or too small.'))
        self.assertTrue(_matches('ISCURRENCY(CURRENCY(9E14)*1.5)', "True"))
        self.assertTrue(_matches('ISCURRENCY(CURRENCY(1E14)*SUM(Facts[Sales]))', 'ERR:Exception calling "Read": too large or too small.'))


class PartDDateBesideNonFiniteTest(unittest.TestCase):
    def test_date_holds_the_non_finite_value(self) -> None:
        self.assertTrue(_matches('DATE(2020,1,1)+(1/0)', "12/31/9999 23:59:59"))
        self.assertTrue(_matches('DATE(2020,1,1)-(-1/0)', "12/31/9999 23:59:59"))
        self.assertTrue(_matches('DATE(2020,1,1)+(0/0)', "12/30/1899 00:00:00"))
        self.assertTrue(_matches('(DATE(2020,1,1)+(0/0))&"z"', "12:00:00 AMz"))

    def test_date_through_iterators_and_variables(self) -> None:
        self.assertTrue(_matches('SUMX({1,2},DATE(2020,1,1)-(0/0))', "12/30/1899 00:00:00"))
        self.assertTrue(_matches('SUMX({1,2},DATE(2020,1,1)+(1/0))', "12/31/9999 23:59:59"))
        self.assertTrue(_matches('MAXX({1,2},DATE(2020,1,1)+(1/0))', "12/31/9999 23:59:59"))
        self.assertTrue(_matches('VAR q=DATE(2020,1,1)+(-1/0) RETURN q', "01/01/0100 00:00:00"))
        self.assertTrue(_matches('AVERAGEX({1,2},DATE(2020,1,1)+(1/0))', "Infinity"))


class PartELogicalBlankBesideErrorTest(unittest.TestCase):
    def test_logical_blank_cancels_an_error_in_times_and_left_of_divide(self) -> None:
        self.assertTrue(_matches('IFERROR((MAX(Facts[Sales])&&"")*SQRT(-1),7)', "BLANK"))
        self.assertTrue(_matches('ISERROR((MAX(Facts[Sales])&&"")*SQRT(-1))', "False"))
        self.assertTrue(_matches('ISBLANK((MAX(Facts[Sales])&&"")*ERROR("x"))', "True"))
        self.assertTrue(_matches('IFERROR((MAX(Facts[Sales])&&"")/ERROR("x"),7)', "BLANK"))

    def test_error_stands_right_of_divide_and_in_plus(self) -> None:
        self.assertTrue(_not_wrong('IFERROR("a"/((MAX(Facts[Sales])&&"")),7)', "7"))
        self.assertTrue(_not_wrong('IFERROR(((MAX(Facts[Sales])&&""))+"a",7)', "7"))


class PartFSmallFunctionsTest(unittest.TestCase):
    def test_unichar_of_blank_is_blank(self) -> None:
        self.assertTrue(_matches('ISBLANK(UNICHAR(BLANK()))', "True"))
        self.assertTrue(_matches('ISERROR(UNICHAR(BLANK()))', "False"))
        self.assertTrue(_matches('UNICHAR(BLANK())&"z"', "z"))

    def test_divide_with_a_scanned_blank_numerator_converts_the_divisor(self) -> None:
        self.assertTrue(_matches('ISERROR(DIVIDE(COUNTROWS(FILTER(Facts,FALSE())),"a"))', "True"))
        self.assertTrue(_matches('DIVIDE(BLANK(),"a")', "BLANK"))
        self.assertTrue(_matches('DIVIDE(IF(1=2,1),"a")', "BLANK"))


class FixRoundGroupsTest(unittest.TestCase):
    """The errors the review of Part A to F found (measured Power BI answers, table M)."""

    def test_double_over_currency_is_a_clean_double(self) -> None:
        self.assertTrue(_matches('INT((3.14159/CURRENCY(0.0001))*10000)', "314159000"))
        self.assertTrue(_matches('INT((0.3/CURRENCY(MAX(Facts[Sales])))*10000)', "150"))

    def test_text_beyond_the_double_range_is_an_error_in_arithmetic(self) -> None:
        self.assertTrue(_matches('("1E400"-2)&""', 'ERR:Cannot convert value \'1E400\' of type Text to type Number.'))
        self.assertTrue(_matches('(2.5/"1E400")&""', 'ERR:Cannot convert value \'1E400\' of type Text to type Number.'))
        self.assertTrue(_matches('IFERROR(TRUE()/"1E400","e")', "e"))
        self.assertTrue(_matches('IFERROR("1E400"*FALSE(),"e")', "e"))
        self.assertTrue(_matches('IFERROR(BLANK()/"1E400","e")', "BLANK"))

    def test_type_test_of_text_beyond_the_range(self) -> None:
        self.assertTrue(_matches('ISCURRENCY("1E400"/CURRENCY(2))', 'ERR:Cannot convert value \'1E400\' of type Text to type Number.'))
        self.assertTrue(_matches('ISDOUBLE("1E400"/MAX(Facts[Sales]))', 'ERR:Cannot convert value \'1E400\' of type Text to type Number.'))
        self.assertTrue(_matches('ISDATETIME("1E400"/FALSE())', 'ERR:Cannot convert value \'1E400\' of type Text to type Number.'))
        self.assertTrue(_matches('ISDOUBLE("1E400"+TRUE())', "True"))
        self.assertTrue(_matches('ISDATETIME("1E400"+2)', "False"))
        self.assertTrue(_matches('ISDATETIME(MAX(Facts[Sales])*"1E400")', "False"))

    def test_format_of_a_date_beside_nan_or_infinity(self) -> None:
        self.assertTrue(_matches('FORMAT(DATE(1899,12,30)+0/0,"yyyy")', "1899"))
        self.assertTrue(_matches('FORMAT(DATE(2020,1,1)-(0/0)*MAX(Facts[Sales]),"yyyy")', "1899"))
        self.assertTrue(_matches('FORMAT(TIME(6,0,0)+(0/0)*MAX(Facts[Sales]),"yyyy")', "1899"))
        self.assertTrue(_matches('FORMAT(DATE(2020,1,1)+MAX(Facts[Sales])/0,"yyyy")', "ERR:x"))
        self.assertTrue(_matches('FORMAT(DATE(2020,1,1)-3/0,"General Number")', "-inf"))
        self.assertTrue(_matches('FORMAT(TIME(6,0,0)+1/0,"yyyy")', "ERR:x"))

    def test_minx_maxx_of_nan_over_a_stored_table_inside_iferror(self) -> None:
        """Measured on table M (t21/q3.json): NaN inside IFERROR's first argument, BLANK everywhere else."""
        self.assertTrue(_matches('IFERROR(MINX(Facts,DATE(2020,1,1)-0/0),7)', 'NaN'))
        self.assertTrue(_matches('MINX(Facts,DATE(2020,1,1)-0/0)', 'BLANK'))
        self.assertTrue(_matches('ISBLANK(IFERROR(MINX(Facts,DATE(2020,1,1)-0/0),7))', 'False'))
        self.assertTrue(_matches('IFERROR(MINX(Facts,DATE(2020,1,1)-0/0),7)&"z"', '-nan(ind)z'))
        self.assertTrue(_matches('IFERROR(MINX(Facts,DATE(2020,1,1)+0/0),7)', 'NaN'))
        self.assertTrue(_matches('IFERROR(MINX(FILTER(Facts,Facts[Quantity]>1),DATE(2020,1,1)-0/0),7)', 'NaN'))
        self.assertTrue(_matches('IFERROR(MINX({1,2},DATE(2020,1,1)-0/0),7)', '7'))
        self.assertTrue(_matches('IFERROR(MAXX(Facts,DATE(2020,1,1)-0/0),7)', 'NaN'))
        self.assertTrue(_matches('IFERROR(MINX(Facts,DATE(2020,1,1)-0/0)+0,7)', 'NaN'))
        self.assertTrue(_matches('COALESCE(MINX(Facts,DATE(2020,1,1)-0/0),7)', '7'))
        self.assertTrue(_matches('IF(ISERROR(MINX(Facts,DATE(2020,1,1)-0/0)),1,2)', '2'))
        self.assertTrue(_matches('IFERROR(MINX(Facts,0/0),7)', 'NaN'))
        self.assertTrue(_matches('IFERROR(MINX(Facts,TIME(6,0,0)-0/0),7)', 'NaN'))
        self.assertTrue(_matches('VAR m=MINX(Facts,DATE(2020,1,1)-0/0) RETURN IFERROR(m,7)', 'BLANK'))

    def test_average_of_a_currency_body_is_a_currency(self) -> None:
        self.assertTrue(_matches('AVERAGEX(Facts,CONVERT(Facts[Sales],CURRENCY)/1E5)', "0.0001"))
        self.assertTrue(_matches('AVERAGEX(Facts,Facts[Sales]/3*CONVERT(Facts[Sales],CURRENCY))', "34.5833"))
        self.assertTrue(_matches('AVERAGEX(FILTER(Facts,Facts[Quantity]>1),CONVERT(Facts[Sales],CURRENCY)*1/3)', "3.6667"))
        self.assertTrue(_matches('AVERAGEX(FILTER(Facts,Facts[Quantity]>1),1/3*CONVERT(Facts[Sales],CURRENCY))', "3.6667"))
        self.assertTrue(_matches('AVERAGEX(Facts,CURRENCY(Facts[Quantity])*Facts[Sales]/3)', "6.1333"))
        self.assertTrue(_not_wrong('AVERAGEX(Facts,0.1/CURRENCY(Facts[Quantity]))', "Infinity"))

    def test_logical_blank_deeper_in_a_chain_cancels_the_error(self) -> None:
        self.assertTrue(_matches('IFERROR((1&&"")/SQRT(-1)*ERROR("z"),"e")', "BLANK"))
        self.assertTrue(_matches('ISERROR((1&&"")*SQRT(-1)*ERROR("z"))', "False"))
        self.assertTrue(_matches('IFERROR("a"*1*(1&&""),"e")', "BLANK"))
        self.assertTrue(_matches('ISERROR("a"*1*(1&&""))', "False"))
        self.assertTrue(_matches('IFERROR((MAX(Facts[Sales])&&"")/SQRT(-1)*ERROR("z"),"e")', "BLANK"))
        self.assertTrue(_matches('IFERROR((MIN(Facts[Quantity])||"")*SQRT(-1)*ERROR("z"),"e")', "BLANK"))
        self.assertTrue(_matches('ISERROR((MAX(Facts[Sales])&&"")/SQRT(-1)*ERROR("z"))', "False"))
        self.assertTrue(_matches('IFERROR("a"*1/(1&&""),"e")', "e"))
        self.assertTrue(_matches('IFERROR("a"*1+(1&&""),"e")', "e"))

    def test_range_error_of_a_row_reading_currency_product_shows_through_isnumber(self) -> None:
        err = "ERR:The result of a conversion or arithmetic operation is either too large or too small."
        self.assertTrue(_matches('ISNUMBER(CURRENCY(1E14)*MAX(Facts[Sales])/7)', err))
        self.assertTrue(_matches('ISNUMBER(CURRENCY(1E14)*MAX(Facts[Sales])/7+0.3)', err))
        self.assertTrue(_matches('ISCURRENCY(CURRENCY(1E14)*MAX(Facts[Sales])/7)', err))
        self.assertTrue(_matches('ISNUMBER(CURRENCY(1E14)*1E10)', "True"))
        self.assertTrue(_matches('ISDOUBLE((SUM(Facts[Sales]))*(CURRENCY(1E14)))', "False"))
        self.assertTrue(_matches('ISINT64((AVERAGE(Facts[Quantity]))*(CURRENCY(9E14)))', "False"))


if __name__ == "__main__":
    unittest.main()
