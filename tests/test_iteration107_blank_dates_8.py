"""Iteration 107: blank-dates-8 (Task 18).

Plan: docs/plans/2026-11-01-blank-dates-8.md
Parts:
  - Part E: CONVERT of a True/False column as a MAXX or MINX body is a text (BOOLEAN is refused)
  - Part C: LOG of BLANK is -Infinity, as LN of BLANK is for any real base (a BLANK base and a zero number stay errors)
"""
from __future__ import annotations

import unittest

from tools import dax_oracle_diff as dax


def _local(expression: str) -> str:
    return dax.local(expression)


class PartCLogOfBlankTests(unittest.TestCase):
    """Part C: LOG10(BLANK()), LOG(BLANK()) and LOG(BLANK(),b) are -Infinity, exactly as LN(BLANK()) is."""

    def test_scalar_log_of_blank_is_negative_infinity(self) -> None:
        for expression in ("LOG10(BLANK())", "LOG(BLANK(),2)", "LOG(BLANK())", "LOG10(VAR y=BLANK() RETURN y)", "LOG(BLANK(),1)", "LOG(BLANK(),-2)", "LOG(BLANK(),0)", "LOG(BLANK(),FALSE())"):
            with self.subTest(expression):
                self.assertEqual("-Infinity", _local(expression))

    def test_log_of_blank_through_arithmetic_comparison_and_text(self) -> None:
        self.assertEqual("-Infinity", _local("LOG10(BLANK())+1"))
        self.assertEqual("-Infinity", _local("LOG(BLANK(),2)+1"))
        self.assertEqual("-infz", _local('LOG10(BLANK())&"z"'))
        self.assertEqual("-infz", _local('LOG(BLANK(),2)&"z"'))
        self.assertEqual("True", _local("LOG10(BLANK())<0"))
        self.assertEqual("True", _local("LOG(BLANK(),2)<0"))
        self.assertEqual("False", _local("ISBLANK(LOG10(BLANK()))"))
        self.assertEqual("False", _local("ISBLANK(LOG(BLANK(),2))"))
        self.assertEqual("7", _local("IFERROR(LOG10(BLANK()),7)"))
        self.assertEqual("7", _local("IFERROR(LOG(BLANK(),2),7)"))

    def test_log_of_blank_over_rows(self) -> None:
        self.assertEqual("BLANK", _local("MAXX(Facts,LOG10(BLANK()))"))
        self.assertEqual("BLANK", _local("MAXX(Facts,LOG(BLANK(),2))"))
        self.assertEqual("-Infinity", _local("MINX(Facts,LOG10(BLANK()))"))
        self.assertEqual("-Infinity", _local("SUMX(Facts,LOG10(BLANK()))"))
        self.assertEqual("-Infinity", _local("AVERAGEX(Facts,LOG10(BLANK()))"))
        self.assertEqual("-Infinity", _local("MINX(Facts,LOG(BLANK(),2))"))
        self.assertEqual("-Infinity", _local("SUMX(Facts,LOG(BLANK(),2))"))
        self.assertEqual("-Infinity", _local("AVERAGEX(Facts,LOG(BLANK(),2))"))
        self.assertEqual("6", _local("COUNTX(Facts,LOG10(BLANK()))"))
        self.assertEqual("6", _local("COUNTX(Facts,LOG(BLANK(),2))"))

    def test_blank_or_zero_base_and_zero_number_stay_errors(self) -> None:
        for expression in ("LOG(2,BLANK())", "LOG(BLANK(),BLANK())", "LOG10(0)", "LOG(0,2)"):
            with self.subTest(expression):
                self.assertTrue(_local(expression).startswith("LOCAL-REJECT"), _local(expression))


