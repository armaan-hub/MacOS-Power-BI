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

    def test_text_clean_custom_formula_previews_saves_reopens_and_refreshes(self) -> None:
        self.source_path.write_text(
            "Customer,Revenue\n\"A" + chr(1) + "B" + chr(0x7F)
            + chr(0x85) + "C" + chr(0x200B) + "D\",1\n,2\n",
            encoding="utf-8",
        )
        controller = self.controller("clean-settings.ini")
        raw = parse_file(self.source_path)
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw, query_name="Customers")
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("add_custom_column")
        )
        dialog.value_edit.setText("Cleaned")
        dialog.custom_expression_edit.setPlainText("Text.Clean([Customer])")
        dialog._add_step()
        self.assertEqual(
            [row["Cleaned"] for row in dialog._preview_candidate.rows],
            ["ABC\u200bD", ""],
        )
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "text-clean-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Customer,Revenue\n\"X" + chr(2) + "Y" + chr(0x86) + "Z\",3\n,4\n",
            encoding="utf-8",
        )
        reopened = self.controller("clean-reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual([row["Cleaned"] for row in reopened._rows], ["XYZ", ""])

        self.source_path.write_text(
            "Customer,Revenue\n\"M" + chr(3) + "N" + chr(0x87) + "O\",5\n,6\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual([row["Cleaned"] for row in reopened._rows], ["MNO", ""])


if __name__ == "__main__":
    unittest.main()
