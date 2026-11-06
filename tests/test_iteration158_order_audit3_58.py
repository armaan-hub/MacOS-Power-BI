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


if __name__ == "__main__":
    unittest.main()
