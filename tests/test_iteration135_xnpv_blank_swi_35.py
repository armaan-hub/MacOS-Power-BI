"""Iteration 135: Task 45 xnpv-blank-swi-35.

Tests for:
- Part A: XNPV whose values are Currency (beside a column of unknown type, or a Currency that is BLANK).
- Part B: BLANK beside failing iterators in arithmetic (* and /), and Variant in arithmetic.
- Part C: FIRSTNONBLANK over ROW/derived tables, and SUBSTITUTEWITHINDEX with derived tables / renamed columns.
"""
import unittest

from tools import dax_oracle_diff as dax


class XnpvBlankSwi35Tests(unittest.TestCase):
    def test_part_a_xnpv_currency_values(self) -> None:
        # Currency values in XNPV:
        # When values evaluate to currency, four decimals are kept.
        self.assertTrue(dax.same(
            "-673.678940646131",
            dax.local('XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{ {-1000,0},{300,365},{400,730},{500,1095} }),"d",DATE(2020,1,1)+[n]),IF([n]>0,CURRENCY([v])/3,[v]),[d],0.1)')
        ))
        self.assertTrue(dax.same(
            "-600",
            dax.local('XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{ {-1000,0},{300,365},{400,730},{500,1095} }),"d",DATE(2020,1,1)+[n]),IF([n]>0,CURRENCY([v])/3,[v]),[d],0)')
        ))
        self.assertTrue(dax.same(
            "1066.6668",
            dax.local('XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{ {-1000,0},{300,365},{400,730},{500,1095} }),"d",DATE(2020,1,1)+[n]),IF([n]>0,CURRENCY([v])/3,[v]),[d],-0.5)')
        ))
        self.assertTrue(dax.same(
            "-895.8333375",
            dax.local('XNPV(ADDCOLUMNS(DATATABLE("v",DOUBLE,"n",INTEGER,{ {-1000,0},{300,365},{400,730},{500,1095} }),"d",DATE(2020,1,1)+[n]),IF([n]>0,CURRENCY([v])/3,[v]),[d],1)')
        ))
        # BLANK currency row in XNPV: evaluates to currency (four decimals)
        self.assertEqual(
            "31.5015",
            dax.local('XNPV(ADDCOLUMNS(Facts,"d",DATE(2020,1,1)+Facts[Quantity]),CURRENCY(Facts[Sales])*1.00005,[d],0)')
        )

    def test_part_b_blank_beside_failing_iterators(self) -> None:
        # Arithmetic subtraction with Variant
        self.assertEqual("6", dax.local('COUNTX(Facts,(IF(TRUE(),"3",1))-(MAXX(Facts,DATE(2020,1,1))))'))
        self.assertEqual("6", dax.local('COUNTX(Facts,(IF(TRUE(),"3",1))-(MAXX({DATE(2020,1,1)},[Value])))'))
        self.assertEqual("-43828", dax.local('MAXX(Facts,(IF(TRUE(),"3",1))-(MAXX({DATE(2020,1,1)},[Value])))'))

        # BLANK times failing iterators / errors
        self.assertEqual("BLANK", dax.local('COUNTX(Facts,(DIVIDE(1,BLANK()))*(SUMX(Facts,ERROR("x"))))'))
        self.assertEqual("BLANK", dax.local('MAXX({1,2},(SUMX(Facts,ERROR("x")))*(SELECTEDVALUE(Facts[Quantity])))'))
        self.assertEqual("BLANK", dax.local('COUNTX(Facts,IFERROR((IF(COUNTROWS(Facts)=0,1))/(ERROR("x")),7))'))
        self.assertEqual("BLANK", dax.local('MAXX(VALUES(Facts[Note]),MAXX(UNION(Facts,Facts),IF(TRUE(),Facts[Region],1)))'))

    def test_part_c_firstnonblank_and_substitutewithindex(self) -> None:
        # FIRSTNONBLANK over ROW
        self.assertEqual("1E+15", dax.local('FIRSTNONBLANK(ROW("a",1E15&""),1)'))
        self.assertEqual("1000000000000000", dax.local('FIRSTNONBLANK(ROW("a",CONVERT(1E15,INTEGER)&""),1)'))
        self.assertEqual("1E+15", dax.local('FIRSTNONBLANK(ROW("a",CONVERT(1000000000000000,DOUBLE)&""),1)'))
        self.assertEqual("1E+100", dax.local('FIRSTNONBLANK(ROW("a",1E100&""),1)'))

        # SUBSTITUTEWITHINDEX with derived tables and renamed columns
        self.assertEqual("2", dax.local(
            'MAXX(SUBSTITUTEWITHINDEX(SELECTCOLUMNS(Facts,"Facts[Region]",Facts[Region]),"i",VALUES(Facts[Region]),Facts[Region]),[i])'
        ))
        self.assertEqual("1", dax.local(
            'MINX(SUBSTITUTEWITHINDEX(DATATABLE("Region",STRING,{ {"East"},{"North"},{"Zed"} }),"i",DATATABLE("Region",STRING,{ {"West"},{"East"},{"North"} }),BLANK()),[i])'
        ))

    def test_empty_outer_iterator_over_statically_failing_inner(self) -> None:
        # the inner iterator is evaluated even over no rows, and SQRT(-1) / LOG(-1) raise: refused, never BLANK
        for expression in (
            'SUMX(FILTER(Facts,FALSE()),MAXX(ROW("a",1),SQRT(-1)))',
            'PRODUCTX(FILTER(Facts,FALSE()),MAXX({1,2},LOG(-1)))',
            'MAXX(FILTER(Facts,FALSE()),MAXX(VALUES(Facts[Note]),LOG(-1)))',
        ):
            self.assertNotEqual("BLANK", dax.local(expression))
        # a valid inner body over no rows stays BLANK
        self.assertEqual("BLANK", dax.local('SUMX(FILTER(Facts,FALSE()),MAXX(ROW("a",1),SQRT(4)))'))

    def test_blank_minus_nan_in_extreme_body_is_refused(self) -> None:
        self.assertNotEqual("BLANK", dax.local('MINX(VALUES(Facts[Note]),(COUNTROWS(FILTER(Facts,FALSE())))-(1/0*0))'))


if __name__ == "__main__":
    unittest.main()
