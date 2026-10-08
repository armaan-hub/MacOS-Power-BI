"""Acceptance checks for advanced multi-column filters."""

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
from analytics_studio.transformations import MAX_FILTER_CLAUSES


class AdvancedMultiColumnFiltersLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "sales.csv"
        self.source_path.write_text(
            "Region,Amount,Status,Id\n"
            "East,100,Open,1\nEast,50,Closed,2\nWest,100,Closed,3\n"
            "North,80,Open,4\nEast,80,Closed,5\nSouth,120,Open,6\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    @staticmethod
    def add_clause(
        dialog: TransformDataDialog,
        column: str,
        operator: str,
        value: str,
        join: str,
    ) -> None:
        dialog.column_combo.setCurrentText(column)
        dialog.option_combo.setCurrentIndex(dialog.option_combo.findData(operator))
        dialog.value_edit.setText(value)
        dialog.advanced_filter_join_combo.setCurrentIndex(
            dialog.advanced_filter_join_combo.findData(join)
        )
        dialog._add_advanced_filter_clause()

    def test_and_binds_before_or_across_columns_and_replays(self) -> None:
        raw = parse_file(self.source_path)
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("filter_rows_advanced")
        )
        self.add_clause(dialog, "Region", "equals", "East", "and")
        self.add_clause(dialog, "Amount", "greater_than_or_equal", "80", "and")
        self.add_clause(dialog, "Status", "equals", "Open", "or")
        dialog._add_step()
        self.assertEqual([row["Id"] for row in dialog._preview_candidate.rows], [
            "1", "4", "5", "6",
        ])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "advanced-filter-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Region,Amount,Status,Id\n"
            "East,50,Closed,7\nEast,80,Closed,8\nWest,120,Open,9\n"
            "West,75,Closed,10\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual([row["Id"] for row in reopened._rows], ["8", "9"])

        self.source_path.write_text(
            "Region,Amount,Status,Id\n"
            "North,80,Open,11\nEast,70,Closed,12\nSouth,90,Closed,13\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual([row["Id"] for row in reopened._rows], ["11"])

    def test_ui_enforces_the_64_clause_limit(self) -> None:
        raw = parse_file(self.source_path)
        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("filter_rows_advanced")
        )
        for index in range(MAX_FILTER_CLAUSES):
            self.add_clause(
                dialog,
                "Region",
                "equals",
                "East",
                "and" if index == 0 else "or",
            )
        self.assertEqual(len(dialog._filter_clauses), 64)

        self.add_clause(dialog, "Region", "equals", "East", "or")

        self.assertEqual(len(dialog._filter_clauses), 64)
        self.assertIn("at most 64 clauses", dialog.error_label.text())
        dialog._add_step()
        self.assertEqual([row["Id"] for row in dialog._preview_candidate.rows], [
            "1", "2", "5",
        ])
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
