"""Acceptance checks for bounded CALCULATE filters and filter modifiers."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.measures import MeasureError, evaluate_measures, normalize_measure


class CalculateBooleanFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.sales_path = self.root / "Sales.csv"
        self.sales_path.write_text(
            "ID,Color,Region,Amount,Active\n"
            "1,Red,East,20,True\n"
            "2,Blue,East,10,False\n"
            "3,Green,East,7,True\n"
            "4,Blue,West,30,True\n"
            "5,Green,West,40,False\n"
            "6,Red,West,50,True\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, settings_name: str) -> StudioController:
        settings = QSettings(
            str(self.root / settings_name), QSettings.Format.IniFormat
        )
        return StudioController(self.app, settings)

    def load_sales(self, controller: StudioController) -> None:
        self.assertTrue(
            controller._commit_import(self.sales_path, parse_file(self.sales_path)),
            controller.statusMessage,
        )
        self.assertTrue(
            controller.setColumnType("Amount", "whole_number"),
            controller.statusMessage,
        )

    def test_calculate_replaces_target_filters_and_preserves_other_columns(self) -> None:
        controller = self.controller("settings.ini")
        self.load_sales(controller)
        sales_id = str(controller.activeTableId)
        self.assertTrue(controller.addPageFilterRule(
            sales_id, "Color", "equals", "Red", "", "", "and"
        ))
        self.assertTrue(controller.addPageFilterRule(
            sales_id, "Region", "equals", "East", "", "", "and"
        ))

        definitions = (
            (
                "Blue sales",
                "CALCULATE(SUM([Amount]), 'Sales'[Color] = \"Blue\")",
                "10",
            ),
            (
                "Blue sales over seven",
                "CALCULATE(SUM([Amount]), 'Sales'[Color] = \"Blue\", 'Sales'[Amount] >= 7)",
                "10",
            ),
            (
                "Blue or green sales",
                "CALCULATE(SUM([Amount]), 'Sales'[Color] = \"Blue\" || 'Sales'[Color] = \"Green\")",
                "17",
            ),
            (
                "Intersect blue sales",
                "CALCULATE(SUM([Amount]), KEEPFILTERS('Sales'[Color] = \"Blue\"))",
                "0",
            ),
            (
                "Intersect red sales",
                "CALCULATE(SUM([Amount]), KEEPFILTERS('Sales'[Color] = \"Red\"))",
                "20",
            ),
            (
                "Current filtered sales",
                "CALCULATE(SUM([Amount]))",
                "20",
            ),
        )
        for name, expression, expected in definitions:
            with self.subTest(name=name):
                self.assertTrue(
                    controller.create_measure(name, expression),
                    controller.statusMessage,
                )
                self.assertEqual(controller.reportKpis[name], expected)

    def test_same_column_filter_arguments_combine_with_and(self) -> None:
        rows = [
            {"Color": "Blue", "Amount": "10"},
            {"Color": "Blue", "Amount": "20"},
            {"Color": "Green", "Amount": "30"},
        ]
        context = [{
            "id": "sales-id",
            "name": "Sales",
            "headers": ["Color", "Amount"],
            "rows": rows,
            "column_types": {"Color": "text", "Amount": "whole_number"},
        }]
        values = evaluate_measures(
            [{
                "name": "Amount range",
                "expression": (
                    "CALCULATE(SUM([Amount]), 'Sales'[Amount] >= 10, "
                    "'Sales'[Amount] <= 20)"
                ),
            }],
            rows,
            ["Color", "Amount"],
            "Sales",
            table_context=context,
            active_table_id="sales-id",
        )
        self.assertEqual(values["Amount range"], 30)

    def test_nested_calculate_keeps_the_outer_filter_context(self) -> None:
        rows = [
            {"Color": "Blue", "Region": "East", "Amount": "10"},
            {"Color": "Blue", "Region": "West", "Amount": "20"},
            {"Color": "Red", "Region": "East", "Amount": "30"},
        ]
        context = [{
            "id": "sales-id",
            "name": "Sales",
            "headers": ["Color", "Region", "Amount"],
            "rows": rows,
            "column_types": {
                "Color": "text",
                "Region": "text",
                "Amount": "whole_number",
            },
        }]
        values = evaluate_measures(
            [{
                "name": "Nested sales",
                "expression": (
                    "CALCULATE(CALCULATE(SUM([Amount]), "
                    "'Sales'[Color] = \"Blue\"), 'Sales'[Region] = \"East\")"
                ),
            }],
            rows,
            ["Color", "Region", "Amount"],
            "Sales",
            table_context=context,
            active_table_id="sales-id",
        )
        self.assertEqual(values["Nested sales"], 10)

    def test_filter_value_conversion_uses_saved_column_type(self) -> None:
        rows = [
            {"Active": "True", "Amount": "10"},
            {"Active": "False", "Amount": "20"},
        ]
        context = [{
            "id": "sales-id",
            "name": "Sales",
            "headers": ["Active", "Amount"],
            "rows": rows,
            "column_types": {"Active": "boolean", "Amount": "whole_number"},
        }]
        values = evaluate_measures(
            [{
                "name": "Active amount",
                "expression": "CALCULATE(SUM([Amount]), 'Sales'[Active] = TRUE())",
            }],
            rows,
            ["Active", "Amount"],
            "Sales",
            table_context=context,
            active_table_id="sales-id",
        )
        self.assertEqual(values["Active amount"], 10)

        with self.assertRaisesRegex(MeasureError, r"Boolean column.*TRUE\(\)"):
            evaluate_measures(
                [{
                    "name": "Invalid boolean amount",
                    "expression": "CALCULATE(SUM([Amount]), 'Sales'[Active] = \"True\")",
                }],
                rows,
                ["Active", "Amount"],
                "Sales",
                table_context=context,
                active_table_id="sales-id",
            )

    def test_date_datetime_and_time_filters_use_iso_literals(self) -> None:
        rows = [
            {
                "OrderDate": "2024-01-01",
                "CreatedAt": "2024-01-01T12:00:00",
                "StartTime": "08:00:00",
                "Amount": "10",
            },
            {
                "OrderDate": "2024-01-02",
                "CreatedAt": "2024-01-02T13:00:00",
                "StartTime": "09:30:00",
                "Amount": "20",
            },
        ]
        context = [{
            "id": "sales-id",
            "name": "Sales",
            "headers": ["OrderDate", "CreatedAt", "StartTime", "Amount"],
            "rows": rows,
            "column_types": {
                "OrderDate": "date",
                "CreatedAt": "datetime",
                "StartTime": "time",
                "Amount": "whole_number",
            },
        }]
        values = evaluate_measures(
            [
                {
                    "name": "After Jan one",
                    "expression": (
                        "CALCULATE(SUM([Amount]), "
                        "'Sales'[OrderDate] > \"2024-01-01\")"
                    ),
                },
                {
                    "name": "After noon",
                    "expression": (
                        "CALCULATE(SUM([Amount]), "
                        "'Sales'[CreatedAt] > \"2024-01-01T12:00:00\")"
                    ),
                },
                {
                    "name": "At or after nine",
                    "expression": (
                        "CALCULATE(SUM([Amount]), "
                        "'Sales'[StartTime] >= \"09:00:00\")"
                    ),
                },
            ],
            rows,
            ["OrderDate", "CreatedAt", "StartTime", "Amount"],
            "Sales",
            table_context=context,
            active_table_id="sales-id",
        )
        self.assertEqual(values, {
            "After Jan one": 20,
            "After noon": 20,
            "At or after nine": 20,
        })

    def test_blank_comparisons_coerce_using_the_saved_column_type(self) -> None:
        rows = [
            {
                "Amount": "",
                "Active": "",
                "Label": "",
                "OrderDate": "",
                "CreatedAt": "",
                "StartTime": "",
            },
            {
                "Amount": "0",
                "Active": "False",
                "Label": "",
                "OrderDate": "1899-12-30",
                "CreatedAt": "1899-12-30T00:00:00",
                "StartTime": "00:00:00",
            },
            {
                "Amount": "1",
                "Active": "True",
                "Label": "set",
                "OrderDate": "2024-01-01",
                "CreatedAt": "2024-01-01T00:00:00",
                "StartTime": "00:00:01",
            },
        ]
        context = [{
            "id": "sales-id",
            "name": "Sales",
            "headers": [
                "Amount", "Active", "Label", "OrderDate", "CreatedAt", "StartTime"
            ],
            "rows": rows,
            "column_types": {
                "Amount": "whole_number",
                "Active": "boolean",
                "Label": "text",
                "OrderDate": "date",
                "CreatedAt": "datetime",
                "StartTime": "time",
            },
        }]
        values = evaluate_measures(
            [
                {
                    "name": "Numeric zero includes blank",
                    "expression": "CALCULATE(COUNTROWS(), 'Sales'[Amount] = 0)",
                },
                {
                    "name": "False includes blank",
                    "expression": "CALCULATE(COUNTROWS(), 'Sales'[Active] = FALSE())",
                },
                {
                    "name": "Text blank",
                    "expression": "CALCULATE(COUNTROWS(), 'Sales'[Label] = BLANK())",
                },
                {
                    "name": "Date blank",
                    "expression": "CALCULATE(COUNTROWS(), 'Sales'[OrderDate] = BLANK())",
                },
                {
                    "name": "DateTime blank",
                    "expression": "CALCULATE(COUNTROWS(), 'Sales'[CreatedAt] = BLANK())",
                },
                {
                    "name": "Time blank",
                    "expression": "CALCULATE(COUNTROWS(), 'Sales'[StartTime] = BLANK())",
                },
            ],
            rows,
            context[0]["headers"],
            "Sales",
            table_context=context,
            active_table_id="sales-id",
        )
        self.assertEqual(values, {
            "Numeric zero includes blank": 2,
            "False includes blank": 2,
            "Text blank": 2,
            "Date blank": 2,
            "DateTime blank": 2,
            "Time blank": 2,
        })

    def test_nested_boolean_filter_preserves_outer_ytd_period(self) -> None:
        calendar_rows = [
            {"Date": "2024-01-01", "Year": "2024"},
            {"Date": "2024-03-15", "Year": "2024"},
            {"Date": "2024-03-16", "Year": "2024"},
            {"Date": "2024-12-01", "Year": "2024"},
        ]
        order_rows = [
            {"OrderDate": "2024-01-01", "Amount": "10"},
            {"OrderDate": "2024-03-15", "Amount": "30"},
            {"OrderDate": "2024-03-16", "Amount": "40"},
            {"OrderDate": "2024-12-01", "Amount": "100"},
        ]
        values = evaluate_measures(
            [{
                "name": "YTD 2024 sales",
                "expression": (
                    "CALCULATE(CALCULATE(SUM([Amount]), "
                    "'Calendar'[Year] = 2024), DATESYTD('Calendar'[Date]))"
                ),
            }],
            order_rows,
            ["OrderDate", "Amount"],
            "Orders",
            table_context=[
                {
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date", "Year"],
                    "rows": calendar_rows,
                    "filter_rows": [calendar_rows[1]],
                    "filter_column_rows": {"Date": {1}},
                    "filter_context_complete": True,
                    "column_types": {"Date": "date", "Year": "whole_number"},
                    "date_column": "Date",
                },
                {
                    "id": "orders-id",
                    "name": "Orders",
                    "headers": ["OrderDate", "Amount"],
                    "rows": order_rows,
                    "column_types": {
                        "OrderDate": "date",
                        "Amount": "whole_number",
                    },
                },
            ],
            relationships=[{
                "relationship_version": 1,
                "id": "calendar-orders",
                "from": "Calendar[Date]",
                "to": "Orders[OrderDate]",
                "from_table_id": "calendar-id",
                "from_column": "Date",
                "to_table_id": "orders-id",
                "to_column": "OrderDate",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": True,
            }],
            filter_table_ids={"calendar-id"},
            active_table_id="orders-id",
        )
        self.assertEqual(values["YTD 2024 sales"], 40)

    def test_qualified_column_can_match_a_measure_name(self) -> None:
        rows = [
            {"Amount": "10", "SalesAmount": "100"},
            {"Amount": "20", "SalesAmount": "200"},
        ]
        context = [{
            "id": "sales-id",
            "name": "Sales",
            "headers": ["Amount", "SalesAmount"],
            "rows": rows,
            "column_types": {
                "Amount": "whole_number",
                "SalesAmount": "whole_number",
            },
        }]
        values = evaluate_measures(
            [
                {"name": "Amount", "expression": "SUM([SalesAmount])"},
                {
                    "name": "Filtered sales",
                    "expression": (
                        "CALCULATE(SUM([SalesAmount]), 'Sales'[Amount] > 10)"
                    ),
                },
            ],
            rows,
            context[0]["headers"],
            "Sales",
            table_context=context,
            active_table_id="sales-id",
        )
        self.assertEqual(values["Filtered sales"], 200)

    def test_opaque_existing_filter_context_is_rejected_for_replacement(self) -> None:
        rows = [
            {"Color": "Red", "Amount": "10"},
            {"Color": "Blue", "Amount": "20"},
        ]
        with self.assertRaisesRegex(MeasureError, "per-column filter context"):
            evaluate_measures(
                [{
                    "name": "Blue amount",
                    "expression": "CALCULATE(SUM([Amount]), 'Sales'[Color] = \"Blue\")",
                }],
                rows,
                ["Color", "Amount"],
                "Sales",
                table_context=[{
                    "id": "sales-id",
                    "name": "Sales",
                    "headers": ["Color", "Amount"],
                    "rows": rows,
                    "filter_rows": [rows[0]],
                    "column_types": {"Color": "text", "Amount": "whole_number"},
                }],
                filter_table_ids={"sales-id"},
                active_table_id="sales-id",
            )

    def test_parser_rejects_unsupported_filter_shapes_and_literal_positions(self) -> None:
        for expression, message in (
            (
                "CALCULATE(SUM([Amount]), 'Sales'[Amount] = 'Sales'[ID])",
                "one column with a scalar literal",
            ),
            (
                "CALCULATE(SUM([Amount]), 'Sales'[Color] = \"Blue\" || 'Sales'[Region] = \"East\")",
                "only one column",
            ),

            (
                "SUM([Amount]) + IF(TRUE(), \"Blue\", \"Red\")",
                "String literals are supported only",
            ),
            (
                "KEEPFILTERS('Sales'[Color] = \"Blue\")",
                "only as a CALCULATE",
            ),
        ):
            with self.subTest(expression=expression):
                with self.assertRaisesRegex(MeasureError, message):
                    normalize_measure("Invalid filter", expression)

    def test_measure_references_cannot_be_used_as_boolean_filter_columns(self) -> None:
        rows = [{"Amount": "10", "Region": "East"}]
        with self.assertRaisesRegex(MeasureError, "cannot reference measures"):
            evaluate_measures(
                [
                    {"name": "Amount total", "expression": "SUM([Amount])"},
                    {
                        "name": "Invalid filter",
                        "expression": "CALCULATE(SUM([Amount]), [Amount total] = 10)",
                    },
                ],
                rows,
                ["Amount", "Region"],
                "Sales",
                measure_names=["Invalid filter"],
            )

    def test_filter_table_preserves_correlated_rows_and_duplicate_rows(self) -> None:
        rows = [
            {"Color": "Red", "Region": "East", "Amount": "10"},
            {"Color": "Red", "Region": "West", "Amount": "12"},
            {"Color": "Blue", "Region": "West", "Amount": "20"},
            {"Color": "Blue", "Region": "East", "Amount": "30"},
            {"Color": "Red", "Region": "East", "Amount": "10"},
            {"Color": "Green", "Region": "North", "Amount": "5"},
        ]
        context = [{
            "id": "sales-id",
            "name": "Sales",
            "headers": ["Color", "Region", "Amount"],
            "rows": rows,
            "column_types": {
                "Color": "text",
                "Region": "text",
                "Amount": "whole_number",
            },
        }]
        values = evaluate_measures(
            [
                {
                    "name": "Correlated sales",
                    "expression": (
                        "CALCULATE(SUM([Amount]), FILTER('Sales', "
                        "('Sales'[Color] = \"Red\" && 'Sales'[Region] = \"East\") || "
                        "('Sales'[Color] = \"Blue\" && 'Sales'[Region] = \"West\")))"
                    ),
                },
                {
                    "name": "Function logic sales",
                    "expression": (
                        "CALCULATE(SUM([Amount]), FILTER('Sales', "
                        "NOT(OR('Sales'[Color] = \"Red\", 'Sales'[Color] = \"Blue\"))))"
                    ),
                },
                {
                    "name": "Function AND sales",
                    "expression": (
                        "CALCULATE(SUM([Amount]), FILTER('Sales', "
                        "AND('Sales'[Color] = \"Red\", 'Sales'[Region] = \"East\")))"
                    ),
                },
                {
                    "name": "Scalar left comparison",
                    "expression": (
                        "CALCULATE(SUM([Amount]), FILTER('Sales', 10 < 'Sales'[Amount]))"
                    ),
                },
            ],
            rows,
            context[0]["headers"],
            "Sales",
            table_context=context,
            active_table_id="sales-id",
        )
        self.assertEqual(values["Correlated sales"], 40)
        self.assertEqual(values["Function logic sales"], 5)
        self.assertEqual(values["Function AND sales"], 20)
        self.assertEqual(values["Scalar left comparison"], 62)

    def test_filter_table_evaluates_its_input_in_current_target_context(self) -> None:
        rows = [
            {"Color": "Red", "Amount": "10"},
            {"Color": "Blue", "Amount": "20"},
        ]
        context = [{
            "id": "sales-id",
            "name": "Sales",
            "headers": ["Color", "Amount"],
            "rows": rows,
            "filter_rows": [rows[1]],
            "filter_column_rows": {"Color": {1}},
            "filter_context_complete": True,
            "column_types": {"Color": "text", "Amount": "whole_number"},
        }]
        values = evaluate_measures(
            [
                {
                    "name": "Matching visible row",
                    "expression": (
                        "CALCULATE(SUM([Amount]), "
                        "FILTER('Sales', 'Sales'[Color] = \"Blue\"))"
                    ),
                },
                {
                    "name": "Excluded row stays excluded",
                    "expression": (
                        "CALCULATE(SUM([Amount]), "
                        "FILTER('Sales', 'Sales'[Color] = \"Red\"))"
                    ),
                },
            ],
            rows,
            context[0]["headers"],
            "Sales",
            table_context=context,
            filter_table_ids={"sales-id"},
            active_table_id="sales-id",
        )
        self.assertEqual(values["Matching visible row"], 20)
        self.assertEqual(values["Excluded row stays excluded"], 0)

    def test_filter_table_text_comparisons_follow_local_case_sensitive_rules(self) -> None:
        rows = [
            {"Color": "Blue", "Amount": "20"},
            {"Color": "blue", "Amount": "10"},
        ]
        context = [{
            "id": "sales-id",
            "name": "Sales",
            "headers": ["Color", "Amount"],
            "rows": rows,
            "column_types": {"Color": "text", "Amount": "whole_number"},
        }]
        values = evaluate_measures(
            [
                {
                    "name": "Lowercase match",
                    "expression": (
                        "CALCULATE(SUM([Amount]), FILTER('Sales', "
                        "'Sales'[Color] = \"blue\"))"
                    ),
                },
                {
                    "name": "Case-sensitive complement",
                    "expression": (
                        "CALCULATE(SUM([Amount]), FILTER('Sales', "
                        "'Sales'[Color] <> \"blue\"))"
                    ),
                },
            ],
            rows,
            context[0]["headers"],
            "Sales",
            table_context=context,
            active_table_id="sales-id",
        )
        self.assertEqual(values["Lowercase match"], 10)
        self.assertEqual(values["Case-sensitive complement"], 20)

    def test_filter_table_preserves_other_table_filter_roots_and_relationships(self) -> None:
        categories = [
            {"CategoryId": "A", "Segment": "Preferred"},
            {"CategoryId": "B", "Segment": "Other"},
        ]
        sales = [
            {"CategoryId": "A", "Amount": "10"},
            {"CategoryId": "A", "Amount": "20"},
            {"CategoryId": "B", "Amount": "100"},
        ]
        values = evaluate_measures(
            [{
                "name": "Preferred high-value sales",
                "expression": (
                    "CALCULATE(SUM([Amount]), FILTER('Sales', "
                    "'Sales'[Amount] > 15))"
                ),
            }],
            sales,
            ["CategoryId", "Amount"],
            "Sales",
            table_context=[
                {
                    "id": "category-id",
                    "name": "Category",
                    "headers": ["CategoryId", "Segment"],
                    "rows": categories,
                    "filter_rows": [categories[0]],
                    "filter_column_rows": {"Segment": {0}},
                    "filter_context_complete": True,
                    "column_types": {"CategoryId": "text", "Segment": "text"},
                },
                {
                    "id": "sales-id",
                    "name": "Sales",
                    "headers": ["CategoryId", "Amount"],
                    "rows": sales,
                    "column_types": {"CategoryId": "text", "Amount": "whole_number"},
                },
            ],
            relationships=[{
                "relationship_version": 1,
                "id": "category-sales",
                "from": "Category[CategoryId]",
                "to": "Sales[CategoryId]",
                "from_table_id": "category-id",
                "from_column": "CategoryId",
                "to_table_id": "sales-id",
                "to_column": "CategoryId",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": True,
            }],
            filter_table_ids={"category-id"},
            active_table_id="sales-id",
        )
        self.assertEqual(values["Preferred high-value sales"], 20)

    def test_filter_table_uses_typed_blank_coercion(self) -> None:
        rows = [{"Amount": ""}, {"Amount": "0"}, {"Amount": "2"}]
        values = evaluate_measures(
            [{
                "name": "Blank or zero rows",
                "expression": (
                    "CALCULATE(COUNTROWS(), "
                    "FILTER('Sales', 'Sales'[Amount] = BLANK()))"
                ),
            }],
            rows,
            ["Amount"],
            "Sales",
            table_context=[{
                "id": "sales-id",
                "name": "Sales",
                "headers": ["Amount"],
                "rows": rows,
                "column_types": {"Amount": "whole_number"},
            }],
            active_table_id="sales-id",
        )
        self.assertEqual(values["Blank or zero rows"], 2)

    def test_parser_rejects_unsupported_filter_table_forms(self) -> None:
        for expression, message in (
            (
                "FILTER('Sales', 'Sales'[Amount] > 10)",
                "sole table-valued CALCULATE filter argument",
            ),
            (
                "CALCULATE(SUM([Amount]), FILTER('Sales', 'Other'[Amount] > 10))",
                "same loaded table",
            ),
            (
                "CALCULATE(SUM([Amount]), FILTER('Sales', [Amount] > 10))",
                "qualified column",
            ),
            (
                "CALCULATE(SUM([Amount]), FILTER('Sales', SUM([Amount]) > 10))",
                "scalar literal",
            ),
            (
                "CALCULATE(SUM([Amount]), FILTER('Sales', 'Sales'[Amount] > 10), "
                "'Sales'[Color] = \"Blue\")",
                "only CALCULATE filter argument",
            ),
            (
                "CALCULATE(SUM([Amount]), FILTER('Sales', 'Sales'[Amount] > 10), "
                "FILTER('Sales', 'Sales'[Color] = \"Blue\"))",
                "only CALCULATE filter argument",
            ),
            (
                "CALCULATE(SUM([Amount]), FILTER(FILTER('Sales', "
                "'Sales'[Amount] > 10), 'Sales'[Color] = \"Blue\"))",
                "base table name",
            ),
            (
                "CALCULATE(SUM([Amount]), "
                "KEEPFILTERS(FILTER('Sales', 'Sales'[Amount] > 10)))",
                "table-valued FILTER",
            ),
        ):
            with self.subTest(expression=expression):
                with self.assertRaisesRegex(MeasureError, message):
                    normalize_measure("Invalid table filter", expression)

    def test_filter_table_rejects_unloaded_fields_and_unsupported_comparisons(self) -> None:
        rows = [{"Color": "Blue", "Amount": "10"}]
        context = [{
            "id": "sales-id",
            "name": "Sales",
            "headers": ["Color", "Amount"],
            "rows": rows,
            "column_types": {"Color": "text", "Amount": "whole_number"},
        }]
        for expression, message in (
            (
                "CALCULATE(SUM([Amount]), "
                "FILTER('Missing', 'Missing'[Color] = \"Blue\"))",
                "not loaded",
            ),
            (
                "CALCULATE(SUM([Amount]), "
                "FILTER('Sales', 'Sales'[Missing] = \"Blue\"))",
                "does not exist",
            ),
            (
                "CALCULATE(SUM([Amount]), "
                "FILTER('Sales', 'Sales'[Color] > \"Blue\"))",
                "only equality filters",
            ),
            (
                "CALCULATE(SUM([Amount]), "
                "FILTER('Sales', 'Sales'[Amount] = \"10\"))",
                "needs a numeric CALCULATE filter value",
            ),
        ):
            with self.subTest(expression=expression):
                with self.assertRaisesRegex(MeasureError, message):
                    evaluate_measures(
                        [{"name": "Invalid", "expression": expression}],
                        rows,
                        context[0]["headers"],
                        "Sales",
                        table_context=context,
                        active_table_id="sales-id",
                    )

    def test_boolean_filter_cannot_rebuild_an_opaque_table_filter_context(self) -> None:
        rows = [
            {"Color": "Blue", "Amount": "10"},
            {"Color": "Red", "Amount": "20"},
        ]
        with self.assertRaisesRegex(MeasureError, "cannot replace a table-valued FILTER rowset"):
            evaluate_measures(
                [{
                    "name": "Nested replacement",
                    "expression": (
                        "CALCULATE(CALCULATE(SUM([Amount]), "
                        "'Sales'[Color] = \"Blue\"), FILTER('Sales', "
                        "'Sales'[Amount] > 0))"
                    ),
                }],
                rows,
                ["Color", "Amount"],
                "Sales",
                table_context=[{
                    "id": "sales-id",
                    "name": "Sales",
                    "headers": ["Color", "Amount"],
                    "rows": rows,
                    "column_types": {"Color": "text", "Amount": "whole_number"},
                }],
                active_table_id="sales-id",
            )

    def test_measure_lifecycle_recomputes_table_filter_after_reopen(self) -> None:
        controller = self.controller("settings.ini")
        self.load_sales(controller)
        self.assertTrue(controller.create_measure(
            "Blue sales",
            "CALCULATE(SUM([Amount]), "
            "FILTER('Sales', 'Sales'[Color] = \"Blue\"))",
        ), controller.statusMessage)
        self.assertTrue(controller.create_measure(
            "Twice blue sales", "[Blue sales] + [Blue sales]"
        ), controller.statusMessage)
        self.assertTrue(controller.create_measure(
            "Sales total", "SUM([Amount])"
        ), controller.statusMessage)
        self.assertTrue(controller.create_measure(
            "Blue sales through total",
            "CALCULATE([Sales total], FILTER('Sales', "
            "'Sales'[Color] = \"Blue\"))",
        ), controller.statusMessage)
        self.assertTrue(controller.create_measure(
            "Total after table filter", "[Sales total]"
        ), controller.statusMessage)
        self.assertTrue(controller.create_measure(
            "Direct total after table filter", "SUM([Amount])"
        ), controller.statusMessage)
        self.assertEqual(controller.reportKpis["Blue sales"], "40")
        self.assertEqual(controller.reportKpis["Twice blue sales"], "80")
        self.assertEqual(controller.reportKpis["Sales total"], "157")
        self.assertEqual(controller.reportKpis["Blue sales through total"], "40")
        self.assertEqual(controller.reportKpis["Total after table filter"], "157")
        self.assertEqual(controller.reportKpis["Direct total after table filter"], "157")
        project_path = self.root / "calculate-table-filter.npa"
        self.assertTrue(controller._save_to(project_path))

        self.sales_path.write_text(
            "ID,Color,Region,Amount,Active\n"
            "1,Red,East,21,True\n"
            "2,Blue,East,12,False\n"
            "3,Green,East,7,True\n"
            "4,Blue,West,31,True\n"
            "5,Green,West,40,False\n"
            "6,Red,West,50,True\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Blue sales"], "43")
        self.assertEqual(reopened.reportKpis["Twice blue sales"], "86")
        self.assertEqual(reopened.reportKpis["Sales total"], "161")
        self.assertEqual(reopened.reportKpis["Blue sales through total"], "43")
        self.assertEqual(reopened.reportKpis["Total after table filter"], "161")
        self.assertEqual(reopened.reportKpis["Direct total after table filter"], "161")

    def test_measure_lifecycle_recomputes_boolean_filter_after_reopen(self) -> None:
        controller = self.controller("settings.ini")
        self.load_sales(controller)
        sales_id = str(controller.activeTableId)
        self.assertTrue(controller.addPageFilterRule(
            sales_id, "Color", "equals", "Red", "", "", "and"
        ))
        self.assertTrue(controller.addPageFilterRule(
            sales_id, "Region", "equals", "East", "", "", "and"
        ))
        self.assertTrue(controller.create_measure(
            "Blue sales",
            "CALCULATE(SUM([Amount]), 'Sales'[Color] = \"Blue\")",
        ), controller.statusMessage)
        self.assertTrue(controller.create_measure(
            "Blue sales intersection",
            "CALCULATE(SUM([Amount]), KEEPFILTERS('Sales'[Color] = \"Blue\"))",
        ), controller.statusMessage)
        project_path = self.root / "calculate-filters.npa"
        self.assertTrue(controller._save_to(project_path))

        self.sales_path.write_text(
            "ID,Color,Region,Amount,Active\n"
            "1,Red,East,21,True\n"
            "2,Blue,East,12,False\n"
            "3,Green,East,7,True\n"
            "4,Blue,West,31,True\n"
            "5,Green,West,40,False\n"
            "6,Red,West,50,True\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Blue sales"], "12")
        self.assertEqual(reopened.reportKpis["Blue sales intersection"], "0")

    def test_removefilters_clears_columns_tables_and_all_filters(self) -> None:
        rows = [
            {"Color": "Red", "Region": "East", "Amount": "20"},
            {"Color": "Blue", "Region": "East", "Amount": "10"},
            {"Color": "Green", "Region": "East", "Amount": "7"},
            {"Color": "Blue", "Region": "West", "Amount": "30"},
            {"Color": "Green", "Region": "West", "Amount": "40"},
            {"Color": "Red", "Region": "West", "Amount": "50"},
        ]
        context = [{
            "id": "sales-id",
            "name": "Sales",
            "headers": ["Color", "Region", "Amount"],
            "rows": rows,
            "column_types": {"Color": "text", "Region": "text", "Amount": "whole_number"},
            "filter_rows": [rows[0]],
            "filter_column_rows": {"Color": {0, 5}, "Region": {0, 1, 2}},
            "filter_context_complete": True,
        }]
        values = evaluate_measures(
            [
                {"name": "Remove Color", "expression": "CALCULATE(SUM([Amount]), REMOVEFILTERS('Sales'[Color]))"},
                {"name": "Remove Region", "expression": "CALCULATE(SUM([Amount]), REMOVEFILTERS('Sales'[Region]))"},
                {"name": "Remove Both", "expression": "CALCULATE(SUM([Amount]), REMOVEFILTERS('Sales'[Color], 'Sales'[Region]))"},
                {"name": "Remove Table", "expression": "CALCULATE(SUM([Amount]), REMOVEFILTERS('Sales'))"},
                {"name": "Remove All", "expression": "CALCULATE(SUM([Amount]), REMOVEFILTERS())"},
                {"name": "Nested Remove Color", "expression": "CALCULATE(CALCULATE(SUM([Amount]), REMOVEFILTERS('Sales'[Color])), 'Sales'[Region] = \"East\")"},
                {"name": "Nested Remove All", "expression": "CALCULATE(CALCULATE(SUM([Amount]), REMOVEFILTERS()), 'Sales'[Color] = \"Blue\")"},
                {"name": "Outer Context", "expression": "SUM([Amount])"},
            ],
            rows,
            context[0]["headers"],
            "Sales",
            table_context=context,
            filter_table_ids={"sales-id"},
            active_table_id="sales-id",
        )
        self.assertEqual(values, {
            "Remove Color": 37,
            "Remove Region": 70,
            "Remove Both": 157,
            "Remove Table": 157,
            "Remove All": 157,
            "Nested Remove Color": 37,
            "Nested Remove All": 157,
            "Outer Context": 20,
        })

    def test_removefilters_preserves_unrelated_relationship_roots(self) -> None:
        categories = [
            {"CategoryId": "A", "Segment": "Preferred"},
            {"CategoryId": "B", "Segment": "Other"},
        ]
        sales = [
            {"CategoryId": "A", "Region": "East", "Amount": "10"},
            {"CategoryId": "A", "Region": "West", "Amount": "20"},
            {"CategoryId": "B", "Region": "East", "Amount": "100"},
        ]
        values = evaluate_measures(
            [
                {"name": "Clear Category", "expression": "CALCULATE(SUM([Amount]), REMOVEFILTERS('Category'))"},
                {"name": "Clear Sales", "expression": "CALCULATE(SUM([Amount]), REMOVEFILTERS('Sales'))"},
                {"name": "Clear Sales Region", "expression": "CALCULATE(SUM([Amount]), REMOVEFILTERS('Sales'[Region]))"},
                {"name": "Clear All", "expression": "CALCULATE(SUM([Amount]), REMOVEFILTERS())"},
            ],
            sales,
            ["CategoryId", "Region", "Amount"],
            "Sales",
            table_context=[
                {
                    "id": "category-id",
                    "name": "Category",
                    "headers": ["CategoryId", "Segment"],
                    "rows": categories,
                    "column_types": {"CategoryId": "text", "Segment": "text"},
                    "filter_rows": [categories[0]],
                    "filter_column_rows": {"Segment": {0}},
                    "filter_context_complete": True,
                },
                {
                    "id": "sales-id",
                    "name": "Sales",
                    "headers": ["CategoryId", "Region", "Amount"],
                    "rows": sales,
                    "column_types": {"CategoryId": "text", "Region": "text", "Amount": "whole_number"},
                    "filter_rows": [sales[0], sales[2]],
                    "filter_column_rows": {"Region": {0, 2}},
                    "filter_context_complete": True,
                },
            ],
            relationships=[{
                "relationship_version": 1,
                "id": "category-sales",
                "from": "Category[CategoryId]",
                "to": "Sales[CategoryId]",
                "from_table_id": "category-id",
                "from_column": "CategoryId",
                "to_table_id": "sales-id",
                "to_column": "CategoryId",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": True,
            }],
            filter_table_ids={"category-id", "sales-id"},
            active_table_id="sales-id",
        )
        self.assertEqual(values, {
            "Clear Category": 110,
            "Clear Sales": 30,
            "Clear Sales Region": 30,
            "Clear All": 130,
        })

    def test_removefilters_handles_opaque_table_filter_by_table_or_all_only(self) -> None:
        rows = [
            {"Color": "Red", "Amount": "10"},
            {"Color": "Blue", "Amount": "20"},
        ]
        context = [{
            "id": "sales-id",
            "name": "Sales",
            "headers": ["Color", "Amount"],
            "rows": rows,
            "column_types": {"Color": "text", "Amount": "whole_number"},
            "filter_rows": [rows[0]],
            "filter_table_rows": {0},
            "filter_context_complete": False,
        }]
        values = evaluate_measures(
            [
                {"name": "Remove Table", "expression": "CALCULATE(SUM([Amount]), REMOVEFILTERS('Sales'))"},
                {"name": "Remove All", "expression": "CALCULATE(SUM([Amount]), REMOVEFILTERS())"},
                {"name": "Outer Context", "expression": "SUM([Amount])"},
            ],
            rows,
            context[0]["headers"],
            "Sales",
            table_context=context,
            filter_table_ids={"sales-id"},
            active_table_id="sales-id",
        )
        self.assertEqual(values, {"Remove Table": 30, "Remove All": 30, "Outer Context": 10})
        with self.assertRaisesRegex(MeasureError, "opaque table-valued FILTER rowset"):
            evaluate_measures(
                [{
                    "name": "Remove Color",
                    "expression": "CALCULATE(SUM([Amount]), REMOVEFILTERS('Sales'[Color]))",
                }],
                rows,
                context[0]["headers"],
                "Sales",
                table_context=context,
                filter_table_ids={"sales-id"},
                active_table_id="sales-id",
            )
        incomplete_context = [{
            "id": "sales-id",
            "name": "Sales",
            "headers": ["Color", "Amount"],
            "rows": rows,
            "filter_rows": [rows[0]],
            "filter_context_complete": False,
        }]
        with self.assertRaisesRegex(MeasureError, "per-column filter context is unavailable"):
            evaluate_measures(
                [{
                    "name": "Remove Color",
                    "expression": "CALCULATE(SUM([Amount]), REMOVEFILTERS('Sales'[Color]))",
                }],
                rows,
                incomplete_context[0]["headers"],
                "Sales",
                table_context=incomplete_context,
                filter_table_ids={"sales-id"},
                active_table_id="sales-id",
            )

    def test_removefilters_parser_and_target_validation(self) -> None:
        for expression in (
            "CALCULATE(SUM([Amount]), REMOVEFILTERS())",
            "CALCULATE(SUM([Amount]), REMOVEFILTERS('Sales'))",
            "CALCULATE(SUM([Amount]), REMOVEFILTERS('Sales'[Color], 'Sales'[Region]))",
        ):
            with self.subTest(expression=expression):
                normalize_measure("Valid REMOVEFILTERS", expression)

        for expression in (
            "REMOVEFILTERS()",
            "CALCULATE(SUM([Amount]), REMOVEFILTERS(), 'Sales'[Color] = \"Blue\")",
            "CALCULATE(SUM([Amount]), REMOVEFILTERS('Sales', 'Sales'[Color]))",
            "CALCULATE(SUM([Amount]), REMOVEFILTERS([Color]))",
            "CALCULATE(SUM([Amount]), REMOVEFILTERS('Sales'[Color], 'Calendar'[Date]))",
            "CALCULATE(SUM([Amount]), REMOVEFILTERS(1))",
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(MeasureError):
                    normalize_measure("Invalid REMOVEFILTERS", expression)

        rows = [{"Color": "Red", "Amount": "10"}]
        with self.assertRaisesRegex(MeasureError, "Table 'Missing' is not loaded"):
            evaluate_measures(
                [{"name": "Missing table", "expression": "CALCULATE(SUM([Amount]), REMOVEFILTERS('Missing'))"}],
                rows,
                ["Color", "Amount"],
                "Sales",
            )
        with self.assertRaisesRegex(MeasureError, "Column 'Missing' does not exist"):
            evaluate_measures(
                [{"name": "Missing column", "expression": "CALCULATE(SUM([Amount]), REMOVEFILTERS('Sales'[Missing]))"}],
                rows,
                ["Color", "Amount"],
                "Sales",
                table_context=[{
                    "id": "sales-id",
                    "name": "Sales",
                    "headers": ["Color", "Amount"],
                    "rows": rows,
                }],
                active_table_id="sales-id",
            )
        with self.assertRaisesRegex(MeasureError, "Table name 'Sales' is ambiguous"):
            evaluate_measures(
                [{"name": "Ambiguous table", "expression": "CALCULATE(SUM([Amount]), REMOVEFILTERS('Sales'))"}],
                rows,
                ["Color", "Amount"],
                "Sales",
                table_context=[
                    {"id": "sales-one", "name": "Sales", "headers": ["Color", "Amount"], "rows": rows},
                    {"id": "sales-two", "name": "Sales", "headers": ["Color", "Amount"], "rows": rows},
                ],
                active_table_id="sales-one",
            )

    def test_removefilters_measure_lifecycle_after_source_change(self) -> None:
        controller = self.controller("settings.ini")
        self.load_sales(controller)
        sales_id = str(controller.activeTableId)
        self.assertTrue(controller.addPageFilterRule(
            sales_id, "Color", "equals", "Red", "", "", "and"
        ))
        self.assertTrue(controller.addPageFilterRule(
            sales_id, "Region", "equals", "East", "", "", "and"
        ))
        for name, expression in (
            ("Remove Color", "CALCULATE(SUM([Amount]), REMOVEFILTERS('Sales'[Color]))"),
            ("Remove Region", "CALCULATE(SUM([Amount]), REMOVEFILTERS('Sales'[Region]))"),
            ("Remove Table", "CALCULATE(SUM([Amount]), REMOVEFILTERS('Sales'))"),
            ("Remove All", "CALCULATE(SUM([Amount]), REMOVEFILTERS())"),
        ):
            self.assertTrue(controller.create_measure(name, expression), controller.statusMessage)
        project_path = self.root / "removefilters.npa"
        self.assertTrue(controller._save_to(project_path))

        self.sales_path.write_text(
            "ID,Color,Region,Amount,Active\n"
            "1,Red,East,21,True\n"
            "2,Blue,East,12,False\n"
            "3,Green,East,7,True\n"
            "4,Blue,West,31,True\n"
            "5,Green,West,40,False\n"
            "6,Red,West,50,True\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Remove Color"], "40")
        self.assertEqual(reopened.reportKpis["Remove Region"], "71")
        self.assertEqual(reopened.reportKpis["Remove Table"], "161")
        self.assertEqual(reopened.reportKpis["Remove All"], "161")

    def test_all_modifier_clears_columns_table_and_all_filters(self) -> None:
        rows = [
            {"Color": "Red", "Region": "East", "Amount": "20"},
            {"Color": "Blue", "Region": "East", "Amount": "10"},
            {"Color": "Green", "Region": "East", "Amount": "7"},
            {"Color": "Blue", "Region": "West", "Amount": "30"},
            {"Color": "Green", "Region": "West", "Amount": "40"},
            {"Color": "Red", "Region": "West", "Amount": "50"},
        ]
        context = [{
            "id": "sales-id",
            "name": "Sales",
            "headers": ["Color", "Region", "Amount"],
            "rows": rows,
            "column_types": {"Color": "text", "Region": "text", "Amount": "whole_number"},
            "filter_rows": [rows[0]],
            "filter_column_rows": {"Color": {0, 5}, "Region": {0, 1, 2}},
            "filter_context_complete": True,
        }]
        values = evaluate_measures(
            [
                {"name": "All Color", "expression": "CALCULATE(SUM([Amount]), ALL('Sales'[Color]))"},
                {"name": "All Region", "expression": "CALCULATE(SUM([Amount]), ALL('Sales'[Region]))"},
                {"name": "All Both", "expression": "CALCULATE(SUM([Amount]), ALL('Sales'[Color], 'Sales'[Region]))"},
                {"name": "All Table", "expression": "CALCULATE(SUM([Amount]), ALL('Sales'))"},
                {"name": "All Context", "expression": "CALCULATE(SUM([Amount]), ALL())"},
                {"name": "Nested All Color", "expression": "CALCULATE(CALCULATE(SUM([Amount]), ALL('Sales'[Color])), 'Sales'[Region] = \"East\")"},
                {"name": "Nested All Context", "expression": "CALCULATE(CALCULATE(SUM([Amount]), ALL()), 'Sales'[Color] = \"Blue\")"},
                {"name": "Outer Context", "expression": "SUM([Amount])"},
            ],
            rows,
            context[0]["headers"],
            "Sales",
            table_context=context,
            filter_table_ids={"sales-id"},
            active_table_id="sales-id",
        )
        self.assertEqual(values, {
            "All Color": 37,
            "All Region": 70,
            "All Both": 157,
            "All Table": 157,
            "All Context": 157,
            "Nested All Color": 37,
            "Nested All Context": 157,
            "Outer Context": 20,
        })

    def test_all_modifier_preserves_unrelated_relationship_roots(self) -> None:
        categories = [
            {"CategoryId": "A", "Segment": "Preferred"},
            {"CategoryId": "B", "Segment": "Other"},
        ]
        sales = [
            {"CategoryId": "A", "Region": "East", "Amount": "10"},
            {"CategoryId": "A", "Region": "West", "Amount": "20"},
            {"CategoryId": "B", "Region": "East", "Amount": "100"},
        ]
        values = evaluate_measures(
            [
                {"name": "All Category", "expression": "CALCULATE(SUM([Amount]), ALL('Category'))"},
                {"name": "All Sales", "expression": "CALCULATE(SUM([Amount]), ALL('Sales'))"},
                {"name": "All Region", "expression": "CALCULATE(SUM([Amount]), ALL('Sales'[Region]))"},
                {"name": "All Context", "expression": "CALCULATE(SUM([Amount]), ALL())"},
                {"name": "ALL Amounts with Other Roots", "expression": "SUMX(ALL('Sales'[Amount]), 'Sales'[Amount])"},
            ],
            sales,
            ["CategoryId", "Region", "Amount"],
            "Sales",
            table_context=[
                {
                    "id": "category-id",
                    "name": "Category",
                    "headers": ["CategoryId", "Segment"],
                    "rows": categories,
                    "column_types": {"CategoryId": "text", "Segment": "text"},
                    "filter_rows": [categories[0]],
                    "filter_column_rows": {"Segment": {0}},
                    "filter_context_complete": True,
                },
                {
                    "id": "sales-id",
                    "name": "Sales",
                    "headers": ["CategoryId", "Region", "Amount"],
                    "rows": sales,
                    "column_types": {"CategoryId": "text", "Region": "text", "Amount": "whole_number"},
                    "filter_rows": [sales[0], sales[2]],
                    "filter_column_rows": {"Region": {0, 2}},
                    "filter_context_complete": True,
                },
            ],
            relationships=[{
                "relationship_version": 1,
                "id": "category-sales",
                "from": "Category[CategoryId]",
                "to": "Sales[CategoryId]",
                "from_table_id": "category-id",
                "from_column": "CategoryId",
                "to_table_id": "sales-id",
                "to_column": "CategoryId",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": True,
            }],
            filter_table_ids={"category-id", "sales-id"},
            active_table_id="sales-id",
        )
        self.assertEqual(values, {
            "All Category": 110,
            "All Sales": 30,
            "All Region": 30,
            "All Context": 130,
            "ALL Amounts with Other Roots": 10,
        })

    def test_all_modifier_parser_and_target_validation(self) -> None:
        for expression in (
            "CALCULATE(SUM([Amount]), ALL())",
            "CALCULATE(SUM([Amount]), ALL('Sales'))",
            "CALCULATE(SUM([Amount]), ALL('Sales'[Color], 'Sales'[Region]))",
        ):
            with self.subTest(expression=expression):
                normalize_measure("Valid ALL", expression)

        for expression in (
            "CALCULATE(SUM([Amount]), ALLNOBLANKROW('Sales'))",
            "CALCULATE(SUM([Amount]), ALLNOBLANKROW('Sales'[Color]))",
            "CALCULATE(COUNTROWS(ALLNOBLANKROW('Sales'[Color], 'Sales'[Region])), ALLNOBLANKROW('Sales'))",
        ):
            with self.subTest(expression=expression):
                normalize_measure("Valid ALLNOBLANKROW", expression)

        for expression in (
            "ALL()",
            "CALCULATE(SUM([Amount]), ALL(), 'Sales'[Color] = \"Blue\")",
            "CALCULATE(SUM([Amount]), ALL('Sales', 'Sales'[Color]))",
            "CALCULATE(SUM([Amount]), ALL([Color]))",
            "CALCULATE(SUM([Amount]), ALL('Sales'[Color], 'Calendar'[Date]))",
            "CALCULATE(SUM([Amount]), ALL(1))",
            "ALLNOBLANKROW()",
            "COUNTROWS(ALLNOBLANKROW())",
            "ALLNOBLANKROW('Sales')",
            "CALCULATE(SUM([Amount]), ALLNOBLANKROW(), 'Sales'[Color] = \"Blue\")",
            "CALCULATE(SUM([Amount]), ALLNOBLANKROW('Sales', 'Sales'[Color]))",
            "CALCULATE(SUM([Amount]), ALLNOBLANKROW('Sales'[Color], 'Calendar'[Date]))",
            "CALCULATE(SUM([Amount]), ALLNOBLANKROW(1))",
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(MeasureError):
                    normalize_measure("Invalid ALL", expression)

        rows = [{"Color": "Red", "Amount": "10"}]
        with self.assertRaisesRegex(MeasureError, "Table 'Missing' is not loaded"):
            evaluate_measures(
                [{"name": "Missing table", "expression": "CALCULATE(SUM([Amount]), ALL('Missing'))"}],
                rows,
                ["Color", "Amount"],
                "Sales",
            )
        with self.assertRaisesRegex(MeasureError, "Column 'Missing' does not exist"):
            evaluate_measures(
                [{"name": "Missing column", "expression": "CALCULATE(SUM([Amount]), ALL('Sales'[Missing]))"}],
                rows,
                ["Color", "Amount"],
                "Sales",
                table_context=[{
                    "id": "sales-id",
                    "name": "Sales",
                    "headers": ["Color", "Amount"],
                    "rows": rows,
                }],
                active_table_id="sales-id",
            )

    def test_all_table_forms_preserve_rows_and_deduplicate_column_tuples(self) -> None:
        rows = [
            {"Color": "Red", "Region": "East", "Amount": "10"},
            {"Color": "Blue", "Region": "East", "Amount": "20"},
            {"Color": "Blue", "Region": "West", "Amount": "20"},
        ]
        values = evaluate_measures(
            [
                {"name": "Visible Rows", "expression": "COUNTROWS()"},
                {"name": "Visible Table Rows", "expression": "COUNTROWS('Sales')"},
                {"name": "ALL Table Rows", "expression": "COUNTROWS(ALL('Sales'))"},
                {"name": "ALL Color Values", "expression": "COUNTROWS(ALL('Sales'[Color]))"},
                {"name": "ALL Color Region Tuples", "expression": "COUNTROWS(ALL('Sales'[Color], 'Sales'[Region]))"},
                {"name": "ALL Table Sum", "expression": "SUMX(ALL('Sales'), 'Sales'[Amount])"},
                {"name": "ALL Amount Sum", "expression": "SUMX(ALL('Sales'[Amount]), 'Sales'[Amount])"},
                {"name": "ALL Table Average", "expression": "AVERAGEX(ALL('Sales'), 'Sales'[Amount])"},
            ],
            rows,
            ["Color", "Region", "Amount"],
            "Sales",
            table_context=[{
                "id": "sales-id",
                "name": "Sales",
                "headers": ["Color", "Region", "Amount"],
                "rows": rows,
                "column_types": {"Color": "text", "Region": "text", "Amount": "whole_number"},
                "filter_rows": [rows[0]],
                "filter_column_rows": {"Color": {0}, "Region": {0, 1}},
                "filter_context_complete": True,
            }],
            filter_table_ids={"sales-id"},
            active_table_id="sales-id",
        )
        self.assertEqual(values["Visible Rows"], 1)
        self.assertEqual(values["Visible Table Rows"], 1)
        self.assertEqual(values["ALL Table Rows"], 3)
        self.assertEqual(values["ALL Color Values"], 2)
        self.assertEqual(values["ALL Color Region Tuples"], 3)
        self.assertEqual(values["ALL Table Sum"], 50)
        self.assertEqual(values["ALL Amount Sum"], 10)
        self.assertEqual(values["ALL Table Average"], Decimal(50) / Decimal(3))

    def test_all_table_form_includes_one_virtual_unknown_parent_row(self) -> None:
        categories = [
            {"CategoryId": "1", "Label": "A"},
            {"CategoryId": "2", "Label": "B"},
            {"CategoryId": "", "Label": "Physical blank"},
        ]
        sales = [
            {"CategoryId": "1", "Amount": "10"},
            {"CategoryId": "99", "Amount": "20"},
        ]
        returns = [{"CategoryId": "98", "Count": "1"}]
        relationships = [
            {
                "relationship_version": 1,
                "id": "category-sales",
                "from": "Category[CategoryId]",
                "to": "Sales[CategoryId]",
                "from_table_id": "category-id",
                "from_column": "CategoryId",
                "to_table_id": "sales-id",
                "to_column": "CategoryId",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": True,
            },
            {
                "relationship_version": 1,
                "id": "category-returns",
                "from": "Category[CategoryId]",
                "to": "Returns[CategoryId]",
                "from_table_id": "category-id",
                "from_column": "CategoryId",
                "to_table_id": "returns-id",
                "to_column": "CategoryId",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": True,
            },
        ]
        tables = [
            {
                "id": "category-id",
                "name": "Category",
                "headers": ["CategoryId", "Label"],
                "rows": categories,
                "column_types": {"CategoryId": "whole_number", "Label": "text"},
            },
            {
                "id": "sales-id",
                "name": "Sales",
                "headers": ["CategoryId", "Amount"],
                "rows": sales,
                "column_types": {"CategoryId": "whole_number", "Amount": "whole_number"},
            },
            {
                "id": "returns-id",
                "name": "Returns",
                "headers": ["CategoryId", "Count"],
                "rows": returns,
                "column_types": {"CategoryId": "whole_number", "Count": "whole_number"},
            },
        ]
        values = evaluate_measures(
            [
                {"name": "ALL Parent Rows", "expression": "COUNTROWS(ALL('Category'))"},
                {"name": "ALL Parent Keys", "expression": "COUNTROWS(ALL('Category'[CategoryId]))"},
            ],
            categories,
            ["CategoryId", "Label"],
            "Category",
            table_context=tables,
            relationships=relationships,
            active_table_id="category-id",
        )
        self.assertEqual(values, {
            "ALL Parent Rows": 4,
            "ALL Parent Keys": 3,
        })

    def test_allnoblankrow_excludes_virtual_member_but_keeps_physical_blank(self) -> None:
        categories = [
            {"Key": "1", "Label": "A", "Amount": "10"},
            {"Key": "", "Label": "Physical blank", "Amount": "20"},
        ]
        sales = [{"Key": "99", "Amount": "5"}]
        relationships = [{
            "relationship_version": 1,
            "id": "category-sales",
            "from": "Category[Key]",
            "to": "Sales[Key]",
            "from_table_id": "category-id",
            "from_column": "Key",
            "to_table_id": "sales-id",
            "to_column": "Key",
            "cardinality": "one_to_many",
            "cross_filter_direction": "single",
            "is_active": True,
        }]
        tables = [
            {
                "id": "category-id",
                "name": "Category",
                "headers": ["Key", "Label", "Amount"],
                "rows": categories,
                "column_types": {
                    "Key": "whole_number", "Label": "text", "Amount": "whole_number"
                },
                "filter_rows": [categories[0]],
                "filter_column_rows": {"Label": {0}},
                "filter_column_blank_allowed": {"Label": False},
                "filter_context_complete": True,
            },
            {
                "id": "sales-id",
                "name": "Sales",
                "headers": ["Key", "Amount"],
                "rows": sales,
                "column_types": {"Key": "whole_number", "Amount": "whole_number"},
            },
        ]
        values = evaluate_measures(
            [
                {"name": "ALL physical plus virtual", "expression": "COUNTROWS(ALL('Category'))"},
                {"name": "No generated blank", "expression": "COUNTROWS(ALLNOBLANKROW('Category'))"},
                {"name": "Residual filter stays", "expression": "COUNTROWS(ALLNOBLANKROW('Category'[Key]))"},
                {
                    "name": "Physical blank remains",
                    "expression": "CALCULATE(COUNTROWS(ALLNOBLANKROW('Category'[Key])), ALL('Category'[Label]))",
                },
                {
                    "name": "Modifier excludes generated blank",
                    "expression": "CALCULATE(COUNTROWS('Category'), ALLNOBLANKROW('Category'))",
                },
                {
                    "name": "Nested ALL restores generated blank",
                    "expression": "CALCULATE(COUNTROWS(ALL('Category')), ALLNOBLANKROW('Category'))",
                },
                {
                    "name": "Nested ALL modifier restores generated blank",
                    "expression": "CALCULATE(CALCULATE(COUNTROWS('Category'), ALL()), ALLNOBLANKROW('Category'))",
                },
                {
                    "name": "Nested table ALL modifier restores generated blank",
                    "expression": "CALCULATE(CALCULATE(COUNTROWS('Category'), ALL('Category')), ALLNOBLANKROW('Category'))",
                },
                {
                    "name": "Column modifier keeps residual filter",
                    "expression": "CALCULATE(COUNTROWS('Category'), ALLNOBLANKROW('Category'[Key]))",
                },
            ],
            categories,
            ["Key", "Label", "Amount"],
            "Category",
            table_context=tables,
            relationships=relationships,
            filter_table_ids={"category-id"},
            active_table_id="category-id",
        )
        self.assertEqual(values, {
            "ALL physical plus virtual": 3,
            "No generated blank": 2,
            "Residual filter stays": 1,
            "Physical blank remains": 2,
            "Modifier excludes generated blank": 2,
            "Nested ALL restores generated blank": 3,
            "Nested ALL modifier restores generated blank": 3,
            "Nested table ALL modifier restores generated blank": 3,
            "Column modifier keeps residual filter": 1,
        })

    def test_allnoblankrow_column_values_and_iterators(self) -> None:
        categories = [
            {"Key": "1", "Amount": "10"},
            {"Key": "2", "Amount": "20"},
        ]
        sales = [{"Key": "99", "Amount": "5"}]
        values = evaluate_measures(
            [
                {"name": "ALL keys", "expression": "COUNTROWS(ALL('Category'[Key]))"},
                {"name": "Known keys", "expression": "COUNTROWS(ALLNOBLANKROW('Category'[Key]))"},
                {
                    "name": "Known key amount pairs",
                    "expression": "COUNTROWS(ALLNOBLANKROW('Category'[Key], 'Category'[Amount]))",
                },
                {
                    "name": "Known amount total",
                    "expression": "SUMX(ALLNOBLANKROW('Category'[Amount]), 'Category'[Amount])",
                },
                {
                    "name": "Known amount average",
                    "expression": "AVERAGEX(ALLNOBLANKROW('Category'), 'Category'[Amount])",
                },
                {
                    "name": "Column ALL modifier restores unknown",
                    "expression": "CALCULATE(CALCULATE(COUNTROWS('Category'), ALL('Category'[Key])), ALLNOBLANKROW('Category'[Key]))",
                },
            ],
            categories,
            ["Key", "Amount"],
            "Category",
            table_context=[
                {
                    "id": "category-id",
                    "name": "Category",
                    "headers": ["Key", "Amount"],
                    "rows": categories,
                    "column_types": {"Key": "whole_number", "Amount": "whole_number"},
                },
                {
                    "id": "sales-id",
                    "name": "Sales",
                    "headers": ["Key", "Amount"],
                    "rows": sales,
                    "column_types": {"Key": "whole_number", "Amount": "whole_number"},
                },
            ],
            relationships=[{
                "relationship_version": 1,
                "id": "category-sales",
                "from": "Category[Key]",
                "to": "Sales[Key]",
                "from_table_id": "category-id",
                "from_column": "Key",
                "to_table_id": "sales-id",
                "to_column": "Key",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": True,
            }],
            active_table_id="category-id",
        )
        self.assertEqual(values, {
            "ALL keys": 3,
            "Known keys": 2,
            "Known key amount pairs": 2,
            "Known amount total": 30,
            "Known amount average": 15,
            "Column ALL modifier restores unknown": 3,
        })

    def test_allnoblankrow_column_modifier_preserves_other_direct_filters(self) -> None:
        categories = [
            {"Key": "1", "Label": "A", "Amount": "10"},
            {"Key": "2", "Label": "B", "Amount": "20"},
        ]
        values = evaluate_measures(
            [{
                "name": "Keep label filter",
                "expression": "CALCULATE(SUM('Category'[Amount]), ALLNOBLANKROW('Category'[Key]))",
            }],
            categories,
            ["Key", "Label", "Amount"],
            "Category",
            table_context=[{
                "id": "category-id",
                "name": "Category",
                "headers": ["Key", "Label", "Amount"],
                "rows": categories,
                "column_types": {
                    "Key": "whole_number", "Label": "text", "Amount": "whole_number"
                },
                "filter_rows": [],
                "filter_column_rows": {"Key": {1}, "Label": {0}},
                "filter_column_blank_allowed": {"Key": False, "Label": False},
                "filter_context_complete": True,
            }],
            filter_table_ids={"category-id"},
            active_table_id="category-id",
        )
        self.assertEqual(values["Keep label filter"], 10)

    def test_allselected_modifier_keeps_saved_filters_and_relationship_roots(self) -> None:
        categories = [{"Key": "1"}, {"Key": "2"}]
        sales = [
            {"CategoryKey": "1", "Color": "Red", "Region": "East", "Amount": "10"},
            {"CategoryKey": "1", "Color": "Blue", "Region": "East", "Amount": "20"},
            {"CategoryKey": "1", "Color": "Blue", "Region": "West", "Amount": "30"},
            {"CategoryKey": "2", "Color": "Green", "Region": "East", "Amount": "40"},
        ]
        values = evaluate_measures(
            [
                {"name": "Visible", "expression": "SUM([Amount])"},
                {
                    "name": "Allselected no arguments",
                    "expression": "CALCULATE(SUM([Amount]), ALLSELECTED())",
                },
                {
                    "name": "Allselected table",
                    "expression": "CALCULATE(SUM([Amount]), ALLSELECTED('Sales'))",
                },
                {
                    "name": "Allselected column",
                    "expression": "CALCULATE(SUM([Amount]), ALLSELECTED('Sales'[Color]))",
                },
                {
                    "name": "Allselected columns",
                    "expression": (
                        "CALCULATE(SUM([Amount]), "
                        "ALLSELECTED('Sales'[Color], 'Sales'[Region]))"
                    ),
                },
                {
                    "name": "Nested allselected",
                    "expression": (
                        "CALCULATE(CALCULATE(SUM([Amount]), ALLSELECTED()), "
                        "'Sales'[Color] = \"Blue\")"
                    ),
                },
            ],
            sales,
            ["CategoryKey", "Color", "Region", "Amount"],
            "Sales",
            table_context=[
                {
                    "id": "category-id",
                    "name": "Category",
                    "headers": ["Key"],
                    "rows": categories,
                    "column_types": {"Key": "whole_number"},
                    "filter_rows": [categories[0]],
                    "filter_column_rows": {"Key": {0}},
                    "filter_context_complete": True,
                },
                {
                    "id": "sales-id",
                    "name": "Sales",
                    "headers": ["CategoryKey", "Color", "Region", "Amount"],
                    "rows": sales,
                    "column_types": {
                        "CategoryKey": "whole_number",
                        "Amount": "whole_number",
                    },
                    "filter_rows": [sales[0], sales[1]],
                    "filter_column_rows": {"Color": {0, 1}, "Region": {0, 1}},
                    "filter_context_complete": True,
                },
            ],
            relationships=[{
                "relationship_version": 1,
                "id": "category-sales",
                "from": "Category[Key]",
                "to": "Sales[CategoryKey]",
                "from_table_id": "category-id",
                "from_column": "Key",
                "to_table_id": "sales-id",
                "to_column": "CategoryKey",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": True,
            }],
            filter_table_ids={"category-id", "sales-id"},
            active_table_id="sales-id",
        )
        self.assertEqual(values, {
            "Visible": 30,
            "Allselected no arguments": 30,
            "Allselected table": 30,
            "Allselected column": 30,
            "Allselected columns": 30,
            "Nested allselected": 20,
        })

    def test_allselected_table_values_keep_visible_rows_and_distinct_tuples(self) -> None:
        rows = [
            {"Color": "Red", "Region": "East", "Amount": "10"},
            {"Color": "Blue", "Region": "East", "Amount": "20"},
            {"Color": "Blue", "Region": "East", "Amount": "20"},
            {"Color": "Blue", "Region": "West", "Amount": "30"},
        ]
        values = evaluate_measures(
            [
                {"name": "Visible rows", "expression": "COUNTROWS(ALLSELECTED('Sales'))"},
                {"name": "Visible colors", "expression": "COUNTROWS(ALLSELECTED('Sales'[Color]))"},
                {
                    "name": "Visible tuples",
                    "expression": "COUNTROWS(ALLSELECTED('Sales'[Color], 'Sales'[Region]))",
                },
                {
                    "name": "Visible amount sum",
                    "expression": "SUMX(ALLSELECTED('Sales'), 'Sales'[Amount])",
                },
            ],
            rows,
            ["Color", "Region", "Amount"],
            "Sales",
            table_context=[{
                "id": "sales-id",
                "name": "Sales",
                "headers": ["Color", "Region", "Amount"],
                "rows": rows,
                "column_types": {"Amount": "whole_number"},
                "filter_rows": rows[:3],
                "filter_column_rows": {"Region": {0, 1, 2}},
                "filter_context_complete": True,
            }],
            filter_table_ids={"sales-id"},
            active_table_id="sales-id",
        )
        self.assertEqual(values, {
            "Visible rows": 3,
            "Visible colors": 2,
            "Visible tuples": 2,
            "Visible amount sum": 50,
        })

    def test_allselected_parser_targets_and_empty_visible_context(self) -> None:
        for expression in (
            "CALCULATE(SUM([Amount]), ALLSELECTED())",
            "CALCULATE(SUM([Amount]), ALLSELECTED('Sales'))",
            "CALCULATE(SUM([Amount]), ALLSELECTED('Sales'[Color]))",
            "CALCULATE(SUM([Amount]), ALLSELECTED('Sales'[Color], 'Sales'[Region]))",
            "COUNTROWS(ALLSELECTED('Sales'))",
            "COUNTROWS(ALLSELECTED('Sales'[Color], 'Sales'[Region]))",
            "SUMX(ALLSELECTED('Sales'), 'Sales'[Amount])",
        ):
            with self.subTest(expression=expression):
                normalize_measure("Valid ALLSELECTED", expression)

        for expression in (
            "ALLSELECTED()",
            "COUNTROWS(ALLSELECTED())",
            "CALCULATE(SUM([Amount]), ALLSELECTED(), 'Sales'[Color] = \"Blue\")",
            "CALCULATE(SUM([Amount]), ALLSELECTED('Sales', 'Sales'[Color]))",
            "CALCULATE(SUM([Amount]), ALLSELECTED('Sales'[Color], 'Calendar'[Date]))",
            "CALCULATE(SUM([Amount]), ALLSELECTED(1))",
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(MeasureError):
                    normalize_measure("Invalid ALLSELECTED", expression)

        rows = [{"Color": "Red", "Amount": "10"}]
        values = evaluate_measures(
            [{"name": "Empty rows", "expression": "COUNTROWS(ALLSELECTED('Sales'))"}],
            rows,
            ["Color", "Amount"],
            "Sales",
            table_context=[{
                "id": "sales-id",
                "name": "Sales",
                "headers": ["Color", "Amount"],
                "rows": rows,
                "filter_rows": [],
                "filter_column_rows": {"Color": set()},
                "filter_context_complete": True,
            }],
            filter_table_ids={"sales-id"},
            active_table_id="sales-id",
        )
        self.assertEqual(values["Empty rows"], 0)

        with self.assertRaisesRegex(MeasureError, "Table 'Missing' is not loaded"):
            evaluate_measures(
                [{
                    "name": "Missing target",
                    "expression": "CALCULATE(SUM([Amount]), ALLSELECTED('Missing'))",
                }],
                rows,
                ["Color", "Amount"],
                "Sales",
                table_context=[{
                    "id": "sales-id",
                    "name": "Sales",
                    "headers": ["Color", "Amount"],
                    "rows": rows,
                }],
                active_table_id="sales-id",
            )

    def test_allselected_opaque_filter_rowset_does_not_add_unknown_member(self) -> None:
        categories = [{"Key": "1", "Label": "A"}]
        sales = [{"Key": "99", "Amount": "5"}]
        values = evaluate_measures(
            [
                {
                    "name": "Filtered selected table",
                    "expression": (
                        "CALCULATE(COUNTROWS(ALLSELECTED('Category')), "
                        "FILTER('Category', 'Category'[Label] = \"A\"))"
                    ),
                },
                {
                    "name": "Filtered selected column",
                    "expression": (
                        "CALCULATE(COUNTROWS(ALLSELECTED('Category'[Key])), "
                        "FILTER('Category', 'Category'[Label] = \"A\"))"
                    ),
                },
            ],
            categories,
            ["Key", "Label"],
            "Category",
            table_context=[
                {
                    "id": "category-id",
                    "name": "Category",
                    "headers": ["Key", "Label"],
                    "rows": categories,
                    "column_types": {"Key": "whole_number"},
                },
                {
                    "id": "sales-id",
                    "name": "Sales",
                    "headers": ["Key", "Amount"],
                    "rows": sales,
                    "column_types": {"Key": "whole_number", "Amount": "whole_number"},
                },
            ],
            relationships=[{
                "relationship_version": 1,
                "id": "category-sales",
                "from": "Category[Key]",
                "to": "Sales[Key]",
                "from_table_id": "category-id",
                "from_column": "Key",
                "to_table_id": "sales-id",
                "to_column": "Key",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": True,
            }],
            active_table_id="category-id",
        )
        self.assertEqual(values, {
            "Filtered selected table": 1,
            "Filtered selected column": 1,
        })

    def test_allselected_measure_lifecycle_preserves_page_filters(self) -> None:
        controller = self.controller("settings.ini")
        self.load_sales(controller)
        sales_id = str(controller.activeTableId)
        self.assertTrue(controller.addPageFilterRule(
            sales_id, "Color", "equals", "Red", "", "", "and"
        ))
        self.assertTrue(controller.addPageFilterRule(
            sales_id, "Region", "equals", "East", "", "", "and"
        ))
        self.assertTrue(controller.create_measure(
            "Selected sales",
            "CALCULATE(SUM([Amount]), ALLSELECTED())",
        ), controller.statusMessage)
        self.assertTrue(controller.create_measure(
            "Selected rows",
            "COUNTROWS(ALLSELECTED('Sales'))",
        ), controller.statusMessage)
        self.assertEqual(controller.reportKpis["Selected sales"], "20")
        self.assertEqual(controller.reportKpis["Selected rows"], "1")
        project_path = self.root / "allselected.npa"
        self.assertTrue(controller._save_to(project_path))

        self.sales_path.write_text(
            "ID,Color,Region,Amount,Active\n"
            "1,Red,East,21,True\n"
            "2,Blue,East,12,False\n"
            "3,Green,East,7,True\n"
            "4,Blue,West,31,True\n"
            "5,Green,West,40,False\n"
            "6,Red,West,50,True\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Selected sales"], "21")
        self.assertEqual(reopened.reportKpis["Selected rows"], "1")

    def test_allexcept_preserves_named_columns_and_external_relationship_roots(self) -> None:
        categories = [{"Key": "1"}, {"Key": "2"}]
        sales = [
            {"CategoryKey": "1", "Color": "Red", "Region": "East", "Amount": "10"},
            {"CategoryKey": "1", "Color": "Blue", "Region": "East", "Amount": "20"},
            {"CategoryKey": "1", "Color": "Blue", "Region": "West", "Amount": "5"},
            {"CategoryKey": "2", "Color": "Blue", "Region": "West", "Amount": "30"},
            {"CategoryKey": "2", "Color": "Green", "Region": "West", "Amount": "40"},
        ]
        relationships = [{
            "relationship_version": 1,
            "id": "category-sales",
            "from": "Category[Key]",
            "to": "Sales[CategoryKey]",
            "from_table_id": "category-id",
            "from_column": "Key",
            "to_table_id": "sales-id",
            "to_column": "CategoryKey",
            "cardinality": "one_to_many",
            "cross_filter_direction": "single",
            "is_active": True,
        }]
        values = evaluate_measures(
            [
                {"name": "Base visible", "expression": "SUM([Amount])"},
                {
                    "name": "Keep region",
                    "expression": "CALCULATE(SUM([Amount]), ALLEXCEPT('Sales', 'Sales'[Region]))",
                },
                {
                    "name": "Keep color",
                    "expression": "CALCULATE(SUM([Amount]), ALLEXCEPT('Sales', 'Sales'[Color]))",
                },
                {
                    "name": "Keep both",
                    "expression": "CALCULATE(SUM([Amount]), ALLEXCEPT('Sales', 'Sales'[Color], 'Sales'[Region]))",
                },
                {
                    "name": "Keep unfiltered column",
                    "expression": "CALCULATE(SUM([Amount]), ALLEXCEPT('Sales', 'Sales'[Amount]))",
                },
                {
                    "name": "Nested keep region",
                    "expression": "CALCULATE(CALCULATE(SUM([Amount]), ALLEXCEPT('Sales', 'Sales'[Region])), 'Sales'[Color] = \"Blue\")",
                },
            ],
            sales,
            ["CategoryKey", "Color", "Region", "Amount"],
            "Sales",
            table_context=[
                {
                    "id": "category-id",
                    "name": "Category",
                    "headers": ["Key"],
                    "rows": categories,
                    "column_types": {"Key": "whole_number"},
                    "filter_rows": [categories[0]],
                    "filter_column_rows": {"Key": {0}},
                    "filter_column_blank_allowed": {"Key": False},
                    "filter_context_complete": True,
                },
                {
                    "id": "sales-id",
                    "name": "Sales",
                    "headers": ["CategoryKey", "Color", "Region", "Amount"],
                    "rows": sales,
                    "column_types": {
                        "CategoryKey": "whole_number",
                        "Color": "text",
                        "Region": "text",
                        "Amount": "whole_number",
                    },
                    "filter_rows": [sales[1]],
                    "filter_column_rows": {"Color": {1, 2, 3}, "Region": {0, 1}},
                    "filter_column_blank_allowed": {"Color": False, "Region": False},
                    "filter_context_complete": True,
                },
            ],
            relationships=relationships,
            filter_table_ids={"category-id", "sales-id"},
            active_table_id="sales-id",
        )
        self.assertEqual(values, {
            "Base visible": 20,
            "Keep region": 30,
            "Keep color": 25,
            "Keep both": 20,
            "Keep unfiltered column": 35,
            "Nested keep region": 30,
        })

    def test_allexcept_preserves_blank_filter_provenance(self) -> None:
        categories = [{"Key": "1", "Label": "A"}, {"Key": "2", "Label": "B"}]
        sales = [{"Key": "99", "Amount": "10"}]
        relationships = [{
            "relationship_version": 1,
            "id": "category-sales",
            "from": "Category[Key]",
            "to": "Sales[Key]",
            "from_table_id": "category-id",
            "from_column": "Key",
            "to_table_id": "sales-id",
            "to_column": "Key",
            "cardinality": "one_to_many",
            "cross_filter_direction": "single",
            "is_active": True,
        }]
        for blank_allowed, expected in ((True, 1), (False, 0)):
            with self.subTest(blank_allowed=blank_allowed):
                values = evaluate_measures(
                    [{
                        "name": "Keep blank key filter",
                        "expression": "CALCULATE(COUNTROWS('Category'), ALLEXCEPT('Category', 'Category'[Key]))",
                    }],
                    categories,
                    ["Key", "Label"],
                    "Category",
                    table_context=[
                        {
                            "id": "category-id",
                            "name": "Category",
                            "headers": ["Key", "Label"],
                            "rows": categories,
                            "column_types": {"Key": "whole_number", "Label": "text"},
                            "filter_rows": [],
                            "filter_column_rows": {"Key": set(), "Label": {0}},
                            "filter_column_blank_allowed": {
                                "Key": blank_allowed, "Label": False
                            },
                            "filter_context_complete": True,
                        },
                        {
                            "id": "sales-id",
                            "name": "Sales",
                            "headers": ["Key", "Amount"],
                            "rows": sales,
                            "column_types": {"Key": "whole_number", "Amount": "whole_number"},
                        },
                    ],
                    relationships=relationships,
                    filter_table_ids={"category-id"},
                    active_table_id="category-id",
                )
                self.assertEqual(values["Keep blank key filter"], expected)

    def test_allexcept_parser_and_target_validation(self) -> None:
        for expression in (
            "CALCULATE(SUM([Amount]), ALLEXCEPT('Sales', 'Sales'[Color]))",
            "CALCULATE(SUM([Amount]), ALLEXCEPT('Sales', 'Sales'[Color], 'Sales'[Region]))",
        ):
            with self.subTest(expression=expression):
                normalize_measure("Valid ALLEXCEPT", expression)

        for expression in (
            "ALLEXCEPT()",
            "ALLEXCEPT('Sales')",
            "ALLEXCEPT('Sales', 'Sales'[Color])",
            "ALLEXCEPT('Sales'[Color], 'Sales'[Region])",
            "CALCULATE(SUM([Amount]), ALLEXCEPT('Sales', [Color]))",
            "CALCULATE(SUM([Amount]), ALLEXCEPT('Sales', 'Calendar'[Date]))",
            "CALCULATE(SUM([Amount]), ALLEXCEPT('Sales', 'Sales'[Color]), 'Sales'[Region] = \"East\")",
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(MeasureError):
                    normalize_measure("Invalid ALLEXCEPT", expression)

        rows = [{"Color": "Red", "Amount": "10"}]
        with self.assertRaisesRegex(MeasureError, "Column 'Missing' does not exist"):
            evaluate_measures(
                [{
                    "name": "Missing keep column",
                    "expression": "CALCULATE(SUM([Amount]), ALLEXCEPT('Sales', 'Sales'[Missing]))",
                }],
                rows,
                ["Color", "Amount"],
                "Sales",
                table_context=[{
                    "id": "sales-id",
                    "name": "Sales",
                    "headers": ["Color", "Amount"],
                    "rows": rows,
                }],
                active_table_id="sales-id",
            )

    def test_allexcept_rejects_opaque_or_incomplete_filter_provenance(self) -> None:
        rows = [
            {"Color": "Red", "Amount": "10"},
            {"Color": "Blue", "Amount": "20"},
        ]
        contexts = [
            ({
                "filter_rows": [rows[0]],
                "filter_table_rows": {0},
                "filter_context_complete": False,
            }, "opaque table-valued FILTER"),
            ({
                "filter_rows": [rows[0]],
                "filter_context_complete": False,
            }, "per-column filter context is unavailable"),
        ]
        for extra_context, message in contexts:
            with self.subTest(message=message):
                context = {
                    "id": "sales-id",
                    "name": "Sales",
                    "headers": ["Color", "Amount"],
                    "rows": rows,
                    "column_types": {"Color": "text", "Amount": "whole_number"},
                    **extra_context,
                }
                with self.assertRaisesRegex(MeasureError, message):
                    evaluate_measures(
                        [{
                            "name": "Preserve color",
                            "expression": "CALCULATE(SUM([Amount]), ALLEXCEPT('Sales', 'Sales'[Color]))",
                        }],
                        rows,
                        ["Color", "Amount"],
                        "Sales",
                        table_context=[context],
                        filter_table_ids={"sales-id"},
                        active_table_id="sales-id",
                    )

    def test_all_column_virtual_blank_respects_residual_filter_provenance(self) -> None:
        categories = [
            {"CategoryId": "1", "Label": "A"},
            {"CategoryId": "2", "Label": "B"},
        ]
        sales = [{"CategoryId": "99", "Amount": "20"}]
        values = evaluate_measures(
            [
                {
                    "name": "Report filter excludes unknown",
                    "expression": "COUNTROWS(ALL('Category'[CategoryId]))",
                },
                {
                    "name": "Boolean filter excludes unknown",
                    "expression": "CALCULATE(COUNTROWS(ALL('Category'[CategoryId])), 'Category'[Label] = \"A\")",
                },
                {
                    "name": "Modifier clears residual filter",
                    "expression": "CALCULATE(COUNTROWS(ALL('Category'[CategoryId])), ALL('Category'[Label]))",
                },
            ],
            categories,
            ["CategoryId", "Label"],
            "Category",
            table_context=[
                {
                    "id": "category-id",
                    "name": "Category",
                    "headers": ["CategoryId", "Label"],
                    "rows": categories,
                    "column_types": {"CategoryId": "whole_number", "Label": "text"},
                    "filter_rows": [categories[0]],
                    "filter_column_rows": {"Label": {0}},
                    "filter_column_blank_allowed": {"Label": False},
                    "filter_context_complete": True,
                },
                {
                    "id": "sales-id",
                    "name": "Sales",
                    "headers": ["CategoryId", "Amount"],
                    "rows": sales,
                    "column_types": {"CategoryId": "whole_number", "Amount": "whole_number"},
                },
            ],
            relationships=[{
                "relationship_version": 1,
                "id": "category-sales",
                "from": "Category[CategoryId]",
                "to": "Sales[CategoryId]",
                "from_table_id": "category-id",
                "from_column": "CategoryId",
                "to_table_id": "sales-id",
                "to_column": "CategoryId",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": True,
            }],
            filter_table_ids={"category-id"},
            active_table_id="category-id",
        )
        self.assertEqual(values, {
            "Report filter excludes unknown": 1,
            "Boolean filter excludes unknown": 1,
            "Modifier clears residual filter": 3,
        })

    def test_all_table_unknown_member_covers_inactive_and_one_to_one_links(self) -> None:
        tables = [
            {
                "id": "parent-id",
                "name": "Parent",
                "headers": ["Key"],
                "rows": [{"Key": "1"}],
                "column_types": {"Key": "whole_number"},
            },
            {
                "id": "child-id",
                "name": "Child",
                "headers": ["Key"],
                "rows": [{"Key": "2"}],
                "column_types": {"Key": "whole_number"},
            },
            {
                "id": "one-a-id",
                "name": "OneA",
                "headers": ["Key"],
                "rows": [{"Key": "3"}],
                "column_types": {"Key": "whole_number"},
            },
            {
                "id": "one-b-id",
                "name": "OneB",
                "headers": ["Key"],
                "rows": [{"Key": "4"}],
                "column_types": {"Key": "whole_number"},
            },
        ]
        relationships = [
            {
                "relationship_version": 1,
                "id": "inactive-parent-child",
                "from": "Parent[Key]",
                "to": "Child[Key]",
                "from_table_id": "parent-id",
                "from_column": "Key",
                "to_table_id": "child-id",
                "to_column": "Key",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": False,
            },
            {
                "relationship_version": 1,
                "id": "one-to-one",
                "from": "OneA[Key]",
                "to": "OneB[Key]",
                "from_table_id": "one-a-id",
                "from_column": "Key",
                "to_table_id": "one-b-id",
                "to_column": "Key",
                "cardinality": "one_to_one",
                "cross_filter_direction": "both",
                "is_active": True,
            },
        ]
        values = evaluate_measures(
            [
                {"name": "Inactive parent", "expression": "COUNTROWS(ALL('Parent'))"},
                {"name": "One-to-one first", "expression": "COUNTROWS(ALL('OneA'))"},
                {"name": "One-to-one second", "expression": "COUNTROWS(ALL('OneB'))"},
            ],
            tables[0]["rows"],
            tables[0]["headers"],
            "Parent",
            table_context=tables,
            relationships=relationships,
            active_table_id="parent-id",
        )
        self.assertEqual(values, {
            "Inactive parent": 2,
            "One-to-one first": 2,
            "One-to-one second": 2,
        })

    def test_all_column_unknown_member_respects_bidirectional_child_filters(self) -> None:
        parents = [{"Key": "1"}, {"Key": "2"}]
        sales = [
            {"Key": "1", "Region": "East"},
            {"Key": "2", "Region": "West"},
            {"Key": "99", "Region": "West"},
        ]
        relationship = {
            "relationship_version": 1,
            "id": "parent-sales-both",
            "from": "Parent[Key]",
            "to": "Sales[Key]",
            "from_table_id": "parent-id",
            "from_column": "Key",
            "to_table_id": "sales-id",
            "to_column": "Key",
            "cardinality": "one_to_many",
            "cross_filter_direction": "both",
            "is_active": True,
        }
        for direction, region, expected in (
            ("both", "East", 1),
            ("both", "West", 2),
            ("single", "East", 3),
        ):
            with self.subTest(direction=direction, region=region):
                relationship["cross_filter_direction"] = direction
                visible_indexes = {
                    index
                    for index, row in enumerate(sales)
                    if row["Region"] == region
                }
                visible_sales = [sales[index] for index in sorted(visible_indexes)]
                values = evaluate_measures(
                    [{
                        "name": "Visible parent keys",
                        "expression": "COUNTROWS(ALL('Parent'[Key]))",
                    }],
                    parents,
                    ["Key"],
                    "Parent",
                    table_context=[
                        {
                            "id": "parent-id",
                            "name": "Parent",
                            "headers": ["Key"],
                            "rows": parents,
                            "column_types": {"Key": "whole_number"},
                        },
                        {
                            "id": "sales-id",
                            "name": "Sales",
                            "headers": ["Key", "Region"],
                            "rows": sales,
                            "column_types": {"Key": "whole_number", "Region": "text"},
                            "filter_rows": visible_sales,
                            "filter_column_rows": {"Region": visible_indexes},
                            "filter_column_blank_allowed": {"Region": False},
                            "filter_context_complete": True,
                        },
                    ],
                    relationships=[relationship],
                    filter_table_ids={"sales-id"},
                    active_table_id="parent-id",
                )
                self.assertEqual(values["Visible parent keys"], expected)

    def test_all_column_unknown_member_respects_indirect_relationship_filters(self) -> None:
        categories = [{"Key": "1"}, {"Key": "2"}]
        regions = [{"RegionId": "E"}, {"RegionId": "W"}]
        sales = [
            {"Key": "1", "RegionId": "E"},
            {"Key": "2", "RegionId": "W"},
            {"Key": "99", "RegionId": "W"},
        ]
        relationships = [
            {
                "relationship_version": 1,
                "id": "category-sales-both",
                "from": "Category[Key]",
                "to": "Sales[Key]",
                "from_table_id": "category-id",
                "from_column": "Key",
                "to_table_id": "sales-id",
                "to_column": "Key",
                "cardinality": "one_to_many",
                "cross_filter_direction": "both",
                "is_active": True,
            },
            {
                "relationship_version": 1,
                "id": "region-sales",
                "from": "Region[RegionId]",
                "to": "Sales[RegionId]",
                "from_table_id": "region-id",
                "from_column": "RegionId",
                "to_table_id": "sales-id",
                "to_column": "RegionId",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": True,
            },
        ]
        for region_index, region, expected in ((0, "E", 1), (1, "W", 2)):
            with self.subTest(region=region):
                values = evaluate_measures(
                    [{
                        "name": "Visible category keys",
                        "expression": "COUNTROWS(ALL('Category'[Key]))",
                    }],
                    categories,
                    ["Key"],
                    "Category",
                    table_context=[
                        {
                            "id": "category-id",
                            "name": "Category",
                            "headers": ["Key"],
                            "rows": categories,
                            "column_types": {"Key": "whole_number"},
                        },
                        {
                            "id": "region-id",
                            "name": "Region",
                            "headers": ["RegionId"],
                            "rows": regions,
                            "column_types": {"RegionId": "text"},
                            "filter_rows": [regions[region_index]],
                            "filter_column_rows": {"RegionId": {region_index}},
                            "filter_column_blank_allowed": {"RegionId": False},
                            "filter_context_complete": True,
                        },
                        {
                            "id": "sales-id",
                            "name": "Sales",
                            "headers": ["Key", "RegionId"],
                            "rows": sales,
                            "column_types": {"Key": "whole_number", "RegionId": "text"},
                        },
                    ],
                    relationships=relationships,
                    filter_table_ids={"region-id"},
                    active_table_id="category-id",
                )
                self.assertEqual(values["Visible category keys"], expected)

    def test_all_column_unknown_member_intersects_separate_filter_roots(self) -> None:
        categories = [{"Key": "1"}, {"Key": "2"}]
        regions = [{"RegionId": "E"}, {"RegionId": "W"}]
        sales = [{"Key": "99", "RegionId": "W"}]
        relationships = [
            {
                "relationship_version": 1,
                "id": "category-sales-both",
                "from": "Category[Key]",
                "to": "Sales[Key]",
                "from_table_id": "category-id",
                "from_column": "Key",
                "to_table_id": "sales-id",
                "to_column": "Key",
                "cardinality": "one_to_many",
                "cross_filter_direction": "both",
                "is_active": True,
            },
            {
                "relationship_version": 1,
                "id": "region-sales",
                "from": "Region[RegionId]",
                "to": "Sales[RegionId]",
                "from_table_id": "region-id",
                "from_column": "RegionId",
                "to_table_id": "sales-id",
                "to_column": "RegionId",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": True,
            },
        ]
        values = evaluate_measures(
            [{
                "name": "No visible parent keys",
                "expression": "COUNTROWS(ALL('Category'[Key]))",
            }],
            categories,
            ["Key"],
            "Category",
            table_context=[
                {
                    "id": "category-id",
                    "name": "Category",
                    "headers": ["Key"],
                    "rows": categories,
                    "column_types": {"Key": "whole_number"},
                },
                {
                    "id": "region-id",
                    "name": "Region",
                    "headers": ["RegionId"],
                    "rows": regions,
                    "column_types": {"RegionId": "text"},
                    "filter_rows": [regions[0]],
                    "filter_column_rows": {"RegionId": {0}},
                    "filter_column_blank_allowed": {"RegionId": False},
                    "filter_context_complete": True,
                },
                {
                    "id": "sales-id",
                    "name": "Sales",
                    "headers": ["Key", "RegionId"],
                    "rows": sales,
                    "column_types": {"Key": "whole_number", "RegionId": "text"},
                    "filter_rows": [sales[0]],
                    "filter_column_rows": {"RegionId": {0}},
                    "filter_column_blank_allowed": {"RegionId": False},
                    "filter_context_complete": True,
                },
            ],
            relationships=relationships,
            filter_table_ids={"region-id", "sales-id"},
            active_table_id="category-id",
        )
        self.assertEqual(values["No visible parent keys"], 0)

    def test_all_column_unknown_member_intersects_bidirectional_child_tables(self) -> None:
        categories = [{"Key": "1"}, {"Key": "2"}]
        sales = [{"Key": "99"}]
        returns = [{"Key": "1"}]
        relationships = [
            {
                "relationship_version": 1,
                "id": "category-sales-both",
                "from": "Category[Key]",
                "to": "Sales[Key]",
                "from_table_id": "category-id",
                "from_column": "Key",
                "to_table_id": "sales-id",
                "to_column": "Key",
                "cardinality": "one_to_many",
                "cross_filter_direction": "both",
                "is_active": True,
            },
            {
                "relationship_version": 1,
                "id": "category-returns-both",
                "from": "Category[Key]",
                "to": "Returns[Key]",
                "from_table_id": "category-id",
                "from_column": "Key",
                "to_table_id": "returns-id",
                "to_column": "Key",
                "cardinality": "one_to_many",
                "cross_filter_direction": "both",
                "is_active": True,
            },
        ]
        values = evaluate_measures(
            [{
                "name": "No intersecting category keys",
                "expression": "COUNTROWS(ALL('Category'[Key]))",
            }],
            categories,
            ["Key"],
            "Category",
            table_context=[
                {
                    "id": "category-id",
                    "name": "Category",
                    "headers": ["Key"],
                    "rows": categories,
                    "column_types": {"Key": "whole_number"},
                },
                {
                    "id": "sales-id",
                    "name": "Sales",
                    "headers": ["Key"],
                    "rows": sales,
                    "column_types": {"Key": "whole_number"},
                    "filter_rows": sales,
                    "filter_column_rows": {"Key": {0}},
                    "filter_column_blank_allowed": {"Key": False},
                    "filter_context_complete": True,
                },
                {
                    "id": "returns-id",
                    "name": "Returns",
                    "headers": ["Key"],
                    "rows": returns,
                    "column_types": {"Key": "whole_number"},
                    "filter_rows": returns,
                    "filter_column_rows": {"Key": {0}},
                    "filter_column_blank_allowed": {"Key": False},
                    "filter_context_complete": True,
                },
            ],
            relationships=relationships,
            filter_table_ids={"sales-id", "returns-id"},
            active_table_id="category-id",
        )
        self.assertEqual(values["No intersecting category keys"], 0)

    def test_all_modifier_measure_lifecycle_after_source_change(self) -> None:
        controller = self.controller("all-settings.ini")
        self.load_sales(controller)
        sales_id = str(controller.activeTableId)
        self.assertTrue(controller.addPageFilterRule(
            sales_id, "Color", "equals", "Red", "", "", "and"
        ))
        self.assertTrue(controller.addPageFilterRule(
            sales_id, "Region", "equals", "East", "", "", "and"
        ))
        for name, expression in (
            ("ALL Color", "CALCULATE(SUM([Amount]), ALL('Sales'[Color]))"),
            ("ALL Region", "CALCULATE(SUM([Amount]), ALL('Sales'[Region]))"),
            ("ALL Table", "CALCULATE(SUM([Amount]), ALL('Sales'))"),
            ("ALL Context", "CALCULATE(SUM([Amount]), ALL())"),
        ):
            self.assertTrue(controller.create_measure(name, expression), controller.statusMessage)
        project_path = self.root / "all-modifier.npa"
        self.assertTrue(controller._save_to(project_path))

        self.sales_path.write_text(
            "ID,Color,Region,Amount,Active\n"
            "1,Red,East,21,True\n"
            "2,Blue,East,12,False\n"
            "3,Green,East,7,True\n"
            "4,Blue,West,31,True\n"
            "5,Green,West,40,False\n"
            "6,Red,West,50,True\n",
            encoding="utf-8",
        )
        reopened = self.controller("all-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["ALL Color"], "40")
        self.assertEqual(reopened.reportKpis["ALL Region"], "71")
        self.assertEqual(reopened.reportKpis["ALL Table"], "161")
        self.assertEqual(reopened.reportKpis["ALL Context"], "161")

    def test_userelationship_uses_inactive_date_role_and_restores_nested_context(self) -> None:
        dates = [
            {"Date": "2024-01-01"},
            {"Date": "2024-01-02"},
        ]
        sales = [
            {"OrderDate": "2024-01-01", "ShipDate": "2024-01-02", "Amount": "10"},
            {"OrderDate": "2024-01-02", "ShipDate": "2024-01-01", "Amount": "20"},
            {"OrderDate": "2024-01-01", "ShipDate": "2024-01-01", "Amount": "30"},
        ]
        relationships = [
            {
                "relationship_version": 1,
                "id": "calendar-order-date",
                "from": "Calendar[Date]",
                "to": "Sales[OrderDate]",
                "from_table_id": "calendar-id",
                "from_column": "Date",
                "to_table_id": "sales-id",
                "to_column": "OrderDate",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": True,
            },
            {
                "relationship_version": 1,
                "id": "calendar-ship-date",
                "from": "Calendar[Date]",
                "to": "Sales[ShipDate]",
                "from_table_id": "calendar-id",
                "from_column": "Date",
                "to_table_id": "sales-id",
                "to_column": "ShipDate",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": False,
            },
        ]
        values = evaluate_measures(
            [
                {"name": "Order role", "expression": "SUM([Amount])"},
                {
                    "name": "Ship role",
                    "expression": (
                        "CALCULATE(SUM([Amount]), "
                        "USERELATIONSHIP('Sales'[ShipDate], 'Calendar'[Date]))"
                    ),
                },
                {
                    "name": "Reverse arguments",
                    "expression": (
                        "CALCULATE(SUM([Amount]), "
                        "USERELATIONSHIP('Calendar'[Date], 'Sales'[ShipDate]))"
                    ),
                },
                {
                    "name": "Nested relationship",
                    "expression": (
                        "CALCULATE(CALCULATE(SUM([Amount]), "
                        "USERELATIONSHIP('Calendar'[Date], 'Sales'[OrderDate])), "
                        "USERELATIONSHIP('Calendar'[Date], 'Sales'[ShipDate]))"
                    ),
                },
                {
                    "name": "Context restored between calls",
                    "expression": (
                        "CALCULATE(SUM([Amount]), "
                        "USERELATIONSHIP('Sales'[ShipDate], 'Calendar'[Date])) + "
                        "CALCULATE(SUM([Amount]), "
                        "USERELATIONSHIP('Sales'[OrderDate], 'Calendar'[Date]))"
                    ),
                },
            ],
            sales,
            ["OrderDate", "ShipDate", "Amount"],
            "Sales",
            table_context=[
                {
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date"],
                    "rows": dates,
                    "column_types": {"Date": "date"},
                    "filter_rows": [dates[0]],
                    "filter_column_rows": {"Date": {0}},
                    "filter_column_blank_allowed": {"Date": False},
                    "filter_context_complete": True,
                },
                {
                    "id": "sales-id",
                    "name": "Sales",
                    "headers": ["OrderDate", "ShipDate", "Amount"],
                    "rows": sales,
                    "column_types": {
                        "OrderDate": "date",
                        "ShipDate": "date",
                        "Amount": "whole_number",
                    },
                },
            ],
            relationships=relationships,
            filter_table_ids={"calendar-id"},
            active_table_id="sales-id",
        )
        self.assertEqual(values, {
            "Order role": 40,
            "Ship role": 50,
            "Reverse arguments": 50,
            "Nested relationship": 40,
            "Context restored between calls": 90,
        })

    def test_userelationship_parser_and_existing_relationship_validation(self) -> None:
        for expression in (
            "CALCULATE(SUM([Amount]), USERELATIONSHIP('Sales'[ShipDate], 'Calendar'[Date]))",
            "CALCULATE(SUM([Amount]), USERELATIONSHIP('Sales'[OrderDate], 'Calendar'[Date]), "
            "USERELATIONSHIP('Sales'[RegionId], 'Region'[Id]))",
        ):
            with self.subTest(expression=expression):
                normalize_measure("Valid USERELATIONSHIP", expression)

        for expression in (
            "USERELATIONSHIP('Sales'[ShipDate], 'Calendar'[Date])",
            "CALCULATE(SUM([Amount]), USERELATIONSHIP([ShipDate], 'Calendar'[Date]))",
            "CALCULATE(SUM([Amount]), USERELATIONSHIP('Sales'[ShipDate]))",
            "CALCULATE(SUM([Amount]), USERELATIONSHIP('Sales'[ShipDate], 'Calendar'[Date]), "
            "'Sales'[Amount] > 0)",
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(MeasureError):
                    normalize_measure("Invalid USERELATIONSHIP", expression)

        sales = [{"OrderDate": "2024-01-01", "ShipDate": "2024-01-02", "Amount": "10"}]
        calendars = [{"Date": "2024-01-01"}, {"Date": "2024-01-02"}]
        contexts = [
            {
                "id": "calendar-id",
                "name": "Calendar",
                "headers": ["Date"],
                "rows": calendars,
                "column_types": {"Date": "date"},
            },
            {
                "id": "sales-id",
                "name": "Sales",
                "headers": ["OrderDate", "ShipDate", "Amount"],
                "rows": sales,
                "column_types": {"OrderDate": "date", "ShipDate": "date"},
            },
        ]
        relationship = {
            "relationship_version": 1,
            "id": "calendar-order-date",
            "from": "Calendar[Date]",
            "to": "Sales[OrderDate]",
            "from_table_id": "calendar-id",
            "from_column": "Date",
            "to_table_id": "sales-id",
            "to_column": "OrderDate",
            "cardinality": "one_to_many",
            "cross_filter_direction": "single",
            "is_active": True,
        }
        with self.assertRaisesRegex(MeasureError, "one existing model relationship"):
            evaluate_measures(
                [{
                    "name": "Missing link",
                    "expression": (
                        "CALCULATE(SUM([Amount]), "
                        "USERELATIONSHIP('Sales'[ShipDate], 'Calendar'[Date]))"
                    ),
                }],
                sales,
                ["OrderDate", "ShipDate", "Amount"],
                "Sales",
                table_context=contexts,
                relationships=[relationship],
                active_table_id="sales-id",
            )

    def test_userelationship_one_to_one_uses_argument_direction(self) -> None:
        left = [{"Key": "1"}, {"Key": "2"}, {"Key": "3"}]
        right = [{"Key": "1"}, {"Key": "2"}]
        relationship = {
            "relationship_version": 1,
            "id": "left-right-one-to-one",
            "from": "Left[Key]",
            "to": "Right[Key]",
            "from_table_id": "left-id",
            "from_column": "Key",
            "to_table_id": "right-id",
            "to_column": "Key",
            "cardinality": "one_to_one",
            "cross_filter_direction": "single",
            "is_active": False,
        }
        values = evaluate_measures(
            [
                {
                    "name": "Right filters left",
                    "expression": (
                        "CALCULATE(COUNTROWS('Left'), "
                        "USERELATIONSHIP('Left'[Key], 'Right'[Key]))"
                    ),
                },
                {
                    "name": "Left does not filter right",
                    "expression": (
                        "CALCULATE(COUNTROWS('Left'), "
                        "USERELATIONSHIP('Right'[Key], 'Left'[Key]))"
                    ),
                },
                {
                    "name": "Both directions",
                    "expression": (
                        "CALCULATE(COUNTROWS('Left'), "
                        "USERELATIONSHIP('Left'[Key], 'Right'[Key]), "
                        "USERELATIONSHIP('Right'[Key], 'Left'[Key]))"
                    ),
                },
                {
                    "name": "Activated unknown member",
                    "expression": (
                        "CALCULATE(COUNTROWS(ALL('Right')), "
                        "USERELATIONSHIP('Left'[Key], 'Right'[Key]))"
                    ),
                },
            ],
            left,
            ["Key"],
            "Left",
            table_context=[
                {
                    "id": "left-id",
                    "name": "Left",
                    "headers": ["Key"],
                    "rows": left,
                    "column_types": {"Key": "whole_number"},
                },
                {
                    "id": "right-id",
                    "name": "Right",
                    "headers": ["Key"],
                    "rows": right,
                    "column_types": {"Key": "whole_number"},
                    "filter_rows": [right[1]],
                    "filter_column_rows": {"Key": {1}},
                    "filter_column_blank_allowed": {"Key": False},
                    "filter_context_complete": True,
                },
            ],
            relationships=[relationship],
            filter_table_ids={"right-id"},
            active_table_id="left-id",
        )
        self.assertEqual(values, {
            "Right filters left": 1,
            "Left does not filter right": 3,
            "Both directions": 1,
            "Activated unknown member": 3,
        })

    def test_userelationship_activates_multiple_links_along_a_table_path(self) -> None:
        accounts = [{"Key": "1"}, {"Key": "2"}]
        mappings = [
            {"AccountKey": "1", "ProductKey": "P1"},
            {"AccountKey": "2", "ProductKey": "P2"},
        ]
        products = [
            {"Key": "P1", "Amount": "5"},
            {"Key": "P2", "Amount": "10"},
        ]
        relationships = [
            {
                "relationship_version": 1,
                "id": "accounts-mappings",
                "from": "Accounts[Key]",
                "to": "Mappings[AccountKey]",
                "from_table_id": "accounts-id",
                "from_column": "Key",
                "to_table_id": "mappings-id",
                "to_column": "AccountKey",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": False,
            },
            {
                "relationship_version": 1,
                "id": "mappings-products",
                "from": "Mappings[ProductKey]",
                "to": "Products[Key]",
                "from_table_id": "mappings-id",
                "from_column": "ProductKey",
                "to_table_id": "products-id",
                "to_column": "Key",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": False,
            },
        ]
        values = evaluate_measures(
            [{
                "name": "Account product sales",
                "expression": (
                    "CALCULATE(SUM([Amount]), "
                    "USERELATIONSHIP('Accounts'[Key], 'Mappings'[AccountKey]), "
                    "USERELATIONSHIP('Mappings'[ProductKey], 'Products'[Key]))"
                ),
            }],
            products,
            ["Key", "Amount"],
            "Products",
            table_context=[
                {
                    "id": "accounts-id",
                    "name": "Accounts",
                    "headers": ["Key"],
                    "rows": accounts,
                    "column_types": {"Key": "whole_number"},
                    "filter_rows": [accounts[0]],
                    "filter_column_rows": {"Key": {0}},
                    "filter_column_blank_allowed": {"Key": False},
                    "filter_context_complete": True,
                },
                {
                    "id": "mappings-id",
                    "name": "Mappings",
                    "headers": ["AccountKey", "ProductKey"],
                    "rows": mappings,
                    "column_types": {"AccountKey": "whole_number", "ProductKey": "text"},
                },
                {
                    "id": "products-id",
                    "name": "Products",
                    "headers": ["Key", "Amount"],
                    "rows": products,
                    "column_types": {"Key": "text", "Amount": "whole_number"},
                },
            ],
            relationships=relationships,
            filter_table_ids={"accounts-id"},
            active_table_id="products-id",
        )
        self.assertEqual(values["Account product sales"], 5)

    def test_userelationship_measure_persists_and_replays_after_source_change(self) -> None:
        calendar_path = self.root / "Calendar.csv"
        calendar_path.write_text(
            "Date\n2024-01-01\n2024-01-02\n", encoding="utf-8"
        )
        self.sales_path.write_text(
            "OrderDate,ShipDate,Amount\n"
            "2024-01-01,2024-01-02,10\n"
            "2024-01-02,2024-01-01,20\n"
            "2024-01-01,2024-01-01,30\n",
            encoding="utf-8",
        )
        controller = self.controller("userelationship-settings.ini")
        self.assertTrue(
            controller._commit_import(calendar_path, parse_file(calendar_path)),
            controller.statusMessage,
        )
        calendar_id = str(controller.activeTableId)
        self.assertTrue(controller.setColumnType("Date", "date"), controller.statusMessage)
        self.assertTrue(
            controller._commit_import(self.sales_path, parse_file(self.sales_path)),
            controller.statusMessage,
        )
        sales_id = str(controller.activeTableId)
        for column in ("OrderDate", "ShipDate"):
            self.assertTrue(
                controller.setColumnType(column, "date"), controller.statusMessage
            )
        self.assertTrue(
            controller.setColumnType("Amount", "whole_number"),
            controller.statusMessage,
        )
        controller._project["model"]["relationships"] = [
            {
                "relationship_version": 1,
                "id": "calendar-order-date",
                "from": "Calendar[Date]",
                "to": "Sales[OrderDate]",
                "from_table_id": calendar_id,
                "from_column": "Date",
                "to_table_id": sales_id,
                "to_column": "OrderDate",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": True,
            },
            {
                "relationship_version": 1,
                "id": "calendar-ship-date",
                "from": "Calendar[Date]",
                "to": "Sales[ShipDate]",
                "from_table_id": calendar_id,
                "from_column": "Date",
                "to_table_id": sales_id,
                "to_column": "ShipDate",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": False,
            },
        ]
        self.assertTrue(controller.addPageFilterRule(
            calendar_id, "Date", "equals", "2024-01-01", "", "", "and"
        ), controller.statusMessage)
        self.assertTrue(controller.create_measure(
            "Ship Sales",
            "CALCULATE(SUM([Amount]), USERELATIONSHIP('Sales'[ShipDate], 'Calendar'[Date]))",
        ), controller.statusMessage)
        self.assertEqual(controller.reportKpis["Ship Sales"], "50")
        project_path = self.root / "userelationship.npa"
        self.assertTrue(controller._save_to(project_path))

        self.sales_path.write_text(
            "OrderDate,ShipDate,Amount\n"
            "2024-01-01,2024-01-02,11\n"
            "2024-01-02,2024-01-01,22\n"
            "2024-01-01,2024-01-01,33\n",
            encoding="utf-8",
        )
        reopened = self.controller("userelationship-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Ship Sales"], "55")
        self.assertEqual(
            [relationship["is_active"] for relationship in reopened._project["model"]["relationships"]],
            [True, False],
        )

    def test_crossfilter_temporarily_changes_relationship_direction(self) -> None:
        categories = [{"Key": "1"}, {"Key": "2"}]
        sales = [
            {"Key": "1", "Region": "East", "Amount": "10"},
            {"Key": "1", "Region": "West", "Amount": "5"},
            {"Key": "2", "Region": "West", "Amount": "20"},
            {"Key": "99", "Region": "East", "Amount": "9"},
        ]
        relationship = {
            "relationship_version": 1,
            "id": "category-sales",
            "from": "Category[Key]",
            "to": "Sales[Key]",
            "from_table_id": "category-id",
            "from_column": "Key",
            "to_table_id": "sales-id",
            "to_column": "Key",
            "cardinality": "one_to_many",
            "cross_filter_direction": "single",
            "is_active": True,
        }
        measures = [
            {"name": "Visible sales", "expression": "COUNTROWS('Sales')"},
            {
                "name": "No propagation",
                "expression": "CALCULATE(COUNTROWS('Sales'), CROSSFILTER('Category'[Key], 'Sales'[Key], None))",
            },
            {
                "name": "One side to many side",
                "expression": "CALCULATE(COUNTROWS('Sales'), CROSSFILTER('Category'[Key], 'Sales'[Key], OneWay))",
            },
            {
                "name": "Many side to one side",
                "expression": "CALCULATE(COUNTROWS('Sales'), CROSSFILTER('Sales'[Key], 'Category'[Key], OneWay_LeftFiltersRight))",
            },
            {
                "name": "One side filters left",
                "expression": "CALCULATE(COUNTROWS('Sales'), CROSSFILTER('Sales'[Key], 'Category'[Key], OneWay_RightFiltersLeft))",
            },
            {
                "name": "Visible categories",
                "expression": "COUNTROWS('Category')",
            },
            {
                "name": "Both directions",
                "expression": "CALCULATE(COUNTROWS('Category'), CROSSFILTER('Sales'[Key], 'Category'[Key], Both))",
            },
            {
                "name": "Nested override",
                "expression": (
                    "CALCULATE(CALCULATE(COUNTROWS('Category'), "
                    "CROSSFILTER('Sales'[Key], 'Category'[Key], None)), "
                    "CROSSFILTER('Sales'[Key], 'Category'[Key], Both))"
                ),
            },
        ]

        category_root = evaluate_measures(
            measures[:5],
            categories,
            ["Key"],
            "Category",
            table_context=[
                {
                    "id": "category-id",
                    "name": "Category",
                    "headers": ["Key"],
                    "rows": categories,
                    "column_types": {"Key": "whole_number"},
                    "filter_rows": [categories[0]],
                    "filter_column_rows": {"Key": {0}},
                    "filter_column_blank_allowed": {"Key": False},
                    "filter_context_complete": True,
                },
                {
                    "id": "sales-id",
                    "name": "Sales",
                    "headers": ["Key", "Region", "Amount"],
                    "rows": sales,
                    "column_types": {"Key": "whole_number", "Region": "text", "Amount": "whole_number"},
                },
            ],
            relationships=[relationship],
            filter_table_ids={"category-id"},
            active_table_id="category-id",
        )
        self.assertEqual(category_root, {
            "Visible sales": 2,
            "No propagation": 4,
            "One side to many side": 2,
            "Many side to one side": 4,
            "One side filters left": 2,
        })

        east_rows = [sales[0], sales[3]]
        sales_root = evaluate_measures(
            measures[5:],
            categories,
            ["Key"],
            "Category",
            table_context=[
                {
                    "id": "category-id",
                    "name": "Category",
                    "headers": ["Key"],
                    "rows": categories,
                    "column_types": {"Key": "whole_number"},
                },
                {
                    "id": "sales-id",
                    "name": "Sales",
                    "headers": ["Key", "Region", "Amount"],
                    "rows": sales,
                    "column_types": {"Key": "whole_number", "Region": "text", "Amount": "whole_number"},
                    "filter_rows": east_rows,
                    "filter_column_rows": {"Region": {0, 3}},
                    "filter_column_blank_allowed": {"Region": False},
                    "filter_context_complete": True,
                },
            ],
            relationships=[relationship],
            filter_table_ids={"sales-id"},
            active_table_id="category-id",
        )
        self.assertEqual(sales_root, {
            "Visible categories": 3,
            "Both directions": 1,
            "Nested override": 3,
        })

    def test_crossfilter_measure_persists_and_replays_after_source_change(self) -> None:
        category_path = self.root / "Category.csv"
        sales_path = self.root / "CrossfilterSales.csv"
        category_path.write_text("Key\n1\n2\n3\n", encoding="utf-8")
        sales_path.write_text(
            "CategoryKey,Region\n1,East\n2,West\n", encoding="utf-8"
        )
        controller = self.controller("crossfilter-settings.ini")
        self.assertTrue(
            controller._commit_import(category_path, parse_file(category_path)),
            controller.statusMessage,
        )
        category_id = str(controller.activeTableId)
        self.assertTrue(controller.setColumnType("Key", "whole_number"), controller.statusMessage)
        self.assertTrue(
            controller._commit_import(sales_path, parse_file(sales_path)),
            controller.statusMessage,
        )
        sales_id = str(controller.activeTableId)
        self.assertTrue(
            controller.setColumnType("CategoryKey", "whole_number"),
            controller.statusMessage,
        )
        controller._project["model"]["relationships"] = [{
            "relationship_version": 1,
            "id": "category-crossfilter-sales",
            "from": "Category[Key]",
            "to": "CrossfilterSales[CategoryKey]",
            "from_table_id": category_id,
            "from_column": "Key",
            "to_table_id": sales_id,
            "to_column": "CategoryKey",
            "cardinality": "one_to_many",
            "cross_filter_direction": "single",
            "is_active": True,
        }]
        self.assertTrue(controller.addPageFilterRule(
            sales_id, "Region", "equals", "East", "", "", "and"
        ), controller.statusMessage)
        self.assertTrue(controller.create_measure(
            "Filtered categories",
            "CALCULATE(COUNTROWS('Category'), CROSSFILTER('CrossfilterSales'[CategoryKey], 'Category'[Key], Both))",
        ), controller.statusMessage)
        self.assertEqual(controller.reportKpis["Filtered categories"], "1")
        project_path = self.root / "crossfilter.npa"
        self.assertTrue(controller._save_to(project_path))

        sales_path.write_text(
            "CategoryKey,Region\n1,East\n2,East\n", encoding="utf-8"
        )
        reopened = self.controller("crossfilter-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Filtered categories"], "2")
        saved_relationship = reopened._project["model"]["relationships"][0]
        self.assertEqual(saved_relationship["cross_filter_direction"], "single")

    def test_crossfilter_parser_and_relationship_validation(self) -> None:
        normalize_measure(
            "Valid CROSSFILTER",
            "CALCULATE(SUM([Amount]), CROSSFILTER('Sales'[Key], 'Category'[Key], Both))",
        )
        for expression in (
            "CROSSFILTER('Sales'[Key], 'Category'[Key], Both)",
            "CALCULATE(SUM([Amount]), CROSSFILTER([Key], 'Category'[Key], Both))",
            "CALCULATE(SUM([Amount]), CROSSFILTER('Sales'[Key], 'Category'[Key]))",
            "CALCULATE(SUM([Amount]), CROSSFILTER('Sales'[Key], 'Category'[Key], Both), 'Sales'[Amount] > 0)",
            'CALCULATE(SUM([Amount]), CROSSFILTER(\'Sales\'[Key], \'Category\'[Key], "Both"))',
        ):
            with self.subTest(expression=expression):
                with self.assertRaises(MeasureError):
                    normalize_measure("Invalid CROSSFILTER", expression)


if __name__ == "__main__":
    unittest.main()
