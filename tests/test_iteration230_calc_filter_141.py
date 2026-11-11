"""Iteration 230: Task 141 dax-calcfilter-141.

CALCULATE filter arguments that the legacy paths refused: a strict equality filter (Facts[X]==BLANK() or Facts[X]==value)
beside a table filter or a plain filter, and the same column in a plain and a KEEPFILTERS filter. These now fall back to the
general filter path (the Power BI answers recorded with the task). Every case must be exact against the Power BI answer;
a wrong answer fails the test.
"""
import unittest

from tools import dax_oracle_diff as dax

CASES = (
    ("CALCULATE(CONCATENATEX(VALUES(Facts[Region]),Facts[Region],\",\"),TREATAS({\"East\",\"West\"},Facts[Region]),Facts[Region]==BLANK())", "BLANK"),
    ("COUNTROWS(CALCULATETABLE(Facts,KEEPFILTERS(VAR t = \"East\" RETURN Facts[Region]==t),Facts[Region]<>\"East\"))", "BLANK"),
    ("COUNTROWS(CALCULATETABLE(Facts,KEEPFILTERS(VAR t = IF(TRUE(),2,3) RETURN Facts[Quantity]==t),Facts[Quantity]>1))", "1"),
    ("CALCULATE(COUNTROWS(Facts),KEEPFILTERS(Facts[Region]=\"East\"),VAR t = BLANK() VAR u = t+1 RETURN Facts[Region]==t)", "BLANK"),
    ("CALCULATE(MAX(Facts[Sales]),Facts[Quantity]>1,KEEPFILTERS(VAR t = 2 RETURN Facts[Quantity]==t))", "10.5"),
    ("CALCULATE(SUM(Facts[Sales]),TREATAS({2,3},Facts[Quantity]),Facts[Region]==BLANK())", "BLANK"),
    ("CALCULATE(SUM(Facts[Sales]),KEEPFILTERS(Facts[Quantity]==BLANK()),KEEPFILTERS(Facts[Sales]=BLANK()),TREATAS({\"East\",\"West\"},Facts[Region]))", "BLANK"),
    ("CALCULATE(COUNTBLANK(Facts[Note]),Facts[Region]==BLANK(),KEEPFILTERS(Facts[Region]=BLANK()))", "BLANK"),
    ("CALCULATE(COUNTROWS(Facts),KEEPFILTERS(Facts[Region]=BLANK()),KEEPFILTERS(Facts[Sales]==BLANK()),VALUES(Facts[Quantity]))", "BLANK"),
    ("CALCULATE(SUM(Facts[Quantity]),VAR t = BLANK() VAR u = t+1 RETURN Facts[Region]==t,KEEPFILTERS(Facts[Region]=\"East\"))", "BLANK"),
    ("CALCULATE(CALCULATE(COUNTROWS(ALLSELECTED(Facts)),TREATAS({2,3},Facts[Quantity]),Facts[Note]==BLANK()),ALLSELECTED())", "1"),
    ("CALCULATE(CALCULATE(MAX(Facts[Quantity]),Facts[Quantity]==BLANK(),KEEPFILTERS(NOT(Facts[Note]=\"Paid\")),TREATAS({\"East\",\"West\"},Facts[Region])),FILTER(Facts,ISBLANK(Facts[Quantity])))", "BLANK"),
    ("CALCULATE(ISINSCOPE(Facts[Region]),TREATAS({2,3},Facts[Quantity]),Facts[Region]==BLANK())", "False"),
    ("CALCULATE(COUNTROWS(FILTERS(Facts[Region])),Facts[Note]<>\"Paid\",Facts[Region]==BLANK(),TREATAS({2,3},Facts[Quantity]))", "BLANK"),
    ("CALCULATE(COUNTBLANK(Facts[Note]),Facts[Quantity]=2,ALLNOBLANKROW(Facts[Quantity]),KEEPFILTERS(Facts[Quantity]==BLANK()))", "BLANK"),
    ("CALCULATE(SUM(Facts[Sales]),Facts[Region]=\"East\",KEEPFILTERS(Facts[Region]==BLANK()))", "BLANK"),
)


class CalculateFilter141Test(unittest.TestCase):
    def test_power_bi_answers(self):
        for expression, expected in CASES:
            with self.subTest(expression=expression):
                local = dax.local(expression)
                self.assertFalse(local.startswith("LOCAL-"), f"refused or crashed: {local}")
                self.assertTrue(dax.same(expected, local), f"Power BI {expected}, local {local}")


if __name__ == "__main__":
    unittest.main()
