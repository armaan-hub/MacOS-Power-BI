"""Task 215b: Pivot with "Don't aggregate" keeps repeated row-key/category pairs as error cells.

Power BI answers (headless M answer check, 2026-11-17): Table.Pivot succeeds and the repeated
pair becomes an Expression.Error cell with the message below; the other pairs are unaffected.
"""

from __future__ import annotations

import re
import unittest

from analytics_studio.file_import import ImportCandidate
from analytics_studio.m_engine import evaluate_to_text
from analytics_studio.power_query_m import parse_m_script, steps_to_m_script
from analytics_studio.power_query_values import PowerQueryCellError, is_cell_error
from analytics_studio.transformations import apply_transformations

PIVOT_MESSAGE = "There were too many elements in the enumeration to complete the operation."

NO_AGGREGATION_PIVOT = {
    "op": "pivot_column",
    "attribute_column": "A",
    "value_column": "V",
    "aggregation": "none",
}

# Power BI's saved answer for the item-0 probe (pivot, then an error-capturing column "e",
# then the x column removed). Its text is the reference for the M the app emits.
POWER_BI_ITEM0_ANSWER = (
    'V:table:cols=["K":"any","y":"any","e":"any"];rows=[list:[number:1,null,'
    'text:"Expression.Error|There were too many elements in the enumeration to complete the operation."],'
    "list:[number:2,number:5,null]]"
)


def _source(rows: list[dict[str, object]]) -> ImportCandidate:
    return ImportCandidate("inline", ["K", "A", "V"], rows, {}, [])


def _probe_rows() -> list[dict[str, object]]:
    return [
        {"K": 1, "A": "x", "V": 10},
        {"K": 1, "A": "x", "V": 20},
        {"K": 2, "A": "y", "V": 5},
    ]


class PivotNoAggregationErrorCellsTests(unittest.TestCase):
    def test_repeated_pair_becomes_error_cell_and_other_pairs_survive(self) -> None:
        result = apply_transformations(_source(_probe_rows()), [NO_AGGREGATION_PIVOT])

        self.assertEqual(result.headers, ["K", "x", "y"])
        self.assertEqual(len(result.rows), 2)
        first, second = result.rows
        self.assertEqual(first["K"], 1)
        cell = first["x"]
        self.assertIsInstance(cell, PowerQueryCellError)
        self.assertTrue(is_cell_error(cell))
        self.assertEqual(cell.reason, "Expression.Error")
        self.assertEqual(cell.message, PIVOT_MESSAGE)
        self.assertIsNone(first["y"])
        self.assertEqual(second["K"], 2)
        self.assertIsNone(second["x"])
        self.assertEqual(second["y"], 5)

    def test_error_cell_carries_source_rows_of_the_repeated_members(self) -> None:
        result = apply_transformations(_source(_probe_rows()), [NO_AGGREGATION_PIVOT])
        cell = result.rows[0]["x"]
        self.assertIsNone(cell.row)
        self.assertEqual(
            sorted(index for _, index in cell.source_rows),
            [1, 2],
        )

    def test_double_repeat_makes_both_cells_error_cells(self) -> None:
        rows = [
            {"K": 1, "A": "x", "V": 10},
            {"K": 1, "A": "x", "V": 20},
            {"K": 1, "A": "y", "V": 7},
            {"K": 1, "A": "y", "V": 8},
            {"K": 2, "A": "y", "V": 5},
        ]
        result = apply_transformations(_source(rows), [NO_AGGREGATION_PIVOT])

        self.assertEqual(len(result.rows), 2)
        first = result.rows[0]
        self.assertTrue(is_cell_error(first["x"]))
        self.assertTrue(is_cell_error(first["y"]))
        self.assertEqual(first["x"].message, PIVOT_MESSAGE)
        self.assertEqual(first["y"].message, PIVOT_MESSAGE)
        self.assertIsNone(result.rows[1]["x"])
        self.assertEqual(result.rows[1]["y"], 5)

    def test_remove_errors_after_pivot_leaves_only_the_clean_row(self) -> None:
        steps = [
            NO_AGGREGATION_PIVOT,
            {"op": "remove_rows_with_errors"},
        ]
        result = apply_transformations(_source(_probe_rows()), steps)

        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["K"], 2)
        self.assertIsNone(result.rows[0]["x"])
        self.assertEqual(result.rows[0]["y"], 5)

    def test_pivot_step_survives_save_and_reopen_text(self) -> None:
        script = steps_to_m_script([NO_AGGREGATION_PIVOT], "Sales Data")
        self.assertEqual(parse_m_script(script, "Sales Data"), [NO_AGGREGATION_PIVOT])


class PivotNoAggregationM215bTests(unittest.TestCase):
    """The M the app emits for the step, evaluated by the M engine, matches Power BI's answer."""

    def test_emitted_pivot_m_matches_power_bi_item0_answer(self) -> None:
        script = steps_to_m_script([NO_AGGREGATION_PIVOT], "Sales Data")
        pivot_line = re.search(r"Table\.Pivot\([^\n]*\)", script)
        self.assertIsNotNone(pivot_line, script)
        pivot_expr = pivot_line.group(0)
        # Replace the workbook source with the same literal table Power BI's probe used.
        expression = (
            'let Source = #table({"K","A","V"},{{1,"x",10},{1,"x",20},{2,"y",5}}), '
            f"p = {pivot_expr}, "
            'q = Table.AddColumn(p, "e", each let r = try [x] in if r[HasError] then '
            'r[Error][Reason] & "|" & r[Error][Message] else Text.From(r[Value])) '
            'in Table.RemoveColumns(q, {"x"})'
        )
        self.assertEqual(evaluate_to_text(expression), POWER_BI_ITEM0_ANSWER)

    def test_emitted_pivot_m_after_dropping_x_column_is_cell_by_cell_equal(self) -> None:
        script = steps_to_m_script([NO_AGGREGATION_PIVOT], "Sales Data")
        pivot_expr = re.search(r"Table\.Pivot\([^\n]*\)", script).group(0)
        expression = (
            'let Source = #table({"K","A","V"},{{1,"x",10},{1,"x",20},{2,"y",5}}), '
            f"p = {pivot_expr} "
            'in Table.RemoveColumns(p, {"x"})'
        )
        text = evaluate_to_text(expression)
        self.assertTrue(text.startswith("V:table:"), text)
        self.assertIn("list:[number:1,null]", text)
        self.assertIn("list:[number:2,number:5]", text)


if __name__ == "__main__":
    unittest.main()
