"""Task 24 (topn-ties-14): row order of TOPN when sort values tie.

Values measured live in Power BI Desktop (tools/parity/task24_topn_ties_spec.json).
"""
from __future__ import annotations

import unittest

from tools import dax_oracle_diff as dax
from tools.parity_check import status


class TopnNoTiesTest(unittest.TestCase):
    """TOPN over distinct values (Facts[Quantity]) follows the binary heap array order."""

    ROWS = [
        ('CONCATENATEX(TOPN(1,Facts,Facts[Quantity]),Facts[Sales],"|")', "2.5"),
        ('CONCATENATEX(TOPN(1,Facts,Facts[Quantity],ASC),Facts[Sales],"|")', "0"),
        ('CONCATENATEX(TOPN(2,Facts,Facts[Quantity]),Facts[Sales],"|")', "|2.5"),
        ('CONCATENATEX(TOPN(2,Facts,Facts[Quantity],ASC),Facts[Sales],"|")', "-1.5|0"),
        ('CONCATENATEX(TOPN(3,Facts,Facts[Quantity]),Facts[Sales],"|")', "20|2.5|"),
        ('CONCATENATEX(TOPN(3,Facts,Facts[Quantity],ASC),Facts[Sales],"|")', "10.5|0|-1.5"),
        ('CONCATENATEX(TOPN(4,Facts,Facts[Quantity]),Facts[Sales],"|")', "10.5|20|2.5|"),
        ('CONCATENATEX(TOPN(4,Facts,Facts[Quantity],ASC),Facts[Sales],"|")', "20|10.5|-1.5|0"),
    ]

    def test_measured_rows_match_power_bi(self) -> None:
        wrong = [(expr, want) for expr, want in self.ROWS if status(want, dax.local(expr)) not in {"match", "gap-reject"}]
        self.assertEqual([], wrong)


class TopnAllTiesTest(unittest.TestCase):
    """When all rows tie (Facts[Sales]>50 or constant 1), TOPN retains the whole table in walk order."""

    ROWS = [
        ('CONCATENATEX(TOPN(1,Facts,1),Facts[Sales],"|")', "|-1.5|0|2.5|10.5|20"),
        ('CONCATENATEX(TOPN(1,Facts,1),Facts[Sales]&Facts[Region],"|")', "10.5East|20West|-1.5East|North|0West|2.5East"),
        ('CONCATENATEX(TOPN(2,Facts,1),Facts[Sales],"|")', "|-1.5|0|2.5|10.5|20"),
        ('CONCATENATEX(TOPN(3,Facts,1),Facts[Sales],"|")', "|-1.5|0|2.5|10.5|20"),
        ('CONCATENATEX(TOPN(4,Facts,1),Facts[Sales],"|")', "|-1.5|0|2.5|10.5|20"),
        ('CONCATENATEX(TOPN(1,Facts,Facts[Sales]>50),Facts[Sales],"|")', "|-1.5|0|2.5|10.5|20"),
        ('CONCATENATEX(TOPN(2,Facts,Facts[Sales]>50),Facts[Sales],"|")', "|-1.5|0|2.5|10.5|20"),
        ('CONCATENATEX(TOPN(3,Facts,Facts[Sales]>50),Facts[Sales],"|")', "|-1.5|0|2.5|10.5|20"),
        ('CONCATENATEX(TOPN(4,Facts,Facts[Sales]>50),Facts[Sales],"|")', "|-1.5|0|2.5|10.5|20"),
    ]

    def test_measured_rows_match_power_bi(self) -> None:
        wrong = [(expr, want) for expr, want in self.ROWS if status(want, dax.local(expr)) not in {"match", "gap-reject"}]
        self.assertEqual([], wrong)


