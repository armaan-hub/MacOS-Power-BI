"""Iteration 165: Task 75 filter audit (filter-audit-65).

Covers the live Power BI evidence in tools/parity/task75_filter_audit_spec.json (19 rows, 1,500-shape grid t75a):
- Part A: ALLNOBLANKROW(T[c]) among CALCULATE's filter arguments is a table filter in Power BI. ISFILTERED of c and ISCROSSFILTERED of
  any column of T are True under it, and it still clears the values of c as before.
- Part B: FILTERS(T[c]) under a FILTER(T, ...) table filter counts only the values of c in the rows that filter leaves.
  The rule is limited to tables with no column filter (a column filter such as TREATAS is not combined yet).
"""
from __future__ import annotations

import unittest

from tools import dax_oracle_diff as dax


def _answer(expression: str) -> str:
    return dax.local(expression)


class TestIteration165FilterAudit65(unittest.TestCase):
    # Part A: the table filter is a flag for ISFILTERED and ISCROSSFILTERED
    def test_part_a_single_allnoblanknow_column_is_a_filter(self) -> None:
        self.assertEqual(_answer("CALCULATE(ISFILTERED(Facts[Region]),ALLNOBLANKROW(Facts[Region]))"), "True")
        self.assertEqual(_answer("CALCULATE(ISCROSSFILTERED(Facts[Quantity]),ALLNOBLANKROW(Facts[Note]))"), "True")

    def test_part_a_nested_and_multi_argument_forms(self) -> None:
        self.assertEqual(
            _answer("CALCULATE(CALCULATE(ISFILTERED(Facts[Region]),ALLNOBLANKROW(Facts[Region])),ALLNOBLANKROW(Facts[Sales]))"),
            "True",
        )
        self.assertEqual(
            _answer("CALCULATE(ISCROSSFILTERED(Facts[Quantity]),ALLNOBLANKROW(Facts[Quantity]),ALLNOBLANKROW(Facts[Note]))"),
            "True",
        )
        self.assertEqual(
            _answer("CALCULATE(ISCROSSFILTERED(Facts[Quantity]),ALLNOBLANKROW(Facts[Note]),REMOVEFILTERS())"),
            "True",
        )
        self.assertEqual(
            _answer("CALCULATE(ISCROSSFILTERED(Facts[Quantity]),ALL(Facts[Region]),ALLNOBLANKROW(Facts[Quantity]))"),
            "True",
        )

    # Part B: FILTERS counts the rows a FILTER table filter leaves
    def test_part_b_filters_counts_rows_left_by_filter_table(self) -> None:
        self.assertEqual(
            _answer(
                'CALCULATE(CALCULATE(COUNTROWS(FILTERS(Facts[Region])),ALL(Facts[Note]),FILTER(Facts,Facts[Region]="East")),'
                'KEEPFILTERS(Facts[Region]="East"))'
            ),
            "1",
        )


if __name__ == "__main__":
    unittest.main()
