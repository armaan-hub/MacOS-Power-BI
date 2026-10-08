"""Acceptance checks for selected-column and other-column unpivot modes."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.local_table_dialogs import TransformDataDialog


class UnpivotLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.selected_path = self.root / "selected.csv"
        self.other_path = self.root / "other.csv"
        self.selected_path.write_text(
            "Region,Store,Note,Q1,Q2\nNorth,1,foo,10,\nSouth,2,bar,5,15\n",
            encoding="utf-8",
        )
        self.other_path.write_text(
            "Region,Store,Department,Q1,Q2\n"
            "North,1,Produce,10,\nSouth,2,Dairy,5,15\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def apply_unpivot(
        self, controller: StudioController, source_id: str, mode: str,
        checked_columns: set[str],
    ) -> TransformDataDialog:
        raw = controller._loaded_candidates[source_id]
        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData(mode))
        for index in range(dialog.keep_columns_list.count()):
            item = dialog.keep_columns_list.item(index)
            item.setCheckState(
                Qt.CheckState.Checked
                if item.text() in checked_columns
                else Qt.CheckState.Unchecked
            )
        dialog.attribute_name_edit.setText("Field")
        dialog.value_column_name_edit.setText("Amount")
        dialog._add_step()
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        return dialog

    def test_selected_and_other_column_unpivot_save_reopen_and_refresh(self) -> None:
        controller = self.controller("settings.ini")
        source_ids = []
        for path in (self.selected_path, self.other_path):
            self.assertTrue(controller._commit_import(path, parse_file(path)))
            source_ids.append(controller.activeTableId)
        selected_id, other_id = source_ids

        selected_dialog = self.apply_unpivot(
            controller, selected_id, "unpivot_columns", {"Q1", "Q2"}
        )
        self.assertEqual(selected_dialog._preview_candidate.headers, [
            "Region", "Store", "Note", "Field", "Amount",
        ])
        self.assertEqual(selected_dialog._preview_candidate.rows, [
            {"Region": "North", "Store": "1", "Note": "foo", "Field": "Q1", "Amount": "10"},
            {"Region": "South", "Store": "2", "Note": "bar", "Field": "Q1", "Amount": "5"},
            {"Region": "South", "Store": "2", "Note": "bar", "Field": "Q2", "Amount": "15"},
        ])
        selected_dialog.deleteLater()

        other_dialog = self.apply_unpivot(
            controller, other_id, "unpivot_other_columns", {"Region", "Store"}
        )
        self.assertEqual(other_dialog._preview_candidate.headers, [
            "Region", "Store", "Field", "Amount",
        ])
        self.assertEqual(other_dialog._preview_candidate.rows, [
            {"Region": "North", "Store": "1", "Field": "Department", "Amount": "Produce"},
            {"Region": "North", "Store": "1", "Field": "Q1", "Amount": "10"},
            {"Region": "South", "Store": "2", "Field": "Department", "Amount": "Dairy"},
            {"Region": "South", "Store": "2", "Field": "Q1", "Amount": "5"},
            {"Region": "South", "Store": "2", "Field": "Q2", "Amount": "15"},
        ])
        other_dialog.deleteLater()

        project_path = self.root / "unpivot-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.selected_path.write_text(
            "Region,Store,Note,Q1,Q2\nEast,3,baz,20,30\n", encoding="utf-8"
        )
        self.other_path.write_text(
            "Region,Store,Department,Q1,Q2\nWest,4,Frozen,6,7\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._loaded_candidates[selected_id].rows, [
            {"Region": "East", "Store": "3", "Note": "baz", "Field": "Q1", "Amount": "20"},
            {"Region": "East", "Store": "3", "Note": "baz", "Field": "Q2", "Amount": "30"},
        ])
        self.assertEqual(reopened._loaded_candidates[other_id].rows, [
            {"Region": "West", "Store": "4", "Field": "Department", "Amount": "Frozen"},
            {"Region": "West", "Store": "4", "Field": "Q1", "Amount": "6"},
            {"Region": "West", "Store": "4", "Field": "Q2", "Amount": "7"},
        ])

        self.selected_path.write_text(
            "Region,Store,Note,Q1,Q2\nCentral,5,xyz,40,\n",
            encoding="utf-8",
        )
        self.other_path.write_text(
            "Region,Store,Department,Q1,Q2\nSouth,6,Chilled,8,9\n",
            encoding="utf-8",
        )
        reopened.refresh_all_sources()
        self.assertEqual(reopened._loaded_candidates[selected_id].rows, [
            {"Region": "Central", "Store": "5", "Note": "xyz", "Field": "Q1", "Amount": "40"},
        ])
        self.assertEqual(reopened._loaded_candidates[other_id].rows, [
            {"Region": "South", "Store": "6", "Field": "Department", "Amount": "Chilled"},
            {"Region": "South", "Store": "6", "Field": "Q1", "Amount": "8"},
            {"Region": "South", "Store": "6", "Field": "Q2", "Amount": "9"},
        ])


if __name__ == "__main__":
    unittest.main()
