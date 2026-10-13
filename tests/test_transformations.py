"""Focused contract tests for replayable local table transformations."""

from __future__ import annotations

import copy
import json
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from analytics_studio.file_import import ImportCandidate
from analytics_studio.power_query_values import PowerQueryCellError, is_cell_error
from analytics_studio.transformations import (
    TransformationError,
    apply_transformations,
    column_types_after_steps,
    count_conversion_errors,
    infer_column_types,
)


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
    def test_type_detection_is_conservative_and_preserves_identifier_text(self) -> None:
        headers = ["Date", "Amount", "Units", "TRN", "Voucher No.", "Active", "Mixed"]
        rows = [
            {
                "Date": "2026-08-01",
                "Amount": "4500.50",
                "Units": "75",
                "TRN": "100233708500003",
                "Voucher No.": "000123",
                "Active": "true",
                "Mixed": "12",
            },
            {
                "Date": "2026-08-02",
                "Amount": "1150",
                "Units": "100",
                "TRN": "100108694000003",
                "Voucher No.": "000124",
                "Active": "FALSE",
                "Mixed": "unknown",
            },
        ]

        self.assertEqual(infer_column_types(headers, rows), {
            "Date": "date",
            "Amount": "decimal_number",
            "Units": "whole_number",
            "TRN": "text",
            "Voucher No.": "text",
            "Active": "boolean",
            "Mixed": "text",
        })

    def test_type_detection_uses_sample_but_checks_every_row(self) -> None:
        headers = ["Amount"]
        rows = [{"Amount": "10"}, {"Amount": "not numeric"}]

        self.assertEqual(
            infer_column_types(headers, rows, sample_size=1),
            {"Amount": "text"},
        )

    def test_type_detection_does_not_infer_integer_amounts_as_time(self) -> None:
        rows = [
            {"Amount": "10", "Units": "2", "Time": "10:00:00"},
            {"Amount": "20", "Units": "3", "Time": "11:30:00"},
        ]

        self.assertEqual(
            infer_column_types(["Amount", "Units", "Time"], rows),
            {
                "Amount": "whole_number",
                "Units": "whole_number",
                "Time": "time",
            },
        )

    def test_type_detection_does_not_round_late_fractions_or_strip_late_zeroes(self) -> None:
        rows = [
            {"Metric": str(index), "Key": str(10_000 + index)}
            for index in range(200)
        ]
        rows.append({"Metric": "12.5", "Key": "00123"})

        self.assertEqual(
            infer_column_types(["Metric", "Key"], rows),
            {"Metric": "decimal_number", "Key": "text"},
        )

    def test_type_detection_keeps_whitespace_only_values_as_text(self) -> None:
        self.assertEqual(
            infer_column_types(["Amount"], [{"Amount": "12"}, {"Amount": " "}]),
            {"Amount": "text"},
        )
        self.assertEqual(
            infer_column_types(
                ["Flag"], [{"Flag": "true"}, {"Flag": " "}], sample_size=1
            ),
            {"Flag": "text"},
        )

    def test_conversion_quality_does_not_count_null_or_empty_as_errors(self) -> None:
        self.assertEqual(
            count_conversion_errors([None, "", "12", " "], "whole_number"),
            1,
        )

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
        self.assertEqual(result.rows[1]["Revenue"], Decimal("10"))
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

    def test_convert_supported_types_keeps_null_and_turns_empty_text_into_error(self) -> None:
        source = candidate()
        source.rows[0]["Active"] = " true "
        source.rows[2]["Active"] = "TRUE"
        source.rows[1]["Date"] = ""

        result = apply_transformations(source, [
            {"op": "convert_type", "column": "Name", "type": "text"},
            {"op": "convert_type", "column": "Active", "type": "boolean"},
            {"op": "convert_type", "column": "Date", "type": "date"},
        ])

        self.assertEqual([row["Active"] for row in result.rows], [True, False, True])
        self.assertEqual(result.rows[0]["Date"], date(2024, 1, 2))
        self.assertIsInstance(result.rows[1]["Date"], PowerQueryCellError)
        self.assertEqual(result.rows[1]["Date"].value, "")

    def test_null_empty_native_values_and_conversion_errors_remain_distinct(self) -> None:
        source = ImportCandidate("inline", ["Value"], [
            {"Value": 12},
            {"Value": "12"},
            {"Value": None},
            {"Value": ""},
            {"Value": "bad"},
        ], {}, [])

        result = apply_transformations(source, [{
            "op": "convert_type", "column": "Value", "type": "decimal_number",
        }])

        self.assertEqual(result.rows[0]["Value"], Decimal(12))
        self.assertEqual(result.rows[1]["Value"], Decimal(12))
        self.assertIsNone(result.rows[2]["Value"])
        self.assertIsInstance(result.rows[3]["Value"], PowerQueryCellError)
        self.assertEqual(result.rows[3]["Value"].value, "")
        self.assertIsInstance(result.rows[4]["Value"], PowerQueryCellError)

    def test_split_column_preserves_null_and_error_in_both_outputs(self) -> None:
        error = PowerQueryCellError("DataFormat.Error", "bad text", "bad", "text", row=2)
        source = ImportCandidate("inline", ["Value"], [
            {"Value": None}, {"Value": error}, {"Value": "left:right"},
        ], {}, [])

        result = apply_transformations(source, [{
            "op": "split_column", "column": "Value", "delimiter": ":",
        }])

        self.assertEqual(result.rows[0], {"Value.1": None, "Value.2": None})
        self.assertEqual(result.rows[1]["Value.1"], error)
        self.assertEqual(result.rows[1]["Value.2"], error)
        self.assertEqual(result.rows[2], {"Value.1": "left", "Value.2": "right"})

    def test_group_and_pivot_reject_error_keys_and_typed_category_collisions(self) -> None:
        error = PowerQueryCellError("DataFormat.Error", "bad key", "bad", "text", row=2)
        group_source = ImportCandidate("inline", ["Key", "Amount"], [
            {"Key": "ok", "Amount": 1}, {"Key": error, "Amount": 2},
        ], {}, [])
        pivot_source = ImportCandidate("inline", ["Key", "Attribute", "Value"], [
            {"Key": "x", "Attribute": 1, "Value": 10},
            {"Key": "x", "Attribute": "1", "Value": 20},
        ], {}, [])
        pivot_error_source = ImportCandidate("inline", ["Key", "Attribute", "Value"], [
            {"Key": "x", "Attribute": error, "Value": 10},
        ], {}, [])

        with self.assertRaisesRegex(TransformationError, "group key.*error"):
            apply_transformations(group_source, [{
                "op": "group_by", "columns": ["Key"], "aggregations": [
                    {"operation": "sum", "column": "Amount", "new_name": "Total"},
                ],
            }])
        for source in (pivot_source, pivot_error_source):
            with self.subTest(source=source):
                with self.assertRaisesRegex(TransformationError, "pivot.*(typed|error)"):
                    apply_transformations(source, [{
                        "op": "pivot_column", "attribute_column": "Attribute",
                        "value_column": "Value", "aggregation": "sum",
                    }])

    def test_fill_down_fills_null_but_preserves_empty_text(self) -> None:
        source = ImportCandidate("inline", ["Value"], [
            {"Value": "North"},
            {"Value": None},
            {"Value": ""},
            {"Value": "South"},
            {"Value": None},
        ], {}, [])

        result = apply_transformations(source, [{
            "op": "fill_down", "columns": ["Value"],
        }])

        self.assertEqual([row["Value"] for row in result.rows], [
            "North", "North", "", "South", "South",
        ])

    def test_null_filters_distinguish_null_from_empty_and_blank_filters(self) -> None:
        source = ImportCandidate("inline", ["Value"], [
            {"Value": None}, {"Value": ""}, {"Value": "x"},
        ], {}, [])

        is_null = apply_transformations(source, [{
            "op": "filter_rows", "column": "Value", "operator": "is_null", "value": "",
        }])
        is_not_null = apply_transformations(source, [{
            "op": "filter_rows", "column": "Value", "operator": "is_not_null", "value": "",
        }])
        is_blank = apply_transformations(source, [{
            "op": "filter_rows", "column": "Value", "operator": "is_blank", "value": "",
        }])
        is_not_blank = apply_transformations(source, [{
            "op": "filter_rows", "column": "Value", "operator": "is_not_blank", "value": "",
        }])

        self.assertEqual(is_null.rows, [{"Value": None}])
        self.assertEqual(is_not_null.rows, [{"Value": ""}, {"Value": "x"}])
        self.assertEqual(is_blank.rows, [{"Value": None}, {"Value": ""}])
        self.assertEqual(is_not_blank.rows, [{"Value": "x"}])

    def test_unpivot_omits_nulls_but_keeps_empty_text(self) -> None:
        source = ImportCandidate("inline", ["Key", "A", "B"], [
            {"Key": "first", "A": None, "B": ""},
            {"Key": "second", "A": "x", "B": None},
        ], {}, [])

        result = apply_transformations(source, [{
            "op": "unpivot_columns", "columns": ["A", "B"],
            "attribute_name": "Attribute", "value_name": "Value",
        }])

        self.assertEqual(result.rows, [
            {"Key": "first", "Attribute": "B", "Value": ""},
            {"Key": "second", "Attribute": "A", "Value": "x"},
        ])

    def test_unpivot_keeps_homogeneous_value_column_type(self) -> None:
        step = {
            "op": "unpivot_columns", "columns": ["Q1", "Q2"],
            "attribute_name": "Field", "value_name": "Amount",
        }

        self.assertEqual(
            column_types_after_steps(
                ["Region", "Q1", "Q2"], [step],
                initial_types={
                    "Region": "text", "Q1": "decimal_number", "Q2": "decimal_number",
                },
            ),
            {"Region": "text", "Field": "text", "Amount": "decimal_number"},
        )

    def test_unpivot_preserves_mixed_native_values_and_reports_any_type(self) -> None:
        source = ImportCandidate("inline", ["Key", "Amount", "Note"], [
            {"Key": "A", "Amount": "1.25", "Note": "cash"},
            {"Key": "B", "Amount": None, "Note": ""},
        ], {}, [])
        steps = [
            {"op": "convert_type", "column": "Amount", "type": "decimal_number"},
            {"op": "convert_type", "column": "Note", "type": "text"},
            {
                "op": "unpivot_columns", "columns": ["Amount", "Note"],
                "attribute_name": "Field", "value_name": "Value",
            },
        ]

        result = apply_transformations(source, steps)
        types = column_types_after_steps(
            source.headers, steps,
            initial_types={"Key": "text", "Amount": "text", "Note": "text"},
        )

        self.assertEqual(types["Value"], "any")
        self.assertEqual(result.rows, [
            {"Key": "A", "Field": "Amount", "Value": Decimal("1.25")},
            {"Key": "A", "Field": "Note", "Value": "cash"},
            {"Key": "B", "Field": "Note", "Value": ""},
        ])

    def test_custom_column_cell_errors_follow_evaluated_branches_only(self) -> None:
        source = ImportCandidate("inline", ["UseFault", "Fault", "Value"], [
            {
                "UseFault": "false",
                "Fault": PowerQueryCellError("DataFormat.Error", "bad source value"),
                "Value": "safe",
            },
            {
                "UseFault": "true",
                "Fault": PowerQueryCellError("DataFormat.Error", "bad source value"),
                "Value": "safe",
            },
        ], {"source_id": "source-1"}, [])

        result = apply_transformations(source, [
            {
                "op": "add_custom_column",
                "name": "Selected",
                "expression": 'if [UseFault] = "true" then [Fault] else [Value]',
            },
        ])

        self.assertEqual(result.rows[0]["Selected"], "safe")
        self.assertEqual(result.rows[1]["Selected"], source.rows[1]["Fault"])

    def test_demote_headers_synthetic_row_has_no_source_row_lineage(self) -> None:
        source = ImportCandidate("inline", ["Key", "Amount"], [
            {"Key": "A", "Amount": "bad"},
        ], {"source_id": "source-1"}, [])

        result = apply_transformations(source, [{"op": "demote_headers"}])

        self.assertEqual(result.rows[0].source_rows, ())
        self.assertEqual(result.rows[1].source_rows[0][1], 1)

    def test_lineage_union_is_bounded_and_marks_truncation(self) -> None:
        from analytics_studio.file_import import LineagedRow, lineaged_row

        parents = [
            LineagedRow({}, source_rows=((f"source-{index}", 1),))
            for index in range(130)
        ]

        result = lineaged_row({"Value": "x"}, *parents)

        self.assertEqual(len(result.source_rows), 128)
        self.assertTrue(result.source_rows_truncated)

    def test_conversion_error_keeps_original_source_row_after_filter_and_projection(self) -> None:
        source = ImportCandidate("inline", ["Key", "Amount"], [
            {"Key": "drop", "Amount": "0"},
            {"Key": "keep", "Amount": "12"},
            {"Key": "keep", "Amount": "bad"},
        ], {"source_id": "sales-source"}, [])

        result = apply_transformations(source, [
            {"op": "filter_rows", "column": "Key", "operator": "equals", "value": "keep"},
            {"op": "keep_columns", "columns": ["Key", "Amount"]},
            {"op": "convert_type", "column": "Amount", "type": "whole_number"},
        ])

        error = result.rows[-1]["Amount"]
        self.assertIsInstance(error, PowerQueryCellError)
        self.assertEqual(error.row, 2)
        self.assertEqual(len(error.source_rows), 1)
        self.assertEqual(error.source_rows[0][1], 3)

    def test_unpivot_retains_source_row_lineage_for_conversion_errors(self) -> None:
        source = ImportCandidate("inline", ["Key", "A", "B"], [
            {"Key": "drop", "A": "1", "B": "2"},
            {"Key": "keep", "A": "3", "B": "bad"},
        ], {"source_id": "sales-source"}, [])

        result = apply_transformations(source, [
            {"op": "filter_rows", "column": "Key", "operator": "equals", "value": "keep"},
            {
                "op": "unpivot_columns", "columns": ["A", "B"],
                "attribute_name": "Field", "value_name": "Value",
            },
            {"op": "convert_type", "column": "Value", "type": "whole_number"},
        ])

        error = result.rows[1]["Value"]
        self.assertIsInstance(error, PowerQueryCellError)
        self.assertEqual(error.row, 2)
        self.assertEqual(error.source_rows[0][1], 2)

    def test_custom_column_runtime_errors_are_cell_values_and_propagate(self) -> None:
        source = ImportCandidate("inline", ["Amount"], [
            {"Amount": "2"},
            {"Amount": "0"},
        ], {"source_id": "sales-source"}, [])

        result = apply_transformations(source, [
            {"op": "add_custom_column", "name": "Rate", "expression": "10 / [Amount]"},
            {"op": "add_custom_column", "name": "Label", "expression": "[Rate] & \"x\""},
        ])

        self.assertEqual(result.rows[0]["Rate"], "5")
        rate_error = result.rows[1]["Rate"]
        self.assertIsInstance(rate_error, PowerQueryCellError)
        self.assertEqual(rate_error.reason, "Expression.Error")
        self.assertEqual(rate_error.row, 2)
        self.assertEqual(result.rows[1]["Label"], rate_error)

    def test_remove_rows_with_errors_supports_all_or_selected_columns(self) -> None:
        error = PowerQueryCellError("DataFormat.Error", "bad value", "bad", "number", row=1)
        source = ImportCandidate("inline", ["A", "B"], [
            {"A": "ok", "B": "ok"},
            {"A": error, "B": "kept when checking B"},
            {"A": "kept when checking B", "B": error},
        ], {}, [])

        all_columns = apply_transformations(source, [{"op": "remove_rows_with_errors"}])
        selected_column = apply_transformations(source, [{
            "op": "remove_rows_with_errors", "columns": ["A"],
        }])

        self.assertEqual(all_columns.rows, [source.rows[0]])
        self.assertEqual(selected_column.rows, [source.rows[0], source.rows[2]])

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
        converted = apply_transformations(source, [
            {"op": "convert_type", "column": "Active", "type": "boolean"},
        ])
        self.assertIsInstance(converted.rows[2]["Active"], PowerQueryCellError)
        self.assertEqual(converted.rows[2]["Active"].row, 3)
        self.assertIn("Active", converted.rows[2]["Active"].message)

        source.rows[2]["Amount"] = "not a number"
        with self.assertRaisesRegex(TransformationError, r"row 3.*Amount.*number"):
            apply_transformations(source, [
                {"op": "filter_rows", "column": "Amount", "operator": "greater_than", "value": "1"},
            ])

    def test_type_conversion_keeps_a_structured_error_in_each_invalid_cell(self) -> None:
        source = ImportCandidate(
            "csv",
            ["Amount"],
            [
                {"Amount": "10"},
                {"Amount": "bad"},
                {"Amount": "20"},
                {"Amount": "also bad"},
            ],
            {},
            [],
        )
        original = copy.deepcopy(source)

        result = apply_transformations(source, [{
            "op": "convert_type", "column": "Amount", "type": "whole_number",
        }])
        errors = [row["Amount"] for row in result.rows if is_cell_error(row["Amount"])]
        self.assertEqual([(error.row, error.value, error.target_type) for error in errors], [
            (2, "bad", "whole_number"),
            (4, "also bad", "whole_number"),
        ])
        self.assertTrue(all(error.reason == "DataFormat.Error" for error in errors))
        self.assertEqual(source, original)

    def test_locale_conversion_keeps_culture_and_row_on_each_error_cell(self) -> None:
        source = ImportCandidate(
            "csv",
            ["Amount"],
            [
                {"Amount": "1,5"},
                {"Amount": "bad"},
                {"Amount": "2,x"},
                {"Amount": ""},
            ],
            {},
            [],
        )

        result = apply_transformations(source, [{
            "op": "convert_type_using_locale",
            "column": "Amount",
            "type": "decimal_number",
            "culture": "de-DE",
        }])
        errors = [row["Amount"] for row in result.rows if is_cell_error(row["Amount"])]
        self.assertEqual([error.row for error in errors], [2, 3, 4])
        self.assertTrue(all(error.culture == "de-DE" for error in errors))
        self.assertEqual([error.value for error in errors], ["bad", "2,x", ""])
        self.assertTrue(all("de-DE" in error.message for error in errors))

    def test_each_conversion_error_is_bounded_and_keeps_its_source_value(self) -> None:
        long_column = "Column " + ("y" * 500)
        source = ImportCandidate(
            "csv",
            [long_column],
            [
                {long_column: "invalid " + ("x" * 500)}
                if index == 0
                else {long_column: f"invalid {index}"}
                for index in range(25)
            ],
            {},
            [],
        )

        result = apply_transformations(source, [{
            "op": "convert_type", "column": long_column, "type": "whole_number",
        }])
        errors = [row[long_column] for row in result.rows]
        self.assertEqual(len(errors), 25)
        self.assertTrue(all(is_cell_error(error) for error in errors))
        self.assertEqual(errors[0].row, 1)
        self.assertEqual(errors[-1].row, 25)
        self.assertEqual(len(errors[0].value), 508)
        self.assertEqual(errors[0].target_type, "whole_number")
        self.assertLess(len(errors[0].message), 2_000)

    def test_transformation_failure_does_not_change_input(self) -> None:
        source = candidate()
        original = copy.deepcopy(source)
        with self.assertRaises(TransformationError):
            apply_transformations(source, [
                {"op": "rename_column", "column": "Name", "new_name": "Label"},
                {"op": "convert_type", "column": "Active", "type": "boolean"},
                {"op": "filter_rows", "column": "Active", "operator": "equals", "value": "true"},
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
