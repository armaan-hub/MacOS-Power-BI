"""Iteration 159: Task 69 order audit 4 (order-audit4-59).

Covers (live Power BI evidence in tools/parity/task69_order_audit4_spec.json and the 1,500-shape audit grid):
- Part A: a partitioned WINDOW (PARTITIONBY(Region), ASC) walks its partitions in the order their first row is stored; a numeric key walks
  partition by partition, a text key walks the text dictionary (BLANK first, then first-seen text) inside the stored partition order.
- Part B: an OFFSET with a negative offset over a text ORDERBY key lists its rows in the reverse of the ORDERBY order; positive offsets and
  numeric keys keep the ORDERBY order. TOPN of exactly as many rows as it keeps goes through the heap (array order), not the walk order.
- Part C: DISTINCT(SELECTCOLUMNS(...)) walks the distinct rows in the order of the columns the projection reads (years ascending).
- Part D: SELECTCOLUMNS walks in the order of every projected column, the bare column Region included (Region major, Quantity minor).
Nothing is refused by this iteration: all 41 measured rows are answered.
"""
from __future__ import annotations

import unittest

from analytics_studio import dax_iteration_order
from tools import dax_oracle_diff as dax


class TestIteration159OrderAudit4(unittest.TestCase):
    def assertLocal(self, expr: str, expected: str) -> None:
        with self.subTest(expr=expr):
            self.assertEqual(str(dax.local(expr)), expected)

    def test_part_a_partitioned_window_walks_partitions_in_stored_order(self) -> None:
        self.assertLocal(
            'CONCATENATEX(WINDOW(0,REL,0,REL,ALL(Facts[Quantity],Facts[Region]),ORDERBY(Facts[Quantity],ASC),PARTITIONBY(Facts[Region])),Facts[Quantity],",")',
            "1,2,5,0,3,4",
        )
        self.assertLocal(
            'CALCULATE(CONCATENATEX(WINDOW(0,REL,0,REL,ALL(Facts[Quantity],Facts[Region]),ORDERBY(Facts[Quantity],ASC),PARTITIONBY(Facts[Region])),Facts[Quantity],","),Facts[Note]="Paid")',
            "1,2,0",
        )
        self.assertLocal(
            'CALCULATE(CONCATENATEX(WINDOW(0,REL,0,REL,ALL(Facts[Quantity],Facts[Region]),ORDERBY(Facts[Quantity],ASC),PARTITIONBY(Facts[Region])),Facts[Quantity],","),Facts[Sales]>0)',
            "2,5,3",
        )
        self.assertLocal(
            'CALCULATE(CONCATENATEX(WINDOW(0,REL,0,REL,ALL(Facts[Sales],Facts[Region]),ORDERBY(Facts[Sales],ASC),PARTITIONBY(Facts[Region])),Facts[Sales],","),Facts[Quantity]<>3)',
            "-1.5,2.5,10.5,0,",
        )
        self.assertLocal(
            'CALCULATE(CONCATENATEX(WINDOW(0,REL,0,REL,ALL(Facts[Sales],Facts[Region]),ORDERBY(Facts[Sales],ASC),PARTITIONBY(Facts[Region])),Facts[Sales],","),Facts[Quantity]>=2)',
            "2.5,10.5,20,",
        )

    def test_part_a_text_key_walks_dictionary_order(self) -> None:
        self.assertLocal(
            'CALCULATE(CONCATENATEX(WINDOW(0,REL,0,REL,ALL(Facts[Note],Facts[Region]),ORDERBY(Facts[Note],ASC),PARTITIONBY(Facts[Region])),Facts[Note],","),Facts[Quantity]>=2)',
            ",,Paid,Late",
        )
        self.assertLocal(
            'CALCULATE(CONCATENATEX(WINDOW(0,REL,0,REL,ALL(Facts[Note],Facts[Region]),ORDERBY(Facts[Note],ASC),PARTITIONBY(Facts[Region])),Facts[Note],","),Facts[Region]<>"East")',
            ",Paid,Late",
        )
        self.assertLocal(
            'CALCULATE(CONCATENATEX(WINDOW(0,REL,0,REL,ALL(Facts[Region],Facts[Region]),ORDERBY(Facts[Region],ASC),PARTITIONBY(Facts[Region])),Facts[Region],","),Facts[Quantity]<>3)',
            "East,West,North",
        )

    def test_part_b_offset_over_text_lists_offset_rows_in_reverse(self) -> None:
        self.assertLocal(
            'CALCULATE(CONCATENATEX(OFFSET(-1,ALL(Facts[Note]),ORDERBY(Facts[Note],ASC)),Facts[Note],","),Facts[Quantity]>=2)',
            "Late,",
        )
        self.assertLocal(
            'CALCULATE(CONCATENATEX(OFFSET(-1,ALL(Facts[Note]),ORDERBY(Facts[Note],DESC)),Facts[Note],","),Facts[Quantity]>=2)',
            "Late,Paid",
        )
        self.assertLocal('CONCATENATEX(OFFSET(-1,ALL(Facts[Region]),ORDERBY(Facts[Region],DESC)),Facts[Region],",")', "North,West")
        self.assertLocal('CONCATENATEX(OFFSET(-1,ALL(Facts[Region]),ORDERBY(Facts[Region],ASC)),Facts[Region],",")', "North,East")

    def test_part_b_offset_over_numbers_and_positive_offsets_keep_order(self) -> None:
        self.assertLocal('CONCATENATEX(OFFSET(-1,ALL(Facts[Quantity]),ORDERBY(Facts[Quantity],ASC)),Facts[Quantity],",")', "0,1,2,3,4")
        self.assertLocal('CONCATENATEX(OFFSET(1,ALL(Facts[Region]),ORDERBY(Facts[Region],ASC)),Facts[Region],",")', "North,West")
        self.assertLocal(
            'CALCULATE(CONCATENATEX(OFFSET(1,ALL(Facts[Note]),ORDERBY(Facts[Note],DESC)),Facts[Note],","),Facts[Quantity]>=2,Facts[Quantity]<>3)',
            "Late,",
        )

    def test_part_b_topn_of_offset_rows_uses_the_heap_order(self) -> None:
        self.assertLocal('CONCATENATEX(TOPN(2,OFFSET(-1,ALL(Facts[Note]),ORDERBY(Facts[Note],ASC)),Facts[Note]),Facts[Note],",")', ",Late")
        self.assertLocal(
            'CALCULATE(CONCATENATEX(TOPN(2,OFFSET(-1,ALL(Facts[Region]),ORDERBY(Facts[Region],ASC)),Facts[Region]),Facts[Region],","),Facts[Region]<>"East")',
            "East,North",
        )
        self.assertLocal(
            'CALCULATE(CONCATENATEX(TOPN(2,OFFSET(2,ALL(Facts[Quantity]),ORDERBY(Facts[Quantity],DESC)),Facts[Quantity]),Facts[Quantity],","),Facts[Region]<>"East")',
            "1,2",
        )

    def test_part_c_distinct_of_selectcolumns_walks_years_ascending(self) -> None:
        self.assertLocal(
            'CONCATENATEX(DISTINCT(SELECTCOLUMNS(Facts,"y",YEAR(DATE(2020+Facts[Quantity],1,1)))),[y],",")',
            "2020,2021,2022,2023,2024,2025",
        )
        self.assertLocal(
            'CALCULATE(CONCATENATEX(DISTINCT(SELECTCOLUMNS(Facts,"y",YEAR(DATE(2020+Facts[Quantity],1,1)))),[y],","),Facts[Region]="West")',
            "2020,2023",
        )
        self.assertLocal(
            'CALCULATE(CONCATENATEX(DISTINCT(SELECTCOLUMNS(Facts,"y",YEAR(DATE(2020+Facts[Quantity],1,1)))),[y],","),Facts[Note]="Paid")',
            "2020,2021,2022",
        )

    def test_part_d_selectcolumns_walks_by_every_projected_column(self) -> None:
        self.assertLocal(
            'CONCATENATEX(SELECTCOLUMNS(Facts,"d",DATE(2020,1,1)-Facts[Quantity],"r",Facts[Region]),[d],",")',
            "12/31/2019,12/30/2019,12/27/2019,1/1/2020,12/29/2019,12/28/2019",
        )
        self.assertLocal(
            'CALCULATE(CONCATENATEX(SELECTCOLUMNS(Facts,"d",DATE(2020,1,1)-Facts[Quantity],"r",Facts[Region]),[d],","),Facts[Note]="Paid")',
            "12/31/2019,12/30/2019,1/1/2020",
        )
        self.assertLocal(
            'CALCULATE(CONCATENATEX(SELECTCOLUMNS(Facts,"d",DATE(2020,1,1)-Facts[Quantity],"r",Facts[Region]),[d],","),Facts[Sales]>0)',
            "12/30/2019,12/27/2019,12/29/2019",
        )


