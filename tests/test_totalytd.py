"""Evaluation and project-lifecycle acceptance for local classic time intelligence."""

from __future__ import annotations

from datetime import date, timedelta
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.controller import StudioController
from analytics_studio.date_table_dialog import DateTableDialog
from analytics_studio.file_import import parse_file
from analytics_studio.measures import (
    MeasureError,
    _dateadd_dates,
    _sameperiodlastyear_dates,
    evaluate_measures,
    normalize_measure,
)
from analytics_studio.relationship_dialog import RelationshipDialog


class TotalYtdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    @staticmethod
    def _relationship() -> dict[str, object]:
        return {
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
        }

    def test_totalytd_replaces_the_date_filter_and_keeps_other_filters(self) -> None:
        calendar_rows = [
            {"Date": (date(2024, 1, 1) + timedelta(days=offset)).isoformat()}
            for offset in range(366)
        ]
        march_rows = [row for row in calendar_rows if row["Date"].startswith("2024-03-")]
        order_rows = [
            {"OrderDate": "2023-12-31", "Amount": "5", "Region": "East"},
            {"OrderDate": "2024-01-05", "Amount": "10", "Region": "East"},
            {"OrderDate": "2024-02-02", "Amount": "20", "Region": "East"},
            {"OrderDate": "2024-03-30", "Amount": "30", "Region": "East"},
            {"OrderDate": "2024-03-15", "Amount": "300", "Region": "West"},
            {"OrderDate": "2024-04-02", "Amount": "40", "Region": "East"},
        ]
        table_context = [
            {
                "id": "calendar-id",
                "name": "Calendar",
                "headers": ["Date"],
                "rows": calendar_rows,
                "filter_rows": march_rows,
                "column_types": {"Date": "date"},
                "date_column": "Date",
            },
            {
                "id": "orders-id",
                "name": "Orders",
                "headers": ["OrderDate", "Amount", "Region"],
                "rows": order_rows,
                "filter_rows": [row for row in order_rows if row["Region"] == "East"],
                "column_types": {"OrderDate": "date", "Amount": "whole_number"},
            },
        ]
        measures = [
            {"name": "Current sales", "expression": "SUM('Orders'[Amount])"},
            {
                "name": "Sales YTD",
                "expression": "TOTALYTD([Current sales], 'Calendar'[Date])",
            },
            {
                "name": "YTD plus current",
                "expression": "[Sales YTD] + [Current sales]",
            },
        ]

        values = evaluate_measures(
            measures,
            table_context[1]["rows"],
            table_context[1]["headers"],
            "Orders",
            table_context=table_context,
            relationships=[self._relationship()],
            filter_table_ids={"calendar-id", "orders-id"},
            active_table_id="orders-id",
        )

        self.assertEqual(values["Current sales"], 30)
        self.assertEqual(values["Sales YTD"], 60)
        self.assertEqual(values["YTD plus current"], 90)

    def test_totalytd_uses_the_configured_fiscal_year_end(self) -> None:
        calendar_start = date(2023, 6, 30)
        calendar_end = date(2024, 7, 1)
        calendar_rows = [
            {"Date": (calendar_start + timedelta(days=offset)).isoformat()}
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        march_rows = [
            row for row in calendar_rows if row["Date"].startswith("2024-03-")
        ]
        order_rows = [
            {"OrderDate": "2023-06-30", "Amount": "1"},
            {"OrderDate": "2023-07-01", "Amount": "10"},
            {"OrderDate": "2023-12-31", "Amount": "20"},
            {"OrderDate": "2024-03-30", "Amount": "30"},
            {"OrderDate": "2024-04-02", "Amount": "40"},
            {"OrderDate": "2024-06-30", "Amount": "5"},
            {"OrderDate": "2024-07-01", "Amount": "7"},
        ]
        expression = 'TOTALYTD(SUM([Amount]), \'Calendar\'[Date],, "6/30")'

        def fiscal_ytd_for(visible_calendar_rows: list[dict[str, str]]) -> int:
            table_context = [
                {
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date"],
                    "rows": calendar_rows,
                    "filter_rows": visible_calendar_rows,
                    "column_types": {"Date": "date"},
                    "date_column": "Date",
                },
                {
                    "id": "orders-id",
                    "name": "Orders",
                    "headers": ["OrderDate", "Amount"],
                    "rows": order_rows,
                    "filter_rows": order_rows,
                    "column_types": {"OrderDate": "date", "Amount": "whole_number"},
                },
            ]
            values = evaluate_measures(
                [{"name": "Sales Fiscal YTD", "expression": expression}],
                order_rows,
                ["OrderDate", "Amount"],
                "Orders",
                table_context=table_context,
                relationships=[self._relationship()],
                filter_table_ids={"calendar-id", "orders-id"},
                active_table_id="orders-id",
            )
            return int(values["Sales Fiscal YTD"])

        # March 2024 starts on July 1, 2023 for a June 30 fiscal year end.
        self.assertEqual(fiscal_ytd_for(march_rows), 60)
        june_30 = [row for row in calendar_rows if row["Date"] == "2024-06-30"]
        july_1 = [row for row in calendar_rows if row["Date"] == "2024-07-01"]
        self.assertEqual(fiscal_ytd_for(june_30), 105)
        self.assertEqual(fiscal_ytd_for(july_1), 7)

    def test_totalytd_clamps_february_29_for_non_leap_years(self) -> None:
        calendar_rows = [
            {"Date": day.isoformat()}
            for day in (date(2023, 2, 28), date(2023, 3, 1))
        ]
        order_rows = [
            {"OrderDate": "2023-02-28", "Amount": "5"},
            {"OrderDate": "2023-03-01", "Amount": "10"},
        ]
        values = evaluate_measures(
            [{
                "name": "Leap Fiscal YTD",
                "expression": 'TOTALYTD(SUM([Amount]), \'Calendar\'[Date],, "2/29")',
            }],
            order_rows,
            ["OrderDate", "Amount"],
            "Orders",
            table_context=[
                {
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date"],
                    "rows": calendar_rows,
                    "filter_rows": [calendar_rows[-1]],
                    "column_types": {"Date": "date"},
                    "date_column": "Date",
                },
                {
                    "id": "orders-id",
                    "name": "Orders",
                    "headers": ["OrderDate", "Amount"],
                    "rows": order_rows,
                    "filter_rows": order_rows,
                    "column_types": {"OrderDate": "date", "Amount": "whole_number"},
                },
            ],
            relationships=[self._relationship()],
            filter_table_ids={"calendar-id", "orders-id"},
            active_table_id="orders-id",
        )

        self.assertEqual(values["Leap Fiscal YTD"], 10)

        leap_start = date(2023, 3, 1)
        leap_end = date(2024, 3, 1)
        leap_calendar_rows = [
            {"Date": (leap_start + timedelta(days=offset)).isoformat()}
            for offset in range((leap_end - leap_start).days + 1)
        ]
        leap_orders = [
            {"OrderDate": "2023-03-01", "Amount": "10"},
            {"OrderDate": "2024-02-28", "Amount": "5"},
            {"OrderDate": "2024-02-29", "Amount": "20"},
            {"OrderDate": "2024-03-01", "Amount": "30"},
        ]
        leap_values = evaluate_measures(
            [{
                "name": "Leap Fiscal YTD",
                "expression": 'TOTALYTD(SUM([Amount]), \'Calendar\'[Date],, "2/29")',
            }],
            leap_orders,
            ["OrderDate", "Amount"],
            "Orders",
            table_context=[
                {
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date"],
                    "rows": leap_calendar_rows,
                    "filter_rows": [
                        row for row in leap_calendar_rows
                        if row["Date"] == "2024-02-29"
                    ],
                    "column_types": {"Date": "date"},
                    "date_column": "Date",
                },
                {
                    "id": "orders-id",
                    "name": "Orders",
                    "headers": ["OrderDate", "Amount"],
                    "rows": leap_orders,
                    "filter_rows": leap_orders,
                    "column_types": {"OrderDate": "date", "Amount": "whole_number"},
                },
            ],
            relationships=[self._relationship()],
            filter_table_ids={"calendar-id", "orders-id"},
            active_table_id="orders-id",
        )

        self.assertEqual(leap_values["Leap Fiscal YTD"], 35)

    def test_totalytd_rejects_invalid_fiscal_dates_and_filter_expressions(self) -> None:
        with self.assertRaisesRegex(MeasureError, "month/day"):
            normalize_measure(
                "Invalid year end",
                'TOTALYTD(SUM([Amount]), \'Calendar\'[Date],, "6/31")',
            )

        with self.assertRaisesRegex(MeasureError, "month/day"):
            normalize_measure(
                "Non-ASCII year end",
                'TOTALYTD(SUM([Amount]), \'Calendar\'[Date],, "６/３０")',
            )

        with self.assertRaisesRegex(MeasureError, "Filter expressions are not supported"):
            normalize_measure(
                "Unsupported filter",
                'TOTALYTD(SUM([Amount]), \'Calendar\'[Date], 1, "6/30")',
            )

        with self.assertRaisesRegex(MeasureError, "String literals are supported only"):
            normalize_measure("Unexpected string", '"6/30"')

        with self.assertRaisesRegex(MeasureError, "optional filter argument"):
            normalize_measure("Unexpected omission", "DIVIDE(1,,3)")

    def test_totalytd_requires_the_marked_date_column_and_two_arguments(self) -> None:
        with self.assertRaisesRegex(MeasureError, "TOTALYTD needs"):
            normalize_measure(
                "Bad arity",
                "TOTALYTD(SUM([Amount]), 'Calendar'[Date], 12)",
            )

        with self.assertRaisesRegex(MeasureError, "marked Date or DateTime"):
            evaluate_measures(
                [{
                    "name": "Sales YTD",
                    "expression": "TOTALYTD(SUM([Amount]), 'Calendar'[Date])",
                }],
                [{"Amount": "10", "Date": "2024-01-01"}],
                ["Amount", "Date"],
                "Calendar",
                table_context=[{
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Amount", "Date"],
                    "rows": [{"Amount": "10", "Date": "2024-01-01"}],
                    "column_types": {"Amount": "whole_number", "Date": "date"},
                }],
                active_table_id="calendar-id",
            )

    def test_totalqtd_replaces_date_filter_and_keeps_other_filters(self) -> None:
        calendar_start = date(2023, 12, 1)
        calendar_end = date(2024, 5, 31)
        calendar_rows = [
            {"Date": (calendar_start + timedelta(days=offset)).isoformat()}
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        may_rows = [
            row for row in calendar_rows
            if row["Date"].startswith("2024-05-") and row["Date"] <= "2024-05-15"
        ]
        order_rows = [
            {"OrderDate": "2023-12-31", "Amount": "5", "Region": "East"},
            {"OrderDate": "2024-01-05", "Amount": "10", "Region": "East"},
            {"OrderDate": "2024-03-30", "Amount": "20", "Region": "East"},
            {"OrderDate": "2024-04-02", "Amount": "30", "Region": "East"},
            {"OrderDate": "2024-05-04", "Amount": "40", "Region": "East"},
            {"OrderDate": "2024-05-15", "Amount": "50", "Region": "East"},
            {"OrderDate": "2024-05-16", "Amount": "60", "Region": "East"},
            {"OrderDate": "2024-05-10", "Amount": "700", "Region": "West"},
        ]
        values = evaluate_measures(
            [{
                "name": "Sales QTD",
                "expression": "TOTALQTD(SUM([Amount]), 'Calendar'[Date])",
            }],
            order_rows,
            ["OrderDate", "Amount", "Region"],
            "Orders",
            table_context=[
                {
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date"],
                    "rows": calendar_rows,
                    "filter_rows": may_rows,
                    "column_types": {"Date": "date"},
                    "date_column": "Date",
                },
                {
                    "id": "orders-id",
                    "name": "Orders",
                    "headers": ["OrderDate", "Amount", "Region"],
                    "rows": order_rows,
                    "filter_rows": [row for row in order_rows if row["Region"] == "East"],
                    "column_types": {"OrderDate": "date", "Amount": "whole_number"},
                },
            ],
            relationships=[self._relationship()],
            filter_table_ids={"calendar-id", "orders-id"},
            active_table_id="orders-id",
        )

        # April 1 begins this quarter. QTD replaces the May-only date filter,
        # stops at May 15, and retains the independent Region filter.
        self.assertEqual(values["Sales QTD"], 120)

    def test_totalqtd_requires_marked_date_column_and_rejects_filter_arguments(self) -> None:
        with self.assertRaisesRegex(MeasureError, "Filter expressions are not supported"):
            normalize_measure(
                "Unsupported QTD filter",
                "TOTALQTD(SUM([Amount]), 'Calendar'[Date], 1)",
            )

        with self.assertRaisesRegex(MeasureError, "marked Date or DateTime"):
            evaluate_measures(
                [{
                    "name": "Sales QTD",
                    "expression": "TOTALQTD(SUM([Amount]), 'Calendar'[Date])",
                }],
                [{"Date": "2024-04-02", "Amount": "10"}],
                ["Date", "Amount"],
                "Calendar",
                table_context=[{
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date", "Amount"],
                    "rows": [{"Date": "2024-04-02", "Amount": "10"}],
                    "column_types": {"Date": "date", "Amount": "whole_number"},
                }],
                active_table_id="calendar-id",
            )

    def test_totalmtd_replaces_date_filter_and_keeps_other_filters(self) -> None:
        calendar_start = date(2024, 1, 1)
        calendar_end = date(2024, 6, 30)
        calendar_rows = [
            {"Date": (calendar_start + timedelta(days=offset)).isoformat()}
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        selected_day = [row for row in calendar_rows if row["Date"] == "2024-06-15"]
        order_rows = [
            {"OrderDate": "2024-05-31", "Amount": "5", "Region": "East"},
            {"OrderDate": "2024-06-01", "Amount": "10", "Region": "East"},
            {"OrderDate": "2024-06-05", "Amount": "20", "Region": "East"},
            {"OrderDate": "2024-06-15", "Amount": "30", "Region": "East"},
            {"OrderDate": "2024-06-16", "Amount": "40", "Region": "East"},
            {"OrderDate": "2024-06-05", "Amount": "700", "Region": "West"},
        ]
        values = evaluate_measures(
            [{
                "name": "Sales MTD",
                "expression": "TOTALMTD(SUM([Amount]), 'Calendar'[Date])",
            }],
            order_rows,
            ["OrderDate", "Amount", "Region"],
            "Orders",
            table_context=[
                {
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date"],
                    "rows": calendar_rows,
                    "filter_rows": selected_day,
                    "column_types": {"Date": "date"},
                    "date_column": "Date",
                },
                {
                    "id": "orders-id",
                    "name": "Orders",
                    "headers": ["OrderDate", "Amount", "Region"],
                    "rows": order_rows,
                    "filter_rows": [row for row in order_rows if row["Region"] == "East"],
                    "column_types": {"OrderDate": "date", "Amount": "whole_number"},
                },
            ],
            relationships=[self._relationship()],
            filter_table_ids={"calendar-id", "orders-id"},
            active_table_id="orders-id",
        )

        # The June 15 selection expands back to June 1, excluding May 31,
        # later June rows, and orders filtered out by Region.
        self.assertEqual(values["Sales MTD"], 60)

    def test_totalmtd_requires_marked_date_column_and_rejects_filter_arguments(self) -> None:
        with self.assertRaisesRegex(MeasureError, "Filter expressions are not supported"):
            normalize_measure(
                "Unsupported MTD filter",
                "TOTALMTD(SUM([Amount]), 'Calendar'[Date], 1)",
            )

        with self.assertRaisesRegex(MeasureError, "marked Date or DateTime"):
            evaluate_measures(
                [{
                    "name": "Sales MTD",
                    "expression": "TOTALMTD(SUM([Amount]), 'Calendar'[Date])",
                }],
                [{"Date": "2024-06-02", "Amount": "10"}],
                ["Date", "Amount"],
                "Calendar",
                table_context=[{
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date", "Amount"],
                    "rows": [{"Date": "2024-06-02", "Amount": "10"}],
                    "column_types": {"Date": "date", "Amount": "whole_number"},
                }],
                active_table_id="calendar-id",
            )

    def test_dateadd_shifts_day_month_quarter_and_year_and_extends_month_end(self) -> None:
        self.assertEqual(
            _dateadd_dates([date(2024, 4, 1), date(2024, 4, 2)], -1, "DAY"),
            {date(2024, 3, 31), date(2024, 4, 1)},
        )
        self.assertEqual(
            _dateadd_dates([date(2024, 4, 1), date(2024, 4, 2)], -1, "QUARTER"),
            {date(2024, 1, 1), date(2024, 1, 2)},
        )
        self.assertEqual(
            _dateadd_dates([date(2024, 3, 1), date(2024, 3, 2)], -1, "YEAR"),
            {date(2023, 3, 1), date(2023, 3, 2)},
        )
        self.assertEqual(
            _dateadd_dates([date(2013, 2, 27), date(2013, 2, 28)], 1, "MONTH"),
            {
                date(2013, 3, 27), date(2013, 3, 28), date(2013, 3, 29),
                date(2013, 3, 30), date(2013, 3, 31),
            },
        )

    def test_calculate_dateadd_replaces_date_filter_and_preserves_other_filters(self) -> None:
        calendar_start = date(2023, 1, 1)
        calendar_end = date(2024, 12, 31)
        calendar_rows = [
            {"Date": (calendar_start + timedelta(days=offset)).isoformat()}
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        selected_dates = [
            row for row in calendar_rows
            if "2024-03-01" <= row["Date"] <= "2024-03-03"
        ]
        order_rows = [
            {"OrderDate": "2023-03-01", "Amount": "10", "Region": "East"},
            {"OrderDate": "2023-03-02", "Amount": "20", "Region": "East"},
            {"OrderDate": "2023-03-03", "Amount": "30", "Region": "East"},
            {"OrderDate": "2023-03-04", "Amount": "400", "Region": "East"},
            {"OrderDate": "2024-03-01", "Amount": "500", "Region": "East"},
            {"OrderDate": "2023-03-02", "Amount": "700", "Region": "West"},
        ]
        values = evaluate_measures(
            [{
                "name": "Prior year sales",
                "expression": (
                    "CALCULATE(SUM([Amount]), "
                    "DATEADD('Calendar'[Date], -1, YEAR))"
                ),
            }],
            order_rows,
            ["OrderDate", "Amount", "Region"],
            "Orders",
            table_context=[
                {
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date"],
                    "rows": calendar_rows,
                    "filter_rows": selected_dates,
                    "column_types": {"Date": "date"},
                    "date_column": "Date",
                },
                {
                    "id": "orders-id",
                    "name": "Orders",
                    "headers": ["OrderDate", "Amount", "Region"],
                    "rows": order_rows,
                    "filter_rows": [row for row in order_rows if row["Region"] == "East"],
                    "column_types": {"OrderDate": "date", "Amount": "whole_number"},
                },
            ],
            relationships=[self._relationship()],
            filter_table_ids={"calendar-id", "orders-id"},
            active_table_id="orders-id",
        )

        self.assertEqual(values["Prior year sales"], 60)

    def test_sameperiodlastyear_shifts_dates_and_applies_documented_month_end_extension(self) -> None:
        self.assertEqual(
            _sameperiodlastyear_dates([date(2009, 2, 27), date(2009, 2, 28)]),
            {date(2008, 2, 27), date(2008, 2, 28), date(2008, 2, 29)},
        )
        self.assertEqual(
            _sameperiodlastyear_dates([date(2009, 2, 27)]),
            {date(2008, 2, 27)},
        )
        self.assertEqual(
            _sameperiodlastyear_dates([date(2024, 2, 28), date(2024, 2, 29)]),
            {date(2023, 2, 28)},
        )
        self.assertEqual(
            _sameperiodlastyear_dates([date(2024, 2, 29)]),
            {date(2023, 2, 28)},
        )
        with self.assertRaisesRegex(MeasureError, "SAMEPERIODLASTYEAR.*contiguous"):
            _sameperiodlastyear_dates([date(2024, 2, 27), date(2024, 2, 29)])

    def test_calculate_sameperiodlastyear_replaces_date_filter_and_preserves_other_filters(self) -> None:
        calendar_start = date(2023, 1, 1)
        calendar_end = date(2024, 12, 31)
        calendar_rows = [
            {"Date": (calendar_start + timedelta(days=offset)).isoformat()}
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        selected_dates = [
            row for row in calendar_rows
            if "2024-03-01" <= row["Date"] <= "2024-03-03"
        ]
        order_rows = [
            {"OrderDate": "2023-03-01", "Amount": "10", "Region": "East"},
            {"OrderDate": "2023-03-02", "Amount": "20", "Region": "East"},
            {"OrderDate": "2023-03-03", "Amount": "30", "Region": "East"},
            {"OrderDate": "2023-03-04", "Amount": "400", "Region": "East"},
            {"OrderDate": "2024-03-01", "Amount": "500", "Region": "East"},
            {"OrderDate": "2023-03-02", "Amount": "700", "Region": "West"},
        ]
        values = evaluate_measures(
            [{
                "name": "Prior year sales",
                "expression": (
                    "CALCULATE(SUM([Amount]), "
                    "SAMEPERIODLASTYEAR('Calendar'[Date]))"
                ),
            }],
            order_rows,
            ["OrderDate", "Amount", "Region"],
            "Orders",
            table_context=[
                {
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date"],
                    "rows": calendar_rows,
                    "filter_rows": selected_dates,
                    "column_types": {"Date": "date"},
                    "date_column": "Date",
                },
                {
                    "id": "orders-id",
                    "name": "Orders",
                    "headers": ["OrderDate", "Amount", "Region"],
                    "rows": order_rows,
                    "filter_rows": [row for row in order_rows if row["Region"] == "East"],
                    "column_types": {"OrderDate": "date", "Amount": "whole_number"},
                },
            ],
            relationships=[self._relationship()],
            filter_table_ids={"calendar-id", "orders-id"},
            active_table_id="orders-id",
        )

        self.assertEqual(values["Prior year sales"], 60)

    def test_sameperiodlastyear_rejects_invalid_forms_and_unmarked_columns(self) -> None:
        with self.assertRaisesRegex(MeasureError, "one marked date-column reference"):
            normalize_measure(
                "Invalid prior year",
                "SAMEPERIODLASTYEAR('Calendar'[Date], 1)",
            )
        with self.assertRaisesRegex(MeasureError, "Table-valued functions"):
            normalize_measure(
                "Bare prior year",
                "SAMEPERIODLASTYEAR('Calendar'[Date])",
            )
        with self.assertRaisesRegex(MeasureError, "marked Date or DateTime"):
            evaluate_measures(
                [{
                    "name": "Prior year sales",
                    "expression": (
                        "CALCULATE(SUM([Amount]), "
                        "SAMEPERIODLASTYEAR('Calendar'[Date]))"
                    ),
                }],
                [{"Date": "2024-03-01", "Amount": "10"}],
                ["Date", "Amount"],
                "Calendar",
                table_context=[{
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date", "Amount"],
                    "rows": [{"Date": "2024-03-01", "Amount": "10"}],
                    "column_types": {"Date": "date", "Amount": "whole_number"},
                }],
                active_table_id="calendar-id",
            )

    def test_calculate_datesytd_uses_calendar_and_fiscal_year_start(self) -> None:
        calendar_start = date(2024, 1, 1)
        calendar_end = date(2024, 6, 30)
        calendar_rows = [
            {"Date": (calendar_start + timedelta(days=offset)).isoformat()}
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        selected_day = [
            row for row in calendar_rows
            if row["Date"] in {"2024-04-01", "2024-04-03"}
        ]
        order_rows = [
            {"OrderDate": "2023-04-02", "Amount": "500", "Region": "East"},
            {"OrderDate": "2024-01-05", "Amount": "10", "Region": "East"},
            {"OrderDate": "2024-02-02", "Amount": "20", "Region": "East"},
            {"OrderDate": "2024-03-30", "Amount": "30", "Region": "East"},
            {"OrderDate": "2024-04-01", "Amount": "35", "Region": "East"},
            {"OrderDate": "2024-04-02", "Amount": "40", "Region": "East"},
            {"OrderDate": "2024-04-03", "Amount": "45", "Region": "East"},
            {"OrderDate": "2024-04-04", "Amount": "55", "Region": "East"},
            {"OrderDate": "2024-03-15", "Amount": "700", "Region": "West"},
        ]
        values = evaluate_measures(
            [
                {
                    "name": "Sales YTD",
                    "expression": (
                        "CALCULATE(SUM([Amount]), DATESYTD('Calendar'[Date]))"
                    ),
                },
                {
                    "name": "Sales FYTD",
                    "expression": (
                        'CALCULATE(SUM([Amount]), DATESYTD(\'Calendar\'[Date], "3/31"))'
                    ),
                },
            ],
            order_rows,
            ["OrderDate", "Amount", "Region"],
            "Orders",
            table_context=[
                {
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date"],
                    "rows": calendar_rows,
                    "filter_rows": selected_day,
                    "column_types": {"Date": "date"},
                    "date_column": "Date",
                },
                {
                    "id": "orders-id",
                    "name": "Orders",
                    "headers": ["OrderDate", "Amount", "Region"],
                    "rows": order_rows,
                    "filter_rows": [row for row in order_rows if row["Region"] == "East"],
                    "column_types": {"OrderDate": "date", "Amount": "whole_number"},
                },
            ],
            relationships=[self._relationship()],
            filter_table_ids={"calendar-id", "orders-id"},
            active_table_id="orders-id",
        )

        self.assertEqual(values["Sales YTD"], 180)
        self.assertEqual(values["Sales FYTD"], 120)

    def test_datesytd_rejects_invalid_forms_and_unmarked_columns(self) -> None:
        with self.assertRaisesRegex(MeasureError, "DATESYTD needs"):
            normalize_measure(
                "Invalid DATESYTD",
                "DATESYTD('Calendar'[Date], \"3/31\", 1)",
            )
        with self.assertRaisesRegex(MeasureError, "valid month/day"):
            normalize_measure(
                "Invalid DATESYTD year end",
                'CALCULATE(SUM([Amount]), DATESYTD(\'Calendar\'[Date], "13/31"))',
            )
        with self.assertRaisesRegex(MeasureError, "Table-valued functions"):
            normalize_measure(
                "Bare DATESYTD",
                "DATESYTD('Calendar'[Date])",
            )
        with self.assertRaisesRegex(MeasureError, "marked Date or DateTime"):
            evaluate_measures(
                [{
                    "name": "Sales YTD",
                    "expression": (
                        "CALCULATE(SUM([Amount]), DATESYTD('Calendar'[Date]))"
                    ),
                }],
                [{"Date": "2024-04-02", "Amount": "10"}],
                ["Date", "Amount"],
                "Calendar",
                table_context=[{
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date", "Amount"],
                    "rows": [{"Date": "2024-04-02", "Amount": "10"}],
                    "column_types": {"Date": "date", "Amount": "whole_number"},
                }],
                active_table_id="calendar-id",
            )

    def test_calculate_datesqtd_uses_visible_quarter_and_preserves_other_filters(self) -> None:
        calendar_start = date(2024, 1, 1)
        calendar_end = date(2024, 6, 30)
        calendar_rows = [
            {"Date": (calendar_start + timedelta(days=offset)).isoformat()}
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        selected_day = [row for row in calendar_rows if row["Date"] == "2024-05-15"]
        order_rows = [
            {"OrderDate": "2024-03-31", "Amount": "5", "Region": "East"},
            {"OrderDate": "2024-04-01", "Amount": "10", "Region": "East"},
            {"OrderDate": "2024-04-05", "Amount": "20", "Region": "East"},
            {"OrderDate": "2024-05-15", "Amount": "30", "Region": "East"},
            {"OrderDate": "2024-05-16", "Amount": "40", "Region": "East"},
            {"OrderDate": "2024-05-15", "Amount": "700", "Region": "West"},
        ]
        values = evaluate_measures(
            [{
                "name": "Sales QTD date set",
                "expression": (
                    "CALCULATE(SUM([Amount]), DATESQTD('Calendar'[Date]))"
                ),
            }],
            order_rows,
            ["OrderDate", "Amount", "Region"],
            "Orders",
            table_context=[
                {
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date"],
                    "rows": calendar_rows,
                    "filter_rows": selected_day,
                    "column_types": {"Date": "date"},
                    "date_column": "Date",
                },
                {
                    "id": "orders-id",
                    "name": "Orders",
                    "headers": ["OrderDate", "Amount", "Region"],
                    "rows": order_rows,
                    "filter_rows": [row for row in order_rows if row["Region"] == "East"],
                    "column_types": {"OrderDate": "date", "Amount": "whole_number"},
                },
            ],
            relationships=[self._relationship()],
            filter_table_ids={"calendar-id", "orders-id"},
            active_table_id="orders-id",
        )

        self.assertEqual(values["Sales QTD date set"], 60)

    def test_datesqtd_rejects_invalid_forms_and_unmarked_columns(self) -> None:
        with self.assertRaisesRegex(MeasureError, "one marked date-column reference"):
            normalize_measure(
                "Invalid DATESQTD",
                "DATESQTD('Calendar'[Date], 1)",
            )
        with self.assertRaisesRegex(MeasureError, "Table-valued functions"):
            normalize_measure(
                "Bare DATESQTD",
                "DATESQTD('Calendar'[Date])",
            )
        with self.assertRaisesRegex(MeasureError, "marked Date or DateTime"):
            evaluate_measures(
                [{
                    "name": "Sales QTD date set",
                    "expression": (
                        "CALCULATE(SUM([Amount]), DATESQTD('Calendar'[Date]))"
                    ),
                }],
                [{"Date": "2024-05-15", "Amount": "10"}],
                ["Date", "Amount"],
                "Calendar",
                table_context=[{
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date", "Amount"],
                    "rows": [{"Date": "2024-05-15", "Amount": "10"}],
                    "column_types": {"Date": "date", "Amount": "whole_number"},
                }],
                active_table_id="calendar-id",
            )

    def test_calculate_datesmtd_uses_visible_month_and_preserves_other_filters(self) -> None:
        calendar_start = date(2024, 5, 1)
        calendar_end = date(2024, 6, 30)
        calendar_rows = [
            {"Date": (calendar_start + timedelta(days=offset)).isoformat()}
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        selected_day = [row for row in calendar_rows if row["Date"] == "2024-06-15"]
        order_rows = [
            {"OrderDate": "2024-05-31", "Amount": "5", "Region": "East"},
            {"OrderDate": "2024-06-01", "Amount": "10", "Region": "East"},
            {"OrderDate": "2024-06-05", "Amount": "20", "Region": "East"},
            {"OrderDate": "2024-06-15", "Amount": "30", "Region": "East"},
            {"OrderDate": "2024-06-16", "Amount": "40", "Region": "East"},
            {"OrderDate": "2024-06-15", "Amount": "700", "Region": "West"},
        ]
        values = evaluate_measures(
            [{
                "name": "Sales MTD date set",
                "expression": (
                    "CALCULATE(SUM([Amount]), DATESMTD('Calendar'[Date]))"
                ),
            }],
            order_rows,
            ["OrderDate", "Amount", "Region"],
            "Orders",
            table_context=[
                {
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date"],
                    "rows": calendar_rows,
                    "filter_rows": selected_day,
                    "column_types": {"Date": "date"},
                    "date_column": "Date",
                },
                {
                    "id": "orders-id",
                    "name": "Orders",
                    "headers": ["OrderDate", "Amount", "Region"],
                    "rows": order_rows,
                    "filter_rows": [row for row in order_rows if row["Region"] == "East"],
                    "column_types": {"OrderDate": "date", "Amount": "whole_number"},
                },
            ],
            relationships=[self._relationship()],
            filter_table_ids={"calendar-id", "orders-id"},
            active_table_id="orders-id",
        )

        self.assertEqual(values["Sales MTD date set"], 60)

    def test_datesmtd_rejects_invalid_forms_and_unmarked_columns(self) -> None:
        with self.assertRaisesRegex(MeasureError, "one marked date-column reference"):
            normalize_measure(
                "Invalid DATESMTD",
                "DATESMTD('Calendar'[Date], 1)",
            )
        with self.assertRaisesRegex(MeasureError, "Table-valued functions"):
            normalize_measure(
                "Bare DATESMTD",
                "DATESMTD('Calendar'[Date])",
            )
        with self.assertRaisesRegex(MeasureError, "marked Date or DateTime"):
            evaluate_measures(
                [{
                    "name": "Sales MTD date set",
                    "expression": (
                        "CALCULATE(SUM([Amount]), DATESMTD('Calendar'[Date]))"
                    ),
                }],
                [{"Date": "2024-06-15", "Amount": "10"}],
                ["Date", "Amount"],
                "Calendar",
                table_context=[{
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date", "Amount"],
                    "rows": [{"Date": "2024-06-15", "Amount": "10"}],
                    "column_types": {"Date": "date", "Amount": "whole_number"},
                }],
                active_table_id="calendar-id",
            )

    def test_calculate_datesbetween_applies_inclusive_and_blank_bounds(self) -> None:
        calendar_start = date(2024, 1, 1)
        calendar_end = date(2024, 4, 30)
        calendar_rows = [
            {"Date": (calendar_start + timedelta(days=offset)).isoformat()}
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        selected_day = [row for row in calendar_rows if row["Date"] == "2024-04-01"]
        order_rows = [
            {"OrderDate": "2024-01-01", "Amount": "5", "Region": "East"},
            {"OrderDate": "2024-01-02", "Amount": "10", "Region": "East"},
            {"OrderDate": "2024-01-15", "Amount": "700", "Region": "West"},
            {"OrderDate": "2024-01-31", "Amount": "20", "Region": "East"},
            {"OrderDate": "2024-02-01", "Amount": "30", "Region": "East"},
        ]
        values = evaluate_measures(
            [
                {
                    "name": "Bounded sales",
                    "expression": (
                        'CALCULATE(SUM([Amount]), DATESBETWEEN('
                        "'Calendar'[Date], \"2024-01-02\", \"2024-01-31\"))"
                    ),
                },
                {
                    "name": "Sales from earliest date",
                    "expression": (
                        'CALCULATE(SUM([Amount]), DATESBETWEEN('
                        "'Calendar'[Date], BLANK(), \"2024-01-02\"))"
                    ),
                },
            ],
            order_rows,
            ["OrderDate", "Amount", "Region"],
            "Orders",
            table_context=[
                {
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date"],
                    "rows": calendar_rows,
                    "filter_rows": selected_day,
                    "column_types": {"Date": "date"},
                    "date_column": "Date",
                },
                {
                    "id": "orders-id",
                    "name": "Orders",
                    "headers": ["OrderDate", "Amount", "Region"],
                    "rows": order_rows,
                    "filter_rows": [row for row in order_rows if row["Region"] == "East"],
                    "column_types": {"OrderDate": "date", "Amount": "whole_number"},
                },
            ],
            relationships=[self._relationship()],
            filter_table_ids={"calendar-id", "orders-id"},
            active_table_id="orders-id",
        )

        self.assertEqual(values["Bounded sales"], 30)
        self.assertEqual(values["Sales from earliest date"], 15)

    def test_datesbetween_rejects_invalid_forms_and_unmarked_columns(self) -> None:
        with self.assertRaisesRegex(MeasureError, "DATESBETWEEN needs"):
            normalize_measure(
                "Invalid DATESBETWEEN arity",
                "DATESBETWEEN('Calendar'[Date], \"2024-01-01\")",
            )
        with self.assertRaisesRegex(MeasureError, "ISO dates"):
            normalize_measure(
                "Invalid DATESBETWEEN bound",
                'CALCULATE(SUM([Amount]), DATESBETWEEN(\'Calendar\'[Date], "1/1/2024", "2024-01-31"))',
            )
        with self.assertRaisesRegex(MeasureError, "Table-valued functions"):
            normalize_measure(
                "Bare DATESBETWEEN",
                'DATESBETWEEN(\'Calendar\'[Date], "2024-01-01", "2024-01-31")',
            )
        with self.assertRaisesRegex(MeasureError, "marked Date or DateTime"):
            evaluate_measures(
                [{
                    "name": "Bounded sales",
                    "expression": (
                        'CALCULATE(SUM([Amount]), DATESBETWEEN('
                        "'Calendar'[Date], \"2024-01-01\", \"2024-01-31\"))"
                    ),
                }],
                [{"Date": "2024-01-15", "Amount": "10"}],
                ["Date", "Amount"],
                "Calendar",
                table_context=[{
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date", "Amount"],
                    "rows": [{"Date": "2024-01-15", "Amount": "10"}],
                    "column_types": {"Date": "date", "Amount": "whole_number"},
                }],
                active_table_id="calendar-id",
            )

    def test_calculate_datesinperiod_uses_shifted_exclusive_boundary(self) -> None:
        calendar_start = date(2019, 6, 30)
        calendar_end = date(2021, 12, 31)
        calendar_rows = [
            {"Date": (calendar_start + timedelta(days=offset)).isoformat()}
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        selected_day = [row for row in calendar_rows if row["Date"] == "2021-06-30"]
        order_rows = [
            {"OrderDate": "2019-06-30", "Amount": "5", "Region": "East"},
            {"OrderDate": "2019-07-01", "Amount": "10", "Region": "East"},
            {"OrderDate": "2019-12-31", "Amount": "20", "Region": "East"},
            {"OrderDate": "2020-06-29", "Amount": "30", "Region": "East"},
            {"OrderDate": "2020-06-30", "Amount": "40", "Region": "East"},
            {"OrderDate": "2020-07-01", "Amount": "50", "Region": "East"},
            {"OrderDate": "2021-01-31", "Amount": "11", "Region": "East"},
            {"OrderDate": "2021-02-01", "Amount": "12", "Region": "East"},
            {"OrderDate": "2021-02-27", "Amount": "13", "Region": "East"},
            {"OrderDate": "2021-02-28", "Amount": "14", "Region": "East"},
            {"OrderDate": "2019-12-31", "Amount": "700", "Region": "West"},
        ]
        values = evaluate_measures(
            [
                {
                    "name": "Prior year sales",
                    "expression": (
                        'CALCULATE(SUM([Amount]), DATESINPERIOD('
                        "'Calendar'[Date], \"2020-06-30\", -1, YEAR))"
                    ),
                },
                {
                    "name": "Forward month sales",
                    "expression": (
                        'CALCULATE(SUM([Amount]), DATESINPERIOD('
                        "'Calendar'[Date], \"2021-01-31\", 1, MONTH))"
                    ),
                },
            ],
            order_rows,
            ["OrderDate", "Amount", "Region"],
            "Orders",
            table_context=[
                {
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date"],
                    "rows": calendar_rows,
                    "filter_rows": selected_day,
                    "column_types": {"Date": "date"},
                    "date_column": "Date",
                },
                {
                    "id": "orders-id",
                    "name": "Orders",
                    "headers": ["OrderDate", "Amount", "Region"],
                    "rows": order_rows,
                    "filter_rows": [row for row in order_rows if row["Region"] == "East"],
                    "column_types": {"OrderDate": "date", "Amount": "whole_number"},
                },
            ],
            relationships=[self._relationship()],
            filter_table_ids={"calendar-id", "orders-id"},
            active_table_id="orders-id",
        )

        self.assertEqual(values["Prior year sales"], 100)
        self.assertEqual(values["Forward month sales"], 36)

    def test_datesinperiod_rejects_invalid_forms_and_unmarked_columns(self) -> None:
        with self.assertRaisesRegex(MeasureError, "DATESINPERIOD needs"):
            normalize_measure(
                "Invalid DATESINPERIOD arity",
                'DATESINPERIOD(\'Calendar\'[Date], "2024-01-01", -1)',
            )
        with self.assertRaisesRegex(MeasureError, "ISO dates"):
            normalize_measure(
                "Invalid DATESINPERIOD start date",
                'CALCULATE(SUM([Amount]), DATESINPERIOD(\'Calendar\'[Date], "1/1/2024", -1, DAY))',
            )
        with self.assertRaisesRegex(MeasureError, "DATESINPERIOD needs"):
            normalize_measure(
                "Unsupported DATESINPERIOD interval",
                'DATESINPERIOD(\'Calendar\'[Date], "2024-01-01", -1, WEEK)',
            )
        with self.assertRaisesRegex(MeasureError, "Table-valued functions"):
            normalize_measure(
                "Bare DATESINPERIOD",
                'DATESINPERIOD(\'Calendar\'[Date], "2024-01-01", -1, DAY)',
            )
        with self.assertRaisesRegex(MeasureError, "whole number"):
            evaluate_measures(
                [{
                    "name": "Invalid period",
                    "expression": (
                        'CALCULATE(SUM([Amount]), DATESINPERIOD('
                        "'Calendar'[Date], \"2024-01-01\", 1.5, DAY))"
                    ),
                }],
                [{"Date": "2024-01-01", "Amount": "10"}],
                ["Date", "Amount"],
                "Calendar",
                table_context=[{
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date", "Amount"],
                    "rows": [{"Date": "2024-01-01", "Amount": "10"}],
                    "column_types": {"Date": "date", "Amount": "whole_number"},
                    "date_column": "Date",
                }],
                active_table_id="calendar-id",
            )
        with self.assertRaisesRegex(MeasureError, "marked Date or DateTime"):
            evaluate_measures(
                [{
                    "name": "Prior year sales",
                    "expression": (
                        'CALCULATE(SUM([Amount]), DATESINPERIOD('
                        "'Calendar'[Date], \"2024-01-01\", -1, DAY))"
                    ),
                }],
                [{"Date": "2024-01-01", "Amount": "10"}],
                ["Date", "Amount"],
                "Calendar",
                table_context=[{
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date", "Amount"],
                    "rows": [{"Date": "2024-01-01", "Amount": "10"}],
                    "column_types": {"Date": "date", "Amount": "whole_number"},
                }],
                active_table_id="calendar-id",
            )

    def test_calculate_previousyear_uses_first_visible_date_and_full_prior_year(self) -> None:
        calendar_start = date(2022, 1, 1)
        calendar_end = date(2025, 12, 31)
        calendar_rows = [
            {"Date": (calendar_start + timedelta(days=offset)).isoformat()}
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        selected_days = {
            "2024-04-30",
            "2025-01-01",
        }
        selected_rows = [row for row in calendar_rows if row["Date"] in selected_days]
        order_rows = [
            {"OrderDate": "2022-06-30", "Amount": "5", "Region": "East"},
            {"OrderDate": "2022-07-01", "Amount": "11", "Region": "East"},
            {"OrderDate": "2023-06-30", "Amount": "13", "Region": "East"},
            {"OrderDate": "2023-07-01", "Amount": "17", "Region": "East"},
            {"OrderDate": "2023-12-31", "Amount": "19", "Region": "East"},
            {"OrderDate": "2024-04-30", "Amount": "23", "Region": "East"},
            {"OrderDate": "2025-01-01", "Amount": "27", "Region": "East"},
            {"OrderDate": "2023-06-30", "Amount": "700", "Region": "West"},
        ]
        values = evaluate_measures(
            [
                {
                    "name": "Prior calendar year sales",
                    "expression": (
                        "CALCULATE(SUM([Amount]), "
                        "PREVIOUSYEAR('Calendar'[Date]))"
                    ),
                },
                {
                    "name": "Prior fiscal year sales",
                    "expression": (
                        'CALCULATE(SUM([Amount]), PREVIOUSYEAR('
                        "'Calendar'[Date], \"6/30\"))"
                    ),
                },
            ],
            order_rows,
            ["OrderDate", "Amount", "Region"],
            "Orders",
            table_context=[
                {
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date"],
                    "rows": calendar_rows,
                    "filter_rows": selected_rows,
                    "column_types": {"Date": "date"},
                    "date_column": "Date",
                },
                {
                    "id": "orders-id",
                    "name": "Orders",
                    "headers": ["OrderDate", "Amount", "Region"],
                    "rows": order_rows,
                    "filter_rows": [row for row in order_rows if row["Region"] == "East"],
                    "column_types": {"OrderDate": "date", "Amount": "whole_number"},
                },
            ],
            relationships=[self._relationship()],
            filter_table_ids={"calendar-id", "orders-id"},
            active_table_id="orders-id",
        )

        self.assertEqual(values["Prior calendar year sales"], 49)
        self.assertEqual(values["Prior fiscal year sales"], 24)

    def test_previousyear_rejects_invalid_forms_and_unmarked_columns(self) -> None:
        with self.assertRaisesRegex(MeasureError, "marked date-column reference"):
            normalize_measure(
                "Invalid PREVIOUSYEAR arity",
                "PREVIOUSYEAR('Calendar'[Date], \"6/30\", 1)",
            )
        with self.assertRaisesRegex(MeasureError, "valid month/day"):
            normalize_measure(
                "Invalid PREVIOUSYEAR year end",
                "CALCULATE(SUM([Amount]), PREVIOUSYEAR('Calendar'[Date], \"6/31\"))",
            )
        with self.assertRaisesRegex(MeasureError, "Table-valued functions"):
            normalize_measure(
                "Bare PREVIOUSYEAR",
                "PREVIOUSYEAR('Calendar'[Date])",
            )
        with self.assertRaisesRegex(MeasureError, "marked Date or DateTime"):
            evaluate_measures(
                [{
                    "name": "Prior year sales",
                    "expression": (
                        "CALCULATE(SUM([Amount]), "
                        "PREVIOUSYEAR('Calendar'[Date]))"
                    ),
                }],
                [{"Date": "2024-01-01", "Amount": "10"}],
                ["Date", "Amount"],
                "Calendar",
                table_context=[{
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date", "Amount"],
                    "rows": [{"Date": "2024-01-01", "Amount": "10"}],
                    "column_types": {"Date": "date", "Amount": "whole_number"},
                }],
                active_table_id="calendar-id",
            )

    def test_calculate_previousquarter_uses_first_visible_date_and_full_prior_quarter(self) -> None:
        calendar_start = date(2023, 1, 1)
        calendar_end = date(2024, 12, 31)
        calendar_rows = [
            {"Date": (calendar_start + timedelta(days=offset)).isoformat()}
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        selected_days = {
            "2024-02-15",
            "2024-04-15",
        }
        selected_rows = [row for row in calendar_rows if row["Date"] in selected_days]
        order_rows = [
            {"OrderDate": "2023-09-30", "Amount": "5", "Region": "East"},
            {"OrderDate": "2023-10-01", "Amount": "10", "Region": "East"},
            {"OrderDate": "2023-12-31", "Amount": "20", "Region": "East"},
            {"OrderDate": "2024-01-01", "Amount": "30", "Region": "East"},
            {"OrderDate": "2024-03-31", "Amount": "35", "Region": "East"},
            {"OrderDate": "2024-02-15", "Amount": "40", "Region": "East"},
            {"OrderDate": "2024-04-15", "Amount": "45", "Region": "East"},
            {"OrderDate": "2023-12-31", "Amount": "700", "Region": "West"},
        ]
        values = evaluate_measures(
            [{
                "name": "Prior quarter sales",
                "expression": (
                    "CALCULATE(SUM([Amount]), "
                    "PREVIOUSQUARTER('Calendar'[Date]))"
                ),
            }],
            order_rows,
            ["OrderDate", "Amount", "Region"],
            "Orders",
            table_context=[
                {
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date"],
                    "rows": calendar_rows,
                    "filter_rows": selected_rows,
                    "column_types": {"Date": "date"},
                    "date_column": "Date",
                },
                {
                    "id": "orders-id",
                    "name": "Orders",
                    "headers": ["OrderDate", "Amount", "Region"],
                    "rows": order_rows,
                    "filter_rows": [row for row in order_rows if row["Region"] == "East"],
                    "column_types": {"OrderDate": "date", "Amount": "whole_number"},
                },
            ],
            relationships=[self._relationship()],
            filter_table_ids={"calendar-id", "orders-id"},
            active_table_id="orders-id",
        )

        self.assertEqual(values["Prior quarter sales"], 30)

    def test_previousquarter_rejects_invalid_forms_and_unmarked_columns(self) -> None:
        with self.assertRaisesRegex(MeasureError, "one marked date-column reference"):
            normalize_measure(
                "Invalid PREVIOUSQUARTER arity",
                "PREVIOUSQUARTER('Calendar'[Date], 1)",
            )
        with self.assertRaisesRegex(MeasureError, "Table-valued functions"):
            normalize_measure(
                "Bare PREVIOUSQUARTER",
                "PREVIOUSQUARTER('Calendar'[Date])",
            )
        with self.assertRaisesRegex(MeasureError, "marked Date or DateTime"):
            evaluate_measures(
                [{
                    "name": "Prior quarter sales",
                    "expression": (
                        "CALCULATE(SUM([Amount]), "
                        "PREVIOUSQUARTER('Calendar'[Date]))"
                    ),
                }],
                [{"Date": "2024-02-15", "Amount": "10"}],
                ["Date", "Amount"],
                "Calendar",
                table_context=[{
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date", "Amount"],
                    "rows": [{"Date": "2024-02-15", "Amount": "10"}],
                    "column_types": {"Date": "date", "Amount": "whole_number"},
                }],
                active_table_id="calendar-id",
            )

    def test_calculate_previousmonth_uses_first_visible_date_and_full_prior_month(self) -> None:
        calendar_start = date(2023, 9, 1)
        calendar_end = date(2024, 5, 31)
        calendar_rows = [
            {"Date": (calendar_start + timedelta(days=offset)).isoformat()}
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        selected_days = {"2024-02-15", "2024-04-15"}
        selected_rows = [row for row in calendar_rows if row["Date"] in selected_days]
        order_rows = [
            {"OrderDate": "2023-12-31", "Amount": "5", "Region": "East"},
            {"OrderDate": "2024-01-01", "Amount": "10", "Region": "East"},
            {"OrderDate": "2024-01-31", "Amount": "20", "Region": "East"},
            {"OrderDate": "2024-02-01", "Amount": "30", "Region": "East"},
            {"OrderDate": "2024-02-15", "Amount": "40", "Region": "East"},
            {"OrderDate": "2024-04-15", "Amount": "45", "Region": "East"},
            {"OrderDate": "2024-01-15", "Amount": "700", "Region": "West"},
        ]

        values = evaluate_measures(
            [{
                "name": "Prior month sales",
                "expression": (
                    "CALCULATE(SUM([Amount]), "
                    "PREVIOUSMONTH('Calendar'[Date]))"
                ),
            }],
            order_rows,
            ["OrderDate", "Amount", "Region"],
            "Orders",
            table_context=[
                {
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date"],
                    "rows": calendar_rows,
                    "filter_rows": selected_rows,
                    "column_types": {"Date": "date"},
                    "date_column": "Date",
                },
                {
                    "id": "orders-id",
                    "name": "Orders",
                    "headers": ["OrderDate", "Amount", "Region"],
                    "rows": order_rows,
                    "filter_rows": [row for row in order_rows if row["Region"] == "East"],
                    "column_types": {"OrderDate": "date", "Amount": "whole_number"},
                },
            ],
            relationships=[self._relationship()],
            filter_table_ids={"calendar-id", "orders-id"},
            active_table_id="orders-id",
        )

        self.assertEqual(values["Prior month sales"], 30)

    def test_previousmonth_crosses_calendar_year_boundary(self) -> None:
        calendar_start = date(2023, 11, 1)
        calendar_end = date(2024, 1, 31)
        calendar_rows = [
            {"Date": (calendar_start + timedelta(days=offset)).isoformat()}
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        selected_rows = [row for row in calendar_rows if row["Date"] == "2024-01-15"]
        order_rows = [
            {"OrderDate": "2023-12-01", "Amount": "10"},
            {"OrderDate": "2023-12-31", "Amount": "20"},
            {"OrderDate": "2024-01-01", "Amount": "100"},
        ]

        values = evaluate_measures(
            [{
                "name": "Prior month sales",
                "expression": (
                    "CALCULATE(SUM([Amount]), "
                    "PREVIOUSMONTH('Calendar'[Date]))"
                ),
            }],
            order_rows,
            ["OrderDate", "Amount"],
            "Orders",
            table_context=[
                {
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date"],
                    "rows": calendar_rows,
                    "filter_rows": selected_rows,
                    "column_types": {"Date": "date"},
                    "date_column": "Date",
                },
                {
                    "id": "orders-id",
                    "name": "Orders",
                    "headers": ["OrderDate", "Amount"],
                    "rows": order_rows,
                    "column_types": {"OrderDate": "date", "Amount": "whole_number"},
                },
            ],
            relationships=[self._relationship()],
            filter_table_ids={"calendar-id", "orders-id"},
            active_table_id="orders-id",
        )

        self.assertEqual(values["Prior month sales"], 30)

    def test_previousmonth_rejects_invalid_forms_and_unmarked_columns(self) -> None:
        with self.assertRaisesRegex(MeasureError, "one marked date-column reference"):
            normalize_measure(
                "Invalid PREVIOUSMONTH arity",
                "PREVIOUSMONTH('Calendar'[Date], 1)",
            )
        with self.assertRaisesRegex(MeasureError, "Table-valued functions"):
            normalize_measure(
                "Bare PREVIOUSMONTH",
                "PREVIOUSMONTH('Calendar'[Date])",
            )
        with self.assertRaisesRegex(MeasureError, "marked Date or DateTime"):
            evaluate_measures(
                [{
                    "name": "Prior month sales",
                    "expression": (
                        "CALCULATE(SUM([Amount]), "
                        "PREVIOUSMONTH('Calendar'[Date]))"
                    ),
                }],
                [{"Date": "2024-02-15", "Amount": "10"}],
                ["Date", "Amount"],
                "Calendar",
                table_context=[{
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date", "Amount"],
                    "rows": [{"Date": "2024-02-15", "Amount": "10"}],
                    "column_types": {"Date": "date", "Amount": "whole_number"},
                }],
                active_table_id="calendar-id",
            )

    def test_dateadd_rejects_noncontiguous_dates_and_invalid_arguments(self) -> None:
        with self.assertRaisesRegex(MeasureError, "contiguous"):
            evaluate_measures(
                [{
                    "name": "Previous day sales",
                    "expression": (
                        "CALCULATE(SUM([Amount]), "
                        "DATEADD('Calendar'[Date], -1, DAY))"
                    ),
                }],
                [{"Date": "2024-01-01", "Amount": "10"}],
                ["Date", "Amount"],
                "Calendar",
                table_context=[{
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date", "Amount"],
                    "rows": [
                        {"Date": "2024-01-01", "Amount": "10"},
                        {"Date": "2024-01-02", "Amount": "20"},
                        {"Date": "2024-01-03", "Amount": "30"},
                    ],
                    "filter_rows": [
                        {"Date": "2024-01-01", "Amount": "10"},
                        {"Date": "2024-01-03", "Amount": "30"},
                    ],
                    "column_types": {"Date": "date", "Amount": "whole_number"},
                    "date_column": "Date",
                }],
                filter_table_ids={"calendar-id"},
                active_table_id="calendar-id",
            )

        with self.assertRaisesRegex(MeasureError, "Table-valued functions"):
            normalize_measure(
                "Bare DATEADD",
                "DATEADD('Calendar'[Date], -1, YEAR)",
            )
        with self.assertRaisesRegex(MeasureError, "YEAR, QUARTER, MONTH, or DAY"):
            normalize_measure(
                "Week DATEADD",
                "CALCULATE(SUM([Amount]), DATEADD('Calendar'[Date], -1, WEEK))",
            )
        with self.assertRaisesRegex(MeasureError, "whole number"):
            evaluate_measures(
                [{
                    "name": "Fractional shift",
                    "expression": (
                        "CALCULATE(SUM([Amount]), "
                        "DATEADD('Calendar'[Date], 0.5, DAY))"
                    ),
                }],
                [{"Date": "2024-01-01", "Amount": "10"}],
                ["Date", "Amount"],
                "Calendar",
                table_context=[{
                    "id": "calendar-id",
                    "name": "Calendar",
                    "headers": ["Date", "Amount"],
                    "rows": [{"Date": "2024-01-01", "Amount": "10"}],
                    "column_types": {"Date": "date", "Amount": "whole_number"},
                    "date_column": "Date",
                }],
                active_table_id="calendar-id",
            )

    def controller(self, settings_name: str) -> StudioController:
        settings = QSettings(
            str(self.root / settings_name), QSettings.Format.IniFormat
        )
        return StudioController(self.app, settings)

    def mark_calendar(self, controller: StudioController) -> None:
        tables = [
            dict(table) for table in controller.tableCatalog
            if table.get("loaded") and table.get("loadEnabled")
        ]
        candidates = {
            str(table["sourceId"]): controller._loaded_candidates[str(table["sourceId"])]
            for table in tables
        }
        dialog = DateTableDialog(tables, candidates)
        dialog.column_combo.setCurrentText("Date")

        def accept_dialog() -> QDialog.DialogCode:
            dialog._accept_mark()
            return dialog.result()

        with (
            patch("analytics_studio.controller.DateTableDialog", return_value=dialog),
            patch.object(dialog, "exec", side_effect=accept_dialog),
        ):
            self.assertTrue(controller.mark_date_table_dialog(), controller.statusMessage)
        dialog.deleteLater()

    def add_date_relationship(
        self,
        controller: StudioController,
        calendar_id: str,
        orders_id: str,
    ) -> None:
        dialog = RelationshipDialog(
            controller._table_catalog,
            controller._project["model"].get("relationships", []),
            lambda items: controller._validate_relationship_candidate(items),
        )
        dialog.from_table.setCurrentIndex(dialog.from_table.findData(calendar_id))
        dialog.from_column.setCurrentIndex(dialog.from_column.findData("Date"))
        dialog.to_table.setCurrentIndex(dialog.to_table.findData(orders_id))
        dialog.to_column.setCurrentIndex(dialog.to_column.findData("OrderDate"))
        dialog.cardinality.setCurrentIndex(
            dialog.cardinality.findData("one_to_many")
        )
        dialog.cross_filter.setCurrentIndex(dialog.cross_filter.findData("single"))
        dialog.active_check.setChecked(True)
        dialog._apply_form()

        def save_and_return() -> QDialog.DialogCode:
            dialog._save()
            return dialog.result()

        with (
            patch("analytics_studio.controller.RelationshipDialog", return_value=dialog),
            patch.object(dialog, "exec", side_effect=save_and_return),
        ):
            self.assertTrue(controller.manage_relationships(), controller.statusMessage)
        dialog.deleteLater()

    def test_totalytd_measure_survives_reopen_and_recomputes_from_sources(self) -> None:
        calendar_path = self.root / "Calendar.csv"
        calendar_start = date(2023, 7, 1)
        calendar_end = date(2024, 5, 4)
        calendar_lines = ["Date"] + [
            (calendar_start + timedelta(days=offset)).isoformat()
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        calendar_path.write_text("\n".join(calendar_lines) + "\n", encoding="utf-8")
        orders_path = self.root / "Orders.csv"
        orders_path.write_text(
            "OrderDate,Amount\n"
            "2023-12-31,5\n"
            "2024-01-05,10\n"
            "2024-02-02,20\n"
            "2024-03-30,30\n"
            "2024-04-02,40\n",
            encoding="utf-8",
        )

        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(calendar_path, parse_file(calendar_path)))
        calendar_id = str(controller.activeTableId)
        self.assertTrue(controller.setColumnType("Date", "date"), controller.statusMessage)
        self.mark_calendar(controller)

        calendar_table = controller._model_table_for_source(
            controller._project, calendar_id
        )
        assert calendar_table is not None
        calendar_name = str(calendar_table["name"])

        self.assertTrue(controller._commit_import(orders_path, parse_file(orders_path)))
        orders_id = str(controller.activeTableId)
        self.assertTrue(controller.setColumnType("OrderDate", "date"), controller.statusMessage)
        self.assertTrue(controller.setColumnType("Amount", "whole_number"), controller.statusMessage)
        self.add_date_relationship(controller, calendar_id, orders_id)

        expression = f"TOTALYTD(SUM([Amount]), '{calendar_name}'[Date])"
        self.assertTrue(
            controller.create_measure("Sales YTD", expression), controller.statusMessage
        )
        fiscal_expression = (
            f'TOTALYTD(SUM([Amount]), \'{calendar_name}\'[Date],, "6/30")'
        )
        self.assertTrue(
            controller.create_measure("Fiscal YTD", fiscal_expression),
            controller.statusMessage,
        )
        self.assertEqual(controller.reportKpis["Sales YTD"], "100")
        self.assertEqual(controller.reportKpis["Fiscal YTD"], "105")

        project_path = self.root / "totalytd.npa"
        self.assertTrue(controller._save_to(project_path))
        orders_path.write_text(
            "OrderDate,Amount\n"
            "2023-12-31,5\n"
            "2024-01-05,12\n"
            "2024-02-02,20\n"
            "2024-03-30,30\n"
            "2024-04-02,40\n"
            "2024-05-04,50\n",
            encoding="utf-8",
        )

        reopened = self.controller("reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Sales YTD"], "152")
        self.assertEqual(reopened.reportKpis["Fiscal YTD"], "157")
        self.assertEqual(reopened._project["model"]["tables"][0]["date_column"], "Date")

    def test_totalqtd_measure_survives_reopen_and_recomputes_from_sources(self) -> None:
        calendar_path = self.root / "Calendar QTD.csv"
        calendar_start = date(2024, 1, 1)
        calendar_end = date(2024, 5, 4)
        calendar_lines = ["Date"] + [
            (calendar_start + timedelta(days=offset)).isoformat()
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        calendar_path.write_text("\n".join(calendar_lines) + "\n", encoding="utf-8")
        orders_path = self.root / "Orders QTD.csv"
        orders_path.write_text(
            "OrderDate,Amount\n"
            "2024-01-05,10\n"
            "2024-02-02,20\n"
            "2024-03-30,30\n"
            "2024-04-02,40\n"
            "2024-05-04,50\n",
            encoding="utf-8",
        )

        controller = self.controller("qtd-settings.ini")
        self.assertTrue(controller._commit_import(calendar_path, parse_file(calendar_path)))
        calendar_id = str(controller.activeTableId)
        self.assertTrue(controller.setColumnType("Date", "date"), controller.statusMessage)
        self.mark_calendar(controller)
        calendar_table = controller._model_table_for_source(controller._project, calendar_id)
        assert calendar_table is not None
        calendar_name = str(calendar_table["name"])

        self.assertTrue(controller._commit_import(orders_path, parse_file(orders_path)))
        orders_id = str(controller.activeTableId)
        self.assertTrue(controller.setColumnType("OrderDate", "date"), controller.statusMessage)
        self.assertTrue(controller.setColumnType("Amount", "whole_number"), controller.statusMessage)
        self.add_date_relationship(controller, calendar_id, orders_id)
        self.assertTrue(
            controller.create_measure(
                "Sales QTD",
                f"TOTALQTD(SUM([Amount]), '{calendar_name}'[Date])",
            ),
            controller.statusMessage,
        )
        self.assertTrue(
            controller.create_measure(
                "Sales QTD dates",
                (
                    "CALCULATE(SUM([Amount]), "
                    f"DATESQTD('{calendar_name}'[Date]))"
                ),
            ),
            controller.statusMessage,
        )
        self.assertEqual(controller.reportKpis["Sales QTD"], "90")
        self.assertEqual(controller.reportKpis["Sales QTD dates"], "90")

        project_path = self.root / "totalqtd.npa"
        self.assertTrue(controller._save_to(project_path))
        orders_path.write_text(
            "OrderDate,Amount\n"
            "2024-01-05,10\n"
            "2024-02-02,20\n"
            "2024-03-30,30\n"
            "2024-04-02,42\n"
            "2024-05-04,55\n",
            encoding="utf-8",
        )

        reopened = self.controller("qtd-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Sales QTD"], "97")
        self.assertEqual(reopened.reportKpis["Sales QTD dates"], "97")

    def test_totalmtd_measure_survives_reopen_and_recomputes_from_sources(self) -> None:
        calendar_path = self.root / "Calendar MTD.csv"
        calendar_start = date(2024, 5, 1)
        calendar_end = date(2024, 6, 15)
        calendar_lines = ["Date"] + [
            (calendar_start + timedelta(days=offset)).isoformat()
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        calendar_path.write_text("\n".join(calendar_lines) + "\n", encoding="utf-8")
        orders_path = self.root / "Orders MTD.csv"
        orders_path.write_text(
            "OrderDate,Amount\n"
            "2024-05-31,5\n"
            "2024-06-01,10\n"
            "2024-06-05,20\n"
            "2024-06-15,30\n",
            encoding="utf-8",
        )

        controller = self.controller("mtd-settings.ini")
        self.assertTrue(controller._commit_import(calendar_path, parse_file(calendar_path)))
        calendar_id = str(controller.activeTableId)
        self.assertTrue(controller.setColumnType("Date", "date"), controller.statusMessage)
        self.mark_calendar(controller)
        calendar_table = controller._model_table_for_source(controller._project, calendar_id)
        assert calendar_table is not None
        calendar_name = str(calendar_table["name"])

        self.assertTrue(controller._commit_import(orders_path, parse_file(orders_path)))
        orders_id = str(controller.activeTableId)
        self.assertTrue(controller.setColumnType("OrderDate", "date"), controller.statusMessage)
        self.assertTrue(controller.setColumnType("Amount", "whole_number"), controller.statusMessage)
        self.add_date_relationship(controller, calendar_id, orders_id)
        self.assertTrue(
            controller.create_measure(
                "Sales MTD",
                f"TOTALMTD(SUM([Amount]), '{calendar_name}'[Date])",
            ),
            controller.statusMessage,
        )
        self.assertTrue(
            controller.create_measure(
                "Sales MTD dates",
                (
                    "CALCULATE(SUM([Amount]), "
                    f"DATESMTD('{calendar_name}'[Date]))"
                ),
            ),
            controller.statusMessage,
        )
        self.assertEqual(controller.reportKpis["Sales MTD"], "60")
        self.assertEqual(controller.reportKpis["Sales MTD dates"], "60")

        project_path = self.root / "totalmtd.npa"
        self.assertTrue(controller._save_to(project_path))
        orders_path.write_text(
            "OrderDate,Amount\n"
            "2024-05-31,5\n"
            "2024-06-01,11\n"
            "2024-06-05,22\n"
            "2024-06-15,33\n",
            encoding="utf-8",
        )

        reopened = self.controller("mtd-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Sales MTD"], "66")
        self.assertEqual(reopened.reportKpis["Sales MTD dates"], "66")

    def test_dateadd_measure_survives_reopen_and_recomputes_from_sources(self) -> None:
        calendar_path = self.root / "Calendar DATEADD.csv"
        calendar_start = date(2024, 1, 1)
        calendar_end = date(2024, 2, 29)
        calendar_lines = ["Date"] + [
            (calendar_start + timedelta(days=offset)).isoformat()
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        calendar_path.write_text("\n".join(calendar_lines) + "\n", encoding="utf-8")
        orders_path = self.root / "Orders DATEADD.csv"
        orders_path.write_text(
            "OrderDate,Amount\n"
            "2024-01-01,10\n"
            "2024-01-15,20\n"
            "2024-01-31,30\n",
            encoding="utf-8",
        )

        controller = self.controller("dateadd-settings.ini")
        self.assertTrue(controller._commit_import(calendar_path, parse_file(calendar_path)))
        calendar_id = str(controller.activeTableId)
        self.assertTrue(controller.setColumnType("Date", "date"), controller.statusMessage)
        self.mark_calendar(controller)
        calendar_table = controller._model_table_for_source(controller._project, calendar_id)
        assert calendar_table is not None
        calendar_name = str(calendar_table["name"])

        self.assertTrue(controller._commit_import(orders_path, parse_file(orders_path)))
        orders_id = str(controller.activeTableId)
        self.assertTrue(controller.setColumnType("OrderDate", "date"), controller.statusMessage)
        self.assertTrue(controller.setColumnType("Amount", "whole_number"), controller.statusMessage)
        self.add_date_relationship(controller, calendar_id, orders_id)
        self.assertTrue(
            controller.create_measure(
                "Previous month sales",
                (
                    "CALCULATE(SUM([Amount]), "
                    f"DATEADD('{calendar_name}'[Date], -1, MONTH))"
                ),
            ),
            controller.statusMessage,
        )
        self.assertEqual(controller.reportKpis["Previous month sales"], "60")

        project_path = self.root / "dateadd.npa"
        self.assertTrue(controller._save_to(project_path))
        orders_path.write_text(
            "OrderDate,Amount\n"
            "2024-01-01,11\n"
            "2024-01-15,22\n"
            "2024-01-31,33\n",
            encoding="utf-8",
        )

        reopened = self.controller("dateadd-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Previous month sales"], "66")

    def test_sameperiodlastyear_measure_survives_reopen_and_recomputes_from_sources(self) -> None:
        calendar_path = self.root / "Calendar SPLY.csv"
        calendar_start = date(2023, 1, 1)
        calendar_end = date(2024, 12, 31)
        calendar_lines = ["Date"] + [
            (calendar_start + timedelta(days=offset)).isoformat()
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        calendar_path.write_text("\n".join(calendar_lines) + "\n", encoding="utf-8")
        orders_path = self.root / "Orders SPLY.csv"
        orders_path.write_text(
            "OrderDate,Amount\n"
            "2023-02-27,10\n"
            "2023-02-28,20\n"
            "2023-03-01,30\n"
            "2024-03-01,500\n",
            encoding="utf-8",
        )

        controller = self.controller("sply-settings.ini")
        self.assertTrue(controller._commit_import(calendar_path, parse_file(calendar_path)))
        calendar_id = str(controller.activeTableId)
        self.assertTrue(controller.setColumnType("Date", "date"), controller.statusMessage)
        self.mark_calendar(controller)
        calendar_table = controller._model_table_for_source(controller._project, calendar_id)
        assert calendar_table is not None
        calendar_name = str(calendar_table["name"])

        self.assertTrue(controller._commit_import(orders_path, parse_file(orders_path)))
        orders_id = str(controller.activeTableId)
        self.assertTrue(controller.setColumnType("OrderDate", "date"), controller.statusMessage)
        self.assertTrue(controller.setColumnType("Amount", "whole_number"), controller.statusMessage)
        self.add_date_relationship(controller, calendar_id, orders_id)
        self.assertTrue(
            controller.create_measure(
                "Prior year sales",
                (
                    "CALCULATE(SUM([Amount]), "
                    f"SAMEPERIODLASTYEAR('{calendar_name}'[Date]))"
                ),
            ),
            controller.statusMessage,
        )
        self.assertEqual(controller.reportKpis["Prior year sales"], "60")

        project_path = self.root / "sameperiodlastyear.npa"
        self.assertTrue(controller._save_to(project_path))
        orders_path.write_text(
            "OrderDate,Amount\n"
            "2023-02-27,11\n"
            "2023-02-28,22\n"
            "2023-03-01,33\n"
            "2024-03-01,500\n",
            encoding="utf-8",
        )

        reopened = self.controller("sply-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Prior year sales"], "66")

    def test_datesytd_measures_survive_reopen_and_recompute_from_sources(self) -> None:
        calendar_path = self.root / "Calendar DATESYTD.csv"
        calendar_start = date(2023, 1, 1)
        calendar_end = date(2024, 4, 30)
        calendar_lines = ["Date"] + [
            (calendar_start + timedelta(days=offset)).isoformat()
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        calendar_path.write_text("\n".join(calendar_lines) + "\n", encoding="utf-8")
        orders_path = self.root / "Orders DATESYTD.csv"
        orders_path.write_text(
            "OrderDate,Amount\n"
            "2023-12-31,5\n"
            "2024-01-05,10\n"
            "2024-02-02,20\n"
            "2024-03-30,30\n"
            "2024-04-02,40\n",
            encoding="utf-8",
        )

        controller = self.controller("datesytd-settings.ini")
        self.assertTrue(controller._commit_import(calendar_path, parse_file(calendar_path)))
        calendar_id = str(controller.activeTableId)
        self.assertTrue(controller.setColumnType("Date", "date"), controller.statusMessage)
        self.mark_calendar(controller)
        calendar_table = controller._model_table_for_source(controller._project, calendar_id)
        assert calendar_table is not None
        calendar_name = str(calendar_table["name"])

        self.assertTrue(controller._commit_import(orders_path, parse_file(orders_path)))
        orders_id = str(controller.activeTableId)
        self.assertTrue(controller.setColumnType("OrderDate", "date"), controller.statusMessage)
        self.assertTrue(controller.setColumnType("Amount", "whole_number"), controller.statusMessage)
        self.add_date_relationship(controller, calendar_id, orders_id)
        self.assertTrue(
            controller.create_measure(
                "Sales YTD",
                (
                    "CALCULATE(SUM([Amount]), "
                    f"DATESYTD('{calendar_name}'[Date]))"
                ),
            ),
            controller.statusMessage,
        )
        self.assertTrue(
            controller.create_measure(
                "Sales FYTD",
                (
                    "CALCULATE(SUM([Amount]), "
                    f"DATESYTD('{calendar_name}'[Date], \"3/31\"))"
                ),
            ),
            controller.statusMessage,
        )
        self.assertEqual(controller.reportKpis["Sales YTD"], "100")
        self.assertEqual(controller.reportKpis["Sales FYTD"], "40")

        project_path = self.root / "datesytd.npa"
        self.assertTrue(controller._save_to(project_path))
        orders_path.write_text(
            "OrderDate,Amount\n"
            "2023-12-31,5\n"
            "2024-01-05,12\n"
            "2024-02-02,20\n"
            "2024-03-30,30\n"
            "2024-04-02,42\n",
            encoding="utf-8",
        )

        reopened = self.controller("datesytd-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Sales YTD"], "104")
        self.assertEqual(reopened.reportKpis["Sales FYTD"], "42")

    def test_datesbetween_measure_survives_reopen_and_recomputes_from_sources(self) -> None:
        calendar_path = self.root / "Calendar DATESBETWEEN.csv"
        calendar_start = date(2023, 12, 1)
        calendar_end = date(2024, 4, 30)
        calendar_lines = ["Date"] + [
            (calendar_start + timedelta(days=offset)).isoformat()
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        calendar_path.write_text("\n".join(calendar_lines) + "\n", encoding="utf-8")
        orders_path = self.root / "Orders DATESBETWEEN.csv"
        orders_path.write_text(
            "OrderDate,Amount\n"
            "2023-12-31,5\n"
            "2024-01-05,10\n"
            "2024-01-31,20\n"
            "2024-02-02,30\n"
            "2024-04-02,40\n",
            encoding="utf-8",
        )

        controller = self.controller("datesbetween-settings.ini")
        self.assertTrue(controller._commit_import(calendar_path, parse_file(calendar_path)))
        calendar_id = str(controller.activeTableId)
        self.assertTrue(controller.setColumnType("Date", "date"), controller.statusMessage)
        self.mark_calendar(controller)
        calendar_table = controller._model_table_for_source(controller._project, calendar_id)
        assert calendar_table is not None
        calendar_name = str(calendar_table["name"])

        self.assertTrue(controller._commit_import(orders_path, parse_file(orders_path)))
        orders_id = str(controller.activeTableId)
        self.assertTrue(controller.setColumnType("OrderDate", "date"), controller.statusMessage)
        self.assertTrue(controller.setColumnType("Amount", "whole_number"), controller.statusMessage)
        self.add_date_relationship(controller, calendar_id, orders_id)
        self.assertTrue(
            controller.create_measure(
                "Bounded sales",
                (
                    "CALCULATE(SUM([Amount]), DATESBETWEEN("
                    f"'{calendar_name}'[Date], \"2024-01-01\", \"2024-02-02\"))"
                ),
            ),
            controller.statusMessage,
        )
        self.assertEqual(controller.reportKpis["Bounded sales"], "60")

        project_path = self.root / "datesbetween.npa"
        self.assertTrue(controller._save_to(project_path))
        orders_path.write_text(
            "OrderDate,Amount\n"
            "2023-12-31,5\n"
            "2024-01-05,11\n"
            "2024-01-31,22\n"
            "2024-02-02,33\n"
            "2024-04-02,40\n",
            encoding="utf-8",
        )

        reopened = self.controller("datesbetween-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Bounded sales"], "66")

    def test_datesinperiod_measure_survives_reopen_and_recomputes_from_sources(self) -> None:
        calendar_path = self.root / "Calendar DATESINPERIOD.csv"
        calendar_start = date(2019, 1, 1)
        calendar_end = date(2021, 12, 31)
        calendar_lines = ["Date"] + [
            (calendar_start + timedelta(days=offset)).isoformat()
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        calendar_path.write_text("\n".join(calendar_lines) + "\n", encoding="utf-8")
        orders_path = self.root / "Orders DATESINPERIOD.csv"
        orders_path.write_text(
            "OrderDate,Amount\n"
            "2019-06-30,5\n"
            "2019-07-01,10\n"
            "2019-12-31,20\n"
            "2020-06-30,30\n"
            "2020-07-01,40\n"
            "2021-06-30,500\n",
            encoding="utf-8",
        )

        controller = self.controller("datesinperiod-settings.ini")
        self.assertTrue(controller._commit_import(calendar_path, parse_file(calendar_path)))
        calendar_id = str(controller.activeTableId)
        self.assertTrue(controller.setColumnType("Date", "date"), controller.statusMessage)
        self.mark_calendar(controller)
        calendar_table = controller._model_table_for_source(controller._project, calendar_id)
        assert calendar_table is not None
        calendar_name = str(calendar_table["name"])

        self.assertTrue(controller._commit_import(orders_path, parse_file(orders_path)))
        orders_id = str(controller.activeTableId)
        self.assertTrue(controller.setColumnType("OrderDate", "date"), controller.statusMessage)
        self.assertTrue(controller.setColumnType("Amount", "whole_number"), controller.statusMessage)
        self.add_date_relationship(controller, calendar_id, orders_id)
        self.assertTrue(
            controller.create_measure(
                "Prior year sales",
                (
                    "CALCULATE(SUM([Amount]), DATESINPERIOD("
                    f"'{calendar_name}'[Date], \"2020-06-30\", -1, YEAR))"
                ),
            ),
            controller.statusMessage,
        )
        self.assertEqual(controller.reportKpis["Prior year sales"], "60")

        project_path = self.root / "datesinperiod.npa"
        self.assertTrue(controller._save_to(project_path))
        orders_path.write_text(
            "OrderDate,Amount\n"
            "2019-06-30,5\n"
            "2019-07-01,11\n"
            "2019-12-31,22\n"
            "2020-06-30,33\n"
            "2020-07-01,40\n"
            "2021-06-30,500\n",
            encoding="utf-8",
        )

        reopened = self.controller("datesinperiod-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Prior year sales"], "66")

    def test_previousyear_measure_survives_reopen_and_recomputes_from_sources(self) -> None:
        calendar_path = self.root / "Calendar PREVIOUSYEAR.csv"
        calendar_start = date(2018, 1, 1)
        calendar_end = date(2021, 12, 31)
        calendar_lines = ["Date"] + [
            (calendar_start + timedelta(days=offset)).isoformat()
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        calendar_path.write_text("\n".join(calendar_lines) + "\n", encoding="utf-8")
        orders_path = self.root / "Orders PREVIOUSYEAR.csv"
        orders_path.write_text(
            "OrderDate,Amount\n"
            "2018-12-31,500\n"
            "2019-01-01,10\n"
            "2019-06-30,20\n"
            "2019-12-31,30\n"
            "2020-06-30,40\n",
            encoding="utf-8",
        )

        controller = self.controller("previousyear-settings.ini")
        self.assertTrue(controller._commit_import(calendar_path, parse_file(calendar_path)))
        calendar_source_id = str(controller.activeTableId)
        self.assertTrue(
            controller.setColumnType("Date", "date"), controller.statusMessage
        )
        self.mark_calendar(controller)
        calendar_table = controller._model_table_for_source(
            controller._project, calendar_source_id
        )
        assert calendar_table is not None
        calendar_id = str(calendar_table["id"])
        calendar_name = str(calendar_table["name"])

        self.assertTrue(controller._commit_import(orders_path, parse_file(orders_path)))
        orders_source_id = str(controller.activeTableId)
        self.assertTrue(
            controller.setColumnType("OrderDate", "date"), controller.statusMessage
        )
        self.assertTrue(
            controller.setColumnType("Amount", "whole_number"), controller.statusMessage
        )
        orders_table = controller._model_table_for_source(
            controller._project, orders_source_id
        )
        assert orders_table is not None
        self.add_date_relationship(controller, calendar_id, str(orders_table["id"]))
        self.assertTrue(controller.addReportFilterRule(
            calendar_id, "Date", "equals", "2020-06-30", "", "", "and"
        ), controller.statusMessage)
        self.assertTrue(
            controller.create_measure(
                "Prior year sales",
                (
                    "CALCULATE(SUM([Amount]), "
                    f"PREVIOUSYEAR('{calendar_name}'[Date]))"
                ),
            ),
            controller.statusMessage,
        )
        self.assertEqual(controller.reportKpis["Prior year sales"], "60")

        project_path = self.root / "previousyear.npa"
        self.assertTrue(controller._save_to(project_path))
        orders_path.write_text(
            "OrderDate,Amount\n"
            "2018-12-31,500\n"
            "2019-01-01,11\n"
            "2019-06-30,22\n"
            "2019-12-31,33\n"
            "2020-06-30,40\n",
            encoding="utf-8",
        )

        reopened = self.controller("previousyear-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Prior year sales"], "66")

    def test_previousquarter_measure_survives_reopen_and_recomputes_from_sources(self) -> None:
        calendar_path = self.root / "Calendar PREVIOUSQUARTER.csv"
        calendar_start = date(2022, 1, 1)
        calendar_end = date(2024, 12, 31)
        calendar_lines = ["Date"] + [
            (calendar_start + timedelta(days=offset)).isoformat()
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        calendar_path.write_text("\n".join(calendar_lines) + "\n", encoding="utf-8")
        orders_path = self.root / "Orders PREVIOUSQUARTER.csv"
        orders_path.write_text(
            "OrderDate,Amount,Region\n"
            "2023-09-30,500,East\n"
            "2023-10-01,10,East\n"
            "2023-12-31,20,East\n"
            "2024-01-01,30,East\n"
            "2023-12-31,700,West\n",
            encoding="utf-8",
        )

        controller = self.controller("previousquarter-settings.ini")
        self.assertTrue(controller._commit_import(calendar_path, parse_file(calendar_path)))
        calendar_source_id = str(controller.activeTableId)
        self.assertTrue(
            controller.setColumnType("Date", "date"), controller.statusMessage
        )
        self.mark_calendar(controller)
        calendar_table = controller._model_table_for_source(
            controller._project, calendar_source_id
        )
        assert calendar_table is not None
        calendar_id = str(calendar_table["id"])
        calendar_name = str(calendar_table["name"])

        self.assertTrue(controller._commit_import(orders_path, parse_file(orders_path)))
        orders_source_id = str(controller.activeTableId)
        self.assertTrue(
            controller.setColumnType("OrderDate", "date"), controller.statusMessage
        )
        self.assertTrue(
            controller.setColumnType("Amount", "whole_number"), controller.statusMessage
        )
        orders_table = controller._model_table_for_source(
            controller._project, orders_source_id
        )
        assert orders_table is not None
        orders_id = str(orders_table["id"])
        self.add_date_relationship(controller, calendar_id, orders_id)
        self.assertTrue(controller.addReportFilterRule(
            calendar_id, "Date", "equals", "2024-02-15", "", "", "and"
        ), controller.statusMessage)
        self.assertTrue(controller.addReportFilterRule(
            orders_id, "Region", "equals", "East", "", "", "and"
        ), controller.statusMessage)
        self.assertTrue(
            controller.create_measure(
                "Prior quarter sales",
                (
                    "CALCULATE(SUM([Amount]), "
                    f"PREVIOUSQUARTER('{calendar_name}'[Date]))"
                ),
            ),
            controller.statusMessage,
        )
        self.assertEqual(controller.reportKpis["Prior quarter sales"], "30")

        project_path = self.root / "previousquarter.npa"
        self.assertTrue(controller._save_to(project_path))
        orders_path.write_text(
            "OrderDate,Amount,Region\n"
            "2023-09-30,500,East\n"
            "2023-10-01,11,East\n"
            "2023-12-31,22,East\n"
            "2024-01-01,30,East\n"
            "2023-12-31,700,West\n",
            encoding="utf-8",
        )

        reopened = self.controller("previousquarter-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Prior quarter sales"], "33")

    def test_previousmonth_measure_survives_reopen_and_recomputes_from_sources(self) -> None:
        calendar_path = self.root / "Calendar PREVIOUSMONTH.csv"
        calendar_start = date(2023, 12, 1)
        calendar_end = date(2024, 3, 31)
        calendar_lines = ["Date"] + [
            (calendar_start + timedelta(days=offset)).isoformat()
            for offset in range((calendar_end - calendar_start).days + 1)
        ]
        calendar_path.write_text("\n".join(calendar_lines) + "\n", encoding="utf-8")
        orders_path = self.root / "Orders PREVIOUSMONTH.csv"
        orders_path.write_text(
            "OrderDate,Amount,Region\n"
            "2023-12-31,500,East\n"
            "2024-01-01,10,East\n"
            "2024-01-31,20,East\n"
            "2024-02-01,30,East\n"
            "2024-02-15,40,East\n"
            "2024-01-15,700,West\n",
            encoding="utf-8",
        )

        controller = self.controller("previousmonth-settings.ini")
        self.assertTrue(controller._commit_import(calendar_path, parse_file(calendar_path)))
        calendar_source_id = str(controller.activeTableId)
        self.assertTrue(
            controller.setColumnType("Date", "date"), controller.statusMessage
        )
        self.mark_calendar(controller)
        calendar_table = controller._model_table_for_source(
            controller._project, calendar_source_id
        )
        assert calendar_table is not None
        calendar_id = str(calendar_table["id"])
        calendar_name = str(calendar_table["name"])

        self.assertTrue(controller._commit_import(orders_path, parse_file(orders_path)))
        orders_source_id = str(controller.activeTableId)
        self.assertTrue(
            controller.setColumnType("OrderDate", "date"), controller.statusMessage
        )
        self.assertTrue(
            controller.setColumnType("Amount", "whole_number"), controller.statusMessage
        )
        orders_table = controller._model_table_for_source(
            controller._project, orders_source_id
        )
        assert orders_table is not None
        orders_id = str(orders_table["id"])
        self.add_date_relationship(controller, calendar_id, orders_id)
        self.assertTrue(controller.addReportFilterRule(
            calendar_id, "Date", "equals", "2024-02-15", "", "", "and"
        ), controller.statusMessage)
        self.assertTrue(controller.addReportFilterRule(
            orders_id, "Region", "equals", "East", "", "", "and"
        ), controller.statusMessage)
        self.assertTrue(
            controller.create_measure(
                "Prior month sales",
                (
                    "CALCULATE(SUM([Amount]), "
                    f"PREVIOUSMONTH('{calendar_name}'[Date]))"
                ),
            ),
            controller.statusMessage,
        )
        self.assertEqual(controller.reportKpis["Prior month sales"], "30")

        project_path = self.root / "previousmonth.npa"
        self.assertTrue(controller._save_to(project_path))
        orders_path.write_text(
            "OrderDate,Amount,Region\n"
            "2023-12-31,500,East\n"
            "2024-01-01,11,East\n"
            "2024-01-31,22,East\n"
            "2024-02-01,30,East\n"
            "2024-02-15,40,East\n"
            "2024-01-15,700,West\n",
            encoding="utf-8",
        )

        reopened = self.controller("previousmonth-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Prior month sales"], "33")


if __name__ == "__main__":
    unittest.main()
