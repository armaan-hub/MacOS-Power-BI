"""Acceptance checks for Merge Columns through source lifecycle."""

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


class MergeColumnsLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "people.csv"
        self.source_path.write_text(
            "First,Middle,Last,City\nAda,M.,Lovelace,London\nGrace,,Hopper,New York\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    @staticmethod
    def configure_merge(raw, output_name: str) -> TransformDataDialog:
        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData("merge_columns"))
        for index in range(dialog.keep_columns_list.count()):
            item = dialog.keep_columns_list.item(index)
            item.setCheckState(
                Qt.CheckState.Checked
                if item.text() in {"First", "Middle", "Last"}
                else Qt.CheckState.Unchecked
            )
        dialog.delimiter_edit.setText(" | ")
        dialog.value_edit.setText(output_name)
        return dialog

    def test_merge_columns_order_blanks_and_saved_refresh(self) -> None:
        controller = self.controller("settings.ini")
        raw = parse_file(self.source_path)
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = self.configure_merge(raw, "Full Name")
        dialog._add_step()
        self.assertEqual(dialog._preview_candidate.headers, ["Full Name", "City"])
        self.assertEqual(dialog._preview_candidate.rows, [
            {"Full Name": "Ada | M. | Lovelace", "City": "London"},
            {"Full Name": "Grace |  | Hopper", "City": "New York"},
        ])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        collision = self.configure_merge(raw, "City")
        collision._add_step()
        self.assertIsNone(collision.candidate)
        self.assertIn("already exists", collision.error_label.text())
        collision.deleteLater()

        project_path = self.root / "merged-columns-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "First,Middle,Last,City\nLin,,Torvalds,Helsinki\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._headers, ["Full Name", "City"])
        self.assertEqual(reopened._rows, [
            {"Full Name": "Lin |  | Torvalds", "City": "Helsinki"},
        ])

        self.source_path.write_text(
            "First,Middle,Last,City\nAlan,,Turing,Manchester\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [
            {"Full Name": "Alan |  | Turing", "City": "Manchester"},
        ])


if __name__ == "__main__":
    unittest.main()
