"""Iteration 131: tests for Task 41 type-tests-errors-31.

Covers:
- Part A: IS* type tests (ISTEXT, ISNONTEXT, ISNUMBER, ISLOGICAL, ISINT64, ISINTEGER, ISDOUBLE,
  ISDECIMAL, ISCURRENCY, ISDATETIME, ISBOOLEAN, ISSTRING, ISNUMERIC, ISBLANK) of failing expressions
  answered from compile-time static type.
- Part B: Non-finite date year/month/day epoch conversion, strict equality == with polymorphic BLANK,
  ROUND parsing of date/time text, COALESCE lazy evaluation of constant keyword-typed expressions,
  and BLANK short-circuiting in * and /.
"""

import unittest
from tools import dax_oracle_diff as dax


class TestIteration131TypeTestsErrors31(unittest.TestCase):
    def test_part_a_type_tests_of_failing_expressions(self) -> None:
        self.assertEqual(dax.local('ISCURRENCY(CONVERT(MAX(Facts[Region]),INTEGER))'), "False")
        self.assertEqual(dax.local('ISLOGICAL(INT("a"))'), "False")
        self.assertEqual(dax.local('ISNONTEXT(INT("a"))'), "True")
        self.assertEqual(dax.local('ISNUMBER(INT("a"))'), "True")
        self.assertEqual(dax.local('ISTEXT(INT("a"))'), "False")
        self.assertEqual(dax.local('ISDOUBLE((INT("a"))*("a"*2))'), "True")
        self.assertEqual(dax.local('ISINT64((INT("a"))*(INT("a")))'), "True")
        self.assertEqual(dax.local('ISNONTEXT(VAR y=VALUE("x") RETURN y)'), "True")
        self.assertEqual(dax.local('ISTEXT(VAR y=VALUE("x") RETURN y)'), "False")
        self.assertEqual(dax.local('ISLOGICAL(VAR y=VALUE("x") RETURN y)'), "False")
        self.assertEqual(dax.local('ISNUMBER(CONVERT("a",BOOLEAN))'), "False")
        self.assertEqual(dax.local('ISBOOLEAN(INT("a"))'), "False")
        self.assertEqual(dax.local('ISSTRING(INT("a"))'), "False")
        self.assertEqual(dax.local('ISNUMERIC(INT("a"))'), "True")
        self.assertEqual(dax.local('ISBLANK(INT("a"))'), "False")

    def test_part_b_non_error_exceptions(self) -> None:
        self.assertEqual(dax.local('YEAR(DATE(1899,12,30)+-1/0)'), "1899")
        self.assertEqual(dax.local('COALESCE((COUNTROWS(FILTER(Facts,FALSE())))*(MAX(Facts[Note])),5)'), "5")
        self.assertEqual(dax.local('VAR y=BLANK() RETURN y==OR(0,"")'), "True")
        self.assertEqual(dax.local('VAR y=BLANK() RETURN y==TRUE()'), "False")
        self.assertEqual(dax.local('ROUND("2020-01-02",0)'), "43832")
        self.assertEqual(dax.local('ROUND("1/2/2020",0)'), "43832")
        self.assertEqual(dax.local('COUNTX({1,2},COALESCE(CONVERT("1",INTEGER),VALUE("East")))'), "2")
        self.assertEqual(dax.local('COUNTX({1,2},COALESCE(CONVERT("3",DOUBLE),VALUE("x")))'), "2")
        self.assertEqual(dax.local('SUMX(Facts,COALESCE(CONVERT("1",INTEGER),INT("a"),Facts[Quantity]/0))'), "6")


if __name__ == "__main__":
    unittest.main()