class PartANumberMinusDateTests(unittest.TestCase):
    """Part A: X-D, where D has a date type, is a Double unless X has a date type (measured in Power BI)."""

    NUMBER_MINUS_DATE = (
        ("COUNTROWS(Facts)-DATE(2020,1,1)", "-43825"),
        ("TRUE()-DATE(2020,1,1)", "-43830"),
        ('"3"-DATE(2020,1,1)', "-43828"),
        ("IF(FALSE(),1)-DATE(2020,1,1)", "-43831"),
        ("(VAR y=0 RETURN y)-DATE(2020,1,1)", "-43831"),
        ("CURRENCY(1)-DATE(2020,1,1)", "-43830"),
    )

    def test_number_minus_date_is_a_number(self) -> None:
        for expression, expected in self.NUMBER_MINUS_DATE:
            with self.subTest(expression):
                self.assertEqual(expected, _local(expression))

    def test_number_minus_date_is_not_a_date_and_concatenates_as_a_number(self) -> None:
        self.assertEqual("-43825z", _local('COUNTROWS(Facts)-DATE(2020,1,1)&"z"'))
        for expression, _expected in self.NUMBER_MINUS_DATE:
            with self.subTest(expression):
                self.assertEqual("False", _local(f"ISDATETIME({expression})"))

    def test_number_minus_date_in_addcolumns_holds_the_number(self) -> None:
        self.assertEqual(
            "-43825,-43825,-43825,-43825,-43825,-43825",
            _local('CONCATENATEX(ADDCOLUMNS(Facts,"d",COUNTROWS(Facts)-DATE(2020,1,1)),[d],",")'),
        )

    def test_date_minus_date_and_number_plus_date_stay_dates(self) -> None:
        for expression in ("DATE(2020,1,2)-DATE(2020,1,1)", "1+DATE(2020,1,1)"):
            with self.subTest(expression):
                self.assertEqual("True", _local(f"ISDATETIME({expression})"))


class PartEConvertInMaxxTests(unittest.TestCase):
    """Part E: CONVERT(column, STRING) as a MAXX or MINX body is a text; CONVERT(column, BOOLEAN) is refused (measured in Power BI)."""

    MAXX_TEXT = (
        ('MAXX({1&&""},CONVERT([Value],STRING))', "FALSE"),
        ('MAXX({-3||TRIM("")},CONVERT([Value],STRING))', "TRUE"),
        ('MAXX({1&&"",TRUE()},CONVERT([Value],STRING))', "TRUE"),
        ('MAXX(ROW("Value",-3||TRIM("")),CONVERT([Value],STRING))', "TRUE"),
        ('MAXX(ROW("Value",BLANK()&&""),CONVERT([Value],STRING))', "FALSE"),
        ('MAXX(UNION({1&&""},{TRUE()}),CONVERT([Value],STRING))', "TRUE"),
    )

    MINX_TEXT_SINGLE_ROW = (
        ('MINX({1&&""},CONVERT([Value],STRING))', "FALSE"),
        ('MINX({-3||TRIM("")},CONVERT([Value],STRING))', "TRUE"),
        ('MINX(ROW("Value",-3||TRIM("")),CONVERT([Value],STRING))', "TRUE"),
        ('MINX(ROW("Value",BLANK()&&""),CONVERT([Value],STRING))', "FALSE"),
    )

    def test_maxx_of_converted_true_false_column_is_a_text(self) -> None:
        for expression, expected in self.MAXX_TEXT:
            with self.subTest(expression):
                self.assertEqual(expected, _local(expression))

    def test_minx_of_converted_true_false_column_is_a_text(self) -> None:
        for expression, expected in self.MINX_TEXT_SINGLE_ROW:
            with self.subTest(expression):
                self.assertEqual(expected, _local(expression))

    def test_maxx_row_of_blank_stays_blank(self) -> None:
        self.assertEqual("True", _local('ISBLANK(MAXX(ROW("Value",1&&""),CONVERT([Value],STRING)))'))

    def test_text_reads_of_the_same_column_still_work(self) -> None:
        self.assertEqual("5", _local('SUMX({1&&""},LEN(CONVERT([Value],STRING)))'))
        self.assertEqual("FALSEz", _local('MAXX({1&&""},[Value]&"z")'))

    def test_maxx_and_minx_of_converted_true_false_column_to_boolean_are_refused(self) -> None:
        for expression in ('MAXX({1&&""},CONVERT([Value],BOOLEAN))', 'MINX({1&&""},CONVERT([Value],BOOLEAN))'):
            with self.subTest(expression):
                result = _local(expression)
                self.assertTrue(result.startswith("LOCAL-REJECT"), result)
                self.assertIn("cannot work with values of type Boolean", result)


