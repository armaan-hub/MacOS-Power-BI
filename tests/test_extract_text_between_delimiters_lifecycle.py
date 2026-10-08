"""Acceptance checks for Extract Text Between Delimiters."""

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


class ExtractTextBetweenDelimitersLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "bracketed.csv"
        self.source_path.write_text(
            'Value,Id\n"a<one>b<two>c",1\n"x<red>y<blue>z",2\n,3\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    @staticmethod
    def configure_between_step(dialog: TransformDataDialog) -> None:
        if dialog.step_list.currentRow() >= 0:
            dialog._add_or_start_new_step()
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("extract_text_between_delimiters")
        )
        dialog.column_combo.setCurrentText("Value")
        dialog.delimiter_edit.setText("<")
        dialog.value_edit.setText("0")
        dialog.end_delimiter_edit.setText(">")
        dialog.end_occurrence_edit.setText("1")

    def test_between_selected_occurrences_replays_and_preserves_empty(self) -> None:
        raw = parse_file(self.source_path)
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        self.configure_between_step(dialog)
        dialog._add_step()
        self.assertEqual(dialog._preview_candidate.rows, [
            {"Value": "one>b<two", "Id": "1"},
            {"Value": "red>y<blue", "Id": "2"},
            {"Value": "", "Id": "3"},
        ])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "extract-between-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            'Value,Id\n"p<green>q<gold>r",4\n', encoding="utf-8"
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._rows, [{"Value": "green>q<gold", "Id": "4"}])

        self.source_path.write_text(
            'Value,Id\n"m<first>n<last>o",5\n', encoding="utf-8"
        )
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [{"Value": "first>n<last", "Id": "5"}])

    def test_between_reports_missing_start_and_end_occurrences(self) -> None:
        for value, expected_error in (
            ("no start", "start delimiter occurrence"),
            ("start<no end", "end delimiter occurrence"),
        ):
            with self.subTest(value=value):
                raw = ImportCandidate("csv", ["Value"], [{"Value": value}], {}, [])
                dialog = TransformDataDialog(raw)
                self.configure_between_step(dialog)

                dialog._add_step()

                self.assertEqual(dialog._steps, [])
                self.assertIn(expected_error, dialog.error_label.text())
                dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
