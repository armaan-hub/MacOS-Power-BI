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

# Overwriting or clearing one column of a table filter that other filters share (the sets of whole rows stay separate;
# a changed set keeps constraining the other columns through its projection; a filter beside the sets on a column is
# remembered next to them), and a Boolean filter beside ALLSELECTED over such a set. Power BI answers.
SHAPE_CASES = (
    ('CALCULATE(CALCULATE(CALCULATE(DISTINCTCOUNT(Facts[Quantity]),Facts[Note]=="Late"),KEEPFILTERS(FILTER(ALL(Facts),NOT(Facts[Note]=="Paid")))),KEEPFILTERS(Facts[Quantity]==2))', 'BLANK'),
    ('CALCULATE(CALCULATE(COUNTROWS(VALUES(Facts[Quantity])),KEEPFILTERS(FILTER(ALL(Facts),Facts[Quantity]<>3))),KEEPFILTERS(FILTER(ALL(Facts),Facts[Quantity]=4)),Facts[Note]=BLANK())', 'BLANK'),
    ('CALCULATE(CALCULATE(HASONEVALUE(Facts[Note]),Facts[Quantity]<>2),KEEPFILTERS(FILTER(Facts,Facts[Quantity]<>BLANK())),FILTER(ALL(Facts),ISBLANK(Facts[Note])))', 'True'),
    ('CALCULATE(CALCULATE(CALCULATE(CONCATENATEX(VALUES(Facts[Region]),Facts[Region],",",Facts[Region],ASC),KEEPFILTERS(Facts[Quantity]>0),Facts[Region]="East"||Facts[Quantity]=BLANK()),KEEPFILTERS(FILTER(Facts,Facts[Quantity]=BLANK())),Facts[Sales]==BLANK()),KEEPFILTERS(FILTER(ALL(Facts),Facts[Region]<>BLANK()&&Facts[Region]=="East")),KEEPFILTERS(FILTER(ALL(Facts),Facts[Note]="Paid")))', 'BLANK'),
    ('CALCULATE(CALCULATE(CALCULATE(COUNTROWS(Facts),ALLEXCEPT(Facts,Facts[Sales]),FILTER(ALL(Facts),Facts[Sales]<0&&Facts[Note]=="Paid")),FILTER(Facts,Facts[Quantity]=3),KEEPFILTERS(FILTER(Facts,Facts[Sales]==0))),KEEPFILTERS(Facts[Sales]=BLANK()))', '1'),
    ('CALCULATE(CALCULATE(CALCULATE(SUM(Facts[Sales]),Facts[Quantity]<>3,ALLEXCEPT(Facts,Facts[Region]),KEEPFILTERS(NOT(Facts[Quantity]==0))),ISBLANK(Facts[Quantity]),Facts[Quantity]=3||Facts[Sales]<20,KEEPFILTERS(Facts[Sales]<20)),Facts[Quantity]>4||Facts[Sales]==10.5,Facts[Region]=="North"||Facts[Sales]=BLANK())', 'BLANK'),
    ('CALCULATE(CALCULATE(CALCULATE(COUNTROWS(VALUES(Facts[Region])),Facts[Note]=="Paid",TREATAS({"North","West"},Facts[Region]),KEEPFILTERS(FILTER(ALL(Facts),Facts[Quantity]==BLANK()))),Facts[Sales]<10.5&&Facts[Quantity]<>2,KEEPFILTERS(NOT(Facts[Sales]=0)),Facts[Region]=="West"),Facts[Quantity] IN {BLANK(),3},Facts[Quantity] IN {3,BLANK()},KEEPFILTERS(FILTER(Facts,ISBLANK(Facts[Region]))))', 'BLANK'),
    ('CALCULATE(CALCULATE(CALCULATE(SUM(Facts[Sales]),Facts[Note]==BLANK(),ALLEXCEPT(Facts,Facts[Quantity])),TREATAS({10.5,20},Facts[Sales]),KEEPFILTERS(NOT(Facts[Sales]==0))),KEEPFILTERS(FILTER(ALL(Facts),Facts[Quantity] IN {3,4})),VALUES(Facts[Note]))', '20'),
    ('CALCULATE(CALCULATE(ISFILTERED(Facts[Region]),ALLSELECTED(),NOT(Facts[Region]="East")),TREATAS({"East","West"},Facts[Region]))', 'True'),
    ('CALCULATE(CALCULATE(CALCULATE(COUNTROWS(FILTERS(Facts[Sales])),ALLSELECTED(),Facts[Quantity]=2),FILTER(Facts,Facts[Region]<>"East")),ALLSELECTED())', '3'),
    ('CALCULATE(CALCULATE(COUNTROWS(FILTERS(Facts[Sales])),KEEPFILTERS(Facts[Note]="Paid"),ALLSELECTED()),FILTER(Facts,ISBLANK(Facts[Quantity])))', 'BLANK'),
    ('CALCULATE(CALCULATE(COUNTROWS(VALUES(Facts[Sales])),ALLSELECTED(Facts[Sales]),NOT(Facts[Quantity]==BLANK())),KEEPFILTERS(FILTER(Facts,Facts[Sales]==10.5)))', '1'),
)


class CalculateFilter141Test(unittest.TestCase):
    def test_power_bi_answers(self):
        for expression, expected in CASES:
            with self.subTest(expression=expression):
                local = dax.local(expression)
                self.assertFalse(local.startswith("LOCAL-"), f"refused or crashed: {local}")
                self.assertTrue(dax.same(expected, local), f"Power BI {expected}, local {local}")

    def test_shared_table_filter_columns(self):
        for expression, expected in SHAPE_CASES:
            with self.subTest(expression=expression):
                local = dax.local(expression)
                self.assertFalse(local.startswith("LOCAL-"), f"refused or crashed: {local}")
                self.assertTrue(dax.same(expected, local), f"Power BI {expected}, local {local}")


if __name__ == "__main__":
    unittest.main()
