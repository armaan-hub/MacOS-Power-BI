"""Acceptance checks for Pivot Column preview, aggregation, and replay."""

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


class PivotColumnLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "monthly-sales.csv"
        self.source_path.write_text(
            "Region,Store,Month,Revenue\n"
            "North,1,Jan,10\n"
            "North,1,Jan,20\n"
            "North,1,Jan,\n"
            "North,1,Feb,5\n"
            "North,1,Mar,\n"
            "South,2,Feb,7\n"
            "South,2,Mar,4\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def pivot_dialog(self, candidate, aggregation: str) -> TransformDataDialog:
        dialog = TransformDataDialog(candidate)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("pivot_column")
        )
        dialog.column_combo.setCurrentText("Month")
        dialog._update_pivot_value_choices()
        dialog.pivot_value_column_combo.setCurrentText("Revenue")
        dialog.option_combo.setCurrentIndex(dialog.option_combo.findData(aggregation))
        return dialog

    def test_pivot_aggregation_choices_and_saved_refresh(self) -> None:
        raw = parse_file(self.source_path)
        expected_headers = ["Region", "Store", "Jan", "Feb", "Mar"]
        expected = {
            "count_all": [
                {"Region": "North", "Store": "1", "Jan": "3", "Feb": "1", "Mar": "1"},
                {"Region": "South", "Store": "2", "Jan": "", "Feb": "1", "Mar": "1"},
            ],
            "count_non_blank": [
                {"Region": "North", "Store": "1", "Jan": "2", "Feb": "1", "Mar": "0"},
                {"Region": "South", "Store": "2", "Jan": "", "Feb": "1", "Mar": "1"},
            ],
            "min": [
                {"Region": "North", "Store": "1", "Jan": "10", "Feb": "5", "Mar": ""},
                {"Region": "South", "Store": "2", "Jan": "", "Feb": "7", "Mar": "4"},
            ],
            "max": [
                {"Region": "North", "Store": "1", "Jan": "20", "Feb": "5", "Mar": ""},
                {"Region": "South", "Store": "2", "Jan": "", "Feb": "7", "Mar": "4"},
            ],
            "median": [
                {"Region": "North", "Store": "1", "Jan": "15", "Feb": "5", "Mar": ""},
                {"Region": "South", "Store": "2", "Jan": "", "Feb": "7", "Mar": "4"},
            ],
            "sum": [
                {"Region": "North", "Store": "1", "Jan": "30", "Feb": "5", "Mar": ""},
                {"Region": "South", "Store": "2", "Jan": "", "Feb": "7", "Mar": "4"},
            ],
            "average": [
                {"Region": "North", "Store": "1", "Jan": "15", "Feb": "5", "Mar": ""},
                {"Region": "South", "Store": "2", "Jan": "", "Feb": "7", "Mar": "4"},
            ],
        }

        no_aggregate = self.pivot_dialog(raw, "none")
        no_aggregate._add_step()
        self.assertIsNone(no_aggregate.candidate)
        self.assertIn("multiple values", no_aggregate.error_label.text())
        no_aggregate.deleteLater()

        for aggregation, expected_rows in expected.items():
            with self.subTest(aggregation=aggregation):
                dialog = self.pivot_dialog(raw, aggregation)
                dialog._add_step()
                self.assertEqual(dialog._preview_candidate.headers, expected_headers)
                self.assertEqual(dialog._preview_candidate.rows, expected_rows)
                dialog.deleteLater()

        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId
        dialog = self.pivot_dialog(raw, "sum")
        dialog._add_step()
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "pivot-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Region,Store,Month,Revenue\n"
            "East,3,Jan,1\nEast,3,Jan,2\nEast,3,Feb,8\nWest,4,Mar,5\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._headers, expected_headers)
        self.assertEqual(reopened._rows, [
            {"Region": "East", "Store": "3", "Jan": "3", "Feb": "8", "Mar": ""},
            {"Region": "West", "Store": "4", "Jan": "", "Feb": "", "Mar": "5"},
        ])

        self.source_path.write_text(
            "Region,Store,Month,Revenue\n"
            "Central,5,Apr,12\nCentral,5,Apr,13\nSouth,2,Jan,10\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual(reopened._headers, ["Region", "Store", "Apr", "Jan"])
        self.assertEqual(reopened._rows, [
            {"Region": "Central", "Store": "5", "Apr": "25", "Jan": ""},
            {"Region": "South", "Store": "2", "Apr": "", "Jan": "10"},
        ])


if __name__ == "__main__":
    unittest.main()
