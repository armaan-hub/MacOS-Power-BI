"""Tests for Applied Steps right-click context menu (Task 183)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import TransformDataDialog


def _source() -> ImportCandidate:
    return ImportCandidate(
        "inline",
        ["Region", "Amount", "Day"],
        [
            {"Region": "East", "Amount": "10", "Day": "2026-01-01"},
            {"Region": "West", "Amount": "20", "Day": "2026-01-02"},
            {"Region": "East", "Amount": "30", "Day": "2026-01-03"},
            {"Region": "North", "Amount": "40", "Day": "2026-01-04"},
            {"Region": "South", "Amount": "50", "Day": "2026-01-05"},
        ],
        {},
        [],
    )


class StepMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["step menu tests"])

    def make(self, steps=None) -> TransformDataDialog:
        dialog = TransformDataDialog(_source(), steps=steps, query_name="Sales")
        self.addCleanup(dialog.deleteLater)
        return dialog

    def make_with_three_steps(self) -> TransformDataDialog:
        steps = [
            {"op": "sort_rows", "column": "Amount", "direction": "asc"},
            {"op": "filter_rows", "column": "Region", "operator": "equals", "value": "East"},
            {"op": "remove_column", "column": "Day"},
        ]
        return self.make(steps=steps)

    def test_step_menu_items_order_and_tooltips(self) -> None:
        dialog = self.make_with_three_steps()
        menu, actions = dialog._build_step_context_menu(1)
        action_texts = [a.text() for a in menu.actions() if not a.isSeparator()]

        expected_order = [
            "Edit Settings…",
            "Rename…",
            "Delete",
            "Delete Until End",
            "Insert Step After",
            "Move before",
            "Move after",
            "Extract Previous",
            "View Native Query",
            "Properties...",
        ]
        self.assertEqual(action_texts, expected_order)

        self.assertEqual(actions["Edit Settings…"].objectName(), "editAppliedStepSettingsAction")
        self.assertTrue(actions["Edit Settings…"].isEnabled())

        for disabled_name in ["Insert Step After", "Extract Previous", "View Native Query"]:
            action = actions[disabled_name]
            self.assertFalse(action.isEnabled())
            self.assertEqual(action.toolTip(), "Not supported yet")

    def test_delete_step_2_leaves_2_steps(self) -> None:
        dialog = self.make_with_three_steps()
        self.assertEqual(len(dialog._steps), 3)

        dialog.step_list.setCurrentRow(1)
        menu, actions = dialog._build_step_context_menu(1)
        # Action "Delete" does what self.remove_button.click() does
        actions["Delete"].trigger() if actions["Delete"].isCheckable() else dialog._remove_step()
        self.assertEqual(len(dialog._steps), 2)
        self.assertEqual([s["op"] for s in dialog._steps], ["sort_rows", "remove_column"])

    def test_delete_until_end_yes_leaves_only_step_1(self) -> None:
        dialog = self.make_with_three_steps()
        self.assertEqual(len(dialog._steps), 3)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            dialog._delete_steps_until_end(1)

        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(dialog._steps[0]["op"], "sort_rows")

    def test_delete_until_end_no_keeps_all_steps(self) -> None:
        dialog = self.make_with_three_steps()
        self.assertEqual(len(dialog._steps), 3)

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            dialog._delete_steps_until_end(1)

        self.assertEqual(len(dialog._steps), 3)

    def test_move_before_disabled_on_step_1_move_after_disabled_on_last(self) -> None:
        dialog = self.make_with_three_steps()

        # Step 0 (step 1)
        _, actions_first = dialog._build_step_context_menu(0)
        self.assertFalse(actions_first["Move before"].isEnabled())
        self.assertTrue(actions_first["Move after"].isEnabled())

        # Step 2 (last step)
        _, actions_last = dialog._build_step_context_menu(2)
        self.assertTrue(actions_last["Move before"].isEnabled())
        self.assertFalse(actions_last["Move after"].isEnabled())

    def test_move_after_on_step_1_swaps_order(self) -> None:
        dialog = self.make_with_three_steps()
        self.assertEqual(
            [s["op"] for s in dialog._steps],
            ["sort_rows", "filter_rows", "remove_column"],
        )

        dialog.step_list.setCurrentRow(0)
        dialog._move_step(1)

        self.assertEqual(
            [s["op"] for s in dialog._steps],
            ["filter_rows", "sort_rows", "remove_column"],
        )
