"""Iteration 229: Task 140 dax-maxxnan-130.

A running MAXX / MINX over a Variant body with NaN beside numbers keeps the value it visits first, so the answer depends on the walk order.
Power BI evaluates an IF / SWITCH(TRUE(), ...) body branch by branch: the rows that take the first branch are visited before the rows of the
second, the else rows last, each group in the walk order of the source (dictionary order over a stored table, source order over INTERSECT / EXCEPT).
Branches ruled out by a literal condition (FALSE(), 1=0) do not add their columns to the dictionary walk.  A body whose IF / SWITCH sits inside
arithmetic, is nested in a branch or switches on a value is refused.

Every case must be either refused (gap-reject) or exact against the Power BI answer recorded here; a wrong answer fails the test.
The answers are recorded values of the Power BI spec for this task and of the five fresh probes given with it.
"""
import unittest

from tools import dax_oracle_diff as dax
from tools.parity_check import status

CASES = (
    # fresh probes (Power BI answers recorded with the task); each was wrong on main
    ("MAXX(INTERSECT(Facts,Facts),SWITCH(TRUE(),1=0,Facts[Note],Facts[Quantity]=3,0/(Facts[Quantity]-3),Facts[Sales]/0))", "NaN"),
    ("MINX(EXCEPT(Facts,FILTER(Facts,Facts[Region]=\"East\")),SWITCH(TRUE(),Facts[Region]=\"East\",TRUE(),NOT(ISBLANK(Facts[Note])),Facts[Sales]*0/Facts[Sales],Facts[Quantity]/Facts[Sales]))", "NaN"),
    ("MINX(FILTER(Facts,Facts[Sales]<>20),SWITCH(TRUE(),FALSE(),Facts[Region],1=0,(Facts[Quantity]-3)/(Facts[Quantity]-3),Facts[Quantity]/0))", "NaN"),
    ("CALCULATE(MAXX(INTERSECT(Facts,Facts),SWITCH(TRUE(),Facts[Region]=\"East\",DATE(2021,5,5),Facts[Quantity]>=4,0/(Facts[Quantity]-3),0/(Facts[Quantity]-3))),Facts[Quantity]>2)", "44321"),
    ("MINX(FILTER(Facts,Facts[Sales]<>20),SWITCH(TRUE(),Facts[Region]=\"East\",\"a\",Facts[Quantity]>2,0/Facts[Quantity],Facts[Quantity]/0))", "0"),
    # spec rows over the other source kinds
    ("MAXX(EXCEPT(Facts,FILTER(Facts,FALSE())),IF(Facts[Quantity]>2,0/0,2))", "NaN"),
    ("MINX(EXCEPT(Facts,FILTER(Facts,FALSE())),Facts[Sales]/0)", "-Infinity"),
    ("MAXX(UNION(Facts,Facts),Facts[Quantity]/0)", "NaN"),
    ("MINX(UNION(Facts,Facts),IF(Facts[Quantity]>2,0/0,2))", "NaN"),
    ("MAXX(INTERSECT(Facts,Facts),IF(Facts[Quantity]>2,0/0,2))", "NaN"),
    ("MINX(INTERSECT(Facts,Facts),Facts[Sales]/0)", "-Infinity"),
    ("MINX(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),IF(1,Facts[Quantity]/0,\"a\"))", "NaN"),
    ("MAXX(DISTINCT(Facts),IF(1,Facts[Quantity]/0,\"a\"))", "NaN"),
    ("MINX(Facts,IF.EAGER(Facts[Quantity]>2,Facts[Region],Facts[Sales]/Facts[Quantity]))", "-1.5"),
    ("MAXX(Facts,SWITCH(TRUE(),FALSE(),FALSE(),Facts[Quantity]/Facts[Sales]))", "NaN"),
    ("MAXX(FILTER(Facts,TRUE()),SWITCH(TRUE(),1=0,\"z\",Facts[Sales]/Facts[Quantity]))", "NaN"),
    ("CALCULATE(MINX(Facts,IF.EAGER(Facts[Region]=\"East\",FALSE(),Facts[Quantity]/Facts[Sales])),Facts[Region]<>\"North\")", "0.15"),
)


class MaxxNanIteration229Tests(unittest.TestCase):
    def test_every_case_is_exact_or_refused(self):
        for expression, powerbi in CASES:
            with self.subTest(expression=expression):
                self.assertIn(status(powerbi, dax.local(expression)), {"match", "gap-reject"}, dax.local(expression))

    def test_fresh_probes_are_exact(self):
        for expression, powerbi in CASES[:5]:
            with self.subTest(expression=expression):
                self.assertEqual(status(powerbi, dax.local(expression)), "match", dax.local(expression))

    def test_switch_over_bare_stored_table_keeps_its_measured_answer(self):
        self.assertEqual(status("NaN", dax.local("MINX(Facts,SWITCH(TRUE(),FALSE(),Facts[Note],Facts[Quantity]/Facts[Quantity]))")), "match")


if __name__ == "__main__":
    unittest.main()
