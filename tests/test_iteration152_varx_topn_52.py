"""Iteration 152: Task 62 varx-topn-52.

VARX / STDEVX over TOPN(...) with a date body that divides is walked in the TOPN heap order that CONCATENATEX reads (the body's columns
and the TOPN keys are the reads), not the sorted order. The Power BI answers below are the recorded values of the spec
tools/parity/task62_varx_topn_spec.json; the app never reads them.
"""
import unittest

from tools import dax_oracle_diff as dax
from tools.parity_check import status

# (expression, Power BI answer) pairs of the spec that now match
ANSWERED = (
    ('CALCULATE(STDEVX.P(TOPN(3,Facts,Facts[Sales]),(DATE(2024,5,26)+Facts[Quantity])/1.5))', "0.83147952990817"),
    ('CALCULATE(STDEVX.S(TOPN(3,Facts,Facts[Sales]),(DATE(1899,2,15)+Facts[Quantity])/12))', "0.127293769305189"),
    ('CALCULATE(VARX.P(TOPN(3,Facts,Facts[Sales]),DATE(1899,12,31)+(Facts[Sales]+1)/6),Facts[Region]<>"West")', "0.557098765432098"),
    ('CALCULATE(VARX.S(TOPN(3,Facts,Facts[Sales]),(DATE(1899,12,31)+Facts[Sales])/8))', "1.19921875"),
)

# Measured Power BI answer (Task 62 fresh grid): n >= the rows left after the CALCULATE filter, ties on the key; rows walk in dictionary order
FILTER_UNCUT = (
    ('CALCULATE(VARX.S(TOPN(6,FILTER(Facts,Facts[Quantity]>0),Facts[Region],DESC),DATE(1905,9,28)+Facts[Quantity]/7+1),Facts[Region]<>"West")', "0.0680272094905376"),
)

# Power BI: "Unexpected value for ORDER argument in TOPN function" when the argument after a sort expression is a column or expression
BAD_ORDER = (
    'CALCULATE(STDEVX.P(TOPN(2,Facts,Facts[Quantity]*-1,Facts[Quantity],ASC),DATE(1900,6,11)+Facts[Sales]*3/0.4))',
    'CALCULATE(STDEVX.P(TOPN(5,ALL(Facts),Facts[Region],ASC,Facts[Quantity],Facts[Sales],ASC),DATE(1899,12,31)+Facts[Quantity]/9))',
    'COUNTROWS(TOPN(2,Facts,Facts[Quantity],Facts[Sales]))',
    'COUNTROWS(TOPN(2,Facts,Facts[Quantity],1+0))',
)

# order forms Power BI accepts (all in the saved batteries): ASC, DESC, 0, 1, TRUE(), FALSE()
GOOD_ORDER = (
    'COUNTROWS(TOPN(2,Facts,Facts[Quantity],ASC))',
    'COUNTROWS(TOPN(2,Facts,Facts[Quantity],DESC,Facts[Sales],1))',
    'COUNTROWS(TOPN(2,Facts,Facts[Quantity],0))',
    'COUNTROWS(TOPN(2,Facts,Facts[Quantity],TRUE()))',
    'COUNTROWS(TOPN(2,Facts,Facts[Quantity],FALSE()))',
)

# A TOPN whose rows tie on the key (a UNION keeps duplicate rows) over a source whose walk order is not modelled stays refused
TIES_REFUSED = (
    'VARX.P(TOPN(2,UNION(Facts,Facts),Facts[Quantity]),DATE(2020,5,19)+Facts[Quantity]*2/9)',
)


class TopnWalkOrder(unittest.TestCase):
    def test_power_bi_answers_match(self):
        for expression, powerbi in ANSWERED:
            with self.subTest(expression=expression):
                self.assertEqual(status(powerbi, dax.local(expression)), "match")

    def test_uncut_topn_under_filter_matches(self):
        for expression, powerbi in FILTER_UNCUT:
            with self.subTest(expression=expression):
                self.assertEqual(status(powerbi, dax.local(expression)), "match")

    def test_column_in_order_position_is_rejected(self):
        for expression in BAD_ORDER:
            with self.subTest(expression=expression):
                self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"), dax.local(expression))

    def test_valid_orders_still_answer(self):
        for expression in GOOD_ORDER:
            with self.subTest(expression=expression):
                self.assertEqual(dax.local(expression), "2", dax.local(expression))

    def test_tied_topn_over_unmodelled_source_stays_refused(self):
        for expression in TIES_REFUSED:
            with self.subTest(expression=expression):
                self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT"))


if __name__ == "__main__":
    unittest.main()
