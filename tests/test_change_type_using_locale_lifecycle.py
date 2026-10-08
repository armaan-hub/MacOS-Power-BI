"""Acceptance checks for Change Type Using Locale through project lifecycle."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.local_table_dialogs import TransformDataDialog


class ChangeTypeUsingLocaleLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "localized.csv"
        self.source_path.write_text(
            "Whole,Decimal,Date,Stamp,Clock\n"
            '"1,234","1,234.50",12/31/2024,"12/31/2024 1:45 PM","1:45:30 PM"\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    @staticmethod
    def table_for(controller: StudioController, source_id: str) -> dict:
        return next(
            table for table in controller._project["model"]["tables"]
            if table["source_id"] == source_id
        )

    @staticmethod
    def add_locale_step(
        dialog: TransformDataDialog, column: str, target_type: str
    ) -> None:
        dialog._add_or_start_new_step()
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("convert_type_using_locale")
        )
        dialog.column_combo.setCurrentText(column)
        dialog.option_combo.setCurrentIndex(
            dialog.option_combo.findData(target_type)
        )
        dialog.culture_edit.setText("en-US")
        dialog._add_step()

    def test_locale_conversion_replays_numbers_dates_and_times(self) -> None:
        raw = parse_file(self.source_path)
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        for column, target_type in (
            ("Whole", "whole_number"),
            ("Decimal", "decimal_number"),
            ("Date", "date"),
            ("Stamp", "datetime"),
            ("Clock", "time"),
        ):
            self.add_locale_step(dialog, column, target_type)

        expected = {
            "Whole": "1234",
            "Decimal": "1234.50",
            "Date": "2024-12-31",
            "Stamp": "2024-12-31T13:45:00",
            "Clock": "13:45:30",
        }
        self.assertEqual(dialog._preview_candidate.rows, [expected])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        self.assertEqual(
            self.table_for(controller, source_id)["column_types"],
            {
                "Whole": "whole_number",
                "Decimal": "decimal_number",
                "Date": "date",
                "Stamp": "datetime",
                "Clock": "time",
            },
        )
        dialog.deleteLater()

        project_path = self.root / "locale-conversion-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Whole,Decimal,Date,Stamp,Clock\n"
            '"2,000","2,500.25",01/01/2025,"01/01/2025 12:00 AM","2:15 PM"\n',
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._rows, [{
            "Whole": "2000",
            "Decimal": "2500.25",
            "Date": "2025-01-01",
            "Stamp": "2025-01-01T00:00:00",
            "Clock": "14:15:00",
        }])

        self.source_path.write_text(
            "Whole,Decimal,Date,Stamp,Clock\n"
            '"3,000","3,750.75",01/02/2025,"01/02/2025 3:30 PM","4:00 PM"\n',
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [{
            "Whole": "3000",
            "Decimal": "3750.75",
            "Date": "2025-01-02",
            "Stamp": "2025-01-02T15:30:00",
            "Clock": "16:00:00",
        }])


if __name__ == "__main__":
    unittest.main()
