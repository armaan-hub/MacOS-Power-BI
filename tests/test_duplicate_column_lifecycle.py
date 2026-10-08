"""Acceptance checks for Duplicate Column value/type persistence."""

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


class DuplicateColumnLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "amounts.csv"
        self.source_path.write_text("Amount,Label\n001,A\n002,B\n", encoding="utf-8")

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

    def test_duplicate_column_copies_values_type_and_refreshes(self) -> None:
        controller = self.controller("settings.ini")
        raw = parse_file(self.source_path)
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("convert_type")
        )
        dialog.column_combo.setCurrentText("Amount")
        dialog.option_combo.setCurrentIndex(dialog.option_combo.findData("whole_number"))
        dialog._add_step()

        dialog.step_list.setCurrentRow(-1)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("duplicate_column")
        )
        dialog.column_combo.setCurrentText("Amount")
        dialog.value_edit.setText("Amount copy")
        dialog._add_step()
        self.assertEqual(dialog._preview_candidate.headers, [
            "Amount", "Label", "Amount copy",
        ])
        self.assertEqual(dialog._preview_candidate.rows, [
            {"Amount": "1", "Label": "A", "Amount copy": "1"},
            {"Amount": "2", "Label": "B", "Amount copy": "2"},
        ])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        self.assertEqual(
            self.table_for(controller, source_id)["column_types"]["Amount copy"],
            "whole_number",
        )
        dialog.deleteLater()

        collision = TransformDataDialog(raw)
        collision.operation_combo.setCurrentIndex(
            collision.operation_combo.findData("duplicate_column")
        )
        collision.column_combo.setCurrentText("Amount")
        collision.value_edit.setText("Label")
        collision._add_step()
        self.assertIsNone(collision.candidate)
        self.assertIn("already exists", collision.error_label.text())
        collision.deleteLater()

        project_path = self.root / "duplicate-column-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text("Amount,Label\n003,C\n", encoding="utf-8")
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._rows, [
            {"Amount": "3", "Label": "C", "Amount copy": "3"},
        ])
        self.assertEqual(
            self.table_for(reopened, source_id)["column_types"]["Amount copy"],
            "whole_number",
        )

        self.source_path.write_text("Amount,Label\n004,D\n005,E\n", encoding="utf-8")
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [
            {"Amount": "4", "Label": "D", "Amount copy": "4"},
            {"Amount": "5", "Label": "E", "Amount copy": "5"},
        ])
        self.assertEqual(
            self.table_for(reopened, source_id)["column_types"]["Amount copy"],
            "whole_number",
        )


if __name__ == "__main__":
    unittest.main()
