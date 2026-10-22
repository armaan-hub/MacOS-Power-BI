"""Acceptance checks for relationship-aware fields in a report Table visual."""

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


class CrossTableTableVisualLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(
            ["cross-table table visual tests"]
        )

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.regions_path = self.root / "Regions.csv"
        self.orders_path = self.root / "Orders.csv"
        self.regions_path.write_text(
            "RegionID,Region\n1,East\n2,West\n", encoding="utf-8"
        )
        self.orders_path.write_text(
            "OrderID,RegionID,Amount\n"
            "100,1,10\n101,1,5\n102,2,20\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str) -> StudioController:
        settings = QSettings(str(self.root / name), QSettings.Format.IniFormat)
        return StudioController(self.app, settings)

    @staticmethod
    def source_id(controller: StudioController, source_name: str) -> str:
        return str(next(
            source["id"]
            for source in controller._project["data_sources"]
            if source["name"] == source_name
        ))

    def import_sources(
        self,
        controller: StudioController,
        *paths: Path,
    ) -> None:
        for path in paths:
            self.assertTrue(
                controller._commit_import(path, parse_file(path)),
                controller.statusMessage,
            )

    def add_relationship(
        self,
        controller: StudioController,
        *,
        from_source: str,
        from_column: str,
        to_source: str,
        to_column: str,
        cardinality: str = "one_to_many",
        cross_filter: str = "single",
        active: bool = True,
    ) -> bool:
        dialog = RelationshipDialog(
            controller._table_catalog,
            controller._project["model"].get("relationships", []),
            lambda items: controller._validate_relationship_candidate(items),
        )
        if controller._project["model"].get("relationships"):
            dialog._start_new()

        source_ids = {
            str(source["name"]): str(source["id"])
            for source in controller._project["data_sources"]
        }
        dialog.from_table.setCurrentIndex(
            dialog.from_table.findData(source_ids[from_source])
        )
        dialog.from_column.setCurrentIndex(dialog.from_column.findData(from_column))
        dialog.to_table.setCurrentIndex(
            dialog.to_table.findData(source_ids[to_source])
        )
        dialog.to_column.setCurrentIndex(dialog.to_column.findData(to_column))
        dialog.cardinality.setCurrentIndex(dialog.cardinality.findData(cardinality))
        dialog.cross_filter.setCurrentIndex(
            dialog.cross_filter.findData(cross_filter)
        )
        dialog.active_check.setChecked(active)
        dialog._apply_form()

        def save_and_return() -> QDialog.DialogCode:
            dialog._save()
            return dialog.result()

        with (
            patch("analytics_studio.controller.RelationshipDialog", return_value=dialog),
            patch.object(dialog, "exec", side_effect=save_and_return),
        ):
            saved = controller.manage_relationships()
        dialog.deleteLater()
        return saved

    def add_order_amount_table_visual(
        self,
        controller: StudioController,
        *,
        regions_source_id: str,
        title: str = "Orders by region",
    ) -> None:
        orders_source_id = self.source_id(controller, self.orders_path.name)
        self.assertTrue(controller.selectTable(orders_source_id))
        orders_table = controller._model_table_for_source(
            controller._project, orders_source_id
        )
        self.assertIsNotNone(orders_table)
        expression = f"SUM('{orders_table['name']}'[Amount])"
        self.assertTrue(
            controller.create_measure("Order Amount", expression),
            controller.statusMessage,
        )

        controller.add_visual("table", title, 40, 40, 420, 240)
        controller.add_field_to_well(
            "Fields", "__dax_measure__:Order Amount"
        )
        # Pin the visual's measure context to Orders before choosing a field
        # from the related Regions table.
        self.assertTrue(controller.selectTable(orders_source_id))
        controller.selectVisual(title)
        controller.selectTable(regions_source_id)
        controller.add_field_to_well("Fields", "Region")

    @staticmethod
    def grouped_region_rows(data: dict[str, object]) -> dict[str, list[str]]:
        rows = data.get("rows", [])
        return {
            str(row["category"]): [str(value) for value in row["values"]]
            for row in rows
        }

    def test_related_region_column_groups_qualified_measure_across_lifecycle(self) -> None:
        controller = self.controller("cross-table-settings.ini")
        self.import_sources(controller, self.regions_path, self.orders_path)
        regions_id = self.source_id(controller, self.regions_path.name)
        orders_id = self.source_id(controller, self.orders_path.name)

        self.assertTrue(self.add_relationship(
            controller,
            from_source=self.regions_path.name,
            from_column="RegionID",
            to_source=self.orders_path.name,
            to_column="RegionID",
            cardinality="one_to_many",
            cross_filter="single",
        ))
        self.assertEqual(
            controller._project["model"]["relationships"][0]["cross_filter_direction"],
            "single",
        )
        self.add_order_amount_table_visual(
            controller, regions_source_id=regions_id
        )

        expected = {
            "East": ["15", "East"],
            "West": ["20", "West"],
        }
        data = controller.visualTableData("Orders by region")
        self.assertEqual(data["columns"], ["Order Amount", "Region"])
        self.assertEqual(self.grouped_region_rows(data), expected)
        self.assertEqual(data["total_rows"], 2)
        self.assertEqual(controller.visualErrorMessage("Orders by region"), "")

        # The report field selector changes the active table. That choice must
        # not change the bound measure or its relationship context.
        for source_id in (orders_id, regions_id, orders_id):
            self.assertTrue(controller.selectTable(source_id))
            self.assertEqual(
                self.grouped_region_rows(
                    controller.visualTableData("Orders by region")
                ),
                expected,
            )

        project_path = self.root / "cross-table-visual.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller("cross-table-reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        for source_id in (regions_id, orders_id):
            self.assertTrue(reopened.selectTable(source_id))
            self.assertEqual(
                self.grouped_region_rows(
                    reopened.visualTableData("Orders by region")
                ),
                expected,
            )

        self.orders_path.write_text(
            "OrderID,RegionID,Amount\n"
            "100,1,12\n101,1,5\n102,2,25\n",
            encoding="utf-8",
        )
        reopened.refresh_all_sources()
        refreshed = reopened.visualTableData("Orders by region")
        self.assertEqual(refreshed["columns"], ["Order Amount", "Region"])
        self.assertEqual(
            self.grouped_region_rows(refreshed),
            {"East": ["17", "East"], "West": ["25", "West"]},
        )

    def test_dimension_first_binding_is_qualified_and_survives_reopen(self) -> None:
        controller = self.controller("dimension-first-settings.ini")
        self.import_sources(controller, self.regions_path, self.orders_path)
        regions_id = self.source_id(controller, self.regions_path.name)
        self.assertTrue(self.add_relationship(
            controller,
            from_source=self.regions_path.name,
            from_column="RegionID",
            to_source=self.orders_path.name,
            to_column="RegionID",
        ))
        self.assertTrue(controller.selectTable(regions_id))
        self.assertTrue(
            controller.create_measure("Order Amount", "SUM('Orders'[Amount])")
        )
        controller.add_visual("table", "Dimension first", 40, 40, 420, 240)
        controller.add_field_to_well("Fields", "Region")
        controller.add_field_to_well("Fields", "__dax_measure__:Order Amount")

        visual = next(
            item for item in controller.activeVisualObjects
            if item["title"] == "Dimension first"
        )
        self.assertEqual(visual.get("table_id"), regions_id)
        self.assertEqual(
            visual["fields"]["Fields"],
            [
                {"table_id": regions_id, "column": "Region"},
                "__dax_measure__:Order Amount",
            ],
        )
        self.assertEqual(
            self.grouped_region_rows(controller.visualTableData("Dimension first")),
            {"East": ["East", "15"], "West": ["West", "20"]},
        )

        project_path = self.root / "dimension-first.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller("dimension-first-reopened-settings.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(
            self.grouped_region_rows(reopened.visualTableData("Dimension first")),
            {"East": ["East", "15"], "West": ["West", "20"]},
        )

    def test_inactive_relationship_cannot_render_a_cross_table_group(self) -> None:
        controller = self.controller("inactive-relationship-settings.ini")
        self.import_sources(controller, self.regions_path, self.orders_path)
        regions_id = self.source_id(controller, self.regions_path.name)
        self.assertTrue(self.add_relationship(
            controller,
            from_source=self.regions_path.name,
            from_column="RegionID",
            to_source=self.orders_path.name,
            to_column="RegionID",
            active=False,
        ))
        self.add_order_amount_table_visual(
            controller, regions_source_id=regions_id
        )

        data = controller.visualTableData("Orders by region")
        field_was_rejected = "Region" not in data["columns"]
        render_was_rejected = bool(data.get("error")) and (
            "relationship" in str(data["error"]).casefold()
            or "active" in str(data["error"]).casefold()
        )
        self.assertTrue(
            field_was_rejected or render_was_rejected,
            f"Inactive relationship silently produced a visual: {data!r}",
        )
        if field_was_rejected:
            self.assertTrue(
                "relationship" in controller.statusMessage.casefold()
                or "active" in controller.statusMessage.casefold(),
                controller.statusMessage,
            )
        else:
            self.assertEqual(data["rows"], [])

    def test_unmatched_fact_key_never_silently_disappears_from_grouping(self) -> None:
        controller = self.controller("orphan-key-settings.ini")
        self.import_sources(controller, self.regions_path, self.orders_path)
        regions_id = self.source_id(controller, self.regions_path.name)
        self.assertTrue(self.add_relationship(
            controller,
            from_source=self.regions_path.name,
            from_column="RegionID",
            to_source=self.orders_path.name,
            to_column="RegionID",
        ))
        self.add_order_amount_table_visual(
            controller, regions_source_id=regions_id
        )
        prior_data = controller.visualTableData("Orders by region")
        prior_rows = self.grouped_region_rows(prior_data)
        self.assertEqual(prior_rows, {"East": ["15", "East"], "West": ["20", "West"]})

        self.orders_path.write_text(
            "OrderID,RegionID,Amount\n"
            "100,1,10\n101,1,5\n102,2,20\n103,99,900\n",
            encoding="utf-8",
        )
        with patch("analytics_studio.controller.QMessageBox.critical"):
            controller.refresh_all_sources()

        data = controller.visualTableData("Orders by region")
        if data.get("error"):
            self.assertEqual(data["rows"], [])
            self.assertRegex(
                str(data["error"]).casefold(),
                r"unmatched|orphan|key|relationship|region",
            )
        else:
            # A refresh-time rejection may retain the prior valid snapshot, but
            # must explain why it did not apply the source containing key 99.
            self.assertEqual(data, prior_data)
            self.assertRegex(
                controller.sourceWarning.casefold(),
                r"could not refresh|unmatched|orphan|key|relationship",
            )

    def test_duplicate_dimension_key_is_rejected_by_relationship_workflow(self) -> None:
        self.regions_path.write_text(
            "RegionID,Region\n1,East\n1,East duplicate\n2,West\n",
            encoding="utf-8",
        )
        controller = self.controller("duplicate-key-settings.ini")
        self.import_sources(controller, self.regions_path, self.orders_path)

        with patch("analytics_studio.relationship_dialog.QMessageBox.warning") as warning:
            saved = self.add_relationship(
                controller,
                from_source=self.regions_path.name,
                from_column="RegionID",
                to_source=self.orders_path.name,
                to_column="RegionID",
            )

        self.assertFalse(saved)
        self.assertEqual(controller._project["model"]["relationships"], [])
        self.assertTrue(warning.called)
        self.assertRegex(str(warning.call_args.args[2]).casefold(), r"unique|duplicate")

    def test_ambiguous_active_paths_do_not_render_partial_grouping(self) -> None:
        bridge_path = self.root / "RegionBridge.csv"
        bridge_path.write_text(
            "RegionID,OrderRegionID\n1,1\n2,2\n", encoding="utf-8"
        )
        controller = self.controller("ambiguous-path-settings.ini")
        self.import_sources(
            controller, self.regions_path, self.orders_path, bridge_path
        )
        regions_id = self.source_id(controller, self.regions_path.name)

        relationships = (
            (self.regions_path.name, "RegionID", self.orders_path.name, "RegionID"),
            (self.regions_path.name, "RegionID", bridge_path.name, "RegionID"),
            (bridge_path.name, "OrderRegionID", self.orders_path.name, "RegionID"),
        )
        for from_source, from_column, to_source, to_column in relationships:
            self.assertTrue(self.add_relationship(
                controller,
                from_source=from_source,
                from_column=from_column,
                to_source=to_source,
                to_column=to_column,
            ), controller.statusMessage)

        self.add_order_amount_table_visual(
            controller, regions_source_id=regions_id
        )
        data = controller.visualTableData("Orders by region")
        if data.get("error"):
            self.assertEqual(data["rows"], [])
            self.assertRegex(
                str(data["error"]).casefold(), r"ambiguous|path|relationship"
            )
        else:
            self.assertNotEqual(
                self.grouped_region_rows(data),
                {"East": ["15", "East"], "West": ["20", "West"]},
                "Ambiguous paths must not silently produce plausible totals.",
            )
            self.assertRegex(
                controller.statusMessage.casefold(), r"ambiguous|path|relationship"
            )

    def test_bidirectional_and_many_to_many_paths_fail_closed(self) -> None:
        for index, (cardinality, cross_filter) in enumerate((
            ("one_to_many", "both"),
            ("many_to_many", "single"),
        )):
            with self.subTest(cardinality=cardinality, cross_filter=cross_filter):
                controller = self.controller(f"unsupported-relationship-{index}.ini")
                self.import_sources(controller, self.regions_path, self.orders_path)
                regions_id = self.source_id(controller, self.regions_path.name)
                self.assertTrue(self.add_relationship(
                    controller,
                    from_source=self.regions_path.name,
                    from_column="RegionID",
                    to_source=self.orders_path.name,
                    to_column="RegionID",
                    cardinality=cardinality,
                    cross_filter=cross_filter,
                ))
                self.add_order_amount_table_visual(
                    controller, regions_source_id=regions_id
                )

                data = controller.visualTableData("Orders by region")
                self.assertEqual(data["rows"], [])
                self.assertRegex(
                    str(data.get("error", "")).casefold(),
                    r"relationship|single.direction|one.to.many",
                )

    def test_blank_dimension_and_fact_keys_fail_closed(self) -> None:
        for index, blank_side in enumerate(("dimension", "fact")):
            with self.subTest(blank_side=blank_side):
                if blank_side == "dimension":
                    self.regions_path.write_text(
                        "RegionID,Region\n,Unassigned\n1,East\n2,West\n",
                        encoding="utf-8",
                    )
                else:
                    self.orders_path.write_text(
                        "OrderID,RegionID,Amount\n"
                        "100,1,10\n101,1,5\n102,2,20\n103,,7\n",
                        encoding="utf-8",
                    )
                controller = self.controller(f"blank-{blank_side}-{index}.ini")
                self.import_sources(controller, self.regions_path, self.orders_path)
                regions_id = self.source_id(controller, self.regions_path.name)
                self.assertTrue(self.add_relationship(
                    controller,
                    from_source=self.regions_path.name,
                    from_column="RegionID",
                    to_source=self.orders_path.name,
                    to_column="RegionID",
                ))
                self.add_order_amount_table_visual(
                    controller, regions_source_id=regions_id
                )

                data = controller.visualTableData("Orders by region")
                self.assertEqual(data["rows"], [])
                self.assertIn("blank", str(data.get("error", "")).casefold())

    def test_unqualified_measure_uses_its_home_table_for_related_grouping(self) -> None:
        controller = self.controller("unqualified-measure-settings.ini")
        self.import_sources(controller, self.regions_path, self.orders_path)
        regions_id = self.source_id(controller, self.regions_path.name)
        orders_id = self.source_id(controller, self.orders_path.name)
        self.assertTrue(self.add_relationship(
            controller,
            from_source=self.regions_path.name,
            from_column="RegionID",
            to_source=self.orders_path.name,
            to_column="RegionID",
        ))
        self.assertTrue(controller.selectTable(orders_id))
        self.assertTrue(
            controller.create_measure("Loose Amount", "SUM('Orders'[Amount])")
        )
        controller.add_visual("table", "Loose amount by region", 40, 40, 420, 240)
        controller.add_field_to_well("Fields", "__dax_measure__:Loose Amount")
        controller.selectVisual("Loose amount by region")
        self.assertTrue(controller.selectTable(regions_id))
        next(
            measure
            for measure in controller._project["model"]["measures"]
            if measure["name"] == "Loose Amount"
        )["expression"] = "SUM([Amount])"
        controller.add_field_to_well("Fields", "Region")

        data = controller.visualTableData("Loose amount by region")
        self.assertEqual(data["columns"], ["Loose Amount", "Region"])
        self.assertEqual(self.grouped_region_rows(data), {
            "East": ["15", "East"],
            "West": ["20", "West"],
        })
        self.assertEqual(controller.visualErrorMessage("Loose amount by region"), "")

    def test_related_table_fields_are_rejected_on_non_table_visuals(self) -> None:
        controller = self.controller("cross-table-non-table-settings.ini")
        self.import_sources(controller, self.regions_path, self.orders_path)
        regions_id = self.source_id(controller, self.regions_path.name)
        orders_id = self.source_id(controller, self.orders_path.name)
        self.assertTrue(self.add_relationship(
            controller,
            from_source=self.regions_path.name,
            from_column="RegionID",
            to_source=self.orders_path.name,
            to_column="RegionID",
        ))
        self.assertTrue(controller.selectTable(orders_id))
        self.assertTrue(
            controller.create_measure("Order Amount", "SUM('Orders'[Amount])")
        )
        controller.add_visual("column", "Orders chart", 40, 40, 420, 240)
        controller.selectVisual("Orders chart")
        controller.add_field_to_well("X-axis", "OrderID")
        fields_before = next(
            item for item in controller.activeVisualObjects
            if item["title"] == "Orders chart"
        )["fields"]["X-axis"][:]

        self.assertTrue(controller.selectTable(regions_id))
        controller.add_field_to_well("X-axis", "Region")
        self.assertIn("only for a Table visual", controller.statusMessage)
        visual = next(
            item for item in controller.activeVisualObjects
            if item["title"] == "Orders chart"
        )
        self.assertEqual(visual.get("table_id"), orders_id)
        self.assertEqual(visual["fields"]["X-axis"], fields_before)

    def test_multiple_related_measures_fail_closed_with_orphan_fact_keys(self) -> None:
        self.orders_path.write_text(
            "OrderID,RegionID,Amount\n"
            "100,1,10\n101,1,5\n102,2,20\n103,99,900\n",
            encoding="utf-8",
        )
        controller = self.controller("multiple-measures-settings.ini")
        self.import_sources(controller, self.regions_path, self.orders_path)
        regions_id = self.source_id(controller, self.regions_path.name)
        self.assertTrue(self.add_relationship(
            controller,
            from_source=self.regions_path.name,
            from_column="RegionID",
            to_source=self.orders_path.name,
            to_column="RegionID",
        ))
        self.assertTrue(controller.selectTable(regions_id))
        for name in ("Order Amount", "Order Amount Copy"):
            self.assertTrue(
                controller.create_measure(name, "SUM('Orders'[Amount])")
            )
        controller.add_visual("table", "Two measures", 40, 40, 420, 240)
        controller.add_field_to_well("Fields", "Region")
        controller.add_field_to_well("Fields", "__dax_measure__:Order Amount")
        controller.add_field_to_well("Fields", "__dax_measure__:Order Amount Copy")

        data = controller.visualTableData("Two measures")
        self.assertEqual(data["rows"], [])
        self.assertRegex(str(data.get("error", "")).casefold(), r"one dimension field and one measure")


if __name__ == "__main__":
    unittest.main()
