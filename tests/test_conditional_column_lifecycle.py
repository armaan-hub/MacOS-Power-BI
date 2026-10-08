"""Acceptance checks for ordered Conditional Column clauses and replay."""

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


class ConditionalColumnLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "rules.csv"
        self.source_path.write_text(
            "Category,Amount,Threshold,Name,Fallback\n"
            "A,8,5,Alpha,backup-a\n"
            "B,8,5,Beta,backup-b\n"
            "B,4,5,Gamma,backup-g\n"
            "B,4,5,Delta,backup-d\n",
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
        *,
        column: str,
        operator: str,
        test_kind: str,
        test: str,
        output_kind: str,
        output: str,
    ) -> None:
        dialog.conditional_test_column_combo.setCurrentText(column)
        dialog.conditional_operator_combo.setCurrentIndex(
            dialog.conditional_operator_combo.findData(operator)
        )
        dialog.conditional_test_value_kind_combo.setCurrentIndex(
            dialog.conditional_test_value_kind_combo.findData(test_kind)
        )
        if test_kind == "column":
            dialog.conditional_test_value_column_combo.setCurrentText(test)
        else:
            dialog.conditional_test_value_edit.setText(test)
        dialog.conditional_output_kind_combo.setCurrentIndex(
            dialog.conditional_output_kind_combo.findData(output_kind)
        )
        if output_kind == "column":
            dialog.conditional_output_column_combo.setCurrentText(output)
        else:
            dialog.conditional_output_edit.setText(output)
        dialog._add_conditional_clause()

    def configure_dialog(self, raw) -> TransformDataDialog:
        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("conditional_column")
        )
        self.add_clause(
            dialog, column="Category", operator="equals", test_kind="value",
            test="A", output_kind="value", output="Priority A",
        )
        self.add_clause(
            dialog, column="Amount", operator="greater_than_or_equal",
            test_kind="column", test="Threshold",
            output_kind="column", output="Name",
        )
        self.add_clause(
            dialog, column="Name", operator="begins_with", test_kind="value",
            test="G", output_kind="value", output="G-name",
        )
        dialog.conditional_else_kind_combo.setCurrentIndex(
            dialog.conditional_else_kind_combo.findData("column")
        )
        dialog.conditional_else_column_combo.setCurrentText("Fallback")
        dialog.value_edit.setText("Status Label")
        return dialog

    def test_ordered_column_rules_and_else_reopen_and_refresh(self) -> None:
        controller = self.controller("settings.ini")
        raw = parse_file(self.source_path)
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = self.configure_dialog(raw)
        dialog._add_step()
        self.assertEqual([row["Status Label"] for row in dialog._preview_candidate.rows], [
            "Priority A", "Beta", "G-name", "backup-d",
        ])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "conditional-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Category,Amount,Threshold,Name,Fallback\n"
            "A,1,2,Zed,else-a\n"
            "B,3,3,Echo,else-b\n"
            "B,1,2,Gina,else-g\n"
            "B,1,2,Nope,else-d\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual([row["Status Label"] for row in reopened._rows], [
            "Priority A", "Echo", "G-name", "else-d",
        ])

        self.source_path.write_text(
            "Category,Amount,Threshold,Name,Fallback\n"
            "A,0,9,Ally,refresh-a\n"
            "B,9,8,Bea,refresh-b\n"
            "B,1,9,Glad,refresh-g\n"
            "C,1,9,Cold,refresh-c\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual([row["Status Label"] for row in reopened._rows], [
            "Priority A", "Bea", "G-name", "refresh-c",
        ])


if __name__ == "__main__":
    unittest.main()
