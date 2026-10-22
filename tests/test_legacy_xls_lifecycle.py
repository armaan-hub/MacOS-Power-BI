"""End-to-end acceptance for the legacy BIFF Excel import workflow."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import (
    _open_legacy_excel,
    list_excel_sheets,
    parse_file,
    recommend_excel_sheet,
)
from analytics_studio.import_preview_dialog import FileImportPreviewDialog


FIXTURES = Path(__file__).parent / "fixtures"


class LegacyXlsLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "quarterly.xls"
        shutil.copyfile(FIXTURES / "legacy_excel.xls", self.source_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, settings_name: str) -> StudioController:
        settings = QSettings(
            str(self.root / settings_name), QSettings.Format.IniFormat
        )
        return StudioController(self.app, settings)

    def wait_for_preview(self, dialog: FileImportPreviewDialog) -> None:
        deadline = time.monotonic() + 5
        while not dialog.import_button.isEnabled() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertTrue(dialog.import_button.isEnabled())

    def test_preview_import_project_reopen_and_changed_source_refresh(self) -> None:
        self.assertEqual(list_excel_sheets(self.source_path), ["Cover", "Data"])
        self.assertEqual(recommend_excel_sheet(self.source_path), "Data")

        dialog = FileImportPreviewDialog(
            self.source_path,
            replacing=False,
            initial_options={"header_row": None},
        )
        self.wait_for_preview(dialog)
        self.assertEqual(dialog.sheet_combo.currentText(), "Data")
        self.assertTrue(dialog.header_auto_checkbox.isChecked())
        preview = dialog.table.model()
        self.assertEqual(preview.rowCount(), 2)
        self.assertEqual(preview.columnCount(), 4)
        self.assertEqual(preview.data(preview.index(0, 0)), "Ada")
        self.assertEqual(preview.data(preview.index(0, 1)), "2024-01-01")
        self.assertEqual(preview.data(preview.index(0, 3)), "25")
        self.assertIn("saved formula results", dialog.notice_label.text())

        dialog._accept_candidate()
        candidate = dialog.candidate
        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(candidate.options, {"sheet_name": "Data", "header_row": None})
        reparsed = parse_file(self.source_path, options=candidate.options)
        self.assertEqual(reparsed.options, candidate.options)
        self.assertEqual(reparsed.headers, candidate.headers)
        self.assertEqual(reparsed.rows, candidate.rows)
        self.assertEqual(candidate.rows, [
            {
                "Name": "Ada", "Order Date": date(2024, 1, 1),
                "Amount": Decimal("12.5"), "Amount x 2": 25,
            },
            {
                "Name": "Bob", "Order Date": date(2024, 1, 2),
                "Amount": 5, "Amount x 2": 10,
            },
        ])

        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(self.source_path, candidate))
        source_id = controller.activeTableId
        project_path = self.root / "legacy-excel.npa"
        self.assertTrue(controller._save_to(project_path))

        reopened = self.controller("reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.activeTableId, source_id)
        self.assertEqual(reopened._active_source_kind, "excel")
        self.assertEqual(reopened._active_parser_options, candidate.options)
        self.assertEqual(reopened._rows, candidate.rows)

        shutil.copyfile(FIXTURES / "legacy_excel_changed.xls", self.source_path)
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [
            {
                "Name": "Ada", "Order Date": date(2024, 1, 1),
                "Amount": 15, "Amount x 2": 30,
            },
            {
                "Name": "Bob", "Order Date": date(2024, 1, 2),
                "Amount": 6, "Amount x 2": 12,
            },
        ])
        dialog.deleteLater()

    def test_manual_worksheet_and_header_row_options_are_respected(self) -> None:
        dialog = FileImportPreviewDialog(
            self.source_path,
            replacing=False,
            initial_options={"sheet_name": "Data", "header_row": 3},
        )
        self.wait_for_preview(dialog)

        self.assertEqual(dialog.sheet_combo.currentText(), "Data")
        self.assertFalse(dialog.header_auto_checkbox.isChecked())
        self.assertEqual(dialog.header_row_spin.value(), 3)
        self.assertEqual(dialog.table.model().rowCount(), 2)
        self.assertEqual(dialog.table.model().columnCount(), 4)

        dialog._accept_candidate()
        self.assertEqual(dialog.candidate.options, {
            "sheet_name": "Data", "header_row": 3,
        })
        dialog.deleteLater()

    def test_transform_raw_rows_reparse_works_for_legacy_xls(self) -> None:
        dialog = FileImportPreviewDialog(self.source_path, replacing=False)
        self.wait_for_preview(dialog)
        self.assertTrue(dialog.transform_raw_rows_checkbox.isChecked())

        dialog.transform_button.click()
        deadline = time.monotonic() + 5
        while dialog.candidate is None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()

        candidate = dialog.candidate
        self.assertIsNotNone(candidate)
        assert candidate is not None
        expected = parse_file(
            self.source_path,
            options={"sheet_name": "Data", "header_row": None, "raw_rows": True},
        )
        self.assertEqual(candidate.options, expected.options)
        self.assertEqual(candidate.headers, expected.headers)
        self.assertEqual(candidate.rows, expected.rows)
        self.assertIsNone(candidate.header_row_used)
        dialog.deleteLater()

    def test_raw_legacy_xls_uses_biff_declared_trailing_rows(self) -> None:
        def open_with_declared_blank_tail(path, cancel_event=None):
            xlrd, book = _open_legacy_excel(path, cancel_event)
            sheet = book.sheet_by_name("Data")
            sheet._dimnrows = sheet.nrows + 3
            return xlrd, book

        with patch(
            "analytics_studio.file_import._open_legacy_excel",
            side_effect=open_with_declared_blank_tail,
        ):
            raw = parse_file(
                self.source_path,
                options={"sheet_name": "Data", "header_row": None, "raw_rows": True},
            )
            automatic = parse_file(
                self.source_path,
                options={"sheet_name": "Data", "header_row": None},
            )

        self.assertEqual(raw.row_count, 8)
        self.assertTrue(all(
            value is None for row in raw.rows[-3:] for value in row.values()
        ))
        self.assertEqual(automatic.row_count, 2)


if __name__ == "__main__":
    unittest.main()
