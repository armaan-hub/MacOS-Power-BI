"""Acceptance checks for blank and nonblank row filters."""

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


class BlankNonblankFilterLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "labels.csv"
        self.source_path.write_text(
            "Value,Status,Id\n"
            ",Open,1\n"
            " ,Closed,2\n"
            "alpha,Open,3\n"
            ",Closed,4\n"
            "0,Open,5\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def test_single_column_blank_filters_are_value_free_and_keep_whitespace_nonblank(self) -> None:
        expected_ids = {
            "is_blank": ["1", "4"],
            "is_not_blank": ["2", "3", "5"],
        }
        for operator, expected in expected_ids.items():
            with self.subTest(operator=operator):
                raw = parse_file(self.source_path)
                dialog = TransformDataDialog(raw)
                dialog.operation_combo.setCurrentIndex(
                    dialog.operation_combo.findData("filter_rows")
                )
                dialog.column_combo.setCurrentText("Value")
                dialog.option_combo.setCurrentIndex(
                    dialog.option_combo.findData(operator)
                )
                dialog.value_edit.setText("stale comparison value")

                self.assertFalse(dialog.value_edit.isVisible())
                dialog._add_step()

                self.assertEqual(
                    [row["Id"] for row in dialog._preview_candidate.rows], expected
                )
                self.assertEqual(dialog._steps[-1]["value"], "")
                dialog.deleteLater()

    def test_advanced_blank_clauses_are_value_free(self) -> None:
        expected_ids = {
            "is_blank": ["1", "4"],
            "is_not_blank": ["2", "3", "5"],
        }
        for operator, expected in expected_ids.items():
            with self.subTest(operator=operator):
                raw = parse_file(self.source_path)
                dialog = TransformDataDialog(raw)
                dialog.operation_combo.setCurrentIndex(
                    dialog.operation_combo.findData("filter_rows_advanced")
                )
                dialog.column_combo.setCurrentText("Value")
                dialog.option_combo.setCurrentIndex(
                    dialog.option_combo.findData(operator)
                )
                dialog.value_edit.setText("stale comparison value")
                dialog._add_advanced_filter_clause()

                self.assertEqual(dialog._filter_clauses[0]["value"], "")
                dialog._add_step()

                self.assertEqual(
                    [row["Id"] for row in dialog._preview_candidate.rows], expected
                )
                dialog.deleteLater()

    def test_nonblank_filter_saves_reopens_and_refreshes(self) -> None:
        raw = parse_file(self.source_path)
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("filter_rows")
        )
        dialog.column_combo.setCurrentText("Value")
        dialog.option_combo.setCurrentIndex(
            dialog.option_combo.findData("is_not_blank")
        )
        dialog._add_step()
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "blank-filter-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Value,Status,Id\n,Open,6\n ,Closed,7\nnew,Open,8\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual([row["Id"] for row in reopened._rows], ["7", "8"])

        self.source_path.write_text(
            "Value,Status,Id\n,Open,9\nnext,Closed,10\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual([row["Id"] for row in reopened._rows], ["10"])


if __name__ == "__main__":
    unittest.main()
