"""Acceptance checks for Keep Duplicates by Selected Columns."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.local_table_dialogs import TransformDataDialog


class KeepDuplicatesSelectedColumnsLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "records.csv"
        self.source_path.write_text(
            "Key,Amount\nA,001\nA,2\na,3\nB,4\nA,5\n", encoding="utf-8"
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

    def test_keep_duplicates_uses_selected_keys_and_replays_in_order(self) -> None:
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
            dialog.operation_combo.findData("keep_duplicates")
        )
        dialog.keep_columns_list.item(1).setCheckState(Qt.CheckState.Unchecked)
        dialog._add_step()
        self.assertEqual(dialog._steps[1]["columns"], ["Key"])
        self.assertEqual(dialog._preview_candidate.rows, [
            {"Key": "A", "Amount": "1"},
            {"Key": "A", "Amount": "2"},
            {"Key": "A", "Amount": "5"},
        ])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        self.assertEqual(
            self.table_for(controller, source_id)["column_types"]["Amount"],
            "whole_number",
        )
        dialog.deleteLater()

        project_path = self.root / "keep-duplicates-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Key,Amount\nx,10\nx,11\ny,12\n", encoding="utf-8"
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._rows, [
            {"Key": "x", "Amount": "10"},
            {"Key": "x", "Amount": "11"},
        ])

        self.source_path.write_text(
            "Key,Amount\nm,20\nm,21\nn,22\nm,23\n", encoding="utf-8"
        )
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [
            {"Key": "m", "Amount": "20"},
            {"Key": "m", "Amount": "21"},
            {"Key": "m", "Amount": "23"},
        ])


if __name__ == "__main__":
    unittest.main()
