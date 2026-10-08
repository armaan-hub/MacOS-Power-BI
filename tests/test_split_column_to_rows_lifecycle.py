"""Acceptance checks for split-into-rows through the saved source lifecycle."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.local_table_dialogs import TransformDataDialog


class SplitColumnToRowsLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "accounts.csv"
        self.source_path.write_text(
            "Order,Accounts,Region\n"
            "1,red;blue;,North\n"
            "2,,South\n"
            "3,green;;gold,West\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def test_split_into_rows_saves_reopens_and_refreshes(self) -> None:
        controller = self.controller("settings.ini")
        raw = parse_file(self.source_path)
        self.assertTrue(controller._commit_import(self.source_path, raw))
        source_id = controller.activeTableId

        dialog = TransformDataDialog(raw)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("split_column_to_rows")
        )
        dialog.column_combo.setCurrentText("Accounts")
        dialog.delimiter_edit.setText(";")
        dialog._add_step()
        self.assertEqual(dialog._preview_candidate.rows, [
            {"Order": "1", "Accounts": "red", "Region": "North"},
            {"Order": "1", "Accounts": "blue", "Region": "North"},
            {"Order": "1", "Accounts": "", "Region": "North"},
            {"Order": "2", "Accounts": "", "Region": "South"},
            {"Order": "3", "Accounts": "green", "Region": "West"},
            {"Order": "3", "Accounts": "", "Region": "West"},
            {"Order": "3", "Accounts": "gold", "Region": "West"},
        ])
        dialog._accept_candidate()
        self.assertTrue(controller._commit_transform_steps(
            source_id, dialog.steps, dialog.candidate, previewed_source=raw
        ))
        dialog.deleteLater()

        project_path = self.root / "split-rows-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Order,Accounts,Region\n1,red;blue,North\n4,amber;gray,East\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._headers, ["Order", "Accounts", "Region"])
        self.assertEqual(reopened._rows, [
            {"Order": "1", "Accounts": "red", "Region": "North"},
            {"Order": "1", "Accounts": "blue", "Region": "North"},
            {"Order": "4", "Accounts": "amber", "Region": "East"},
            {"Order": "4", "Accounts": "gray", "Region": "East"},
        ])

        self.source_path.write_text(
            "Order,Accounts,Region\n5,teal;white,South\n6,black,West\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [
            {"Order": "5", "Accounts": "teal", "Region": "South"},
            {"Order": "5", "Accounts": "white", "Region": "South"},
            {"Order": "6", "Accounts": "black", "Region": "West"},
        ])


if __name__ == "__main__":
    unittest.main()
