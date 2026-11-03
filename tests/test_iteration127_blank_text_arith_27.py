"""Iteration 127: Task 37 blank-text-arith-27.

Tests for BLANK from logical operators (&&, ||) and text conversion in arithmetic:
- Part A: logical operator BLANK beside BLANK or text in arithmetic (+ - * / ^), &, COALESCE, IFERROR, type tests.
- Part B: text meeting BLANK or text in arithmetic, static type tests.
- Part C: conditional branches with logical BLANK beside text in iterators.
"""
import unittest

from tools import dax_oracle_diff as dax


class BlankTextArithTests(unittest.TestCase):
    def test_part_a_logical_blank_in_arithmetic(self) -> None:
        # COALESCE of logical blank product returns BLANK (logical blank preserved)
        self.assertEqual(dax.local('COALESCE((2.5&&"")*(""), 5)'), "BLANK")
        # Logical blank product with text number is Double
        self.assertEqual(dax.local('ISDOUBLE(("2")*(1&&""))'), "True")
        # Logical blank quotient with text concatenation
        self.assertEqual(dax.local('((1&&"")/(""))&"z"'), "z")
        # Division by logical blank is Infinity
        self.assertEqual(dax.local('("2")/(2.5&&"")'), "Infinity")
        # Multiplication by logical blank yields BLANK
        self.assertEqual(dax.local('(1&&"")*(UPPER("a"))'), "BLANK")
        # Non-numeric text addition caught by IFERROR
        self.assertEqual(dax.local('IFERROR(((IF(1=1,1)&&""))+"a", 7)'), "7")
        # Logical blank plus row sales with row 0 blank evaluated correctly
        self.assertEqual(dax.local('SUMX(Facts,IF(ISBLANK(COALESCE((1&&"")+(Facts[Sales]),1)),1,2))'), "11")

    def test_part_b_text_meeting_blank_and_static_types(self) -> None:
        # Static type tests on arithmetic with text
        self.assertEqual(dax.local('ISNUMBER("a"+1)'), "True")
        self.assertEqual(dax.local('ISTEXT("a"+1)'), "False")
        self.assertEqual(dax.local('ISLOGICAL("a"+1)'), "False")
        self.assertEqual(dax.local('ISNONTEXT("a"+1)'), "True")
        self.assertEqual(dax.local('ISNUMBER("a"^2)'), "True")
        self.assertEqual(dax.local('ISNUMBER(("")*("a"))'), "True")
        self.assertEqual(dax.local('ISDOUBLE(("")*("a"))'), "True")
        self.assertEqual(dax.local('ISDOUBLE(BLANK()-"abc")'), "True")
        self.assertEqual(dax.local('ISDOUBLE(DATE(2021,3,4)+"TRUE")'), "False")
        self.assertEqual(dax.local('ISDATETIME(DATE(2021,3,4)+"TRUE")'), "True")

        # BLANK meeting text in multiplication/division yields BLANK
        self.assertEqual(dax.local('(MAX(BLANK(),BLANK()))*("a")'), "BLANK")
        self.assertEqual(dax.local('("a")*(MAX(BLANK(),BLANK()))'), "BLANK")
        self.assertEqual(dax.local('(MAX(BLANK(),BLANK()))/("a")'), "BLANK")
        self.assertEqual(dax.local('(CONVERT(BLANK(),INTEGER))*("a")'), "BLANK")
        self.assertEqual(dax.local('(MAX(BLANK(),BLANK()))*(VALUE("x"))'), "BLANK")

    def test_part_c_logical_blank_in_conditionals(self) -> None:
        # COUNTAX ignores BLANK from logical branch
        self.assertEqual(dax.local('COUNTAX(ROW("Value",1),IF(1=1,1&&"","a"))+1'), "1")
        self.assertEqual(dax.local('COUNTAX({1},IF(1=1,1&&"","a"))+1'), "1")
        self.assertEqual(dax.local('COUNTAX({"a"},IF(1=1,1&&"","a"))+1'), "1")
        # SUMX with IF/SWITCH yielding BLANK in condition branch
        self.assertEqual(dax.local('SUMX(Facts,IF(SWITCH(TRUE(),FALSE(),"a","0"||LEFT("a",0)),1,2))'), "12")
        self.assertEqual(dax.local('SUMX(Facts,IF(IF(TRUE(),2.5&&"","a"),1,2))'), "12")


if __name__ == "__main__":
    unittest.main()
