"""Acceptance checks for Fill Down and Fill Up through source lifecycle."""

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


class FillDownUpLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "categories.csv"
        self.source_path.write_text(
            "Region,Category,Sales\n"
            ",,0\n,Tools,1\nWest,,2\n,,3\nEast,Food,4\n,,5\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    @staticmethod
    def select_fill_columns(dialog: TransformDataDialog) -> None:
        for index in range(dialog.keep_columns_list.count()):
            item = dialog.keep_columns_list.item(index)
            item.setCheckState(
                Qt.CheckState.Checked
                if item.text() in {"Region", "Category"}
                else Qt.CheckState.Unchecked
            )

    def test_fill_down_and_up_replay_in_order(self) -> None:
        controller = self.controller("settings.ini")
        raw = parse_file(self.source_path)
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData("fill_down"))
        self.select_fill_columns(dialog)
        dialog._add_step()
        self.assertEqual(dialog._preview_candidate.rows, [
            {"Region": "", "Category": "", "Sales": "0"},
            {"Region": "", "Category": "Tools", "Sales": "1"},
            {"Region": "West", "Category": "Tools", "Sales": "2"},
            {"Region": "West", "Category": "Tools", "Sales": "3"},
            {"Region": "East", "Category": "Food", "Sales": "4"},
            {"Region": "East", "Category": "Food", "Sales": "5"},
        ])

        dialog.step_list.setCurrentRow(-1)
        dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData("fill_up"))
        self.select_fill_columns(dialog)
        dialog._add_step()
        self.assertEqual(dialog._preview_candidate.rows, [
            {"Region": "West", "Category": "Tools", "Sales": "0"},
            {"Region": "West", "Category": "Tools", "Sales": "1"},
            {"Region": "West", "Category": "Tools", "Sales": "2"},
            {"Region": "West", "Category": "Tools", "Sales": "3"},
            {"Region": "East", "Category": "Food", "Sales": "4"},
            {"Region": "East", "Category": "Food", "Sales": "5"},
        ])
        dialog._accept_candidate()
        self.assertEqual([step["op"] for step in dialog.steps], ["fill_down", "fill_up"])
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "fill-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Region,Category,Sales\n,Services,9\n,,10\nNorth,,11\n,Food,12\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual([row["Region"] for row in reopened._rows], [
            "North", "North", "North", "North",
        ])
        self.assertEqual([row["Category"] for row in reopened._rows], [
            "Services", "Services", "Services", "Food",
        ])

        self.source_path.write_text(
            "Region,Category,Sales\nNorth,Office,15\n,,16\n,,17\nEast,Food,18\n,,19\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual([row["Region"] for row in reopened._rows], [
            "North", "North", "North", "East", "East",
        ])
        self.assertEqual([row["Category"] for row in reopened._rows], [
            "Office", "Office", "Office", "Food", "Food",
        ])


if __name__ == "__main__":
    unittest.main()
