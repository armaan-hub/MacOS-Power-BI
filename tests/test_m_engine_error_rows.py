"""Table.ReplaceErrorValues and the columns argument of Table.SelectRowsWithErrors / RemoveRowsWithErrors.

Each expression is one of Power BI Desktop's live answers (headless M answer check, 2026-11-17).
UNREPRESENTABLE means Power BI's result still holds error cells; the test then checks that the
local engine's result holds an error cell in the stated columns.
"""

from __future__ import annotations

import unittest

import pytest

from analytics_studio.m_engine import evaluate_to_text
from analytics_studio.m_engine import values as V
from analytics_studio.m_engine.evaluator import evaluate, root_env
from analytics_studio.m_engine.parser import parse
from analytics_studio.m_engine.values import MError

BASE = (
    'Table.TransformColumns(#table({"A","B"},{{"1","x"},{"q","2"},{"3","4"}}), '
    '{{"A", Number.From},{"B", Number.From}})'
)
BASE_TWO_ROWS = (
    'Table.TransformColumns(#table({"A","B"},{{"1","x"},{"q","2"}}), '
    '{{"A", Number.From},{"B", Number.From}})'
)
TO_ROWS_AB = (
    'Table.ToRows(Table.SelectColumns(Table.AddColumn(Table.AddColumn({t}, "a", '
    'each try Text.From([A]) otherwise "ERR"), "b", each try Text.From([B]) otherwise "ERR"), {{"a","b"}}))'
)


def _error_columns(source: str) -> set:
    """Names of the columns that hold an error cell in the result table."""
    value = evaluate(parse(source), root_env())
    assert isinstance(value, V.Table), type(value)
    found = set()
    for row in value.rows:
        for (name, _kind), cell in zip(value.columns, row):
            try:
                V.force(cell)
            except MError:
                found.add(name)
    return found


class ReplaceErrorValuesTests(unittest.TestCase):
    def test_item_12_replaces_only_listed_column_and_keeps_other_errors(self):
        source = f'Table.ReplaceErrorValues({BASE_TWO_ROWS}, {{{{"A", null}}}})'
        self.assertEqual(evaluate_to_text(source), "UNREPRESENTABLE")
        self.assertEqual(_error_columns(source), {"B"})

    @pytest.mark.xfail(strict=True, reason="Task 212: try inside Table.TransformColumns must not catch cell errors (Power BI answer check 2026-11-17)")
    def test_item_22_replace_then_try_per_cell(self):
        source = (
            f'let t = Table.ReplaceErrorValues({BASE_TWO_ROWS}, {{{{"A", null}}}}) in '
            'Table.TransformColumns(t, {{"A", each try _ otherwise "ERR"},{"B", each try _ otherwise "ERR"}})'
        )
        self.assertEqual(evaluate_to_text(source), "UNREPRESENTABLE")

    def test_item_25_keeps_number_column_type_and_puts_text_in_cell(self):
        source = (
            'let t = Table.ReplaceErrorValues(Table.TransformColumns(#table({"A"},{{"q"}}), '
            '{{"A", Number.From}}), {{"A", ""}}) in t'
        )
        self.assertEqual(
            evaluate_to_text(source),
            'V:table:cols=["A":"number"];rows=[list:[text:""]]',
        )

    def test_item_26_text_view_of_replaced_rows(self):
        source = (
            f'let t = Table.ReplaceErrorValues({BASE_TWO_ROWS}, {{{{"A", null}}}}) in '
            'Table.ToRows(Table.SelectColumns(Table.AddColumn(Table.AddColumn(t, "a", '
            'each try Text.From([A]) otherwise "ERR"), "b", each try Text.From([B]) otherwise "ERR"), {"a","b"}))'
        )
        self.assertEqual(
            evaluate_to_text(source),
            'V:list:[list:[text:"1",text:"ERR"],list:[null,text:"2"]]',
        )

    def test_flat_pair_form_is_accepted(self):
        source = f'Table.ReplaceErrorValues({BASE_TWO_ROWS}, {{"A", 0}})'
        self.assertEqual(_error_columns(source), {"B"})
        self.assertEqual(
            evaluate_to_text(f'Table.ReplaceErrorValues({BASE_TWO_ROWS}, {{"A", 0}})'),
            "UNREPRESENTABLE",
        )

    def test_unknown_column_message_verbatim(self):
        source = f'Table.ReplaceErrorValues({BASE_TWO_ROWS}, {{{{"Zed", 0}}}})'
        self.assertEqual(
            evaluate_to_text(source),
            "ERR:Expression.Error: The column 'Zed' of the table wasn't found.",
        )


