"""Iteration 158: Task 68 order audit 3 (order-audit3-58).

Covers (live Power BI evidence in tools/parity/task68_order_audit3_spec.json and the 1,500-shape audit grid):
- Part A: a relative WINDOW over ORDERBY(column, DESC), and an OFFSET over DESC of a numeric column, are refused (no order the ORDERBY explains);
  ASC windows and text OFFSET windows keep the answers that already match.
- Part B: SAMPLE over a text column walks the table in dictionary order (blank, then first-seen text) whatever the direction; numeric SAMPLE is unchanged.
- Part C: the groups of every level of a SUMMARIZE ... ROLLUP / ROLLUPGROUP come out in the order of the scan over the level's kept columns plus the
  columns an outer filter restricts to two or more values: dictionary order inside the measured key space, storage order of the first row at 792 over 6 rows.
- Part D: the same scan decides the group order of ADDMISSINGITEMS(SUMMARIZE ...) in TOCSV / TOJSON (storage order at 792 over 6 rows).
"""
from __future__ import annotations

import unittest

from tools import dax_oracle_diff as dax
from tools.parity_check import status


class TestIteration158OrderAudit3(unittest.TestCase):
    def test_part_a_relative_window_over_desc_is_refused(self) -> None:
        refused_cases = [
            'CONCATENATEX(WINDOW(-1,REL,1,REL,ALL(Facts[Quantity]),ORDERBY(Facts[Quantity],DESC)),Facts[Quantity],",")',
            'CONCATENATEX(WINDOW(-1,REL,1,REL,ALL(Facts[Note]),ORDERBY(Facts[Note],DESC)),Facts[Note],",")',
            'CALCULATE(CONCATENATEX(OFFSET(1,ALL(Facts[Sales]),ORDERBY(Facts[Sales],DESC)),Facts[Sales],","),Facts[Region]="West")',
        ]
        for expr in refused_cases:
            with self.subTest(expr=expr):
                actual = str(dax.local(expr))
                self.assertTrue(actual.startswith("LOCAL-REJECT:"), f"Expected refusal for {expr}, got: {actual}")

    def test_part_a_matching_windows_keep_their_answers(self) -> None:
        self.assertEqual(str(dax.local('CONCATENATEX(WINDOW(-1,REL,1,REL,ALL(Facts[Note]),ORDERBY(Facts[Note],ASC)),Facts[Note],",")')), ",Late,Paid")
        self.assertEqual(str(dax.local('CONCATENATEX(WINDOW(-1,REL,1,REL,ALL(Facts[Sales]),ORDERBY(Facts[Sales],ASC)),Facts[Sales],",")')), "-1.5,,0,2.5,10.5,20")
        self.assertEqual(str(dax.local('CONCATENATEX(OFFSET(1,ALL(Facts[Region]),ORDERBY(Facts[Region],ASC)),Facts[Region],",")')), "North,West")

    def test_part_b_sample_over_text_walks_dictionary_order(self) -> None:
        for direction in ("ASC", "DESC"):
            expr = f'CONCATENATEX(SAMPLE(3,ALL(Facts[Note]),Facts[Note],{direction}),Facts[Note],",")'
            with self.subTest(expr=expr):
                self.assertEqual(str(dax.local(expr)), ",Paid,Late")
        self.assertEqual(
            str(dax.local('CALCULATE(CONCATENATEX(SAMPLE(3,ALL(Facts[Region]),Facts[Region],DESC),Facts[Region],","),Facts[Quantity]<>3,Facts[Region]="West")')),
            "East,West,North",
        )

    def test_part_b_sample_over_numbers_is_unchanged(self) -> None:
        self.assertEqual(str(dax.local('CONCATENATEX(SAMPLE(3,ALL(Facts[Quantity]),Facts[Quantity],ASC),Facts[Quantity],",")')), "0,3,5")

    def test_part_c_rollup_groups_follow_the_scan_key_space(self) -> None:
        cases = {
            'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Sales],ROLLUP(Facts[Note]),"s",SUM(Facts[Quantity])),Facts[Sales],","),Facts[Quantity]<>3)': "10.5,-1.5,,0,2.5,0,-1.5,10.5,,2.5",
            'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Sales],ROLLUP(Facts[Region]),"s",SUM(Facts[Quantity])),Facts[Sales],","),Facts[Quantity]>=2,Facts[Region]<>"East")': "20,,20,",
            'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Sales],ROLLUP(Facts[Quantity]),"s",SUM(Facts[Quantity])),Facts[Quantity],","),Facts[Region]<>"East")': "3,4,0,,,",
            'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,ROLLUPGROUP(Facts[Quantity],Facts[Sales]),"s",SUM(Facts[Quantity])),Facts[Sales],","),Facts[Region]<>"East")': "20,,0,,,,",
            'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,ROLLUPGROUP(Facts[Region],Facts[Sales]),"s",SUM(Facts[Quantity])),Facts[Sales],","),Facts[Quantity]>1)': "10.5,20,,2.5,,,,",
            'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,ROLLUPGROUP(Facts[Sales],Facts[Region]),"s",SUM(Facts[Quantity])),Facts[Sales],","),Facts[Quantity]>=2)': "10.5,20,,2.5,10.5,20,,2.5,",
        }
        for expr, expected in cases.items():
            with self.subTest(expr=expr):
                self.assertEqual(str(dax.local(expr)), expected)

    def test_part_c_sorted_key_space_keeps_dictionary_order(self) -> None:
        # a filter on the group column itself adds no scan column: 44 x 6 = 264 stays inside the measured sorted space
        self.assertEqual(
            str(dax.local('CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Sales],ROLLUP(Facts[Quantity]),"s",SUM(Facts[Quantity])),Facts[Quantity],","),Facts[Quantity]<>3)')),
            "0,1,2,4,5,,,,,",
        )
        # an equality filter leaves one value: it does not join the scan
        self.assertEqual(
            str(dax.local('CALCULATE(CONCATENATEX(SUMMARIZE(Facts,ROLLUPGROUP(Facts[Quantity],Facts[Sales]),"s",SUM(Facts[Quantity])),Facts[Quantity],","),Facts[Region]="West")')),
            "0,3,0,3,",
        )

    def test_part_c_single_value_rollup_keeps_its_answer(self) -> None:
        expr = 'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Sales],ROLLUP(Facts[Note]),"s",SUM(Facts[Quantity])),Facts[Sales],","),Facts[Sales]>0,Facts[Region]="West")'
        self.assertEqual(str(dax.local(expr)), "20,20")

    def test_part_d_addmissingitems_two_outer_filters_storage_order(self) -> None:
        expr = 'CALCULATE(TOJSON(ADDMISSINGITEMS(Facts[Note],SUMMARIZE(Facts,Facts[Note],"s",SUM(Facts[Sales])),Facts[Note])),Facts[Quantity]>1,Facts[Sales]>0)'
        expected = '{\n\t"header": ["\'Facts\'[Note]", "[s]"],\n\t"rowCount": 2,\n\t"data": [\n\t\t["Paid", 10.5],\n\t\t[null, 22.5]\n\t]\n}'
        self.assertEqual(status(expected, str(dax.local(expr))), "match")

    def test_part_d_addmissingitems_one_outer_filter_keeps_its_answer(self) -> None:
        expr = 'CALCULATE(TOCSV(ADDMISSINGITEMS(Facts[Note],SUMMARIZE(Facts,Facts[Note],"s",SUM(Facts[Sales])),Facts[Note]),100),Facts[Sales]>0)'
        self.assertEqual(status("'Facts'[Note],[s]\n,22.5\nPaid,10.5", str(dax.local(expr))), "match")


    def test_round2_scan_order_on_other_row_sets(self) -> None:
        """Live Power BI answers on three more Facts row sets (datasets d2, d7, d10 of the round-2 probe grids)."""
        d2 = [("5", "7", "North", "Late"), ("", "2", "East", ""), ("5", "3", "West", "Paid"), ("-2", "7", "East", "Paid"), ("8", "1", "North", ""),
              ("1.5", "2", "West", "Late"), ("8", "9", "East", "Paid"), ("0", "3", "North", "Paid"), ("3", "5", "West", "")]
        d7 = [("11", "1", "West", "Paid"), ("2", "3", "West", "Paid"), ("30", "5", "East", "Late"), ("-4", "3", "West", "Paid"), ("27", "3", "West", "Late"),
              ("", "0", "North", ""), ("25", "1", "West", "Paid"), ("0", "1", "South", "")]
        d10 = [("2", "3", "West", ""), ("1", "2", "North", "Paid"), ("3", "2", "West", "Late"), ("0", "3", "South", ""), ("3", "2", "South", "")]
        saved = (dax.ROWS, dax.LOCAL_ROWS, dax.FACTS_DAX)
        cases = [
            (d2, 'CALCULATE(CONCATENATEX(ADDMISSINGITEMS(Facts[Sales],SUMMARIZE(Facts,Facts[Sales],"s",SUM(Facts[Sales])),Facts[Sales]),Facts[Sales],","),Facts[Region]<>"East")', "0,5,8,1.5,3"),
            (d2, 'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Sales],ROLLUP(Facts[Region]),"s",SUM(Facts[Quantity])),Facts[Sales],","),Facts[Region]<>"East")', "0,5,8,1.5,3,5,0,5,8,1.5,3"),
            (d7, 'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Sales],ROLLUP(Facts[Quantity]),"s",SUM(Facts[Quantity])),Facts[Sales],","),Facts[Region]<>"East")', "11,25,-4,2,27,,0,-4,2,11,25,27,,0"),
            (d7, 'CALCULATE(CONCATENATEX(SAMPLE(3,ALL(Facts[Region]),Facts[Region],ASC),Facts[Region],","),Facts[Quantity]>2)', "East,South,West"),
            (d10, 'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Sales],ROLLUP(Facts[Note]),"s",SUM(Facts[Quantity])),Facts[Sales],","),Facts[Region]<>"East")', "2,0,3,1,3,2,3,1,0"),
        ]
        try:
            for rows, expr, expected in cases:
                dax.ROWS = rows
                dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, r)} for r in rows]
                with self.subTest(expr=expr):
                    self.assertEqual(str(dax.local(expr)), expected)
            dax.ROWS = d7
            dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, r)} for r in d7]
            desc = 'CALCULATE(CONCATENATEX(SAMPLE(3,ALL(Facts[Region]),Facts[Region],DESC),Facts[Region],","),Facts[Quantity]>2)'
            self.assertTrue(str(dax.local(desc)).startswith("LOCAL-REJECT:"))  # a dropping text sample was measured for ASC only
        finally:
            dax.ROWS, dax.LOCAL_ROWS, dax.FACTS_DAX = saved


    def test_round3_scan_points_on_d12_and_d14(self) -> None:
        """Live Power BI answers on the held-out row sets d12 (11 rows, sorted scan at 2,250) and d14 (14 rows, storage-order detail scan at 7,600)."""
        d12 = [("-2", "8", "North", "Late"), ("", "9", "North", "Late"), ("10", "4", "South", "Late"), ("32", "8", "West", "Paid"), ("36", "15", "North", "Late"),
               ("34", "13", "North", "Late"), ("37", "14", "North", ""), ("32", "2", "West", ""), ("39", "1", "South", "Paid"), ("47", "11", "South", "Late"),
               ("0", "15", "South", "Paid")]
        d14 = [("29", "9", "South", "Paid"), ("81", "10", "North", "Paid"), ("0", "22", "West", ""), ("94", "7", "South", "Late"), ("2", "12", "East", "Late"),
               ("42", "9", "West", "Paid"), ("28", "12", "South", ""), ("4", "3", "West", "Late"), ("24", "8", "West", ""), ("", "5", "West", ""),
               ("73", "21", "East", "Paid"), ("29", "8", "North", ""), ("23", "14", "East", "Paid"), ("76", "4", "North", "Late")]
        saved = (dax.ROWS, dax.LOCAL_ROWS, dax.FACTS_DAX)
        cases = [
            (d12, 'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Sales],ROLLUP(Facts[Region]),"s",SUM(Facts[Quantity])),Facts[Region],","),Facts[Quantity]>2)',
             "North,North,North,North,North,South,South,South,West,,,,,,,,,"),
            (d14, 'CALCULATE(CONCATENATEX(SUMMARIZE(Facts,Facts[Sales],ROLLUP(Facts[Quantity]),"s",SUM(Facts[Quantity])),Facts[Sales],","),Facts[Region]<>"East")',
             "29,81,0,94,42,28,4,24,,29,76,28,29,94,76,81,,0,4,24,42"),
        ]
        try:
            for rows, expr, expected in cases:
                dax.ROWS = rows
                dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, r)} for r in rows]
                with self.subTest(expr=expr):
                    self.assertEqual(str(dax.local(expr)), expected)
        finally:
            dax.ROWS, dax.LOCAL_ROWS, dax.FACTS_DAX = saved


if __name__ == "__main__":
    unittest.main()
