"""Task 216: Group By writes the column types Power BI's dialog writes, and accepts typed scripts.

Answers 1-6 are Power BI Desktop 2.157.879.0's formula-bar text from the Group By dialog
(2026-11-17). Min, Max, Count Distinct Rows, All Rows and date/time/logical operations were
not observed, so they keep the untyped form.
"""

from __future__ import annotations

import unittest

from analytics_studio.m_engine import evaluate_to_text
from analytics_studio.power_query_m import (
    PowerQueryMScriptError,
    parse_m_script,
    steps_to_m_script,
)
from analytics_studio.transformations import TransformationError, validate_steps

QUERY = "Source Table"
SOURCE_TYPES = {
    "K": "text",
    "W": "whole_number",
    "N": "decimal_number",
    "C": "decimal_number",  # The app has no currency type; Currency.Type converts to decimal_number.
    "D": "date",
    "T": "text",
}
# Power BI's answers (Task 216), grouped by K.
ANSWERS = {
    1: 'Table.Group(Source, {"K"}, {{"Count", each Table.RowCount(_), Int64.Type}})',
    2: 'Table.Group(Source, {"K"}, {{"Count", each List.Sum([W]), type number}})',
    3: 'Table.Group(Source, {"K"}, {{"Count", each List.Average([W]), type number}})',
    4: 'Table.Group(Source, {"K"}, {{"Count", each List.Average([N]), type number}})',
    5: 'Table.Group(Source, {"K"}, {{"Count", each List.Median([C]), type number}})',
    6: 'Table.Group(Source, {"K"}, {{"Count", each List.Average([K]), type text}})',
}
# Power BI's six answers are written as a whole query with the step bound to "Grouped Rows".
SOURCE_EXPRESSION = (
    '#table({"K", "W", "N", "C"}, {{"a", 1, 1.5, 2.5}, {"a", 2, 2.5, 3.5}, {"b", 3, 4.5, 5.5}})'
)
TYPED_SOURCE_EXPRESSION = (
    "Table.TransformColumnTypes(" + SOURCE_EXPRESSION
    + ', {{"K", type text}, {"W", Int64.Type}, {"N", type number}, {"C", Currency.Type}})'
)


def full_script(group_expression: str) -> str:
    return "\n".join([
        "let",
        '    Source = #"Source Table",',
        f'    #"Grouped Rows" = {group_expression}',
        "in",
        '    #"Grouped Rows"',
    ])


def group_step(*aggregations: dict[str, str]) -> dict[str, object]:
    return {"op": "group_by", "columns": ["K"], "aggregations": list(aggregations)}


class GroupByEmitterTypeTests(unittest.TestCase):
    def emit(self, *aggregations: dict[str, str], types: dict[str, str] | None = SOURCE_TYPES) -> str:
        return steps_to_m_script(
            [group_step(*aggregations)], QUERY, initial_column_types=types,
        )

    def test_count_rows_emits_power_bi_answer_1(self) -> None:
        script = self.emit({"operation": "count_rows", "new_name": "Count"})
        self.assertEqual(script, full_script(ANSWERS[1]))

    def test_sum_average_median_emit_power_bi_answers_2_to_6(self) -> None:
        cases = {
            2: {"operation": "sum", "column": "W", "new_name": "Count"},
            3: {"operation": "average", "column": "W", "new_name": "Count"},
            4: {"operation": "average", "column": "N", "new_name": "Count"},
            5: {"operation": "median", "column": "C", "new_name": "Count"},
            6: {"operation": "average", "column": "K", "new_name": "Count"},
        }
        for number, aggregate in cases.items():
            with self.subTest(answer=number):
                self.assertEqual(self.emit(aggregate), full_script(ANSWERS[number]))

    def test_min_max_and_distinct_rows_keep_no_type(self) -> None:
        for aggregate in (
            {"operation": "min", "column": "W", "new_name": "Count"},
            {"operation": "max", "column": "W", "new_name": "Count"},
            {"operation": "count_distinct_rows", "new_name": "Count"},
        ):
            with self.subTest(operation=aggregate["operation"]):
                script = self.emit(aggregate)
                self.assertNotIn("type number", script)
                self.assertNotIn("type text", script)
                self.assertNotIn("Int64.Type", script)

    def test_unknown_source_type_emits_no_type(self) -> None:
        script = self.emit(
            {"operation": "sum", "column": "W", "new_name": "Count"},
            types=None,
        )
        self.assertIn('{"Count", each List.Sum([W])}', script)
        self.assertNotIn("type number", script)

    def test_unknown_column_type_emits_no_type(self) -> None:
        # Column Z is not in the known types, so no type argument is written.
        script = self.emit({"operation": "sum", "column": "Z", "new_name": "Count"})
        self.assertIn('{"Count", each List.Sum([Z])}', script)

    def test_date_source_emits_no_type_for_sum(self) -> None:
        script = self.emit({"operation": "sum", "column": "D", "new_name": "Count"})
        self.assertIn('{"Count", each List.Sum([D])}', script)
        self.assertNotIn("type number", script)

    def test_stored_m_type_is_written_exactly(self) -> None:
        script = self.emit({
            "operation": "min", "column": "W", "new_name": "Count", "m_type": "Int64.Type",
        })
        self.assertEqual(
            script,
            full_script('Table.Group(Source, {"K"}, {{"Count", each List.Min([W]), Int64.Type}})'),
        )


