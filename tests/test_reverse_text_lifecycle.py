"""Acceptance checks for Reverse Text through project lifecycle."""

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


class ReverseTextLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "labels.csv"
        self.source_path.write_text(
            "Label,Id\nA🙂e\u0301,1\n,2\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def test_reverse_text_reverses_code_points_and_replays(self) -> None:
        raw = parse_file(self.source_path)
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("reverse_text")
        )
        dialog.column_combo.setCurrentText("Label")
        dialog._add_step()
        self.assertEqual(dialog._preview_candidate.rows, [
            {"Label": "\u0301e🙂A", "Id": "1"},
            {"Label": "", "Id": "2"},
        ])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "reverse-text-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Label,Id\nabc🙂,3\n", encoding="utf-8"
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._rows, [{"Label": "🙂cba", "Id": "3"}])

        self.source_path.write_text(
            "Label,Id\nNorth,4\n", encoding="utf-8"
        )
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [{"Label": "htroN", "Id": "4"}])

    def test_reverse_text_requires_text_type_before_conversion(self) -> None:
        with self.assertRaisesRegex(TransformationError, "Reverse Text requires a text-typed"):
            column_types_after_steps(
                ["Label"],
                [
                    {"op": "convert_type", "column": "Label", "type": "whole_number"},
                    {"op": "reverse_text", "column": "Label"},
                ],
                output_headers=["Label"],
            )


if __name__ == "__main__":
    unittest.main()
