"""A ribbon command with a middle applied step selected asks "Insert step" and inserts after it.

Power BI shows an Insert Step prompt (Insert / Cancel); Insert puts the new step directly after the
selected step, Cancel changes nothing.  The last step (or no step) selected adds without a prompt.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QToolButton

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import TransformDataDialog


def make_source() -> ImportCandidate:
    headers = ["Column1", "Column2", "Column3", "Amount", "Region"]
    rows = [
        {"Column1": f"a{i}", "Column2": f"b{i}", "Column3": f"c{i}", "Amount": str(i),
         "Region": "East" if i % 2 else "West"}
        for i in range(1, 5)
    ]
    return ImportCandidate("inline", headers, rows, {}, [])


class RibbonMiddleStepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def open_with_two_steps(self) -> TransformDataDialog:
        dialog = TransformDataDialog(make_source(), query_name="Sheet_1")
        dialog.resize(1300, 800)
        dialog.show()
        self.app.processEvents()
        self.addCleanup(dialog.deleteLater)
        for column in ("Column2", "Column3"):
            self.pick(dialog, column)
            dialog.ribbon_command_buttons["remove_column"].click()
            self.app.processEvents()
        self.assertEqual(len(dialog._steps), 2)
        return dialog

    def pick(self, dialog: TransformDataDialog, column: str) -> None:
        model = dialog.preview.model()  # the grid shows the selected step's output
        headers = [str(model.headerData(c, Qt.Orientation.Horizontal))
                   for c in range(model.columnCount())]
        index = headers.index(column)
        dialog.preview.selectColumn(index)
        dialog.preview.setCurrentIndex(dialog.preview.model().index(0, index))

    def click_with_prompt(self, action, answer: str) -> dict:
        """Run ``action`` and answer the modal Insert-step prompt with the button ``answer``."""
        seen: dict = {"count": 0}

        def respond() -> None:
            box = self.app.activeModalWidget()
            if not (isinstance(box, QDialog) and box.objectName() == "powerQueryInsertStepPrompt"):
                QTimer.singleShot(10, respond)
                return
            seen["count"] += 1
            seen["title"] = box.windowTitle()
            seen["text"] = box.findChild(QLabel, "powerQueryInsertStepMessage").text()
            buttons = box.findChildren(QPushButton)
            seen["buttons"] = [b.text().replace("&", "") for b in buttons]
            seen["default"] = next((b.text() for b in buttons if b.isDefault()), None)
            next(b for b in buttons if b.text().replace("&", "") == answer).click()

        QTimer.singleShot(0, respond)
        action()
        self.app.processEvents()
        return seen

    def no_prompt(self, action) -> None:
        shown: list[bool] = []

        def watch() -> None:
            box = self.app.activeModalWidget()
            if isinstance(box, QDialog):
                shown.append(True)
                box.reject()

        timer = QTimer()
        timer.timeout.connect(watch)
        timer.start(5)
        action()
        self.app.processEvents()
        timer.stop()
        self.assertEqual(shown, [], "no Insert prompt is expected here")

    def columns(self, dialog: TransformDataDialog) -> list[str]:
        return [step.get("column") for step in dialog._steps]

    def select_middle(self, dialog: TransformDataDialog, column: str) -> None:
        dialog.step_list.setCurrentRow(0)
        self.app.processEvents()
        self.pick(dialog, column)

    def test_insert_prompt_text_and_cancel_changes_nothing(self) -> None:
        dialog = self.open_with_two_steps()
        before_steps = [dict(step) for step in dialog._steps]
        before_meta = [dict(item) for item in dialog._step_metadata]
        self.select_middle(dialog, "Column3")  # still there after step 1, gone after step 2
        seen = self.click_with_prompt(
            dialog.ribbon_command_buttons["remove_column"].click, "Cancel"
        )
        self.assertEqual(seen["count"], 1)
        self.assertEqual(seen["title"], "Insert step")
        self.assertIn("1 more step", seen["text"])
        self.assertEqual(sorted(seen["buttons"]), ["Cancel", "Insert"])
        self.assertEqual(seen["default"], "Cancel")
        self.assertEqual(dialog._steps, before_steps)
        self.assertEqual(dialog._step_metadata, before_meta)
        self.assertEqual(dialog.step_list.currentRow(), 0, "the selection stays on the middle step")
        self.assertIsNone(dialog._insert_at)

    def test_insert_puts_the_step_right_after_the_selected_one_with_aligned_metadata(self) -> None:
        dialog = self.open_with_two_steps()
        dialog._step_metadata[0] = {"name": "Dropped Two"}
        dialog._step_metadata[1] = {"name": "Dropped Three"}
        self.select_middle(dialog, "Region")
        seen = self.click_with_prompt(
            dialog.ribbon_command_buttons["remove_column"].click, "Insert"
        )
        self.assertEqual(seen["count"], 1)
        self.assertEqual(self.columns(dialog), ["Column2", "Region", "Column3"])
        self.assertEqual(len(dialog._step_metadata), 3)
        self.assertEqual(dialog._step_metadata[0], {"name": "Dropped Two"})
        self.assertTrue(dialog._step_metadata[1].get("name"))
        self.assertEqual(dialog._step_metadata[2], {"name": "Dropped Three"})
        self.assertEqual(dialog.step_list.currentRow(), 1, "the new step is selected")
        self.assertEqual(dialog._preview_candidate.headers, ["Column1", "Amount"])
        self.assertIsNone(dialog._insert_at)

    def test_insert_that_breaks_a_later_step_is_rejected_unchanged(self) -> None:
        dialog = self.open_with_two_steps()
        before_steps = [dict(step) for step in dialog._steps]
        before_meta = [dict(item) for item in dialog._step_metadata]
        before_headers = list(dialog._preview_candidate.headers)
        self.select_middle(dialog, "Column3")  # removing it first leaves step 2 with nothing to remove
        self.click_with_prompt(dialog.ribbon_command_buttons["remove_column"].click, "Insert")
        self.assertEqual(dialog._steps, before_steps)
        self.assertEqual(dialog._step_metadata, before_meta)
        self.assertEqual(dialog._preview_candidate.headers, before_headers)
        self.assertEqual(dialog.step_list.count(), 2)
        self.assertTrue(dialog.error_label.text(), "the error is shown")
        self.assertEqual(dialog.step_list.currentRow(), 0, "the selection is put back")
        self.assertIsNone(dialog._insert_at)

    def test_sort_and_data_type_commands_also_insert_after_the_selected_step(self) -> None:
        dialog = self.open_with_two_steps()
        sort_button = dialog.findChild(QToolButton, "powerQuerySortAscendingButton")
        self.assertIsNotNone(sort_button)
        self.select_middle(dialog, "Amount")
        self.click_with_prompt(sort_button.click, "Insert")
        self.assertEqual([step["op"] for step in dialog._steps],
                         ["remove_column", "sort_rows", "remove_column"])
        self.assertEqual(len(dialog._step_metadata), 3)
        self.select_middle(dialog, "Amount")
        self.click_with_prompt(lambda: dialog._select_ribbon_data_type("whole_number"), "Insert")
        self.assertEqual([step["op"] for step in dialog._steps],
                         ["remove_column", "convert_type", "sort_rows", "remove_column"])
        self.assertEqual(dialog._steps[1]["column"], "Amount")
        self.assertEqual(len(dialog._step_metadata), 4)

    def test_several_selected_columns_are_inserted_in_order_after_the_selected_step(self) -> None:
        dialog = self.open_with_two_steps()
        dialog.step_list.setCurrentRow(0)
        self.app.processEvents()
        headers = list(dialog._selected_preview_candidate().headers)
        dialog.preview.clearSelection()
        dialog.preview.setSelectionMode(dialog.preview.SelectionMode.MultiSelection)
        for column in ("Amount", "Region"):
            dialog.preview.selectColumn(headers.index(column))
        self.assertEqual(dialog._selected_preview_columns(), ["Amount", "Region"])
        self.click_with_prompt(lambda: dialog._select_ribbon_data_type("text"), "Insert")
        self.assertEqual(self.columns(dialog), ["Column2", "Amount", "Region", "Column3"])
        self.assertEqual(len(dialog._step_metadata), 4)
        self.assertIsNone(dialog._insert_at)

    def test_dialog_command_inserts_after_the_selected_step_and_cancel_leaks_nothing(self) -> None:
        dialog = self.open_with_two_steps()
        self.select_middle(dialog, "Amount")
        self.click_with_prompt(dialog.ribbon_command_buttons["keep_top_rows"].click, "Insert")
        sub = dialog._operation_dialog
        self.assertIsNotNone(sub, "Keep Rows opens its settings dialog")
        self.assertEqual(len(dialog._steps), 2, "nothing is added until OK")
        sub.cancel_button.click()
        self.app.processEvents()
        self.assertIsNone(dialog._operation_dialog)
        self.assertIsNone(dialog._insert_at, "a cancelled dialog leaves no insert position behind")
        self.assertEqual(len(dialog._steps), 2)
        self.assertEqual(dialog.step_list.currentRow(), 0)

        self.select_middle(dialog, "Amount")
        self.click_with_prompt(dialog.ribbon_command_buttons["keep_top_rows"].click, "Insert")
        sub = dialog._operation_dialog
        sub.ok_button.click()
        self.app.processEvents()
        self.assertEqual([step["op"] for step in dialog._steps],
                         ["remove_column", "keep_top_rows", "remove_column"])
        self.assertEqual(len(dialog._step_metadata), 3)
        self.assertIsNone(dialog._insert_at)

    def test_conditional_column_dialog_keeps_the_insert_point_until_it_closes(self) -> None:
        dialog = self.open_with_two_steps()
        self.select_middle(dialog, "Amount")
        self.click_with_prompt(dialog.ribbon_command_buttons["conditional_column"].click, "Insert")
        self.assertEqual(dialog._insert_at, 1)
        dialog._conditional_dialog.reject()
        self.app.processEvents()
        self.assertIsNone(dialog._insert_at)
        self.assertEqual(dialog.step_list.currentRow(), 0)
        self.assertEqual(len(dialog._steps), 2)

    def test_no_stale_insert_position_after_a_cancelled_ribbon_prompt(self) -> None:
        dialog = self.open_with_two_steps()
        self.select_middle(dialog, "Amount")
        self.click_with_prompt(dialog.ribbon_command_buttons["keep_top_rows"].click, "Cancel")
        # The form's own Add button afterwards is a plain append at the end.
        dialog.step_list.setCurrentRow(-1)
        self.app.processEvents()
        dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData("remove_column"))
        dialog.column_combo.setCurrentText("Region")
        dialog.add_button.click()
        self.app.processEvents()
        self.assertEqual(self.columns(dialog), ["Column2", "Column3", "Region"])
        self.assertEqual(len(dialog._step_metadata), 3)

    def test_no_stale_insert_position_after_a_cancelled_dialog_then_form_add(self) -> None:
        dialog = self.open_with_two_steps()
        self.select_middle(dialog, "Amount")
        self.click_with_prompt(dialog.ribbon_command_buttons["keep_top_rows"].click, "Insert")
        dialog._operation_dialog.cancel_button.click()
        self.app.processEvents()
        dialog.step_list.setCurrentRow(-1)
        self.app.processEvents()
        dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData("remove_column"))
        dialog.column_combo.setCurrentText("Region")
        dialog.add_button.click()
        self.app.processEvents()
        self.assertEqual(self.columns(dialog), ["Column2", "Column3", "Region"])

    def test_no_prompt_when_the_last_or_no_step_is_selected(self) -> None:
        dialog = self.open_with_two_steps()
        dialog.step_list.setCurrentRow(1)
        self.pick(dialog, "Region")
        self.no_prompt(dialog.ribbon_command_buttons["remove_column"].click)
        dialog.step_list.setCurrentRow(-1)
        self.pick(dialog, "Amount")
        self.no_prompt(dialog.ribbon_command_buttons["remove_column"].click)
        self.assertEqual(self.columns(dialog), ["Column2", "Column3", "Region", "Amount"])
        self.assertEqual(len(dialog._step_metadata), 4)

    def test_detect_data_types_inserts_after_the_selected_step(self) -> None:
        dialog = self.open_with_two_steps()
        dialog.step_list.setCurrentRow(0)
        self.app.processEvents()
        self.click_with_prompt(dialog._detect_data_types, "Insert")
        ops = [step["op"] for step in dialog._steps]
        self.assertGreater(len(ops), 2)
        self.assertEqual(ops[0], "remove_column")
        self.assertEqual(ops[-1], "remove_column")
        self.assertEqual(ops[1:-1], ["convert_type"] * (len(ops) - 2))
        self.assertEqual(len(dialog._step_metadata), len(ops))


if __name__ == "__main__":
    unittest.main()
