"""Acceptance checks for Sort Rows by Multiple Columns."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QComboBox

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.local_table_dialogs import TransformDataDialog


class SortRowsMultipleColumnsLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "sales.csv"
        self.source_path.write_text(
            "Region,Amount,Id\n"
            "East,10,A\nWest,10,B\nEast,20,C\nWest,5,D\nEast,5,E\nEast,20,F\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def test_sort_priority_mixed_directions_and_stability_replay(self) -> None:
        raw = parse_file(self.source_path)
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("convert_type")
        )
        dialog.column_combo.setCurrentText("Amount")
        dialog.option_combo.setCurrentIndex(
            dialog.option_combo.findData("whole_number")
        )
        dialog._add_step()

        dialog._add_or_start_new_step()
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("sort_rows_by_columns")
        )
        amount_column = dialog.sort_criteria_table.cellWidget(0, 0)
        amount_direction = dialog.sort_criteria_table.cellWidget(0, 1)
        self.assertIsInstance(amount_column, QComboBox)
        self.assertIsInstance(amount_direction, QComboBox)
        amount_column.setCurrentText("Amount")
        amount_direction.setCurrentIndex(amount_direction.findData("desc"))
        dialog._add_sort_level()
        region_column = dialog.sort_criteria_table.cellWidget(1, 0)
        region_direction = dialog.sort_criteria_table.cellWidget(1, 1)
        self.assertIsInstance(region_column, QComboBox)
        self.assertIsInstance(region_direction, QComboBox)
        region_column.setCurrentText("Region")
        region_direction.setCurrentIndex(region_direction.findData("asc"))
        dialog._add_step()

        self.assertEqual(dialog._steps[1]["sorts"], [
            {"column": "Amount", "direction": "desc"},
            {"column": "Region", "direction": "asc"},
        ])
        self.assertEqual([row["Id"] for row in dialog._preview_candidate.rows], [
            "C", "F", "A", "B", "E", "D",
        ])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "multi-sort-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Region,Amount,Id\nWest,5,G\nEast,5,H\nWest,5,I\nEast,10,J\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual([row["Id"] for row in reopened._rows], ["J", "H", "G", "I"])

        self.source_path.write_text(
            "Region,Amount,Id\nWest,10,K\nEast,20,L\nWest,20,M\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual([row["Id"] for row in reopened._rows], ["L", "M", "K"])


if __name__ == "__main__":
    unittest.main()
