"""Iteration 159: Task 69 order audit 4 (order-audit4-59).

Covers (live Power BI evidence in tools/parity/task69_order_audit4_spec.json, the 1,500-shape audit grid t69a, the held-out grid t69b and nine more Facts
row sets d2 to d18):
- OFFSET and relative WINDOW over ALL(columns of one table) list the rows the current rows pick in the walk order of the CURRENT rows (BLANK, then first-seen
  text, numbers ascending, the later table column the major key), each current row's pick in ORDERBY order, a row once. That explains OFFSET(-1, ALL(Note),
  ORDERBY(Note, ASC)) = "Late," over Paid, BLANK, Late stored, and the partitioned WINDOW(0, REL, 0, REL, ALL(Sales, Region), ..., PARTITIONBY(Region)) rows.
- TOPN of exactly as many OFFSET rows as it keeps goes through the heap (array order); a WINDOW of exactly that many rows comes back in walk order.
- DISTINCT(SELECTCOLUMNS(.. one source column ..)) walks the source column in dictionary order, a projected value where its first source row stands.
- SELECTCOLUMNS with a computed projection walks every projected column (the later table column major) while their dense key space is small for the rows,
  in storage order when it is large, and is refused between the measured points.
"""
from __future__ import annotations

import unittest

from analytics_studio import dax_iteration_order
from tools import dax_oracle_diff as dax


class TestIteration159OrderAudit4(unittest.TestCase):
    def assertLocal(self, expr: str, expected: str) -> None:
        with self.subTest(expr=expr):
            self.assertEqual(str(dax.local(expr)), expected)

    def test_part_a_partitioned_window_walks_partitions_in_dictionary_order(self) -> None:
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

    def test_part_b_offset_lists_rows_in_the_walk_of_the_current_rows(self) -> None:
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


