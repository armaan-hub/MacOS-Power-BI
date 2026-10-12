"""Safety and arithmetic tests for the local DAX measure subset."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
import unittest

from analytics_studio.measures import (
    MeasureError,
    evaluate_measures,
    normalize_calculated_column,
    normalize_measure,
    rename_table_references,
    validate_measures,
)
from analytics_studio.project import FORMAT_VERSION, ProjectFileError, new_project, validate_project


class MeasureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.headers = ["Sales", "Quantity", "Region", "Note"]
        self.rows = [
            {"Sales": "10.5", "Quantity": "2", "Region": "East", "Note": "Paid"},
            {"Sales": "20", "Quantity": "3", "Region": "West", "Note": ""},
            {"Sales": "-1.5", "Quantity": "1", "Region": "East", "Note": "Paid"},
        ]

    def test_rename_table_references_preserves_literals_and_escapes_names(self) -> None:
        expression = 'CALCULATE(SUM(\'Sales Data\'[Amount]), \'Sales Data\'[Region] = "Sales Data[Region]")'

        self.assertEqual(
            rename_table_references(expression, "Sales Data", "O'Brien Sales"),
            'CALCULATE(SUM(\'O\'\'Brien Sales\'[Amount]), \'O\'\'Brien Sales\'[Region] = "Sales Data[Region]")',
        )
        self.assertEqual(
            rename_table_references("COUNTROWS(Sales[Amount])", "Sales", "Revenue"),
            "COUNTROWS('Revenue'[Amount])",
        )

    def test_aggregations_arithmetic_and_measure_dependencies(self) -> None:
        measures = [
            {"name": "Gross sales", "expression": "SUM([Sales])"},
            {"name": "Average sale", "expression": "AVERAGE([Sales])"},
            {"name": "Rate", "expression": "DIVIDE([Gross sales], COUNTROWS())"},
            {"name": "Double rate", "expression": "[Rate] * 2"},
        ]

        result = evaluate_measures(measures, self.rows, self.headers, "Sales data")

        self.assertEqual(result["Gross sales"], Decimal("29.0"))
        self.assertEqual(result["Average sale"], Decimal("9.666666666666666666666666667"))
        self.assertEqual(result["Rate"], Decimal("29.0") / 3)
        self.assertEqual(result["Double rate"], Decimal("29.0") / 3 * 2)

    def test_count_text_distinct_count_and_empty_divide_alternate(self) -> None:
        measures = [
            {"name": "Rows", "expression": "COUNTROWS()"},
            {"name": "Notes", "expression": "COUNTA([Note])"},
            {"name": "Unique regions", "expression": "DISTINCTCOUNT([Region])"},
            {"name": "Safe rate", "expression": "DIVIDE(10, 0, -1)"},
        ]

        result = evaluate_measures(measures, self.rows, self.headers)

        self.assertEqual(result["Rows"], Decimal(3))
        self.assertEqual(result["Notes"], Decimal(2))
        self.assertEqual(result["Unique regions"], Decimal(2))
        self.assertEqual(result["Safe rate"], Decimal(-1))

    def test_distinct_count_functions_count_blank_and_preserve_empty_results(self) -> None:
        rows = [
            {"Value": "A"},
            {"Value": "A"},
            {"Value": ""},
            {"Value": ""},
            {"Value": " "},
            {"Value": "0"},
            {"Value": "0"},
        ]
        measures = [
            {"name": "Including blank", "expression": "DISTINCTCOUNT([Value])"},
            {
                "name": "Without blank",
                "expression": "DISTINCTCOUNTNOBLANK([Value])",
            },
            {
                "name": "Filtered empty",
                "expression": 'CALCULATE(DISTINCTCOUNT([Value]), [Value] = "Missing")',
            },
            {
                "name": "Filtered empty without blank",
                "expression": 'CALCULATE(DISTINCTCOUNTNOBLANK([Value]), [Value] = "Missing")',
            },
        ]

        result = evaluate_measures(measures, rows, ["Value"], "Values")
        self.assertEqual(result["Including blank"], Decimal(4))
        self.assertEqual(result["Without blank"], Decimal(3))
        self.assertIsNone(result["Filtered empty"])
        self.assertIsNone(result["Filtered empty without blank"])

        blank_only = evaluate_measures(
            measures[:2], [{"Value": ""}, {"Value": ""}], ["Value"], "Values"
        )
        self.assertEqual(blank_only["Including blank"], Decimal(1))
        self.assertEqual(blank_only["Without blank"], Decimal(0))

        no_rows = evaluate_measures(measures[:2], [], ["Value"], "Values")
        self.assertIsNone(no_rows["Including blank"])
        self.assertIsNone(no_rows["Without blank"])

        typed_zero = evaluate_measures(
            measures[:2],
            [{"Value": 0}, {"Value": None}, {"Value": 0}],
            ["Value"],
            "Values",
        )
        self.assertEqual(typed_zero["Including blank"], Decimal(2))
        self.assertEqual(typed_zero["Without blank"], Decimal(1))

        with self.assertRaises(MeasureError):
            normalize_measure(
                "Invalid distinct", "DISTINCTCOUNTNOBLANK(SUM([Value]))"
            )

    def test_countx_and_countax_iterate_nonblank_values_and_boolean_results(self) -> None:
        rows = [
            *self.rows,
            {"Sales": " ", "Quantity": "4", "Region": "North", "Note": " "},
        ]
        result = evaluate_measures([
            {"name": "Numeric total", "expression": "SUMX('Sales data', [Sales])"},
            {"name": "Numeric values", "expression": "COUNTX('Sales data', [Sales])"},
            {"name": "Text values", "expression": "COUNTX('Sales data', [Note])"},
            {
                "name": "Conditional text",
                "expression": 'COUNTX(\'Sales data\', IF([Quantity] > 2, "x", BLANK()))',
            },
            {
                "name": "Text equality",
                "expression": 'COUNTX(\'Sales data\', IF([Note] = "paid", "x", BLANK()))',
            },
            {
                "name": "Logical text equality and empty result",
                "expression": 'COUNTAX(\'Sales data\', IF(AND([Note] = "PAID", [Quantity] > 1), "", BLANK()))',
            },
            {"name": "Empty string countx", "expression": 'COUNTX(\'Sales data\', "")'},
            {"name": "Empty string countax", "expression": 'COUNTAX(\'Sales data\', "")'},
            {
                "name": "Boolean countx",
                "expression": "COUNTX('Sales data', IF([Quantity] > 2, TRUE(), FALSE()))",
            },
            {
                "name": "Boolean countax",
                "expression": "COUNTAX('Sales data', IF([Quantity] > 2, TRUE(), FALSE()))",
            },
            {"name": "Text countax", "expression": "COUNTAX('Sales data', [Note])"},
        ], rows, self.headers, "Sales data")

        self.assertEqual(result, {
            "Numeric total": Decimal("29.0"),
            "Numeric values": Decimal(4),
            "Text values": Decimal(3),
            "Conditional text": Decimal(2),
            "Text equality": Decimal(2),
            "Logical text equality and empty result": Decimal(1),
            "Empty string countx": Decimal(4),
            "Empty string countax": Decimal(4),
            "Boolean countx": None,
            "Boolean countax": Decimal(4),
            "Text countax": Decimal(3),
        })

    def test_count_iterators_accept_distinct_count_without_blank_expression(self) -> None:
        rows = [
            {"Value": "A"},
            {"Value": "A"},
            {"Value": ""},
            {"Value": " "},
            {"Value": "0"},
        ]
        result = evaluate_measures(
            [
                {
                    "name": "CountX distinct",
                    "expression": "COUNTX('Values', DISTINCTCOUNTNOBLANK([Value]))",
                },
                {
                    "name": "CountAX distinct",
                    "expression": "COUNTAX('Values', DISTINCTCOUNTNOBLANK([Value]))",
                },
            ],
            rows,
            ["Value"],
            "Values",
        )

        self.assertEqual(result["CountX distinct"], Decimal(5))
        self.assertEqual(result["CountAX distinct"], Decimal(5))

    def test_countx_and_countax_preserve_blank_zero_and_empty_string_results(self) -> None:
        blank_rows = [
            {"Sales": "", "Quantity": "1", "Region": "East", "Note": ""},
            {"Sales": "", "Quantity": "2", "Region": "West", "Note": ""},
        ]
        result = evaluate_measures([
            {"name": "Blank countx", "expression": "COUNTX('Sales data', [Sales])"},
            {"name": "Blank countax", "expression": "COUNTAX('Sales data', [Note])"},
            {
                "name": "Blank expression",
                "expression": "COUNTX('Sales data', IF([Sales] > 0, 1, BLANK()))",
            },
            {"name": "Boolean-only countx", "expression": "COUNTX('Sales data', TRUE())"},
            {"name": "Boolean-only countax", "expression": "COUNTAX('Sales data', TRUE())"},
            {"name": "Count zero values", "expression": "COUNTX('Sales data', 0)"},
            {"name": "Empty-string count", "expression": 'COUNTX(\'Sales data\', "")'},
            {"name": "Blank alias", "expression": "[Blank expression]"},
            {"name": "Actual zero", "expression": "0"},
        ], blank_rows, self.headers, "Sales data")

        self.assertIsNone(result["Blank countx"])
        self.assertIsNone(result["Blank countax"])
        self.assertIsNone(result["Blank expression"])
        self.assertIsNone(result["Boolean-only countx"])
        self.assertEqual(result["Boolean-only countax"], Decimal(2))
        self.assertEqual(result["Count zero values"], Decimal(2))
        self.assertEqual(result["Empty-string count"], Decimal(2))
        self.assertIsNone(result["Blank alias"])
        self.assertEqual(result["Actual zero"], Decimal(0))

        empty_result = evaluate_measures([
            {"name": "Empty countx", "expression": "COUNTX('Sales data', [Sales])"},
            {"name": "Empty countax", "expression": "COUNTAX('Sales data', [Note])"},
        ], [], self.headers, "Sales data")
        self.assertIsNone(empty_result["Empty countx"])
        self.assertIsNone(empty_result["Empty countax"])

    def test_countx_blank_result_survives_calculate_filter_and_all(self) -> None:
        filtered_result = evaluate_measures([
            {"name": "Filtered count", "expression": "COUNTX('Sales data', [Sales])"},
        ], self.rows[:1], self.headers, "Sales data")
        all_result = evaluate_measures([
            {"name": "All count", "expression": "COUNTX(ALL('Sales data'), [Sales])"},
        ], self.rows, self.headers, "Sales data")
        explicitly_filtered = evaluate_measures([
            {
                "name": "Explicitly empty count",
                "expression": 'CALCULATE(COUNTX(\'Sales data\', [Sales]), \'Sales data\'[Region] = "Missing")',
            },
        ], self.rows, self.headers, "Sales data")

        self.assertEqual(filtered_result["Filtered count"], Decimal(1))
        self.assertEqual(all_result["All count"], Decimal(3))
        self.assertIsNone(explicitly_filtered["Explicitly empty count"])

    def test_countx_and_countax_validate_table_argument_and_measure_only_scope(self) -> None:
        for expression in (
            "COUNTX('Sales data')",
            "COUNTAX('Sales data', [Sales], [Quantity])",
            'COUNTX(\'Sales data\', IF([Note] > "a", "x", BLANK()))',
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(MeasureError):
                    evaluate_measures(
                        [{"name": "Invalid", "expression": expression}],
                        self.rows,
                        self.headers,
                        "Sales data",
                    )
        with self.assertRaisesRegex(MeasureError, "only in measures"):
            normalize_calculated_column(
                "Count sales", "COUNTX('Sales data', [Sales])"
            )
        invalid_numeric_rows = [
            *self.rows,
            {"Sales": "not numeric", "Quantity": "1", "Region": "East", "Note": "x"},
        ]
        with self.assertRaisesRegex(MeasureError, "non-numeric"):
            evaluate_measures(
                [{"name": "Count", "expression": "COUNTX('Sales data', [Sales])"}],
                invalid_numeric_rows,
                self.headers,
                "Sales data",
                table_context=[{
                    "id": "sales-table",
                    "name": "Sales data",
                    "headers": self.headers,
                    "rows": invalid_numeric_rows,
                    "column_types": {"Sales": "decimal_number"},
                }],
            )

    def test_count_iterators_allow_same_table_text_column_equality_conditions(self) -> None:
        rows = [
            {"Sales": "1", "Quantity": "1", "Region": "Paid", "Note": "paid"},
            {"Sales": "2", "Quantity": "2", "Region": "East", "Note": "Paid"},
        ]
        result = evaluate_measures([
            {
                "name": "Matching text columns",
                "expression": 'COUNTX(\'Sales data\', IF([Note] = [Region], "x", BLANK()))',
            },
            {
                "name": "Different text columns",
                "expression": 'COUNTAX(\'Sales data\', IF([Note] <> [Region], "x", BLANK()))',
            },
            {
                "name": "Numeric columns",
                "expression": 'COUNTX(\'Sales data\', IF([Sales] = [Quantity], "x", BLANK()))',
            },
        ], rows, self.headers, "Sales data", table_context=[{
            "id": "sales-table",
            "name": "Sales data",
            "headers": self.headers,
            "rows": rows,
            "column_types": {
                "Sales": "whole_number",
                "Quantity": "whole_number",
                "Region": "text",
                "Note": "text",
            },
        }])

        self.assertEqual(result, {
            "Matching text columns": Decimal(1),
            "Different text columns": Decimal(1),
            "Numeric columns": Decimal(2),
        })

    def test_count_iterators_reject_unsupported_date_text_comparisons(self) -> None:
        rows = [{
            "Sales": "1",
            "Quantity": "1",
            "Region": "2026-10-10",
            "Note": "2026-10-10",
        }]
        table_context = [{
            "id": "sales-table",
            "name": "Sales data",
            "headers": self.headers,
            "rows": rows,
            "column_types": {"Region": "date", "Note": "text"},
        }]
        for expression in (
            'COUNTX(\'Sales data\', IF([Region] = [Note], "x", BLANK()))',
            'COUNTX(\'Sales data\', IF([Region] = "2026-10-10", "x", BLANK()))',
            'COUNTX(\'Sales data\', IF([Region] = [Region], "x", BLANK()))',
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(MeasureError):
                    evaluate_measures(
                        [{"name": "Date comparison", "expression": expression}],
                        rows,
                        self.headers,
                        "Sales data",
                        table_context=table_context,
                    )

    def test_count_iterators_reject_mixed_reference_literal_types(self) -> None:
        rows = [{
            "Sales": "1",
            "Quantity": "1",
            "Region": "East",
            "Note": "1",
        }]
        table_context = [{
            "id": "sales-table",
            "name": "Sales data",
            "headers": self.headers,
            "rows": rows,
            "column_types": {"Sales": "whole_number", "Note": "text"},
        }]
        expressions = (
            'COUNTX(\'Sales data\', IF([Note] = 1, "x", BLANK()))',
            'COUNTX(\'Sales data\', IF([Sales] = "1", "x", BLANK()))',
            'COUNTX(\'Sales data\', IF(ABS([Sales]) = [Note], "x", BLANK()))',
            'COUNTX(\'Sales data\', IF(IF([Note] = 1, [Sales], 0) = 1, "x", BLANK()))',
            'COUNTX(\'Sales data\', IF([Note] > 0, "x", BLANK()))',
            'COUNTX(\'Sales data\', IF(COUNTROWS(FILTER(\'Sales data\', [Note] > 0)) > 0, "x", BLANK()))',
            'COUNTX(\'Sales data\', IF(AND([Note], TRUE()) = TRUE(), "x", BLANK()))',
            'COUNTX(\'Sales data\', IF(AND(IF([Note], TRUE(), FALSE()), TRUE()) = TRUE(), "x", BLANK()))',
            'COUNTX(\'Sales data\', IF([Sales], "x", BLANK()))',
            'COUNTX(\'Sales data\', IF(AND(ABS([Note]), TRUE()), "x", BLANK()))',
            'COUNTX(\'Sales data\', IF(ABS([Note]) > 0, "x", BLANK()))',
            'COUNTX(\'Sales data\', ABS([Note]))',
            'COUNTX(\'Sales data\', IF(COUNT([Note]) > 0, "x", BLANK()))',
        )

        for expression in expressions:
            with self.subTest(expression=expression):
                with self.assertRaises(MeasureError):
                    evaluate_measures(
                        [{"name": "Mixed comparison", "expression": expression}],
                        rows,
                        self.headers,
                        "Sales data",
                        table_context=table_context,
                    )

    def test_count_iterators_evaluate_inferred_boolean_and_all_table_arguments(self) -> None:
        rows = [
            {"Sales": "1", "Quantity": "1", "Region": "East", "Note": "true"},
            {"Sales": "2", "Quantity": "2", "Region": "West", "Note": "false"},
        ]
        result = evaluate_measures([
            {
                "name": "Untyped Boolean condition",
                "expression": 'COUNTX(\'Sales data\', IF([Note] = TRUE(), "x", BLANK()))',
            },
            {
                "name": "ALL table condition",
                "expression": 'COUNTX(\'Sales data\', IF(COUNTROWS(ALL(\'Sales data\')) > 0, "x", BLANK()))',
            },
        ], rows, self.headers, "Sales data")

        self.assertEqual(result, {
            "Untyped Boolean condition": Decimal(1),
            "ALL table condition": Decimal(2),
        })
        typed_result = evaluate_measures([{
            "name": "Typed numeric scalar",
            "expression": 'COUNTX(\'Sales data\', ABS([Sales]))',
        }], rows, self.headers, "Sales data", table_context=[{
            "id": "sales-table",
            "name": "Sales data",
            "headers": self.headers,
            "rows": rows,
            "column_types": {"Sales": "whole_number", "Note": "text"},
        }])
        self.assertEqual(typed_result["Typed numeric scalar"], Decimal(2))
        cross_table_result = evaluate_measures([{
            "name": "Nested iterator against second table",
            "expression": 'COUNTX(\'Sales data\', IF(SUMX(\'Targets\', \'Targets\'[Target]) > 0, "x", BLANK()))',
        }, {
            "name": "Scalar aggregate against second table",
            "expression": 'COUNTX(\'Sales data\', IF(SUM(\'Targets\'[Target]) > 0, "x", BLANK()))',
        }], rows, self.headers, "Sales data", table_context=[
            {
                "id": "sales-table",
                "name": "Sales data",
                "headers": self.headers,
                "rows": rows,
                "column_types": {"Sales": "whole_number", "Note": "text"},
            },
            {
                "id": "targets-table",
                "name": "Targets",
                "headers": ["Target"],
                "rows": [{"Target": "10"}],
                "column_types": {"Target": "whole_number"},
            },
        ])
        self.assertEqual(
            cross_table_result["Nested iterator against second table"], Decimal(2)
        )
        self.assertEqual(
            cross_table_result["Scalar aggregate against second table"], Decimal(2)
        )
        with self.assertRaises(MeasureError):
            evaluate_measures([{
                "name": "Unverified logical condition",
                "expression": 'COUNTX(\'Sales data\', IF([Note], "x", BLANK()))',
            }], rows, self.headers, "Sales data")
        empty_table_context = [{
            "id": "sales-table",
            "name": "Sales data",
            "headers": self.headers,
            "rows": [],
            "column_types": {"Sales": "whole_number", "Note": "text"},
        }]
        with self.assertRaises(MeasureError):
            evaluate_measures([{
                "name": "Invalid numeric IF condition on empty table",
                "expression": 'COUNTX(\'Sales data\', IF([Sales], "x", BLANK()))',
            }], [], self.headers, "Sales data", table_context=empty_table_context)

    def test_abs_and_round_use_safe_decimal_evaluation_and_dax_half_away_rounding(self) -> None:
        result = evaluate_measures([
            {"name": "Absolute loss", "expression": "ABS(MIN([Sales]))"},
            {"name": "Rounded average", "expression": "ROUND(AVERAGE([Sales]), 2)"},
            {"name": "Round positive half", "expression": "ROUND(2.5, 0)"},
            {"name": "Round negative half", "expression": "ROUND(-2.5, 0)"},
            {"name": "Round tens", "expression": "ROUND(125, -1)"},
        ], self.rows, self.headers)

        self.assertEqual(result["Absolute loss"], Decimal("1.5"))
        self.assertEqual(result["Rounded average"], Decimal("9.67"))
        self.assertEqual(result["Round positive half"], Decimal("3"))
        self.assertEqual(result["Round negative half"], Decimal("-3"))
        self.assertEqual(result["Round tens"], Decimal("1.3E+2"))

    def test_abs_and_round_reject_bad_arity_and_fractional_precision(self) -> None:
        for expression in (
            "ABS()", "ABS(1, 2)", "ROUND(1)", "ROUND(1, 1.5)", "ROUND(1, 29)"
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(MeasureError):
                    evaluate_measures(
                        [{"name": "Invalid", "expression": expression}],
                        self.rows,
                        self.headers,
                    )

    def test_if_comparisons_and_logical_expressions(self) -> None:
        result = evaluate_measures([
            {"name": "Threshold", "expression": "IF(SUM([Sales]) >= 20, SUM([Sales]), 0)"},
            {"name": "Fallback", "expression": "IF(SUM([Sales]) < 0, ABS(SUM([Sales])), ROUND(AVERAGE([Sales]), 2))"},
            {"name": "And condition", "expression": "IF(AND(COUNTROWS() = 3, SUM([Sales]) <> 0), 1, 0)"},
            {"name": "Or condition", "expression": "IF(SUM([Sales]) < 0 || COUNTROWS() > 2, 1, 0)"},
            {"name": "Not condition", "expression": "IF(NOT(SUM([Sales]) < 0), 1, 0)"},
            {"name": "Boolean comparison", "expression": "IF(TRUE = FALSE, 1, 0)"},
        ], self.rows, self.headers)

        self.assertEqual(result["Threshold"], Decimal("29.0"))
        self.assertEqual(result["Fallback"], Decimal("9.67"))
        self.assertEqual(result["And condition"], Decimal(1))
        self.assertEqual(result["Or condition"], Decimal(1))
        self.assertEqual(result["Not condition"], Decimal(1))
        self.assertEqual(result["Boolean comparison"], Decimal(0))

    def test_conditional_expressions_reject_invalid_boolean_shapes(self) -> None:
        for expression in (
            "IF(1 = 1, 2)",
            "1 < 2 < 3",
            "SUM([Sales]) > 10",
            "IF(TRUE, FALSE, TRUE) + 1",
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(MeasureError):
                    evaluate_measures(
                        [{"name": "Invalid", "expression": expression}],
                        self.rows,
                        self.headers,
                    )

    def test_sumx_and_averagex_evaluate_row_expressions_with_blank_handling(self) -> None:
        measures = [
            {"name": "Line total", "expression": "SUMX('Active table', [Sales] * [Quantity])"},
            {"name": "Qualified line total", "expression": "SUMX('Active table', 'Active table'[Sales] * [Quantity])"},
            {"name": "Average sales", "expression": "AVERAGEX('Active table', [Sales])"},
        ]
        rows = [*self.rows, {"Sales": "", "Quantity": "4", "Region": "East", "Note": ""}]

        result = evaluate_measures(measures, rows, self.headers)

        self.assertEqual(result["Line total"], Decimal("79.5"))
        self.assertEqual(result["Qualified line total"], Decimal("79.5"))
        self.assertEqual(result["Average sales"], Decimal("9.666666666666666666666666667"))

    def test_related_looks_up_numeric_value_through_direct_many_to_one(self) -> None:
        sales_rows = [
            {"ProductKey": "1", "Quantity": "2"},
            {"ProductKey": "2", "Quantity": "3"},
            {"ProductKey": "99", "Quantity": "8"},
        ]
        product_rows = [
            {"ProductKey": "1", "Unit Price": "10.50", "Category": "A"},
            {"ProductKey": "2", "Unit Price": "4", "Category": "B"},
        ]
        tables = [
            {
                "id": "sales",
                "name": "Sales",
                "headers": ["ProductKey", "Quantity"],
                "rows": sales_rows,
                "column_types": {
                    "ProductKey": "whole_number", "Quantity": "whole_number",
                },
            },
            {
                "id": "products",
                "name": "Products",
                "headers": ["ProductKey", "Unit Price", "Category"],
                "rows": product_rows,
                "column_types": {
                    "ProductKey": "whole_number",
                    "Unit Price": "decimal_number",
                    "Category": "text",
                },
            },
        ]
        relationship = {
            "relationship_version": 1,
            "id": "sales-products",
            "from": "Sales[ProductKey]",
            "to": "Products[ProductKey]",
            "from_table_id": "sales",
            "from_column": "ProductKey",
            "to_table_id": "products",
            "to_column": "ProductKey",
            "cardinality": "many_to_one",
            "cross_filter_direction": "single",
            "is_active": True,
        }

        result = evaluate_measures(
            [
                {
                    "name": "Revenue",
                    "expression": (
                        "SUMX('Sales', 'Sales'[Quantity] * "
                        "RELATED('Products'[Unit Price]))"
                    ),
                },
                {
                    "name": "Matched prices",
                    "expression": "SUMX('Sales', RELATED('Products'[Unit Price]))",
                },
            ],
            sales_rows,
            ["ProductKey", "Quantity"],
            "Sales",
            table_context=tables,
            relationships=[relationship],
            active_table_id="sales",
        )

        self.assertEqual(result["Revenue"], Decimal("33"))
        # The unmatched key contributes BLANK and is skipped by SUMX.
        self.assertEqual(result["Matched prices"], Decimal("14.50"))

        reversed_relationship = {
            **relationship,
            "from": "Products[ProductKey]",
            "to": "Sales[ProductKey]",
            "from_table_id": "products",
            "from_column": "ProductKey",
            "to_table_id": "sales",
            "to_column": "ProductKey",
            "cardinality": "one_to_many",
        }
        reversed_result = evaluate_measures(
            [{
                "name": "Matched prices",
                "expression": "SUMX('Sales', RELATED('Products'[Unit Price]))",
            }],
            sales_rows,
            ["ProductKey", "Quantity"],
            "Sales",
            table_context=tables,
            relationships=[reversed_relationship],
            active_table_id="sales",
        )
        self.assertEqual(reversed_result["Matched prices"], Decimal("14.50"))

    def test_related_lookup_ignores_target_filter_when_it_does_not_filter_iterator(self) -> None:
        sales_rows = [
            {"ProductKey": "1", "Quantity": "2"},
            {"ProductKey": "2", "Quantity": "3"},
        ]
        product_rows = [
            {"ProductKey": "1", "Unit Price": "10"},
            {"ProductKey": "2", "Unit Price": "20"},
        ]
        tables = [
            {
                "id": "sales", "name": "Sales",
                "headers": ["ProductKey", "Quantity"], "rows": sales_rows,
                "column_types": {
                    "ProductKey": "whole_number", "Quantity": "whole_number",
                },
            },
            {
                "id": "products", "name": "Products",
                "headers": ["ProductKey", "Unit Price"], "rows": product_rows,
                "column_types": {
                    "ProductKey": "whole_number", "Unit Price": "decimal_number",
                },
                "filter_rows": [product_rows[0]],
            },
        ]
        relationship = {
            "relationship_version": 1,
            "id": "sales-products",
            "from": "Sales[ProductKey]",
            "to": "Products[ProductKey]",
            "from_table_id": "sales", "from_column": "ProductKey",
            "to_table_id": "products", "to_column": "ProductKey",
            "cardinality": "many_to_one", "cross_filter_direction": "single",
            "filter_direction_override": "from_to", "is_active": True,
        }

        result = evaluate_measures(
            [{
                "name": "Revenue",
                "expression": (
                    "SUMX('Sales', 'Sales'[Quantity] * "
                    "RELATED('Products'[Unit Price]))"
                ),
            }],
            sales_rows,
            ["ProductKey", "Quantity"],
            "Sales",
            table_context=tables,
            relationships=[relationship],
            filter_table_ids={"products"},
            active_table_id="sales",
        )

        # The product filter does not remove Sales rows, and RELATED reads the
        # matching product value from the full related table.
        self.assertEqual(result["Revenue"], Decimal("80"))

    def test_related_rejects_unsupported_relationship_and_scope_shapes(self) -> None:
        sales_rows = [{"ProductKey": "1", "Quantity": "2"}]
        product_rows = [{"ProductKey": "1", "Unit Price": "10", "Category": "A"}]
        tables = [
            {
                "id": "sales", "name": "Sales",
                "headers": ["ProductKey", "Quantity"], "rows": sales_rows,
                "column_types": {
                    "ProductKey": "whole_number", "Quantity": "whole_number",
                },
            },
            {
                "id": "products", "name": "Products",
                "headers": ["ProductKey", "Unit Price", "Category"], "rows": product_rows,
                "column_types": {
                    "ProductKey": "whole_number", "Unit Price": "decimal_number",
                    "Category": "text",
                },
            },
        ]
        relationship = {
            "relationship_version": 1,
            "id": "sales-products",
            "from": "Sales[ProductKey]", "to": "Products[ProductKey]",
            "from_table_id": "sales", "from_column": "ProductKey",
            "to_table_id": "products", "to_column": "ProductKey",
            "cardinality": "many_to_one", "cross_filter_direction": "single",
            "is_active": True,
        }

        cases = (
            ("RELATED('Products'[Unit Price])", [relationship], "row context"),
            ("SUMX('Sales', RELATED('Products'[Unit Price]))", [], "relationship"),
            (
                "SUMX('Sales', RELATED('Products'[Unit Price]))",
                [{**relationship, "is_active": False}],
                "relationship",
            ),
            (
                "SUMX('Sales', RELATED('Products'[Unit Price]))",
                [
                    relationship,
                    {
                        **relationship,
                        "id": "sales-quantity-products",
                        "from_column": "Quantity",
                    },
                ],
                "more than one direct relationship",
            ),
            (
                "SUMX('Sales', RELATED('Products'[Category]))",
                [relationship],
                "numeric",
            ),
        )
        for expression, links, message in cases:
            with self.subTest(expression=expression, message=message):
                with self.assertRaisesRegex(MeasureError, message):
                    evaluate_measures(
                        [{"name": "Invalid", "expression": expression}],
                        sales_rows,
                        ["ProductKey", "Quantity"],
                        "Sales",
                        table_context=tables,
                        relationships=links,
                        active_table_id="sales",
                    )

        text_key_tables = deepcopy(tables)
        text_key_tables[0]["column_types"]["ProductKey"] = "text"
        text_key_tables[0]["rows"][0]["ProductKey"] = "a"
        text_key_tables[1]["column_types"]["ProductKey"] = "text"
        text_key_tables[1]["rows"][0]["ProductKey"] = "A"
        text_result = evaluate_measures(
            [{
                "name": "Case-insensitive text lookup",
                "expression": "SUMX('Sales', RELATED('Products'[Unit Price]))",
            }],
            text_key_tables[0]["rows"],
            text_key_tables[0]["headers"],
            "Sales",
            table_context=text_key_tables,
            relationships=[relationship],
            active_table_id="sales",
        )
        self.assertEqual(text_result["Case-insensitive text lookup"], Decimal("10"))

        duplicate_text_key_tables = deepcopy(text_key_tables)
        duplicate_text_key_tables[1]["rows"].append({
            "ProductKey": "a", "Unit Price": "20", "Category": "B",
        })
        with self.assertRaisesRegex(MeasureError, "unique values"):
            evaluate_measures(
                [{
                    "name": "Ambiguous text lookup",
                    "expression": "SUMX('Sales', RELATED('Products'[Unit Price]))",
                }],
                duplicate_text_key_tables[0]["rows"],
                duplicate_text_key_tables[0]["headers"],
                "Sales",
                table_context=duplicate_text_key_tables,
                relationships=[relationship],
                active_table_id="sales",
            )

    def test_iterator_measure_reference_uses_row_context_transition(self) -> None:
        result = evaluate_measures([
            {"name": "Base sales", "expression": "SUM([Sales])"},
            {"name": "Sum of row sales", "expression": "SUMX('Sales data', [Base sales])"},
        ], self.rows, self.headers, "Sales data")

        self.assertEqual(result["Base sales"], Decimal("29.0"))
        self.assertEqual(result["Sum of row sales"], Decimal("29.0"))

    def test_iterators_reject_unloaded_tables_and_text(self) -> None:
        for expression, message in (
            ("SUMX(Missing, [Sales])", "not loaded"),
            ("SUMX('Active table', [Note])", "non-numeric"),
        ):
            with self.subTest(expression=expression):
                with self.assertRaisesRegex(MeasureError, message):
                    evaluate_measures(
                        [{"name": "Invalid", "expression": expression}],
                        self.rows,
                        self.headers,
                        measure_names=["Invalid"],
                    )

    def test_qualified_column_and_formula_assignment_are_supported(self) -> None:
        measure = normalize_measure(
            "Net sales", "Net sales = SUM('Sales data'[Sales]) - SUM([Sales]) + 29"
        )

        self.assertEqual(measure, {
            "name": "Net sales",
            "expression": "SUM('Sales data'[Sales]) - SUM([Sales]) + 29",
        })
        self.assertEqual(
            evaluate_measures([measure], self.rows, self.headers, "Sales data")["Net sales"],
            Decimal(29),
        )

    def test_invalid_dax_and_unsafe_code_are_rejected(self) -> None:
        for expression in (
            "SUM([Missing])",
            "__import__('os')",
            "SUM([Sales]); open('/tmp/x', 'w')",
            "SUM([Sales]) / 0",
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(MeasureError):
                    evaluate_measures(
                        [{"name": "Bad", "expression": expression}],
                        self.rows,
                        self.headers,
                        "Sales data",
                    )

    def test_calculate_without_filters_keeps_the_current_context(self) -> None:
        values = evaluate_measures(
            [{
                "name": "Current sales",
                "expression": "CALCULATE(SUM([Sales]))",
            }],
            self.rows,
            self.headers,
            "Sales data",
        )
        self.assertEqual(values["Current sales"], Decimal("29.0"))

    def test_invalid_measure_dependency_and_non_numeric_values_report_clear_errors(self) -> None:
        with self.assertRaisesRegex(MeasureError, "cycle"):
            evaluate_measures([
                {"name": "A", "expression": "[B]"},
                {"name": "B", "expression": "[A]"},
            ], self.rows, self.headers)
        with self.assertRaisesRegex(MeasureError, "non-numeric"):
            evaluate_measures(
                [{"name": "Bad", "expression": "SUM([Note])"}],
                self.rows,
                self.headers,
            )

    def test_measure_list_requires_unique_names_and_known_definition_shape(self) -> None:
        with self.assertRaisesRegex(MeasureError, "duplicated"):
            validate_measures([
                {"name": "Sales", "expression": "SUM([Sales])"},
                {"name": "sales", "expression": "SUM([Sales])"},
            ])
        with self.assertRaises(MeasureError):
            validate_measures([{"name": "Sales", "expression": "SUM([Sales])", "code": "bad"}])

    def test_measure_model_metadata_is_normalized_and_validated(self) -> None:
        measure = normalize_measure(
            "Sales total",
            "SUM([Sales])",
            description="  Net value after discounts  ",
            display_folder=" Finance / Sales ",
            is_hidden=True,
        )
        self.assertEqual(measure, {
            "name": "Sales total",
            "expression": "SUM([Sales])",
            "description": "Net value after discounts",
            "display_folder": "Finance / Sales",
            "is_hidden": True,
        })
        self.assertEqual(validate_measures([measure]), [measure])
        self.assertEqual(
            normalize_measure("Plain", "SUM([Sales])"),
            {"name": "Plain", "expression": "SUM([Sales])"},
        )
        for metadata in (
            {"description": "x" * 4_001},
            {"display_folder": "x\nfolder"},
            {"is_hidden": 1},
        ):
            with self.subTest(metadata=metadata):
                with self.assertRaises(MeasureError):
                    normalize_measure("Invalid", "SUM([Sales])", **metadata)

    def test_project_validation_preserves_measure_model_metadata(self) -> None:
        project = new_project("Measure metadata")
        project["model"]["measures"] = [{
            "name": "Sales total",
            "expression": "SUM([Sales])",
            "description": "Sales after discount",
            "display_folder": "Finance/Sales",
            "is_hidden": True,
        }]
        validated = validate_project(project)
        self.assertEqual(validated["model"]["measures"], project["model"]["measures"])

    def test_v4_projects_migrate_to_current_format_with_an_empty_measure_list(self) -> None:
        project = new_project("Legacy")
        project["format_version"] = 4
        project["model"].pop("measures")

        migrated = validate_project(project)

        self.assertEqual(FORMAT_VERSION, 78)
        self.assertEqual(migrated["format_version"], FORMAT_VERSION)
        self.assertEqual(migrated["model"]["measures"], [])

    def test_project_validation_checks_measure_definitions(self) -> None:
        project = new_project("Measures")
        project["model"]["measures"] = [{"name": "Sales", "expression": "SUM([Sales])"}]
        self.assertEqual(validate_project(project)["model"]["measures"], project["model"]["measures"])

        project["model"]["measures"] = [{"name": "Bad", "expression": "CALCULATE()"}]
        with self.assertRaises(ProjectFileError):
            validate_project(project)


if __name__ == "__main__":
    unittest.main()
