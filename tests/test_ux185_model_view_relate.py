"""Tests for Task 185: Model view drag-to-relate and relationship line edit/delete."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QSettings, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.relationship_dialog import RelationshipDialog


def _quick_item_named(root: QQuickItem | None, name: str) -> QQuickItem | None:
    if root is None:
        return None
    if root.objectName() == name:
        return root
    for child in root.childItems():
        found = _quick_item_named(child, name)
        if found is not None:
            return found
    return None


class ModelViewRelateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        QQuickStyle.setStyle("Basic")
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
        self.settings = QSettings(str(self.root / "test.ini"), QSettings.Format.IniFormat)
        self.controller = StudioController(self.app, self.settings)
        self.controller._commit_import(self.dimension_path, parse_file(self.dimension_path))
        self.regions_id = str(self.controller._project["data_sources"][0]["id"])
        self.controller._commit_import(self.facts_path, parse_file(self.facts_path))
        self.orders_id = str(self.controller._project["data_sources"][1]["id"])

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_create_relationship_from_drag_rejected(self) -> None:
        captured_dialog: list[RelationshipDialog] = []

        def capture_exec(dialog_self: RelationshipDialog) -> QDialog.DialogCode:
            captured_dialog.append(dialog_self)
            return QDialog.DialogCode.Rejected

        with patch.object(RelationshipDialog, "exec", new=capture_exec):
            result = self.controller.createRelationshipFromDrag(
                self.orders_id, "RegionID", self.regions_id, "RegionID"
            )
            self.assertFalse(result)

        self.assertEqual(len(captured_dialog), 1)
        dialog = captured_dialog[0]
        self.assertEqual(dialog.from_table.currentData(), self.orders_id)
        self.assertEqual(dialog.from_column.currentData(), "RegionID")
        self.assertEqual(dialog.to_table.currentData(), self.regions_id)
        self.assertEqual(dialog.to_column.currentData(), "RegionID")
        self.assertEqual(self.controller._project.get("model", {}).get("relationships", []), [])

    def test_create_relationship_from_drag_accepted(self) -> None:
        def accept_exec(dialog_self: RelationshipDialog) -> QDialog.DialogCode:
            dialog_self._apply_form()
            dialog_self._save()
            return dialog_self.result()

        with patch.object(RelationshipDialog, "exec", new=accept_exec):
            result = self.controller.createRelationshipFromDrag(
                self.orders_id, "RegionID", self.regions_id, "RegionID"
            )
            self.assertTrue(result)

        saved = self.controller._project.get("model", {}).get("relationships", [])
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["from_table_id"], self.orders_id)
        self.assertEqual(saved[0]["from_column"], "RegionID")
        self.assertEqual(saved[0]["to_table_id"], self.regions_id)
        self.assertEqual(saved[0]["to_column"], "RegionID")

    def test_same_table_drag_returns_false_and_saves_nothing(self) -> None:
        result = self.controller.createRelationshipFromDrag(
            self.orders_id, "RegionID", self.orders_id, "OrderID"
        )
        self.assertFalse(result)
        self.assertEqual(self.controller._project.get("model", {}).get("relationships", []), [])

    def test_edit_relationship(self) -> None:
        # Add an initial relationship
        def accept_exec(dialog_self: RelationshipDialog) -> QDialog.DialogCode:
            dialog_self._apply_form()
            dialog_self._save()
            return dialog_self.result()

        with patch.object(RelationshipDialog, "exec", new=accept_exec):
            self.controller.createRelationshipFromDrag(
                self.orders_id, "RegionID", self.regions_id, "RegionID"
            )

        saved = self.controller._project.get("model", {}).get("relationships", [])
        self.assertEqual(len(saved), 1)
        rel_id = saved[0]["id"]

        captured_dialog: list[RelationshipDialog] = []

        def capture_exec(dialog_self: RelationshipDialog) -> QDialog.DialogCode:
            captured_dialog.append(dialog_self)
            return QDialog.DialogCode.Rejected

        with patch.object(RelationshipDialog, "exec", new=capture_exec):
            self.controller.editRelationship(rel_id)

        self.assertEqual(len(captured_dialog), 1)
        dialog = captured_dialog[0]
        self.assertEqual(dialog._editing_index, 0)
        self.assertEqual(dialog.from_table.currentData(), self.orders_id)
        self.assertEqual(dialog.from_column.currentData(), "RegionID")

    def test_delete_relationship(self) -> None:
        # Add an initial relationship
        def accept_exec(dialog_self: RelationshipDialog) -> QDialog.DialogCode:
            dialog_self._apply_form()
            dialog_self._save()
            return dialog_self.result()

        with patch.object(RelationshipDialog, "exec", new=accept_exec):
            self.controller.createRelationshipFromDrag(
                self.orders_id, "RegionID", self.regions_id, "RegionID"
            )

        saved = self.controller._project.get("model", {}).get("relationships", [])
        self.assertEqual(len(saved), 1)
        rel_id = saved[0]["id"]

        # With QMessageBox patched to No, it keeps it
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            result = self.controller.deleteRelationship(rel_id)
            self.assertFalse(result)
            self.assertEqual(len(self.controller._project.get("model", {}).get("relationships", [])), 1)

        # With QMessageBox patched to Yes, it removes it
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            result = self.controller.deleteRelationship(rel_id)
            self.assertTrue(result)
            self.assertEqual(len(self.controller._project.get("model", {}).get("relationships", [])), 0)

    def test_qml_model_view_integration(self) -> None:
        # Add relationship so route button is present
        def accept_exec(dialog_self: RelationshipDialog) -> QDialog.DialogCode:
            dialog_self._apply_form()
            dialog_self._save()
            return dialog_self.result()

        with patch.object(RelationshipDialog, "exec", new=accept_exec):
            self.controller.createRelationshipFromDrag(
                self.orders_id, "RegionID", self.regions_id, "RegionID"
            )

        saved = self.controller._project.get("model", {}).get("relationships", [])
        self.assertEqual(len(saved), 1)
        rel_id = saved[0]["id"]

        self.controller.setCurrentView("Model")
        qml_dir = Path("/Users/armaan/wt-ux-185/analytics_studio/qml")
        engine = QQmlEngine()
        component = QQmlComponent(engine)
        component.loadUrl(QUrl.fromLocalFile(str(qml_dir / "Main.qml")))
        self.assertFalse(component.isError(), "\n".join(e.toString() for e in component.errors()))
        window = component.createWithInitialProperties({"studioController": self.controller})
        self.assertIsNotNone(window)
        self.app.processEvents()

        model_view = _quick_item_named(window.contentItem(), "modelViewRoot")
        self.assertIsNotNone(model_view)

        # Test finishRelationshipDrag calls slot
        with patch.object(self.controller, "createRelationshipFromDrag") as mock_slot:
            model_view.finishRelationshipDrag(self.orders_id, "RegionID", self.regions_id, "RegionID")
            mock_slot.assert_called_once_with(self.orders_id, "RegionID", self.regions_id, "RegionID")

        # Test relationship link button has the menu
        link_btn = _quick_item_named(window.contentItem(), f"modelDiagramRelationshipLink_{rel_id}")
        self.assertIsNotNone(link_btn)
        menu = link_btn.findChild(object, "modelRelationshipMenu")
        self.assertIsNotNone(menu)

        window.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        self.app.processEvents()


    def test_edit_relationship_unknown_id_refused(self) -> None:
        with patch.object(RelationshipDialog, "exec", side_effect=AssertionError("dialog must not open")):
            self.assertFalse(self.controller.editRelationship("nope"))

    def test_qml_drag_from_column_relates_tables(self) -> None:
        from PySide6.QtCore import QPoint, QPointF, Qt
        from PySide6.QtGui import QGuiApplication, QMouseEvent
        from PySide6.QtCore import QEvent
        from PySide6.QtTest import QTest

        self.controller.setCurrentView("Model")
        qml_dir = Path("/Users/armaan/wt-ux-185/analytics_studio/qml")
        engine = QQmlEngine()
        component = QQmlComponent(engine)
        component.loadUrl(QUrl.fromLocalFile(str(qml_dir / "Main.qml")))
        self.assertFalse(component.isError(), "\n".join(e.toString() for e in component.errors()))
        window = component.createWithInitialProperties({"studioController": self.controller})
        self.assertIsNotNone(window)
        window.resize(1400, 900)
        window.show()
        self.app.processEvents()

        src = _quick_item_named(window.contentItem(), f"modelDiagramFieldSelect_{self.orders_id}_RegionID")
        dst = _quick_item_named(window.contentItem(), f"modelDiagramFieldSelect_{self.regions_id}_RegionID")
        self.assertIsNotNone(src)
        self.assertIsNotNone(dst)

        start = src.mapToScene(src.boundingRect().center()).toPoint()
        end = dst.mapToScene(dst.boundingRect().center()).toPoint()

        with patch.object(self.controller, "createRelationshipFromDrag") as mock_slot:
            QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
            self.app.processEvents()
            steps = 12
            for i in range(1, steps + 1):
                p = QPoint(
                    start.x() + (end.x() - start.x()) * i // steps,
                    start.y() + (end.y() - start.y()) * i // steps,
                )
                move = QMouseEvent(
                    QEvent.MouseMove, QPointF(p), QPointF(window.mapToGlobal(p)),
                    Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
                )
                QGuiApplication.sendEvent(window, move)
                self.app.processEvents()
            QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
            self.app.processEvents()
            mock_slot.assert_called_once_with(self.orders_id, "RegionID", self.regions_id, "RegionID")

        window.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_qml_drag_from_and_to_right_edge_of_row(self) -> None:
        from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
        from PySide6.QtGui import QGuiApplication, QMouseEvent
        from PySide6.QtTest import QTest

        self.controller.setCurrentView("Model")
        qml_dir = Path("/Users/armaan/wt-ux-185/analytics_studio/qml")
        engine = QQmlEngine()
        component = QQmlComponent(engine)
        component.loadUrl(QUrl.fromLocalFile(str(qml_dir / "Main.qml")))
        self.assertFalse(component.isError(), "\n".join(e.toString() for e in component.errors()))
        window = component.createWithInitialProperties({"studioController": self.controller})
        self.assertIsNotNone(window)
        window.resize(1400, 900)
        window.show()
        self.app.processEvents()

        src = _quick_item_named(window.contentItem(), f"modelDiagramFieldSelect_{self.orders_id}_RegionID")
        dst = _quick_item_named(window.contentItem(), f"modelDiagramFieldSelect_{self.regions_id}_RegionID")
        self.assertIsNotNone(src)
        self.assertIsNotNone(dst)

        start = src.mapToScene(QPointF(src.width() - 8, src.height() / 2)).toPoint()
        end = dst.mapToScene(QPointF(dst.width() - 8, dst.height() / 2)).toPoint()

        with patch.object(self.controller, "createRelationshipFromDrag") as mock_slot:
            QTest.mousePress(window, Qt.LeftButton, Qt.NoModifier, start)
            self.app.processEvents()
            steps = 12
            for i in range(1, steps + 1):
                p = QPoint(
                    start.x() + (end.x() - start.x()) * i // steps,
                    start.y() + (end.y() - start.y()) * i // steps,
                )
                move = QMouseEvent(
                    QEvent.MouseMove, QPointF(p), QPointF(window.mapToGlobal(p)),
                    Qt.NoButton, Qt.LeftButton, Qt.NoModifier,
                )
                QGuiApplication.sendEvent(window, move)
                self.app.processEvents()
            QTest.mouseRelease(window, Qt.LeftButton, Qt.NoModifier, end)
            self.app.processEvents()
            mock_slot.assert_called_once_with(self.orders_id, "RegionID", self.regions_id, "RegionID")

        window.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

if __name__ == "__main__":
    unittest.main()
