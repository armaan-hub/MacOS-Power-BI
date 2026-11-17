"""Task 216 round 4: Power BI's typed Table.Group form is accepted as an editor step."""

from __future__ import annotations

import unittest

from analytics_studio.power_query_m import parse_m_script, steps_to_m_script

QUERY = "Sales"
TYPES = {"Region": "text", "Units": "whole_number"}
TYPED_GROUP_LINE = (
    'Table.Group(Source, {"Region"}, {{"Total", each List.Sum([Units]), type number}, '
    '{"Rows", each Table.RowCount(_), Int64.Type}})'
)
TYPED_SCRIPT = "\n".join([
    "let",
    '    Source = #"Sales",',
    f"    Grouped = {TYPED_GROUP_LINE}",
    "in",
    "    Grouped",
])


class TypedGroupByEditorStepTests(unittest.TestCase):
    # Task 216: Power BI's typed Group By form is now an editor step
    def test_typed_group_script_parses_into_one_group_step_with_stored_types(self) -> None:
        steps = parse_m_script(TYPED_SCRIPT, QUERY, initial_column_types=TYPES)
        self.assertEqual(len(steps), 1)
        step = steps[0]
        self.assertEqual(step["op"], "group_by")
        self.assertEqual(step["columns"], ["Region"])
        self.assertEqual(len(step["aggregations"]), 2)
        total, rows = step["aggregations"]
        self.assertEqual(total, {
            "operation": "sum", "column": "Units", "new_name": "Total", "m_type": "type number",
        })
        # Count Rows' Int64.Type is always written by the emitter, so it is not stored.
        self.assertEqual(rows, {"operation": "count_rows", "new_name": "Rows"})

    def test_steps_re_emit_the_typed_table_group_line_exactly(self) -> None:
        steps = parse_m_script(TYPED_SCRIPT, QUERY, initial_column_types=TYPES)
        script = steps_to_m_script(steps, QUERY, initial_column_types=TYPES, step_names=["Grouped"])
        self.assertIn(TYPED_GROUP_LINE, script)

    def test_full_script_differs_only_in_the_quoted_step_name(self) -> None:
        # The emitter quotes every step name (#"Grouped"); the typed input wrote it as a plain name.
        steps = parse_m_script(TYPED_SCRIPT, QUERY, initial_column_types=TYPES)
        script = steps_to_m_script(steps, QUERY, initial_column_types=TYPES, step_names=["Grouped"])
        expected = TYPED_SCRIPT.replace("    Grouped = ", '    #"Grouped" = ').replace("in\n    Grouped", 'in\n    #"Grouped"')
        self.assertEqual(script, expected)


if __name__ == "__main__":
    unittest.main()
