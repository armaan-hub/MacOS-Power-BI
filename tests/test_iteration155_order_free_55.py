"""Iteration 155: Task 65 order-free-55 (CONCATENATEX without an ORDER BY).

Without an ORDER BY, CONCATENATEX walks the rows in an order the local engine does not reproduce, so it refuses.  Two cases do not
depend on that order and are answered:
  1. every row gives the same text (the order cannot show);
  2. the body folds to the branch a condition that reads no row takes, IF(TRUE(), x, y) being x, COALESCE(BLANK(), x) being x; the
     walk is then the one that branch has on its own over the table, and the tables whose walk is not measured stay refused.
A date or time taken beside a number is typed as a number by Power BI, so such an IF is not folded.
The Power BI answers below are the recorded values of tools/parity/task65_order_free_spec.json.
"""
import unittest

from tools import dax_oracle_diff as dax

# every row gives the same text: the order cannot show
SAME_TEXT = (
    ("CONCATENATEX(CALCULATETABLE(Facts,Facts[Region]=\"East\"),MAX(\"a\",\"b\"))", "bbb"),
    ("CONCATENATEX(Facts,MIN(\"a\",Facts[Region]))", "aaaaaa"),
    ("CONCATENATEX(Facts,MAX(\"a\",\"b\"))", "bbbbbb"),
    ("CONCATENATEX(CALCULATETABLE(Facts,Facts[Region]=\"West\"),MIN(\"a\",Facts[Region]))", "aa"),
    ("CONCATENATEX({1},MAX(1E15,1))", "1E+15"),
    ("CONCATENATEX({1,2},MAX(1E15,1),\",\")", "1E+15,1E+15"),
)

# a constant condition folds to the branch it takes; the folded walk is the plain walk of its column
FOLDED = (
    ("CONCATENATEX(ALL(Facts),IF(TRUE(),Facts[Region],1))", "EastEastEastWestWestNorth"),
    ("CONCATENATEX(ALL(Facts[Region]),IF(TRUE(),Facts[Region],1))", "EastWestNorth"),
    ("CONCATENATEX(VALUES(Facts[Region]),IF(TRUE(),Facts[Region],1))", "EastWestNorth"),
    ("CONCATENATEX(FILTER(Facts,Facts[Quantity]>2),IF(TRUE(),Facts[Region],1))", "EastWestNorth"),
)

# still refused: the walk is not reproduced, or the body is typed differently by Power BI
REFUSED = (
    "CONCATENATEX(SUMMARIZECOLUMNS(Facts[Region]),IF(TRUE(),Facts[Region],1))",  # SUMMARIZECOLUMNS is an unmeasured walk
    "CONCATENATEX(UNION(Facts,Facts),IF(TRUE(),Facts[Region],1))",  # UNION is an unmeasured walk
    "CONCATENATEX(Facts,COALESCE(BLANK(),DATE(2020,1,1)+Facts[Quantity],Facts[Region]),\"|\")",  # COALESCE with more arguments is not folded
    "CONCATENATEX(Facts,IF(TRUE(),DATE(2020,1,1),Facts[Sales]))",  # a date beside a number is typed as a number: not answered without the walk
)

# fresh Power BI grid: under a CALCULATE filter TOPN and ALLSELECTED are walked in an order the plain walk does not give, so the folds are refused
FILTERED_REFUSED = (
    "CALCULATE(CONCATENATEX(TOPN(3,Facts,Facts[Sales]),IF(TRUE(),Facts[Region],1)),Facts[Quantity]<>3)",  # Power BI: WestEastEast
    "CALCULATE(CONCATENATEX(TOPN(3,Facts,Facts[Sales]),IF(1=1,Facts[Sales],2.5)),Facts[Quantity]<>3)",  # Power BI: 10.52.50
    "CALCULATE(CONCATENATEX(TOPN(3,Facts,Facts[Sales]),COALESCE(BLANK(),Facts[Region]),\"|\"),Facts[Quantity]<>3)",  # Power BI: West|East|East
    "CALCULATE(CONCATENATEX(ALLSELECTED(Facts),IF(TRUE(),Facts[Region],\"a\"),\",\"),Facts[Quantity]<>3)",  # Power BI: East,East,East,West,North
)

# Task 65 Part C, held-out Power BI grid (1266 probes): under an outer CALCULATE filter a TOPN is walked in the source order it has without the
# filter and then through the heap (60 of these were wrong on main), and the visible rows of ALLSELECTED(table) are walked by the dictionary of the
# WHOLE column, not of the rows the filter leaves (4 were wrong on main)
FILTERED_WALKS = (
    ("CALCULATE(CONCATENATEX(TOPN(3,ALL(Facts),Facts[Quantity]),Facts[Region],\"|\"),Facts[Note]=\"Paid\")", "West|North|East"),
    ("CALCULATE(CONCATENATEX(TOPN(4,Facts,Facts[Sales],ASC),Facts[Quantity],\"|\"),Facts[Sales]>0)", "2|3|5"),
    ("CALCULATE(CONCATENATEX(TOPN(2,Facts,Facts[Quantity]),Facts[Region],\"|\"),Facts[Quantity]>=2)", "North|East"),
    ("CALCULATE(CONCATENATEX(ALLSELECTED(Facts),Facts[Region],\",\"),Facts[Quantity]<>3)", "East,East,East,West,North"),
    ("CALCULATE(CONCATENATEX(ALLSELECTED(Facts),Facts[Note]),Facts[Region]<>\"East\")", "PaidLate"),
    ("CALCULATE(CONCATENATEX(ALLSELECTED(Facts),Facts[Note]&\"\",\"|\"),Facts[Region]<>\"East\")", "|Paid|Late"),
)

# ALLSELECTED(table) under an outer filter read through several columns was not measured: refused
FILTERED_ALLSELECTED_REFUSED = (
    "CALCULATE(CONCATENATEX(ALLSELECTED(Facts),Facts[Region]&Facts[Note],\",\"),Facts[Quantity]<>3)",
)


class OrderFreeConcatenatex(unittest.TestCase):
    def test_topn_and_allselected_walks_under_a_filter_match_powerbi(self) -> None:
        for expression, powerbi in FILTERED_WALKS:
            with self.subTest(expression=expression):
                self.assertEqual(dax.local(expression), powerbi)

    def test_allselected_over_several_columns_under_a_filter_is_refused(self) -> None:
        for expression in FILTERED_ALLSELECTED_REFUSED:
            with self.subTest(expression=expression):
                self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"), dax.local(expression)[:120])

    def test_same_text_on_every_row_is_answered(self) -> None:
        for expression, powerbi in SAME_TEXT:
            with self.subTest(expression=expression):
                self.assertEqual(dax.local(expression), powerbi)

    def test_constant_condition_folds_to_its_branch(self) -> None:
        for expression, powerbi in FOLDED:
            with self.subTest(expression=expression):
                self.assertEqual(dax.local(expression), powerbi)

    def test_order_dependent_shapes_stay_refused(self) -> None:
        for expression in REFUSED:
            with self.subTest(expression=expression):
                self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"), dax.local(expression)[:120])

    def test_folds_over_topn_and_allselected_are_refused_under_a_filter(self) -> None:
        for expression in FILTERED_REFUSED:
            with self.subTest(expression=expression):
                self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"), dax.local(expression)[:120])


if __name__ == "__main__":
    unittest.main()
