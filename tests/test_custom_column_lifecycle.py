"""Acceptance checks for a safe custom formula through source lifecycle."""

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


class CustomColumnLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "products.csv"
        self.source_path.write_text(
            "Product,Units,Revenue\nWidget,2,3.5\npear,1,4\nberry,3,2\n",
            encoding="utf-8",
        )
        self.formula = (
            'if [Units] > 1 then Text.Upper([Product]) & "-" & '
            "Text.From(Number.Round([Revenue] * [Units], 0)) else [Product]"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def test_custom_formula_previews_saves_reopens_and_refreshes(self) -> None:
        controller = self.controller("settings.ini")
        raw = parse_file(self.source_path)
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("add_custom_column")
        )
        dialog.value_edit.setText("Sales label")
        dialog.custom_expression_edit.setPlainText(self.formula)
        dialog._add_step()
        self.assertEqual(dialog._preview_candidate.headers, [
            "Product", "Units", "Revenue", "Sales label",
        ])
        self.assertEqual([row["Sales label"] for row in dialog._preview_candidate.rows], [
            "WIDGET-7", "pear", "BERRY-6",
        ])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "custom-column-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Product,Units,Revenue\nmug,2,1.4\npeach,1,9\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual([row["Sales label"] for row in reopened._rows], [
            "MUG-3", "peach",
        ])

        self.source_path.write_text(
            "Product,Units,Revenue\nbook,3,1.6\ncup,1,4\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual([row["Sales label"] for row in reopened._rows], [
            "BOOK-5", "cup",
        ])


if __name__ == "__main__":
    unittest.main()
