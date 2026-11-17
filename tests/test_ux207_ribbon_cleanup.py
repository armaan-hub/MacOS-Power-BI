"""Tests for Task 207: remove ribbon buttons Power BI does not have."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import TransformDataDialog


def _sample_source() -> ImportCandidate:
    return ImportCandidate(
        "inline",
        ["Region", "Amount"],
        [
            {"Region": "East", "Amount": "10"},
            {"Region": "West", "Amount": "20"},
            {"Region": "", "Amount": ""},
        ],
        {},
        [],
    )


class RibbonCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["ribbon cleanup tests"])

    def make(self, source: ImportCandidate | None = None) -> TransformDataDialog:
        dialog = TransformDataDialog(source or _sample_source(), query_name="Sales")
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_eleven_removed_ops_not_in_ribbon_command_buttons_and_in_ribbon_menu_actions(
        self,
    ) -> None:
        dialog = self.make()
        dialog.show()
        self.app.processEvents()

        removed_ops = [
            "remove_duplicates",
            "keep_duplicates",
            "split_column_by_each_delimiter",
            "split_column_to_rows",
            "split_column_by_positions",
            "keep_bottom_rows",
            "keep_range_rows",
            "remove_bottom_rows",
            "remove_alternate_rows",
            "remove_blank_rows",
            "remove_rows_with_errors",
        ]

        for op in removed_ops:
            self.assertNotIn(op, dialog.ribbon_command_buttons)
            self.assertIn(op, dialog.ribbon_menu_actions)
            self.assertIsNotNone(dialog.ribbon_menu_actions[op])

    def test_triggering_remove_blank_rows_menu_action(self) -> None:
        dialog = self.make()
        dialog.show()
        self.app.processEvents()

        action = dialog.ribbon_menu_actions["remove_blank_rows"]
        action.trigger()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(dialog._steps[-1], {"op": "remove_blank_rows"})
        self.assertEqual(dialog.step_list.item(0).text(), "Removed Blank Rows")

    def test_triggering_keep_bottom_rows_opens_dialog(self) -> None:
        dialog = self.make()
        dialog.show()
        self.app.processEvents()

        action = dialog.ribbon_menu_actions["keep_bottom_rows"]
        action.trigger()
        self.app.processEvents()

        sub = dialog._operation_dialog
        self.assertIsNotNone(sub)
        self.assertEqual(sub.windowTitle(), "Keep Bottom Rows")
        self.assertEqual(dialog.operation_combo.currentData(), "keep_bottom_rows")
        sub.reject()
        self.app.processEvents()

    def test_triggering_split_column_by_positions_opens_dialog(self) -> None:
        dialog = self.make()
        dialog.show()
        self.app.processEvents()

        action = dialog.ribbon_menu_actions["split_column_by_positions"]
        action.trigger()
        self.app.processEvents()

        sub = dialog._operation_dialog
        self.assertIsNotNone(sub)
        self.assertEqual(sub.windowTitle(), "Split Column by Positions")
        self.assertEqual(dialog.operation_combo.currentData(), "split_column_by_positions")
        sub.reject()
        self.app.processEvents()

    def test_filter_rows_and_sort_rows_still_in_ribbon_command_buttons(self) -> None:
        dialog = self.make()
        dialog.show()
        self.app.processEvents()

        self.assertIn("filter_rows", dialog.ribbon_command_buttons)
        self.assertIn("filter_rows_advanced", dialog.ribbon_command_buttons)
        self.assertIn("sort_rows", dialog.ribbon_command_buttons)
        self.assertIn("sort_rows_by_columns", dialog.ribbon_command_buttons)


if __name__ == "__main__":
    unittest.main()
