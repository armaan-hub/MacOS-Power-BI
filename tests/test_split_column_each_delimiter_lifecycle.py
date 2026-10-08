"""Acceptance checks for Split Column at Every Delimiter into Columns."""

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


class SplitColumnEachDelimiterLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "parts.csv"
        self.source_path.write_text(
            "Code,Amount\nA||C|,10\nx|y,20\n|z||,30\n", encoding="utf-8"
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

    def test_split_each_delimiter_preserves_empty_parts_and_replays(self) -> None:
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
            dialog.operation_combo.findData("split_column_by_each_delimiter")
        )
        dialog.column_combo.setCurrentText("Code")
        dialog.delimiter_edit.setText("|")
        dialog._add_step()
        headers = ["Code.1", "Code.2", "Code.3", "Code.4", "Amount"]
        expected_rows = [
            {"Code.1": "A", "Code.2": "", "Code.3": "C", "Code.4": "", "Amount": "10"},
            {"Code.1": "x", "Code.2": "y", "Code.3": "", "Code.4": "", "Amount": "20"},
            {"Code.1": "", "Code.2": "z", "Code.3": "", "Code.4": "", "Amount": "30"},
        ]
        self.assertEqual(dialog._preview_candidate.headers, headers)
        self.assertEqual(dialog._preview_candidate.rows, expected_rows)
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        self.assertEqual(
            self.table_for(controller, source_id)["column_types"],
            {
                "Code.1": "text",
                "Code.2": "text",
                "Code.3": "text",
                "Code.4": "text",
                "Amount": "whole_number",
            },
        )
        dialog.deleteLater()

        project_path = self.root / "split-every-delimiter-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Code,Amount\nM|N,40\n,50\n", encoding="utf-8"
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._headers, ["Code.1", "Code.2", "Amount"])
        self.assertEqual(reopened._rows, [
            {"Code.1": "M", "Code.2": "N", "Amount": "40"},
            {"Code.1": "", "Code.2": "", "Amount": "50"},
        ])

        self.source_path.write_text(
            "Code,Amount\nP|Q|R,60\n", encoding="utf-8"
        )
        reopened.refresh_source()
        self.assertEqual(reopened._headers, ["Code.1", "Code.2", "Code.3", "Amount"])
        self.assertEqual(reopened._rows, [
            {"Code.1": "P", "Code.2": "Q", "Code.3": "R", "Amount": "60"},
        ])

    def test_split_each_delimiter_requires_a_delimiter(self) -> None:
        raw = parse_file(self.source_path)
        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("split_column_by_each_delimiter")
        )
        dialog.column_combo.setCurrentText("Code")
        dialog.delimiter_edit.clear()

        dialog._add_step()

        self.assertEqual(dialog._steps, [])
        self.assertIn("non-empty delimiter", dialog.error_label.text())
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
