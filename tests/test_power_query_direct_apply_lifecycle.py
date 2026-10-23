"""Power Query ribbon commands apply directly, or open a modal dialog, like Power BI."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QSettings, Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.local_table_dialogs import TransformDataDialog


class PowerQueryDirectApplyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "data.csv"
        self.source_path.write_text(
            "Column1,Column2,Column3\n1,a,x\n5,b,y\n7,c,z\n",
            encoding="utf-8",
        )
        self.raw = parse_file(self.source_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str = "settings.ini") -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def open_dialog(self) -> TransformDataDialog:
        dialog = TransformDataDialog(self.raw)
        dialog.resize(1300, 800)
        dialog.show()
        self.app.processEvents()
        self.addCleanup(dialog.deleteLater)
        return dialog

    @staticmethod
    def select_column(dialog: TransformDataDialog, column: int) -> None:
        dialog.preview.selectColumn(column)
        dialog.preview.setCurrentIndex(dialog.preview.model().index(0, column))

    @staticmethod
    def step_names(dialog: TransformDataDialog) -> list[str]:
        return [dialog.step_list.item(i).text() for i in range(dialog.step_list.count())]

    # ---- direct apply -------------------------------------------------

    def test_remove_columns_applies_immediately_with_power_bi_step_name(self) -> None:
        dialog = self.open_dialog()
        self.select_column(dialog, 1)
        dialog.ribbon_command_buttons["remove_column"].click()
        self.app.processEvents()

        self.assertEqual(self.step_names(dialog), ["Removed Columns"])
        self.assertEqual(dialog._preview_candidate.headers, ["Column1", "Column3"])
        self.assertIn("Table.RemoveColumns", dialog.formula_bar.text())
        self.assertTrue(dialog.operation_settings_panel.isHidden())

        self.select_column(dialog, 1)
        dialog.ribbon_command_buttons["remove_column"].click()
        self.app.processEvents()
        self.assertEqual(self.step_names(dialog), ["Removed Columns", "Removed Columns1"])
        self.assertEqual(dialog._preview_candidate.headers, ["Column1"])
        self.assertTrue(dialog.operation_settings_panel.isHidden())

    def test_remove_columns_without_selection_applies_nothing(self) -> None:
        dialog = self.open_dialog()
        dialog.preview.setCurrentIndex(dialog.preview.model().index(-1, -1))
        dialog.preview.clearSelection()
        dialog.ribbon_command_buttons["remove_column"].click()
        self.app.processEvents()
        self.assertEqual(self.step_names(dialog), [])
        self.assertTrue(dialog.operation_settings_panel.isHidden())

    def test_parameterless_selection_commands_apply_without_a_form(self) -> None:
        dialog = self.open_dialog()
        self.select_column(dialog, 1)
        dialog.ribbon_command_buttons["uppercase_text"].click()
        self.app.processEvents()
        self.assertEqual(self.step_names(dialog), ["Uppercased Text"])
        self.assertEqual(
            [row["Column2"] for row in dialog._preview_candidate.rows], ["A", "B", "C"]
        )
        self.select_column(dialog, 0)
        dialog.ribbon_command_buttons["duplicate_column"].click()
        self.app.processEvents()
        self.assertEqual(self.step_names(dialog)[-1], "Duplicated Column")
        self.assertEqual(
            dialog._preview_candidate.headers,
            ["Column1", "Column2", "Column3", "Column1 - Copy"],
        )
        self.select_column(dialog, 2)
        dialog.ribbon_command_buttons["remove_duplicates"].click()
        self.app.processEvents()
        self.assertEqual(self.step_names(dialog)[-1], "Removed Duplicates")
        self.assertTrue(dialog.operation_settings_panel.isHidden())
        self.assertEqual(len(dialog._steps), 3)

    def test_change_type_from_selected_column_applies_directly(self) -> None:
        dialog = self.open_dialog()
        self.select_column(dialog, 0)
        dialog._select_ribbon_data_type("whole_number")
        self.app.processEvents()
        self.assertEqual(self.step_names(dialog), ["Changed Type"])
        self.assertEqual(dialog._steps[0]["type"], "whole_number")
        self.assertTrue(dialog.operation_settings_panel.isHidden())

    # ---- parameter dialogs -------------------------------------------

    def test_keep_top_rows_opens_a_modal_dialog_ok_applies_cancel_discards(self) -> None:
        dialog = self.open_dialog()
        self.select_column(dialog, 0)
        dialog.ribbon_command_buttons["keep_top_rows"].click()
        self.app.processEvents()

        sub = dialog._operation_dialog
        self.assertIsNotNone(sub)
        self.assertTrue(sub.isVisible())
        self.assertTrue(sub.isModal())
        self.assertEqual(sub.windowTitle(), "Keep Top Rows")
        self.assertEqual(self.step_names(dialog), [])
        self.assertTrue(dialog.operation_settings_panel.isVisibleTo(sub))
        self.assertTrue(dialog.add_button.isHidden())
        self.assertTrue(dialog.update_button.isHidden())

        dialog.value_edit.setText("2")
        sub.reject()
        self.app.processEvents()
        self.assertEqual(self.step_names(dialog), [])
        self.assertEqual(len(dialog._preview_candidate.rows), 3)
        self.assertIsNone(dialog._operation_dialog)
        self.assertTrue(dialog.operation_settings_panel.isHidden())
        self.assertFalse(dialog.add_button.isHidden())

        dialog.ribbon_command_buttons["keep_top_rows"].click()
        self.app.processEvents()
        sub = dialog._operation_dialog
        dialog.value_edit.setText("2")
        sub.ok_button.click()
        self.app.processEvents()
        self.assertEqual(self.step_names(dialog), ["Kept First Rows"])
        self.assertEqual(len(dialog._preview_candidate.rows), 2)
        self.assertIn("Table.FirstN", dialog.formula_bar.text())
        self.assertIsNone(dialog._operation_dialog)
        self.assertTrue(dialog.operation_settings_panel.isHidden())

    def test_dialog_ok_with_invalid_input_stays_open_with_error(self) -> None:
        dialog = self.open_dialog()
        dialog.ribbon_command_buttons["keep_top_rows"].click()
        self.app.processEvents()
        sub = dialog._operation_dialog
        self.assertIsNotNone(sub)
        dialog.value_edit.setText("")
        sub.ok_button.click()
        self.app.processEvents()
        self.assertIs(dialog._operation_dialog, sub)
        self.assertTrue(sub.isVisible())
        self.assertEqual(self.step_names(dialog), [])
        sub.reject()
        self.app.processEvents()

    def test_parameter_dialogs_show_their_input_fields(self) -> None:
        dialog = self.open_dialog()
        self.select_column(dialog, 1)
        expected = {
            "keep_top_rows": ("value_edit",),
            "remove_top_rows": ("value_edit",),
            "replace_value": ("value_edit", "replacement_edit", "column_combo"),
            "split_column": ("delimiter_edit", "column_combo"),
            "rename_column": ("value_edit", "column_combo"),
            "group_by": ("keep_columns_list",),
            "add_index_column": ("value_edit", "index_start_edit"),
        }
        for operation, fields in expected.items():
            with self.subTest(operation=operation):
                dialog.ribbon_command_buttons[operation].click()
                self.app.processEvents()
                sub = dialog._operation_dialog
                self.assertIsNotNone(sub, operation)
                for field in fields:
                    self.assertTrue(
                        getattr(dialog, field).isVisibleTo(sub), f"{operation}: {field}"
                    )
                sub.reject()
                self.app.processEvents()

    def test_every_parameter_command_opens_dialog_not_bottom_form(self) -> None:
        dialog = self.open_dialog()
        self.select_column(dialog, 1)
        for operation in (
            "split_column", "replace_value", "group_by", "merge_columns",
            "remove_top_rows", "filter_rows", "add_index_column", "rename_column",
        ):
            with self.subTest(operation=operation):
                dialog.ribbon_command_buttons[operation].click()
                self.app.processEvents()
                sub = dialog._operation_dialog
                self.assertIsNotNone(sub, operation)
                self.assertTrue(sub.isVisible())
                sub.reject()
                self.app.processEvents()
                self.assertTrue(dialog.operation_settings_panel.isHidden())
                self.assertEqual(self.step_names(dialog), [])

    # ---- Conditional Column dialog ------------------------------------

    def test_conditional_column_dialog_builds_step_with_else_if(self) -> None:
        dialog = self.open_dialog()
        self.select_column(dialog, 0)
        dialog._select_ribbon_data_type("whole_number")
        self.app.processEvents()
        self.assertEqual(self.step_names(dialog), ["Changed Type"])
        dialog.ribbon_command_buttons["conditional_column"].click()
        self.app.processEvents()
        cond = dialog._conditional_dialog
        self.assertIsNotNone(cond)
        self.assertTrue(cond.isModal())
        self.assertEqual(self.step_names(dialog), ["Changed Type"])  # nothing applied yet
        self.assertTrue(dialog.operation_settings_panel.isHidden())

        cond.name_edit.setText("Size")
        row = cond.clause_rows[0]
        row.column_combo.setCurrentText("Column1")
        row.operator_combo.setCurrentIndex(row.operator_combo.findData("equals"))
        row.test_value.set_value("value", "5")
        row.output.set_value("value", "five")
        cond.add_clause_button.click()
        self.assertEqual(len(cond.clause_rows), 2)
        self.assertEqual(cond.clause_rows[1].prefix_label.text(), "Else If")
        second = cond.clause_rows[1]
        second.column_combo.setCurrentText("Column1")
        second.operator_combo.setCurrentIndex(second.operator_combo.findData("greater_than"))
        second.test_value.set_value("value", "5")
        second.output.set_value("column", "Column2")
        cond.else_output.set_value("value", "small")
        cond.ok_button.click()
        self.app.processEvents()

        self.assertEqual(
            self.step_names(dialog), ["Changed Type", "Added Conditional Column"]
        )
        self.assertEqual(
            [row["Size"] for row in dialog._preview_candidate.rows],
            ["small", "five", "c"],
        )
        formula = dialog.formula_bar.text()
        self.assertTrue(formula.startswith('Table.AddColumn(#"'), formula)
        self.assertIn('"Size", each if [#"Column1"] = 5 then', formula)
        self.assertIn('else if [#"Column1"] > 5 then', formula)
        self.assertIsNone(dialog._conditional_dialog)
        self.assertTrue(dialog.operation_settings_panel.isHidden())

    def test_conditional_column_dialog_remove_clause_cancel_and_validation(self) -> None:
        dialog = self.open_dialog()
        dialog.ribbon_command_buttons["conditional_column"].click()
        self.app.processEvents()
        cond = dialog._conditional_dialog
        cond.add_clause_button.click()
        self.assertEqual(len(cond.clause_rows), 2)
        cond.clause_rows[1].remove_button.click()
        self.assertEqual(len(cond.clause_rows), 1)
        self.assertTrue(cond.clause_rows[0].remove_button.isHidden())
        cond.name_edit.setText("")
        self.assertFalse(cond.ok_button.isEnabled())  # a new column name is required
        cond.name_edit.setText("X")
        self.assertTrue(cond.ok_button.isEnabled())
        cond.cancel_button.click()
        self.app.processEvents()
        self.assertEqual(self.step_names(dialog), [])
        self.assertIsNone(dialog._conditional_dialog)

    def test_editing_conditional_step_reopens_prefilled_dialog(self) -> None:
        dialog = self.open_dialog()
        dialog.ribbon_command_buttons["conditional_column"].click()
        cond = dialog._conditional_dialog
        cond.name_edit.setText("Tier")
        row = cond.clause_rows[0]
        row.column_combo.setCurrentText("Column1")
        row.test_value.set_value("value", "5")
        row.output.set_value("value", "mid")
        cond.else_output.set_value("value", "other")
        cond.ok_button.click()
        self.app.processEvents()
        dialog.step_list.setCurrentRow(0)
        dialog._edit_selected_step_settings()
        self.app.processEvents()
        cond = dialog._conditional_dialog
        self.assertIsNotNone(cond)
        self.assertEqual(cond.name_edit.text(), "Tier")
        self.assertEqual(cond.clause_rows[0].test_value.value(), ("value", "5"))
        cond.else_output.set_value("value", "changed")
        cond.ok_button.click()
        self.app.processEvents()
        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(dialog._steps[0]["else_value"], "changed")

    # ---- Close & Apply / close prompt ---------------------------------

    def test_close_and_apply_loads_the_data_into_the_model(self) -> None:
        controller = self.controller()
        before_sources = len(controller._project["data_sources"])

        def drive(dialog: TransformDataDialog) -> int:
            dialog.show()
            self.app.processEvents()
            self.select_column(dialog, 1)
            dialog.ribbon_command_buttons["remove_column"].click()
            self.app.processEvents()
            QTimer.singleShot(0, dialog.apply_button.click)
            return QDialog.exec(dialog)

        with patch.object(TransformDataDialog, "exec", new=drive):
            self.assertTrue(
                controller.transform_data_dialog(
                    pending_source=(self.raw, {
                        "id": "src-1", "name": "data · CSV", "query_name": "data",
                        "kind": "csv", "path": str(self.source_path),
                        "parser_options": dict(self.raw.options),
                        "transform_steps": [],
                    })
                )
            )
        self.assertTrue(controller.sourceLoaded)
        self.assertEqual(len(controller._project["data_sources"]), before_sources + 1)
        self.assertEqual(controller._rows[0], {"Column1": "1", "Column3": "x"})
        self.assertEqual(len(controller._rows), 3)
        # What the main window's Data view reads:
        self.assertEqual(controller.rowCount, 3)
        self.assertEqual(controller.dataModel.rowCount(), 3)
        self.assertEqual(controller.dataModel.columnCount(), 2)

    def click_message_button(self, label: str) -> None:
        """Click ``label`` on the next visible QMessageBox (polls, so it works inside exec())."""
        timer = QTimer(self.app)
        timer.setInterval(10)

        def poll() -> None:
            boxes = [
                widget for widget in QApplication.topLevelWidgets()
                if isinstance(widget, QMessageBox) and widget.isVisible()
            ]
            if not boxes:
                return
            timer.stop()
            box = boxes[0]
            self.prompt_text = box.text()
            self.prompt_buttons = [button.text() for button in box.buttons()]
            for button in box.buttons():
                if button.text() == label:
                    button.click()
                    return
            box.reject()

        timer.timeout.connect(poll)
        timer.start()
        self.addCleanup(timer.stop)

    def test_close_with_pending_changes_prompts_and_cancel_stays(self) -> None:
        dialog = self.open_dialog()
        self.select_column(dialog, 1)
        dialog.ribbon_command_buttons["remove_column"].click()
        self.app.processEvents()
        self.click_message_button("Cancel")
        dialog.request_close()
        self.app.processEvents()
        self.assertEqual(
            sorted(self.prompt_buttons), ["Apply changes", "Cancel", "Discard changes"]
        )
        self.assertIn("pending changes", self.prompt_text)
        self.assertTrue(dialog.isVisible())
        self.assertEqual(len(dialog._steps), 1)

    def test_close_with_pending_changes_discard_leaves_project_unchanged(self) -> None:
        controller = self.controller()

        def drive(dialog: TransformDataDialog) -> int:
            dialog.show()
            self.app.processEvents()
            self.select_column(dialog, 1)
            dialog.ribbon_command_buttons["remove_column"].click()
            self.app.processEvents()
            self.click_message_button("Discard changes")
            QTimer.singleShot(0, dialog.close)
            return QDialog.exec(dialog)

        with patch.object(TransformDataDialog, "exec", new=drive):
            self.assertFalse(
                controller.transform_data_dialog(
                    pending_source=(self.raw, {
                        "id": "src-2", "name": "data · CSV", "query_name": "data",
                        "kind": "csv", "path": str(self.source_path),
                        "parser_options": dict(self.raw.options),
                        "transform_steps": [],
                    })
                )
            )
        self.assertFalse(controller.sourceLoaded)
        self.assertEqual(controller._project["data_sources"], [])

    def test_close_with_pending_changes_apply_commits(self) -> None:
        controller = self.controller()

        def drive(dialog: TransformDataDialog) -> int:
            dialog.show()
            self.app.processEvents()
            self.select_column(dialog, 1)
            dialog.ribbon_command_buttons["remove_column"].click()
            self.app.processEvents()
            self.click_message_button("Apply changes")
            QTimer.singleShot(0, dialog.close)
            return QDialog.exec(dialog)

        with patch.object(TransformDataDialog, "exec", new=drive):
            self.assertTrue(
                controller.transform_data_dialog(
                    pending_source=(self.raw, {
                        "id": "src-3", "name": "data · CSV", "query_name": "data",
                        "kind": "csv", "path": str(self.source_path),
                        "parser_options": dict(self.raw.options),
                        "transform_steps": [],
                    })
                )
            )
        self.assertTrue(controller.sourceLoaded)
        self.assertEqual(controller._rows[0], {"Column1": "1", "Column3": "x"})

    def test_close_without_pending_changes_is_silent(self) -> None:
        controller = self.controller()
        self.assertTrue(controller._commit_import(self.source_path, self.raw))
        source_id = controller.activeTableId
        self.assertTrue(source_id)
        raw = self.raw
        dialog = TransformDataDialog(raw)
        dialog.show()
        self.app.processEvents()
        with patch.object(QMessageBox, "exec", side_effect=AssertionError("prompted")):
            dialog.close()
        self.app.processEvents()
        self.assertFalse(dialog.isVisible())

    def test_escape_and_file_menu_close_use_the_prompt(self) -> None:
        dialog = self.open_dialog()
        self.select_column(dialog, 1)
        dialog.ribbon_command_buttons["remove_column"].click()
        self.app.processEvents()
        self.click_message_button("Cancel")
        event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(dialog, event)
        self.app.processEvents()
        self.assertIn("Apply changes", self.prompt_buttons)
        self.assertTrue(dialog.isVisible())
        self.click_message_button("Cancel")
        close_action = [a for a in dialog.file_menu.actions() if a.text() == "Close"][0]
        close_action.trigger()
        self.app.processEvents()
        self.assertIn("Apply changes", self.prompt_buttons)
        self.assertTrue(dialog.isVisible())


if __name__ == "__main__":
    unittest.main()