class RowsWithErrorsColumnsTests(unittest.TestCase):
    def test_item_13_select_with_two_columns_keeps_any_listed_error(self):
        source = f'Table.SelectRowsWithErrors({BASE}, {{"A","B"}})'
        self.assertEqual(evaluate_to_text(source), "UNREPRESENTABLE")
        self.assertEqual(_error_columns(source), {"A", "B"})

    def test_item_14_remove_with_two_columns(self):
        source = f'Table.RemoveRowsWithErrors({BASE}, {{"A","B"}})'
        self.assertEqual(
            evaluate_to_text(source),
            'V:table:cols=["A":"number","B":"number"];rows=[list:[number:3,number:4]]',
        )

    def test_item_15_select_without_columns_uses_all_columns(self):
        source = f'Table.SelectRowsWithErrors({BASE})'
        self.assertEqual(evaluate_to_text(source), "UNREPRESENTABLE")
        self.assertEqual(_error_columns(source), {"A", "B"})

    @pytest.mark.xfail(strict=True, reason="Task 212: try inside Table.TransformColumns must not catch cell errors (Power BI answer check 2026-11-17)")
    def test_item_23_select_then_try_per_cell(self):
        source = (
            f'let t = Table.SelectRowsWithErrors({BASE}, {{"A","B"}}) in '
            'Table.TransformColumns(t, {{"A", each try _ otherwise "ERR"},{"B", each try _ otherwise "ERR"}})'
        )
        self.assertEqual(evaluate_to_text(source), "UNREPRESENTABLE")

    @pytest.mark.xfail(strict=True, reason="Task 212: try inside Table.TransformColumns must not catch cell errors (Power BI answer check 2026-11-17)")
    def test_item_24_select_on_column_a_then_try_per_cell(self):
        source = (
            f'let t = Table.SelectRowsWithErrors({BASE}, {{"A"}}) in '
            'Table.TransformColumns(t, {{"A", each try _ otherwise "ERR"},{"B", each try _ otherwise "ERR"}})'
        )
        self.assertEqual(evaluate_to_text(source), "UNREPRESENTABLE")

    def test_item_27_select_two_columns_text_view(self):
        source = (
            f'let t = Table.SelectRowsWithErrors({BASE}, {{"A","B"}}) in '
            + TO_ROWS_AB.format(t="t")
        )
        self.assertEqual(
            evaluate_to_text(source),
            'V:list:[list:[text:"1",text:"ERR"],list:[text:"ERR",text:"2"]]',
        )

    def test_item_28_select_on_column_a_text_view(self):
        source = (
            f'let t = Table.SelectRowsWithErrors({BASE}, {{"A"}}) in '
            + TO_ROWS_AB.format(t="t")
        )
        self.assertEqual(evaluate_to_text(source), 'V:list:[list:[text:"ERR",text:"2"]]')

    def test_unknown_column_message_verbatim(self):
        source = f'Table.SelectRowsWithErrors({BASE}, {{"Zed"}})'
        self.assertEqual(
            evaluate_to_text(source),
            "ERR:Expression.Error: The column 'Zed' of the table wasn't found.",
        )

    def test_remove_unknown_column_message_verbatim(self):
        source = f'Table.RemoveRowsWithErrors({BASE}, {{"Zed"}})'
        self.assertEqual(
            evaluate_to_text(source),
            "ERR:Expression.Error: The column 'Zed' of the table wasn't found.",
        )

    def test_item_1_select_with_empty_list_keeps_no_rows(self):
        source = f'Table.RowCount(Table.SelectRowsWithErrors({BASE}, {{}}))'
        self.assertEqual(evaluate_to_text(source), "V:number:0")

    def test_item_1_remove_with_empty_list_keeps_all_rows(self):
        source = f'Table.RowCount(Table.RemoveRowsWithErrors({BASE}, {{}}))'
        self.assertEqual(evaluate_to_text(source), "V:number:3")

    def test_item_2_select_text_argument_is_refused(self):
        source = 'Table.SelectRowsWithErrors(#table({"A"},{{1}}), "A")'
        self.assertEqual(
            evaluate_to_text(source),
            'ERR:Expression.Error: We cannot convert the value "A" to type List.',
        )

    def test_item_2_remove_text_argument_is_refused(self):
        source = 'Table.RemoveRowsWithErrors(#table({"A"},{{1}}), "A")'
        self.assertEqual(
            evaluate_to_text(source),
            'ERR:Expression.Error: We cannot convert the value "A" to type List.',
        )


class AppEmptyColumnListTests(unittest.TestCase):
    """The app reads and writes the same meaning as Power BI: {} is no columns, an omitted list is all columns."""

    def _parse(self, op: str, arguments: str):
        from analytics_studio.power_query_m import parse_m_script, steps_to_m_script

        script = steps_to_m_script([{"op": op}], "Errors").replace("(Source)", f"(Source{arguments})")
        return parse_m_script(script, "Errors")

    def test_empty_list_parses_as_no_columns(self):
        self.assertEqual(self._parse("remove_rows_with_errors", ", {}"),
                         [{"op": "remove_rows_with_errors", "columns": []}])
        self.assertEqual(self._parse("keep_rows_with_errors", ", {}"),
                         [{"op": "keep_rows_with_errors", "columns": []}])

    def test_omitted_list_parses_as_all_columns(self):
        self.assertEqual(self._parse("remove_rows_with_errors", ""),
                         [{"op": "remove_rows_with_errors"}])

    def test_empty_list_step_emits_empty_braces(self):
        from analytics_studio.power_query_m import steps_to_m_script

        script = steps_to_m_script([{"op": "keep_rows_with_errors", "columns": []}], "Errors")
        self.assertIn("Table.SelectRowsWithErrors(Source, {})", script)

    def test_replay_empty_list_means_no_columns(self):
        from analytics_studio.file_import import ImportCandidate
        from analytics_studio.power_query_values import PowerQueryCellError
        from analytics_studio.transformations import apply_transformations

        error = PowerQueryCellError("DataFormat.Error", "bad value", "bad", "number", row=1)
        source = ImportCandidate("inline", ["A", "B"], [
            {"A": error, "B": "keep"},
            {"A": "keep", "B": error},
            {"A": "clean", "B": "clean"},
        ], {}, [])
        kept = apply_transformations(source, [{"op": "keep_rows_with_errors", "columns": []}])
        removed = apply_transformations(source, [{"op": "remove_rows_with_errors", "columns": []}])
        self.assertEqual(kept.rows, [])
        self.assertEqual(removed.rows, source.rows)


if __name__ == "__main__":
    unittest.main()
