"""Tests for Power BI Group By dialog (Basic / Advanced) (Task 195)."""

from __future__ import annotations

import os
import unittest
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QPushButton, QRadioButton, QToolButton

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import GroupByDialog, TransformDataDialog


def _source() -> ImportCandidate:
    return ImportCandidate(
        "inline",
        ["Region", "Product", "Amount"],
        [
            {"Region": "North", "Product": "A", "Amount": "10"},
            {"Region": "North", "Product": "A", "Amount": "20"},
            {"Region": "North", "Product": "B", "Amount": "30"},
            {"Region": "South", "Product": "A", "Amount": "40"},
        ],
        {},
        [],
    )


class GroupByDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["group by dialog tests"])

    def make_dialog(self, steps=None) -> TransformDataDialog:
        dialog = TransformDataDialog(_source(), steps=steps, query_name="Sales")
        self.addCleanup(dialog.deleteLater)
        return dialog

    def select_column(self, dialog: TransformDataDialog, col_idx: int) -> None:
        dialog.preview.selectColumn(col_idx)
        dialog.preview.setCurrentIndex(dialog.preview.model().index(0, col_idx))

    def test_ribbon_group_by_with_region_selected_opens_basic_mode_and_applies(self) -> None:
        dialog = self.make_dialog()
        self.select_column(dialog, 0)  # "Region"
        self.assertEqual(dialog._selected_preview_columns(), ["Region"])

        dialog.ribbon_command_buttons["group_by"].click()
        self.app.processEvents()

        sub = getattr(dialog, "_group_by_dialog", None) or dialog._operation_dialog
        self.assertIsInstance(sub, GroupByDialog)
        self.assertEqual(sub.objectName(), "powerQueryGroupByDialog")

        basic_radio = sub.findChild(QRadioButton, "groupByBasicRadio")
        advanced_radio = sub.findChild(QRadioButton, "groupByAdvancedRadio")
        self.assertIsNotNone(basic_radio)
        self.assertIsNotNone(advanced_radio)
        self.assertTrue(basic_radio.isChecked())
        self.assertFalse(advanced_radio.isChecked())

        col_combo = sub.findChild(QComboBox, "groupByColumnCombo_0")
        name_edit = sub.findChild(QLineEdit, "groupByNewName_0")
        op_combo = sub.findChild(QComboBox, "groupByOperation_0")
        agg_col_combo = sub.findChild(QComboBox, "groupByAggColumn_0")

        self.assertIsNotNone(col_combo)
        self.assertIsNotNone(name_edit)
        self.assertIsNotNone(op_combo)
        self.assertIsNotNone(agg_col_combo)

        self.assertEqual(col_combo.currentText(), "Region")
        self.assertEqual(name_edit.text(), "Count")
        self.assertEqual(op_combo.currentData(), "count_rows")
        self.assertFalse(agg_col_combo.isEnabled())

        # OK adds the step
        sub.ok_button.click()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        expected_step = {
            "op": "group_by",
            "columns": ["Region"],
            "aggregations": [{"operation": "count_rows", "new_name": "Count"}],
        }
        self.assertEqual(dialog._steps[0], expected_step)

        # Preview has the Region and Count columns
        self.assertEqual(dialog._preview_candidate.headers, ["Region", "Count"])
        self.assertEqual(
            dialog._preview_candidate.rows,
            [
                {"Region": "North", "Count": 3},
                {"Region": "South", "Count": 1},
            ],
        )

    def test_advanced_mode_add_grouping_and_sum_aggregation(self) -> None:
        dialog = self.make_dialog()
        self.select_column(dialog, 0)
        dialog.ribbon_command_buttons["group_by"].click()
        self.app.processEvents()

        sub = getattr(dialog, "_group_by_dialog", None) or dialog._operation_dialog
        self.assertIsInstance(sub, GroupByDialog)

        advanced_radio = sub.findChild(QRadioButton, "groupByAdvancedRadio")
        advanced_radio.setChecked(True)
        self.app.processEvents()

        add_grouping = sub.findChild(QPushButton, "groupByAddGrouping")
        add_agg = sub.findChild(QPushButton, "groupByAddAggregation")
        self.assertIsNotNone(add_grouping)
        self.assertIsNotNone(add_agg)

        # Add grouping: Product
        add_grouping.click()
        self.app.processEvents()
        group_combo_1 = sub.findChild(QComboBox, "groupByColumnCombo_1")
        self.assertIsNotNone(group_combo_1)
        group_combo_1.setCurrentText("Product")

        # Add aggregation: Sum of Amount -> Total
        add_agg.click()
        self.app.processEvents()
        agg_name_1 = sub.findChild(QLineEdit, "groupByNewName_1")
        agg_op_1 = sub.findChild(QComboBox, "groupByOperation_1")
        agg_col_1 = sub.findChild(QComboBox, "groupByAggColumn_1")

        self.assertIsNotNone(agg_name_1)
        self.assertIsNotNone(agg_op_1)
        self.assertIsNotNone(agg_col_1)

        agg_name_1.setText("Total")
        agg_op_1.setCurrentIndex(agg_op_1.findData("sum"))
        agg_col_1.setCurrentText("Amount")

        sub.ok_button.click()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        expected_step = {
            "op": "group_by",
            "columns": ["Region", "Product"],
            "aggregations": [
                {"operation": "count_rows", "new_name": "Count"},
                {"operation": "sum", "column": "Amount", "new_name": "Total"},
            ],
        }
        self.assertEqual(dialog._steps[0], expected_step)
        self.assertEqual(dialog._preview_candidate.headers, ["Region", "Product", "Count", "Total"])
        self.assertEqual(
            dialog._preview_candidate.rows,
            [
                {"Region": "North", "Product": "A", "Count": 2, "Total": Decimal("30")},
                {"Region": "North", "Product": "B", "Count": 1, "Total": Decimal("30")},
                {"Region": "South", "Product": "A", "Count": 1, "Total": Decimal("40")},
            ],
        )

    def test_all_rows_disabled_and_ok_disabled_when_sum_has_no_column(self) -> None:
        dialog = self.make_dialog()
        dialog.ribbon_command_buttons["group_by"].click()
        self.app.processEvents()

        sub = getattr(dialog, "_group_by_dialog", None) or dialog._operation_dialog
        self.assertIsInstance(sub, GroupByDialog)

        op_combo = sub.findChild(QComboBox, "groupByOperation_0")
        all_rows_idx = op_combo.findData("all_rows")
        self.assertGreaterEqual(all_rows_idx, 0)
        item = op_combo.model().item(all_rows_idx)
        self.assertFalse(item.isEnabled())
        self.assertEqual(item.toolTip(), "All Rows is not supported yet.")

        # Switch to Sum
        op_combo.setCurrentIndex(op_combo.findData("sum"))
        col_combo = sub.findChild(QComboBox, "groupByAggColumn_0")
        self.assertTrue(col_combo.isEnabled())
        self.assertTrue(sub.ok_button.isEnabled())

        # If column combo is empty, OK is disabled
        col_combo.clear()
        self.app.processEvents()
        self.assertFalse(sub.ok_button.isEnabled())

        # If name edit is empty, OK is disabled
        col_combo.addItems(["Amount"])
        col_combo.setCurrentText("Amount")
        name_edit = sub.findChild(QLineEdit, "groupByNewName_0")
        name_edit.setText("")
        self.app.processEvents()
        self.assertFalse(sub.ok_button.isEnabled())

        name_edit.setText("Total")
        self.app.processEvents()
        self.assertTrue(sub.ok_button.isEnabled())

        sub.reject()

    def test_gear_on_existing_2_aggregation_step_reopens_in_advanced_mode_and_edits_in_place(self) -> None:
        initial_step = {
            "op": "group_by",
            "columns": ["Region"],
            "aggregations": [
                {"operation": "count_rows", "new_name": "Count"},
                {"operation": "sum", "column": "Amount", "new_name": "Total"},
            ],
        }
        dialog = self.make_dialog(steps=[initial_step])
        dialog.step_list.setCurrentRow(0)
        self.assertEqual(dialog.step_list.currentRow(), 0)

        # Trigger gear edit settings
        dialog._edit_selected_step_settings()
        self.app.processEvents()

        sub = getattr(dialog, "_group_by_dialog", None) or dialog._operation_dialog
        self.assertIsInstance(sub, GroupByDialog)

        advanced_radio = sub.findChild(QRadioButton, "groupByAdvancedRadio")
        self.assertTrue(advanced_radio.isChecked())

        # Check pre-filled values
        name_0 = sub.findChild(QLineEdit, "groupByNewName_0")
        name_1 = sub.findChild(QLineEdit, "groupByNewName_1")
        self.assertEqual(name_0.text(), "Count")
        self.assertEqual(name_1.text(), "Total")

        # Change name_1 to "Subtotal"
        name_1.setText("Subtotal")
        sub.ok_button.click()
        self.app.processEvents()

        # Step is updated in place, count of steps is still 1
        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(
            dialog._steps[0]["aggregations"][1]["new_name"],
            "Subtotal",
        )
        self.assertEqual(dialog._preview_candidate.headers, ["Region", "Count", "Subtotal"])

    def test_cancel_adds_nothing_and_restores_step_selection(self) -> None:
        initial_step = {
            "op": "group_by",
            "columns": ["Region"],
            "aggregations": [{"operation": "count_rows", "new_name": "Count"}],
        }
        dialog = self.make_dialog(steps=[initial_step])
        dialog.step_list.setCurrentRow(0)
        self.assertEqual(dialog.step_list.currentRow(), 0)

        # Click ribbon Group By while step 0 is selected
        dialog.ribbon_command_buttons["group_by"].click()
        self.app.processEvents()

        sub = getattr(dialog, "_group_by_dialog", None) or dialog._operation_dialog
        self.assertIsInstance(sub, GroupByDialog)

        sub.cancel_button.click()
        self.app.processEvents()

        # No step added, selection restored
        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(dialog.step_list.currentRow(), 0)
