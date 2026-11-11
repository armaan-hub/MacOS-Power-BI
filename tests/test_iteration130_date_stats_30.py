"""Iteration 130: Task 40 date-stats-30.

Tests for dates inside statistical iterators and negative date-times:
- Part A: VARX.P over dates in conditionals (refused: Power BI's float32 noise is not modelled).
- Part B: PRODUCTX and MEDIANX over expressions involving dates and date arithmetic.
- Part C: Date/time values before December 30, 1899 (OLE Automation negative serials).
"""
import unittest

from tools import dax_oracle_diff as dax


class DateStats30Tests(unittest.TestCase):
    def assertRefused(self, expression: str) -> None:
        # Power BI's answer (float32 noise for VARX.P, a log-based Double product for PRODUCTX) follows no rule the local engine reproduces: refuse
        self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT:"), dax.local(expression))

    def test_part_a_varx_p_over_dates_in_conditionals(self) -> None:
        # Task 47 (2026-11-04): answered now; live Power BI answer
        from tools.parity_check import status
        for powerbi, expression in (
            ("2.91666674613953", 'VARX.P(Facts,DATE(2020,1,1)+Facts[Quantity])'),
            ("2.91666674613953", 'IF(FALSE(),1,VARX.P(Facts,DATE(2020,1,1)+Facts[Quantity]))'),
            ("3.91666674613953", '(VARX.P(Facts,DATE(2020,1,1)+Facts[Quantity]))+1'),
            ("17.5000004768372", 'SUMX(Facts,IF(FALSE(),1,VARX.P(Facts,DATE(2020,1,1)+Facts[Quantity])))'),
            ("2.88888907432556", 'CALCULATE(IF(FALSE(),1,VARX.P(Facts,DATE(2020,1,1)+Facts[Quantity])),Facts[Region]="East")'),
            ("2.88888907432556", 'VARX.P(CALCULATETABLE(Facts,Facts[Region]="East"),IF.EAGER(SELECTEDVALUE(Facts[Region])="East",1,DATE(2020,1,1)+Facts[Quantity]))'),
            ("1.25", 'VARX.P(FILTER(Facts,Facts[Quantity]>1),VAR d=DATE(2020,1,1) RETURN d+Facts[Quantity])'),
            ("2.91666666666667", 'VARX.P(Facts,IF(1=1,CONVERT(Facts[Quantity],DATETIME),DATE(2020,1,1)))'),
        ):
            with self.subTest(expression):
                self.assertEqual("match", status(powerbi, dax.local(expression)))

    def test_part_b_productx_medianx_over_dates(self) -> None:
        # PRODUCTX over Variant holding date (a number agrees to 14 digits; as text it is refused, see test_productx_double_product_refuses_text)
        self.assertTrue(dax.same("7.09068634572637E+27", dax.local('PRODUCTX(Facts,IF.EAGER(1=1,DATE(2020,1,1),Facts[Region]))')))
        self.assertTrue(dax.same("5.23278088563099E-09", dax.local('PRODUCTX(Facts,IF(TRUE(),TIME(1,0,0),Facts[Region]))')))

        # PRODUCTX over MAX / MIN with date
        self.assertTrue(dax.same("7.09068634572637E+27", dax.local('PRODUCTX(Facts,MAX(DATE(2020,1,1),1))')))
        self.assertTrue(dax.same("7.09068634572637E+27", dax.local('PRODUCTX(Facts,MAX(BLANK(),DATE(2020,1,1)))')))
        self.assertEqual("BLANK", dax.local('PRODUCTX(Facts,MIN(DATE(2020,1,1),BLANK()))'))
        self.assertEqual("0", dax.local('PRODUCTX(Facts,MIN(DATE(2020,1,1),Facts[Quantity]))'))

        # PRODUCTX over arithmetic with dates
        self.assertTrue(dax.same("1", dax.local('PRODUCTX(Facts,("1/2/2020")-(MAXX({DATE(2020,1,1)},[Value])))')))

        # MEDIANX over arithmetic with dates
        self.assertTrue(dax.same("-43861", dax.local('MEDIANX(Facts,(MOD(5,2))-(EDATE(DATE(2020,1,1),1)))')))

        # MEDIANX over Variant holding date vs MAX/MIN with date
        self.assertEqual("BLANK", dax.local('MEDIANX(Facts,IF(TRUE(),DATE(2020,1,1),Facts[Region]))'))
        self.assertTrue(dax.same("43831", dax.local('MEDIANX(Facts,MAX(DATE(2020,1,1),1))')))
        self.assertTrue(dax.same("43831", dax.local('MEDIANX(Facts,MAX(BLANK(),DATE(2020,1,1)))')))
        self.assertTrue(dax.same("2.5", dax.local('MEDIANX(Facts,MIN(DATE(2020,1,1),Facts[Quantity]))')))

    def test_productx_double_product_refuses_text(self) -> None:
        # Power BI: 805005849.390624z, 7.08971576117319E+27z (live, Task 40 review): the 15th digit of a Double product is not modelled
        self.assertRefused('(PRODUCTX(Facts,(SUM(Facts[Sales]))-(DATE(1899,12,31))))&"z"')
        self.assertRefused('(PRODUCTX(Facts,(MOD(5,2))-(DATE(2020,1,1))))&"z"')
        self.assertTrue(dax.same("7.08971576117319E+27", dax.local('PRODUCTX(Facts,(MOD(5,2))-(DATE(2020,1,1)))')))

    def test_productx_date_body_refuses_through_arithmetic_and_if(self) -> None:
        # Power BI (live, Task 40 review round 2): 7.51104613175871E+27z where the exact product gives ...865; arithmetic or IF around the product
        # must not hide the refusal from the text conversion, and a product that three summation orders show equal can still differ (EDATE case)
        for expression in (
            '(PRODUCTX(Facts,(Facts[Sales])-(DATE(2021,3,4)))*1)&"z"',
            '(PRODUCTX(Facts,("3/4/2021")-(DATE(1999,12,31)))+0)&"z"',
            '(PRODUCTX(Facts,(SUM(Facts[Sales]))-(DATE(2021,3,4)))+0)&"z"',
            '(PRODUCTX(Facts,(Facts[Sales]+1)-(EOMONTH(DATE(2020,1,1),0)))+0)&"z"',
            '(PRODUCTX(FILTER(Facts,Facts[Quantity]<4),(Facts[Quantity]+1)-(TODAY()*0+DATE(2022,1,1)))*1)&"z"',
            'IF(1=1,PRODUCTX(Facts,(Facts[Sales])-(EDATE(DATE(2010,7,7)+0.25,2))),0)&"z"',
        ):
            self.assertRefused(expression)
        # through a VAR and a LEN of the joined text
        self.assertRefused('VAR p=PRODUCTX(Facts,(Facts[Sales])-(DATE(2021,3,4))) RETURN (p*1)&"z"')
        self.assertRefused('LEN(PRODUCTX(Facts,(Facts[Sales])-(DATE(2021,3,4)))&"")')
        # every other way a number becomes text: FORMAT, CONVERT to STRING, CONCATENATEX, the text functions (through arithmetic, IF and VARs too)
        product = "PRODUCTX(Facts,(Facts[Sales])-(DATE(2021,3,4)))"
        for expression in (
            f'FORMAT({product},"0")',
            f'FORMAT({product}*1,"General Number")',
            f"CONVERT({product},STRING)",
            f"CONVERT(IF(1=1,{product},0)+0,STRING)",
            f"VAR p={product} RETURN CONVERT(p,STRING)",
            f'VAR p={product} RETURN FORMAT(p,"0")',
            f'CONCATENATEX(Facts,{product},",")',
            f"LEN({product})",
            f"LEFT({product}*1,5)",
            f"MID({product},1,3)",
            f'SUBSTITUTE({product},"1","2")',
            f"UPPER({product})",
            f'CONCATENATE({product},"z")',
        ):
            self.assertRefused(expression)
        # CONVERT to a number does not make text
        self.assertTrue(dax.same("7.51104613175871E+27", dax.local(f"CONVERT({product},DOUBLE)")))
        # the same product as a number is answered (it agrees with Power BI to 14 digits)
        self.assertTrue(dax.same("7.51104613175871E+27", dax.local('PRODUCTX(Facts,(Facts[Sales])-(DATE(2021,3,4)))*1')))
        # a product of dates that is exact stays answered
        self.assertEqual("652458240z", dax.local('(PRODUCTX(Facts,(Facts[Quantity])-(EDATE(DATE(1899,12,31),1))))&"z"'))

    def test_second_of_negative_serial_with_fraction_of_second_is_answered(self) -> None:
        # Task 48 (2026-11-04): answered now; live Power BI answer (dax_battery_datestats30_extra: 27 for each)
        for expression in (
            "SECOND(-(3)+(0.999))",
            "SECOND(-(10.5)+(0.999))",
            "SECOND(-(DATE(1900,1,2))+(0.999))",
            "SECOND(-(DATE(2019,5,5))+(0.999))",
        ):
            self.assertEqual("27", dax.local(expression))
        # whole seconds and hours / minutes that rounding cannot change stay answered (live)
        self.assertEqual("51", dax.local("SECOND((TIME(9,9,9))-(DATE(2019,5,5)))"))
        self.assertEqual("1", dax.local("MINUTE(-(DATE(2019,5,5))+(0.999))"))
        self.assertEqual("0", dax.local("HOUR(-(DATE(1900,1,2))+(0.999))"))

    def test_part_c_negative_date_time_serials(self) -> None:
        # Negative serials with time part
        self.assertEqual("12/17/1899 12:00:00", dax.local('SUMX(Facts,IF.EAGER(TRUE(),TIME(6,0,0)-Facts[Quantity],"a"))'))
        self.assertEqual("12/29/1899 06:00:00", dax.local('MINX(Facts,IF.EAGER(TRUE(),TIME(6,0,0)+Facts[Sales],"a"))'))
        self.assertEqual("12/26/1899 18:00:00", dax.local('MINX(Facts,IF.EAGER(TRUE(),TIME(6,0,0)-Facts[Quantity],"a"))'))
        self.assertEqual("12/30/1899 18:00:00", dax.local('(TIMEVALUE("06:00"))-1'))
        self.assertEqual("12/29/1779 18:00:00", dax.local('(TIME(6,0,0))-(DATE(2020,1,1))'))
        self.assertEqual("12/29/1779 6:00:00 PMz", dax.local('((TIME(6,0,0))-(DATE(2020,1,1)))&"z"'))
        self.assertEqual("12/29/1779 18:00:00", dax.local('MAXX(Facts,(TIME(6,0,0))-(DATE(2020,1,1)))'))

        # Negative numbers in EDATE
        self.assertEqual("363", dax.local('COALESCE(EDATE(MIN(Facts[Sales]),"12"),5)'))
        self.assertEqual("606", dax.local('COALESCE(EDATE(MIN(Facts[Sales]),MAX(Facts[Sales])),5)'))
        self.assertEqual("-2", dax.local('COALESCE(EDATE(MIN(Facts[Sales]),IF(1=2,1)),5)'))

        # Negative datetime text formatting
        self.assertEqual("12/28/1899 12:00:00 PM", dax.local('(MAXX(FILTER(Facts,FALSE()),DATE(2021,6,1))-2.5)&""'))

    def test_exact_half_second_of_negative_serial_is_refused_and_card_is_safe(self) -> None:
        # Task 40 t40h: Power BI rounds an exact half second of a serial below zero up or down by the last digit of its double
        # (DATE(1800,1,1)+1.5/86400 shows 11:59:58 PM, DATE(1850,7,4)+1.5/86400 shows 11:59:59 PM): refused, never guessed
        for expression in (
            '(DATE(1800,1,1)+1.5/86400)&"z"', '(DATE(1850,7,4)+1-1.5/86400)&"z"',
            '(DATE(1899,12,29)+1-1.5/86400)&"z"', 'FORMAT(DATE(1899,12,29)+1-1.5/86400,"yyyy-mm-dd hh:nn:ss")',
            'FORMAT(DATE(1899,1,15)+1.5/86400,"yyyy-mm-dd hh:nn:ss")',
        ):
            self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"), expression)
        # off the half second, and a time of day after day zero, keep their measured answers
        self.assertEqual("1/2/1800 11:59:55 PMz", dax.local('(DATE(1800,1,1)+5.25/86400)&"z"'))
        self.assertEqual("1899-12-30 00:00:02", dax.local('FORMAT(-0+1.5/86400,"yyyy-mm-dd hh:nn:ss")'))
        self.assertEqual("1899-12-30 00:00:01", dax.local('FORMAT(-0+0.5/86400,"yyyy-mm-dd hh:nn:ss")'))
        self.assertEqual("1899-12-30 23:59:59", dax.local('FORMAT(-0+1-1.5/86400,"yyyy-mm-dd hh:nn:ss")'))
        # the report card never receives such a value: the evaluator refuses it and the next measure still evaluates
        from analytics_studio.controller import _format_report_number
        from analytics_studio.measures import MeasureError, evaluate_measures

        def evaluate(expression: str):
            return evaluate_measures(
                [{"name": "Probe__", "expression": expression}], dax.LOCAL_ROWS, dax.HEADERS, "Facts", measure_names=["Probe__"],
                table_context=[{
                    "id": "facts", "name": "Facts", "headers": dax.HEADERS, "rows": dax.LOCAL_ROWS,
                    "column_types": {"Sales": "decimal_number", "Quantity": "whole_number", "Region": "text", "Note": "text"},
                }],
                active_table_id="facts",
            )["Probe__"]

        for expression in ("DATE(1800,1,1)+1.5/86400", "DATE(1899,12,29)+1-1.5/86400"):
            with self.assertRaises(MeasureError, msg=expression):
                _format_report_number(evaluate(expression))
        self.assertEqual("15", _format_report_number(evaluate("SUM(Facts[Quantity])")))


if __name__ == "__main__":
    unittest.main()
