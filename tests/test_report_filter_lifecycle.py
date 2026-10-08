"""Acceptance checks for report-wide filters and their interaction with pages."""

from __future__ import annotations

import json
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


class ReportFilterLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.regions_path = self.root / "Regions.csv"
        self.orders_path = self.root / "Orders.csv"
        self.regions_path.write_text(
            "RegionID,Region\n1,East\n2,West\n", encoding="utf-8"
        )
        self.orders_path.write_text(
            "OrderID,RegionID,Amount\n100,1,10\n101,1,5\n102,2,20\n",
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

    def add_single_direction_relationship(self, controller: StudioController) -> None:
        regions_id = self.table_id(controller, self.regions_path.name)
        orders_id = self.table_id(controller, self.orders_path.name)
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

    def test_report_filter_applies_to_every_page_and_relationship_and_clears(self) -> None:
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(
            self.regions_path, parse_file(self.regions_path)
        ))
        self.assertTrue(controller._commit_import(
            self.orders_path, parse_file(self.orders_path)
        ))
        self.assertTrue(controller.setColumnType("Amount", "whole_number"))
        self.add_single_direction_relationship(controller)
        regions_id = self.table_id(controller, self.regions_path.name)
        orders_id = self.table_id(controller, self.orders_path.name)

        self.assertEqual(controller.reportKpis["Revenue"], "35")
        self.assertTrue(controller.addReportFilterRule(
            regions_id, "Region", "equals", "East", "", "", "and"
        ))
        self.assertEqual(controller.reportKpis["Revenue"], "15")
        self.assertEqual(len(controller.activeReportFilters), 1)

        controller.add_page()
        second_page = controller.activePageIndex
        self.assertEqual(controller.reportKpis["Revenue"], "15")
        self.assertEqual(controller.activePageFilters, [])
        self.assertTrue(controller.addPageFilterRule(
            orders_id, "Amount", "greater_than_or_equal", "10", "", "", "and"
        ))
        self.assertEqual(controller.reportKpis["Revenue"], "10")
        controller.setActivePage(0)
        self.assertEqual(controller.reportKpis["Revenue"], "15")
        controller.setActivePage(second_page)
        self.assertEqual(controller.reportKpis["Revenue"], "10")

        project_path = self.root / "report-filters.npa"
        self.assertTrue(controller._save_to(project_path))
        self.orders_path.write_text(
            "OrderID,RegionID,Amount\n103,1,12\n104,1,8\n105,2,40\n",
            encoding="utf-8",
        )
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.activePageIndex, second_page)
        self.assertEqual(reopened.reportKpis["Revenue"], "12")
        reopened.setActivePage(0)
        self.assertEqual(reopened.reportKpis["Revenue"], "20")

        self.assertTrue(reopened.removeReportFilter(0))
        self.assertEqual(reopened.activeReportFilters, [])
        self.assertEqual(reopened.reportKpis["Revenue"], "60")
        self.assertTrue(reopened.addReportMultiValueFilter(
            regions_id, "Region", "is_none_of", json.dumps(["West"])
        ))
        self.assertEqual(reopened.reportKpis["Revenue"], "20")
        reopened.setActivePage(second_page)
        self.assertEqual(reopened.reportKpis["Revenue"], "12")

        reopened.clear_filters()
        self.assertEqual(reopened.activeReportFilters, [])
        self.assertEqual(reopened.activePageFilters, [])
        self.assertEqual(reopened.reportKpis["Revenue"], "60")
        reopened.setActivePage(0)
        self.assertEqual(reopened.reportKpis["Revenue"], "60")


if __name__ == "__main__":
    unittest.main()
