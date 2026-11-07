"""Iteration 165: Task 75 filter audit (filter-audit-65).

Covers the live Power BI evidence in tools/parity/task75_filter_audit_spec.json (19 rows, 1,500-shape grid t75a):
- Part A: ALLNOBLANKROW(T[c]) among CALCULATE's filter arguments is a table filter in Power BI. ISFILTERED of c and ISCROSSFILTERED of
  any column of T are True under it, and it still clears the values of c as before.
  ALLNOBLANKROW(T) filters every column of T. The mark survives ALLSELECTED and the clears that do not reach it, and is dropped by
  ALL(T) / REMOVEFILTERS() / ALL(T[c]) of its own column (a table mark keeps ISCROSSFILTERED but loses ISFILTERED for a cleared column).
- Part B: FILTERS(T[c]) is what the filters that reach c directly leave of it. A FILTER(T, ...) table filter reaches every column of T
  through the rows it keeps (also inside a nested CALCULATE and next to a TREATAS on another column); a filter on another column of T
  only cross-filters c and does not count. Grids t75a (1,500), t75b, t75c (300 each) and t75d (136) match Power BI.
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

    def test_part_b_nested_table_filter_next_to_other_column_filters(self) -> None:
        cases = {
            'CALCULATE(CALCULATE(COUNTROWS(FILTERS(Facts[Region])),FILTER(Facts,Facts[Quantity]=BLANK()),ALLSELECTED()),TREATAS({"East","West"},Facts[Region]))': "1",
            'CALCULATE(CALCULATE(COUNTROWS(FILTERS(Facts[Region])),FILTER(Facts,Facts[Region]="East")),TREATAS({2,3},Facts[Quantity]))': "1",
            "CALCULATE(CALCULATE(COUNTROWS(FILTERS(Facts[Region])),FILTER(Facts,Facts[Sales]<>0)),ALLEXCEPT(Facts,Facts[Note]))": "2",
            "CALCULATE(COUNTROWS(FILTERS(Facts[Region])),FILTER(Facts,Facts[Sales]<>0))": "2",
            "CALCULATE(COUNTROWS(FILTERS(Facts[Sales])),FILTER(Facts,Facts[Sales]=BLANK()))": "2",
            "CALCULATE(CALCULATE(COUNTROWS(FILTERS(Facts[Region])),ALLSELECTED()),FILTER(Facts,Facts[Sales]=0))": "2",
            # a filter on another column of the same table does not count for FILTERS of this one
            'CALCULATE(COUNTROWS(FILTERS(Facts[Region])),ALLSELECTED(Facts[Region]),FILTER(Facts,Facts[Note]="Paid"),KEEPFILTERS(ISBLANK(Facts[Note])))': "2",
        }
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                self.assertEqual(_answer(expression), expected)

    def test_part_b_filters_of_a_table_filter_that_keeps_no_row_is_blank(self) -> None:
        self.assertEqual(_answer("CALCULATE(COUNTROWS(FILTERS(Facts[Quantity])),FILTER(Facts,Facts[Region]=BLANK()),REMOVEFILTERS(Facts[Note]))"), "BLANK")

    def test_part_b_filters_without_a_table_filter_is_unchanged(self) -> None:
        self.assertEqual(_answer("CALCULATE(COUNTROWS(FILTERS(Facts[Region])),TREATAS({2,3},Facts[Quantity]))"), "3")
        self.assertEqual(_answer('CALCULATE(COUNTROWS(FILTERS(Facts[Region])),TREATAS({"East","West"},Facts[Region]))'), "2")

    # Part A, table form and clearing
    def test_part_a_whole_table_form_marks_every_column(self) -> None:
        self.assertEqual(_answer("CALCULATE(ISFILTERED(Facts[Region]),ALLNOBLANKROW(Facts))"), "True")
        self.assertEqual(_answer("CALCULATE(ISCROSSFILTERED(Facts[Quantity]),ALLNOBLANKROW(Facts))"), "True")
        self.assertEqual(_answer("CALCULATE(CALCULATE(ISFILTERED(Facts[Quantity]),ALLNOBLANKROW(Facts)),ALL(Facts))"), "True")
        self.assertEqual(_answer("CALCULATE(ISFILTERED(Facts[Sales]),ALLNOBLANKROW(Facts),ALL(Facts[Sales]))"), "True")
        self.assertEqual(
            _answer("CALCULATE(CALCULATE(ISFILTERED(Facts[Region]),ALLNOBLANKROW(Facts),Facts[Sales]=BLANK()),ALLNOBLANKROW(Facts[Sales]))"),
            "True",
        )

    def test_part_a_an_outer_mark_is_dropped_by_the_clears_that_reach_it(self) -> None:
        outer = "ALLNOBLANKROW(Facts[Region])"
        cases = {
            ("ISFILTERED(Facts[Region])", "ALL(Facts[Region])"): "False",
            ("ISCROSSFILTERED(Facts[Quantity])", "REMOVEFILTERS(Facts[Region])"): "False",
            ("ISCROSSFILTERED(Facts[Quantity])", "ALLEXCEPT(Facts,Facts[Quantity])"): "False",
            ("ISCROSSFILTERED(Facts[Quantity])", "ALL(Facts)"): "False",
            ("ISCROSSFILTERED(Facts[Quantity])", "REMOVEFILTERS()"): "False",
            ("ISFILTERED(Facts[Region])", "ALL(Facts[Quantity])"): "True",
            ("ISFILTERED(Facts[Quantity])", "ALL(Facts[Quantity])"): "False",
            ("ISFILTERED(Facts[Region])", "ALLEXCEPT(Facts,Facts[Region])"): "True",
            ("ISFILTERED(Facts[Region])", "ALLSELECTED()"): "True",
        }
        for (flag, clear), expected in cases.items():
            expression = f"CALCULATE(CALCULATE({flag},{clear}),{outer})"
            with self.subTest(expression=expression):
                self.assertEqual(_answer(expression), expected)

    def test_part_a_an_outer_table_mark_keeps_iscrossfiltered_for_a_column_clear(self) -> None:
        table = "ALLNOBLANKROW(Facts)"
        cases = {
            ("ISFILTERED(Facts[Quantity])", "ALL(Facts[Quantity])"): "False",
            ("ISCROSSFILTERED(Facts[Quantity])", "ALL(Facts[Quantity])"): "True",
            ("ISFILTERED(Facts[Region])", "ALLEXCEPT(Facts,Facts[Quantity])"): "False",
            ("ISCROSSFILTERED(Facts[Region])", "ALLEXCEPT(Facts,Facts[Quantity])"): "True",
            ("ISFILTERED(Facts[Region])", "REMOVEFILTERS()"): "False",
            ("ISCROSSFILTERED(Facts[Region])", "ALL(Facts)"): "False",
            ("ISFILTERED(Facts[Quantity])", "ALLSELECTED(Facts)"): "True",
        }
        for (flag, clear), expected in cases.items():
            expression = f"CALCULATE(CALCULATE({flag},{clear}),{table})"
            with self.subTest(expression=expression):
                self.assertEqual(_answer(expression), expected)

    def test_part_a_three_levels_deep(self) -> None:
        self.assertEqual(
            _answer("CALCULATE(CALCULATE(CALCULATE(ISCROSSFILTERED(Facts[Quantity]),ALL(Facts[Quantity])),ALL(Facts)),ALLNOBLANKROW(Facts[Quantity]))"),
            "False",
        )
        self.assertEqual(
            _answer("CALCULATE(CALCULATE(CALCULATE(ISFILTERED(Facts[Region]),ALLNOBLANKROW(Facts[Quantity])),REMOVEFILTERS()),ALLNOBLANKROW(Facts[Region]))"),
            "False",
        )


if __name__ == "__main__":
    unittest.main()
