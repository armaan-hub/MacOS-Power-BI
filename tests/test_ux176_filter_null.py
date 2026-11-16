"""Task 176: Power Query filter lists (null) separately from empty text."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

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
            {"Region": "", "Amount": "40", "Day": "2026-01-04"},
            {"Region": None, "Amount": "50", "Day": "2026-01-05"},
        ],
        {},
        [],
    )


class NullFilterColumnMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["null filter tests"])

    def make(self) -> TransformDataDialog:
        dialog = TransformDataDialog(_source(), query_name="Sales")
        self.addCleanup(dialog.deleteLater)
        return dialog

    def _item(self, panel, text: str):
        for index in range(panel.value_list.count()):
            item = panel.value_list.item(index)
            if item.text() == text:
                return item
        raise AssertionError(f"no list item labelled {text!r}")

    def test_unchecking_null_keeps_empty_text_rows(self) -> None:
        dialog = self.make()
        info = dialog._build_preview_column_menu(0)
        self._item(info.panel, "(null)").setCheckState(Qt.CheckState.Unchecked)
        info.panel.ok_button.click()
        self.assertEqual(dialog._steps[-1], {
            "op": "filter_rows", "column": "Region",
            "operator": "is_not_null", "value": "",
        })
        self.assertEqual([row["Region"] for row in dialog._preview_candidate.rows],
                         ["East", "West", "East", ""])

    def test_unchecking_null_and_blank_keeps_only_text_rows(self) -> None:
        dialog = self.make()
        info = dialog._build_preview_column_menu(0)
        self._item(info.panel, "(null)").setCheckState(Qt.CheckState.Unchecked)
        self._item(info.panel, "(Blank)").setCheckState(Qt.CheckState.Unchecked)
        info.panel.ok_button.click()
        self.assertEqual([row["Region"] for row in dialog._preview_candidate.rows],
                         ["East", "West", "East"])

    def test_null_only_column_shows_null_and_no_blank(self) -> None:
        dialog = TransformDataDialog(
            ImportCandidate("inline", ["Note"], [{"Note": None}, {"Note": None}], {}, []),
            query_name="Notes",
        )
        self.addCleanup(dialog.deleteLater)
        panel = dialog._build_preview_column_menu(0).panel
        labels = [panel.value_list.item(i).text()
                  for i in range(panel.value_list.count())]
        self.assertEqual(labels, ["(Select All)", "(null)"])


if __name__ == "__main__":
    unittest.main()
