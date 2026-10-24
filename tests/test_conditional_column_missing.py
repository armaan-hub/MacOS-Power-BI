"""Critic I11: a conditional-column step whose columns no longer exist is never silently rebound."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.conditional_column_dialog import ConditionalColumnDialog


def broken_step() -> dict:
    return {
        "op": "conditional_column",
        "name": "Flag",
        "clauses": [
            {"column": "Gone", "operator": "equals", "test_value": "1",
             "test_value_kind": "value", "output": "yes", "output_kind": "value"},
            {"column": "A", "operator": "equals", "test_value": "Missing",
             "test_value_kind": "column", "output": "Gone", "output_kind": "column"},
        ],
        "else_value": "Missing",
        "else_kind": "column",
    }


class MissingColumnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def dialog(self, step: dict | None = None) -> ConditionalColumnDialog:
        dialog = ConditionalColumnDialog(["A", "B"], initial_step=step or broken_step())
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_original_names_are_kept_not_rebound_to_the_first_column(self) -> None:
        step = self.dialog().step()
        self.assertEqual(step["clauses"][0]["column"], "Gone")
        self.assertEqual(step["clauses"][1]["test_value"], "Missing")
        self.assertEqual(step["clauses"][1]["output"], "Gone")
        self.assertEqual(step["else_value"], "Missing")

    def test_missing_columns_are_listed_and_shown(self) -> None:
        dialog = self.dialog()
        self.assertEqual(dialog.missing_columns(), ["Gone", "Missing"])
        dialog.show()
        self.app.processEvents()
        self.assertTrue(dialog.error_label.isVisible())
        self.assertIn("Gone", dialog.error_label.text())
        self.assertIn("Missing", dialog.error_label.text())
        self.assertIn("(missing)", dialog.clause_rows[0].column_combo.currentText())

    def test_ok_is_refused_until_every_missing_column_is_repicked(self) -> None:
        calls: list[dict] = []
        dialog = ConditionalColumnDialog(
            ["A", "B"], initial_step=broken_step(),
            validate_callback=lambda step: calls.append(step) or None)
        self.addCleanup(dialog.deleteLater)
        self.assertFalse(dialog.ok_button.isEnabled())
        dialog._accept_step()
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(calls, [], "the step must not even be validated while columns are missing")

        row0, row1 = dialog.clause_rows
        row0.column_combo.setCurrentText("B")
        self.assertEqual(dialog.missing_columns(), ["Missing", "Gone"])  # clause 2 output too
        self.assertFalse(dialog.ok_button.isEnabled())
        row1.test_value.column_combo.setCurrentText("A")
        row1.output.column_combo.setCurrentText("B")
        dialog.else_output.column_combo.setCurrentText("A")
        self.assertEqual(dialog.missing_columns(), [])
        self.assertTrue(dialog.ok_button.isEnabled())
        dialog._accept_step()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        step = dialog.step()
        self.assertEqual(step["clauses"][0]["column"], "B")
        self.assertEqual(step["clauses"][1]["test_value"], "A")
        self.assertEqual(step["else_value"], "A")

    def test_a_step_with_existing_columns_is_unchanged(self) -> None:
        step = {
            "op": "conditional_column", "name": "Flag",
            "clauses": [{"column": "B", "operator": "equals", "test_value": "1",
                         "test_value_kind": "value", "output": "A", "output_kind": "column"}],
            "else_value": "no", "else_kind": "value",
        }
        dialog = self.dialog(step)
        self.assertEqual(dialog.missing_columns(), [])
        self.assertTrue(dialog.ok_button.isEnabled())
        self.assertEqual(dialog.step(), step)
        self.assertFalse(dialog.error_label.isVisible())


if __name__ == "__main__":
    unittest.main()
