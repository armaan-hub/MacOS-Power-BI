"""Acceptance checks for the six text filter operators."""

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


class TextFilterOperatorsLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "labels.csv"
        self.source_path.write_text(
            "Label,Id\n"
            "Alpha beta,1\nalpha beta,2\nalpha,3\nbeta,4\ngamma,5\n"
            "alphabet,6\n,7\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def test_all_text_operators_are_case_sensitive_and_keep_input_order(self) -> None:
        cases = {
            "contains": ["alpha beta", "alpha", "alphabet"],
            "does_not_contain": ["Alpha beta", "beta", "gamma", ""],
            "begins_with": ["alpha beta", "alpha", "alphabet"],
            "does_not_begin_with": ["Alpha beta", "beta", "gamma", ""],
            "ends_with": ["Alpha beta", "alpha beta", "beta"],
            "does_not_end_with": ["alpha", "gamma", "alphabet", ""],
        }
        for operator, expected_labels in cases.items():
            with self.subTest(operator=operator):
                raw = parse_file(self.source_path)
                dialog = TransformDataDialog(raw)
                dialog.operation_combo.setCurrentIndex(
                    dialog.operation_combo.findData("filter_rows")
                )
                dialog.column_combo.setCurrentText("Label")
                dialog.option_combo.setCurrentIndex(
                    dialog.option_combo.findData(operator)
                )
                dialog.value_edit.setText(
                    "beta" if operator in {"ends_with", "does_not_end_with"} else "alpha"
                )
                dialog._add_step()
                self.assertEqual(
                    [row["Label"] for row in dialog._preview_candidate.rows],
                    expected_labels,
                )
                dialog.deleteLater()

    def test_text_filter_saves_reopens_and_refreshes(self) -> None:
        raw = parse_file(self.source_path)
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("filter_rows")
        )
        dialog.column_combo.setCurrentText("Label")
        dialog.option_combo.setCurrentIndex(
            dialog.option_combo.findData("contains")
        )
        dialog.value_edit.setText("alpha")
        dialog._add_step()
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "text-filter-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Label,Id\nalpha new,8\nAlpha excluded,9\n", encoding="utf-8"
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._rows, [{"Label": "alpha new", "Id": "8"}])

        self.source_path.write_text(
            "Label,Id\nnew alpha,10\nother,11\n", encoding="utf-8"
        )
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [{"Label": "new alpha", "Id": "10"}])


if __name__ == "__main__":
    unittest.main()