class TestIteration159Helpers(unittest.TestCase):
    def test_offset_walk_reversed_only_for_negative_text_offsets(self) -> None:
        self.assertTrue(dax_iteration_order.offset_walk_reversed(-1, ["Paid", None, "Late"]))
        self.assertFalse(dax_iteration_order.offset_walk_reversed(1, ["Paid", None, "Late"]))
        self.assertFalse(dax_iteration_order.offset_walk_reversed(-1, [1, 2, 3]))
        self.assertFalse(dax_iteration_order.offset_walk_reversed(-1, [None, None]))

    def test_partitioned_window_walk_numbers_partition_major(self) -> None:
        # rows 0..3 in ORDERBY order 2, 0, 3, 1; partitions: 0 and 2 are East (stored first), 1 and 3 are West
        key_values = [10, 20, 30, 40]
        partition_of = {0: "E", 1: "W", 2: "E", 3: "W"}
        storage_rank = {0: 0, 1: 1, 2: 2, 3: 3}
        ordered = [2, 0, 3, 1]
        self.assertEqual(dax_iteration_order.partitioned_window_walk(ordered, partition_of, key_values, storage_rank), [2, 0, 3, 1])
        self.assertEqual(
            dax_iteration_order.partitioned_window_walk([0, 1, 2, 3], partition_of, key_values, storage_rank),
            [0, 2, 1, 3],
        )

    def test_partitioned_window_walk_text_uses_dictionary_order(self) -> None:
        key_values = ["Paid", None, "Late", None]
        partition_of = {0: "E", 1: "W", 2: "N", 3: "E"}
        storage_rank = {0: 0, 1: 1, 2: 2, 3: 3}
        ordered = [1, 3, 0, 2]  # ORDERBY order: blank, blank, Late, Paid (alphabetical)
        # dictionary: blank, then Paid (stored first), then Late; the two blanks follow their partitions' stored order (E before W)
        self.assertEqual(dax_iteration_order.partitioned_window_walk(ordered, partition_of, key_values, storage_rank), [3, 1, 0, 2])


if __name__ == "__main__":
    unittest.main()
