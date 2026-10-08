"""Acceptance checks for Remove Bottom Rows through project lifecycle."""

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


class RemoveBottomRowsLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "ordered.csv"
        self.source_path.write_text(
            "id,value\n1,a\n2,b\n3,c\n4,d\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def test_remove_bottom_rows_previews_saves_and_refreshes(self) -> None:
        controller = self.controller("settings.ini")
        raw = parse_file(self.source_path)
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("remove_bottom_rows")
        )
        dialog.value_edit.setText("2")
        dialog._add_step()
        self.assertEqual(dialog._preview_candidate.rows, [
            {"id": "1", "value": "a"},
            {"id": "2", "value": "b"},
        ])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "remove-bottom-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "id,value\n10,j\n11,k\n12,l\n13,m\n", encoding="utf-8"
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._rows, [
            {"id": "10", "value": "j"},
            {"id": "11", "value": "k"},
        ])

        self.source_path.write_text(
            "id,value\n20,t\n21,u\n22,v\n", encoding="utf-8"
        )
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [{"id": "20", "value": "t"}])


if __name__ == "__main__":
    unittest.main()