class GroupByRoundTripTests(unittest.TestCase):
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

    def test_parsed_power_bi_type_is_stored_verbatim(self) -> None:
        steps = parse_m_script(full_script(ANSWERS[2]), QUERY, initial_column_types=SOURCE_TYPES)
        self.assertEqual(steps[-1]["aggregations"][0]["m_type"], "type number")
        # Count Rows' Int64.Type is always emitted, so the parser does not store it (Task 216).
        steps = parse_m_script(full_script(ANSWERS[1]), QUERY, initial_column_types=SOURCE_TYPES)
        self.assertNotIn("m_type", steps[-1]["aggregations"][0])

    def test_accepted_type_forms_parse_and_round_trip(self) -> None:
        for m_type in (
            "Int64.Type", "type number", "type nullable number", "type text",
            "type nullable text", "Number.Type", "Text.Type", "Currency.Type", "type any",
        ):
            with self.subTest(m_type=m_type):
                script = full_script(
                    f'Table.Group(Source, {{"K"}}, {{{{"Count", each List.Sum([W]), {m_type}}}}})'
                )
                steps = parse_m_script(script, QUERY, initial_column_types=SOURCE_TYPES)
                self.assertEqual(steps[-1]["aggregations"][0]["m_type"], m_type)
                self.assertEqual(
                    steps_to_m_script(steps, QUERY, initial_column_types=SOURCE_TYPES),
                    script,
                )

    def test_unsupported_type_form_is_rejected(self) -> None:
        script = full_script(
            'Table.Group(Source, {"K"}, {{"Count", each List.Sum([W]), type date}})'
        )
        with self.assertRaisesRegex(PowerQueryMScriptError, "outside the supported local subset"):
            parse_m_script(script, QUERY, initial_column_types=SOURCE_TYPES)

    def test_validate_steps_accepts_m_type_and_rejects_unknown(self) -> None:
        valid = group_step({"operation": "sum", "column": "W", "new_name": "Count", "m_type": "type number"})
        self.assertEqual(validate_steps([valid])[0]["aggregations"][0]["m_type"], "type number")
        invalid = group_step({"operation": "sum", "column": "W", "new_name": "Count", "m_type": "type date"})
        with self.assertRaises(TransformationError):
            validate_steps([invalid])

    def test_steps_without_m_type_still_validate(self) -> None:
        # Projects saved before Task 216 have no m_type key and need no migration.
        legacy = group_step({"operation": "sum", "column": "W", "new_name": "Count"})
        self.assertNotIn("m_type", validate_steps([legacy])[0]["aggregations"][0])


class GroupByEvaluationTests(unittest.TestCase):
    def evaluate_schema(self, group_expression: str) -> str:
        return evaluate_to_text(
            f"Table.Schema(Table.Group({TYPED_SOURCE_EXPRESSION}, {{\"K\"}}, {{{group_expression}}}))"
            "[[Name],[Kind]]"
        )

    def test_answer_1_count_column_evaluates_as_number(self) -> None:
        text = self.evaluate_schema('{"Count", each Table.RowCount(_), Int64.Type}')
        self.assertTrue(text.startswith("V:table:"), text)
        self.assertIn('list:[text:"Count",text:"number"]', text)

    def test_answer_2_sum_column_evaluates_as_number(self) -> None:
        text = self.evaluate_schema('{"Count", each List.Sum([W]), type number}')
        self.assertTrue(text.startswith("V:table:"), text)
        self.assertIn('list:[text:"Count",text:"number"]', text)

    def test_answer_6_average_of_text_evaluates(self) -> None:
        text = self.evaluate_schema('{"Count", each List.Average([K]), type text}')
        self.assertTrue(text.startswith("V:table:"), text)

    def test_all_power_bi_answers_evaluate_to_values(self) -> None:
        # Answers 1-5 evaluate to a table. Answer 6 (average of text) has no Power BI result to
        # compare with; the engine gives the same answer with or without the type argument.
        for number, expression in ANSWERS.items():
            with self.subTest(answer=number):
                source_query = expression.replace("Source", TYPED_SOURCE_EXPRESSION, 1)
                text = evaluate_to_text(source_query)
                self.assertNotIn("ERR:SYNTAX", text)
                if number == 6:
                    untyped = expression.replace(", type text}}", "}}").replace("Source", TYPED_SOURCE_EXPRESSION, 1)
                    self.assertEqual(text, evaluate_to_text(untyped))
                else:
                    self.assertTrue(text.startswith("V:table:"), text)


if __name__ == "__main__":
    unittest.main()
