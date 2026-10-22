"""Acceptance checks for keeping multiple linked local tables in one project."""

from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QMessageBox

from analytics_studio.controller import StudioController
from analytics_studio.file_import import ImportCandidate, parse_file
from analytics_studio.transformations import apply_transformations


class MultipleLocalTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.sources = self.root / "sources"
        self.sources.mkdir()
        self.settings = QSettings(
            str(self.root / "settings.ini"), QSettings.Format.IniFormat
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self) -> StudioController:
        return StudioController(self.app, self.settings)

    def test_multiple_sources_switch_save_as_refresh_independently_and_reopen(self) -> None:
        sales_path = self.sources / "sales.csv"
        sales_path.write_text("id,revenue\n1,10\n", encoding="utf-8")
        regions_path = self.sources / "regions.csv"
        regions_path.write_text("region,count\nNorth,2\n", encoding="utf-8")

        controller = self.controller()
        self.assertTrue(controller._commit_import(sales_path, parse_file(sales_path)))
        sales_id = controller.activeTableId
        self.assertTrue(controller._commit_import(regions_path, parse_file(regions_path)))
        regions_id = controller.activeTableId

        self.assertNotEqual(sales_id, regions_id)
        self.assertEqual(len(controller._project["data_sources"]), 2)
        self.assertEqual(len(controller._project["model"]["tables"]), 2)
        self.assertEqual(controller._rows, [{"region": "North", "count": "2"}])
        self.assertTrue(controller.selectTable(sales_id))
        self.assertEqual(controller._rows, [{"id": "1", "revenue": "10"}])

        first_save = self.root / "projects" / "working.npa"
        first_save.parent.mkdir()
        self.assertTrue(controller._save_to(first_save))
        save_as = self.root / "archive" / "copy.npa"
        save_as.parent.mkdir()
        self.assertTrue(controller._save_to(save_as))

        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(save_as))
        self.assertEqual(reopened.activeTableId, sales_id)
        self.assertEqual(set(reopened._loaded_candidates), {sales_id, regions_id})
        self.assertEqual(len(reopened.tableCatalog), 2)

        sales_path.write_text("id,revenue\n1,15\n2,20\n", encoding="utf-8")
        regions_path.write_text("region,count\nNorth,3\nSouth,4\n", encoding="utf-8")

        # Refreshing the selected source leaves the other source's last result intact.
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [
            {"id": "1", "revenue": "15"},
            {"id": "2", "revenue": "20"},
        ])
        self.assertEqual(
            reopened._loaded_candidates[regions_id].rows,
            [{"region": "North", "count": "2"}],
        )

        self.assertTrue(reopened.selectTable(regions_id))
        reopened.refresh_source()
        self.assertEqual(reopened._rows, [
            {"region": "North", "count": "3"},
            {"region": "South", "count": "4"},
        ])
        self.assertEqual(
            reopened._loaded_candidates[sales_id].rows,
            [{"id": "1", "revenue": "15"}, {"id": "2", "revenue": "20"}],
        )

        # Importing the same linked path updates its existing table record.
        self.assertTrue(reopened._commit_import(regions_path, parse_file(regions_path)))
        self.assertEqual(reopened.activeTableId, regions_id)
        self.assertEqual(len(reopened._project["data_sources"]), 2)
        self.assertEqual(len(reopened._project["model"]["tables"]), 2)

        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            self.assertTrue(reopened.removeTable(regions_id))
        self.assertTrue(regions_path.exists())
        self.assertNotIn(regions_id, [
            source["id"] for source in reopened._project["data_sources"]
        ])
        self.assertEqual(reopened.activeTableId, sales_id)

        # A project with one missing linked source still opens its available table.
        regions_path.unlink()
        partial = self.controller()
        with patch.object(QMessageBox, "warning"):
            self.assertTrue(partial.open_project_path(save_as))
        self.assertEqual(partial.activeTableId, sales_id)
        self.assertTrue(partial.sourceLoaded)
        self.assertTrue(any(
            table["sourceId"] == regions_id and not table["loaded"]
            for table in partial.tableCatalog
        ))
        self.assertIn("regions.csv", partial.sourceWarning)

    def test_workbook_sheets_load_as_distinct_model_tables(self) -> None:
        workbook = self.sources / "ledger.xlsx"
        workbook.write_bytes(b"test workbook placeholder")
        controller = self.controller()

        def sheet(name: str, rows: list[dict[str, object]]) -> ImportCandidate:
            return ImportCandidate(
                "excel",
                ["Voucher", "Amount"],
                rows,
                {"sheet_name": name, "header_row": 1},
                [],
            )

        self.assertTrue(controller._commit_import(
            workbook, sheet("Sales", [{"Voucher": 1, "Amount": 100}])
        ))
        sales_id = controller.activeTableId
        self.assertTrue(controller._commit_import(
            workbook, sheet("Purchases", [{"Voucher": 2, "Amount": 40}])
        ))
        purchases_id = controller.activeTableId

        self.assertNotEqual(sales_id, purchases_id)
        self.assertEqual(len(controller._project["data_sources"]), 2)
        self.assertEqual(
            {table["name"] for table in controller._project["model"]["tables"]},
            {"Sales", "Purchases"},
        )
        self.assertEqual(controller._loaded_candidates[sales_id].rows[0]["Amount"], 100)
        self.assertEqual(controller._loaded_candidates[purchases_id].rows[0]["Amount"], 40)

        # Reimporting one sheet refreshes that table without replacing its sibling.
        self.assertTrue(controller._commit_import(
            workbook, sheet("Sales", [{"Voucher": 1, "Amount": 125}])
        ))
        self.assertEqual(controller.activeTableId, sales_id)
        self.assertEqual(len(controller._project["data_sources"]), 2)
        self.assertEqual(controller._loaded_candidates[sales_id].rows[0]["Amount"], 125)
        self.assertEqual(controller._loaded_candidates[purchases_id].rows[0]["Amount"], 40)

    def test_reimport_rejects_duplicate_key_on_active_relationship_one_side(self) -> None:
        workbook = self.sources / "linked-ledger.xlsx"
        workbook.write_bytes(b"test workbook placeholder")
        controller = self.controller()

        def sheet(name: str, rows: list[dict[str, object]]) -> ImportCandidate:
            return ImportCandidate(
                "excel",
                ["RegionID", "Value"],
                rows,
                {"sheet_name": name, "header_row": 1},
                [],
            )

        self.assertTrue(controller._commit_import(
            workbook,
            sheet("Regions", [
                {"RegionID": 1, "Value": "East"},
                {"RegionID": 2, "Value": "West"},
            ]),
        ))
        regions_id = controller.activeTableId
        self.assertTrue(controller._commit_import(
            workbook,
            sheet("Orders", [
                {"RegionID": 1, "Value": 10},
                {"RegionID": 1, "Value": 5},
                {"RegionID": 2, "Value": 20},
            ]),
        ))
        orders_id = controller.activeTableId
        relationship = controller._validate_relationship_candidate([{
            "relationship_version": 1,
            "id": "regions-orders",
            "from": "Regions[RegionID]",
            "to": "Orders[RegionID]",
            "from_table_id": regions_id,
            "from_column": "RegionID",
            "to_table_id": orders_id,
            "to_column": "RegionID",
            "cardinality": "one_to_many",
            "cross_filter_direction": "single",
            "is_active": True,
        }])
        controller._project["model"]["relationships"] = relationship
        project_before = deepcopy(controller._project)
        loaded_before = deepcopy(controller._loaded_candidates)
        raw_before = deepcopy(controller._raw_candidates)
        rows_before = deepcopy(controller._rows)
        active_before = (
            controller._active_source_id,
            controller._active_source_path,
            controller._active_source_kind,
            deepcopy(controller._active_parser_options),
            controller._dirty,
        )

        with patch("analytics_studio.controller.QMessageBox.critical") as show_error:
            imported = controller._commit_import(
                workbook,
                sheet("Regions", [
                    {"RegionID": 1, "Value": "East"},
                    {"RegionID": 1, "Value": "Duplicate"},
                ]),
            )

        self.assertFalse(imported)
        show_error.assert_called_once()
        self.assertEqual(controller.activeTableId, orders_id)
        self.assertEqual(controller._project, project_before)
        self.assertEqual(controller._loaded_candidates, loaded_before)
        self.assertEqual(controller._raw_candidates, raw_before)
        self.assertEqual(controller._rows, rows_before)
        self.assertEqual(
            (
                controller._active_source_id,
                controller._active_source_path,
                controller._active_source_kind,
                controller._active_parser_options,
                controller._dirty,
            ),
            active_before,
        )

    def test_transform_apply_rejects_duplicate_active_relationship_key_atomically(self) -> None:
        regions_path = self.sources / "regions.csv"
        regions_path.write_text(
            "RegionID,Region\n1,East\n2,West\n", encoding="utf-8"
        )
        orders_path = self.sources / "orders.csv"
        orders_path.write_text(
            "RegionID,Amount\n1,10\n1,5\n2,20\n", encoding="utf-8"
        )
        controller = self.controller()
        self.assertTrue(controller._commit_import(regions_path, parse_file(regions_path)))
        regions_id = str(controller.activeTableId)
        self.assertTrue(controller._commit_import(orders_path, parse_file(orders_path)))
        orders_id = str(controller.activeTableId)
        controller._project["model"]["relationships"] = (
            controller._validate_relationship_candidate([{
                "relationship_version": 1,
                "id": "regions-orders",
                "from": "Regions[RegionID]",
                "to": "Orders[RegionID]",
                "from_table_id": regions_id,
                "from_column": "RegionID",
                "to_table_id": orders_id,
                "to_column": "RegionID",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": True,
            }])
        )
        self.assertTrue(controller.selectTable(regions_id))
        self.assertTrue(controller.create_measure(
            "Order Amount", "SUM('Orders'[Amount])"
        ))
        controller.setRegionFilter("East")
        def measure_value() -> str:
            return next(
                item["value"] for item in controller.modelMeasures
                if item["name"] == "Order Amount"
            )
        self.assertEqual(measure_value(), "15")
        controller._dirty = False
        raw = controller._raw_candidates[regions_id]
        steps = [{
            "op": "replace_value",
            "column": "RegionID",
            "value": "2",
            "replacement": "1",
        }]
        transformed = apply_transformations(raw, steps)
        project_before = deepcopy(controller._project)
        loaded_before = deepcopy(controller._loaded_candidates)
        raw_before = deepcopy(controller._raw_candidates)
        rows_before = deepcopy(controller._rows)
        active_before = (
            controller._active_source_id,
            controller._active_source_path,
            controller._active_source_kind,
            deepcopy(controller._active_parser_options),
            controller._dirty,
        )

        applied = controller._commit_transform_steps(
            regions_id, steps, transformed, previewed_source=raw
        )

        self.assertFalse(applied)
        self.assertIn("no longer has unique values", controller.statusMessage)
        self.assertEqual(controller._project, project_before)
        self.assertEqual(controller._loaded_candidates, loaded_before)
        self.assertEqual(controller._raw_candidates, raw_before)
        self.assertEqual(controller._rows, rows_before)
        self.assertEqual(controller.activeTableId, regions_id)
        self.assertEqual(measure_value(), "15")
        self.assertEqual(controller.filterContextError, "")
        self.assertEqual(
            (
                controller._active_source_id,
                controller._active_source_path,
                controller._active_source_kind,
                controller._active_parser_options,
                controller._dirty,
            ),
            active_before,
        )


if __name__ == "__main__":
    unittest.main()
