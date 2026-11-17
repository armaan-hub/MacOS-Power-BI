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
        # For non-active tables, the object name is reportFieldSelect_<tableId>_<binding>
        self.assertIsNotNone(
            _quick_item_named(field_list, f"reportFieldSelect_{customers_id}_CustomerName")
            or _quick_item_named(field_list, "reportFieldSelect_CustomerName"),
            "Expanding Customers table must instantiate CustomerName field row",
        )

    def test_followup_cross_table_toggle_and_same_named_columns(self) -> None:
        controller, orders_id, customers_id = self._setup_controller()
        controller.selectTable(orders_id)
        controller.setTableExpanded(orders_id, True)
        controller.setTableExpanded(customers_id, True)

        controller.add_visual("table", "Test Visual", 50, 50, 300, 200)
        controller.selectVisual("Test Visual")

        # CustomerID exists in both Orders and Customers
        # Toggling Customers' CustomerID
        controller.toggleFieldInVisual(customers_id, "CustomerID", True)

        tree = controller.fieldTree
        cust_t = next(t for t in tree if t["tableId"] == customers_id)
        ord_t = next(t for t in tree if t["tableId"] == orders_id)

        cust_id_field = next(f for f in cust_t["fields"] if f["label"] == "CustomerID")
        ord_id_field = next(f for f in ord_t["fields"] if f["label"] == "CustomerID")

        self.assertTrue(cust_id_field["inVisual"])
        self.assertFalse(ord_id_field["inVisual"])

        # Toggling off removes it
        controller.toggleFieldInVisual(customers_id, "CustomerID", False)
        tree = controller.fieldTree
        cust_t = next(t for t in tree if t["tableId"] == customers_id)
        cust_id_field = next(f for f in cust_t["fields"] if f["label"] == "CustomerID")
        self.assertFalse(cust_id_field["inVisual"])

    def test_followup_measure_homes_after_table_switch(self) -> None:
        controller, orders_id, customers_id = self._setup_controller()
        # Total Amount was created on Orders table
        controller.selectTable(customers_id)

        tree = controller.fieldTree
        cust_t = next(t for t in tree if t["tableId"] == customers_id)
        ord_t = next(t for t in tree if t["tableId"] == orders_id)

        self.assertNotIn("Total Amount", [f["label"] for f in cust_t["fields"]])
        self.assertIn("Total Amount", [f["label"] for f in ord_t["fields"]])

    def test_followup_focus_table_leaves_exactly_one_expanded(self) -> None:
        controller, orders_id, customers_id = self._setup_controller()
        # Expand both first
        controller.setTableExpanded(orders_id, True)
        controller.setTableExpanded(customers_id, True)

        controller.focusTable(customers_id)
        self.assertEqual(str(controller.activeTableId), customers_id)

        tree = controller.fieldTree
        cust_t = next(t for t in tree if t["tableId"] == customers_id)
        ord_t = next(t for t in tree if t["tableId"] == orders_id)

        self.assertTrue(cust_t["expanded"])
        self.assertFalse(ord_t["expanded"])

    def test_select_table_keeps_other_tables_expanded_focus_collapses(self) -> None:
        controller, orders_id, customers_id = self._setup_controller()
        controller.setTableExpanded(orders_id, True)
        controller.setTableExpanded(customers_id, True)

        self.assertTrue(controller.selectTable(customers_id))
        tree = controller.fieldTree
        self.assertTrue(next(t for t in tree if t["tableId"] == customers_id)["expanded"])
        self.assertTrue(next(t for t in tree if t["tableId"] == orders_id)["expanded"])

        controller.focusTable(customers_id)
        tree = controller.fieldTree
        self.assertTrue(next(t for t in tree if t["tableId"] == customers_id)["expanded"])
        self.assertFalse(next(t for t in tree if t["tableId"] == orders_id)["expanded"])

    def test_followup_hidden_column_absent_from_field_tree(self) -> None:
        controller, orders_id, customers_id = self._setup_controller()
        model_tables = controller._project.get("model", {}).get("tables", [])
        ord_model = next(t for t in model_tables if str(t.get("id")) == orders_id or t.get("name") == "Orders")
        # Hide a column on the Orders model table
        ord_model["hidden_columns"] = ["OrderID"]
        controller._invalidate_field_tree_cache()

        tree = controller.fieldTree
        ord_t = next(t for t in tree if t["tableId"] == orders_id)
        self.assertNotIn("OrderID", [f["label"] for f in ord_t["fields"]])

    def test_calculated_column_shows_in_field_tree(self) -> None:
        controller, orders_id, customers_id = self._setup_controller()
        controller.selectTable(orders_id)

        # Before adding calculated column
        tree_before = controller.fieldTree
        ord_t_before = next(t for t in tree_before if t["tableId"] == orders_id)
        self.assertNotIn("Double", [f["label"] for f in ord_t_before["fields"]])

        # Add calculated column
        err = controller.save_calculated_column("Double", "Orders[Amount] * 2")
        self.assertEqual(err, "")

        tree_after = controller.fieldTree
        ord_t_after = next(t for t in tree_after if t["tableId"] == orders_id)
        self.assertIn("Double", [f["label"] for f in ord_t_after["fields"]])

    def test_renaming_column_shows_new_name_in_field_tree(self) -> None:
        from analytics_studio.transformations import apply_transformations

        controller, orders_id, customers_id = self._setup_controller()
        controller.selectTable(orders_id)

        tree_before = controller.fieldTree
        ord_t_before = next(t for t in tree_before if t["tableId"] == orders_id)
        self.assertIn("Amount", [f["label"] for f in ord_t_before["fields"]])
        self.assertNotIn("OrderAmount", [f["label"] for f in ord_t_before["fields"]])

        # Rename column via transformation steps
        raw = controller._raw_candidates[orders_id]
        steps = [{"op": "rename_column", "column": "Amount", "new_name": "OrderAmount"}]
        transformed = apply_transformations(raw, steps)
        self.assertTrue(controller._commit_transform_steps(orders_id, steps, transformed))

        tree_after = controller.fieldTree
        ord_t_after = next(t for t in tree_after if t["tableId"] == orders_id)
        self.assertNotIn("Amount", [f["label"] for f in ord_t_after["fields"]])
        self.assertIn("OrderAmount", [f["label"] for f in ord_t_after["fields"]])


