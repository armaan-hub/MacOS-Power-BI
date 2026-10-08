"""Acceptance checks for Extract Text Before/After Delimiter."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import ImportCandidate, parse_file
from analytics_studio.local_table_dialogs import TransformDataDialog


class ExtractTextDelimiterLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "delimited.csv"
        self.source_path.write_text(
            "Before,After,Id\n\"a|b|c\",\"x|y|z\",1\n,,2\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    @staticmethod
    def add_extract_step(
        dialog: TransformDataDialog, column: str, side: str
    ) -> None:
        if dialog.step_list.currentRow() >= 0:
            dialog._add_or_start_new_step()
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("extract_text_by_delimiter")
        )
        dialog.column_combo.setCurrentText(column)
        dialog.option_combo.setCurrentIndex(dialog.option_combo.findData(side))
        dialog.delimiter_edit.setText("|")
        dialog.value_edit.setText("1")
        dialog._add_step()

    def test_before_and_after_occurrence_replay_and_preserve_empty_values(self) -> None:
        raw = parse_file(self.source_path)
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        self.add_extract_step(dialog, "Before", "before")
        self.add_extract_step(dialog, "After", "after")
        expected = [
            {"Before": "a|b", "After": "z", "Id": "1"},
            {"Before": "", "After": "", "Id": "2"},
        ]
        self.assertEqual(dialog._preview_candidate.rows, expected)
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "extract-delimiter-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Before,After,Id\n\"one|two|three\",\"red|green|blue\",3\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._rows, [
            {"Before": "one|two", "After": "blue", "Id": "3"},
        ])

        self.source_path.write_text(
            "Before,After,Id\n\"left|middle|right\",\"up|mid|down\",4\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [
            {"Before": "left|middle", "After": "down", "Id": "4"},
        ])

    def test_extract_reports_a_missing_requested_delimiter(self) -> None:
        raw = ImportCandidate("csv", ["Value"], [{"Value": "no separator"}], {}, [])
        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("extract_text_by_delimiter")
        )
        dialog.column_combo.setCurrentText("Value")
        dialog.option_combo.setCurrentIndex(dialog.option_combo.findData("after"))
        dialog.delimiter_edit.setText("|")
        dialog.value_edit.setText("1")

        dialog._add_step()

        self.assertEqual(dialog._steps, [])
        self.assertIn("row 1 of column 'Value'", dialog.error_label.text())
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
