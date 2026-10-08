"""Value checks for marked local date tables."""

from __future__ import annotations

import unittest

from analytics_studio.date_tables import DateTableError, validate_date_table_rows


class DateTableValidationTests(unittest.TestCase):
    def test_accepts_unordered_contiguous_dates_across_leap_day(self) -> None:
        rows = [
            {"Date": "2020-03-01"},
            {"Date": "2020-02-29"},
            {"Date": "2020-02-28"},
        ]

        self.assertEqual(validate_date_table_rows(rows, "Date", "date"), 3)

    def test_rejects_empty_blank_duplicate_invalid_and_missing_dates(self) -> None:
        cases = [
            ([], "at least one"),
            ([{"Date": ""}], "blank"),
            ([{"Date": "2024-01-01"}, {"Date": "2024-01-01"}], "duplicate"),
            ([{"Date": "not-a-date"}], "valid date"),
            ([{"Date": "2024-01-01"}, {"Date": "2024-01-03"}], "missing date"),
        ]
        for rows, message in cases:
            with self.subTest(rows=rows), self.assertRaisesRegex(DateTableError, message):
                validate_date_table_rows(rows, "Date", "date")

    def test_requires_a_date_or_datetime_model_type(self) -> None:
        with self.assertRaisesRegex(DateTableError, "date or datetime"):
            validate_date_table_rows([{"Date": "2024-01-01"}], "Date", "text")

    def test_datetime_values_must_share_the_same_time_of_day(self) -> None:
        rows = [
            {"Date": "2024-01-01T08:30:00"},
            {"Date": "2024-01-02T08:30:00"},
        ]
        self.assertEqual(validate_date_table_rows(rows, "Date", "datetime"), 2)
        rows[1]["Date"] = "2024-01-02T09:30:00"
        with self.assertRaisesRegex(DateTableError, "same time"):
            validate_date_table_rows(rows, "Date", "datetime")

    def test_datetime_values_must_not_include_timezone_offsets(self) -> None:
        rows = [
            {"Date": "2024-01-01T08:30:00+14:00"},
            {"Date": "2024-01-02T08:30:00-12:00"},
        ]
        with self.assertRaisesRegex(DateTableError, "timezone offsets"):
            validate_date_table_rows(rows, "Date", "datetime")


if __name__ == "__main__":
    unittest.main()
