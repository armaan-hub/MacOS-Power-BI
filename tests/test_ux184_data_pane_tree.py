"""Acceptance tests for Task 184: Data pane grouped and collapsible table tree."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QSettings, QUrl, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file

QQuickStyle.setStyle("Basic")


def _quick_items(root: QQuickItem):
    yield root
    for child in root.childItems():
        yield from _quick_items(child)


def _quick_item_named(root: QQuickItem, name: str) -> QQuickItem | None:
    return next((item for item in _quick_items(root) if item.objectName() == name), None)


class Ux184DataPaneTreeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["ux-184 data pane tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.qml_path = (
            Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml"
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _setup_controller(self) -> tuple[StudioController, str, str]:
        customers_path = self.root / "Customers.csv"
        customers_path.write_text("CustomerID,CustomerName\n1,Alice\n2,Bob\n", encoding="utf-8")
        orders_path = self.root / "Orders.csv"
        orders_path.write_text("OrderID,CustomerID,Amount\n101,1,10\n102,2,20\n", encoding="utf-8")

        settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        controller = StudioController(self.app, settings)

        self.assertTrue(controller._commit_import(orders_path, parse_file(orders_path)))
        orders_id = str(controller.activeTableId)
        self.assertTrue(controller._commit_import(customers_path, parse_file(customers_path)))
        customers_id = str(controller.activeTableId)

        # Create a measure on Orders table
        self.assertTrue(controller.selectTable(orders_id))
        self.assertTrue(controller.create_measure("Total Amount", "SUM('Orders'[Amount])"))

        return controller, orders_id, customers_id

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

    def test_field_tree_controller_contract(self) -> None:
        controller, orders_id, customers_id = self._setup_controller()

        # fieldTree lists both tables A–Z with their columns and measures under home table
        tree = controller.fieldTree
        self.assertEqual(len(tree), 2)
        table_names = [t["table"] for t in tree]
        self.assertEqual(table_names, ["Customers", "Orders"])

        customers_entry = next(t for t in tree if t["table"] == "Customers")
        orders_entry = next(t for t in tree if t["table"] == "Orders")

        self.assertIn("CustomerID", [f["label"] for f in customers_entry["fields"]])
        self.assertIn("CustomerName", [f["label"] for f in customers_entry["fields"]])

        order_field_labels = [f["label"] for f in orders_entry["fields"]]
        self.assertIn("Amount", order_field_labels)
        self.assertIn("OrderID", order_field_labels)
        self.assertIn("Total Amount", order_field_labels)

        measure_field = next(f for f in orders_entry["fields"] if f["label"] == "Total Amount")
        self.assertEqual(measure_field["kind"], "measure")
        self.assertEqual(measure_field["binding"], "__dax_measure__:Total Amount")

        # setTableExpanded toggles expanded
        controller.setTableExpanded(customers_id, True)
        self.assertTrue(any(t["tableId"] == customers_id and t["expanded"] for t in controller.fieldTree))
        controller.setTableExpanded(customers_id, False)
        self.assertFalse(any(t["tableId"] == customers_id and t["expanded"] for t in controller.fieldTree))

        # A search query keeps only the matching table, expanded
        controller.setFieldQuery("CustomerName")
        filtered_tree = controller.fieldTree
        self.assertEqual(len(filtered_tree), 1)
        self.assertEqual(filtered_tree[0]["table"], "Customers")
        self.assertTrue(filtered_tree[0]["expanded"])
        controller.setFieldQuery("")

        # toggleFieldInVisual(binding, True) with selected visual adds field, inVisual becomes True. False removes it.
        controller.add_visual("table", "Test Visual", 50, 50, 300, 200)
        controller.selectVisual("Test Visual")

        # Initially inVisual is False
        tree = controller.fieldTree
        orders_entry = next(t for t in tree if t["table"] == "Orders")
        amount_field = next(f for f in orders_entry["fields"] if f["label"] == "Amount")
        self.assertFalse(amount_field["inVisual"])

        controller.toggleFieldInVisual("Amount", True)
        tree = controller.fieldTree
        orders_entry = next(t for t in tree if t["table"] == "Orders")
        amount_field = next(f for f in orders_entry["fields"] if f["label"] == "Amount")
        self.assertTrue(amount_field["inVisual"])

        controller.toggleFieldInVisual("Amount", False)
        tree = controller.fieldTree
        orders_entry = next(t for t in tree if t["table"] == "Orders")
        amount_field = next(f for f in orders_entry["fields"] if f["label"] == "Amount")
        self.assertFalse(amount_field["inVisual"])

    def test_qml_tree_elements_and_chevron_expansion(self) -> None:
        controller, orders_id, customers_id = self._setup_controller()
        controller.selectTable(orders_id)
        controller.setCurrentView("Report")

        engine, component, window = self._load_main(controller)
        root = window.contentItem()
        field_list = _quick_item_named(root, "reportFieldsList")
        self.assertIsNotNone(field_list)

        # In QML, fieldTable_<name> row exists for both tables
        customers_table_row = _quick_item_named(field_list, "fieldTable_Customers")
        orders_table_row = _quick_item_named(field_list, "fieldTable_Orders")
        self.assertIsNotNone(customers_table_row, "fieldTable_Customers must exist in QML")
        self.assertIsNotNone(orders_table_row, "fieldTable_Orders must exist in QML")

        # Orders is active, so it starts expanded; Customers starts collapsed
        self.assertIsNotNone(_quick_item_named(field_list, "reportFieldSelect_Amount"))
        self.assertIsNone(_quick_item_named(field_list, "reportFieldSelect_CustomerName"))

        # Clicking a collapsed table's chevron (or row) shows its field rows
        self._click(window, customers_table_row)

        # Now Customers field rows exist in QML
        self.assertIsNotNone(
            _quick_item_named(field_list, "reportFieldSelect_CustomerName"),
            "Expanding Customers table must instantiate reportFieldSelect_CustomerName",
        )
