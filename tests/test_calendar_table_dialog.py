"""Dialog preview checks for fixed and automatic calendar tables."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication

from analytics_studio.calendar_table_dialog import CalendarTableDialog
from analytics_studio.file_import import ImportCandidate


class CalendarTableDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.candidate = ImportCandidate(
            "csv", ["OrderDate", "Label"],
            [
                {"OrderDate": "2020-03-15", "Label": "First"},
                {"OrderDate": "2022-08-05", "Label": "Last"},
            ], {}, [],
        )
        self.table = {
            "id": "orders", "sourceId": "orders", "name": "Orders",
            "kind": "csv", "loaded": True, "loadEnabled": True,
            "headers": list(self.candidate.headers),
            "columnTypes": {"OrderDate": "date", "Label": "text"},
            "calculatedColumns": [], "queryOperation": "",
        }

    def test_fixed_range_preview_and_saved_definition(self) -> None:
        dialog = CalendarTableDialog([self.table], {"orders": self.candidate})
        dialog.table_name_edit.setText("Fiscal dates")
        dialog.start_date_edit.setDate(QDate(2024, 2, 28))
        dialog.end_date_edit.setDate(QDate(2024, 3, 1))

        self.assertTrue(dialog.create_button.isEnabled())
        self.assertEqual(dialog.expression_edit.text(),
                         "CALENDAR(DATE(2024, 2, 28), DATE(2024, 3, 1))")
        dialog._accept_table()
        self.assertEqual(dialog.candidate.rows, [
            {"Date": "2024-02-28"},
            {"Date": "2024-02-29"},
            {"Date": "2024-03-01"},
        ])
        self.assertEqual(dialog.query_definition, {
            "operation": "calendar", "source_ids": [],
            "start_date": "2024-02-28", "end_date": "2024-03-01",
        })
        self.assertEqual(dialog.output_types, {"Date": "date"})
        dialog.deleteLater()

    def test_automatic_preview_uses_loaded_model_dates_and_fiscal_end(self) -> None:
        dialog = CalendarTableDialog([self.table], {"orders": self.candidate})
        dialog.range_mode_combo.setCurrentIndex(1)
        dialog.fiscal_month_combo.setCurrentIndex(2)

        self.assertTrue(dialog.create_button.isEnabled())
        self.assertEqual(dialog.expression_edit.text(), "CALENDARAUTO(3)")
        dialog._accept_table()
        self.assertEqual(dialog.query_definition, {
            "operation": "calendar_auto",
            "source_ids": ["orders"],
            "fiscal_year_end_month": 3,
        })
        self.assertEqual(dialog.candidate.rows[0]["Date"], "2019-04-01")
        self.assertEqual(dialog.candidate.rows[-1]["Date"], "2023-03-31")
        self.assertIn("Orders[OrderDate]", dialog.date_column_summary.text())
        dialog.deleteLater()

    def test_automatic_mode_requires_a_typed_model_date_column(self) -> None:
        dialog = CalendarTableDialog([], {})
        dialog.range_mode_combo.setCurrentIndex(1)

        self.assertFalse(dialog.create_button.isEnabled())
        self.assertIn("Date or DateTime", dialog.error_label.text())
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
