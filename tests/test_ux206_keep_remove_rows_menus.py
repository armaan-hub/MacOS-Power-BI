"""Tests for Task 206: Home > Keep Rows / Remove Rows dropdowns and Keep Errors, like Power BI."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelection, QItemSelectionModel
from PySide6.QtWidgets import QApplication

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import TransformDataDialog
from analytics_studio.power_query_m import parse_m_script, steps_to_m_script
from analytics_studio.power_query_values import PowerQueryCellError
from analytics_studio.transformations import (
    TransformationError,
    apply_transformations,
    validate_steps,
)


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


class KeepRemoveRowsMenusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["keep remove rows menus tests"])

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

    def test_keep_rows_menu_items_order_and_actions(self) -> None:
        dialog = self.make()
        button = dialog.ribbon_command_buttons["keep_top_rows"]
        menu = button.menu()
        self.assertIsNotNone(menu)

        actions = menu.actions()
        expected = [
            ("Keep Top Rows", "keepRowsKeepTopRowsAction"),
            ("Keep Bottom Rows", "keepRowsKeepBottomRowsAction"),
            ("Keep Range of Rows", "keepRowsKeepRangeRowsAction"),
            ("Keep Duplicates", "keepRowsKeepDuplicatesAction"),
            ("Keep Errors", "keepRowsKeepErrorsAction"),
        ]
        self.assertEqual(len(actions), len(expected))
        for action, (exp_text, exp_obj_name) in zip(actions, expected):
            self.assertEqual(action.text(), exp_text)
            self.assertEqual(action.objectName(), exp_obj_name)
            self.assertTrue(action.isEnabled())

    def test_remove_rows_menu_items_order_and_actions(self) -> None:
        dialog = self.make()
        button = dialog.ribbon_command_buttons["remove_top_rows"]
        menu = button.menu()
        self.assertIsNotNone(menu)

        actions = menu.actions()
        expected = [
            ("Remove Top Rows", "removeRowsRemoveTopRowsAction"),
            ("Remove Bottom Rows", "removeRowsRemoveBottomRowsAction"),
            ("Remove Alternate Rows", "removeRowsRemoveAlternateRowsAction"),
            ("Remove Duplicates", "removeRowsRemoveDuplicatesAction"),
            ("Remove Blank Rows", "removeRowsRemoveBlankRowsAction"),
            ("Remove Errors", "removeRowsRemoveErrorsAction"),
        ]
        self.assertEqual(len(actions), len(expected))
        for action, (exp_text, exp_obj_name) in zip(actions, expected):
            self.assertEqual(action.text(), exp_text)
            self.assertEqual(action.objectName(), exp_obj_name)
            self.assertTrue(action.isEnabled())

    def test_keep_rows_main_click_opens_keep_top_rows(self) -> None:
        dialog = self.make()
        dialog.show()
        self.app.processEvents()

        button = dialog.ribbon_command_buttons["keep_top_rows"]
        button.click()
        self.app.processEvents()

        sub = dialog._operation_dialog
        self.assertIsNotNone(sub)
        self.assertTrue(sub.isVisible())
        self.assertEqual(sub.windowTitle(), "Keep Top Rows")
        sub.reject()

    def test_remove_rows_main_click_opens_remove_top_rows(self) -> None:
        dialog = self.make()
        dialog.show()
        self.app.processEvents()

        button = dialog.ribbon_command_buttons["remove_top_rows"]
        button.click()
        self.app.processEvents()

        sub = dialog._operation_dialog
        self.assertIsNotNone(sub)
        self.assertTrue(sub.isVisible())
        self.assertEqual(sub.windowTitle(), "Remove Top Rows")
        sub.reject()

    def test_remove_rows_menu_entries_run_ribbon_operations(self) -> None:
        dialog = self.make()
        dialog.show()
        self.app.processEvents()

        # Remove Duplicates menu action
        remove_button = dialog.ribbon_command_buttons["remove_top_rows"]
        menu = remove_button.menu()
        action_map = {a.objectName(): a for a in menu.actions()}

        self._select_columns(dialog, ["Region"])
        action_map["removeRowsRemoveDuplicatesAction"].trigger()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(dialog._steps[-1]["op"], "remove_duplicates")

        # Remove Blank Rows
        action_map["removeRowsRemoveBlankRowsAction"].trigger()
        self.app.processEvents()
        self.assertEqual(len(dialog._steps), 2)
        self.assertEqual(dialog._steps[-1]["op"], "remove_blank_rows")

        # Remove Errors with Region selected
        self._select_columns(dialog, ["Region"])
        action_map["removeRowsRemoveErrorsAction"].trigger()
        self.app.processEvents()
        self.assertEqual(len(dialog._steps), 3)
        self.assertEqual(
            dialog._steps[-1],
            {"op": "remove_rows_with_errors", "columns": ["Region"]},
        )

    def test_keep_errors_with_column_selected(self) -> None:
        source = _sample_source()
        dialog = self.make(source)
        dialog.show()
        self.app.processEvents()

        # Select Region
        self._select_columns(dialog, ["Region"])
        self.assertEqual(dialog._selected_preview_columns(), ["Region"])

        keep_button = dialog.ribbon_command_buttons["keep_top_rows"]
        menu = keep_button.menu()
        keep_errors_action = next(a for a in menu.actions() if a.objectName() == "keepRowsKeepErrorsAction")

        keep_errors_action.trigger()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        expected_step = {"op": "keep_rows_with_errors", "columns": ["Region"]}
        self.assertEqual(dialog._steps[-1], expected_step)

        # Step name check in step_list
        self.assertEqual(dialog.step_list.item(0).text(), "Kept Errors")

        # Preview equals apply_transformations(source, steps)
        expected_candidate = apply_transformations(source, dialog._steps)
        preview_candidate = dialog._selected_preview_candidate()
        self.assertEqual(preview_candidate.headers, expected_candidate.headers)
        self.assertEqual(preview_candidate.rows, expected_candidate.rows)

        # In source:
        # Row 0: Region "East" (no error) -> dropped
        # Row 1: Region error -> KEPT
        # Row 2: Region "West" (error in Amount only) -> dropped because only Region was checked
        # Row 3: Region error -> KEPT
        self.assertEqual(len(preview_candidate.rows), 2)
        self.assertTrue(isinstance(preview_candidate.rows[0]["Region"], PowerQueryCellError))
        self.assertTrue(isinstance(preview_candidate.rows[1]["Region"], PowerQueryCellError))

        # Generated M contains Table.SelectRowsWithErrors and {"Region"}
        m_code = steps_to_m_script(dialog._steps, "Sales")
        self.assertIn("Table.SelectRowsWithErrors(", m_code)
        self.assertIn('{"Region"}', m_code)

        # Roundtrip via parse_m_script
        roundtrip_steps = parse_m_script(m_code, "Sales")
        self.assertEqual(roundtrip_steps, dialog._steps)

    def test_keep_errors_without_column_selected(self) -> None:
        source = _sample_source()
        dialog = self.make(source)
        dialog.show()
        self.app.processEvents()

        dialog.preview.selectionModel().clearSelection()
        dialog.preview.setCurrentIndex(dialog.preview.model().index(-1, -1))
        self.assertEqual(dialog._selected_preview_columns(), [])

        keep_button = dialog.ribbon_command_buttons["keep_top_rows"]
        menu = keep_button.menu()
        keep_errors_action = next(a for a in menu.actions() if a.objectName() == "keepRowsKeepErrorsAction")

        keep_errors_action.trigger()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        expected_step = {"op": "keep_rows_with_errors"}
        self.assertEqual(dialog._steps[-1], expected_step)
        self.assertEqual(dialog.step_list.item(0).text(), "Kept Errors")

        # In source:
        # Row 0: no error -> dropped
        # Row 1: error in Region -> kept
        # Row 2: error in Amount -> kept
        # Row 3: error in both -> kept
        preview_candidate = dialog._selected_preview_candidate()
        self.assertEqual(len(preview_candidate.rows), 3)

        # M code emission and roundtrip
        m_code = steps_to_m_script(dialog._steps, "Sales")
        self.assertIn("Table.SelectRowsWithErrors(", m_code)
        self.assertNotIn('{"Region"}', m_code)
        roundtrip_steps = parse_m_script(m_code, "Sales")
        self.assertEqual(roundtrip_steps, dialog._steps)

    def test_engine_missing_column_raises_error(self) -> None:
        source = _sample_source()
        step = {"op": "keep_rows_with_errors", "columns": ["NonExistentColumn"]}
        validate_steps([step])

        with self.assertRaises(TransformationError) as ctx:
            apply_transformations(source, [step])
        self.assertIn("Error-check column 'NonExistentColumn' does not exist.", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
