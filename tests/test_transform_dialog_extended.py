"""Qt smoke tests for the added local Transform Data controls."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import TransformDataDialog
from analytics_studio.project import new_project, validate_project


class ExtendedTransformDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Transform dialog tests"])

    def setUp(self) -> None:
        self.source = ImportCandidate(
            "csv",
            ["Name", "Note"],
            [
                {"Name": " Ada ", "Note": "old"},
                {"Name": "Ada", "Note": "old"},
                {"Name": " Lin ", "Note": "old"},
            ],
            {},
            [],
        )
        self.dialog = TransformDataDialog(self.source)

    def choose(self, operation: str, column: str | None = None) -> None:
        self.dialog.operation_combo.setCurrentIndex(
            self.dialog.operation_combo.findData(operation)
        )
        if column is not None:
            self.dialog.column_combo.setCurrentText(column)

    def test_replace_and_trim_controls_add_previewed_steps(self) -> None:
        self.choose("replace_value", "Note")
        self.dialog.value_edit.setText("old")
        self.dialog.replacement_edit.setText("new")
        self.dialog._add_step()

        self.choose("trim_text", "Name")
        self.dialog._add_step()

        self.assertEqual(self.dialog._preview_candidate.rows[0], {"Name": "Ada", "Note": "new"})
        self.assertEqual(self.dialog._preview_candidate.rows[1], {"Name": "Ada", "Note": "new"})
        self.assertEqual(self.dialog.step_list.count(), 2)

    def test_remove_duplicates_and_keep_columns_controls_preview(self) -> None:
        self.choose("trim_text", "Name")
        self.dialog._add_step()
        self.choose("remove_duplicates")
        self.assertTrue(self.dialog.column_label.isHidden())
        self.dialog._add_step()
        self.assertEqual(self.dialog._preview_candidate.row_count, 2)

        self.choose("keep_columns")
        self.assertFalse(self.dialog.keep_columns_list.isHidden())
        self.assertTrue(self.dialog.column_label.isHidden())
        for index in range(self.dialog.keep_columns_list.count()):
            item = self.dialog.keep_columns_list.item(index)
            if item.text() == "Name":
                item.setCheckState(Qt.CheckState.Checked)
        self.dialog._add_step()

        self.assertEqual(self.dialog._preview_candidate.headers, ["Name"])
        self.assertEqual(self.dialog._preview_candidate.rows, [{"Name": "Ada"}, {"Name": "Lin"}])
        self.assertEqual(self.dialog._steps[-1], {"op": "keep_columns", "columns": ["Name"]})
        self.dialog._accept_candidate()
        self.assertEqual(self.dialog.steps[-1], {"op": "keep_columns", "columns": ["Name"]})

    def test_new_steps_remain_project_json_persistable(self) -> None:
        document = new_project("Extended transforms")
        steps = [
            {"op": "replace_value", "column": "Name", "value": "Ada", "replacement": "Ada L."},
            {"op": "trim_text", "column": "Name"},
            {"op": "remove_duplicates"},
            {"op": "keep_columns", "columns": ["Name"]},
        ]
        document["data_sources"] = [{
            "id": "inline-1",
            "name": "Entered data",
            "kind": "inline",
            "headers": ["Name", "Note"],
            "rows": [{"Name": "Ada", "Note": "old"}],
            "transform_steps": steps,
        }]
        document["active_source_id"] = "inline-1"

        validated = validate_project(document)

        self.assertEqual(validated["data_sources"][0]["transform_steps"], steps)


if __name__ == "__main__":
    unittest.main()
