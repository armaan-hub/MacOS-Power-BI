"""Tests for Power Query column header right-click menu and type-icon Change Type menu."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelection, QItemSelectionModel, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMenu

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import _NOT_SUPPORTED_YET, TransformDataDialog


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


def _texts(menu: QMenu) -> list[str]:
    return [
        action.text()
        for action in menu.actions()
        if not action.isSeparator() and action.text()
    ]


class HeaderMenusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["header menus tests"])

    def make(self, steps=None) -> TransformDataDialog:
        dialog = TransformDataDialog(_source(), steps=steps, query_name="Sales")
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_context_menu_for_region_lists_items_in_order(self) -> None:
        dialog = self.make()
        menu = dialog._build_header_context_menu(0)
        expected_items = [
            "Copy",
            "Remove",
            "Remove Other Columns",
            "Duplicate Column",
            "Add Column From Examples...",
            "Remove Duplicates",
            "Remove Errors",
            "Change Type",
            "Transform",
            "Replace Values...",
            "Replace Errors...",
            "Group By...",
            "Fill",
            "Unpivot Columns",
            "Unpivot Other Columns",
            "Unpivot Only Selected Columns",
            "Rename...",
            "Move",
            "Drill Down",
            "Add as New Query",
        ]
        self.assertEqual(_texts(menu), expected_items)

    def test_triggering_remove_adds_remove_column_step(self) -> None:
        dialog = self.make()
        menu = dialog._build_header_context_menu(0)
        remove_action = next(a for a in menu.actions() if a.text() == "Remove")
        self.assertTrue(remove_action.isEnabled())
        remove_action.trigger()

        # Added step for Region removal
        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(dialog._steps[0]["op"], "remove_column")
        self.assertEqual(dialog._steps[0]["column"], "Region")

        # Preview headers become ["Amount", "Day"]
        self.assertEqual(dialog._selected_preview_candidate().headers, ["Amount", "Day"])

    def test_triggering_duplicate_column_adds_step_and_header_count_grows(self) -> None:
        dialog = self.make()
        before_count = len(dialog._selected_preview_candidate().headers)
        menu = dialog._build_header_context_menu(0)
        duplicate_action = next(a for a in menu.actions() if a.text() == "Duplicate Column")
        self.assertTrue(duplicate_action.isEnabled())
        duplicate_action.trigger()

        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(dialog._steps[0]["op"], "duplicate_column")
        after_count = len(dialog._selected_preview_candidate().headers)
        self.assertEqual(after_count, before_count + 1)

    def test_change_type_menu_for_amount_lists_types_in_order(self) -> None:
        dialog = self.make()
        menu = dialog._build_change_type_menu(1)
        expected_types = [
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
        self.assertEqual(_texts(menu), expected_types)

        # Triggering "Whole Number" adds a convert-type step for Amount to whole_number
        whole_num_action = next(a for a in menu.actions() if a.text() == "Whole Number")
        self.assertTrue(whole_num_action.isEnabled())
        whole_num_action.trigger()

        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(dialog._steps[0]["op"], "convert_type")
        self.assertEqual(dialog._steps[0]["column"], "Amount")
        self.assertEqual(dialog._steps[0]["type"], "whole_number")

    def test_disabled_items_carry_not_supported_yet_tooltip(self) -> None:
        dialog = self.make()
        ctx_menu = dialog._build_header_context_menu(0)
        disabled_ctx_actions = [a for a in ctx_menu.actions() if not a.isEnabled()]
        self.assertTrue(len(disabled_ctx_actions) > 0)
        for a in disabled_ctx_actions:
            self.assertEqual(a.toolTip(), _NOT_SUPPORTED_YET, f"{a.text()} should have tooltip")

        change_menu = dialog._build_change_type_menu(0)
        disabled_change_actions = [a for a in change_menu.actions() if not a.isEnabled()]
        self.assertTrue(len(disabled_change_actions) > 0)
        for a in disabled_change_actions:
            self.assertEqual(a.toolTip(), _NOT_SUPPORTED_YET, f"{a.text()} should have tooltip")

    def test_type_icon_clicked_emitted_by_glyph_click_and_not_middle_click(self) -> None:
        dialog = self.make()
        header = dialog.preview_header
        dialog.show()

        # Suppress dialogs triggered by menu popups in test
        dialog._show_change_type_menu = lambda idx: None
        dialog._show_preview_column_menu = lambda idx: None

        emitted: list[int] = []
        header.typeIconClicked.connect(emitted.append)

        # Click at glyph position of section 0
        glyph_rect = header._type_icon_rect(0)
        glyph_point = glyph_rect.center()
        QTest.mouseClick(header, Qt.MouseButton.LeftButton, pos=glyph_point)
        self.assertEqual(emitted, [0])

        emitted.clear()
        # Click near section 0's middle
        middle_x = header.sectionViewportPosition(0) + header.sectionSize(0) // 2
        middle_point = QPoint(middle_x, glyph_rect.center().y())
        QTest.mouseClick(header, Qt.MouseButton.LeftButton, pos=middle_point)
        self.assertEqual(emitted, [])

    def test_copy_column_preview_values_to_clipboard(self) -> None:
        dialog = self.make()
        ctx_menu = dialog._build_header_context_menu(0)
        copy_action = next(a for a in ctx_menu.actions() if a.text() == "Copy")
        self.assertTrue(copy_action.isEnabled())
        copy_action.trigger()

        expected_clipboard = "East\nWest\nEast\n\n"
        self.assertEqual(QApplication.clipboard().text(), expected_clipboard)

    def test_remove_removes_all_selected_columns(self) -> None:
        dialog = self.make()
        dialog.preview.selectColumn(0)
        model = dialog.preview.model()
        dialog.preview.selectionModel().select(
            QItemSelection(
                model.index(0, 1), model.index(model.rowCount() - 1, 1)
            ),
            QItemSelectionModel.SelectionFlag.Select,
        )
        self.assertEqual(dialog._selected_preview_columns(), ["Region", "Amount"])

        menu = dialog._build_header_context_menu(1)
        remove_action = next(a for a in menu.actions() if a.text() == "Remove")
        self.assertTrue(remove_action.isEnabled())
        remove_action.trigger()

        self.assertEqual(dialog._selected_preview_candidate().headers, ["Day"])

    def test_change_type_to_current_type_adds_no_step(self) -> None:
        dialog = self.make()
        menu = dialog._build_change_type_menu(0)
        checked = [a for a in menu.actions() if a.isChecked()]
        self.assertEqual(len(checked), 1)
        self.assertTrue(checked[0].isEnabled())
        checked[0].trigger()

        self.assertEqual(dialog._steps, [])

    def test_remove_other_columns_keeps_only_selected(self) -> None:
        dialog = self.make()
        menu = dialog._build_header_context_menu(1)
        keep_action = next(
            a for a in menu.actions() if a.text() == "Remove Other Columns"
        )
        self.assertTrue(keep_action.isEnabled())
        keep_action.trigger()

        self.assertEqual(dialog._selected_preview_candidate().headers, ["Amount"])
        self.assertEqual(
            dialog._steps[-1], {"op": "keep_columns", "columns": ["Amount"]}
        )

    def test_move_to_beginning_reorders_headers(self) -> None:
        dialog = self.make()
        menu = dialog._build_header_context_menu(2)
        move_menu = next(a for a in menu.actions() if a.text() == "Move").menu()
        beginning_action = next(
            a for a in move_menu.actions() if a.text() == "To Beginning"
        )
        self.assertTrue(beginning_action.isEnabled())
        beginning_action.trigger()

        self.assertEqual(
            dialog._selected_preview_candidate().headers,
            ["Day", "Region", "Amount"],
        )

    def test_move_left_disabled_on_first_column(self) -> None:
        dialog = self.make()
        menu = dialog._build_header_context_menu(0)
        move_menu = next(a for a in menu.actions() if a.text() == "Move").menu()
        actions = {a.text(): a for a in move_menu.actions()}

        self.assertFalse(actions["Left"].isEnabled())
        self.assertFalse(actions["To Beginning"].isEnabled())
        self.assertTrue(actions["Right"].isEnabled())
        self.assertTrue(actions["To End"].isEnabled())
