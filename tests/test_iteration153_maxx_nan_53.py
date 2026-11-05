"""Iteration 153: Task 63 maxx-nan-53.

A running MAXX / MINX keeps the first value it visits (NaN > x and x > NaN are both false), so a NaN body is NaN when the walk meets
a NaN first and the extreme of the numbers otherwise.  Over a stored table the walk is the dictionary order of the body's columns
(a folded IF keeps only the branch it reads; IF(1=0,..) folds like IF(FALSE(),..)).  A double beside ONE other column keeps the dictionary
order for an IF / IF.EAGER body over Facts or ALL(Facts) (held-out Power BI grid: exact on every row of those classes).  SWITCH bodies with a
double beside another column, three columns, FILTER, INTERSECT / EXCEPT and UNION were not exact on every measured row: they stay refused.
The Power BI answers below are recorded values of tools/parity/task63_maxx_nan_spec.json and the held-out grid.
"""
import unittest

from tools import dax_oracle_diff as dax
from tools.parity_check import status

REFUSAL = "over a Variant with NaN beside other numbers depends on the engine's row order"

# stored table: IF / IF.EAGER walked in dictionary order (Power BI answers on the Windows VM)
STORED = (
    ("MAXX(Facts,IF(FALSE(),TRUE(),Facts[Sales]/Facts[Quantity]))", "NaN"),
    ("MINX(Facts,IF.EAGER(FALSE(),Facts[Region],Facts[Quantity]/Facts[Sales]))", "NaN"),
    ("MINX(Facts,IF.EAGER(Facts[Region]=\"East\",\"a\",Facts[Sales]*0/Facts[Sales]))", "NaN"),
    ("MINX(Facts,SWITCH(TRUE(),FALSE(),Facts[Note],Facts[Quantity]/Facts[Quantity]))", "NaN"),
    ("MINX(Facts,IF(1=0,Facts[Region],0/Facts[Quantity]))", "NaN"),
    ("MINX(ALL(Facts),IF(1=0,Facts[Note],0/Facts[Quantity]))", "NaN"),
    ("MAXX(Facts,IF.EAGER(1=0,\"x\"&Facts[Quantity],Facts[Sales]*0/Facts[Sales]))", "0"),
)

# refused: no single walk rule was exact on every measured row of these classes
REFUSED = (
    "MINX(Facts,IF.EAGER(Facts[Quantity]>2,Facts[Region],Facts[Sales]/Facts[Quantity]))",  # three columns
    "MAXX(Facts,SWITCH(TRUE(),Facts[Sales]>0,Facts[Note],-Facts[Sales]/Facts[Quantity]))",  # three columns
    "MAXX(Facts,SWITCH(TRUE(),FALSE(),Facts[Note],(Facts[Sales]-Facts[Sales])/Facts[Quantity]))",  # SWITCH with a double beside another column
    "MINX(INTERSECT(Facts,Facts),IF(1,Facts[Quantity]/0,\"a\"))",  # INTERSECT / EXCEPT
    "MINX(EXCEPT(Facts,FILTER(Facts,FALSE())),Facts[Sales]/0)",
    "MAXX(UNION(Facts,Facts),IF(Facts[Quantity]>2,0/0,2))",
)


class MaxxNanIteration153Tests(unittest.TestCase):
    def test_stored_table_walk_answers_match_power_bi(self):
        for expression, powerbi in STORED:
            with self.subTest(expression=expression):
                self.assertEqual(status(powerbi, dax.local(expression)), "match", dax.local(expression))

    def test_unmeasured_classes_stay_refused(self):
        for expression in REFUSED:
            with self.subTest(expression=expression):
                self.assertTrue(dax.local(expression).startswith("LOCAL-REJECT:"), dax.local(expression))
                self.assertIn(REFUSAL, dax.local(expression))


if __name__ == "__main__":
    unittest.main()
