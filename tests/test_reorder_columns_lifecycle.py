"""Acceptance checks for Reorder Columns through project lifecycle."""

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


class ReorderColumnsLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "records.csv"
        self.source_path.write_text(
            "name,amount,region\nA,10,East\nB,20,West\n", encoding="utf-8"
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

    def test_reorder_columns_previews_saves_and_refreshes(self) -> None:
        controller = self.controller("settings.ini")
        raw = parse_file(self.source_path)
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("convert_type")
        )
        dialog.column_combo.setCurrentText("amount")
        dialog.option_combo.setCurrentIndex(dialog.option_combo.findData("whole_number"))
        dialog._add_step()

        dialog.step_list.setCurrentRow(-1)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("reorder_columns")
        )
        moved = dialog.keep_columns_list.takeItem(2)
        dialog.keep_columns_list.insertItem(0, moved)
        dialog._add_step()
        self.assertEqual(dialog._preview_candidate.headers, [
            "region", "name", "amount",
        ])
        self.assertEqual(dialog._preview_candidate.rows, [
            {"region": "East", "name": "A", "amount": "10"},
            {"region": "West", "name": "B", "amount": "20"},
        ])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        self.assertEqual(
            self.table_for(controller, source_id)["column_types"]["amount"],
            "whole_number",
        )
        dialog.deleteLater()

        project_path = self.root / "reorder-columns-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "name,amount,region\nC,30,North\n", encoding="utf-8"
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._rows, [
            {"region": "North", "name": "C", "amount": "30"},
        ])
        self.assertEqual(
            self.table_for(reopened, source_id)["column_types"]["amount"],
            "whole_number",
        )

        self.source_path.write_text(
            "name,amount,region\nD,40,South\nE,50,Central\n", encoding="utf-8"
        )
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [
            {"region": "South", "name": "D", "amount": "40"},
            {"region": "Central", "name": "E", "amount": "50"},
        ])


if __name__ == "__main__":
    unittest.main()
