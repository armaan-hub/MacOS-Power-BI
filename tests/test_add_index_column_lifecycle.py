"""Acceptance checks for Add Index Column through project lifecycle."""

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


class AddIndexColumnLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "records.csv"
        self.source_path.write_text(
            "name\nA\nB\nC\n", encoding="utf-8"
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

    def test_add_index_column_previews_saves_and_refreshes(self) -> None:
        controller = self.controller("settings.ini")
        raw = parse_file(self.source_path)
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("add_index_column")
        )
        dialog.value_edit.setText("Sequence")
        dialog.index_start_edit.setText("100")
        dialog.index_increment_edit.setText("-10")
        dialog._add_step()
        self.assertEqual(dialog._preview_candidate.rows, [
            {"name": "A", "Sequence": "100"},
            {"name": "B", "Sequence": "90"},
            {"name": "C", "Sequence": "80"},
        ])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        self.assertEqual(
            self.table_for(controller, source_id)["column_types"]["Sequence"],
            "whole_number",
        )
        dialog.deleteLater()

        project_path = self.root / "index-column-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text("name\nD\nE\n", encoding="utf-8")
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._rows, [
            {"name": "D", "Sequence": "100"},
            {"name": "E", "Sequence": "90"},
        ])
        self.assertEqual(
            self.table_for(reopened, source_id)["column_types"]["Sequence"],
            "whole_number",
        )

        self.source_path.write_text("name\nF\n", encoding="utf-8")
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [{"name": "F", "Sequence": "100"}])


if __name__ == "__main__":
    unittest.main()
