"""Acceptance checks for Remove Alternate Rows through project lifecycle."""

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


class RemoveAlternateRowsLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "ordered.csv"
        self.source_path.write_text(
            "id,value\n"
            "1,a\n2,b\n3,c\n4,d\n5,e\n6,f\n7,g\n8,h\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def test_remove_alternate_rows_previews_saves_and_refreshes(self) -> None:
        controller = self.controller("settings.ini")
        raw = parse_file(self.source_path)
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("remove_alternate_rows")
        )
        dialog.alternate_first_row_edit.setText("2")
        dialog.alternate_remove_count_edit.setText("2")
        dialog.alternate_keep_count_edit.setText("2")
        dialog._add_step()
        expected = [
            {"id": "1", "value": "a"},
            {"id": "4", "value": "d"},
            {"id": "5", "value": "e"},
            {"id": "8", "value": "h"},
        ]
        self.assertEqual(dialog._preview_candidate.rows, expected)
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "remove-alternate-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "id,value\n10,j\n11,k\n12,l\n13,m\n14,n\n15,o\n16,p\n17,q\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._rows, [
            {"id": "10", "value": "j"},
            {"id": "13", "value": "m"},
            {"id": "14", "value": "n"},
            {"id": "17", "value": "q"},
        ])

        self.source_path.write_text(
            "id,value\n20,t\n21,u\n22,v\n23,w\n24,x\n", encoding="utf-8"
        )
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [
            {"id": "20", "value": "t"},
            {"id": "23", "value": "w"},
            {"id": "24", "value": "x"},
        ])


if __name__ == "__main__":
    unittest.main()
