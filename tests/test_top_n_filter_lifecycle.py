"""Acceptance checks for visual Top N filters."""

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


class TopNFilterLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "Regional Sales.csv"
        self.source_path.write_text(
            "Region,Revenue,Segment\n"
            "North,40,Retail\nEast,30,Retail\nSouth,30,Retail\nWest,5,Retail\n"
            "North,5,Online\nEast,60,Online\nSouth,50,Online\nWest,40,Online\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    @staticmethod
    def table_id(controller: StudioController) -> str:
        source_id = controller.activeTableId
        return next(
            table["id"] for table in controller._project["model"]["tables"]
            if table["source_id"] == source_id
        )

    @staticmethod
    def series_values(series: list[dict[str, str | float]]) -> dict[str, float]:
        return {str(item["label"]): float(item["value"]) for item in series}

    def test_top_bottom_ties_page_interaction_save_reopen_and_removal(self) -> None:
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(
            self.source_path, parse_file(self.source_path)
        ))
        table_id = self.table_id(controller)
        self.assertTrue(controller.addPageFilter(table_id, "Segment", "Retail"))
        self.assertEqual(controller.reportKpis["Revenue"], "105")

        visual_name = "Region revenue"
        controller.selectVisual(visual_name)
        operators = {
            item["value"] for item in controller.visualFilterOperators(
                table_id, "Region", "text", visual_name
            )
        }
        self.assertIn("top_n", operators)
        self.assertTrue(any(item["column"] == "Revenue" for item in controller.topNOrderByFields))
        self.assertTrue(controller.addVisualTopNFilter(
            visual_name, table_id, "Region", "top", 2, "Revenue"
        ))
        self.assertEqual(
            self.series_values(controller.regionSeriesForVisual(visual_name)),
            {"East": 30.0, "North": 40.0},
        )
        self.assertEqual(controller.reportKpis["Revenue"], "105")

        self.assertTrue(controller.addVisualTopNFilter(
            visual_name, table_id, "Region", "bottom", 2, "Revenue"
        ))
        self.assertEqual(
            self.series_values(controller.regionSeriesForVisual(visual_name)),
            {"East": 30.0, "West": 5.0},
        )
        self.assertFalse(controller.addVisualTopNFilter(
            visual_name, table_id, "Region", "top", 0, "Revenue"
        ))
        self.assertFalse(controller.addVisualTopNFilter(
            visual_name, table_id, "Revenue", "top", 2, "Region"
        ))

        self.assertTrue(controller.addVisualTopNFilter(
            visual_name, table_id, "Region", "top", 2, "Revenue"
        ))
        project_path = self.root / "top-n-filter.npa"
        self.assertTrue(controller._save_to(project_path))
        self.source_path.write_text(
            "Region,Revenue,Segment\n"
            "North,20,Retail\nEast,60,Retail\nSouth,50,Retail\nWest,5,Retail\n"
            "North,5,Online\nEast,6,Online\nSouth,40,Online\nWest,70,Online\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        reopened.selectVisual(visual_name)
        self.assertEqual(reopened.reportKpis["Revenue"], "135")
        self.assertEqual(
            self.series_values(reopened.regionSeriesForVisual(visual_name)),
            {"East": 60.0, "South": 50.0},
        )

        reopened.addPageFilter(table_id, "Segment", "Online")
        self.assertEqual(reopened.reportKpis["Revenue"], "121")
        self.assertEqual(
            self.series_values(reopened.regionSeriesForVisual(visual_name)),
            {"South": 40.0, "West": 70.0},
        )
        self.assertEqual(len(reopened.activeVisualFilters), 1)
        self.assertTrue(reopened.removeVisualFilter(
            int(reopened.activeVisualFilters[0]["index"])
        ))
        self.assertEqual(
            self.series_values(reopened.regionSeriesForVisual(visual_name)),
            {"East": 6.0, "North": 5.0, "South": 40.0, "West": 70.0},
        )


if __name__ == "__main__":
    unittest.main()
