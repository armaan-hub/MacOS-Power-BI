"""Value and range checks for generated calendar tables."""

from __future__ import annotations

import unittest

from analytics_studio.calendar_tables import (
    CalendarTableError,
    calendar_expression,
    generate_calendar,
    generate_calendar_auto,
)
from analytics_studio.file_import import ImportCandidate, MAX_DATA_ROWS
from analytics_studio.project import new_project, validate_project


class CalendarTableTests(unittest.TestCase):
    def test_calendar_returns_inclusive_contiguous_days(self) -> None:
        candidate = generate_calendar("2024-02-28", "2024-03-01")

        self.assertEqual(candidate.headers, ["Date"])
        self.assertEqual(candidate.rows, [
            {"Date": "2024-02-28"},
            {"Date": "2024-02-29"},
            {"Date": "2024-03-01"},
        ])

    def test_calendar_rejects_bad_order_bad_dates_and_ranges_over_row_limit(self) -> None:
        cases = [
            ("2024-02-02", "2024-02-01", "on or before"),
            ("02/01/2024", "2024-02-02", "ISO date"),
            ("0001-01-01", "9999-12-31", "table limit"),
        ]
        for start, end, message in cases:
            with self.subTest(start=start), self.assertRaisesRegex(CalendarTableError, message):
                generate_calendar(start, end)

    def test_calendar_auto_spans_full_fiscal_years_across_date_columns(self) -> None:
        candidates = {
            "orders": ImportCandidate(
                "csv", ["OrderDate"], [{"OrderDate": "2020-03-15"}], {}, []
            ),
            "forecast": ImportCandidate(
                "csv", ["Expected"],
                [{"Expected": "2021-02-20T23:30:00"}, {"Expected": "2022-08-05T08:00:00"}],
                {}, [],
            ),
        }
        fields = [
            {"source_id": "orders", "column": "OrderDate", "type": "date"},
            {"source_id": "forecast", "column": "Expected", "type": "datetime"},
        ]

        candidate = generate_calendar_auto(candidates, fields, 3)

        self.assertEqual(candidate.rows[0]["Date"], "2019-04-01")
        self.assertEqual(candidate.rows[-1]["Date"], "2023-03-31")
        self.assertEqual(len(candidate.rows), 1461)
        self.assertIn({"Date": "2020-02-29"}, candidate.rows)

    def test_calendar_auto_ignores_blanks_and_rejects_missing_or_invalid_values(self) -> None:
        candidate = ImportCandidate(
            "csv", ["When"], [{"When": ""}, {"When": "2024-06-15"}], {}, []
        )
        fields = [{"source_id": "source", "column": "When", "type": "date"}]
        generated = generate_calendar_auto({"source": candidate}, fields)
        self.assertEqual(generated.rows[0]["Date"], "2024-01-01")
        self.assertEqual(generated.rows[-1]["Date"], "2024-12-31")

        invalid_candidate = ImportCandidate(
            "csv", ["When"], [{"When": "not a date"}], {}, []
        )
        with self.assertRaisesRegex(CalendarTableError, "valid date"):
            generate_calendar_auto({"source": invalid_candidate}, fields)
        blank_candidate = ImportCandidate(
            "csv", ["When"], [{"When": ""}], {}, []
        )
        with self.assertRaisesRegex(CalendarTableError, "No nonblank"):
            generate_calendar_auto({"source": blank_candidate}, [
                {"source_id": "source", "column": "When", "type": "datetime"}
            ])

    def test_auto_calendar_validates_fields_fiscal_month_and_range_size(self) -> None:
        candidate = ImportCandidate(
            "csv", ["When"], [{"When": "0001-01-01"}, {"When": "9999-12-31"}], {}, []
        )
        fields = [{"source_id": "source", "column": "When", "type": "date"}]
        with self.assertRaisesRegex(CalendarTableError, "table limit"):
            generate_calendar_auto({"source": candidate}, fields)
        with self.assertRaisesRegex(CalendarTableError, "between 1 and 12"):
            generate_calendar_auto({"source": candidate}, fields, 13)
        with self.assertRaisesRegex(CalendarTableError, "not loaded"):
            generate_calendar_auto({}, fields)

    def test_calendar_expression_displays_supported_dax_shape(self) -> None:
        self.assertEqual(calendar_expression({
            "operation": "calendar",
            "start_date": "2024-02-01",
            "end_date": "2024-02-29",
        }), "CALENDAR(DATE(2024, 2, 1), DATE(2024, 2, 29))")
        self.assertEqual(calendar_expression({
            "operation": "calendar_auto", "fiscal_year_end_month": 12,
        }), "CALENDARAUTO()")
        self.assertEqual(calendar_expression({
            "operation": "calendar_auto", "fiscal_year_end_month": 3,
        }), "CALENDARAUTO(3)")

    def test_calendar_auto_dependencies_expand_when_model_tables_are_added(self) -> None:
        project = new_project("automatic calendar dependency")
        project["data_sources"] = [
            {
                "id": "orders", "name": "Orders", "kind": "inline",
                "headers": ["OrderDate"],
                "rows": [{"OrderDate": "2024-01-01"}],
                "transform_steps": [],
            },
            {
                "id": "calendar-auto", "name": "Calendar", "kind": "query",
                "load_enabled": True, "include_in_report_refresh": True,
                "query_definition": {
                    "operation": "calendar_auto", "source_ids": [],
                    "fiscal_year_end_month": 12,
                },
                "transform_steps": [{
                    "op": "convert_type", "column": "Date", "type": "date",
                }],
            },
        ]
        project["model"]["tables"] = [
            {
                "id": "orders", "source_id": "orders", "name": "Orders",
                "column_types": {"OrderDate": "date"},
            },
            {
                "id": "calendar-auto", "source_id": "calendar-auto", "name": "Calendar",
                "column_types": {"Date": "date"}, "date_column": "Date",
            },
        ]

        validated = validate_project(project)
        self.assertEqual(
            validated["data_sources"][1]["query_definition"]["source_ids"], ["orders"]
        )

        validated["data_sources"].insert(1, {
            "id": "forecast", "name": "Forecast", "kind": "inline",
            "headers": ["Expected"],
            "rows": [{"Expected": "2025-06-01"}],
            "transform_steps": [],
        })
        validated["model"]["tables"].insert(1, {
            "id": "forecast", "source_id": "forecast", "name": "Forecast",
            "column_types": {"Expected": "date"},
        })

        expanded = validate_project(validated)
        self.assertEqual(
            next(source for source in expanded["data_sources"] if source["id"] == "calendar-auto")
            ["query_definition"]["source_ids"],
            ["orders", "forecast"],
        )


if __name__ == "__main__":
    unittest.main()
