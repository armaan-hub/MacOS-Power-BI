"""Tests for the Column tools contextual ribbon tab in Table view (Task 192)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QPointF, QSettings, Qt, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file

QQuickStyle.setStyle("Basic")
QML = Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml"


class ColumnToolsRibbonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        source = self.root / "Orders.csv"
        source.write_text("Quantity,Unit price\n2,12.5\n3,8\n", encoding="utf-8")
        settings = QSettings(str(self.root / "settings.ini"), QSettings.Format.IniFormat)
        self.controller = StudioController(self.app, settings)
        self.assertTrue(self.controller._commit_import(source, parse_file(source)))

        self.engine = QQmlEngine()
        self.component = QQmlComponent(self.engine)
        self.component.loadUrl(QUrl.fromLocalFile(str(QML)))
        self.window = self.component.createWithInitialProperties(
            {"studioController": self.controller}
        )
        self.assertIsNotNone(self.window, "\n".join(e.toString() for e in self.component.errors()))
        self.window.resize(1500, 900)
        self.window.show()
        self.window.requestActivate()
        QTest.qWaitForWindowExposed(self.window)
        self.controller.setCurrentView("Data")
        self.process()

    def tearDown(self) -> None:
        self.controller._dirty = False
        if self.controller.formulaBar.active:
            self.controller.formulaBar.cancel()
        self.window.close()
        self.window.deleteLater()
        self.component.deleteLater()
        self.engine.deleteLater()

    def process(self) -> None:
        for _ in range(4):
            self.app.processEvents()
            QTest.qWait(10)

    def child(self, name: str) -> QObject | None:
        item = self.window.findChild(QObject, name)
        if item is None:
            matches: list[QObject] = []

            def walk(parent: QObject) -> None:
                for candidate in parent.childItems():
                    if candidate.objectName() == name:
                        matches.append(candidate)
                    walk(candidate)

            walk(self.window.contentItem())
            if matches:
                return matches[0]
        return item

    def tabs(self) -> list[str]:
        tabs = self.window.property("visibleRibbonTabs")
        return [str(tab) for tab in tabs.toVariant()] if hasattr(tabs, "toVariant") else [str(tab) for tab in tabs]

    def select_column_header(self, index: int = 0) -> None:
        header = self.child(f"dataColumnHeaderName_{index}")
        self.assertIsNotNone(header, f"Header {index} must exist")
        center = header.mapToScene(QPointF(header.width() / 2, header.height() / 2)).toPoint()
        QTest.mouseClick(self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
        self.process()

    def get_tooltip(self, item: QObject) -> str:
        for c in item.children():
            if c.metaObject().className() == "QQuickToolTipAttached":
                return str(c.property("text") or "")
        return ""

    def test_no_column_selected_has_no_column_tools_tab(self) -> None:
        self.assertNotIn("Column tools", self.tabs())
        self.assertIn("Table tools", self.tabs())

    def test_selecting_column_shows_column_tools_and_switches_to_it(self) -> None:
        self.select_column_header(0)
        self.assertIn("Column tools", self.tabs())
        self.assertEqual(self.window.property("ribbonTabName"), "Column tools")
        self.assertEqual(self.window.property("selectedFieldBinding"), "Quantity")

    def test_summarization_average_updates_model_and_reflects_in_model_view(self) -> None:
        self.select_column_header(0)  # Quantity
        summ_combo = self.child("columnToolsSummarization")
        self.assertIsNotNone(summ_combo)
        self.assertTrue(summ_combo.property("enabled"))

        # Select "Average" (value "average", index 2)
        summ_combo.setProperty("currentIndex", 2)
        summ_combo.activated.emit(2)
        self.process()

        table_id = self.controller.activeTableId
        table = next(t for t in self.controller.tableCatalog if str(t["id"]) == table_id)
        self.assertEqual(table["columnSummarizations"].get("Quantity"), "average")

        # Switch to Model view and verify Model view's default summarization matches
        self.controller.setCurrentView("Model")
        self.process()
        field_btn = self.child(f"modelFieldSelect_{table_id}_Quantity")
        self.assertIsNotNone(field_btn)
        field_btn.clicked.emit()
        self.process()

        model_summ = self.child("modelColumnDefaultSummarization")
        self.assertIsNotNone(model_summ)
        self.assertEqual(model_summ.property("currentValue"), "average")

    def test_sort_by_column_updates_model_and_reflects_in_model_view(self) -> None:
        self.select_column_header(0)  # Quantity
        sort_combo = self.child("columnToolsSortBy")
        self.assertIsNotNone(sort_combo)
        self.assertTrue(sort_combo.property("enabled"))

        # Select "Unit price" (index 1)
        sort_combo.setProperty("currentIndex", 1)
        sort_combo.activated.emit(1)
        self.process()

        table_id = self.controller.activeTableId
        table = next(t for t in self.controller.tableCatalog if str(t["id"]) == table_id)
        self.assertEqual(table["columnSortBy"].get("Quantity"), "Unit price")

        # Switch to Model view and verify Model view's sort by column matches
        self.controller.setCurrentView("Model")
        self.process()
        field_btn = self.child(f"modelFieldSelect_{table_id}_Quantity")
        self.assertIsNotNone(field_btn)
        field_btn.clicked.emit()
        self.process()

        model_sort = self.child("modelColumnSortBy")
        self.assertIsNotNone(model_sort)
        self.assertEqual(model_sort.property("currentValue"), "Unit price")

    def test_disabled_controls_carry_tooltips(self) -> None:
        self.select_column_header(0)

        name_box = self.child("columnToolsName")
        self.assertIsNotNone(name_box)
        self.assertEqual(self.get_tooltip(name_box), "Renaming columns here is not supported yet.")

        format_box = self.child("columnToolsFormat")
        self.assertIsNotNone(format_box)
        self.assertEqual(self.get_tooltip(format_box), "Column number formats are not supported yet.")

        category_box = self.child("columnToolsDataCategory")
        self.assertIsNotNone(category_box)
        self.assertEqual(self.get_tooltip(category_box), "Data categories are not supported yet.")

        groups_box = self.child("columnToolsDataGroups")
        self.assertIsNotNone(groups_box)
        self.assertEqual(self.get_tooltip(groups_box), "Data groups are not supported yet.")

    def test_table_tools_keeps_working_unchanged(self) -> None:
        self.assertIn("Table tools", self.tabs())
        self.window.setProperty("ribbonTabName", "Table tools")
        self.process()
        self.assertEqual(self.window.property("ribbonTabName"), "Table tools")
        new_measure_btn = self.child("ribbonCommand_data.newMeasure")
        self.assertIsNotNone(new_measure_btn)
