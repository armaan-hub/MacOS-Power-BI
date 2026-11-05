"""Iteration 149: Task 59 swi-ties-49.

SUBSTITUTEWITHINDEX over tied order values is answered only when every tie order gives the same result (the whole measure
is re-run under each permutation of the tie groups). The Power BI answers below are the recorded values of the spec
tools/parity/task59_swi_ties_spec.json; the order-dependent listing stays refused.
"""
import itertools
import unittest

from analytics_studio import dax_swi_ties
from analytics_studio import measures
from tools import dax_oracle_diff as dax

ORDER_REFUSAL = (
    "The row order of this index table is not modelled in the local engine, so SUBSTITUTEWITHINDEX refuses tied order values over it."
)

# (expression, Power BI answer) pairs measured on the Windows VM for Task 59
ANSWERED = (
    ('SUMX(SUBSTITUTEWITHINDEX(VALUES(Facts[Quantity]),"i",FILTER(ALL(Facts),Facts[Quantity]>1),Facts[Region],1),[i]*[i])', "14"),
    ('MAXX(SUBSTITUTEWITHINDEX(ADDCOLUMNS(VALUES(Facts[Quantity]),"d",Facts[Quantity]*2),"i",FILTER(ALL(Facts),Facts[Quantity]>1),Facts[Region],1),[i])', "3"),
    ('MAXX(SUBSTITUTEWITHINDEX(VALUES(Facts[Quantity]),"i",Facts,IF(Facts[Region]="East",1,2),ASC),[i])', "5"),
    ('CONCATENATEX(SUBSTITUTEWITHINDEX(Facts,"i",Facts,Facts[Region],ASC),[i],"|",[i])', "0|1|2|3|4|5"),
    ('CONCATENATEX(SUBSTITUTEWITHINDEX(SUMMARIZE(Facts,Facts[Region],Facts[Note],"s",SUM(Facts[Quantity])),"i",FILTER(ALL(Facts),Facts[Quantity]>1),0),[i],"|",[i])', "0|1|2|3"),
)

# Part B listing whose Power BI answer depends on the tie order: it must stay refused
ORDER_DEPENDENT = (
    'CONCATENATEX(SUBSTITUTEWITHINDEX(FILTER(VALUES(Facts[Region]),Facts[Region]<>"West"),"i",TOPN(2,VALUES(Facts[Region]),Facts[Region]),BLANK()),[i],"|",[i])',
)


class AnsweredSpecRows(unittest.TestCase):
    def test_power_bi_answers_match(self):
        for expression, powerbi in ANSWERED:
            with self.subTest(expression=expression):
                self.assertEqual(dax.local(expression), powerbi)

    def test_order_dependent_listing_stays_refused(self):
        for expression in ORDER_DEPENDENT:
            with self.subTest(expression=expression):
                self.assertEqual(dax.local(expression), "LOCAL-REJECT:" + ORDER_REFUSAL)


class TieOrderDriver(unittest.TestCase):
    def test_no_driver_outside_a_search(self):
        self.assertIsNone(dax_swi_ties.current_driver())

    def test_nth_permutation_enumerates_every_order_once(self):
        for size in range(1, 5):
            expected = list(itertools.permutations(range(size)))
            actual = [tuple(dax_swi_ties._nth_permutation(size, index)) for index in range(len(expected))]
            self.assertEqual(actual, expected)

    def test_disagreeing_tie_orders_refuse(self):
        def run():
            driver = dax_swi_ties.current_driver()
            ranked = [([1], "a"), ([1], "b")]
            ordered = driver.choose(ranked, [(0, 2)], ORDER_REFUSAL)
            return ordered[0][1]  # depends on the tie order, so the runs disagree

        with self.assertRaises(dax_swi_ties.TieRefused):
            dax_swi_ties.run_with_tie_orders(run, lambda first, second: first == second)

    def test_agreeing_tie_orders_answer(self):
        def run():
            driver = dax_swi_ties.current_driver()
            ranked = [([1], "a"), ([1], "b"), ([1], "c")]
            ordered = driver.choose(ranked, [(0, 3)], ORDER_REFUSAL)
            return len(ordered)  # the same for every tie order

        self.assertEqual(dax_swi_ties.run_with_tie_orders(run, lambda first, second: first == second), 3)


if __name__ == "__main__":
    unittest.main()