class PartDCountaxOfLogicalTests(unittest.TestCase):
    """Part D: COUNTAX of a logical operator with an empty text (measured in Power BI on 6 rows).

    A BLANK operator value counts nothing; a True/False value counts every row (6).
    """

    BLANK_OPERATORS = (
        '1&&""', '2.5&&""', '"0"||LEFT("a",0)', 'OR(0,"")', 'BLANK()||""', '"TRUE"&&""', '"false"||""',
        '0||""', 'TRUE()&&""', 'FALSE()||""', 'TRUE()&&VAR y="" RETURN y', 'AND(1,IF(TRUE(),"",""))',
        'FALSE()||IF(1=1,"","a")',
    )

    SIX_OPERATORS = (
        '""&&""', 'FALSE()&&""', 'TRUE()||""', '1||""', '0&&""',
    )

    # Measured in Power BI, but the column operands are not reached by the scalar path yet (see the report)
    COLUMN_OPERATORS = ('Facts[Quantity]>2&&""', 'Facts[Quantity]||""', 'Facts[Region]&&""')

    def test_countax_of_blank_operator_is_blank(self) -> None:
        for operator in self.BLANK_OPERATORS:
            with self.subTest(operator):
                self.assertEqual("BLANK", _local(f"COUNTAX(Facts,{operator})"))

    def test_countax_of_true_false_operator_counts_every_row(self) -> None:
        for operator in self.SIX_OPERATORS:
            with self.subTest(operator):
                self.assertEqual("6", _local(f"COUNTAX(Facts,{operator})"))

    def test_countax_through_if_and_iferror_is_the_same(self) -> None:
        self.assertEqual("BLANK", _local('COUNTAX(Facts,IF(TRUE(),1&&""))'))
        self.assertEqual("6", _local('COUNTAX(Facts,IF(TRUE(),""&&""))'))
        self.assertEqual("BLANK", _local('IFERROR(COUNTAX(Facts,1&&""),"e")'))
        self.assertEqual("6", _local('IFERROR(COUNTAX(Facts,""&&""),"e")'))

    def test_countax_over_empty_table_is_blank(self) -> None:
        for operator in self.BLANK_OPERATORS + self.SIX_OPERATORS:
            with self.subTest(operator):
                self.assertEqual("BLANK", _local(f"COUNTAX(FILTER(Facts,FALSE()),{operator})"))

    def test_countx_of_logical_text_operator_stays_refused(self) -> None:
        for operator in self.BLANK_OPERATORS + self.SIX_OPERATORS:
            with self.subTest(operator):
                result = _local(f"COUNTX(Facts,{operator})")
                self.assertTrue(result.startswith("LOCAL-REJECT"), result)

    def test_column_operands_stay_refused(self) -> None:
        for operator in self.COLUMN_OPERATORS:
            with self.subTest(operator):
                result = _local(f"COUNTAX(Facts,{operator})")
                self.assertTrue(result.startswith("LOCAL-REJECT"), result)


class PartFIsblankCurrencyDivisionTests(unittest.TestCase):
    """Part F: ISBLANK of a Currency divided by 0 (Infinity) is False; the bare expression and its other uses stay refused."""

    def test_isblank_of_currency_division_by_zero_is_false(self) -> None:
        for expression in (
            "ISBLANK(CURRENCY(1)/0)",
            "ISBLANK(CURRENCY(1)/0.0)",
            "ISBLANK(CURRENCY(0)/BLANK())",
            "ISBLANK(CURRENCY(1)*2/VAR z=0 RETURN z)",
            "ISBLANK(CURRENCY(1)+CURRENCY(2)/0)",
            "ISBLANK((CURRENCY(1)/0)+1)",
            "ISBLANK(VAR z=BLANK() RETURN CURRENCY(1)/z)",
            "ISBLANK(VAR z=0 RETURN CURRENCY(1)/z)",
        ):
            with self.subTest(expression):
                self.assertEqual("False", _local(expression))

    def test_isblank_of_currency_division_on_a_row_is_false(self) -> None:
        self.assertEqual("12", _local("SUMX(Facts,IF(ISBLANK(CURRENCY(-1)/0),1,2))"))

    def test_bare_currency_division_by_zero_stays_refused(self) -> None:
        self.assertTrue(_local("CURRENCY(1)/0").startswith("LOCAL-REJECT"))

    def test_other_uses_of_currency_division_by_zero_stay_refused(self) -> None:
        for expression in (
            "ISNUMBER(CURRENCY(1)/0)",
            "(CURRENCY(1)/0)+1",
            "(CURRENCY(1)/0)=1",
            "IF(CURRENCY(1)/0,1,2)",
            'SWITCH(CURRENCY(1)/0,1,"a","b")',
        ):
            with self.subTest(expression):
                self.assertTrue(_local(expression).startswith("LOCAL-REJECT"), _local(expression))

    def test_part_f_listed_false_cases(self) -> None:
        for expression in (
            "ISBLANK(CURRENCY(1)/0)",
            "ISBLANK(CURRENCY(-1)/0.0)",
            "ISBLANK(CURRENCY(0)/BLANK())",
            "ISBLANK(CURRENCY(1)*2/VAR z=0 RETURN z)",
            "ISBLANK((CURRENCY(1)+CURRENCY(2))/IF(FALSE(),1))",
            "ISBLANK((CURRENCY(1)/0)+1)",
        ):
            with self.subTest(expression):
                self.assertEqual("False", _local(expression))
        self.assertEqual("12", _local("SUMX(Facts,IF(ISBLANK(CURRENCY(-1)/0),1,2))"))

    def test_part_f_listed_stay_refused_cases(self) -> None:
        for expression in (
            "ISBLANK(SUMX(Facts,CURRENCY(1))/0)",
            "ISBLANK(MAXX(Facts,CURRENCY(1))/0)",
            "ISBLANK(CALCULATE(CURRENCY(1))/0)",
            "ISBLANK(IF(TRUE(),CURRENCY(1))/0)",
            "ISBLANK((VAR c=CURRENCY(1) RETURN c)/0)",
        ):
            with self.subTest(expression):
                self.assertTrue(_local(expression).startswith("LOCAL-REJECT"), _local(expression))

    def test_non_currency_division_by_zero_is_unchanged(self) -> None:
        self.assertEqual("False", _local("ISBLANK(1/0)"))
        self.assertEqual("True", _local("ISNUMBER(1/0)"))


