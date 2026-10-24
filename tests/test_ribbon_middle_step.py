"""Critic (minor): a ribbon command with a middle applied step selected must not silently append."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import TransformDataDialog

YES = QMessageBox.StandardButton.Yes
NO = QMessageBox.StandardButton.No


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

    def test_asks_before_adding_at_the_end_and_no_changes_nothing(self) -> None:
        dialog = self.open_with_two_steps()
        dialog.step_list.setCurrentRow(0)
        self.app.processEvents()
        self.pick(dialog, "Column3")  # still there after step 1, gone after step 2
        with patch.object(QMessageBox, "question", return_value=NO) as ask:
            dialog.ribbon_command_buttons["remove_column"].click()
            self.app.processEvents()
        self.assertEqual(ask.call_count, 1)
        self.assertIn("end", ask.call_args.args[2].lower())
        self.assertEqual(len(dialog._steps), 2)
        self.assertEqual(dialog.step_list.currentRow(), 0, "the selection stays on the middle step")

    def test_yes_appends_at_the_end(self) -> None:
        dialog = self.open_with_two_steps()
        dialog.step_list.setCurrentRow(0)
        self.app.processEvents()
        self.pick(dialog, "Region")
        with patch.object(QMessageBox, "question", return_value=YES) as ask:
            dialog.ribbon_command_buttons["remove_column"].click()
            self.app.processEvents()
        self.assertEqual(ask.call_count, 1)
        self.assertEqual([step["column"] for step in dialog._steps],
                         ["Column2", "Column3", "Region"])

    def test_no_prompt_when_the_last_or_no_step_is_selected(self) -> None:
        dialog = self.open_with_two_steps()
        with patch.object(QMessageBox, "question") as ask:
            dialog.step_list.setCurrentRow(1)
            self.pick(dialog, "Region")
            dialog.ribbon_command_buttons["remove_column"].click()
            self.app.processEvents()
            dialog.step_list.setCurrentRow(-1)
            self.pick(dialog, "Amount")
            dialog.ribbon_command_buttons["remove_column"].click()
            self.app.processEvents()
        ask.assert_not_called()
        self.assertEqual(len(dialog._steps), 4)


if __name__ == "__main__":
    unittest.main()
