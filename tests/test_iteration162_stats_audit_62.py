"""Iteration 162: Task 72 statistical iterator audit (stats-audit-62).

Covers (live Power BI evidence in tools/parity/task72_stats_audit_spec.json and the 1,500-shape audit grid t72a):
- Part A: GEOMEANX / GEOMEAN of n values whose product is negative returns NaN when n is even and the real (negative) n-th root when n is odd.
  The rule is computed from the values (count and sign), not keyed on the expression. The three spec rows are NaN in Power BI.
- The odd-count negative case (values -0.5, -1.5, -2.5 under Note="Paid") already matched Power BI (-1.2331) and must keep matching.
"""
from __future__ import annotations

import unittest

from tools import dax_oracle_diff as dax


class TestIteration162StatsAudit62(unittest.TestCase):
    def assertLocal(self, expr: str, expected: str) -> None:
        with self.subTest(expr=expr):
            self.assertEqual(str(dax.local(expr)), expected)

    def test_part_a_even_count_negative_product_is_nan(self) -> None:
        # Power BI: values 0.5 and -2.5 (product negative, n = 2) give NaN
        self.assertLocal(
            'CALCULATE(GEOMEANX(ALLSELECTED(Facts),Facts[Quantity]-2.5),Facts[Region]="West")',
            "NaN",
        )
        self.assertLocal(
            'CALCULATE(GEOMEANX(TOPN(4,Facts,Facts[Quantity]),Facts[Quantity]-2.5),Facts[Region]="West")',
            "NaN",
        )
        self.assertLocal("GEOMEANX(ALLSELECTED(Facts),Facts[Quantity]-2.5)", "NaN")

    def test_part_a_odd_count_negative_product_keeps_signed_root(self) -> None:
        # Power BI: values -0.5, -1.5, -2.5 (product negative, n = 3) give -1.2331
        expr = 'CALCULATE(GEOMEANX(ALLSELECTED(Facts),Facts[Quantity]-2.5),Facts[Note]="Paid")'
        result = str(dax.local(expr))
        self.assertNotIn("LOCAL-REJECT", result)
        self.assertEqual(round(float(result), 4), -1.2331)


if __name__ == "__main__":
    unittest.main()