class PartBBlankInMultiplyDivideTests(unittest.TestCase):
    """Part B: a BLANK operand of * makes the result BLANK (the other side's error or text does not count); / only for a BLANK left side."""

    def test_multiply_with_blank_side_is_blank(self) -> None:
        for expression in (
            'BLANK()*"b"',
            '"a"*BLANK()',
            '"a"*VAR y=BLANK() RETURN y',
            'BLANK()*VAR y="b" RETURN y+1',
            "BLANK()*ERROR(\"x\")",
            "ERROR(\"x\")*BLANK()",
            'VALUE("x")*BLANK()',
            'IF(FALSE(),1)*"b"',
            '(VAR y=BLANK() RETURN y)*"a"',
        ):
            with self.subTest(expression):
                self.assertEqual("BLANK", _local(expression))

    def test_divide_with_blank_left_side_is_blank(self) -> None:
        for expression in (
            'BLANK()/"b"',
            'BLANK()/VAR y="2" RETURN y&"z"',
            'BLANK()/ERROR("x")',
            "BLANK()/LOG10(0)",
        ):
            with self.subTest(expression):
                self.assertEqual("BLANK", _local(expression))

    def test_blank_multiply_and_divide_inside_isblank_iferror_and_rows(self) -> None:
        self.assertEqual("True", _local('ISBLANK(BLANK()*"b")'))
        self.assertEqual("BLANK", _local('IFERROR(BLANK()*"b","e")'))
        self.assertEqual("False", _local("ISERROR(BLANK()*LN(0))"))
        self.assertEqual("6", _local('SUMX(Facts,IF(ISBLANK(BLANK()*"b"),1,2))'))
        self.assertEqual("BLANK", _local('MAXX(Facts,BLANK()/"b")'))

    def test_non_blank_multiply_and_divide_stay_errors(self) -> None:
        for expression in (
            '"a"*"b"',
            '"a"*1',
            '"a"/BLANK()',
            'ERROR("x")/BLANK()',
            'ERROR("x")/1',
            'ERROR("x")*1',
        ):
            with self.subTest(expression):
                self.assertTrue(_local(expression).startswith("LOCAL-REJECT"), _local(expression))

    def test_number_divided_by_blank_is_unchanged(self) -> None:
        self.assertEqual("Infinity", _local("1/BLANK()"))

    def test_text_column_in_multiply_or_divide_stays_refused(self) -> None:
        for expression in ('Facts[Note]*"b"', 'BLANK()*Facts[Note]', 'Facts[Note]/"b"'):
            with self.subTest(expression):
                self.assertTrue(_local(expression).startswith("LOCAL-REJECT"), _local(expression))


if __name__ == "__main__":
    unittest.main()


