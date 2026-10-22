"""QML acceptance checks for a related-dimension Table visual."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QSettings, QUrl, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.relationship_dialog import RelationshipDialog

QQuickStyle.setStyle("Basic")


def _quick_items(root: QQuickItem):
    yield root
    for child in root.childItems():
        yield from _quick_items(child)


def _quick_item_named(root: QQuickItem, name: str) -> QQuickItem | None:
    return next((item for item in _quick_items(root) if item.objectName() == name), None)


class CrossTableTableVisualUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["cross-table table visual tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.qml_path = (
            Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _controller(self, *, orphan_fact_key: bool = False) -> tuple[
        StudioController, Path, Path, str, str
    ]:
        regions_path = self.root / "Regions.csv"
        regions_path.write_text(
            "RegionID,Region\n1,East\n2,West\n", encoding="utf-8"
        )
        orders_path = self.root / "Orders.csv"
        orders_rows = "100,1,10\n101,1,5\n102,2,20\n"
        if orphan_fact_key:
            orders_rows += "103,99,7\n"
        orders_path.write_text(
            "OrderID,RegionID,Amount\n" + orders_rows, encoding="utf-8"
        )
        settings = QSettings(
            str(self.root / "settings.ini"), QSettings.Format.IniFormat
        )
        controller = StudioController(self.app, settings)
        self.assertTrue(
            controller._commit_import(regions_path, parse_file(regions_path)),
            controller.statusMessage,
        )
        regions_id = str(controller.activeTableId)
        self.assertTrue(
            controller._commit_import(orders_path, parse_file(orders_path)),
            controller.statusMessage,
        )
        orders_id = str(controller.activeTableId)

        relationship_dialog = RelationshipDialog(
            controller._table_catalog,
            controller._project["model"].get("relationships", []),
            lambda items: controller._validate_relationship_candidate(items),
        )
        relationship_dialog.from_table.setCurrentIndex(
            relationship_dialog.from_table.findData(regions_id)
        )
        relationship_dialog.from_column.setCurrentIndex(
            relationship_dialog.from_column.findData("RegionID")
        )
        relationship_dialog.to_table.setCurrentIndex(
            relationship_dialog.to_table.findData(orders_id)
        )
        relationship_dialog.to_column.setCurrentIndex(
            relationship_dialog.to_column.findData("RegionID")
        )
        relationship_dialog.cardinality.setCurrentIndex(
            relationship_dialog.cardinality.findData("one_to_many")
        )
        relationship_dialog.cross_filter.setCurrentIndex(
            relationship_dialog.cross_filter.findData("single")
        )
        relationship_dialog.active_check.setChecked(True)
        relationship_dialog._apply_form()

        def save_relationship() -> QDialog.DialogCode:
            relationship_dialog._save()
            return relationship_dialog.result()

        with (
            patch(
                "analytics_studio.controller.RelationshipDialog",
                return_value=relationship_dialog,
            ),
            patch.object(relationship_dialog, "exec", side_effect=save_relationship),
        ):
            self.assertTrue(controller.manage_relationships(), controller.statusMessage)
        relationship_dialog.deleteLater()

        self.assertTrue(controller.selectTable(regions_id), controller.statusMessage)
        self.assertTrue(
            controller.create_measure("Order Amount", "SUM('Orders'[Amount])"),
            controller.statusMessage,
        )
        # Start on Orders so the UI test has to switch the report field selector
        # to the Regions dimension before adding its category field.
        self.assertTrue(controller.selectTable(orders_id), controller.statusMessage)
        controller.add_visual("table", "Orders by region", 40, 40, 480, 300)
        controller.selectVisual("Orders by region")
        controller.setCurrentView("Report")
        return controller, regions_path, orders_path, regions_id, orders_id

    def _load_main(self, controller: StudioController):
        engine = QQmlEngine()
        component = QQmlComponent(engine)
        component.loadUrl(QUrl.fromLocalFile(str(self.qml_path)))
        self.assertFalse(
            component.isError(), "\n".join(error.toString() for error in component.errors())
        )
        window = component.createWithInitialProperties({"studioController": controller})
        self.assertIsNotNone(
            window, "\n".join(error.toString() for error in component.errors())
        )
        window.resize(1400, 900)
        window.setProperty("dataPaneExpanded", True)
        window.show()
        self.app.processEvents()
        return engine, component, window

    def _click(self, window, item: QQuickItem) -> None:
        point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(round(point.x()), round(point.y())),
        )
        self.app.processEvents()

    def _add_report_field(self, window, field_binding: str) -> None:
        root = window.contentItem()
        field_list = _quick_item_named(root, "reportFieldsList")
        self.assertIsNotNone(field_list)
        select = _quick_item_named(field_list, "reportFieldSelect_" + field_binding)
        add = _quick_item_named(field_list, "reportFieldAdd_" + field_binding)
        self.assertIsNotNone(select, f"Report field {field_binding!r} is not shown.")
        self.assertIsNotNone(add, f"Report field {field_binding!r} has no Add control.")
        self._click(window, add)
        well_option = _quick_item_named(root, "reportFieldWell_Fields")
        self.assertIsNotNone(well_option, "The Table Fields well is not available.")
        self._click(window, well_option)

    def _select_regions_in_report_pane(
        self, window, controller: StudioController, regions_id: str
    ) -> QQuickItem:
        root = window.contentItem()
        table_selector = _quick_item_named(root, "reportTableSelector")
        field_list = _quick_item_named(root, "reportFieldsList")
        self.assertIsNotNone(table_selector)
        self.assertIsNotNone(field_list)
        self.assertEqual(controller.activeTableId, controller.tableCatalog[
            int(table_selector.property("currentIndex"))
        ]["sourceId"])

        table_selector.forceActiveFocus()
        for _ in range(len(controller.tableCatalog) + 1):
            if controller.activeTableId == regions_id:
                break
            current_index = int(table_selector.property("currentIndex"))
            tables = [
                table for table in controller.tableCatalog
                if table.get("loaded") and table.get("loadEnabled")
            ]
            region_index = next(
                index for index, table in enumerate(tables)
                if str(table["sourceId"]) == regions_id
            )
            key = Qt.Key.Key_Up if current_index > region_index else Qt.Key.Key_Down
            QTest.keyClick(window, key)
            self.app.processEvents()
        self.assertEqual(controller.activeTableId, regions_id)
        self.assertEqual(int(table_selector.property("currentIndex")), 0)

        field_labels = [
            str(item.property("text"))
            for item in _quick_items(field_list)
            if item.isVisible() and item.metaObject().indexOfProperty("text") >= 0
        ]
        self.assertTrue(
            any("Regions" in label for label in field_labels),
            f"The report field list should identify the Regions table: {field_labels!r}",
        )
        self.assertTrue(
            any("Region" in label for label in field_labels),
            f"The Region field should be shown: {field_labels!r}",
        )
        self.assertIsNotNone(
            _quick_item_named(field_list, "reportFieldSelect_Region"),
            "Region should be selectable from the report field list.",
        )
        return table_selector

    def test_report_table_uses_dimension_field_and_related_fact_measure(self) -> None:
        controller, _regions_path, _orders_path, regions_id, orders_id = self._controller()
        engine, component, window = self._load_main(controller)
        try:
            root = window.contentItem()
            self.assertEqual(controller.activeTableId, orders_id)
            self._add_report_field(window, "__dax_measure__:Order Amount")
            measure_visual = next(
                item for item in controller.activeVisualObjects
                if item["title"] == "Orders by region"
            )
            self.assertEqual(
                measure_visual.get("table_id"), orders_id,
                "The Table visual should anchor to the table used by its measure.",
            )
            table_selector = self._select_regions_in_report_pane(
                window, controller, regions_id
            )

            self._add_report_field(window, "Region")
            self.app.processEvents()

            visual = next(
                item for item in controller.activeVisualObjects
                if item["title"] == "Orders by region"
            )
            self.assertEqual(
                visual.get("table_id"), regions_id,
                "A cross-table Table visual should anchor to its saved dimension.",
            )
            self.assertEqual(
                visual["fields"].get("Fields"),
                [
                    "__dax_measure__:Order Amount",
                    {"table_id": regions_id, "column": "Region"},
                ],
            )
            field_well_labels = [
                str(item.property("text"))
                for item in _quick_items(root)
                if item.isVisible() and item.metaObject().indexOfProperty("text") >= 0
            ]
            self.assertTrue(
                any("Regions" in label and "Region" in label for label in field_well_labels),
                f"The visual field well should display the field's table identity: {field_well_labels!r}",
            )
            card = _quick_item_named(root, "tableCard_Orders by region")
            self.assertIsNotNone(card)
            rows = _quick_item_named(root, "tableRow_Orders by region_0")
            self.assertIsNotNone(rows)
            row_data = rows.property("rowData")
            self.assertEqual(list(row_data["values"]), ["15", "East"])
            second_row = _quick_item_named(root, "tableRow_Orders by region_1")
            self.assertIsNotNone(second_row)
            self.assertEqual(
                list(second_row.property("rowData")["values"]), ["20", "West"]
            )

            # The visual's saved dimension binding must remain its own context
            # when the global fields-pane selection changes back to Orders.
            table_selector.forceActiveFocus()
            QTest.keyClick(window, Qt.Key.Key_Down)
            self.app.processEvents()
            self.assertEqual(controller.activeTableId, orders_id)
            visual_after_table_switch = next(
                item for item in controller.activeVisualObjects
                if item["title"] == "Orders by region"
            )
            self.assertEqual(visual_after_table_switch.get("table_id"), regions_id)
            self.assertEqual(
                list(rows.property("rowData")["values"]), ["15", "East"]
            )
            self.assertEqual(
                list(second_row.property("rowData")["values"]), ["20", "West"]
            )

            remove_dimension = _quick_item_named(
                root, "visualFieldRemove_Fields_Region"
            )
            self.assertIsNotNone(remove_dimension)
            self.assertTrue(remove_dimension.isVisible())
            self.assertTrue(remove_dimension.isEnabled())
            self._click(window, remove_dimension)
            visual_after_removal = next(
                item for item in controller.activeVisualObjects
                if item["title"] == "Orders by region"
            )
            self.assertEqual(
                visual_after_removal["fields"]["Fields"],
                ["__dax_measure__:Order Amount"],
            )
        finally:
            controller._dirty = False
            window.close()
            window.deleteLater()
            component.deleteLater()
            engine.deleteLater()
            self.app.processEvents()

    def test_table_card_reports_inactive_relationship_instead_of_repeating_total(self) -> None:
        controller, _regions_path, _orders_path, regions_id, _orders_id = self._controller()
        controller._project["model"]["relationships"][0]["is_active"] = False
        controller._refresh_report()
        engine, component, window = self._load_main(controller)
        try:
            self._add_report_field(window, "__dax_measure__:Order Amount")
            self._select_regions_in_report_pane(window, controller, regions_id)
            self._add_report_field(window, "Region")
            self.app.processEvents()

            root = window.contentItem()
            card = _quick_item_named(root, "tableCard_Orders by region")
            self.assertIsNotNone(card)
            error = str(card.property("tableError") or "")
            self.assertTrue(
                "active relationship" in error.casefold()
                or "inactive relationship" in error.casefold(),
                f"Expected a readable relationship diagnostic, got {error!r}.",
            )
            self.assertEqual(controller.visualTableData("Orders by region")["rows"], [])
            self.assertIsNone(
                _quick_item_named(root, "tableRow_Orders by region_0")
            )
        finally:
            controller._dirty = False
            window.close()
            window.deleteLater()
            component.deleteLater()
            engine.deleteLater()
            self.app.processEvents()

    def test_table_card_explains_unmatched_fact_keys_without_partial_totals(self) -> None:
        controller, _regions_path, _orders_path, regions_id, _orders_id = self._controller(
            orphan_fact_key=True
        )
        engine, component, window = self._load_main(controller)
        try:
            self._add_report_field(window, "__dax_measure__:Order Amount")
            self._select_regions_in_report_pane(window, controller, regions_id)
            self._add_report_field(window, "Region")
            self.app.processEvents()

            root = window.contentItem()
            card = _quick_item_named(root, "tableCard_Orders by region")
            self.assertIsNotNone(card)
            error = str(card.property("tableError") or "")
            self.assertTrue(
                "unmatched" in error.casefold() or "orphan" in error.casefold(),
                f"Expected a readable unmatched-key diagnostic, got {error!r}.",
            )
            self.assertEqual(controller.visualTableData("Orders by region")["rows"], [])
            visible_error_text = [
                str(item.property("text"))
                for item in _quick_items(card)
                if item.isVisible() and item.metaObject().indexOfProperty("text") >= 0
            ]
            self.assertTrue(any(error in text for text in visible_error_text))
            self.assertIsNone(_quick_item_named(root, "tableRow_Orders by region_0"))
        finally:
            controller._dirty = False
            window.close()
            window.deleteLater()
            component.deleteLater()
            engine.deleteLater()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
