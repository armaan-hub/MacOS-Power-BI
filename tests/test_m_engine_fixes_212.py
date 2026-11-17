"""Task 212: three M engine fixes from the Power BI answer check (live, headless, 2026-11-17).

Items 16, 17, 18, 20 and 21 are Power BI's answers verbatim. Items 22-24 live in test_m_engine_error_rows.py.
"""

from __future__ import annotations

import unittest

from analytics_studio.m_engine import evaluate_to_text

ITEM_16 = 'Table.Schema(Table.Group(#table(type table [K=text, X=number],{{"a",1},{"a",2},{"b",3}}), {"K"}, {{"Count", each Table.RowCount(_), Int64.Type},{"Total", each List.Sum([X]), type nullable number}}))[[Name],[Kind]]'
ITEM_17 = 'Table.Schema(Table.Group(#table(type table [K=text, X=number],{{"a",1},{"a",2},{"b",3}}), {"K"}, {{"Count", each Table.RowCount(_)}}))[[Name],[Kind]]'
ITEM_18 = 'Table.AddIndexColumn(#table({"Index"},{{"a"}}), "Index", 0, 1)'
ITEM_20 = 'let t = Table.ReplaceValue(#table({"A"},{{"ab"},{null}}), "a", null, Replacer.ReplaceText, {"A"}) in Table.TransformColumns(t, {"A", each try _ otherwise "ERR"})'
ITEM_21 = 'let t = Table.ReplaceValue(#table({"A"},{{"ab"},{null}}), "a", null, Replacer.ReplaceText, {"A"}) in Table.TransformColumns(t, {"A", each try _ otherwise "ERR"})[A]{0}'


class TransformColumnsErrorCellTests(unittest.TestCase):
    def test_item_20_error_cell_is_not_passed_to_try_function(self):
        self.assertEqual(evaluate_to_text(ITEM_20), "UNREPRESENTABLE")

    def test_item_21_original_error_surfaces_when_read(self):
        self.assertEqual(
            evaluate_to_text(ITEM_21),
            "ERR:Expression.Error: We cannot convert the value null to type Text.",
        )


class AddIndexColumnNameClashTests(unittest.TestCase):
    def test_item_18_existing_name_gives_already_exists_error(self):
        self.assertEqual(
            evaluate_to_text(ITEM_18),
            "ERR:Expression.Error: The field 'Index' already exists in the record.",
        )


class TableProjectionTests(unittest.TestCase):
    def test_item_16_projection_keeps_named_columns_in_order(self):
        self.assertEqual(
            evaluate_to_text(ITEM_16),
            'V:table:cols=["Name":"text","Kind":"text"];rows=[list:[text:"K",text:"text"],'
            'list:[text:"Count",text:"number"],list:[text:"Total",text:"number"]]',
        )

    def test_item_17_projection_of_any_typed_column(self):
        self.assertEqual(
            evaluate_to_text(ITEM_17),
            'V:table:cols=["Name":"text","Kind":"text"];rows=[list:[text:"K",text:"text"],'
            'list:[text:"Count",text:"any"]]',
        )


if __name__ == "__main__":
    unittest.main()
