"""Task 214: typed table columns accept null cells (Power BI answer check, live, headless, 2026-11-17).

Items 36-43 are Power BI's answers verbatim.
"""

from __future__ import annotations

import unittest

from analytics_studio.m_engine import evaluate_to_text

ITEM_36 = '#table(type table [A=number,B=text,C=date],{{1,"a",null}})'
ITEM_37 = '#table(type table [A=number,B=text,C=date],{{1,"a",null}})[[C],[A]]'
ITEM_38 = 'Table.Schema(#table(type table [C=date],{{null},{#date(2026,1,2)}}))[[Name],[Kind],[IsNullable]]'
ITEM_39 = 'List.Max(#table(type table [C=date],{{null},{#date(2026,1,2)}})[C])'
ITEM_40 = 'Table.Sort(#table(type table [C=date],{{#date(2026,1,2)},{null},{#date(2025,5,1)}}), {{"C", Order.Ascending}})'
ITEM_41 = 'Table.SelectRows(#table(type table [C=date],{{#date(2026,1,2)},{null}}), each [C] > #date(2026,1,1))'
ITEM_42 = '#table(type table [C=datetime],{{null}})'
ITEM_43 = '#table(type table [C=time],{{null}})'


class TypedNullCellTests(unittest.TestCase):
    def test_item_36_null_cell_in_typed_table(self):
        self.assertEqual(
            evaluate_to_text(ITEM_36),
            'V:table:cols=["A":"number","B":"text","C":"date"];rows=[list:[number:1,text:"a",null]]',
        )

    def test_item_37_projection_keeps_null_cell(self):
        self.assertEqual(
            evaluate_to_text(ITEM_37),
            'V:table:cols=["C":"date","A":"number"];rows=[list:[null,number:1]]',
        )

    def test_item_38_schema_keeps_date_kind_and_non_nullable(self):
        # Power BI keeps IsNullable false here; it does not enforce the type on the null cell.
        self.assertEqual(
            evaluate_to_text(ITEM_38),
            'V:table:cols=["Name":"text","Kind":"text","IsNullable":"logical"];rows=[list:[text:"C",text:"date",false]]',
        )

    def test_item_39_list_max_ignores_null(self):
        self.assertEqual(evaluate_to_text(ITEM_39), "V:date:2026-01-02")

    def test_item_40_sort_ascending_puts_null_first(self):
        self.assertEqual(
            evaluate_to_text(ITEM_40),
            'V:table:cols=["C":"date"];rows=[list:[null],list:[date:2025-05-01],list:[date:2026-01-02]]',
        )

    def test_item_41_select_rows_drops_null_row(self):
        self.assertEqual(
            evaluate_to_text(ITEM_41),
            'V:table:cols=["C":"date"];rows=[list:[date:2026-01-02]]',
        )

    def test_item_42_datetime_null_cell(self):
        self.assertEqual(
            evaluate_to_text(ITEM_42),
            'V:table:cols=["C":"datetime"];rows=[list:[null]]',
        )

    def test_item_43_time_null_cell(self):
        self.assertEqual(
            evaluate_to_text(ITEM_43),
            'V:table:cols=["C":"time"];rows=[list:[null]]',
        )


if __name__ == "__main__":
    unittest.main()
