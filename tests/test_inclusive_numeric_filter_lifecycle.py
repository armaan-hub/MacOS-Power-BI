"""Acceptance checks for inclusive numeric filter operators."""

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


class InclusiveNumericFilterLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "amounts.csv"
        self.source_path.write_text(
            "Amount,Id\n-1,a\n0,b\n9.99,c\n10,d\n10.0,e\n100,f\n,g\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def filter_preview(self, operator: str, threshold: str) -> list[str]:
        raw = parse_file(self.source_path)
        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("filter_rows")
        )
        dialog.column_combo.setCurrentText("Amount")
        dialog.option_combo.setCurrentIndex(
            dialog.option_combo.findData(operator)
        )
        dialog.value_edit.setText(threshold)
        dialog._add_step()
        result = [row["Id"] for row in dialog._preview_candidate.rows]
        dialog.deleteLater()
        return result

    def test_inclusive_comparisons_keep_equal_values_and_skip_blanks(self) -> None:
        self.assertEqual(
            self.filter_preview("greater_than_or_equal", "10"),
            ["d", "e", "f"],
        )
        self.assertEqual(
            self.filter_preview("less_than_or_equal", "10"),
            ["a", "b", "c", "d", "e"],
        )

    def test_inclusive_filter_reports_invalid_nonempty_numbers(self) -> None:
        raw = ImportCandidate(
            "csv", ["Amount"], [{"Amount": "not a number"}], {}, []
        )
        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("filter_rows")
        )
        dialog.column_combo.setCurrentText("Amount")
        dialog.option_combo.setCurrentIndex(
            dialog.option_combo.findData("greater_than_or_equal")
        )
        dialog.value_edit.setText("10")

        dialog._add_step()

        self.assertEqual(dialog._steps, [])
        self.assertIn("row 1", dialog.error_label.text())
        self.assertIn("Amount", dialog.error_label.text())
        dialog.deleteLater()

    def test_inclusive_filter_saves_reopens_and_refreshes(self) -> None:
        raw = parse_file(self.source_path)
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("filter_rows")
        )
        dialog.column_combo.setCurrentText("Amount")
        dialog.option_combo.setCurrentIndex(
            dialog.option_combo.findData("greater_than_or_equal")
        )
        dialog.value_edit.setText("10")
        dialog._add_step()
        self.assertEqual([row["Id"] for row in dialog._preview_candidate.rows], [
            "d", "e", "f",
        ])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "inclusive-filter-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Amount,Id\n5,a\n10,b\n15,c\n", encoding="utf-8"
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual([row["Id"] for row in reopened._rows], ["b", "c"])

        self.source_path.write_text(
            "Amount,Id\n10,d\n9.99,e\n20,f\n", encoding="utf-8"
        )
        reopened.refresh_source()
        self.assertEqual([row["Id"] for row in reopened._rows], ["d", "f"])


if __name__ == "__main__":
    unittest.main()
