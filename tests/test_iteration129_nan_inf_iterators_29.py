"""Iteration 129: tests for Task 39 nan-inf-iterators-29.

Covers:
- Part A: PRODUCTX, MEDIANX, GEOMEANX, PERCENTILEX.INC/EXC over Infinity or NaN values.
- Part B: VARX.P/S and STDEVX.P/S over Infinity or NaN values.
- Part C: MAXX / MINX over Variant body with NaN beside other numbers (honest refusal of row order dependency).
- Part D: SUMX, COUNTX, COUNTAX, AVERAGEX over NaN beside a product with a constant zero.
"""

import unittest
from tools import dax_oracle_diff as dax


class TestIteration129NanInfIterators29(unittest.TestCase):
    def test_part_a_productx_medianx_geomeanx_percentilex(self) -> None:
        self.assertEqual(
            dax.local('PRODUCTX(CALCULATETABLE(Facts,Facts[Region]="East"),1/0)'),
            "Infinity",
        )
        self.assertEqual(
            dax.local('PRODUCTX(Facts,LN(BLANK()))'),
            "Infinity",
        )
        self.assertEqual(
            dax.local('PRODUCTX(Facts,("2")*(0/0))'),
            "NaN",
        )
        self.assertEqual(
            dax.local('MEDIANX(CALCULATETABLE(Facts,Facts[Region]="East"),1/0)'),
            "Infinity",
        )
        self.assertEqual(
            dax.local('MEDIANX(Facts,LN(BLANK()))'),
            "-Infinity",
        )
        self.assertEqual(
            dax.local('MEDIANX(Facts,(1/0*0)*(2.5))'),
            "NaN",
        )
        self.assertEqual(
            dax.local('MEDIANX(Facts,(BLANK())+(FORMAT(1,"0"))/(Facts[Quantity]))'),
            "0.416666666666667",
        )
        # NaN beside other numbers: the sort order of the engine is not modelled, so these are refused (Task 39 review: [1,NaN,NaN] is NaN, [0,NaN,0,NaN,0,NaN] is 0)
        self.assertTrue(dax.local('MEDIANX(Facts,(0)/(IF(Facts[Quantity]>2,BLANK(),1)))').startswith("LOCAL-REJECT:"))
        self.assertTrue(dax.local('MEDIANX({1,2,3},IF([Value]>1,0/0,[Value]))').startswith("LOCAL-REJECT:"))
        self.assertEqual(
            dax.local('MEDIANX(Facts,(TRUE())/(IF(Facts[Quantity]>2,BLANK(),1)))'),
            "Infinity",
        )
        self.assertTrue(dax.local('MEDIANX(Facts,CONVERT(Facts[Quantity]/0,DOUBLE))').startswith("LOCAL-REJECT:"))  # one NaN beside Infinities: Infinity in Power BI, refused here
        self.assertTrue(dax.local('MEDIANX(Facts,CONVERT(Facts[Sales]/0,DOUBLE))').startswith("LOCAL-REJECT:"))
        self.assertEqual(
            dax.local('GEOMEANX(CALCULATETABLE(Facts,Facts[Region]="East"),1/0)'),
            "Infinity",
        )
        self.assertEqual(
            dax.local('GEOMEANX(VALUES(Facts[Region]),IF(TRUE(),CONVERT(-1/0,DOUBLE)))'),
            "-Infinity",
        )
        self.assertEqual(
            dax.local('GEOMEANX(Facts,CONVERT(Facts[Quantity]/0,DOUBLE))'),
            "0",
        )
        self.assertEqual(
            dax.local('PERCENTILEX.INC(CALCULATETABLE(Facts,Facts[Region]="East"),1/0,0.5)'),
            "Infinity",
        )
        self.assertEqual(
            dax.local('PERCENTILEX.EXC(CALCULATETABLE(Facts,Facts[Region]="East"),1/0,0.5)'),
            "Infinity",
        )

    def test_part_b_varx_stdevx_over_inf_nan(self) -> None:
        self.assertEqual(
            dax.local('STDEVX.P(CALCULATETABLE(Facts,Facts[Region]="East"),1/0)'),
            "0",
        )
        self.assertEqual(
            dax.local('STDEVX.P(Facts,LOG10(VAR y=BLANK() RETURN y))'),
            "0",
        )
        self.assertEqual(
            dax.local('STDEVX.P(Facts,(1/0*0)/(FORMAT(1,"0")))'),
            "0",
        )
        self.assertEqual(
            dax.local('VARX.P(Facts,CONVERT(Facts[Quantity]/0,DOUBLE))'),
            "0",
        )
        self.assertEqual(
            dax.local('STDEVX.S(Facts,CONVERT(Facts[Sales]/0,DOUBLE))'),
            "0",
        )
        self.assertEqual(
            dax.local('STDEVX.S(ROW("Value",1),IF(TRUE(),CONVERT(0/0,DATETIME)))'),
            "NaN",
        )
        self.assertEqual(
            dax.local('VARX.S({1},COALESCE(CONVERT(-1/0,DOUBLE),CONVERT(-1/0,DOUBLE)))'),
            "NaN",
        )

    def test_fresh_shapes_measured_in_power_bi(self) -> None:
        local = dax.local
        # Infinity only: the middle pair is interpolated as low + (high - low) * fraction, equal ends give the end
        self.assertEqual(local('MEDIANX({-1,2,5,0},IF([Value]>1,-1/0,[Value]))'), "NaN")
        self.assertEqual(local('MEDIANX(FILTER(Facts,Facts[Quantity]>2),IF(Facts[Sales]>1,1/0,-1/0))'), "Infinity")
        self.assertEqual(local('PERCENTILEX.INC({1,2,3},IF([Value]>1,-1/0,[Value]),0.75)'), "NaN")
        # the text of a NaN: the default NaN of an invalid operation, and a NaN that is passed on, are -nan(ind)
        self.assertEqual(local('(SUMX({1,2,3},(1/0*0)+[Value]))&"z"'), "-nan(ind)z")
        self.assertEqual(local('(PRODUCTX({-1,2,5,0},(1/0*0)+[Value]))&"z"'), "-nan(ind)z")
        self.assertEqual(local('(PRODUCTX({1,2},IF([Value]>1,1/0,0)))&"z"'), "-nan(ind)z")
        self.assertEqual(local('(PRODUCTX({0,1},IF([Value]=1,1/0,[Value])))&"z"'), "-nan(ind)z")
        # a NaN (from 1/0-1/0 in the body) beside a zero factor printed a positive nan in Power BI (West rows 0 and 3): the sign is unsettled, so refused
        self.assertTrue(local('(PRODUCTX(FILTER(Facts,Facts[Region]="West"),IF(Facts[Quantity]>1,1/0-1/0,Facts[Quantity])))&"z"').startswith("LOCAL-REJECT:"))
        self.assertTrue(local('PRODUCTX({0,3},IF([Value]>1,1/0-1/0,[Value]))').startswith("LOCAL-REJECT:"))
        self.assertEqual(local('(PERCENTILEX.EXC({1},0/0,0.5))&"z"'), "-nan(ind)z")
        self.assertEqual(local('(PERCENTILEX.INC({1,2,3},IF([Value]>1,-1/0,1),0.75))&"z"'), "-nan(ind)z")
        # an even root of a negative product with an Infinity is the positive NaN
        self.assertEqual(local('GEOMEANX({-1,2,5,0},1/[Value])'), "NaN")
        self.assertEqual(local('GEOMEANX({-1,2,5,0},-1/[Value])'), "NaN")
        self.assertEqual(local('(GEOMEANX({-1,2,5,0},1/[Value]))&"z"'), "nanz")
        self.assertEqual(local('GEOMEANX({1,2,3},IF([Value]>1,-1/0,1))'), "Infinity")
        # PERCENTILEX.EXC out of 1/(N+1)..N/(N+1) is an error whatever the values, and IFERROR does not catch it
        for expression in (
            'PERCENTILEX.EXC({1},1/0,1)',
            'PERCENTILEX.EXC({1,2},-1/0,0.75)',
            'PERCENTILEX.EXC({BLANK(),1},1/0,0)',
            'IFERROR(PERCENTILEX.EXC({0,1},[Value]/0,0.75),7)',
            'IFERROR(PERCENTILEX.EXC({1},IF([Value]>1,1/0,-1/0),0.25),7)',
            'ISBLANK(PERCENTILEX.EXC({1,2},1/0,0.75))',
        ):
            self.assertTrue(local(expression).startswith("LOCAL-REJECT:"), expression)
        # a zero product folded by Power BI over a stored Int64 column is refused, not answered NaN
        for expression in (
            'SUMX(CALCULATETABLE(Facts,Facts[Region]="East"),(Facts[Quantity]/0)*0)',
            'PRODUCTX(CALCULATETABLE(Facts,Facts[Region]="East"),(Facts[Quantity]/0)*0)',
            'COUNTX(Facts,(Facts[Quantity]/0)*0)',
        ):
            self.assertTrue(local(expression).startswith("LOCAL-REJECT:"), expression)
        # over a table constructor the zero product is not folded
        self.assertEqual(local('SUMX({1},([Value]/0)*0)'), "NaN")
        self.assertEqual(local('PRODUCTX({1,2},([Value]/0)*0)'), "NaN")
        # NaN beside other numbers in MEDIANX, PERCENTILEX and VARX.S: refused
        self.assertTrue(local('MEDIANX({0,1},[Value]/0)').startswith("LOCAL-REJECT:"))
        self.assertTrue(local('PERCENTILEX.INC({-1,2,5,0},IF([Value]>1,0/0,[Value]),0.75)').startswith("LOCAL-REJECT:"))
        self.assertTrue(local('VARX.S(CALCULATETABLE(Facts,Facts[Region]="East"),IF(Facts[Quantity]>1,0/0,Facts[Quantity]))').startswith("LOCAL-REJECT:"))

    def test_part_c_maxx_minx_variant_nan_honest_refusal(self) -> None:
        self.assertTrue(
            dax.local('MAXX(Facts,IF.EAGER(TRUE(),-Facts[Quantity]/0,"a"))').startswith("LOCAL-REJECT:")
        )
        self.assertTrue(
            dax.local('MINX(Facts,IF.EAGER(Facts[Quantity]>2,Facts[Region],Facts[Sales]/Facts[Quantity]))').startswith("LOCAL-REJECT:")
        )

    def test_part_d_zero_product_nan_folding(self) -> None:
        self.assertEqual(
            dax.local('SUMX({BLANK(),1},(1/0*0)/(2.5))'),
            "NaN",
        )
        self.assertEqual(
            dax.local('SUMX(Facts,(1/0*0)+(CURRENCY(2)))'),
            "NaN",
        )
        self.assertEqual(
            dax.local('AVERAGEX(Facts,("2")/(1/0*0))'),
            "0",
        )
        self.assertEqual(
            dax.local('COUNTAX(Facts,(1/0*0)*(2.5))'),
            "0",
        )
        self.assertEqual(
            dax.local('COUNTX(Facts,(1/0*0)*(2.5))'),
            "0",
        )
        self.assertEqual(
            dax.local('COUNTAX(Facts,1/0*0)'),
            "0",
        )
        self.assertEqual(
            dax.local('COUNTX(Facts,1/0*0)'),
            "0",
        )


if __name__ == "__main__":
    unittest.main()
