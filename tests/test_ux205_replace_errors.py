"""Tests for Task 205: Replace Errors like Power BI."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelection, QItemSelectionModel
from PySide6.QtWidgets import QApplication

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import (
    ReplaceErrorsDialog,
    ReplaceValuesDialog,
    TransformDataDialog,
)
from analytics_studio.power_query_m import (
    PowerQueryMScriptError,
    parse_m_script,
    steps_to_m_script,
)
from analytics_studio.power_query_values import PowerQueryCellError
from analytics_studio.transformations import (
    TransformationError,
    apply_transformations,
    validate_steps,
)


def _sample_source() -> ImportCandidate:
    # 4 rows:
    # Row 0: Region "East", Amount 10 (no errors)
    # Row 1: Region error, Amount 20
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


_CONVERT_AMOUNT_STEP = {"op": "convert_type", "column": "Amount", "type": "whole_number"}


class ReplaceErrorsEngineAndMTests(unittest.TestCase):
    def test_engine_replaces_only_errors_in_specified_column(self) -> None:
        source = _sample_source()
        step = {"op": "replace_error_values", "replacements": [["Amount", 10]]}
        result = apply_transformations(source, [step])

        self.assertEqual(result.rows[0]["Amount"], "10")
        self.assertEqual(result.rows[1]["Amount"], "20")
        self.assertEqual(result.rows[2]["Amount"], 10)  # was err_amount
        self.assertEqual(result.rows[3]["Amount"], 10)  # was err_amount

        # Region errors remain untouched
        self.assertEqual(result.rows[0]["Region"], "East")
        self.assertIsInstance(result.rows[1]["Region"], PowerQueryCellError)
        self.assertEqual(result.rows[2]["Region"], "West")
        self.assertIsInstance(result.rows[3]["Region"], PowerQueryCellError)

    def test_engine_missing_or_duplicate_column_raises_transformation_error(self) -> None:
        source = _sample_source()
        with self.assertRaises(TransformationError):
            apply_transformations(
                source,
                [{"op": "replace_error_values", "replacements": [["MissingCol", 10]]}],
            )

        with self.assertRaises(TransformationError):
            validate_steps(
                [{"op": "replace_error_values", "replacements": [["Amount", 10], ["Amount", 20]]}]
            )

    def test_m_round_trip(self) -> None:
        # Number column
        step_num = {"op": "replace_error_values", "replacements": [["Amount", 10]]}
        m_code = steps_to_m_script([step_num], "Sales", initial_column_types={"Amount": "whole_number"})
        self.assertIn("Table.ReplaceErrorValues(", m_code)
        self.assertIn('{{"Amount", 10}}', m_code)
        parsed = parse_m_script(m_code, "Sales")
        self.assertEqual(parsed, [step_num])

        # Text column
        step_text = {"op": "replace_error_values", "replacements": [["Region", "x"]]}
        m_code_text = steps_to_m_script([step_text], "Sales", initial_column_types={"Region": "text"})
        self.assertIn('{{"Region", "x"}}', m_code_text)
        parsed_text = parse_m_script(m_code_text, "Sales")
        self.assertEqual(parsed_text, [step_text])

        # Null replacement
        step_null = {"op": "replace_error_values", "replacements": [["Amount", None]]}
        m_code_null = steps_to_m_script([step_null], "Sales", initial_column_types={"Amount": "whole_number"})
        self.assertIn('{{"Amount", null}}', m_code_null)
        parsed_null = parse_m_script(m_code_null, "Sales")
        self.assertEqual(parsed_null, [step_null])

        # Two columns
        step_two = {
            "op": "replace_error_values",
            "replacements": [["Region", "x"], ["Amount", 10]],
        }
        m_code_two = steps_to_m_script(
            [step_two], "Sales", initial_column_types={"Region": "text", "Amount": "whole_number"}
        )
        self.assertIn('{{"Region", "x"}, {"Amount", 10}}', m_code_two)
        parsed_two = parse_m_script(m_code_two, "Sales")
        self.assertEqual(parsed_two, [step_two])

        # Non-literal or invalid syntax raises PowerQueryMScriptError
        with self.assertRaises(PowerQueryMScriptError):
            parse_m_script(
                'let Source = #table({"A"}, {{1}}), Step = Table.ReplaceErrorValues(Source, {{"A", 1 + 2}}) in Step',
                "Test",
            )


class ReplaceErrorsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["replace errors tests"])

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

    def test_ribbon_dropdown_has_replace_values_and_replace_errors(self) -> None:
        dialog = self.make()
        button = dialog.ribbon_command_buttons.get("replace_value")
        self.assertIsNotNone(button)
        menu = button.menu()
        self.assertIsNotNone(menu)
        actions = menu.actions()
        action_names = [a.objectName() for a in actions]
        self.assertIn("replaceValuesAction", action_names)
        self.assertIn("replaceErrorsAction", action_names)

    def test_main_click_on_replace_values_opens_replace_values_dialog(self) -> None:
        dialog = self.make()
        dialog.show()
        self.app.processEvents()

        button = dialog.ribbon_command_buttons["replace_value"]
        button.click()
        self.app.processEvents()

        sub = dialog._operation_dialog
        self.assertIsInstance(sub, ReplaceValuesDialog)
        self.assertEqual(sub.windowTitle(), "Replace Values")
        sub.reject()
        self.app.processEvents()

    def test_replace_errors_dialog_workflow(self) -> None:
        source = _sample_source()
        dialog = self.make(source, steps=[_CONVERT_AMOUNT_STEP])
        dialog.show()
        self.app.processEvents()

        self._select_columns(dialog, ["Amount"])
        button = dialog.ribbon_command_buttons["replace_value"]
        action_errors = next(a for a in button.menu().actions() if a.objectName() == "replaceErrorsAction")
        action_errors.trigger()
        self.app.processEvents()

        sub = dialog._operation_dialog
        self.assertIsInstance(sub, ReplaceErrorsDialog)
        self.assertEqual(sub.windowTitle(), "Replace Errors")
        self.assertEqual(sub.objectName(), "powerQueryReplaceErrorsDialog")

        # Type invalid value 'abc' for whole number column -> error shown, dialog stays open
        sub.value_edit.setText("abc")
        sub.ok_button.click()
        self.app.processEvents()
        self.assertTrue(sub.error_label.isVisible())
        self.assertIsNotNone(dialog._operation_dialog)

        # Type valid value 10 -> step added
        sub.value_edit.setText("10")
        sub.ok_button.click()
        self.app.processEvents()

        self.assertIsNone(dialog._operation_dialog)
        self.assertEqual(len(dialog._steps), 2)
        expected_step = {"op": "replace_error_values", "replacements": [["Amount", 10]]}
        self.assertEqual(dialog._steps[-1], expected_step)

        # Step name check
        self.assertEqual(dialog.step_list.item(1).text(), "Replaced Errors")

        # Preview equals apply_transformations
        preview = dialog._selected_preview_candidate()
        expected = apply_transformations(source, dialog._steps)
        self.assertEqual(preview.rows, expected.rows)

    def test_cancel_adds_nothing(self) -> None:
        dialog = self.make()
        dialog.show()
        self.app.processEvents()

        self._select_columns(dialog, ["Amount"])
        button = dialog.ribbon_command_buttons["replace_value"]
        action_errors = next(a for a in button.menu().actions() if a.objectName() == "replaceErrorsAction")
        action_errors.trigger()
        self.app.processEvents()

        sub = dialog._operation_dialog
        self.assertIsInstance(sub, ReplaceErrorsDialog)
        sub.cancel_button.click()
        self.app.processEvents()

        self.assertIsNone(dialog._operation_dialog)
        self.assertEqual(len(dialog._steps), 0)

    def test_right_click_menu_opens_replace_errors_dialog(self) -> None:
        dialog = self.make()
        dialog.show()
        self.app.processEvents()

        menu = dialog._build_header_context_menu(1)  # Amount
        action = next((a for a in menu.actions() if a.text() == "Replace Errors..."), None)
        self.assertIsNotNone(action)
        self.assertTrue(action.isEnabled())

        action.trigger()
        self.app.processEvents()

        sub = dialog._operation_dialog
        self.assertIsInstance(sub, ReplaceErrorsDialog)
        self.assertEqual(sub.windowTitle(), "Replace Errors")
        sub.reject()
        self.app.processEvents()

    def test_gear_edit_prefill_and_change(self) -> None:
        source = _sample_source()
        step = {"op": "replace_error_values", "replacements": [["Amount", 10]]}
        dialog = self.make(source, steps=[_CONVERT_AMOUNT_STEP, step])
        dialog.show()
        self.app.processEvents()

        dialog.step_list.setCurrentRow(1)
        self.app.processEvents()

        dialog._edit_selected_step_settings()
        self.app.processEvents()

        sub = dialog._operation_dialog
        self.assertIsInstance(sub, ReplaceErrorsDialog)
        self.assertEqual(sub.value_edit.text(), "10")

        sub.value_edit.setText("99")
        sub.ok_button.click()
        self.app.processEvents()

        self.assertIsNone(dialog._operation_dialog)
        self.assertEqual(
            dialog._steps[1],
            {"op": "replace_error_values", "replacements": [["Amount", 99]]},
        )


if __name__ == "__main__":
    unittest.main()
