"""Acceptance checks for relationship create/edit/delete and project persistence."""

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


class RelationshipLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.dimension_path = self.root / "Regions.csv"
        self.facts_path = self.root / "Orders.csv"
        self.dimension_path.write_text(
            "RegionID,Region\n1,East\n2,West\n", encoding="utf-8"
        )
        self.facts_path.write_text(
            "OrderID,RegionID,Amount\n100,1,10\n101,1,5\n102,2,20\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def add_relationship(
        self, controller: StudioController, *, cross_filter: str = "both"
    ) -> dict:
        dialog = RelationshipDialog(
            controller._table_catalog,
            controller._project["model"].get("relationships", []),
            lambda items: controller._validate_relationship_candidate(items),
        )
        regions_id = next(
            source["id"] for source in controller._project["data_sources"]
            if source["name"] == self.dimension_path.name
        )
        orders_id = next(
            source["id"] for source in controller._project["data_sources"]
            if source["name"] == self.facts_path.name
        )
        dialog.from_table.setCurrentIndex(dialog.from_table.findData(regions_id))
        dialog.from_column.setCurrentIndex(dialog.from_column.findData("RegionID"))
        dialog.to_table.setCurrentIndex(dialog.to_table.findData(orders_id))
        dialog.to_column.setCurrentIndex(dialog.to_column.findData("RegionID"))
        dialog.cardinality.setCurrentIndex(dialog.cardinality.findData("one_to_many"))
        dialog.cross_filter.setCurrentIndex(
            dialog.cross_filter.findData(cross_filter)
        )
        dialog.active_check.setChecked(True)
        dialog._apply_form()

        def save_and_return() -> QDialog.DialogCode:
            dialog._save()
            return dialog.result()

        with (
            patch("analytics_studio.controller.RelationshipDialog", return_value=dialog),
            patch.object(dialog, "exec", side_effect=save_and_return),
        ):
            self.assertTrue(controller.manage_relationships())
        saved = controller._project["model"]["relationships"]
        self.assertEqual(len(saved), 1)
        dialog.deleteLater()
        return saved[0]

    def test_relationship_create_edit_delete_save_and_reopen(self) -> None:
        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(
            self.dimension_path, parse_file(self.dimension_path),
        ))
        self.assertTrue(controller._commit_import(
            self.facts_path, parse_file(self.facts_path),
        ))

        relationship = self.add_relationship(controller)
        self.assertEqual(relationship["cardinality"], "one_to_many")
        self.assertEqual(relationship["cross_filter_direction"], "both")
        self.assertTrue(relationship["is_active"])
        relationship_id = relationship["id"]

        project_path = self.root / "relationships.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller("reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(
            reopened._project["model"]["relationships"][0]["id"], relationship_id
        )

        edited_dialog = RelationshipDialog(
            reopened._table_catalog,
            reopened._project["model"]["relationships"],
            lambda items: reopened._validate_relationship_candidate(items),
        )
        edited_dialog.cross_filter.setCurrentIndex(
            edited_dialog.cross_filter.findData("single")
        )
        edited_dialog.active_check.setChecked(False)
        edited_dialog._apply_form()

        def save_edit() -> QDialog.DialogCode:
            edited_dialog._save()
            return edited_dialog.result()

        with (
            patch("analytics_studio.controller.RelationshipDialog", return_value=edited_dialog),
            patch.object(edited_dialog, "exec", side_effect=save_edit),
        ):
            self.assertTrue(reopened.manage_relationships())
        edited = reopened._project["model"]["relationships"][0]
        self.assertEqual(edited["id"], relationship_id)
        self.assertEqual(edited["cross_filter_direction"], "single")
        self.assertFalse(edited["is_active"])
        edited_dialog.deleteLater()

        deleted_dialog = RelationshipDialog(
            reopened._table_catalog,
            reopened._project["model"]["relationships"],
            lambda items: reopened._validate_relationship_candidate(items),
        )
        deleted_dialog._delete_selected()

        def save_delete() -> QDialog.DialogCode:
            deleted_dialog._save()
            return deleted_dialog.result()

        with (
            patch("analytics_studio.controller.RelationshipDialog", return_value=deleted_dialog),
            patch.object(deleted_dialog, "exec", side_effect=save_delete),
        ):
            self.assertTrue(reopened.manage_relationships())
        self.assertEqual(reopened._project["model"]["relationships"], [])
        deleted_dialog.deleteLater()

        self.assertTrue(reopened._save_to(project_path))
        final = self.controller("final-settings.ini")
        self.assertTrue(final.open_project_path(project_path))
        self.assertEqual(final._project["model"]["relationships"], [])

    def test_active_relationship_filters_a_qualified_measure_across_tables(self) -> None:
        controller = self.controller("measure-settings.ini")
        self.assertTrue(controller._commit_import(
            self.dimension_path, parse_file(self.dimension_path)
        ))
        regions_id = controller.activeTableId
        self.assertTrue(controller._commit_import(
            self.facts_path, parse_file(self.facts_path)
        ))
        relationship = self.add_relationship(controller, cross_filter="single")
        self.assertEqual(relationship["cross_filter_direction"], "single")

        self.assertTrue(controller.selectTable(regions_id))
        self.assertTrue(controller.create_measure(
            "Order Amount", "SUM('Orders'[Amount])"
        ))
        def amount_measure(app: StudioController) -> dict:
            return next(
                measure for measure in app.modelMeasures
                if measure["name"] == "Order Amount"
            )

        self.assertEqual(amount_measure(controller)["value"], "35")

        controller.setRegionFilter("East")
        self.assertEqual(amount_measure(controller)["value"], "15")

        project_path = self.root / "related-measure-project.npa"
        self.assertTrue(controller._save_to(project_path))
        self.facts_path.write_text(
            "OrderID,RegionID,Amount\n100,1,12\n101,1,5\n102,2,20\n",
            encoding="utf-8",
        )
        reopened = self.controller("related-measure-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        reopened.setRegionFilter("East")
        reopened_measure = next(
            measure for measure in reopened.modelMeasures
            if measure["name"] == "Order Amount"
        )
        self.assertEqual(reopened_measure["value"], "17")


if __name__ == "__main__":
    unittest.main()
