"""Acceptance checks for model column types across project lifecycle events."""

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


class ColumnTypeLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "sales.csv"
        self.source_path.write_text(
            "Region,Revenue\nEast,12.00\nWest,20.00\n", encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, settings_name: str) -> StudioController:
        settings = QSettings(
            str(self.root / settings_name), QSettings.Format.IniFormat
        )
        return StudioController(self.app, settings)

    @staticmethod
    def table_for(controller: StudioController, source_id: str) -> dict:
        return next(
            table for table in controller._project["model"]["tables"]
            if table["source_id"] == source_id
        )

    def test_column_type_saves_reopens_and_replays_on_source_refresh(self) -> None:
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(
            self.source_path, parse_file(self.source_path)
        ))
        source_id = controller.activeTableId

        self.assertTrue(controller.setColumnType("Revenue", "whole_number"))
        table = self.table_for(controller, source_id)
        self.assertEqual(table["column_types"]["Revenue"], "whole_number")
        self.assertEqual(controller._rows, [
            {"Region": "East", "Revenue": "12"},
            {"Region": "West", "Revenue": "20"},
        ])

        project_path = self.root / "typed-project.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.activeTableId, source_id)
        self.assertEqual(
            self.table_for(reopened, source_id)["column_types"]["Revenue"],
            "whole_number",
        )
        self.assertEqual(reopened._rows[0]["Revenue"], "12")

        self.source_path.write_text(
            "Region,Revenue\nEast,12.00\nWest,20.00\nNorth,30.00\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual(reopened.rowCount, 3)
        self.assertEqual(reopened._rows[-1], {
            "Region": "North", "Revenue": "30",
        })
        self.assertEqual(
            self.table_for(reopened, source_id)["column_types"]["Revenue"],
            "whole_number",
        )

    def test_all_model_column_types_round_trip_and_replay_on_refresh(self) -> None:
        self.source_path.write_text(
            "Name,Whole,Decimal,Boolean,Date,DateTime,Time\n"
            "A,7,12.50,true,2026-10-08,2026-10-08T14:30:00,14:30:00\n",
            encoding="utf-8",
        )
        controller = self.controller("all-types-settings.ini")
        self.assertTrue(controller._commit_import(
            self.source_path, parse_file(self.source_path)
        ))
        source_id = controller.activeTableId

        model_types = {
            "Name": "text",
            "Whole": "whole_number",
            "Decimal": "decimal_number",
            "Boolean": "boolean",
            "Date": "date",
            "DateTime": "datetime",
            "Time": "time",
        }
        for column, type_name in model_types.items():
            self.assertTrue(controller.setColumnType(column, type_name), column)

        project_path = self.root / "all-types-project.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller("all-types-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(
            self.table_for(reopened, source_id)["column_types"], model_types
        )
        self.assertEqual(reopened._rows[0], {
            "Name": "A",
            "Whole": "7",
            "Decimal": "12.50",
            "Boolean": "true",
            "Date": "2026-10-08",
            "DateTime": "2026-10-08T14:30:00",
            "Time": "14:30:00",
        })

        self.source_path.write_text(
            "Name,Whole,Decimal,Boolean,Date,DateTime,Time\n"
            "B,8,13.25,false,2026-10-09,2026-10-09T16:00:00,16:00:00\n",
            encoding="utf-8",
        )
        reopened.refresh_source()
        self.assertEqual(reopened._rows[0], {
            "Name": "B",
            "Whole": "8",
            "Decimal": "13.25",
            "Boolean": "false",
            "Date": "2026-10-09",
            "DateTime": "2026-10-09T16:00:00",
            "Time": "16:00:00",
        })
        self.assertEqual(
            self.table_for(reopened, source_id)["column_types"], model_types
        )


if __name__ == "__main__":
    unittest.main()