class CorrectionsRound1Tests(unittest.TestCase):
    """Corrections from the first review round (plan, last section), measured in Power BI."""

    def test_rule1_blank_from_data_does_not_cancel_an_error_or_text(self) -> None:
        for expression in (
            '(COUNTROWS(FILTER(Facts,FALSE())))*(ERROR("x"))',
            '("a")*(MAXX({BLANK()},[Value]))',
            'COUNTROWS(FILTER(Facts,FALSE()))*ERROR("x")',
            'SUMX(FILTER(Facts,FALSE()),1)/"a"',
            'MAXX({BLANK()},[Value])*ERROR("x")',
            'CALCULATE(SUM(Facts[Sales]))*"a"',
            '(1>0 && BLANK())*ERROR("x")',
        ):
            with self.subTest(expression):
                self.assertTrue(_local(expression).startswith("LOCAL-REJECT"), _local(expression))

    def test_rule1_blank_that_reads_no_data_still_cancels(self) -> None:
        for expression in (
            'BLANK()*ERROR("x")',
            'ERROR("x")*BLANK()',
            'BLANK()/ERROR("x")',
            'BLANK()*"a"',
            'ABS(BLANK())*ERROR("x")',
            'CALCULATE(BLANK())*"a"',
            'VAR q=BLANK() RETURN q*ERROR("x")',
            '(IF(1=2,1))*ERROR("x")',
            '"a"*(VAR q=BLANK() RETURN q)',
        ):
            with self.subTest(expression):
                self.assertEqual("BLANK", _local(expression))

    def test_rule2_isblank_of_currency_division_only_through_arithmetic(self) -> None:
        for expression in ("ISBLANK(CURRENCY(1)/0)", "ISBLANK(-(CURRENCY(1)/0))", "ISBLANK(CURRENCY(1)/0+2)", "ISBLANK(2*(CURRENCY(1)/0))", 'ISBLANK(CURRENCY(1)/CALCULATE(SUM(Facts[Quantity]),Facts[Region]="Nope"))'):
            with self.subTest(expression):
                self.assertEqual("False", _local(expression))
        for expression in (
            "ISBLANK(IF(TRUE(),CURRENCY(1)/0))",
            "ISBLANK(COALESCE(CURRENCY(1)/0,1))",
            "ISBLANK((MAX(Facts[Sales]))*(CURRENCY(1)/0))",
        ):
            with self.subTest(expression):
                self.assertTrue(_local(expression).startswith("LOCAL-REJECT"), _local(expression))

    def test_rule3_date_times_currency_is_not_a_double(self) -> None:
        self.assertEqual("False", _local("ISDOUBLE(DATE(2020,1,1)*CURRENCY(0))"))
        self.assertEqual("True", _local("ISDOUBLE(DATE(2020,1,1)*2)"))

    def test_rule4_unknown_left_type_minus_a_date_is_a_number(self) -> None:
        self.assertEqual("-43830", _local("(IF(TRUE(),1,DATE(2020,1,2)))-DATE(2020,1,1)"))
        self.assertEqual("1", _local("(IFERROR(DATE(2020,1,2),1))-DATE(2020,1,1)"))
        self.assertEqual("-43832", _local("(-TRUE())-(IF(TRUE(),DATE(2020,1,1)))"))
        self.assertEqual("True", _local("ISDATETIME((DATE(2020,1,2))-(VAR d=DATE(2020,1,1) RETURN d))"))

    def test_rule5_maxx_minx_of_infinity_by_table_kind(self) -> None:
        for expression in (
            "MAXX({1,2},-1/0)",
            'MAXX(ROW("a",1),LN(BLANK()))',
            "MAXX(GENERATESERIES(1,3),-1/0)",
            "MAXX(CALENDAR(DATE(2020,1,1),DATE(2020,1,3)),-1/0)",
            'MAXX(SELECTCOLUMNS(Facts,"z",1),-1/0)',
            "MAXX(FILTER({1,2},TRUE()),-1/0)",
            "MAXX(TOPN(2,Facts,Facts[Quantity]),-1/0)",
            'MAXX(ADDCOLUMNS(Facts,"a",1),-1/0)',
        ):
            with self.subTest(expression):
                self.assertEqual("-Infinity", _local(expression))
        self.assertEqual("Infinity", _local("MINX({1,2},1/0)"))
        for expression in (
            "MAXX(Facts,-1/0)",
            "MAXX(FILTER(Facts,TRUE()),-1/0)",
            "MAXX(VALUES(Facts[Region]),-1/0)",
            "MAXX(ALL(Facts),-1/0)",
            "MAXX(DISTINCT(Facts),-1/0)",
            "MAXX(SUMMARIZE(Facts,Facts[Region]),-1/0)",
            "MINX(Facts,1/0)",
        ):
            with self.subTest(expression):
                self.assertEqual("BLANK", _local(expression))

    def test_rule6_log_with_an_infinite_base_is_an_error(self) -> None:
        for expression in ("LOG(1/0,1/0)", "LOG(2,1/0)", "LOG(2,-1/0)"):
            with self.subTest(expression):
                self.assertTrue(_local(expression).startswith("LOCAL-REJECT"), _local(expression))
        self.assertEqual("-Infinity", _local("LOG(BLANK(),1/0)"))
