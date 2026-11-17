"""Tests for Task 202: Remove Errors on selected columns like Power BI."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelection, QItemSelectionModel
from PySide6.QtWidgets import QApplication

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import TransformDataDialog
from analytics_studio.power_query_m import steps_to_m_script
from analytics_studio.power_query_values import PowerQueryCellError
from analytics_studio.transformations import apply_transformations


def _sample_source() -> ImportCandidate:
    # 4 rows:
    # Row 0: Region "East", Amount "10" (no errors)
    # Row 1: Region error, Amount "20"
    # Row 2: Region "West", Amount error
    # Row 3: Region error, Amount error
    err_region = PowerQueryCellError("DataFormat.Error", "bad region", "bad_r", "text", row=2)
    err_amount = PowerQueryCellError("DataFormat.Error", "bad amount", "bad_a", "whole_number", row=3)
    return ImportCandidate(
        "inline",
        ["Region", "Amount"],
        [
            {"Region": "East", "Amount": "10"},
            {"Region": err_region, "Amount": "20"},
            {"Region": "West", "Amount": err_amount},
            {"Region": err_region, "Amount": err_amount},
        ],
        {},
        [],
    )


class RemoveErrorsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["remove errors tests"])

    def make(self, source: ImportCandidate | None = None, steps=None) -> TransformDataDialog:
        dialog = TransformDataDialog(source or _sample_source(), steps=steps, query_name="Sales")
        self.addCleanup(dialog.deleteLater)
        return dialog

    def _select_columns(self, dialog: TransformDataDialog, column_names: list[str]) -> None:
        headers = dialog._selected_preview_candidate().headers
        model = dialog.preview.model()
        selection_model = dialog.preview.selectionModel()
        selection_model.clearSelection()
        for i, name in enumerate(column_names):
            if name in headers:
                col_idx = headers.index(name)
                if i == 0:
                    dialog.preview.selectColumn(col_idx)
                else:
                    selection_model.select(
                        QItemSelection(
                            model.index(0, col_idx),
                            model.index(model.rowCount() - 1, col_idx),
                        ),
                        QItemSelectionModel.SelectionFlag.Select,
                    )

    def test_ribbon_button_text_and_tooltip(self) -> None:
        dialog = self.make()
        # Task 207 (2026-11-17): commands Power BI keeps in dropdowns are reachable through ribbon_menu_actions.
        action = dialog.ribbon_menu_actions.get("remove_rows_with_errors")
        self.assertIsNotNone(action)
        self.assertEqual(action.text(), "Remove Errors")

    def test_ribbon_remove_errors_with_region_selected(self) -> None:
        source = _sample_source()
        dialog = self.make(source)
        dialog.show()
        self.app.processEvents()

        self._select_columns(dialog, ["Region"])
        self.assertEqual(dialog._selected_preview_columns(), ["Region"])

        # Task 207 (2026-11-17): commands Power BI keeps in dropdowns are reachable through ribbon_menu_actions.
        dialog.ribbon_menu_actions["remove_rows_with_errors"].trigger()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        expected_step = {"op": "remove_rows_with_errors", "columns": ["Region"]}
        self.assertEqual(dialog._steps[-1], expected_step)

        # Step name check
        self.assertEqual(dialog.step_list.item(0).text(), "Removed Errors")

        # Preview equals apply_transformations(source, steps)
        expected_candidate = apply_transformations(source, dialog._steps)
        preview_candidate = dialog._selected_preview_candidate()
        self.assertEqual(preview_candidate.headers, expected_candidate.headers)
        self.assertEqual(preview_candidate.rows, expected_candidate.rows)

        # Only rows with error in Region are removed (rows 1 and 3 are dropped; row 2 with error only in Amount stays)
        self.assertEqual(len(preview_candidate.rows), 2)
        self.assertEqual(preview_candidate.rows[0]["Region"], "East")
        self.assertEqual(preview_candidate.rows[1]["Region"], "West")

        # Generated M contains Table.RemoveRowsWithErrors and {"Region"}
        m_code = steps_to_m_script(dialog._steps, "Sales")
        self.assertIn("Table.RemoveRowsWithErrors(", m_code)
        self.assertIn('{"Region"}', m_code)

    def test_selection_amount_then_region_keeps_table_order(self) -> None:
        source = _sample_source()
        dialog = self.make(source)
        dialog.show()
        self.app.processEvents()

        # Select Amount then Region
        self._select_columns(dialog, ["Amount", "Region"])
        self.assertEqual(dialog._selected_preview_columns(), ["Region", "Amount"])

        # Task 207 (2026-11-17): commands Power BI keeps in dropdowns are reachable through ribbon_menu_actions.
        dialog.ribbon_menu_actions["remove_rows_with_errors"].trigger()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(
            dialog._steps[-1],
            {"op": "remove_rows_with_errors", "columns": ["Region", "Amount"]},
        )

    def test_no_selection_keeps_unchanged_parameterless_step(self) -> None:
        source = _sample_source()
        dialog = self.make(source)
        dialog.show()
        self.app.processEvents()

        dialog.preview.selectionModel().clearSelection()
        dialog.preview.setCurrentIndex(dialog.preview.model().index(-1, -1))
        self.assertEqual(dialog._selected_preview_columns(), [])

        # Task 207 (2026-11-17): commands Power BI keeps in dropdowns are reachable through ribbon_menu_actions.
        dialog.ribbon_menu_actions["remove_rows_with_errors"].trigger()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(dialog._steps[-1], {"op": "remove_rows_with_errors"})
        self.assertEqual(dialog.step_list.item(0).text(), "Removed Errors")

        # Dropping all errors leaves only row 0
        preview_candidate = dialog._selected_preview_candidate()
        self.assertEqual(len(preview_candidate.rows), 1)
        self.assertEqual(preview_candidate.rows[0]["Region"], "East")

    def test_right_click_menu_remove_errors_is_enabled_and_adds_step(self) -> None:
        source = _sample_source()
        dialog = self.make(source)
        dialog.show()
        self.app.processEvents()

        menu = dialog._build_header_context_menu(0)  # column 0 is Region
        action = next((a for a in menu.actions() if a.text() == "Remove Errors"), None)
        self.assertIsNotNone(action)
        self.assertTrue(action.isEnabled())

        action.trigger()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(
            dialog._steps[-1],
            {"op": "remove_rows_with_errors", "columns": ["Region"]},
        )
        self.assertEqual(dialog.step_list.item(0).text(), "Removed Errors")


if __name__ == "__main__":
    unittest.main()
