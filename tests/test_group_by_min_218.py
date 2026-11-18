"""Task 218: Group By "Min" writes the column type Power BI's dialog writes for text and decimal columns.

Power BI Desktop 2.157.879.0's formula-bar text from the Group By dialog (2026-11-18),
grouped by T, column name "Count":
1. Min of K (text):     Table.Group(Source, {"T"}, {{"Count", each List.Min([K]), type text}})
2. Min of C (Currency): Table.Group(Source, {"T"}, {{"Count", each List.Min([C]), type number}})
Min of whole number/date and Max of any column were not observed, so they keep the
untyped form.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from analytics_studio.power_query_m import parse_m_script, steps_to_m_script

QUERY = "Source Table"
SOURCE_TYPES = {
    "K": "text",
    "W": "whole_number",
    "N": "decimal_number",
    "C": "decimal_number",  # The app has no currency type; Currency.Type converts to decimal_number.
    "D": "date",
    "T": "text",
}
# Power BI's answers (Task 218), grouped by T.
ANSWERS = {
    1: 'Table.Group(Source, {"T"}, {{"Count", each List.Min([K]), type text}})',
    2: 'Table.Group(Source, {"T"}, {{"Count", each List.Min([C]), type number}})',
}


def full_script(group_expression: str) -> str:
    return "\n".join([
        "let",
        '    Source = #"Source Table",',
        f'    #"Grouped Rows" = {group_expression}',
        "in",
        '    #"Grouped Rows"',
    ])


def group_step(*aggregations: dict[str, str]) -> dict[str, object]:
    return {"op": "group_by", "columns": ["T"], "aggregations": list(aggregations)}


class GroupByMinTypeTests(unittest.TestCase):
    def emit(self, *aggregations: dict[str, str], types: dict[str, str] | None = SOURCE_TYPES) -> str:
        return steps_to_m_script(
            [group_step(*aggregations)], QUERY, initial_column_types=types,
        )

    def test_min_of_text_emits_power_bi_answer_1(self) -> None:
        script = self.emit({"operation": "min", "column": "K", "new_name": "Count"})
        self.assertEqual(script, full_script(ANSWERS[1]))

    def test_min_of_decimal_emits_power_bi_answer_2(self) -> None:
        script = self.emit({"operation": "min", "column": "C", "new_name": "Count"})
        self.assertEqual(script, full_script(ANSWERS[2]))

    def test_unobserved_min_and_max_stay_untyped(self) -> None:
        for aggregate in (
            {"operation": "min", "column": "W", "new_name": "Count"},
            {"operation": "min", "column": "D", "new_name": "Count"},
            {"operation": "max", "column": "K", "new_name": "Count"},
            {"operation": "max", "column": "C", "new_name": "Count"},
        ):
            with self.subTest(operation=aggregate["operation"], column=aggregate["column"]):
                script = self.emit(aggregate)
                self.assertNotIn("type number", script)
                self.assertNotIn("type text", script)
                self.assertNotIn("Int64.Type", script)


class GroupByMinRoundTripTests(unittest.TestCase):
    def test_each_power_bi_answer_parses_and_re_emits_the_same_text(self) -> None:
        for number, expression in ANSWERS.items():
            with self.subTest(answer=number):
                script = full_script(expression)
                steps = parse_m_script(script, QUERY, initial_column_types=SOURCE_TYPES)
                self.assertEqual(steps[-1]["op"], "group_by")
                re_emitted = steps_to_m_script(
                    steps, QUERY, initial_column_types=SOURCE_TYPES,
                )
                self.assertEqual(re_emitted, script)


if __name__ == "__main__":
    unittest.main()
