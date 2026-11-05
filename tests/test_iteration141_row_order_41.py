"""Iteration 141: Task 51 row-order-41 (MAXX / MINX over a Variant with NaN beside other numbers, and CONCATENATEX walks).

Covers:
- MAXX / MINX over a stored table (Facts) whose body is a Variant with NaN beside numbers: the running extreme keeps the value it
  visits first (NaN > x and x > NaN are both false), so the answer is NaN when the dictionary walk of the body's columns visits a
  NaN first, and otherwise the extreme of the numbers.
- CONCATENATEX without an ORDER BY over TOPN of a stored table, with a constant IF body (a Variant), walks the kept rows in the
  dictionary order of the columns read.
- Derived tables (ADDCOLUMNS, SUMMARIZE, ALL of columns) and fractional columns beside another column keep refusing.

Expected values are the live Power BI answers saved in tools/parity/task51_row_order_spec.json (copied here, not loaded).
"""
from __future__ import annotations

import unittest

from tools import dax_oracle_diff as dax
from tools.parity_check import status


# (expression, Power BI answer) pairs measured in Power BI Desktop for the shapes this iteration models
MODELLED = [
    ('MAXX(Facts,IF.EAGER(TRUE(),-Facts[Quantity]/0,"a"))', "NaN"),
    ('MINX(Facts,IF.EAGER(FALSE(),"5",Facts[Quantity]/0))', "NaN"),
    ('MINX(Facts,IF(TRUE(),-Facts[Quantity]/0,Facts[Region]))', "NaN"),
    ('MAXX(Facts,IF(TRUE(),-Facts[Quantity]/0,"a"))', "NaN"),
    ('MINX(Facts,IF.EAGER(TRUE(),-Facts[Quantity]/0,"5"))', "NaN"),
    ('MAXX(Facts,IF(Facts[Quantity]>2,Facts[Region],Facts[Quantity]/0))', "Infinity"),
    ('CONCATENATEX(TOPN(2,Facts,Facts[Quantity]),IF.EAGER("",CURRENCY(3),Facts[Note]),"|")', "Late|"),
    ('CONCATENATEX(TOPN(2,Facts,Facts[Quantity]),IF.EAGER(COUNTROWS(Facts)>3,"a",-Facts[Quantity]),"|")', "a|a"),
    ('CONCATENATEX(TOPN(2,Facts,Facts[Quantity]),IF(MAX(Facts[Quantity])>3,-Facts[Quantity],UPPER(Facts[Region])),"|")', "-4|-5"),
    ('CONCATENATEX(TOPN(2,Facts,Facts[Quantity]),IF.EAGER(Facts[Region]="East",Facts[Region],"5"),"|")', "5|East"),
    ('CONCATENATEX(TOPN(2,Facts,Facts[Quantity]),VAR x=Facts[Region] RETURN IF(1=1,x,Facts[Note]),"|")', "North|East"),
    ('CONCATENATEX(TOPN(2,Facts,Facts[Quantity]),IF(1/0,NOT(TRUE()),Facts[Sales]),"|")', "FALSE|FALSE"),
]

# shapes whose walk is not modelled: each must keep refusing (MeasureError, shown as LOCAL-REJECT)
STAYS_REFUSED = [
    'MAXX(ADDCOLUMNS(Facts,"z",1),IF(Facts[Quantity]>2,0/0,2))',
    'MINX(ADDCOLUMNS(Facts,"z",1),IF(Facts[Quantity]>2,0/0,2))',
    'MAXX(SUMMARIZE(Facts,Facts[Region],Facts[Quantity]),IF(1,Facts[Quantity]/0,"a"))',
    'MINX(ALL(Facts[Region],Facts[Quantity]),IF(1,Facts[Quantity]/0,"a"))',
    'MINX(Facts,IF.EAGER(Facts[Quantity]>2,Facts[Region],Facts[Sales]/Facts[Quantity]))',
]


class RowOrderFortyOneTests(unittest.TestCase):
    def test_modelled_shapes_match_power_bi(self) -> None:
        for expression, expected in MODELLED:
            with self.subTest(expression=expression):
                ours = dax.local(expression)
                self.assertEqual(status(expected, ours), "match", f"{expression!r} gave {ours!r}")

    def test_unmodelled_shapes_keep_refusing(self) -> None:
        for expression in STAYS_REFUSED:
            with self.subTest(expression=expression):
                ours = dax.local(expression)
                self.assertTrue(str(ours).startswith("LOCAL-REJECT"), f"{expression!r} should refuse, gave {ours!r}")


if __name__ == "__main__":
    unittest.main()
