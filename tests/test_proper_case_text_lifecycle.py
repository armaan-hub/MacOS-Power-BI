"""Acceptance checks for Capitalize Each Word through project lifecycle."""

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
from analytics_studio.transformations import (
    TransformationError,
    column_types_after_steps,
)


class ProperCaseTextLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "labels.csv"
        self.source_path.write_text(
            "Label,Id\nmIxEd cASE,1\no'NEILL,2\n,3\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def test_capitalize_each_word_replays_python_title_casing(self) -> None:
        raw = parse_file(self.source_path)
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("proper_case_text")
        )
        dialog.column_combo.setCurrentText("Label")
        dialog._add_step()
        self.assertEqual(dialog._preview_candidate.rows, [
            {"Label": "Mixed Case", "Id": "1"},
            {"Label": "O'Neill", "Id": "2"},
            {"Label": "", "Id": "3"},
        ])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "proper-case-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Label,Id\nhELLO wORLD,4\n", encoding="utf-8"
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._rows, [{"Label": "Hello World", "Id": "4"}])

        self.source_path.write_text(
            "Label,Id\nfinal TEST,5\n", encoding="utf-8"
        )
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [{"Label": "Final Test", "Id": "5"}])

    def test_capitalize_each_word_requires_text_type_before_conversion(self) -> None:
        with self.assertRaisesRegex(
            TransformationError, "Capitalize Each Word requires a text-typed"
        ):
            column_types_after_steps(
                ["Label"],
                [
                    {"op": "convert_type", "column": "Label", "type": "whole_number"},
                    {"op": "proper_case_text", "column": "Label"},
                ],
                output_headers=["Label"],
            )


if __name__ == "__main__":
    unittest.main()
