"""Acceptance checks for removing fully blank rows through refresh."""

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


class RemoveBlankRowsLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "records.csv"
        self.source_path.write_text(
            "id,value\n1,one\n,\n, \n2,two\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def test_remove_blank_rows_preserves_whitespace_and_replays(self) -> None:
        controller = self.controller("settings.ini")
        raw = parse_file(self.source_path)
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("remove_blank_rows")
        )
        dialog._add_step()
        self.assertEqual(dialog._preview_candidate.rows, [
            {"id": "1", "value": "one"},
            {"id": "", "value": " "},
            {"id": "2", "value": "two"},
        ])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "remove-blank-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "id,value\n3,three\n,\n4,four\n", encoding="utf-8"
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._rows, [
            {"id": "3", "value": "three"},
            {"id": "4", "value": "four"},
        ])

        self.source_path.write_text(
            "id,value\n5,five\n,,\n6,six\n", encoding="utf-8"
        )
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [
            {"id": "5", "value": "five"},
            {"id": "6", "value": "six"},
        ])


if __name__ == "__main__":
    unittest.main()
