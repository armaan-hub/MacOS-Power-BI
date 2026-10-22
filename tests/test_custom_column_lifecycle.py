"""Acceptance checks for a safe custom formula through source lifecycle."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import ImportCandidate, parse_file
from analytics_studio.local_table_dialogs import (
    CustomColumnDialog,
    TransformDataDialog,
)


class CustomColumnLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "products.csv"
        self.source_path.write_text(
            "Product,Units,Revenue\nWidget,2,3.5\npear,1,4\nberry,3,2\n",
            encoding="utf-8",
        )
        self.formula = (
            'if [Units] > 1 then Text.Upper([Product]) & "-" & '
            "Text.From(Number.Round([Revenue] * [Units], 0)) else [Product]"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def test_custom_formula_previews_saves_reopens_and_refreshes(self) -> None:
        controller = self.controller("settings.ini")
        raw = parse_file(self.source_path)
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("add_custom_column")
        )
        dialog.value_edit.setText("Sales label")
        dialog.custom_expression_edit.setPlainText(self.formula)
        dialog._add_step()
        self.assertEqual(dialog._preview_candidate.headers, [
            "Product", "Units", "Revenue", "Sales label",
        ])
        self.assertEqual([row["Sales label"] for row in dialog._preview_candidate.rows], [
            "WIDGET-7", "pear", "BERRY-6",
        ])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "custom-column-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Product,Units,Revenue\nmug,2,1.4\npeach,1,9\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual([row["Sales label"] for row in reopened._rows], [
            "MUG-3", "peach",
        ])

        self.source_path.write_text(
            "Product,Units,Revenue\nbook,3,1.6\ncup,1,4\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual([row["Sales label"] for row in reopened._rows], [
            "BOOK-5", "cup",
        ])

    def test_text_clean_custom_formula_previews_saves_reopens_and_refreshes(self) -> None:
        self.source_path.write_text(
            "Customer,Revenue\n\"A" + chr(1) + "B" + chr(0x7F)
            + chr(0x85) + "C" + chr(0x200B) + "D\",1\n,2\n",
            encoding="utf-8",
        )
        controller = self.controller("clean-settings.ini")
        raw = parse_file(self.source_path)
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw, query_name="Customers")
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("add_custom_column")
        )
        dialog.value_edit.setText("Cleaned")
        dialog.custom_expression_edit.setPlainText("Text.Clean([Customer])")
        dialog._add_step()
        self.assertEqual(
            [row["Cleaned"] for row in dialog._preview_candidate.rows],
            ["ABC\u200bD", ""],
        )
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "text-clean-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Customer,Revenue\n\"X" + chr(2) + "Y" + chr(0x86) + "Z\",3\n,4\n",
            encoding="utf-8",
        )
        reopened = self.controller("clean-reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual([row["Cleaned"] for row in reopened._rows], ["XYZ", ""])

        self.source_path.write_text(
            "Customer,Revenue\n\"M" + chr(3) + "N" + chr(0x87) + "O\",5\n,6\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual([row["Cleaned"] for row in reopened._rows], ["MNO", ""])

    def test_custom_column_ribbon_uses_formula_dialog_and_staged_preview(self) -> None:
        raw = parse_file(self.source_path)
        dialog = TransformDataDialog(raw)

        def accept_custom_column(editor: CustomColumnDialog) -> int:
            self.assertEqual(
                [editor.column_list.item(index).text()
                 for index in range(editor.column_list.count())],
                raw.headers,
            )
            self.assertGreater(editor.function_list.count(), 10)
            editor.name_edit.setText("Normalized product")
            function_item = editor.function_list.findItems(
                "Text.Upper", Qt.MatchFlag.MatchExactly
            )[0]
            editor.function_list.setCurrentItem(function_item)
            editor._insert_selected_function()
            editor.column_list.setCurrentRow(0)
            editor._insert_selected_column()
            self.assertEqual(
                editor.expression_edit.toPlainText(), "Text.Upper([Product])"
            )
            editor._accept_column()
            return editor.result()

        with patch.object(CustomColumnDialog, "exec", new=accept_custom_column):
            dialog._select_ribbon_operation("add_custom_column")

        self.assertEqual(dialog._steps[-1], {
            "op": "add_custom_column",
            "name": "Normalized product",
            "expression": "Text.Upper([Product])",
        })
        self.assertEqual(
            [row["Normalized product"] for row in dialog._preview_candidate.rows],
            ["WIDGET", "PEAR", "BERRY"],
        )
        dialog.deleteLater()
        self.app.processEvents()

    def test_operation_combo_opens_formula_dialog_and_saves_custom_column(self) -> None:
        raw = parse_file(self.source_path)
        dialog = TransformDataDialog(raw)
        custom_index = dialog.operation_combo.findData("add_custom_column")

        def accept_custom_column(editor: CustomColumnDialog) -> int:
            self.assertEqual(editor.column_list.count(), len(raw.headers))
            editor.name_edit.setText("Revenue doubled")
            editor.expression_edit.setPlainText("[Revenue] * 2")
            editor._accept_column()
            return editor.result()

        with patch.object(CustomColumnDialog, "exec", new=accept_custom_column):
            dialog.operation_combo.setCurrentIndex(custom_index)
            dialog.operation_combo.activated.emit(custom_index)

        self.assertEqual(dialog._steps[-1]["name"], "Revenue doubled")
        self.assertEqual(
            [row["Revenue doubled"] for row in dialog._preview_candidate.rows],
            ["7", "8", "4"],
        )
        dialog.deleteLater()
        self.app.processEvents()

    def test_add_step_carries_existing_custom_column_draft_into_dialog(self) -> None:
        raw = parse_file(self.source_path)
        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("add_custom_column")
        )
        dialog.value_edit.setText("Revenue doubled")
        dialog.custom_expression_edit.setPlainText("[Revenue] * 2")

        def accept_custom_column(editor: CustomColumnDialog) -> int:
            self.assertEqual(editor.name_edit.text(), "Revenue doubled")
            self.assertEqual(editor.expression_edit.toPlainText(), "[Revenue] * 2")
            editor._accept_column()
            return editor.result()

        with patch.object(CustomColumnDialog, "exec", new=accept_custom_column):
            dialog._add_or_start_new_step()

        self.assertEqual(dialog._steps[-1]["expression"], "[Revenue] * 2")
        self.assertEqual(
            [row["Revenue doubled"] for row in dialog._preview_candidate.rows],
            ["7", "8", "4"],
        )
        dialog.deleteLater()
        self.app.processEvents()

    def test_custom_column_edit_dialog_preserves_saved_output_type(self) -> None:
        raw = parse_file(self.source_path)
        dialog = TransformDataDialog(raw, steps=[{
            "op": "add_custom_column",
            "name": "Units plus",
            "expression": "[Units] + 1",
            "output_type": "whole_number",
        }])
        dialog.step_list.setCurrentRow(0)

        def accept_edit(editor: CustomColumnDialog) -> int:
            self.assertEqual(editor.name_edit.text(), "Units plus")
            self.assertEqual(editor.column_list.count(), len(raw.headers))
            editor.expression_edit.setPlainText("[Units] + 2")
            editor._accept_column()
            return editor.result()

        with patch.object(CustomColumnDialog, "exec", new=accept_edit):
            dialog._edit_selected_step_settings()

        self.assertEqual(dialog._steps[0]["expression"], "[Units] + 2")
        self.assertEqual(dialog._steps[0]["output_type"], "whole_number")
        self.assertEqual(
            [row["Units plus"] for row in dialog._preview_candidate.rows],
            [4, 3, 5],
        )
        dialog.deleteLater()
        self.app.processEvents()

    def test_custom_column_inserts_escaped_field_name_and_hides_empty_generic_labels(self) -> None:
        source = ImportCandidate(
            "inline", ["Tax] code"], [{"Tax] code": "AE-01"}], {}, [],
        )
        transform = TransformDataDialog(source)
        custom_index = transform.operation_combo.findData("add_custom_column")
        transform.operation_combo.setCurrentIndex(custom_index)
        transform._configure_editor()
        self.assertTrue(transform.custom_parameter_label.isHidden())
        self.assertTrue(transform.custom_function_label.isHidden())

        editor = CustomColumnDialog(source.headers)
        editor.column_list.setCurrentRow(0)
        editor._insert_selected_column()
        self.assertEqual(editor.expression_edit.toPlainText(), '[#"Tax] code"]')
        transform.value_edit.setText("Tax copy")
        transform.custom_expression_edit.setPlainText(
            editor.expression_edit.toPlainText()
        )
        transform._add_step()
        self.assertEqual(transform._preview_candidate.rows[0]["Tax copy"], "AE-01")
        editor.deleteLater()
        transform.deleteLater()
        self.app.processEvents()

    def test_custom_column_conditional_help_shows_the_next_part_to_enter(self) -> None:
        editor = CustomColumnDialog(["Quantity", "Product"])
        editor.expression_edit.setPlainText("if [Quantity] > 0")
        self.assertIn("add <code>then</code>", editor.syntax_help_label.text())
        editor.expression_edit.setPlainText(
            'if [Quantity] > 0 then "Has quantity"'
        )
        self.assertIn("Add <code>else</code>", editor.syntax_help_label.text())
        editor.expression_edit.setPlainText(
            'if [Quantity] > 0 then "Has quantity" else "Empty"'
        )
        self.assertIn("Nest another if/then/else", editor.syntax_help_label.text())
        editor.deleteLater()
        self.app.processEvents()

    def test_custom_column_columns_follow_the_selected_power_query(self) -> None:
        first = parse_file(self.source_path)
        second_path = self.root / "territories.csv"
        second_path.write_text("Zone,Goal\nEast,12\n", encoding="utf-8")
        second = parse_file(second_path)
        queries = [
            {
                "id": "products", "name": "Products", "candidate": first,
                "source_candidate": first, "steps": [],
            },
            {
                "id": "territories", "name": "Territories", "candidate": second,
                "source_candidate": second, "steps": [],
            },
        ]
        transform = TransformDataDialog(
            first, queries=queries, active_query_id="territories"
        )

        def accept_column(editor: CustomColumnDialog) -> int:
            self.assertEqual(
                [editor.column_list.item(index).text()
                 for index in range(editor.column_list.count())],
                ["Zone", "Goal"],
            )
            editor.name_edit.setText("Goal plus")
            editor.expression_edit.setPlainText("[Goal] + 1")
            editor._accept_column()
            return editor.result()

        with patch.object(CustomColumnDialog, "exec", new=accept_column):
            transform._select_ribbon_operation("add_custom_column")
        self.assertEqual(transform._preview_candidate.headers, [
            "Zone", "Goal", "Goal plus",
        ])
        self.assertEqual(transform._preview_candidate.rows[0]["Goal plus"], "13")
        transform.deleteLater()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
