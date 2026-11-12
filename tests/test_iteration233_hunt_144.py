"""Iteration 233: Task 144 (dax-hunt-144), hunt backlog batch 2. Values are the Power BI answers measured for the spec rows."""

import unittest
from decimal import Decimal
from tools import dax_oracle_diff as dax
from tools.dax_oracle_diff import same


def same15(pbi: str, loc: str) -> bool:
    # Task 144: Power BI doubles are compared at 15 significant digits
    return Decimal(format(Decimal(loc), ".15g")) == Decimal(pbi)


class TestIteration233Hunt144(unittest.TestCase):
    def test_family_j_query_level_errors_are_not_caught_by_iferror(self) -> None:
        # Power BI fails the whole query for these; the local engine refuses them (never the IFERROR fallback "E")
        for expr in (
            'IFERROR(PERCENTILE.EXC(Facts[Sales],0.9),"E")',
            'IFERROR(PERCENTILE.INC(Facts[Sales],-0.1),"E")',
            'IFERROR(PERCENTILE.EXC(Facts[Quantity],BLANK()),"E")',
            'IFERROR(COUNTROWS(CALENDAR(DATE(2020,13,45),DATE(2021,1,1))),"E")',
            'IFERROR(COUNTROWS(CALENDAR(DATE(10000,1,1),DATE(10000,2,1))),"E")',
            'IFERROR(COUNTROWS(SAMPLE(-1,Facts,Facts[Sales])),"E")',
        ):
            self.assertTrue(dax.local(expr).startswith("LOCAL-REJECT:"), expr)
        # Power BI returns values for these, so they stay answers
        self.assertTrue(same("2.5", dax.local("PERCENTILE.INC(Facts[Quantity],0.5)")))
        self.assertTrue(same("36890", dax.local('IFERROR(COUNTROWS(CALENDAR(DATE(-1,1,1),DATE(2000,1,1))),"E")')))
        self.assertTrue(same("BLANK", dax.local('IFERROR(COUNTROWS(SAMPLE(0,Facts,Facts[Sales])),"E")')))

    def test_family_k_floor_ceiling_fractional_significance(self) -> None:
        self.assertTrue(same("8.88178419700125E-16", dax.local("FLOOR(7,1E-5)-7")))
        self.assertTrue(same("-0.100000000000001", dax.local("FLOOR(7,0.3)-7")))
        self.assertTrue(same("1.4210854715202E-14", dax.local("FLOOR(100,1E-5)-100")))
        self.assertTrue(same("2.22044604925031E-16", dax.local("FLOOR(1.5,1E-5)-1.5")))
        self.assertTrue(same("-2.0000000766629E-08", dax.local("FLOOR(8,3E-8)-8")))
        self.assertTrue(same("0", dax.local("FLOOR(0.5,1E-5)-0.5")))
        self.assertTrue(same("9", dax.local("ODD(FLOOR(7,1E-5))")))
        self.assertTrue(same("-9", dax.local("ODD(FLOOR(-7,1E-5))")))
        self.assertTrue(same("102", dax.local("EVEN(CEILING(100,1E-5))")))

    def test_family_l_effect_in_double(self) -> None:
        self.assertTrue(same("4.16333634234434E-17", dax.local("EFFECT(0.05,1)-0.05")))
        self.assertTrue(same("-8.88178419700125E-16", dax.local("1-EFFECT(0.05,1)/0.05")))
        # Task 144 family L: PRICEDISC with a discount that cancels 1 is no longer refused (the double residue is computed in the Power BI order)
        self.assertTrue(same15("6.93889390390723E-18", dax.local("PRICEDISC(DATE(2020,1,1),DATE(2021,1,1),1,EFFECT(0.05,1))")))
        self.assertTrue(same("-4.99999999999806E-06", dax.local("PRICEDISC(DATE(2020,1,1),DATE(2021,1,1),1.0001,0.05,1)")))
        # PRICEDISC with a discount far from 1 keeps its answer
        self.assertTrue(same("-4.95", dax.local("PRICEDISC(DATE(2020,1,1),DATE(2021,1,1),100,EFFECT(0.05,1))")))

    def test_family_m_varx_doubles_and_stdevx_s_refused(self) -> None:
        self.assertTrue(same("0.138888888888886", dax.local("VARX.P(Facts,LEN(Facts[Region]))")))
        self.assertTrue(same("0.372677996249961", dax.local("STDEVX.P(Facts,LEN(Facts[Region]))")))
        self.assertTrue(same("0.388888888888889", dax.local("VARX.S(Facts,Facts[Quantity]/3)")))
        # Task 144 family M: STDEVX.S is no longer refused; compared at 15 significant digits
        self.assertTrue(same15("0.623609564462323", dax.local("STDEVX.S(Facts,Facts[Quantity]/3)")))
        self.assertTrue(same15("0.388888888888889", dax.local("VARX.S(Facts,Facts[Quantity]/3)")))

    def test_task144_round_to_multiple_and_discount_values(self) -> None:
        # Task 144 fix round: FLOOR/CEILING fractional significance, CURRENCY multiple, PRICEDISC
        self.assertTrue(same15("5.55111512312578E-17", dax.local("CEILING(0.3,0.1)-0.3")))
        self.assertTrue(same15("0", dax.local("CEILING(1.1,0.1)-1.1")))
        self.assertTrue(same15("0", dax.local("FLOOR(2.5,0.3)-2.4")))
        self.assertTrue(same15("2.7", dax.local("CEILING(CURRENCY(2.5),0.3)")))

    def test_family_n_ispmt_currency_principal(self) -> None:
        self.assertTrue(same("-0.2469", dax.local("ISPMT(CURRENCY(0.1),3,-3,CURRENCY(1.23456))")))
        self.assertTrue(same("-0.1132", dax.local("ISPMT(0.1,1,12,CURRENCY(1.23456))")))
        self.assertTrue(same("0.7778", dax.local("ISPMT(0.1,0,5,CURRENCY(-7.777777))")))
        self.assertTrue(same("1.5556", dax.local("ISPMT(0.1,3,-3,CURRENCY(-7.777777))")))
        self.assertTrue(same("0.713", dax.local("ISPMT(0.1,1,12,CURRENCY(-7.777777))")))
        self.assertTrue(same("-91.6666666666667", dax.local("ISPMT(CURRENCY(0.1),1,12,1000)")))

    def test_family_o_productx_currency_column_refused(self) -> None:
        self.assertTrue(dax.local("PRODUCTX(FILTER(Facts,Facts[Sales]<>0),CURRENCY(Facts[Sales]/7))").startswith("LOCAL-REJECT:"))
        self.assertTrue(dax.local("PRODUCTX(FILTER(Facts,Facts[Quantity]>0),CURRENCY(Facts[Quantity]/3))").startswith("LOCAL-REJECT:"))

    def test_family_h_oddfyield_long_first_coupon_refused(self) -> None:
        self.assertTrue(
            dax.local("ODDFYIELD(DATE(2020,1,1),DATE(2025,1,1),DATE(2019,10,1),DATE(2020,7,1),0.05,98,100,2)").startswith("LOCAL-REJECT:")
        )
        self.assertTrue(
            dax.local('IFERROR(ODDFYIELD(DATE(2020,1,1),DATE(2025,1,1),DATE(2019,12,1),DATE(2020,7,1),0,98,100,2),"E")').startswith("LOCAL-REJECT:")
        )
        # the measured short-first-coupon example of Iteration 123 is unchanged
        self.assertTrue(
            same("0.0772455415972989", dax.local("ODDFYIELD(DATE(2008,11,11),DATE(2021,3,1),DATE(2008,10,15),DATE(2009,3,1),0.0575,84.5,100,2,0)"))
        )


if __name__ == "__main__":
    unittest.main()
