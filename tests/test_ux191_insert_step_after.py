"""Tests for Applied Steps "Insert Step After" (Task 191)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import TransformDataDialog
from analytics_studio.power_query_m import (
    PowerQueryMEditorDialog,
    m_script_matches_steps,
    parse_m_script,
    steps_to_m_script,
)


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


class InsertStepAfterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["insert step after tests"])

    def make_with_three_steps(self) -> TransformDataDialog:
        steps = [
            {"op": "sort_rows", "column": "Amount", "direction": "asc"},
            {"op": "filter_rows", "column": "Region", "operator": "equals", "value": "East"},
            {"op": "remove_column", "column": "Day"},
        ]
        dialog = TransformDataDialog(_source(), steps=steps, query_name="Sales")
        self.addCleanup(dialog.deleteLater)
        return dialog

    def test_insert_step_after_middle_and_round_trip(self) -> None:
        dialog = self.make_with_three_steps()
        # Initial steps: A (sort_rows), B (filter_rows), C (remove_column)
        self.assertEqual(len(dialog._steps), 3)

        # Baseline preview candidates
        # Preview after A:
        dialog.step_list.setCurrentRow(0)
        a_preview = dialog._selected_preview_candidate()
        # Preview after C:
        dialog.step_list.setCurrentRow(2)
        c_preview = dialog._selected_preview_candidate()

        # Context menu action is enabled
        menu, actions = dialog._build_step_context_menu(0)
        self.assertIn("Insert Step After", actions)
        self.assertTrue(actions["Insert Step After"].isEnabled())

        # Insert after A (row 0) gives [A, Custom1, B, C]
        dialog.step_list.setCurrentRow(0)
        ok = dialog._insert_step_after(0)
        self.assertTrue(ok)

        self.assertEqual(len(dialog._steps), 4)
        step_names = [dialog.step_list.item(i).text() for i in range(dialog.step_list.count())]
        self.assertEqual(step_names, ["Sorted Rows", "Custom1", "Filtered Rows", "Removed Columns"])

        # Custom1 is selected (row 1)
        self.assertEqual(dialog.step_list.currentRow(), 1)

        # Custom1's preview equals A's preview
        custom1_preview = dialog._selected_preview_candidate()
        self.assertEqual(custom1_preview.headers, a_preview.headers)
        self.assertEqual([dict(r) for r in custom1_preview.rows], [dict(r) for r in a_preview.rows])

        # C's final preview is unchanged
        dialog.step_list.setCurrentRow(3)
        final_c_preview = dialog._selected_preview_candidate()
        self.assertEqual(final_c_preview.headers, c_preview.headers)
        self.assertEqual([dict(r) for r in final_c_preview.rows], [dict(r) for r in c_preview.rows])

        # The formula bar text for Custom1 is = #"<A's name>"
        dialog.step_list.setCurrentRow(1)
        self.assertEqual(dialog.formula_bar.text(), '#"Sorted Rows"')

        # Advanced Editor shows Custom1 = #"Sorted Rows", in the let chain
        m_script = steps_to_m_script(
            dialog._steps, "Sales", step_names=dialog._step_names_for(dialog._steps)
        )
        self.assertIn('#"Custom1" = #"Sorted Rows",', m_script)

        # Round-trips through parse_m_script and m_script_matches_steps
        parsed = parse_m_script(m_script, "Sales")
        self.assertEqual(len(parsed), 4)
        self.assertTrue(m_script_matches_steps(m_script, "Sales", dialog._steps))

        # Advanced editor dialog accept round-trip
        with patch.object(
            PowerQueryMEditorDialog, "exec", return_value=QDialog.DialogCode.Accepted
        ):
            dialog._open_advanced_editor()

        self.assertEqual(len(dialog._steps), 4)
        reopened_names = [dialog.step_list.item(i).text() for i in range(dialog.step_list.count())]
        self.assertEqual(reopened_names, ["Sorted Rows", "Custom1", "Filtered Rows", "Removed Columns"])

    def test_insert_again_after_same_step_gives_custom2(self) -> None:
        dialog = self.make_with_three_steps()
        # Insert after row 0 (A) -> [A, Custom1, B, C]
        dialog._insert_step_after(0)
        self.assertEqual(dialog.step_list.item(1).text(), "Custom1")

        # Insert again after row 0 (A) -> [A, Custom2, Custom1, B, C]
        dialog._insert_step_after(0)
        step_names = [dialog.step_list.item(i).text() for i in range(dialog.step_list.count())]
        self.assertEqual(
            step_names,
            ["Sorted Rows", "Custom2", "Custom1", "Filtered Rows", "Removed Columns"],
        )
        self.assertEqual(dialog.step_list.currentRow(), 1)
        self.assertEqual(dialog.formula_bar.text(), '#"Sorted Rows"')

    def test_insert_after_last_step_appends(self) -> None:
        dialog = self.make_with_three_steps()
        # Steps [A, B, C] (length 3). Insert after C (row 2)
        menu, actions = dialog._build_step_context_menu(2)
        self.assertTrue(actions["Insert Step After"].isEnabled())

        ok = dialog._insert_step_after(2)
        self.assertTrue(ok)

        self.assertEqual(len(dialog._steps), 4)
        step_names = [dialog.step_list.item(i).text() for i in range(dialog.step_list.count())]
        self.assertEqual(step_names, ["Sorted Rows", "Filtered Rows", "Removed Columns", "Custom1"])
        self.assertEqual(dialog.step_list.currentRow(), 3)
        self.assertEqual(dialog.formula_bar.text(), '#"Removed Columns"')

        m_script = steps_to_m_script(
            dialog._steps, "Sales", step_names=dialog._step_names_for(dialog._steps)
        )
        self.assertIn('#"Custom1" = #"Removed Columns"', m_script)
        self.assertTrue(m_script_matches_steps(m_script, "Sales", dialog._steps))

    def test_insert_after_sparse_helper_is_disabled(self) -> None:
        steps = [
            {"op": "m_sparse_boundary_helper", "name": "FilterNullAndWhitespace"},
            {"op": "remove_sparse_bottom_rows"},
            {"op": "remove_sparse_top_rows"},
            {"op": "promote_headers", "promote_all_scalars": True},
        ]
        dialog = TransformDataDialog(_source(), steps=steps, query_name="Sales")
        self.addCleanup(dialog.deleteLater)
        before = [dict(step) for step in dialog._steps]

        _, actions = dialog._build_step_context_menu(0)
        self.assertFalse(actions["Insert Step After"].isEnabled())
        self.assertEqual(actions["Insert Step After"].toolTip(), "Not supported yet")

        self.assertFalse(dialog._insert_step_after(0))
        self.assertEqual(dialog._steps, before)

    def test_formula_edit_keeps_custom_name(self) -> None:
        dialog = self.make_with_three_steps()
        dialog._insert_step_after(0)
        self.assertEqual(dialog.step_list.item(1).text(), "Custom1")

        dialog.step_list.setCurrentRow(1)
        dialog.formula_bar.setText(
            'Table.SelectRows(#"Sorted Rows", each [Region] = "East")'
        )
        dialog._apply_formula_bar()

        self.assertEqual(dialog.step_list.item(1).text(), "Custom1")
        self.assertEqual(dialog._steps[1]["op"], "filter_rows")

    def test_insert_after_convert_type_preserves_types(self) -> None:
        # Task 194 (2026-11-17): check step type metadata, not inferred types
        steps = [
            {"op": "convert_type", "column": "Amount", "type": "number"},
            {"op": "remove_column", "column": "Day"},
        ]
        dialog = TransformDataDialog(_source(), steps=steps, query_name="Sales")
        self.addCleanup(dialog.deleteLater)

        dialog._insert_step_after(0)
        self.assertEqual(dialog.step_list.item(1).text(), "Custom1")

        dialog.step_list.setCurrentRow(0)
        step0_types = {p["name"]: p.get("type") for p in dialog.preview_header._profiles}
        self.assertNotIn(step0_types.get("Amount"), ("any", "text", None))
        self.assertIn("decimal", str(step0_types.get("Amount")))

        dialog.step_list.setCurrentRow(1)
        custom1_types = {p["name"]: p.get("type") for p in dialog.preview_header._profiles}
        self.assertEqual(custom1_types, step0_types)
