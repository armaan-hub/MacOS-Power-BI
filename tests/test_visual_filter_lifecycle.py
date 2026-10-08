"""Acceptance checks for saved visual-level filters."""

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
from analytics_studio.relationship_dialog import RelationshipDialog


class VisualFilterLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.sales_path = self.root / "Sales.csv"
        self.sales_path.write_text(
            "Date,Region,Revenue\n"
            "2026-08-01,East,10\n2026-08-02,East,20\n2026-08-03,West,5\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    @staticmethod
    def table_id(controller: StudioController, source_name: str) -> str:
        source_id = next(
            source["id"] for source in controller._project["data_sources"]
            if source["name"] == source_name
        )
        return next(
            table["id"] for table in controller._project["model"]["tables"]
            if table["source_id"] == source_id
        )

    @staticmethod
    def series_values(series: list[dict[str, str | float]]) -> dict[str, float]:
        return {str(item["label"]): float(item["value"]) for item in series}

    def test_visual_filters_are_isolated_editable_removable_and_persist_on_refresh(self) -> None:
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(self.sales_path, parse_file(self.sales_path)))
        table_id = self.table_id(controller, self.sales_path.name)
        self.assertEqual(controller.reportKpis["Revenue"], "35")

        controller.selectVisual("Revenue KPI")
        self.assertTrue(controller.addVisualFilter("Revenue KPI", table_id, "Region", "East"))
        self.assertEqual(controller.visualKpis["Revenue KPI"], "30")
        self.assertEqual(controller.reportKpis["Revenue"], "35")
        self.assertEqual(len(controller.activeVisualFilters), 1)

        controller.selectVisual("Monthly revenue")
        self.assertTrue(controller.addVisualFilter("Monthly revenue", table_id, "Region", "West"))
        self.assertEqual(
            self.series_values(controller.monthlySeriesForVisual("Monthly revenue")),
            {"2026-08": 5.0},
        )
        self.assertTrue(controller.addVisualFilter("Monthly revenue", table_id, "Region", "East"))
        self.assertEqual(
            self.series_values(controller.monthlySeriesForVisual("Monthly revenue")),
            {"2026-08": 30.0},
        )
        self.assertEqual(len(controller.activeVisualFilters), 1)
        self.assertTrue(controller.removeVisualFilter(int(controller.activeVisualFilters[0]["index"])))
        self.assertEqual(
            self.series_values(controller.monthlySeriesForVisual("Monthly revenue")),
            {"2026-08": 35.0},
        )
        self.assertTrue(controller.addVisualFilter("Monthly revenue", table_id, "Region", "West"))

        controller.selectVisual("Region revenue")
        self.assertEqual(
            self.series_values(controller.regionSeriesForVisual("Region revenue")),
            {"East": 30.0, "West": 5.0},
        )
        self.assertTrue(controller.addVisualFilter("Region revenue", table_id, "Region", "East"))
        self.assertEqual(
            self.series_values(controller.regionSeriesForVisual("Region revenue")),
            {"East": 30.0},
        )

        controller.add_page()
        controller.add_chart("Region revenue")
        self.assertEqual(controller.activeVisualFilters, [])
        self.assertEqual(
            self.series_values(controller.regionSeriesForVisual("Region revenue")),
            {"East": 30.0, "West": 5.0},
        )
        self.assertTrue(controller.addVisualFilter("Region revenue", table_id, "Region", "West"))
        self.assertEqual(
            self.series_values(controller.regionSeriesForVisual("Region revenue")),
            {"West": 5.0},
        )

        controller.setActivePage(0)
        project_path = self.root / "visual-filters.npa"
        self.assertTrue(controller._save_to(project_path))
        self.sales_path.write_text(
            "Date,Region,Revenue\n2026-08-04,East,12\n2026-08-05,West,18\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))

        reopened.selectVisual("Revenue KPI")
        self.assertEqual(reopened.visualKpis["Revenue KPI"], "12")
        self.assertEqual(reopened.reportKpis["Revenue"], "30")
        self.assertEqual(len(reopened.activeVisualFilters), 1)
        reopened.selectVisual("Monthly revenue")
        self.assertEqual(
            self.series_values(reopened.monthlySeriesForVisual("Monthly revenue")),
            {"2026-08": 18.0},
        )
        reopened.selectVisual("Region revenue")
        self.assertEqual(
            self.series_values(reopened.regionSeriesForVisual("Region revenue")),
            {"East": 12.0},
        )
        reopened.setActivePage(1)
        reopened.selectVisual("Region revenue")
        self.assertEqual(
            self.series_values(reopened.regionSeriesForVisual("Region revenue")),
            {"West": 18.0},
        )

    def test_visual_filter_propagates_from_dimension_to_measure_kpi_and_reopens(self) -> None:
        regions_path = self.root / "Regions.csv"
        orders_path = self.root / "Orders.csv"
        regions_path.write_text("RegionID,Region\n1,East\n2,West\n", encoding="utf-8")
        orders_path.write_text(
            "OrderID,RegionID,Amount\n100,1,10\n101,1,5\n102,2,20\n",
            encoding="utf-8",
        )
        controller = self.controller("relationship-settings.ini")
        self.assertTrue(controller._commit_import(regions_path, parse_file(regions_path)))
        self.assertTrue(controller._commit_import(orders_path, parse_file(orders_path)))
        regions_id = self.table_id(controller, regions_path.name)
        orders_id = self.table_id(controller, orders_path.name)

        dialog = RelationshipDialog(
            controller._table_catalog,
            controller._project["model"].get("relationships", []),
            lambda items: controller._validate_relationship_candidate(items),
        )
        dialog.from_table.setCurrentIndex(dialog.from_table.findData(regions_id))
        dialog.from_column.setCurrentIndex(dialog.from_column.findData("RegionID"))
        dialog.to_table.setCurrentIndex(dialog.to_table.findData(orders_id))
        dialog.to_column.setCurrentIndex(dialog.to_column.findData("RegionID"))
        dialog.cardinality.setCurrentIndex(dialog.cardinality.findData("one_to_many"))
        dialog.cross_filter.setCurrentIndex(dialog.cross_filter.findData("single"))
        dialog.active_check.setChecked(True)
        dialog._apply_form()

        def save_relationship() -> QDialog.DialogCode:
            dialog._save()
            return dialog.result()

        with (
            patch("analytics_studio.controller.RelationshipDialog", return_value=dialog),
            patch.object(dialog, "exec", side_effect=save_relationship),
        ):
            self.assertTrue(controller.manage_relationships())
        dialog.deleteLater()

        self.assertTrue(controller.create_measure("Total Amount", "SUM('Orders'[Amount])"))
        self.assertEqual(controller.reportKpis["Total Amount"], "35")
        visual_name = "Total Amount KPI"
        controller.selectVisual(visual_name)
        self.assertTrue(controller.addVisualFilter(visual_name, regions_id, "Region", "East"))
        self.assertEqual(controller.visualKpis[visual_name], "15")
        self.assertEqual(controller.reportKpis["Total Amount"], "35")

        project_path = self.root / "related-visual-filter.npa"
        self.assertTrue(controller._save_to(project_path))
        orders_path.write_text(
            "OrderID,RegionID,Amount\n103,1,7\n104,2,4\n", encoding="utf-8"
        )
        reopened = self.controller("relationship-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        reopened.selectVisual(visual_name)
        self.assertEqual(reopened.visualKpis[visual_name], "7")
        self.assertEqual(reopened.reportKpis["Total Amount"], "11")


if __name__ == "__main__":
    unittest.main()