class TestIteration159HeldOutRowSets(unittest.TestCase):
    """Live Power BI answers on six more Facts row sets (datasets d2, d4, d7, d9, d12, d16 of the held-out probe grids)."""

    DATASETS = {
        "d2": [('5', '7', 'North', 'Late'), ('', '2', 'East', ''), ('5', '3', 'West', 'Paid'), ('-2', '7', 'East', 'Paid'), ('8', '1', 'North', ''), ('1.5', '2', 'West', 'Late'), ('8', '9', 'East', 'Paid'), ('0', '3', 'North', 'Paid'), ('3', '5', 'West', '')],
        "d4": [('500', '40', 'West', ''), ('12', '3', 'North', 'Paid'), ('999', '77', 'East', 'Late'), ('', '12', 'West', 'Paid'), ('7', '81', 'North', 'Late'), ('250', '5', 'East', ''), ('61', '60', 'West', 'Late'), ('3', '22', 'North', 'Paid'), ('800', '9', 'East', 'Paid'), ('45', '33', 'West', ''), ('130', '18', 'North', 'Late'), ('2', '70', 'East', 'Paid')],
        "d7": [('11', '1', 'West', 'Paid'), ('2', '3', 'West', 'Paid'), ('30', '5', 'East', 'Late'), ('-4', '3', 'West', 'Paid'), ('27', '3', 'West', 'Late'), ('', '0', 'North', ''), ('25', '1', 'West', 'Paid'), ('0', '1', 'South', '')],
        "d9": [('48', '5', 'West', 'Paid'), ('', '3', 'West', ''), ('123', '24', 'South', 'Late'), ('124', '38', 'East', 'Late'), ('154', '18', 'North', 'Late'), ('111', '12', 'East', ''), ('', '2', 'East', ''), ('', '5', 'East', ''), ('47', '5', 'South', 'Paid'), ('22', '24', 'North', 'Late')],
        "d12": [('-2', '8', 'North', 'Late'), ('', '9', 'North', 'Late'), ('10', '4', 'South', 'Late'), ('32', '8', 'West', 'Paid'), ('36', '15', 'North', 'Late'), ('34', '13', 'North', 'Late'), ('37', '14', 'North', ''), ('32', '2', 'West', ''), ('39', '1', 'South', 'Paid'), ('47', '11', 'South', 'Late'), ('0', '15', 'South', 'Paid')],
        "d16": [('', '7', 'South', 'Paid'), ('', '9', 'South', 'Paid'), ('', '4', 'North', 'Late'), ('41', '9', 'South', ''), ('-3', '5', 'North', 'Paid'), ('-5', '3', 'West', ''), ('15', '6', 'West', 'Late'), ('24', '0', 'East', ''), ('-4', '4', 'North', 'Late'), ('3', '7', 'North', 'Paid'), ('67', '1', 'East', 'Paid'), ('50', '5', 'East', ''), ('34', '9', 'East', 'Late')],
    }
    DATASET_CASES = [
        ('d2', 'CONCATENATEX(OFFSET(-1,ALL(Facts[Note]),ORDERBY(Facts[Note],ASC)),Facts[Note],",")', ',Late'),
        ('d2', 'CONCATENATEX(OFFSET(1,ALL(Facts[Region]),ORDERBY(Facts[Region],DESC)),Facts[Region],",")', 'East,North'),
        ('d2', 'CALCULATE(CONCATENATEX(OFFSET(1,ALL(Facts[Sales]),ORDERBY(Facts[Sales],ASC)),Facts[Sales],","),Facts[Region]<>"East")', '1.5,3,5,8'),
        ('d2', 'CONCATENATEX(WINDOW(0,REL,0,REL,ALL(Facts[Sales],Facts[Region]),ORDERBY(Facts[Sales],ASC),PARTITIONBY(Facts[Region])),Facts[Sales],",")', '0,5,8,,-2,8,1.5,3,5'),
        ('d2', 'CALCULATE(CONCATENATEX(WINDOW(0,REL,0,REL,ALL(Facts[Note],Facts[Region]),ORDERBY(Facts[Note],ASC),PARTITIONBY(Facts[Region])),Facts[Note],","),Facts[Quantity]>2)', ',Late,Paid,Paid,Paid'),
        ('d2', 'CONCATENATEX(DISTINCT(SELECTCOLUMNS(Facts,"y",LEN(Facts[Sales]))),[y],",")', ',2,1,3'),
        ('d2', 'CALCULATE(CONCATENATEX(DISTINCT(SELECTCOLUMNS(Facts,"y",LEN(Facts[Note]))),[y],","),Facts[Region]<>"East")', ',4'),
        ('d2', 'CONCATENATEX(SELECTCOLUMNS(Facts,"d",DATE(2020,1,1)-Facts[Quantity],"r",Facts[Sales]),[d],",")', '12/25/2019,12/30/2019,12/29/2019,12/25/2019,12/31/2019,12/30/2019,12/23/2019,12/29/2019,12/27/2019'),
        ('d2', 'CONCATENATEX(SELECTCOLUMNS(Facts,"d",DATE(2020,1,1)-Facts[Quantity],"r",Facts[Note]),[d],",")', '12/31/2019,12/30/2019,12/27/2019,12/30/2019,12/25/2019,12/29/2019,12/29/2019,12/25/2019,12/23/2019'),
        ('d4', 'CONCATENATEX(OFFSET(-1,ALL(Facts[Note]),ORDERBY(Facts[Note],ASC)),Facts[Note],",")', 'Late,'),
        ('d4', 'CONCATENATEX(OFFSET(1,ALL(Facts[Region]),ORDERBY(Facts[Region],DESC)),Facts[Region],",")', 'North,East'),
        ('d4', 'CALCULATE(CONCATENATEX(OFFSET(1,ALL(Facts[Sales]),ORDERBY(Facts[Sales],ASC)),Facts[Sales],","),Facts[Region]<>"East")', '2,7,12,45,61,130,250,800'),
        ('d4', 'CONCATENATEX(WINDOW(0,REL,0,REL,ALL(Facts[Sales],Facts[Region]),ORDERBY(Facts[Sales],ASC),PARTITIONBY(Facts[Region])),Facts[Sales],",")', ',45,61,500,3,7,12,130,2,250,800,999'),
        ('d4', 'CALCULATE(CONCATENATEX(WINDOW(0,REL,0,REL,ALL(Facts[Note],Facts[Region]),ORDERBY(Facts[Note],ASC),PARTITIONBY(Facts[Region])),Facts[Note],","),Facts[Quantity]>2)', ',,Paid,Paid,Paid,Late,Late,Late'),
        ('d4', 'CONCATENATEX(DISTINCT(SELECTCOLUMNS(Facts,"y",LEN(Facts[Sales]))),[y],",")', ',1,2,3'),
        ('d4', 'CALCULATE(CONCATENATEX(DISTINCT(SELECTCOLUMNS(Facts,"y",LEN(Facts[Note]))),[y],","),Facts[Region]<>"East")', ',4'),
        ('d4', 'CONCATENATEX(SELECTCOLUMNS(Facts,"d",DATE(2020,1,1)-Facts[Quantity],"r",Facts[Sales]),[d],",")', '11/22/2019,12/29/2019,10/16/2019,12/20/2019,10/12/2019,12/27/2019,11/2/2019,12/10/2019,12/23/2019,11/29/2019,12/14/2019,10/23/2019'),
        ('d4', 'CONCATENATEX(SELECTCOLUMNS(Facts,"d",DATE(2020,1,1)-Facts[Quantity],"r",Facts[Note]),[d],",")', '12/27/2019,11/29/2019,11/22/2019,12/29/2019,12/23/2019,12/20/2019,12/10/2019,10/23/2019,12/14/2019,11/2/2019,10/16/2019,10/12/2019'),
        ('d7', 'CONCATENATEX(OFFSET(-1,ALL(Facts[Note]),ORDERBY(Facts[Note],ASC)),Facts[Note],",")', 'Late,'),
        ('d7', 'CONCATENATEX(OFFSET(1,ALL(Facts[Region]),ORDERBY(Facts[Region],DESC)),Facts[Region],",")', 'South,East,North'),
        ('d7', 'CALCULATE(CONCATENATEX(OFFSET(1,ALL(Facts[Sales]),ORDERBY(Facts[Sales],ASC)),Facts[Sales],","),Facts[Region]<>"East")', '0,,2,11,25,27,30'),
        ('d7', 'CONCATENATEX(WINDOW(0,REL,0,REL,ALL(Facts[Sales],Facts[Region]),ORDERBY(Facts[Sales],ASC),PARTITIONBY(Facts[Region])),Facts[Sales],",")', '-4,2,11,25,27,30,,0'),
        ('d7', 'CALCULATE(CONCATENATEX(WINDOW(0,REL,0,REL,ALL(Facts[Note],Facts[Region]),ORDERBY(Facts[Note],ASC),PARTITIONBY(Facts[Region])),Facts[Note],","),Facts[Quantity]>2)', 'Paid,Late,Late'),
        ('d7', 'CONCATENATEX(DISTINCT(SELECTCOLUMNS(Facts,"y",LEN(Facts[Sales]))),[y],",")', ',2,1'),
        ('d7', 'CALCULATE(CONCATENATEX(DISTINCT(SELECTCOLUMNS(Facts,"y",LEN(Facts[Note]))),[y],","),Facts[Region]<>"East")', ',4'),
        ('d7', 'CONCATENATEX(SELECTCOLUMNS(Facts,"d",DATE(2020,1,1)-Facts[Quantity],"r",Facts[Sales]),[d],",")', '1/1/2020,12/31/2019,12/31/2019,12/31/2019,12/29/2019,12/29/2019,12/29/2019,12/27/2019'),
        ('d7', 'CONCATENATEX(SELECTCOLUMNS(Facts,"d",DATE(2020,1,1)-Facts[Quantity],"r",Facts[Note]),[d],",")', '1/1/2020,12/31/2019,12/31/2019,12/31/2019,12/29/2019,12/29/2019,12/29/2019,12/27/2019'),
        ('d9', 'CONCATENATEX(OFFSET(-1,ALL(Facts[Note]),ORDERBY(Facts[Note],ASC)),Facts[Note],",")', 'Late,'),
        ('d9', 'CONCATENATEX(OFFSET(1,ALL(Facts[Region]),ORDERBY(Facts[Region],DESC)),Facts[Region],",")', 'South,North,East'),
        ('d9', 'CALCULATE(CONCATENATEX(OFFSET(1,ALL(Facts[Sales]),ORDERBY(Facts[Sales],ASC)),Facts[Sales],","),Facts[Region]<>"East")', '22,47,48,111,124'),
        ('d9', 'CONCATENATEX(WINDOW(0,REL,0,REL,ALL(Facts[Sales],Facts[Region]),ORDERBY(Facts[Sales],ASC),PARTITIONBY(Facts[Region])),Facts[Sales],",")', ',48,47,123,,111,124,22,154'),
        ('d9', 'CALCULATE(CONCATENATEX(WINDOW(0,REL,0,REL,ALL(Facts[Note],Facts[Region]),ORDERBY(Facts[Note],ASC),PARTITIONBY(Facts[Region])),Facts[Note],","),Facts[Quantity]>2)', ',,Paid,Paid,Late,Late,Late'),
        ('d9', 'CONCATENATEX(DISTINCT(SELECTCOLUMNS(Facts,"y",LEN(Facts[Sales]))),[y],",")', ',2,3'),
        ('d9', 'CALCULATE(CONCATENATEX(DISTINCT(SELECTCOLUMNS(Facts,"y",LEN(Facts[Note]))),[y],","),Facts[Region]<>"East")', ',4'),
        ('d9', 'CONCATENATEX(SELECTCOLUMNS(Facts,"d",DATE(2020,1,1)-Facts[Quantity],"r",Facts[Sales]),[d],",")', '12/27/2019,12/29/2019,12/8/2019,11/24/2019,12/14/2019,12/20/2019,12/30/2019,12/27/2019,12/27/2019,12/8/2019'),
        ('d9', 'CONCATENATEX(SELECTCOLUMNS(Facts,"d",DATE(2020,1,1)-Facts[Quantity],"r",Facts[Note]),[d],",")', '12/30/2019,12/29/2019,12/27/2019,12/20/2019,12/27/2019,12/27/2019,12/14/2019,12/8/2019,12/8/2019,11/24/2019'),
        ('d12', 'CONCATENATEX(OFFSET(-1,ALL(Facts[Note]),ORDERBY(Facts[Note],ASC)),Facts[Note],",")', ',Late'),
        ('d12', 'CONCATENATEX(OFFSET(1,ALL(Facts[Region]),ORDERBY(Facts[Region],DESC)),Facts[Region],",")', 'North,South'),
        ('d12', 'CALCULATE(CONCATENATEX(OFFSET(1,ALL(Facts[Sales]),ORDERBY(Facts[Sales],ASC)),Facts[Sales],","),Facts[Region]<>"East")', '0,,10,32,34,36,37,39,47'),
        ('d12', 'CONCATENATEX(WINDOW(0,REL,0,REL,ALL(Facts[Sales],Facts[Region]),ORDERBY(Facts[Sales],ASC),PARTITIONBY(Facts[Region])),Facts[Sales],",")', ',-2,34,36,37,0,10,39,47,32'),
        ('d12', 'CALCULATE(CONCATENATEX(WINDOW(0,REL,0,REL,ALL(Facts[Note],Facts[Region]),ORDERBY(Facts[Note],ASC),PARTITIONBY(Facts[Region])),Facts[Note],","),Facts[Quantity]>2)', ',Late,Late,Paid,Paid'),
        ('d12', 'CONCATENATEX(DISTINCT(SELECTCOLUMNS(Facts,"y",LEN(Facts[Sales]))),[y],",")', ',2,1'),
        ('d12', 'CALCULATE(CONCATENATEX(DISTINCT(SELECTCOLUMNS(Facts,"y",LEN(Facts[Note]))),[y],","),Facts[Region]<>"East")', ',4'),
        ('d12', 'CONCATENATEX(SELECTCOLUMNS(Facts,"d",DATE(2020,1,1)-Facts[Quantity],"r",Facts[Sales]),[d],",")', '12/24/2019,12/23/2019,12/28/2019,12/24/2019,12/17/2019,12/19/2019,12/18/2019,12/30/2019,12/31/2019,12/21/2019,12/17/2019'),
        ('d12', 'CONCATENATEX(SELECTCOLUMNS(Facts,"d",DATE(2020,1,1)-Facts[Quantity],"r",Facts[Note]),[d],",")', '12/30/2019,12/18/2019,12/28/2019,12/24/2019,12/23/2019,12/21/2019,12/19/2019,12/17/2019,12/31/2019,12/24/2019,12/17/2019'),
        ('d16', 'CONCATENATEX(OFFSET(-1,ALL(Facts[Note]),ORDERBY(Facts[Note],ASC)),Facts[Note],",")', 'Late,'),
        ('d16', 'CONCATENATEX(OFFSET(1,ALL(Facts[Region]),ORDERBY(Facts[Region],DESC)),Facts[Region],",")', 'North,East,South'),
        ('d16', 'CALCULATE(CONCATENATEX(OFFSET(1,ALL(Facts[Sales]),ORDERBY(Facts[Sales],ASC)),Facts[Sales],","),Facts[Region]<>"East")', '3,-4,-3,,15,24,50'),
        ('d16', 'CONCATENATEX(WINDOW(0,REL,0,REL,ALL(Facts[Sales],Facts[Region]),ORDERBY(Facts[Sales],ASC),PARTITIONBY(Facts[Region])),Facts[Sales],",")', ',41,,-4,-3,3,-5,15,24,34,50,67'),
        ('d16', 'CALCULATE(CONCATENATEX(WINDOW(0,REL,0,REL,ALL(Facts[Note],Facts[Region]),ORDERBY(Facts[Note],ASC),PARTITIONBY(Facts[Region])),Facts[Note],","),Facts[Quantity]>2)', ',,,Paid,Paid,Late,Late,Late'),
        ('d16', 'CONCATENATEX(DISTINCT(SELECTCOLUMNS(Facts,"y",LEN(Facts[Sales]))),[y],",")', ',2,1'),
        ('d16', 'CALCULATE(CONCATENATEX(DISTINCT(SELECTCOLUMNS(Facts,"y",LEN(Facts[Note]))),[y],","),Facts[Region]<>"East")', ',4'),
        ('d16', 'CONCATENATEX(SELECTCOLUMNS(Facts,"d",DATE(2020,1,1)-Facts[Quantity],"r",Facts[Sales]),[d],",")', '12/25/2019,12/23/2019,12/28/2019,12/23/2019,12/27/2019,12/29/2019,12/26/2019,1/1/2020,12/28/2019,12/25/2019,12/31/2019,12/27/2019,12/23/2019'),
        ('d16', 'CONCATENATEX(SELECTCOLUMNS(Facts,"d",DATE(2020,1,1)-Facts[Quantity],"r",Facts[Note]),[d],",")', '1/1/2020,12/29/2019,12/27/2019,12/23/2019,12/31/2019,12/27/2019,12/25/2019,12/25/2019,12/23/2019,12/28/2019,12/28/2019,12/26/2019,12/23/2019'),
    ]

    def test_dataset_answers(self) -> None:
        saved = (dax.ROWS, dax.LOCAL_ROWS, dax.FACTS_DAX)
        try:
            for name, expr, expected in self.DATASET_CASES:
                rows = self.DATASETS[name]
                dax.ROWS = rows
                dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, r)} for r in rows]
                with self.subTest(dataset=name, expr=expr):
                    self.assertEqual(str(dax.local(expr)), expected)
        finally:
            dax.ROWS, dax.LOCAL_ROWS, dax.FACTS_DAX = saved

    def test_selectcolumns_key_space_between_measured_points_is_refused(self) -> None:
        # Sales 41..100 x Quantity 1..9 is a key space of 540 over 8 rows: above the sorted point (210, 8), below the storage point (730, 13), not measured
        rows = [("61", "5", "East", ""), ("100", "3", "West", ""), ("75", "9", "East", ""), ("41", "1", "West", ""), ("88", "6", "East", ""),
                ("52", "2", "North", ""), ("67", "8", "North", ""), ("93", "4", "West", "")]
        saved = (dax.ROWS, dax.LOCAL_ROWS, dax.FACTS_DAX)
        try:
            dax.ROWS = rows
            dax.LOCAL_ROWS = [{h: (v if v != "" else None) for h, v in zip(dax.HEADERS, r)} for r in rows]
            actual = str(dax.local('CONCATENATEX(SELECTCOLUMNS(Facts,"d",DATE(2020,1,1)-Facts[Quantity],"r",Facts[Sales]),[d],",")'))
            self.assertTrue(actual.startswith("LOCAL-REJECT:"), actual)
        finally:
            dax.ROWS, dax.LOCAL_ROWS, dax.FACTS_DAX = saved
