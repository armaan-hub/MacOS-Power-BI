"""Task 186: the Power Query ribbon Data Type dropdown lists Power BI's full Change Type list."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMenu, QToolButton

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import TransformDataDialog

_EXPECTED_LABELS = [
    "Decimal Number",
    "Fixed decimal number",
    "Whole Number",
    "Percentage",
    "Date/Time",
    "Date",
    "Time",
    "Date/Time/Timezone",
    "Duration",
    "Text",
    "True/False",
    "Binary",
    "Using Locale...",
]


def _source() -> ImportCandidate:
    return ImportCandidate(
        "inline",
        ["Region", "Amount", "Day"],
        [
            {"Region": "East", "Amount": "10", "Day": "2026-01-01"},
            {"Region": "West", "Amount": "20", "Day": "2026-01-02"},
            {"Region": "East", "Amount": "30", "Day": "2026-01-03"},
        ],
        {},
        [],
    )


def _menu_actions(menu: QMenu) -> list:
    return [a for a in menu.actions() if not a.isSeparator() and a.text()]


class RibbonDataTypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["ux186 ribbon data type"])

    def make(self) -> TransformDataDialog:
        dialog = TransformDataDialog(_source(), query_name="Sales")
        self.addCleanup(dialog.deleteLater)
        return dialog

    def ribbon_menu(self, dialog: TransformDataDialog) -> QMenu:
        button = dialog.findChild(QToolButton, "powerQueryDataTypeButton")
        self.assertIsNotNone(button)
        menu = button.menu()
        self.assertIsNotNone(menu)
        return menu

    def test_ribbon_data_type_menu_lists_power_bi_items_in_order(self) -> None:
        dialog = self.make()
        actions = _menu_actions(self.ribbon_menu(dialog))
        self.assertEqual([a.text() for a in actions], _EXPECTED_LABELS)

    def test_ribbon_true_false_adds_boolean_convert_type_step(self) -> None:
        dialog = self.make()
        dialog.preview.selectColumn(1)
        action = next(
            a for a in _menu_actions(self.ribbon_menu(dialog)) if a.text() == "True/False"
        )
        self.assertTrue(action.isEnabled())
        action.trigger()

        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(dialog._steps[0]["op"], "convert_type")
        self.assertEqual(dialog._steps[0]["column"], "Amount")
        self.assertEqual(dialog._steps[0]["type"], "boolean")

    def test_ribbon_fixed_decimal_and_percentage_match_header_menu(self) -> None:
        dialog = self.make()
        header_menu = dialog._build_change_type_menu(1)
        header = {a.text(): a for a in _menu_actions(header_menu)}
        ribbon = {a.text(): a for a in _menu_actions(self.ribbon_menu(dialog))}

        for label, expected_type in (
            ("Fixed decimal number", "fixed_decimal"),
            ("Percentage", "percentage"),
        ):
            with self.subTest(label=label):
                self.assertEqual(ribbon[label].isEnabled(), header[label].isEnabled())
                if ribbon[label].isEnabled():
                    dialog.preview.selectColumn(1)
                    steps_before = len(dialog._steps)
                    ribbon[label].trigger()
                    self.assertEqual(len(dialog._steps), steps_before + 1)
                    self.assertEqual(dialog._steps[-1]["op"], "convert_type")
                    self.assertEqual(dialog._steps[-1]["type"], expected_type)
                    dialog._steps.pop()
                    dialog._render_steps()

    def test_header_change_type_texts_are_unchanged(self) -> None:
        dialog = self.make()
        menu = dialog._build_change_type_menu(1)
        self.assertEqual([a.text() for a in _menu_actions(menu)], _EXPECTED_LABELS)


if __name__ == "__main__":
    unittest.main()
