"""Acceptance checks for typed report filters and relationship path errors."""

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


class TypedFilterLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

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

    def add_relationship(
        self,
        controller: StudioController,
        from_source: str,
        from_column: str,
        to_source: str,
        to_column: str,
    ) -> None:
        from_id = self.table_id(controller, from_source)
        to_id = self.table_id(controller, to_source)
        dialog = RelationshipDialog(
            controller._table_catalog,
            controller._project["model"].get("relationships", []),
            lambda items: controller._validate_relationship_candidate(items),
        )
        dialog._start_new()
        dialog.from_table.setCurrentIndex(dialog.from_table.findData(from_id))
        dialog.from_column.setCurrentIndex(dialog.from_column.findData(from_column))
        dialog.to_table.setCurrentIndex(dialog.to_table.findData(to_id))
        dialog.to_column.setCurrentIndex(dialog.to_column.findData(to_column))
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

    def test_typed_two_condition_filters_apply_and_replay_after_source_refresh(self) -> None:
        source_path = self.root / "Typed Sales.csv"
        source_path.write_text(
            "Name,Amount,Date,Timestamp,Clock,Enabled\n"
            "East A,10,2026-10-01,2026-10-01T09:00:00,09:00:00,true\n"
            "East B,20,2026-10-02,2026-10-02T10:00:00,10:00:00,true\n"
            "West A,30,2026-10-03,2026-10-03T11:00:00,11:00:00,false\n"
            "West B,40,2026-10-04,2026-10-04T12:00:00,12:00:00,false\n",
            encoding="utf-8",
        )
        controller = self.controller("typed-settings.ini")
        self.assertTrue(controller._commit_import(source_path, parse_file(source_path)))
        table_id = self.table_id(controller, source_path.name)

        column_types = {
            "Amount": "whole_number",
            "Date": "date",
            "Timestamp": "datetime",
            "Clock": "time",
            "Enabled": "boolean",
        }
        for column, type_name in column_types.items():
            self.assertTrue(controller.setColumnType(column, type_name), column)

        def operators(type_name: str) -> set[str]:
            return {item["value"] for item in controller.pageFilterOperators(type_name)}

        self.assertIn("contains", operators("text"))
        self.assertNotIn("contains", operators("whole_number"))
        self.assertIn("greater_than_or_equal", operators("date"))
        self.assertIn("relative_date", operators("date"))
        self.assertIn("relative_time", operators("datetime"))
        self.assertIn("greater_than_or_equal", operators("time"))
        self.assertIn("equals", operators("boolean"))
        self.assertNotIn("contains", operators("boolean"))

        self.assertTrue(controller.addPageFilterRule(
            table_id, "Name", "contains", "East", "begins_with", "West", "or"
        ))
        self.assertTrue(controller.addPageFilterRule(
            table_id, "Amount", "greater_than_or_equal", "20",
            "less_than_or_equal", "30", "and",
        ))
        self.assertTrue(controller.addPageFilterRule(
            table_id, "Date", "greater_than_or_equal", "2026-10-02",
            "less_than_or_equal", "2026-10-03", "and",
        ))
        self.assertTrue(controller.addPageFilterRule(
            table_id, "Timestamp", "greater_than_or_equal", "2026-10-02T10:00:00",
            "less_than_or_equal", "2026-10-03T11:00:00", "and",
        ))
        self.assertTrue(controller.addPageFilterRule(
            table_id, "Clock", "greater_than_or_equal", "10:00:00",
            "less_than_or_equal", "11:00:00", "and",
        ))
        self.assertTrue(controller.addPageFilterRule(
            table_id, "Enabled", "equals", "true", "", "", "and"
        ))
        self.assertEqual(controller.reportKpis["Revenue"], "20")
        self.assertEqual(len(controller.activePageFilters), 6)
        controller.selectVisual("Revenue KPI")
        self.assertTrue(controller.addVisualFilterRule(
            "Revenue KPI", table_id, "Amount", "greater_than_or_equal", "20",
            "less_than_or_equal", "30", "and",
        ))
        self.assertEqual(controller.visualKpis["Revenue KPI"], "20")
        self.assertEqual(controller.reportKpis["Revenue"], "20")

        self.assertFalse(controller.addPageFilterRule(
            table_id, "Amount", "greater_than", "20.5", "", "", "and"
        ))
        self.assertEqual(len(controller.activePageFilters), 6)

        project_path = self.root / "typed-filters.npa"
        self.assertTrue(controller._save_to(project_path))
        source_path.write_text(
            "Name,Amount,Date,Timestamp,Clock,Enabled\n"
            "East B,25,2026-10-02,2026-10-02T10:30:00,10:30:00,true\n"
            "West A,35,2026-10-03,2026-10-03T11:00:00,11:00:00,false\n",
            encoding="utf-8",
        )
        reopened = self.controller("typed-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Revenue"], "25")
        self.assertEqual(len(reopened.activePageFilters), 6)
        reopened.selectVisual("Revenue KPI")
        self.assertEqual(reopened.visualKpis["Revenue KPI"], "25")
        self.assertEqual(len(reopened.activeVisualFilters), 1)

    def test_ambiguous_active_relationship_paths_name_both_routes(self) -> None:
        regions_path = self.root / "Regions.csv"
        bridge_path = self.root / "RegionBridge.csv"
        orders_path = self.root / "Orders.csv"
        regions_path.write_text("RegionID,Region\n1,East\n2,West\n", encoding="utf-8")
        bridge_path.write_text("RegionID,BridgeID\n1,A\n2,B\n", encoding="utf-8")
        orders_path.write_text(
            "OrderID,RegionID,BridgeID,Amount\n100,1,A,10\n101,2,B,20\n",
            encoding="utf-8",
        )
        controller = self.controller("path-settings.ini")
        for path in (regions_path, bridge_path, orders_path):
            self.assertTrue(controller._commit_import(path, parse_file(path)))

        self.add_relationship(
            controller, regions_path.name, "RegionID", orders_path.name, "RegionID"
        )
        self.add_relationship(
            controller, regions_path.name, "RegionID", bridge_path.name, "RegionID"
        )
        self.add_relationship(
            controller, bridge_path.name, "BridgeID", orders_path.name, "BridgeID"
        )

        regions_id = self.table_id(controller, regions_path.name)
        self.assertEqual(controller.reportKpis["Revenue"], "30")
        self.assertTrue(controller.addPageFilter(regions_id, "Region", "East"))
        self.assertEqual(controller.reportKpis["Revenue"], "30")
        self.assertIn("Ambiguous active relationship paths", controller.filterContextError)
        self.assertIn("Regions → Orders", controller.filterContextError)
        self.assertIn("Regions → RegionBridge → Orders", controller.filterContextError)


if __name__ == "__main__":
    unittest.main()
