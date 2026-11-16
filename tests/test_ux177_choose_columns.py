"""Tests for Task 177: Power BI's Choose Columns dialog."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import (
    ChooseColumnsDialog,
    TransformDataDialog,
)


def _source() -> ImportCandidate:
    return ImportCandidate(
        "inline",
        ["Region", "Amount", "Day"],
        [
            {"Region": "East", "Amount": "10", "Day": "2026-01-01"},
            {"Region": "West", "Amount": "20", "Day": "2026-01-02"},
            {"Region": "East", "Amount": "30", "Day": "2026-01-03"},
            {"Region": "", "Amount": "40", "Day": "2026-01-04"},
            {"Region": None, "Amount": "50", "Day": "2026-01-05"},
        ],
        {},
        [],
    )


class ChooseColumnsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["choose columns tests"])

    def make(self, steps=None) -> TransformDataDialog:
        dialog = TransformDataDialog(_source(), steps=steps, query_name="Sales")
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_choose_columns_dialog_standalone(self) -> None:
        headers = ["Region", "Amount", "Day"]
        dialog = ChooseColumnsDialog(headers)
        self.addCleanup(dialog.deleteLater)

        # Object names
        self.assertEqual(dialog.objectName(), "chooseColumnsDialog")
        self.assertEqual(dialog.search_edit.objectName(), "chooseColumnsSearch")
        self.assertEqual(dialog.column_list.objectName(), "chooseColumnsList")
        self.assertEqual(dialog.sort_button.objectName(), "chooseColumnsSortButton")
        self.assertEqual(dialog.ok_button.objectName(), "chooseColumnsOkButton")

        # Texts and all checked
        items = [dialog.column_list.item(i) for i in range(dialog.column_list.count())]
        self.assertEqual(
            [it.text() for it in items],
            ["(Select All Columns)", "Region", "Amount", "Day"],
        )
        for it in items:
            self.assertEqual(it.checkState(), Qt.CheckState.Checked)
        self.assertTrue(dialog.ok_button.isEnabled())
        self.assertEqual(dialog.columns(), ["Region", "Amount", "Day"])

        # Unchecking "(Select All Columns)" unchecks all and disables OK
        dialog._select_all.setCheckState(Qt.CheckState.Unchecked)
        for it in items:
            self.assertEqual(it.checkState(), Qt.CheckState.Unchecked)
        self.assertFalse(dialog.ok_button.isEnabled())
        self.assertEqual(dialog.columns(), [])

        # Sort A to Z: texts are ["(Select All Columns)", "Amount", "Day", "Region"]
        # Check Region and Day
        region_item = None
        day_item = None
        for i in range(1, dialog.column_list.count()):
            it = dialog.column_list.item(i)
            if it.text() == "Region":
                region_item = it
            elif it.text() == "Day":
                day_item = it

        assert region_item is not None and day_item is not None
        region_item.setCheckState(Qt.CheckState.Checked)
        day_item.setCheckState(Qt.CheckState.Checked)

        dialog._sort_items("a_to_z")
        sorted_texts = [
            dialog.column_list.item(i).text()
            for i in range(dialog.column_list.count())
        ]
        self.assertEqual(
            sorted_texts,
            ["(Select All Columns)", "Amount", "Day", "Region"],
        )
        self.assertEqual(dialog.columns(), ["Region", "Day"])

        # Search "re" leaves only Region visible
        dialog.search_edit.setText("re")
        # Items: 0 is select-all (not hidden by search), 1 is Amount (hidden), 2 is Day (hidden), 3 is Region (visible)
        for i in range(1, dialog.column_list.count()):
            it = dialog.column_list.item(i)
            if it.text() == "Region":
                self.assertFalse(it.isHidden())
            else:
                self.assertTrue(it.isHidden())

    def test_choose_columns_through_editor(self) -> None:
        dialog = self.make()
        button = dialog.ribbon_command_buttons.get("keep_columns")
        self.assertIsNotNone(button)
        self.assertEqual(button.objectName(), "powerQueryCommand_keep_columns")

        created_dialogs: list[ChooseColumnsDialog] = []

        def fake_show(dlg_self: ChooseColumnsDialog) -> None:
            created_dialogs.append(dlg_self)
            # Uncheck Amount
            for i in range(1, dlg_self.column_list.count()):
                it = dlg_self.column_list.item(i)
                if it.text() == "Amount":
                    it.setCheckState(Qt.CheckState.Unchecked)
            dlg_self.accept()

        with patch.object(ChooseColumnsDialog, "show", fake_show):
            button.click()

        self.assertEqual(len(created_dialogs), 1)
        self.assertEqual(
            dialog._steps[-1],
            {"op": "keep_columns", "columns": ["Region", "Day"]},
        )
        preview_headers = dialog._preview_candidate.headers
        self.assertEqual(preview_headers, ["Region", "Day"])
