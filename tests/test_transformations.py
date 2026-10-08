"""Focused contract tests for replayable local table transformations."""

from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import patch

from analytics_studio.file_import import ImportCandidate
from analytics_studio.transformations import TransformationError, apply_transformations


def candidate() -> ImportCandidate:
    return ImportCandidate(
        "csv",
        ["Name", "Amount", "Active", "Date", "Group"],
        [
            {"Name": "alpha", "Amount": "10", "Active": "TRUE", "Date": "2024-01-02", "Group": "x"},
            {"Name": "beta", "Amount": "2.50", "Active": "false", "Date": "2024-01-01", "Group": "y"},
            {"Name": "gamma", "Amount": "20", "Active": "yes", "Date": "2024-01-03", "Group": "x"},
        ],
        {"encoding": "utf-8"},
        ["source notice"],
    )


class TransformationTests(unittest.TestCase):
    def test_ordered_steps_rename_convert_filter_and_sort(self) -> None:
        source = candidate()

        result = apply_transformations(source, [
            {"op": "rename_column", "column": "Amount", "new_name": "Revenue"},
            {"op": "convert_type", "column": "Revenue", "type": "number"},
            {"op": "filter_rows", "column": "Revenue", "operator": "greater_than", "value": "2.5"},
            {"op": "sort_rows", "column": "Revenue", "direction": "desc"},
        ])

        self.assertEqual(result.headers, ["Name", "Revenue", "Active", "Date", "Group"])
        self.assertEqual([row["Name"] for row in result.rows], ["gamma", "alpha"])
        self.assertEqual(result.rows[1]["Revenue"], "10")
        self.assertEqual(result.options, source.options)
        self.assertEqual(result.notices, source.notices)
        self.assertIsNot(result, source)

    def test_remove_column_and_all_filter_operators(self) -> None:
        source = candidate()
        contains = apply_transformations(source, [
            {"op": "filter_rows", "column": "Name", "operator": "contains", "value": "a"},
            {"op": "remove_column", "column": "Group"},
        ])
        equals = apply_transformations(source, [
            {"op": "filter_rows", "column": "Group", "operator": "equals", "value": "x"},
        ])
        not_equals = apply_transformations(source, [
            {"op": "filter_rows", "column": "Group", "operator": "not_equals", "value": "x"},
        ])
        less_than = apply_transformations(source, [
            {"op": "filter_rows", "column": "Amount", "operator": "less_than", "value": "10"},
        ])

        self.assertEqual([row["Name"] for row in contains.rows], ["alpha", "beta", "gamma"])
        self.assertNotIn("Group", contains.headers)
        self.assertEqual([row["Name"] for row in equals.rows], ["alpha", "gamma"])
        self.assertEqual([row["Name"] for row in not_equals.rows], ["beta"])
        self.assertEqual([row["Name"] for row in less_than.rows], ["beta"])

    def test_convert_supported_types_and_keep_empty_cells_empty(self) -> None:
        source = candidate()
        source.rows[0]["Active"] = " true "
        source.rows[2]["Active"] = "TRUE"
        source.rows[1]["Date"] = ""

        result = apply_transformations(source, [
            {"op": "convert_type", "column": "Name", "type": "text"},
            {"op": "convert_type", "column": "Active", "type": "boolean"},
            {"op": "convert_type", "column": "Date", "type": "date"},
        ])

        self.assertEqual([row["Active"] for row in result.rows], ["true", "false", "true"])
        self.assertEqual(result.rows[0]["Date"], "2024-01-02")
        self.assertEqual(result.rows[1]["Date"], "")

    def test_input_candidate_is_not_mutated_and_nested_metadata_is_copied(self) -> None:
        source = candidate()
        source.options["nested"] = {"flag": [1]}
        original = copy.deepcopy(source)

        result = apply_transformations(source, [
            {"op": "rename_column", "column": "Name", "new_name": "Label"},
        ])
        result.options["nested"]["flag"].append(2)
        result.notices.append("later")

        self.assertEqual(source, original)
        self.assertEqual(source.options["nested"], {"flag": [1]})
        self.assertEqual(source.notices, ["source notice"])

    def test_steps_are_json_serializable_and_malformed_shapes_are_rejected(self) -> None:
        steps = [{"op": "filter_rows", "column": "Name", "operator": "equals", "value": "alpha"}]
        self.assertEqual(json.loads(json.dumps(steps)), steps)
        bad_steps = (
            None,
            (),
            [{"op": "unknown"}],
            [{"op": "rename_column", "column": "Name", "new_name": "Label", "extra": True}],
            [{"op": "rename_column", "column": "Name", "new_name": " "}],
            [{"op": "filter_rows", "column": "Name", "operator": "regex", "value": ".*"}],
            [{"op": "sort_rows", "column": "Name", "direction": "up"}],
            [{"op": "convert_type", "column": "Name", "type": "integer"}],
            [{"op": "filter_rows", "column": "Name", "operator": "equals", "value": 1}],
        )
        for steps_value in bad_steps:
            with self.subTest(steps=steps_value), self.assertRaises(TransformationError):
                apply_transformations(candidate(), steps_value)

    def test_missing_columns_collisions_and_last_column_removal_are_rejected(self) -> None:
        for step in (
            {"op": "remove_column", "column": "Missing"},
            {"op": "rename_column", "column": "Missing", "new_name": "Other"},
            {"op": "rename_column", "column": "Name", "new_name": "Amount"},
            {"op": "sort_rows", "column": "Missing", "direction": "asc"},
        ):
            with self.subTest(step=step), self.assertRaises(TransformationError):
                apply_transformations(candidate(), [step])

        one_column = ImportCandidate("csv", ["Only"], [{"Only": "x"}], {}, [])
        with self.assertRaisesRegex(TransformationError, "last column"):
            apply_transformations(one_column, [{"op": "remove_column", "column": "Only"}])

    def test_invalid_conversion_and_numeric_filter_report_stable_row_and_column(self) -> None:
        source = candidate()
        with self.assertRaisesRegex(TransformationError, r"row 3.*Active.*boolean"):
            apply_transformations(source, [
                {"op": "convert_type", "column": "Active", "type": "boolean"},
            ])

        source.rows[2]["Amount"] = "not a number"
        with self.assertRaisesRegex(TransformationError, r"row 3.*Amount.*number"):
            apply_transformations(source, [
                {"op": "filter_rows", "column": "Amount", "operator": "greater_than", "value": "1"},
            ])

    def test_transformation_failure_does_not_change_input(self) -> None:
        source = candidate()
        original = copy.deepcopy(source)
        with self.assertRaises(TransformationError):
            apply_transformations(source, [
                {"op": "rename_column", "column": "Name", "new_name": "Label"},
                {"op": "convert_type", "column": "Active", "type": "boolean"},
            ])
        self.assertEqual(source, original)

    def test_candidate_limits_match_the_importer_caps(self) -> None:
        with patch("analytics_studio.transformations.MAX_DATA_ROWS", 2):
            with self.assertRaisesRegex(TransformationError, "2-row import limit"):
                apply_transformations(candidate(), [])

    def test_replace_trim_remove_duplicates_and_keep_columns_compose_in_order(self) -> None:
        source = ImportCandidate(
            "csv",
            ["Name", "Group", "Note"],
            [
                {"Name": " Ada ", "Group": "East", "Note": "old"},
                {"Name": "Ada", "Group": "East", "Note": "old"},
                {"Name": " Lin ", "Group": "West", "Note": "old"},
            ],
            {},
            [],
        )

        result = apply_transformations(source, [
            {"op": "trim_text", "column": "Name"},
            {"op": "replace_value", "column": "Note", "value": "old", "replacement": "new"},
            {"op": "remove_duplicates"},
            {"op": "keep_columns", "columns": ["Name", "Note"]},
        ])

        self.assertEqual(result.headers, ["Name", "Note"])
        self.assertEqual(result.rows, [
            {"Name": "Ada", "Note": "new"},
            {"Name": "Lin", "Note": "new"},
        ])
        self.assertEqual(source.rows[0]["Name"], " Ada ")

    def test_new_step_shapes_are_strict_and_missing_kept_columns_fail_on_replay(self) -> None:
        malformed = (
            {"op": "replace_value", "column": "Name", "value": "a"},
            {"op": "replace_value", "column": "Name", "value": "a", "replacement": "b", "extra": "x"},
            {"op": "trim_text", "column": " "},
            {"op": "keep_columns", "columns": []},
            {"op": "keep_columns", "columns": ["Name", "Name"]},
            {"op": "keep_columns", "columns": ["Name", 4]},
            {"op": "remove_duplicates", "columns": []},
        )
        for step in malformed:
            with self.subTest(step=step), self.assertRaises(TransformationError):
                apply_transformations(candidate(), [step])

        with self.assertRaisesRegex(TransformationError, "Missing.*does not exist"):
            apply_transformations(candidate(), [
                {"op": "keep_columns", "columns": ["Name", "Missing"]},
            ])


if __name__ == "__main__":
    unittest.main()
