"""Acceptance checks for relationship create/edit/delete and project persistence."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.relationship_dialog import RelationshipDialog
from analytics_studio.relationships import (
    RelationshipError,
    _relationship_value_key,
    detect_relationship_candidates,
    propagate_relationship_filters,
)
from analytics_studio.power_query_values import PowerQueryCellError


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

    def test_relationship_keys_keep_null_and_empty_text_distinct_and_reject_errors(self) -> None:
        self.assertNotEqual(
            _relationship_value_key(None, "text"),
            _relationship_value_key("", "text"),
        )
        self.assertEqual(
            _relationship_value_key("A  ", "text"),
            _relationship_value_key("a", "text"),
        )
        self.assertNotEqual(
            _relationship_value_key(" A", "text"),
            _relationship_value_key("A", "text"),
        )
        self.assertNotEqual(
            _relationship_value_key("A\t", "text"),
            _relationship_value_key("A", "text"),
        )
        with self.assertRaisesRegex(RelationshipError, "Power Query cell error"):
            _relationship_value_key(
                PowerQueryCellError("DataFormat.Error", "not numeric", "bad", "whole_number", row=2),
                "whole_number",
            )

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    def add_relationship(
        self,
        controller: StudioController,
        *,
        cross_filter: str = "both",
        cardinality: str = "one_to_many",
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
        dialog.cardinality.setCurrentIndex(dialog.cardinality.findData(cardinality))
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

    def add_relationship_between(
        self,
        controller: StudioController,
        *,
        from_source_name: str,
        from_column: str,
        to_source_name: str,
        to_column: str,
        cardinality: str,
        cross_filter: str = "single",
    ) -> dict:
        dialog = RelationshipDialog(
            controller._table_catalog,
            controller._project["model"].get("relationships", []),
            lambda items: controller._validate_relationship_candidate(items),
        )
        source_ids = {
            str(source["name"]): str(source["id"])
            for source in controller._project["data_sources"]
        }
        dialog.from_table.setCurrentIndex(
            dialog.from_table.findData(source_ids[from_source_name])
        )
        dialog.from_column.setCurrentIndex(dialog.from_column.findData(from_column))
        dialog.to_table.setCurrentIndex(
            dialog.to_table.findData(source_ids[to_source_name])
        )
        dialog.to_column.setCurrentIndex(dialog.to_column.findData(to_column))
        dialog.cardinality.setCurrentIndex(dialog.cardinality.findData(cardinality))
        dialog.cross_filter.setCurrentIndex(dialog.cross_filter.findData(cross_filter))
        dialog.active_check.setChecked(True)
        dialog._apply_form()

        def save_and_return() -> QDialog.DialogCode:
            dialog._save()
            return dialog.result()

        with (
            patch("analytics_studio.controller.RelationshipDialog", return_value=dialog),
            patch.object(dialog, "exec", side_effect=save_and_return),
        ):
            self.assertTrue(controller.manage_relationships(), controller.statusMessage)
        saved = controller._project["model"]["relationships"]
        self.assertEqual(len(saved), 1)
        dialog.deleteLater()
        return saved[0]

    def test_many_to_many_dialog_saves_and_reopens_with_duplicate_keys(self) -> None:
        self.dimension_path.write_text(
            "RegionID,Region\n1,East\n1,East variant\n2,West\n",
            encoding="utf-8",
        )
        controller = self.controller("many-to-many-settings.ini")
        self.assertTrue(controller._commit_import(
            self.dimension_path, parse_file(self.dimension_path)
        ))
        self.assertTrue(controller._commit_import(
            self.facts_path, parse_file(self.facts_path)
        ))

        relationship = self.add_relationship(
            controller, cardinality="many_to_many", cross_filter="both"
        )
        self.assertEqual(relationship["cardinality"], "many_to_many")

        project_path = self.root / "many-to-many.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller("many-to-many-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(
            reopened._project["model"]["relationships"][0]["cardinality"],
            "many_to_many",
        )

    def test_many_to_many_measure_filter_reopens_and_refreshes(self) -> None:
        self.dimension_path.write_text(
            "RegionID,Region\n1,East\n1,East variant\n2,West\n",
            encoding="utf-8",
        )
        controller = self.controller("many-to-many-measure-settings.ini")
        self.assertTrue(controller._commit_import(
            self.dimension_path, parse_file(self.dimension_path)
        ))
        regions_id = str(controller.activeTableId)
        self.assertTrue(controller._commit_import(
            self.facts_path, parse_file(self.facts_path)
        ))
        self.add_relationship_between(
            controller,
            from_source_name=self.dimension_path.name,
            from_column="RegionID",
            to_source_name=self.facts_path.name,
            to_column="RegionID",
            cardinality="many_to_many",
            cross_filter="both",
        )
        orders_table = controller._model_table_for_source(
            controller._project, str(controller.activeTableId)
        )
        assert orders_table is not None
        orders_name = str(orders_table["name"])
        self.assertTrue(controller.create_measure(
            "Filtered order amount", f"SUM('{orders_name}'[Amount])"
        ), controller.statusMessage)
        self.assertTrue(controller.addPageFilterRule(
            regions_id, "Region", "equals", "East", "", "", "and"
        ), controller.statusMessage)
        self.assertEqual(controller.reportKpis["Filtered order amount"], "15")

        project_path = self.root / "many-to-many-measure.npa"
        self.assertTrue(controller._save_to(project_path))
        self.facts_path.write_text(
            "OrderID,RegionID,Amount\n100,1,12\n101,1,5\n102,2,20\n",
            encoding="utf-8",
        )
        reopened = self.controller("many-to-many-measure-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Filtered order amount"], "17")
        self.assertEqual(len(reopened.activePageFilters), 1)
        self.assertEqual(
            reopened._project["model"]["relationships"][0]["cardinality"],
            "many_to_many",
        )

        self.facts_path.write_text(
            "OrderID,RegionID,Amount\n100,1,14\n101,1,5\n102,2,20\n",
            encoding="utf-8",
        )
        reopened.refresh_all_sources()
        self.assertEqual(reopened.reportKpis["Filtered order amount"], "19")

    def test_one_to_one_regular_filter_measure_reopens_and_refreshes(self) -> None:
        self.facts_path.write_text(
            "OrderID,RegionID,Amount\n100,1,10\n101,2,20\n",
            encoding="utf-8",
        )
        controller = self.controller("one-to-one-measure-settings.ini")
        self.assertTrue(controller._commit_import(
            self.dimension_path, parse_file(self.dimension_path)
        ))
        regions_id = str(controller.activeTableId)
        self.assertTrue(controller._commit_import(
            self.facts_path, parse_file(self.facts_path)
        ))
        self.add_relationship_between(
            controller,
            from_source_name=self.dimension_path.name,
            from_column="RegionID",
            to_source_name=self.facts_path.name,
            to_column="RegionID",
            cardinality="one_to_one",
        )
        orders_table = controller._model_table_for_source(
            controller._project, str(controller.activeTableId)
        )
        assert orders_table is not None
        orders_name = str(orders_table["name"])
        self.assertTrue(controller.create_measure(
            "Filtered order amount", f"SUM('{orders_name}'[Amount])"
        ), controller.statusMessage)
        self.assertTrue(controller.addPageFilterRule(
            regions_id, "Region", "equals", "East", "", "", "and"
        ), controller.statusMessage)
        self.assertEqual(controller.reportKpis["Filtered order amount"], "10")

        project_path = self.root / "one-to-one-measure.npa"
        self.assertTrue(controller._save_to(project_path))
        self.facts_path.write_text(
            "OrderID,RegionID,Amount\n100,1,12\n101,2,20\n",
            encoding="utf-8",
        )
        reopened = self.controller("one-to-one-measure-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Filtered order amount"], "12")
        self.facts_path.write_text(
            "OrderID,RegionID,Amount\n100,1,13\n101,2,20\n",
            encoding="utf-8",
        )
        reopened.refresh_all_sources()
        self.assertEqual(reopened.reportKpis["Filtered order amount"], "13")

    def test_many_to_one_regular_filter_measure_reopens_and_refreshes(self) -> None:
        controller = self.controller("many-to-one-measure-settings.ini")
        self.assertTrue(controller._commit_import(
            self.dimension_path, parse_file(self.dimension_path)
        ))
        regions_id = str(controller.activeTableId)
        self.assertTrue(controller._commit_import(
            self.facts_path, parse_file(self.facts_path)
        ))
        orders_source_id = str(controller.activeTableId)
        self.add_relationship_between(
            controller,
            from_source_name=self.facts_path.name,
            from_column="RegionID",
            to_source_name=self.dimension_path.name,
            to_column="RegionID",
            cardinality="many_to_one",
        )
        orders_table = controller._model_table_for_source(
            controller._project, orders_source_id
        )
        assert orders_table is not None
        orders_name = str(orders_table["name"])
        self.assertTrue(controller.create_measure(
            "Filtered order amount", f"SUM('{orders_name}'[Amount])"
        ), controller.statusMessage)
        self.assertTrue(controller.addPageFilterRule(
            regions_id, "Region", "equals", "East", "", "", "and"
        ), controller.statusMessage)
        self.assertEqual(controller.reportKpis["Filtered order amount"], "15")

        project_path = self.root / "many-to-one-measure.npa"
        self.assertTrue(controller._save_to(project_path))
        self.facts_path.write_text(
            "OrderID,RegionID,Amount\n100,1,12\n101,1,5\n102,2,20\n",
            encoding="utf-8",
        )
        reopened = self.controller("many-to-one-measure-reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Filtered order amount"], "17")
        self.facts_path.write_text(
            "OrderID,RegionID,Amount\n100,1,13\n101,1,5\n102,2,20\n",
            encoding="utf-8",
        )
        reopened.refresh_all_sources()
        self.assertEqual(reopened.reportKpis["Filtered order amount"], "18")

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

    def test_text_relationship_keys_casefold_for_filtering_and_one_side_uniqueness(self) -> None:
        regions = {
            "id": "regions",
            "name": "Regions",
            "headers": ["RegionKey", "Region"],
            "column_types": {"RegionKey": "text", "Region": "text"},
            "rows": [
                {"RegionKey": "A  ", "Region": "East"},
                {"RegionKey": "B ", "Region": "West"},
            ],
            "filter_rows": [{"RegionKey": "A  ", "Region": "East"}],
        }
        orders = {
            "id": "orders",
            "name": "Orders",
            "headers": ["RegionKey", "Amount"],
            "column_types": {"RegionKey": "text", "Amount": "decimal_number"},
            "rows": [
                {"RegionKey": "a", "Amount": "10"},
                {"RegionKey": "b", "Amount": "20"},
            ],
        }
        relationship = {
            "relationship_version": 1,
            "id": "regions-orders",
            "from_table_id": "regions",
            "from_column": "RegionKey",
            "to_table_id": "orders",
            "to_column": "RegionKey",
            "cardinality": "one_to_many",
            "cross_filter_direction": "single",
            "is_active": True,
        }

        filtered = propagate_relationship_filters(
            [regions, orders], [relationship], {"regions"}
        )
        self.assertEqual(filtered["orders"], [orders["rows"][0]])

        colliding_dimension = {
            **regions,
            "rows": [
                {"RegionKey": "A", "Region": "East"},
                {"RegionKey": "a ", "Region": "East variant"},
            ],
            "filter_rows": [],
        }
        with self.assertRaisesRegex(RelationshipError, "no longer has unique values"):
            propagate_relationship_filters(
                [colliding_dimension, orders], [relationship], set()
            )

    def test_key_and_group_by_metadata_validate_and_survive_project_reopen(self) -> None:
        controller = self.controller("relationship-metadata-settings.ini")
        self.assertTrue(
            controller._commit_import(self.dimension_path, parse_file(self.dimension_path))
        )
        regions = controller.tableCatalog[0]
        table_id = str(regions["id"])

        self.assertTrue(controller.set_model_key_column(table_id, "RegionID"))
        self.assertEqual(
            controller._model_table_for_source(controller._project, regions["sourceId"])[
                "key_column"
            ],
            "RegionID",
        )

        from analytics_studio.group_by_columns_dialog import GroupByColumnsDialog

        group_dialog = GroupByColumnsDialog(
            "Regions", "Region", ["RegionID", "Region"], [],
            available_headers=["RegionID", "Region"],
        )
        group_dialog.columns.item(0).setCheckState(Qt.CheckState.Checked)
        with (
            patch("analytics_studio.controller.GroupByColumnsDialog", return_value=group_dialog),
            patch.object(group_dialog, "exec", return_value=QDialog.DialogCode.Accepted),
        ):
            self.assertTrue(controller.edit_model_column_group_by(table_id, "Region"))

        table = controller._model_table_for_source(controller._project, regions["sourceId"])
        self.assertEqual(table["group_by_columns"], {"Region": ["RegionID"]})
        self.assertEqual(
            next(item for item in controller.tableCatalog if item["id"] == table_id)[
                "groupByColumns"
            ],
            {"Region": ["RegionID"]},
        )

        duplicate_path = self.root / "Duplicate keys.csv"
        duplicate_path.write_text("Key,Value\nA,one\nA,two\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(duplicate_path, parse_file(duplicate_path)))
        duplicate_table = next(
            item for item in controller.tableCatalog if item["displayName"] == "Duplicate keys"
        )
        self.assertFalse(controller.set_model_key_column(str(duplicate_table["id"]), "Key"))
        self.assertIn("not unique", controller.statusMessage)

        project_path = self.root / "relationship-metadata.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller("relationship-metadata-reopen.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        saved_table = reopened._model_table_for_source(
            reopened._project, str(regions["sourceId"])
        )
        self.assertEqual(saved_table["key_column"], "RegionID")
        self.assertEqual(saved_table["group_by_columns"], {"Region": ["RegionID"]})

    def test_manage_relationships_passes_rea_metadata_into_detector_and_saves_suggestion(self) -> None:
        controller = self.controller("relationship-autodetect-settings.ini")
        self.assertTrue(
            controller._commit_import(self.dimension_path, parse_file(self.dimension_path))
        )
        regions = next(
            table for table in controller.tableCatalog if table["displayName"] == "Regions"
        )
        self.assertTrue(controller.set_model_key_column(str(regions["id"]), "RegionID"))
        model_table = controller._model_table_for_source(
            controller._project, str(regions["sourceId"])
        )
        model_table["group_by_columns"] = {"Region": ["RegionID"]}

        self.assertTrue(
            controller._commit_import(self.facts_path, parse_file(self.facts_path))
        )

        created_dialogs = []
        detector_calls = []

        def run_detector(detection_tables, current, target_tables=None):
            detector_calls.append((
                [dict(table) for table in detection_tables],
                list(current),
                target_tables,
            ))
            return detect_relationship_candidates(
                detection_tables, current, target_tables
            )

        class StagedAutoDetectDialog:
            def __init__(self, _tables, relationships, _validate, *, detect_candidates):
                self._relationships = list(relationships)
                self._detect_candidates = detect_candidates
                created_dialogs.append(self)

            def exec(self):
                self._relationships.extend(
                    self._detect_candidates(self._relationships)
                )
                return QDialog.DialogCode.Accepted

            @property
            def relationships(self):
                return self._relationships

        with (
            patch("analytics_studio.controller.RelationshipDialog", StagedAutoDetectDialog),
            patch(
                "analytics_studio.controller.detect_relationship_candidates",
                side_effect=run_detector,
            ),
        ):
            self.assertTrue(controller.manage_relationships(), controller.statusMessage)

        self.assertEqual(len(created_dialogs), 1)
        self.assertEqual(len(detector_calls), 1)
        detection_tables, current, scope = detector_calls[0]
        self.assertEqual(current, [])
        self.assertIsNone(scope)
        detected_regions = next(
            table for table in detection_tables if table["id"] == str(regions["id"])
        )
        self.assertEqual(detected_regions["key_column"], "RegionID")
        self.assertEqual(
            detected_regions["group_by_columns"], {"Region": ["RegionID"]}
        )
        saved = controller._project["model"]["relationships"]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["cardinality"], "many_to_one")
        self.assertEqual(saved[0]["from_column"], "RegionID")
        self.assertEqual(saved[0]["to_column"], "RegionID")

    def test_many_to_many_filters_duplicate_keys_in_both_directions(self) -> None:
        left_rows = [
            {"Key": "A", "Label": "left A"},
            {"Key": "B", "Label": "left B"},
            {"Key": "b", "Label": "left b"},
        ]
        right_rows = [
            {"Key": "A", "Value": 10},
            {"Key": "A", "Value": 15},
            {"Key": "B", "Value": 20},
            {"Key": "C", "Value": 30},
        ]
        left = {
            "id": "left",
            "name": "Left",
            "headers": ["Key", "Label"],
            "column_types": {"Key": "text", "Label": "text"},
            "rows": left_rows,
            "filter_rows": [left_rows[0]],
        }
        right = {
            "id": "right",
            "name": "Right",
            "headers": ["Key", "Value"],
            "column_types": {"Key": "text", "Value": "whole_number"},
            "rows": right_rows,
        }
        relationship = {
            "relationship_version": 1,
            "id": "left-right-many-to-many",
            "from_table_id": "left",
            "from_column": "Key",
            "to_table_id": "right",
            "to_column": "Key",
            "cardinality": "many_to_many",
            "cross_filter_direction": "both",
            "is_active": True,
        }

        filtered_from_left = propagate_relationship_filters(
            [left, right], [relationship], {"left"}
        )
        self.assertEqual(filtered_from_left["right"], right_rows[:2])

        right["filter_rows"] = [right_rows[2]]
        filtered_from_right = propagate_relationship_filters(
            [left, right], [relationship], {"right"}
        )
        self.assertEqual(filtered_from_right["left"], left_rows[1:])

    def test_any_relationship_keys_compare_native_values_without_text_coercion(self) -> None:
        mixed = {
            "id": "mixed",
            "name": "Mixed",
            "headers": ["Value"],
            "column_types": {"Value": "any"},
            "rows": [{"Value": "1"}, {"Value": Decimal("1")}],
            "filter_rows": [{"Value": "1"}],
        }
        facts = {
            "id": "facts",
            "name": "Facts",
            "headers": ["Value", "Amount"],
            "column_types": {"Value": "any", "Amount": "decimal_number"},
            "rows": [
                {"Value": "1", "Amount": Decimal("10")},
                {"Value": Decimal("1"), "Amount": Decimal("20")},
            ],
        }
        relationship = {
            "relationship_version": 1,
            "id": "mixed-facts",
            "from_table_id": "mixed",
            "from_column": "Value",
            "to_table_id": "facts",
            "to_column": "Value",
            "cardinality": "one_to_many",
            "cross_filter_direction": "single",
            "is_active": True,
        }

        filtered = propagate_relationship_filters([mixed, facts], [relationship], {"mixed"})

        self.assertEqual(filtered["facts"], [facts["rows"][0]])
        self.assertNotEqual(
            _relationship_value_key("1", "any"),
            _relationship_value_key(Decimal("1"), "any"),
        )

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
