"""Acceptance checks for first-delimiter split through the saved source lifecycle."""

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


class SplitColumnLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "locations.csv"
        self.source_path.write_text(
            "Id,Code\nA,dept-001\nB,west-lake\nC,unknown\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def test_first_delimiter_split_saves_reopens_and_refreshes(self) -> None:
        controller = self.controller("settings.ini")
        raw = parse_file(self.source_path)
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("split_column")
        )
        dialog.column_combo.setCurrentText("Code")
        dialog.delimiter_edit.setText("-")
        dialog._add_step()
        self.assertEqual(dialog._preview_candidate.headers, ["Id", "Code.1", "Code.2"])
        self.assertEqual(dialog._preview_candidate.rows, [
            {"Id": "A", "Code.1": "dept", "Code.2": "001"},
            {"Id": "B", "Code.1": "west", "Code.2": "lake"},
            {"Id": "C", "Code.1": "unknown", "Code.2": ""},
        ])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "split-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Id,Code\nA,dept-001\nB,west-lake\nC,unknown\nD,site-003\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._headers, ["Id", "Code.1", "Code.2"])
        self.assertEqual(reopened._rows[-1], {
            "Id": "D", "Code.1": "site", "Code.2": "003",
        })

        self.source_path.write_text(
            "Id,Code\nA,dept-001\nB,west-lake\nC,unknown\nD,site-003\nE,north-hill\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual(reopened._rows[-1], {
            "Id": "E", "Code.1": "north", "Code.2": "hill",
        })


if __name__ == "__main__":
    unittest.main()
