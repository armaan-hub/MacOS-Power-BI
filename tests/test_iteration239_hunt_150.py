"""Task 150 (dax-hunt-150): fresh Power BI hunt, batch 8. Exact assertions per family, values copied from the measured Power BI answers.

Family A: a CURRENCY amount result is a Currency only when every other amount argument is a Currency, whole number or BLANK;
a double amount argument (2.0, 0.5, TRUE(), "1", a date difference, SUM of a double column) makes the plain double.
Family B: the redemption / investment / par amount positions of PRICE, PRICEDISC, ODDFPRICE, ODDLPRICE, RECEIVED, ACCRINT, ACCRINTM,
DOLLARDE and DOLLARFR take a CURRENCY the same way (the rate and yield positions do not).
Family C: DIVIDE of a CURRENCY by a number is a Currency (rounded per value) and CONVERT(x,CURRENCY) is a Currency for a MEDIANX body.
"""

import unittest
from decimal import Decimal

from tools.dax_oracle_diff import local


def _same_15(expression: str, measured: str) -> bool:
    """The local answer and the measured Power BI answer agree to 15 significant digits."""
    return float(f"{float(local(expression)):.15g}") == float(f"{float(measured):.15g}")


class TestIteration239Hunt150(unittest.TestCase):
    # Family A: the Currency result stays when the other amount arguments are Currency, whole number or BLANK
    def test_family_a_currency_stays_currency(self):
        self.assertEqual(Decimal(local("PMT(0.05,2,CURRENCY(1.23456),1)")), Decimal("-1.1518"))
        self.assertEqual(Decimal(local("PMT(0.05,2,CURRENCY(1.23456),INT(2.5))")), Decimal("-1.6396"))
        self.assertEqual(Decimal(local("PMT(0.05,2,CURRENCY(1.23456),BLANK())")), Decimal("-0.664"))
        self.assertEqual(Decimal(local("PMT(0.05,2,CURRENCY(1.23456),0)")), Decimal("-0.664"))
        self.assertEqual(Decimal(local("PMT(0.05,2,CURRENCY(1.23456)*0.5)")), Decimal("-0.332"))
        self.assertEqual(Decimal(local("FV(0.05,2,CURRENCY(1.23456),CURRENCY(1.23456)*0.5)")), Decimal("-3.2115"))

    def test_family_a_double_amount_is_double(self):
        self.assertTrue(_same_15("PMT(0.05,2,CURRENCY(1.23456),2.0)", "-1.63958365853659"))
        self.assertTrue(_same_15("PMT(0.05,2,CURRENCY(1.23456),1E2)", "-49.4444617073171"))
        self.assertTrue(_same_15("PMT(0.05,2,CURRENCY(1.23456),DIVIDE(4,2))", "-1.63958365853659"))
        self.assertTrue(_same_15("PMT(0.05,2,CURRENCY(1.23456),4/2)", "-1.63958365853659"))
        self.assertTrue(_same_15("PMT(0.05,2,CURRENCY(1.23456),0.0)", "-0.663973902439024"))
        self.assertTrue(_same_15("PMT(0.05,2,CURRENCY(1.23456),SUM(Facts[Sales]))", "-16.0298275609756"))
        self.assertTrue(_same_15("FV(0.05,2,CURRENCY(1.23456),2.5)", "-5.28718"))
        self.assertTrue(_same_15("FV(0.05,2,CURRENCY(1.23456),CURRENCY(1.23456)+0.5)", "-4.4433265"))
        self.assertTrue(_same_15("SLN(CURRENCY(1000.12345),100.25,3)", "299.957833333333"))
        self.assertTrue(_same_15("SYD(CURRENCY(1000.12345),100.5,3,1)", "449.81175"))
        self.assertTrue(_same_15("DB(CURRENCY(1000.12345),100.5,3,1)", "535.0660725"))
        self.assertTrue(_same_15("VDB(CURRENCY(1.23456),2.5,5,0.05,0.25)", "-0.25308"))
        self.assertTrue(_same_15("SLN(CURRENCY(1.23456),DATE(2020,1,1)-DATE(2020,1,1),3)", "0.411533333333333"))
        self.assertTrue(_same_15("IPMT(0.05,1,2,CURRENCY(1.23456),0.5)", "-0.06173"))

    # Family B: the bond and fractional-dollar amount positions
    def test_family_b_bond_amount_positions_are_currency(self):
        self.assertEqual(Decimal(local("PRICE(DATE(2020,1,1),DATE(2025,1,1),0.05,0.06,CURRENCY(1.23456),2)")), Decimal("22.2442"))
        self.assertEqual(Decimal(local("PRICEDISC(DATE(2020,1,1),DATE(2021,1,1),0.1,CURRENCY(1.23456))")), Decimal("1.1111"))
        self.assertEqual(Decimal(local("PRICEDISC(DATE(2020,1,1),DATE(2021,1,1),0.1,CURRENCY(1.23456),1)")), Decimal("1.1111"))
        self.assertEqual(Decimal(local("ODDFPRICE(DATE(2020,1,1),DATE(2025,1,1),DATE(2019,12,1),DATE(2020,7,1),0.05,0.06,CURRENCY(1.23456),2)")), Decimal("22.232"))
        self.assertEqual(Decimal(local("RECEIVED(DATE(2020,1,1),DATE(2021,1,1),CURRENCY(1.23456),0.05)")), Decimal("1.2996"))
        self.assertEqual(local('RECEIVED(DATE(2020,1,1),DATE(2021,1,1),CURRENCY(1.23456),0.05)&"z"'), "1.2996z")
        self.assertEqual(Decimal(local("RECEIVED(DATE(2020,1,1),DATE(2021,1,1),CURRENCY(1.23456),0.05)*1")), Decimal("1.2996"))
        self.assertEqual(Decimal(local("ACCRINT(DATE(2020,1,1),DATE(2020,7,1),DATE(2020,3,1),0.05,CURRENCY(1000.12345),2)")), Decimal("8.3344"))
        self.assertEqual(Decimal(local("ACCRINTM(DATE(2020,1,1),DATE(2021,1,1),0.05,CURRENCY(1000.12345))")), Decimal("50.0062"))
        self.assertEqual(Decimal(local("DOLLARDE(CURRENCY(1.23456),16)")), Decimal("2.4662"))
        self.assertEqual(Decimal(local("DOLLARFR(CURRENCY(1.23456),16)")), Decimal("1.0375"))

    def test_family_b_rate_and_yield_positions_stay_double(self):
        self.assertTrue(_same_15("ACCRINTM(DATE(2020,1,1),DATE(2021,1,1),0.05,1000.5)", "50.025"))
        self.assertTrue(_same_15("ACCRINTM(DATE(2020,1,1),DATE(2021,1,1),CURRENCY(1.23456),1000)", "1234.6"))
        self.assertTrue(_same_15("ACCRINT(DATE(2020,1,1),DATE(2020,7,1),DATE(2020,3,1),CURRENCY(1.23456),1000,2)", "205.766666666667"))
        self.assertTrue(_same_15("EFFECT(CURRENCY(1.23456),2)", "1.61565929"))
        self.assertTrue(_same_15("NOMINAL(CURRENCY(1.23456),2)", "0.989715705547937"))
        self.assertTrue(_same_15("RRI(2,CURRENCY(1.23456),2)", "0.272775660159752"))
        self.assertTrue(_same_15("PDURATION(0.1,CURRENCY(1.23456),2)", "5.06137068015894"))
        self.assertTrue(_same_15("AMORLINC(CURRENCY(1.23456),DATE(2020,1,1),DATE(2020,12,31),0.1,1,0.15)", "0.18519"))

    # Family C: DIVIDE and CONVERT(x,CURRENCY) feed the Currency midpoint rule of MEDIANX
    def test_family_c_divide_and_convert_are_currency(self):
        self.assertEqual(Decimal(local("MEDIANX({1,2},DIVIDE(CURRENCY(0.0003)*[Value],2))")), Decimal("0.0003"))
        self.assertEqual(Decimal(local("MEDIANX({1,2},CONVERT(CURRENCY(0.0003)*[Value],CURRENCY))")), Decimal("0.0005"))
        self.assertEqual(Decimal(local("MEDIANX({1,2},CURRENCY(0.0003)*[Value]/2)")), Decimal("0.0003"))

    def test_family_c_currency_times_currency_and_if_stay_double(self):
        self.assertTrue(_same_15("MEDIANX({1,2},CURRENCY(0.0003)*[Value]*CURRENCY(1))", "0.00045"))
        self.assertEqual(local('(CURRENCY(0.0003)*CURRENCY(1.5))&"z"'), "0.00045z")
        self.assertTrue(_same_15("MEDIANX({1,2},IF(TRUE(),CURRENCY(0.0003)*[Value],0.5))", "0.00045"))


if __name__ == "__main__":
    unittest.main()
