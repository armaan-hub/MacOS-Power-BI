"""Iteration 160: Task 70 RANKX audit (rankx-audit-60).

Covers (live Power BI evidence in tools/parity/task70_rankx_audit_spec.json and the 1,500-shape audit grid t70a):
- Part A: a DENSE rank counts a BLANK and a 0 as one value (the rank of a row below both is one step lower than before).
- Part B: an iterator over the walked table whose body is a RANKX over ALL / ALLSELECTED / VALUES / the table of that table walks the rows by the
  columns the RANKX expression reads (blank first, then first-seen text; numbers ascending), not in storage order.
- Part C: CONCATENATEX whose ORDER BY keys tie on every row, over a walk of a fractional column beside another column, is refused (the walk is not
  measured for that shape); an ORDER BY that breaks the ties keeps its answer.
"""
from __future__ import annotations

import unittest

from tools import dax_oracle_diff as dax


class TestIteration160RankxAudit60(unittest.TestCase):
    def test_part_a_dense_rank_ties_blank_with_zero(self) -> None:
        # Power BI: 2,1,5,4,4,3 (the blank sum and the 0 sum share rank 4; -1.5 is rank 5)
        self.assertEqual(
            str(dax.local('CONCATENATEX(Facts,RANKX(ALLSELECTED(Facts),CALCULATE(SUM(Facts[Sales])),,DESC,DENSE),",")')),
            "2,1,5,4,4,3",
        )

    def test_part_a_non_dense_rank_is_unchanged(self) -> None:
        # Power BI: 4,6,4,3,2,1 (SKIP ranks, BLANK and 0 already tie)
        self.assertEqual(str(dax.local('CONCATENATEX(Facts,RANKX(ALLSELECTED(Facts),Facts[Sales]),",")')), "4,6,4,3,2,1")

    def test_part_b_walk_follows_the_columns_the_rankx_body_reads(self) -> None:
        cases = {
            'CONCATENATEX(Facts,RANKX(ALLSELECTED(Facts),Facts[Note],,DESC),",")': "5,5,1,1,1,4",
            'CALCULATE(CONCATENATEX(Facts,RANKX(ALL(Facts),Facts[Note]),","),Facts[Sales]>0)': "5,5,1",
            'CONCATENATEX(Facts,RANKX(VALUES(Facts[Quantity]),Facts[Quantity]),",")': "6,5,4,3,2,1",
            'CONCATENATEX(Facts,RANKX(Facts,Facts[Quantity]),",")': "6,5,4,3,2,1",
        }
        for expr, expected in cases.items():
            with self.subTest(expr=expr):
                self.assertEqual(str(dax.local(expr)), expected)

    def test_part_c_tied_order_by_over_unmodelled_walk_is_refused(self) -> None:
        expr = 'CALCULATE(CONCATENATEX(Facts,Facts[Sales],",",Facts[Note],DESC,Facts[Note],DESC),Facts[Note]="Paid")'
        actual = str(dax.local(expr))
        self.assertTrue(actual.startswith("LOCAL-REJECT:"), f"Expected refusal, got: {actual}")

    def test_part_c_order_by_that_breaks_the_tie_keeps_its_answer(self) -> None:
        # Power BI: 10.5,0,-1.5 (Sales DESC breaks the tie of the Note keys)
        self.assertEqual(
            str(dax.local('CALCULATE(CONCATENATEX(Facts,Facts[Sales],",",Facts[Note],DESC,Facts[Sales],DESC),Facts[Note]="Paid")')),
            "10.5,0,-1.5",
        )


if __name__ == "__main__":
    unittest.main()
