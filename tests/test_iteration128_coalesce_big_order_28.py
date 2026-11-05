"""Iteration 128: tests for Task 38 coalesce-big-order-28.

Covers:
- Part A: COALESCE whose earlier argument can fail in iterator bodies, IFERROR date-to-number unification,
  variant COALESCE date/blank typing, AVERAGEX all-NaN date/number unification over stored scans.
- Part B: Rounding of numbers >= 1E15 (IEEE-754 double precision vs DAX 15-digit decimal rounding).
- Part C: CONCATENATEX without an order: dictionary order walk for constant conditionals, constant bodies,
  and proper refusals for unmodelled table constructors / multi-table generators.
"""

import unittest
from tools import dax_oracle_diff as dax


class TestIteration128CoalesceBigOrder28(unittest.TestCase):
    def test_part_a_coalesce_failing_argument_in_iterators(self) -> None:
        self.assertEqual(
            dax.local('MAXX(Facts,COALESCE(Facts[Note],VARX.S(FILTER(Facts,FALSE()),1),1))'),
            "1",
        )
        self.assertEqual(
            dax.local('SUMX({1,2},COALESCE(CONVERT("3",DOUBLE),CONVERT("3",DOUBLE)))'),
            "6",
        )
        self.assertEqual(
            dax.local('MAXX(Facts,COALESCE(PERCENTILEX.INC(Facts,Facts[Quantity],0.5),"a"))'),
            "2.5",
        )
        self.assertEqual(
            dax.local('COUNTX({1},COALESCE(CONVERT(0||"",DATETIME),CONVERT(0||"",DATETIME)))'),
            "BLANK",
        )
        self.assertEqual(
            dax.local('MAXX(Facts,COALESCE(FIRSTNONBLANKVALUE(Facts[Quantity],BLANK()),"a"))'),
            "BLANK",
        )
        self.assertEqual(
            dax.local('COUNTX(Facts,COALESCE(FIRSTNONBLANKVALUE(Facts[Quantity],BLANK()),"a"))'),
            "BLANK",
        )
        self.assertEqual(
            dax.local('IFERROR(MAXX(Facts,COALESCE(SUMX(VALUES(Facts[Region]),DATE(2020,1,1)),"a")),7)'),
            "131493",
        )
        self.assertEqual(
            dax.local('AVERAGEX(Facts,COALESCE(CONVERT(0/0,DATETIME),CONVERT(0/0,DATETIME)))'),
            "0",
        )
        self.assertEqual(
            dax.local('SUMX(Facts,IF(ISBLANK(COALESCE((1&&"")&(LOOKUPVALUE(Facts[Quantity],Facts[Region],"Nope")),1)),1,2))'),
            "6",
        )

    def test_part_b_big_number_rounding(self) -> None:
        self.assertEqual(
            dax.local('MROUND(2^53,2)&"z"'),
            "9007199254740992z",
        )
        self.assertEqual(
            dax.local('MROUND(2^53,1.5)&"z"'),
            "9.00719925474099E+15z",
        )
        self.assertEqual(
            dax.local('FLOOR(2^60,11)&"z"'),
            "1152921504606850048z",
        )
        self.assertEqual(
            dax.local('CEILING(2^61,1024)&"z"'),
            "2305843009213696000z",
        )
        # Task 55 (2026-11-05): answered now; live Power BI answers (saved batteries)
        for expression, expected in (
            ('(CONVERT(2^52+0.25,INTEGER))&"z"', '4503599627370496z'),
            ('(CONVERT(2^52+1,INTEGER))&"z"', '4503599627370498z'),
            ('FLOOR(2^52,1)&"z"', '4503599627370500z'),
            ('CEILING(2^52+0.25,1024)&"z"', '4503599627370496z'),
            ('INT(2^52-0.5)&"z"', '4503599627370495z'),
            ('FLOOR(7*2^50+0.5,3)&"z"', '7881299347898370z'),
            ('QUOTIENT(2^63-1024,1024)&"z"', '9007199254740992z'),
            ('QUOTIENT(2^52+1,1)&"z"', '4503599627370498z'),
            ('QUOTIENT(2^54+5,3)&"z"', '6004799503160664z'),
        ):
            self.assertEqual(dax.local(expression), expected, expression)

    def test_part_c_concatenatex_without_order(self) -> None:
        self.assertEqual(
            dax.local('CONCATENATEX(Facts,IF(1=1,Facts[Region],-(7)))'),
            "EastEastEastWestWestNorth",
        )
        self.assertEqual(
            dax.local('CONCATENATEX(Facts,IF(1=1,-Facts[Quantity],Facts[Region]))'),
            "0-1-2-3-4-5",
        )
        self.assertEqual(
            dax.local('CONCATENATEX(Facts,IF.EAGER(1=1,Facts[Quantity],LEFT("a",1)))'),
            "012345",
        )
        self.assertEqual(
            dax.local('CONCATENATEX(Facts,IF.EAGER(1=1,-Facts[Quantity],Facts[Sales]))'),
            "0-1-2-3-4-5",
        )
        self.assertEqual(
            dax.local('CONCATENATEX(Facts,IF(1=1,Facts[Region],Facts[Sales]))'),
            "EastEastEastWestWestNorth",
        )
        self.assertEqual(
            dax.local('CONCATENATEX(Facts,COALESCE(BLANK(),1.5,DATEVALUE("2020-01-01")),"|")'),
            "1.5|1.5|1.5|1.5|1.5|1.5",
        )
        # Unmodelled multi-table generators stay honestly refused
        self.assertTrue(
            dax.local('CONCATENATEX(GENERATE(VALUES(Facts[Note]),VALUES(Facts[Region])),IF(TRUE(),Facts[Region],1))').startswith("LOCAL-REJECT:")
        )
        self.assertTrue(
            dax.local('CONCATENATEX(SUMMARIZECOLUMNS(Facts[Region]),IF(TRUE(),Facts[Region],1))').startswith("LOCAL-REJECT:")
        )
        self.assertTrue(
            dax.local('CONCATENATEX(UNION(Facts,Facts),IF(TRUE(),Facts[Region],1))').startswith("LOCAL-REJECT:")
        )


    def test_part_b_power_beyond_2_53_is_the_double_of_the_whole_expression(self) -> None:
        # measured in Power BI Desktop: a power that is exactly a double (2^n, or 3^k below 2^53) is unambiguous; the rest of the expression is double arithmetic
        measured = {
            'MROUND(2^54+3,3)&"z"': "18014398509481988z",
            'INT(2^60+1)&"z"': "1152921504606846976z",
            'CEILING(2^60*3,7)&"z"': "3458764513820538880z",
            'INT(3^33*3)&"z"': "16677181699666568z",
        }
        for expression, expected in measured.items():
            self.assertEqual(dax.local(expression), expected, expression)

    def test_part_b_inexact_power_beyond_2_53_is_refused(self) -> None:
        # Task 46 (2026-11-04): a whole-number power is square-and-multiply in doubles like Power BI, so these are answered now;
        # every value below is the live Power BI Desktop answer (saved batteries, and FLOOR/CEILING measured on 2026-11-04)
        for expression, expected in (
            ('INT(POWER(1.5,98))&"z"', '180693856682317856z'),
            ('INT(1.5^100)&"z"', '406561177535215296z'),
            ('INT(2.5^45)&"z"', '807793566946316160z'),
            ('INT(13^17)&"z"', '8650415919381339136z'),
            ('QUOTIENT(POWER(13,17)+3,2)&"z"', '4325207959690669568z'),
            ('MROUND(1.5^98,5)&"z"', '180693856682317824z'),
            ('QUOTIENT(13^17*3,7)&"z"', '3707321108306288128z'),
            ('(CONVERT(3^34+1,INTEGER))&"z"', '16677181699666568z'),
            ('INT(3^34+1)&"z"', '16677181699666568z'),
            ('MROUND(POWER(3,35),9)&"z"', '50031545098999704z'),
            ('FLOOR(1.5^100,1)&"z"', '406561177535214976z'),
            ('CEILING(1.5^100,1)&"z"', '406561177535214976z'),
        ):
            self.assertEqual(dax.local(expression), expected, expression)


    def test_part_c_round_4_ceiling_tie_and_quotient_band(self) -> None:
        # measured (fourth fresh set): the quotient 5552790630845645 is cut to 15 digits with an exact tie going up (...650), so the product is 27763953154228248
        self.assertEqual(dax.local('CEILING(3^25*2^15,5)&"z"'), "27763953154228248z")
        # Task 55 (2026-11-05): answered now; live Power BI answer
        self.assertEqual(dax.local('QUOTIENT(POWER(7,14)*POWER(2,14)+1,1.5)&"z"'), '7408004550372012z')


if __name__ == "__main__":
    unittest.main()
