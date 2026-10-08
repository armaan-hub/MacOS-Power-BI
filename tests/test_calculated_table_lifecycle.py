"""Acceptance checks for calculated-table preview, persistence, and refresh."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.local_table_dialogs import CalculatedTableDialog


class CalculatedTableLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "Sales.csv"
        self.source_path.write_text(
            "Region,Amount\nWest,10\nEast,20\nWest,30\n,40\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, settings_name: str) -> StudioController:
        settings = QSettings(
            str(self.root / settings_name), QSettings.Format.IniFormat
        )
        return StudioController(self.app, settings)

    def create_distinct_table(self, controller: StudioController) -> bool:
        tables = [
            dict(table) for table in controller._table_catalog
            if table.get("loaded") and table.get("loadEnabled")
        ]
        candidates = {
            str(table["sourceId"]): controller._loaded_candidates[str(table["sourceId"])]
            for table in tables
        }
        dialog = CalculatedTableDialog(tables, candidates)
        dialog.table_name_edit.setText("Sales regions")
        dialog.column_combo.setCurrentText("Region")

        def accept_dialog() -> QDialog.DialogCode:
            dialog._accept_table()
            return dialog.result()

        with (
            patch("analytics_studio.controller.CalculatedTableDialog", return_value=dialog),
            patch.object(dialog, "exec", side_effect=accept_dialog),
        ):
            result = controller.calculated_table_dialog()
        dialog.deleteLater()
        return result

    def test_create_reopen_and_refresh_calculated_table(self) -> None:
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(
            self.source_path, parse_file(self.source_path)
        ))

        dialog = CalculatedTableDialog(
            controller._table_catalog,
            controller._loaded_candidates,
        )
        self.assertTrue(dialog.create_button.isEnabled())
        self.assertEqual(dialog.expression_edit.text(), "DISTINCT('Sales'[Region])")
        self.assertEqual(dialog.preview.model().rowCount(), 3)
        self.assertEqual(dialog.preview.model().columnCount(), 1)
        self.assertEqual(dialog.preview.model().data(dialog.preview.model().index(0, 0)), "West")
        self.assertEqual(dialog.preview.model().data(dialog.preview.model().index(1, 0)), "East")
        dialog.deleteLater()

        self.assertTrue(
            self.create_distinct_table(controller), controller.statusMessage
        )
        query = next(
            source for source in controller._project["data_sources"]
            if source.get("query_definition", {}).get("operation") == "calculated_table"
        )
        query_id = query["id"]
        self.assertEqual(query["query_definition"]["expression"], "DISTINCT('Sales'[Region])")
        self.assertEqual(controller._loaded_candidates[query_id].rows, [
            {"Region": "West"}, {"Region": "East"}, {"Region": ""},
        ])

        project_path = self.root / "calculated-table.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Region,Amount\nEast,200\nNorth,300\nNorth,400\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened._loaded_candidates[query_id].rows, [
            {"Region": "East"}, {"Region": "North"},
        ])

        self.source_path.write_text(
            "Region,Amount\nSouth,5\nSouth,6\nCentral,7\n",
            encoding="utf-8",
        )
        reopened.refresh_all_sources()
        self.assertEqual(reopened._loaded_candidates[query_id].rows, [
            {"Region": "South"}, {"Region": "Central"},
        ])


if __name__ == "__main__":
    unittest.main()