class TopnCutoffTiesTest(unittest.TestCase):
    """Ties across the cut-off: heap array with appended tied rows in arrival order."""

    ROWS = [
        ('CONCATENATEX(TOPN(1,Facts,Facts[Region]),Facts[Sales],"|")', "20|0"),
        ('CONCATENATEX(TOPN(1,Facts,Facts[Region],ASC),Facts[Sales],"|")', "10.5|-1.5|2.5"),
        ('CONCATENATEX(TOPN(2,Facts,Facts[Region]),Facts[Sales],"|")', "0|20"),
        ('CONCATENATEX(TOPN(2,Facts,Facts[Region],ASC),Facts[Sales],"|")', "-1.5|10.5|2.5"),
        ('CONCATENATEX(TOPN(3,Facts,Facts[Region]),Facts[Sales],"|")', "|20|0"),
        ('CONCATENATEX(TOPN(3,Facts,Facts[Region],ASC),Facts[Sales],"|")', "2.5|10.5|-1.5"),
        ('CONCATENATEX(TOPN(4,Facts,Facts[Region],ASC),Facts[Sales],"|")', "|2.5|-1.5|10.5"),
        ('CONCATENATEX(TOPN(1,Facts,INT(Facts[Sales]/100)),Facts[Sales],"|")', "0|2.5|10.5|20"),
        ('CONCATENATEX(TOPN(2,Facts,INT(Facts[Sales]/100)),Facts[Sales],"|")', "2.5|0|10.5|20"),
        ('CONCATENATEX(TOPN(3,Facts,INT(Facts[Sales]/100)),Facts[Sales],"|")', "10.5|2.5|0|20"),
        ('CONCATENATEX(TOPN(4,Facts,INT(Facts[Sales]/100)),Facts[Sales],"|")', "20|10.5|0|2.5"),
        ('CONCATENATEX(TOPN(1,Facts,INT(Facts[Sales]/100)),Facts[Sales]&Facts[Region],"|")', "10.5East|20West|0West|2.5East"),
        ('CONCATENATEX(TOPN(2,Facts,INT(Facts[Sales]/100)),Facts[Sales]&Facts[Region],"|")', "10.5East|20West|0West|2.5East"),
        ('CONCATENATEX(TOPN(3,Facts,INT(Facts[Sales]/100)),Facts[Sales]&Facts[Region],"|")', "0West|20West|10.5East|2.5East"),
        ('CONCATENATEX(TOPN(4,Facts,INT(Facts[Sales]/100)),Facts[Sales]&Facts[Region],"|")', "2.5East|0West|10.5East|20West"),
    ]

    def test_measured_rows_match_power_bi(self) -> None:
        wrong = [(expr, want) for expr, want in self.ROWS if status(want, dax.local(expr)) not in {"match", "gap-reject"}]
        self.assertEqual([], wrong)


class TopnTiesKeepEveryRowTest(unittest.TestCase):
    """Ties at the cut-off that keep every row stay in the heap (no refusal): all six rows come back."""

    ROWS = [
        'CONCATENATEX(TOPN(4,Facts,Facts[Region]),Facts[Sales],"|")',
        'CONCATENATEX(TOPN(4,Facts,Facts[Region],DESC),Facts[Sales]&Facts[Region],"|")',
        'CONCATENATEX(TOPN(3,Facts,INT(Facts[Sales]/100),ASC),Facts[Sales],"|")',
        'CONCATENATEX(TOPN(4,Facts,INT(Facts[Sales]/100),ASC),Facts[Sales]&Facts[Region],"|")',
    ]

    def test_every_row_is_kept(self) -> None:
        for expr in self.ROWS:
            res = str(dax.local(expr))
            self.assertFalse(res.startswith("LOCAL-REJECT:"), f"Unexpected refusal for {expr}")
            self.assertEqual(6, len(res.split("|")), f"{expr} gave {res}")


class TopnTieHeapOrderTest(unittest.TestCase):
    """Heap array order with ties kept in the heap (measured on Facts[Quantity]>2 and friends)."""

    ROWS = [
        ('CONCATENATEX(TOPN(2,Facts,Facts[Quantity]>2),Facts[Quantity],"|")', "3|4|5"),
        ('CONCATENATEX(TOPN(2,Facts,Facts[Sales]>0,ASC),Facts[Quantity],"|")', "1|4|0"),
        ('CONCATENATEX(TOPN(3,Facts,Facts[Quantity]>2),Facts[Quantity],"|")', "3|5|4"),
        ('CONCATENATEX(TOPN(2,ALL(Facts),Facts[Quantity]>2),Facts[Quantity],"|")', "3|4|5"),
        ('CONCATENATEX(TOPN(4,Facts,MOD(Facts[Quantity],3),DESC,Facts[Region]="East",ASC),Facts[Quantity],"|")', "1|4|5|2"),
    ]

    def test_measured_rows_match_power_bi(self) -> None:
        wrong = [(expr, want) for expr, want in self.ROWS if status(want, dax.local(expr)) not in {"match", "gap-reject"}]
        self.assertEqual([], wrong)


if __name__ == "__main__":
    unittest.main()
