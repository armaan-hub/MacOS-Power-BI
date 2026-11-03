"""Iteration 120: tests for Task 30 static-types-20 (static type inference)."""

import unittest
from tools import dax_oracle_diff as dax


class TestIteration120StaticTypes20(unittest.TestCase):
    def test_part_a_date_arithmetic_types(self) -> None:
        # String/bool minus date is a double
        self.assertEqual(dax.local('ISDOUBLE(("3")-(DATE(2020,1,1)))'), "True")
        self.assertEqual(dax.local('ISINT64(("3")-(DATE(2020,1,1)))'), "False")
        self.assertEqual(dax.local('ISDOUBLE((TRUE())-(DATE(2020,1,1)))'), "True")
        self.assertEqual(dax.local('ISINT64((TRUE())-(DATE(2020,1,1)))'), "False")
        self.assertEqual(dax.local('ISDOUBLE(("3.5")-(TIME(6,0,0)))'), "True")
        self.assertEqual(dax.local('ISDOUBLE((VAR d="3" RETURN d)-(MAXX(Facts,DATE(2020,1,1))))'), "True")

        # Date plus/minus date is a datetime (not double or int64)
        self.assertEqual(dax.local('ISDOUBLE((DATE(2020,1,2))+(DATE(2020,1,1)))'), "False")
        self.assertEqual(dax.local('ISINT64((DATE(2020,1,2))+(DATE(2020,1,1)))'), "False")
        self.assertEqual(dax.local('ISDOUBLE((DATE(2020,1,2))+(TIME(6,0,0)))'), "False")
        self.assertEqual(dax.local('ISDOUBLE((TIME(6,0,0))+(TIME(6,0,0)))'), "False")
        self.assertEqual(dax.local('ISCURRENCY(DATE(2021,3,4)-"0.5")'), "False")

        # Date times date is a double
        self.assertEqual(dax.local('ISDOUBLE((CALCULATE(DATE(2020,1,1)))*(MAX(BLANK(),DATE(2020,1,1))))'), "True")
        self.assertEqual(dax.local('ISCURRENCY((COALESCE(BLANK(),DATE(2020,1,1)))*(CALCULATE(DATE(2020,1,2))))'), "False")

    def test_part_a_logical_blank_arithmetic(self) -> None:
        # Logical blank in arithmetic is typed Integer/Double
        self.assertEqual(dax.local('ISINT64((0||"")*(0||""))'), "True")
        self.assertEqual(dax.local('ISINT64((0||"")*(1&&""))'), "True")
        self.assertEqual(dax.local('ISDOUBLE((0||"")*(DATE(2020,1,1)))'), "True")
        self.assertEqual(dax.local('ISDOUBLE((DATE(2020,1,1))*(1&&""))'), "True")
        self.assertEqual(dax.local('ISDOUBLE((2.5&&"")*(2.5))'), "True")
        self.assertEqual(dax.local('ISINTEGER((OR(0,""))*(FALSE()))'), "True")
        self.assertEqual(dax.local('ISINTEGER((0)*(0||""))'), "True")
        self.assertEqual(dax.local('ISDOUBLE((1&&TRIM(""))*(2.5))'), "True")

    def test_part_a_plan_examples(self) -> None:
        # Examples directly from Task 30 plan
        self.assertEqual(dax.local('ISINT64((TIME(1,0,0))+(VAR d=DATE(2020,1,1) RETURN d))'), "False")
        self.assertEqual(dax.local('ISCURRENCY((MAXX({DATE(2020,1,1)},[Value]))-(MAX(BLANK(),DATE(2020,1,1))))'), "False")
        self.assertEqual(dax.local('ISDOUBLE((VAR y=1/0 RETURN y)*(1&&"")*(FALSE()))'), "False")

    def test_part_b_strict_equality(self) -> None:
        # Strict equality == with VAR returning blank and logical blanks
        self.assertEqual(dax.local('IFERROR(VAR y=BLANK() RETURN y==0, 7)'), "False")
        self.assertEqual(dax.local('(IF(TRUE(),OR(0,""),1))==FALSE()'), "False")
        self.assertEqual(dax.local('(IF(TRUE(),2.5&&"",""))==BLANK()'), "True")
        self.assertEqual(dax.local('(IF(TRUE(),2.5&&"",1))==BLANK()'), "True")
        self.assertEqual(dax.local('(VAR y=BLANK() RETURN y)==0'), "False")
        self.assertEqual(dax.local('(0||"")==FALSE()'), "False")
        self.assertEqual(dax.local('(0||"")==BLANK()'), "True")

    def test_part_c_coalesce_iterator_bodies(self) -> None:
        # COALESCE with scalar function branches in iterator bodies
        self.assertEqual(dax.local('MAXX(Facts,COALESCE(1,INT("a"),"x"))'), "1")
        self.assertEqual(dax.local('MAXX(Facts,COALESCE(INT("1"),"a"))'), "1")
        self.assertEqual(dax.local('MAXX(Facts,COALESCE(INT("1"),7))'), "1")
        self.assertEqual(dax.local('SUMX(Facts,COALESCE(INT("1"),0))'), "6")
        self.assertEqual(dax.local('AVERAGEX(Facts,COALESCE(INT("1"),1))'), "1")
        self.assertEqual(dax.local('COUNTAX(ADDCOLUMNS(Facts,"q",COALESCE(OR(0,""),"a")),[q])'), "BLANK")


if __name__ == "__main__":
    unittest.main()
