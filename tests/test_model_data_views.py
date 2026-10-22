"""QML acceptance checks for the data preview and model relationship views."""

from __future__ import annotations

import os
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QPointF, QSettings, QUrl, Qt
from PySide6.QtGui import QAccessible, QColor
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQuick import QQuickItem
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.controller import (
    StudioController,
    _model_candidate_with_format_errors_as_blank,
)
from analytics_studio.calculated_column_dialog import CalculatedColumnDialog
from analytics_studio.file_import import ImportCandidate, parse_file
from analytics_studio.import_preview_dialog import FileImportPreviewDialog
from analytics_studio.power_query_values import PowerQueryCellError
from analytics_studio.relationship_dialog import RelationshipDialog

QQuickStyle.setStyle("Basic")


def _quick_item_named(root: QQuickItem, name: str) -> QQuickItem | None:
    if root.objectName() == name:
        return root
    for child in root.childItems():
        found = _quick_item_named(child, name)
        if found is not None:
            return found
    return None


def _quick_items(root: QQuickItem):
    yield root
    for child in root.childItems():
        yield from _quick_items(child)


def _contrast_ratio(foreground: QColor, background: QColor) -> float:
    def luminance(color: QColor) -> float:
        channels = [color.redF(), color.greenF(), color.blueF()]
        linear = [
            channel / 12.92
            if channel <= 0.04045
            else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    light, dark = sorted(
        (luminance(foreground), luminance(background)), reverse=True
    )
    return (light + 0.05) / (dark + 0.05)


class ModelDataViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.qml_dir = Path(__file__).resolve().parents[1] / "analytics_studio" / "qml"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self) -> StudioController:
        settings = QSettings(
            str(self.root / "settings.ini"), QSettings.Format.IniFormat
        )
        return StudioController(self.app, settings)

    def test_model_projection_blanks_only_data_format_errors_and_preserves_query_result(self) -> None:
        data_format_error = PowerQueryCellError(
            "DataFormat.Error", "invalid number", "n/a", "number", row=0
        )
        expression_error = PowerQueryCellError(
            "Expression.Error", "unsupported expression", row=1
        )
        candidate = ImportCandidate(
            "csv",
            ["TRN", "Other"],
            [
                {"TRN": data_format_error, "Other": "keep"},
                {"TRN": 123, "Other": expression_error},
            ],
            {"culture": "en-US"},
            ["source notice"],
            source_id="vat-source",
        )
        candidate.set_source_identity("vat-source")
        source_rows = [row.source_rows for row in candidate.rows]
        # Source identity stamps lineage onto stored errors, so compare against
        # the objects the candidate actually holds, not the pre-lineage originals.
        stored_format_error = candidate.rows[0]["TRN"]
        stored_expression_error = candidate.rows[1]["Other"]
        self.assertEqual(stored_format_error.reason, data_format_error.reason)
        self.assertEqual(stored_expression_error.reason, expression_error.reason)

        projected = _model_candidate_with_format_errors_as_blank(candidate)

        self.assertIsNone(projected.rows[0]["TRN"])
        self.assertEqual(projected.rows[0]["Other"], "keep")
        self.assertEqual(projected.rows[1]["TRN"], 123)
        self.assertIs(projected.rows[1]["Other"], stored_expression_error)
        self.assertIs(candidate.rows[0]["TRN"], stored_format_error)
        self.assertEqual([row.source_rows for row in projected.rows], source_rows)
        self.assertEqual(projected.options, candidate.options)
        self.assertEqual(projected.notices, candidate.notices)
        self.assertEqual(projected.source_id, candidate.source_id)

    def load_view(self, controller: StudioController, filename: str, **properties):
        engine = QQmlEngine()
        component = QQmlComponent(engine)
        component.loadUrl(QUrl.fromLocalFile(str(self.qml_dir / filename)))
        self.assertFalse(
            component.isError(), "\n".join(error.toString() for error in component.errors())
        )
        view = component.createWithInitialProperties(
            {"appController": controller, **properties}
        )
        self.assertIsNotNone(
            view, "\n".join(error.toString() for error in component.errors())
        )
        self.app.processEvents()
        return engine, component, view

    def load_main(self, controller: StudioController):
        engine = QQmlEngine()
        component = QQmlComponent(engine)
        component.loadUrl(QUrl.fromLocalFile(str(self.qml_dir / "Main.qml")))
        self.assertFalse(
            component.isError(), "\n".join(error.toString() for error in component.errors())
        )
        window = component.createWithInitialProperties({"studioController": controller})
        self.assertIsNotNone(
            window, "\n".join(error.toString() for error in component.errors())
        )
        self.app.processEvents()
        return engine, component, window

    def load_model_window(
        self,
        controller: StudioController,
        width: int = 1200,
        *,
        diagram_mode: bool | None = False,
    ):
        controller.setCurrentView("Model")
        properties = {} if diagram_mode is None else {"diagramMode": diagram_mode}
        engine, component, view = self.load_view(
            controller, "ModelView.qml", **properties
        )
        window = QQuickWindow()
        window.resize(width, 900)
        view.setParentItem(window.contentItem())
        view.setWidth(width)
        view.setHeight(900)
        window.show()
        self.app.processEvents()
        return engine, component, view, window

    def activate_with_keyboard(self, window: QQuickWindow, item: QQuickItem) -> None:
        item.forceActiveFocus()
        self.assertTrue(item.property("activeFocus"), "The model field must accept keyboard focus.")
        QTest.keyClick(window, Qt.Key.Key_Space)
        self.app.processEvents()

    def select_summarization_with_keyboard(
        self, window: QQuickWindow, combo: QQuickItem, value: str
    ) -> None:
        options = combo.property("model")
        target_index = next(
            index for index, option in enumerate(options)
            if str(option.get("value")) == value
        )
        combo.forceActiveFocus()
        QTest.keyClick(window, Qt.Key.Key_Space)
        self.app.processEvents()
        highlighted_index = int(combo.property("highlightedIndex"))
        for _ in range(len(options) + 1):
            if highlighted_index == target_index:
                break
            direction = (
                Qt.Key.Key_Down
                if highlighted_index < target_index
                else Qt.Key.Key_Up
            )
            QTest.keyClick(window, direction)
            self.app.processEvents()
            highlighted_index = int(combo.property("highlightedIndex"))
        self.assertEqual(highlighted_index, target_index)
        QTest.keyClick(window, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(str(combo.property("currentValue")), value)

    def select_model_sort_with_keyboard(
        self, window: QQuickWindow, combo: QQuickItem, value: str
    ) -> None:
        options = combo.property("model")
        target_index = next(
            index for index, option in enumerate(options)
            if str(option.get("value")) == value
        )
        combo.forceActiveFocus()
        QTest.keyClick(window, Qt.Key.Key_Space)
        self.app.processEvents()
        highlighted_index = int(combo.property("highlightedIndex"))
        for _ in range(len(options) + 1):
            if highlighted_index == target_index:
                break
            direction = (
                Qt.Key.Key_Down
                if highlighted_index < target_index
                else Qt.Key.Key_Up
            )
            QTest.keyClick(window, direction)
            self.app.processEvents()
            highlighted_index = int(combo.property("highlightedIndex"))
        self.assertEqual(highlighted_index, target_index)
        QTest.keyClick(window, Qt.Key.Key_Return)
        self.app.processEvents()
        self.assertEqual(str(combo.property("currentValue")), value)

    def activate_button_with_keyboard(
        self, window: QQuickWindow, button: QQuickItem
    ) -> None:
        button.forceActiveFocus()
        self.assertTrue(button.property("activeFocus"), "The model action must accept keyboard focus.")
        QTest.keyClick(window, Qt.Key.Key_Space)
        self.app.processEvents()

    def accessible_name_and_description(self, item: QQuickItem) -> tuple[str, str, bool]:
        interface = QAccessible.queryAccessibleInterface(item)
        self.assertIsNotNone(interface, "The model control must expose its accessible properties.")
        return (
            interface.text(QAccessible.Text.Name),
            interface.text(QAccessible.Text.Description),
            bool(interface.state().disabled),
        )

    @staticmethod
    def visible_text(item: QQuickItem) -> str:
        fragments = []
        for child in _quick_items(item):
            meta = child.metaObject()
            if meta.indexOfProperty("text") >= 0:
                value = child.property("text")
                if value is not None and str(value):
                    fragments.append(str(value))
            if meta.indexOfProperty("currentText") >= 0:
                value = child.property("currentText")
                if value is not None and str(value):
                    fragments.append(str(value))
        return " ".join(fragments)

    def create_numeric_calculated_column(self, controller: StudioController) -> None:
        table = controller._model_table_for_source(
            controller._project, controller.activeTableId
        )
        dialog = CalculatedColumnDialog(table.get("calculated_columns", []))
        dialog.name_edit.setText("Calculated Revenue")
        dialog.expression_edit.setPlainText("[Revenue] * 2")

        def accept_dialog() -> int:
            dialog._accept_column()
            return dialog.result()

        with (
            patch("analytics_studio.controller.CalculatedColumnDialog", return_value=dialog),
            patch.object(dialog, "exec", side_effect=accept_dialog),
            patch("analytics_studio.controller.QMessageBox.warning"),
        ):
            self.assertTrue(controller.calculated_column_dialog())

    def test_data_view_pages_loaded_rows_and_resets_on_lifecycle_changes(self) -> None:
        long_path = self.root / "Long.csv"
        headers = ["Row", *(f"Field{index}" for index in range(1, 12))]

        def write_rows(row_count: int) -> None:
            contents = [",".join(headers)]
            contents.extend(
                ",".join([str(index)] * len(headers))
                for index in range(row_count)
            )
            long_path.write_text("\n".join(contents) + "\n", encoding="utf-8")

        write_rows(600)
        short_path = self.root / "Short.csv"
        short_path.write_text("Name\nfirst\nsecond\n", encoding="utf-8")

        controller = self.controller()
        self.assertTrue(controller._commit_import(long_path, parse_file(long_path)))
        long_id = str(controller.activeTableId)
        self.assertTrue(controller._commit_import(short_path, parse_file(short_path)))
        short_id = str(controller.activeTableId)
        self.assertTrue(controller.selectTable(long_id))
        self.assertEqual(controller.rowCount, 600)
        self.assertEqual(controller.dataModel.rowCount(), 500)
        self.assertEqual(controller.dataModel.data(controller.dataModel.index(499, 0)), "499")

        engine, component, view = self.load_view(controller, "DataView.qml")
        selector = view.findChild(QObject, "activeTableComboBox")
        range_label = view.findChild(QObject, "dataViewPageRange")
        page_label = view.findChild(QObject, "dataViewPageIndicator")
        previous_button = view.findChild(QObject, "dataViewPreviousPage")
        next_button = view.findChild(QObject, "dataViewNextPage")
        table_view = view.findChild(QObject, "dataViewTable")
        self.assertIsNotNone(selector)
        self.assertIsNotNone(range_label)
        self.assertIsNotNone(page_label)
        self.assertIsNotNone(previous_button)
        self.assertIsNotNone(next_button)
        self.assertIsNotNone(table_view)
        self.assertEqual(selector.property("currentIndex"), 0)
        self.assertEqual(controller.dataModel.rowCount(), 500)
        self.assertEqual(range_label.property("text"), "Rows 1–500 of 600")
        self.assertEqual(page_label.property("text"), "Page 1 of 2")
        self.assertFalse(previous_button.property("enabled"))
        self.assertTrue(next_button.property("enabled"))

        window = QQuickWindow()
        window.resize(900, 600)
        view.setParentItem(window.contentItem())
        view.setWidth(900)
        view.setHeight(600)
        window.show()
        self.app.processEvents()

        def click(item: QQuickItem) -> None:
            point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
            QTest.mouseClick(
                window,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                QPoint(round(point.x()), round(point.y())),
            )
            self.app.processEvents()

        controller._dirty = False
        original_project = deepcopy(controller._project)
        original_rows = deepcopy(controller._rows)
        table_view.setProperty("contentY", 1000.0)
        table_view.setProperty("contentX", 180.0)
        self.app.processEvents()
        self.assertGreater(float(table_view.property("contentY")), 0.0)
        self.assertGreater(float(table_view.property("contentX")), 0.0)
        click(next_button)
        self.assertEqual(controller.dataModel.currentPage, 2)
        self.assertEqual(controller.dataModel.pageCount, 2)
        self.assertEqual(controller.dataModel.rowCount(), 100)
        self.assertEqual(controller.dataModel.data(controller.dataModel.index(0, 0)), "500")
        self.assertEqual(controller.dataModel.data(controller.dataModel.index(99, 0)), "599")
        self.assertEqual(
            controller.dataModel.headerData(0, Qt.Orientation.Vertical), 501
        )
        self.assertEqual(range_label.property("text"), "Rows 501–600 of 600")
        self.assertEqual(page_label.property("text"), "Page 2 of 2")
        self.assertEqual(float(table_view.property("contentY")), 0.0)
        self.assertGreater(float(table_view.property("contentX")), 0.0)
        self.assertTrue(previous_button.property("enabled"))
        self.assertFalse(next_button.property("enabled"))
        self.assertEqual(controller._project, original_project)
        self.assertEqual(controller._rows, original_rows)
        self.assertFalse(controller.dirty)

        click(previous_button)
        self.assertEqual(controller.dataModel.currentPage, 1)
        self.assertEqual(controller.dataModel.rowCount(), 500)
        self.assertEqual(range_label.property("text"), "Rows 1–500 of 600")
        click(next_button)
        table_view.setProperty("contentY", 1000.0)
        table_view.setProperty("contentX", 180.0)
        self.app.processEvents()
        self.assertGreater(float(table_view.property("contentY")), 0.0)
        self.assertGreater(float(table_view.property("contentX")), 0.0)

        project_path = self.root / "preview-page.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.dataModel.currentPage, 1)
        self.assertEqual(reopened.dataModel.pageCount, 2)
        self.assertEqual(reopened.dataModel.rowCount(), 500)
        self.assertEqual(reopened.dataModel.data(reopened.dataModel.index(0, 0)), "0")

        selector.forceActiveFocus()
        QTest.keyClick(window, Qt.Key.Key_Down)
        self.app.processEvents()

        self.assertEqual(selector.property("currentIndex"), 1)
        self.assertEqual(controller.activeTableId, short_id)
        self.assertEqual(controller.rowCount, 2)
        self.assertEqual(controller.dataModel.rowCount(), 2)
        self.assertEqual(controller.dataModel.data(controller.dataModel.index(1, 0)), "second")
        self.assertEqual(controller.dataModel.currentPage, 1)
        self.assertEqual(float(table_view.property("contentY")), 0.0)

        selector.forceActiveFocus()
        QTest.keyClick(window, Qt.Key.Key_Up)
        self.app.processEvents()
        self.assertEqual(controller.activeTableId, long_id)
        self.assertEqual(controller.dataModel.currentPage, 1)

        click(next_button)
        self.assertEqual(controller.dataModel.currentPage, 2)
        table_view.setProperty("contentY", 1000.0)
        table_view.setProperty("contentX", 180.0)
        self.app.processEvents()
        self.assertGreater(float(table_view.property("contentY")), 0.0)
        long_path.unlink()
        with patch("analytics_studio.controller.QMessageBox.critical") as critical:
            controller.refresh_source()
        critical.assert_called_once()
        self.assertEqual(controller.rowCount, 600)
        self.assertEqual(controller.dataModel.currentPage, 2)
        self.assertEqual(controller.dataModel.data(controller.dataModel.index(0, 0)), "500")
        self.assertGreater(float(table_view.property("contentY")), 0.0)
        self.assertGreater(float(table_view.property("contentX")), 0.0)

        write_rows(100)
        controller._dirty = False
        controller.refresh_source()
        self.app.processEvents()
        self.assertEqual(controller.rowCount, 100)
        self.assertEqual(controller.dataModel.currentPage, 1)
        self.assertEqual(controller.dataModel.pageCount, 1)
        self.assertEqual(controller.dataModel.rowCount(), 100)
        self.assertEqual(controller.dataModel.data(controller.dataModel.index(0, 0)), "0")
        self.assertEqual(float(table_view.property("contentY")), 0.0)
        self.assertEqual(float(table_view.property("contentX")), 0.0)
        self.assertEqual(range_label.property("text"), "Rows 1–100 of 100")
        self.assertFalse(previous_button.property("enabled"))
        self.assertFalse(next_button.property("enabled"))
        window.close()
        view.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        reopened.deleteLater()
        self.app.processEvents()

    def test_data_model_page_boundaries_for_exact_limit_and_empty_rows(self) -> None:
        source = self.root / "ExactLimit.csv"
        source.write_text(
            "Row\n" + "".join(f"{index}\n" for index in range(500)),
            encoding="utf-8",
        )
        controller = self.controller()
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        model = controller.dataModel
        self.assertEqual(model.pageCount, 1)
        self.assertEqual(model.currentPage, 1)
        self.assertEqual(model.pageRange, "Rows 1–500 of 500")
        self.assertEqual(model.rowCount(), 500)
        self.assertFalse(model.canGoPrevious)
        self.assertFalse(model.canGoNext)

        empty_source = self.root / "Empty.csv"
        empty_source.write_text("Row\n", encoding="utf-8")
        self.assertTrue(controller._commit_import(empty_source, parse_file(empty_source)))
        model = controller.dataModel
        self.assertEqual(model.pageCount, 0)
        self.assertEqual(model.currentPage, 0)
        self.assertEqual(model.pageRange, "No rows")
        self.assertEqual(model.rowCount(), 0)
        self.assertFalse(model.canGoPrevious)
        self.assertFalse(model.canGoNext)

        engine, component, view = self.load_view(controller, "DataView.qml")
        range_label = view.findChild(QObject, "dataViewPageRange")
        previous_button = view.findChild(QObject, "dataViewPreviousPage")
        next_button = view.findChild(QObject, "dataViewNextPage")
        self.assertIsNotNone(range_label)
        self.assertIsNotNone(previous_button)
        self.assertIsNotNone(next_button)
        self.assertEqual(range_label.property("text"), "No rows")
        self.assertFalse(previous_button.property("enabled"))
        self.assertFalse(next_button.property("enabled"))
        view.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_data_view_column_filters_affect_preview_only_and_follow_the_table(self) -> None:
        sales_path = self.root / "Sales.csv"
        sales_path.write_text(
            "Region,Amount\nEast,10\nWest,20\nEast,30\n",
            encoding="utf-8",
        )
        target_path = self.root / "Targets.csv"
        target_path.write_text(
            "Region,Target\nNorth,100\nSouth,200\n",
            encoding="utf-8",
        )
        controller = self.controller()
        self.assertTrue(controller._commit_import(sales_path, parse_file(sales_path)))
        sales_id = str(controller.activeTableId)
        controller.setCurrentView("Data")

        engine, component, window = self.load_main(controller)
        window.resize(1280, 800)
        window.show()
        self.app.processEvents()

        def find_region_filter_button() -> QQuickItem:
            filter_buttons = [
                item for item in _quick_items(window.contentItem())
                if item.objectName() == "dataViewFilterColumn_0"
                and item.isVisible()
            ]
            return max(
                filter_buttons,
                key=lambda item: item.mapToScene(QPointF(0, 0)).x(),
            )

        filter_button = find_region_filter_button()
        self.assertIsNotNone(filter_button)
        filter_icons = [
            item for item in _quick_items(filter_button)
            if item.objectName() == "dataViewFilterIcon"
        ]
        self.assertEqual(len(filter_icons), 1)
        self.assertTrue(filter_icons[0].isVisible())
        name, description, disabled = self.accessible_name_and_description(
            filter_button
        )
        self.assertEqual(name, "Filter preview rows by Region")
        self.assertIn("Filter the rows shown in Data view", description)
        self.assertFalse(disabled)

        model = controller._table_model
        clicked = QSignalSpy(filter_button.clicked)

        def click_item(item: QQuickItem) -> None:
            scene_point = item.mapToScene(
                QPointF(item.width() / 2, item.height() / 2)
            )
            QTest.mousePress(
                window,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                QPoint(round(scene_point.x()), round(scene_point.y())),
            )
            self.app.processEvents()
            QTest.mouseRelease(
                window,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                QPoint(round(scene_point.x()), round(scene_point.y())),
            )
            self.app.processEvents()

        click_item(find_region_filter_button())
        self.assertEqual(clicked.count(), 1)
        filter_dialog = window.findChild(QObject, "dataViewColumnFilterDialog")
        self.assertIsNotNone(filter_dialog)
        self.assertEqual(model.sortColumn, "")
        self.assertTrue(filter_dialog.property("visible"))
        condition_tab = window.findChild(QObject, "dataViewFilterTabCondition")
        self.assertIsNotNone(condition_tab)
        click_item(condition_tab)
        self.assertEqual(
            window.findChild(QObject, "dataViewFilterTabs").property("currentIndex"),
            1,
        )
        operator = window.findChild(QObject, "dataViewFilterOperator")
        self.assertIsNotNone(operator)
        operator_name, _operator_description, operator_disabled = (
            self.accessible_name_and_description(operator)
        )
        self.assertEqual(operator_name, "Condition operator for Region")
        self.assertFalse(operator_disabled)
        value_field = window.findChild(QObject, "dataViewFilterValue")
        self.assertIsNotNone(value_field)
        value_field.setProperty("text", "East")
        apply_button = window.findChild(QObject, "dataViewApplyColumnFilter")
        self.assertIsNotNone(apply_button)
        click_item(apply_button)
        self.app.processEvents()
        self.assertEqual(model.rowCount(), 2)
        self.assertEqual(model.pageRange, "Rows 1–2 of 2")
        self.assertEqual(model.data(model.index(1, 1)), "30")
        self.assertEqual(controller.rowCount, 3)
        self.assertEqual(model.activeFilterColumns, ["Region"])

        model.setColumnFilter("Amount", "contains", "3")
        self.app.processEvents()
        self.assertEqual(model.rowCount(), 1)
        self.assertEqual(model.data(model.index(0, 0)), "East")
        find_region_filter_button().clicked.emit()
        self.app.processEvents()
        self.assertTrue(filter_dialog.property("visible"))
        clear_button = window.findChild(QObject, "dataViewClearColumnFilter")
        self.assertIsNotNone(clear_button)
        self.assertTrue(clear_button.property("enabled"))
        click_item(clear_button)
        self.assertEqual(model.rowCount(), 1)
        self.assertEqual(model.activeFilterColumns, ["Amount"])

        self.assertTrue(controller._commit_import(target_path, parse_file(target_path)))
        target_id = str(controller.activeTableId)
        self.assertEqual(model.rowCount(), 2)
        self.assertEqual(model.activeFilterColumns, [])
        self.assertTrue(controller.selectTable(sales_id))
        self.assertEqual(model.rowCount(), 1)
        self.assertEqual(model.activeFilterColumns, ["Amount"])
        self.assertTrue(controller.selectTable(target_id))
        self.assertEqual(model.rowCount(), 2)
        self.assertEqual(model.activeFilterColumns, [])

        controller._dirty = False
        window.hide()
        window.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_data_view_filter_toolbar_shortcut_shows_scope_and_active_count(self) -> None:
        source = self.root / "FilterToolbar.csv"
        source.write_text(
            "Region,Amount\nEast,10\nWest,20\nEast,30\n",
            encoding="utf-8",
        )
        second_source = self.root / "FilterToolbarSecond.csv"
        second_source.write_text(
            "Region,Amount\nNorth,40\nSouth,50\n",
            encoding="utf-8",
        )
        controller = self.controller()
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        active_table_id = str(controller.activeTableId)
        self.assertTrue(
            controller._commit_import(second_source, parse_file(second_source))
        )
        self.assertTrue(controller.selectTable(active_table_id))
        controller.setCurrentView("Data")
        controller.dataModel.setColumnFilter("Region", "equals", "East")
        controller._dirty = False

        engine, component, window = self.load_main(controller)
        window.resize(1040, 800)
        window.show()
        self.app.processEvents()
        try:
            filter_action = _quick_item_named(
                window.contentItem(), "dataViewFilterRowsButton"
            )
            self.assertIsNotNone(filter_action)
            self.assertTrue(filter_action.isVisible())
            self.assertEqual(filter_action.property("text"), "Filter rows (1)")
            filter_origin = filter_action.mapToItem(
                window.contentItem(), QPointF(0, 0)
            )
            self.assertGreaterEqual(filter_origin.x(), 0)
            self.assertLessEqual(
                filter_origin.x() + filter_action.width(), window.width()
            )
            toolbar_buttons = {
                str(item.property("text")): item
                for item in _quick_items(window.contentItem())
                if str(item.property("text")) in ("Append queries", "Merge queries")
            }
            self.assertTrue(toolbar_buttons["Append queries"].isVisible())
            self.assertTrue(toolbar_buttons["Merge queries"].isVisible())
            name, description, disabled = self.accessible_name_and_description(
                filter_action
            )
            self.assertIn("Filter data view rows", name)
            self.assertIn("preview only", description.casefold())
            self.assertIn("Transform data", description)
            self.assertFalse(disabled)

            filter_action.click()
            self.app.processEvents()
            dialog = window.findChild(QObject, "dataViewColumnFilterDialog")
            self.assertIsNotNone(dialog)
            self.assertTrue(dialog.property("visible"))
            self.assertEqual(dialog.property("columnName"), "Region")

            dialog.close()
            controller.dataModel.clearColumnFilter("Region")
            self.app.processEvents()
            self.assertEqual(filter_action.property("text"), "Filter rows")
            self.assertEqual(controller.dataModel.activeFilterColumns, [])

            controller.dataModel.setColumnFilter("Region", "equals", "East")
            controller.dataModel.setColumnFilter("Amount", "contains", "0")
            self.app.processEvents()
            self.assertEqual(filter_action.property("text"), "Filter rows (2)")
            controller.dataModel.clearColumnFilter("Region")
            self.app.processEvents()
            self.assertEqual(filter_action.property("text"), "Filter rows (1)")
            controller.dataModel.clearColumnFilter("Amount")
            self.app.processEvents()
            self.assertEqual(filter_action.property("text"), "Filter rows")
            self.assertEqual(controller.dataModel.activeFilterColumns, [])
        finally:
            controller._dirty = False
            window.hide()
            window.deleteLater()
            component.deleteLater()
            engine.deleteLater()
            self.app.processEvents()

    def test_report_filters_open_by_default_and_can_collapse_at_minimum_width(self) -> None:
        source = self.root / "VatWithoutRegion.csv"
        source.write_text(
            "Particulars,Value\nA,10\nGrand Total,10\n",
            encoding="utf-8",
        )
        controller = self.controller()
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        controller.setCurrentView("Report")

        engine, component, window = self.load_main(controller)
        window.resize(1040, 680)
        window.show()
        self.app.processEvents()
        try:
            self.assertEqual(window.width(), 1040)
            self.assertTrue(window.property("filtersExpanded"))
            scope = _quick_item_named(window.contentItem(), "filterScopeCombo")
            self.assertIsNotNone(scope)
            self.assertTrue(scope.isVisible())
            region_card = _quick_item_named(
                window.contentItem(), "reportRegionFilterCard"
            )
            self.assertIsNotNone(region_card)
            self.assertFalse(region_card.isVisible())

            canvas = _quick_item_named(window.contentItem(), "reportPageBody")
            self.assertIsNotNone(canvas)
            self.assertTrue(canvas.isVisible())
            self.assertGreater(canvas.width(), 250)

            collapse = _quick_item_named(
                window.contentItem(), "collapseReportFiltersPaneButton"
            )
            self.assertIsNotNone(collapse)
            collapse.click()
            self.app.processEvents()
            self.assertFalse(window.property("filtersExpanded"))
            self.assertFalse(scope.isVisible())

            expand = _quick_item_named(
                window.contentItem(), "expandReportFiltersPaneButton"
            )
            self.assertIsNotNone(expand)
            expand.click()
            self.app.processEvents()
            self.assertTrue(window.property("filtersExpanded"))
            self.assertTrue(scope.isVisible())

            collapse.click()
            self.app.processEvents()
            self.assertFalse(window.property("filtersExpanded"))
            window.runCommand("view.resetLayout")
            self.app.processEvents()
            self.assertTrue(window.property("filtersExpanded"))
            self.assertTrue(scope.isVisible())
        finally:
            controller._dirty = False
            window.hide()
            window.deleteLater()
            component.deleteLater()
            engine.deleteLater()
            self.app.processEvents()

    def test_model_view_opens_data_view_for_row_filters(self) -> None:
        source = self.root / "ModelToData.csv"
        source.write_text("Region,Amount\nEast,10\nWest,20\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        table_id = str(controller.activeTableId)
        controller.setCurrentView("Model")
        controller._dirty = False

        engine, component, window = self.load_main(controller)
        window.resize(1280, 800)
        window.show()
        self.app.processEvents()
        try:
            guidance = _quick_item_named(
                window.contentItem(), "modelWorkspaceFilterGuidance"
            )
            self.assertIsNotNone(guidance)
            self.assertIn("Data = preview filter", str(guidance.property("text")))
            self.assertIn("Transform = saved", str(guidance.property("text")))

            open_data = _quick_item_named(
                window.contentItem(), "modelOpenDataViewButton"
            )
            self.assertIsNotNone(open_data)
            model_root = window.findChild(QObject, "modelViewRoot")
            self.assertTrue(
                open_data.isVisible(),
                f"Model view width: {model_root.width() if model_root else 'missing'}",
            )
            self.assertEqual(open_data.property("text"), "Data view")
            self.assertTrue(open_data.property("enabled"))
            name, description, disabled = self.accessible_name_and_description(
                open_data
            )
            self.assertIn("Open Data view", name)
            self.assertIn("preview", description.casefold())
            self.assertIn("Transform data", description)
            self.assertFalse(disabled)

            open_data.click()
            self.app.processEvents()
            self.assertEqual(controller.currentView, "Data")
            self.assertEqual(str(controller.activeTableId), table_id)
            filter_action = _quick_item_named(
                window.contentItem(), "dataViewFilterRowsButton"
            )
            self.assertIsNotNone(filter_action)
            self.assertTrue(filter_action.isVisible())

            controller.setCurrentView("Model")
            window.resize(1040, 680)
            self.app.processEvents()
            self.assertEqual(window.width(), 1040)
            self.assertFalse(open_data.isVisible())
            table_list_toggle = _quick_item_named(
                window.contentItem(), "toggleModelDiagramButton"
            )
            self.assertIsNotNone(table_list_toggle)
            self.assertEqual(table_list_toggle.property("text"), "Table list")
            table_list_toggle.click()
            self.app.processEvents()
            open_table_data = _quick_item_named(
                window.contentItem(), "openModelTableDataButton"
            )
            self.assertIsNotNone(open_table_data)
            self.assertTrue(open_table_data.isVisible())
            self.assertEqual(
                str(open_table_data.property("tableSourceId")), table_id
            )
            open_table_data.click()
            self.app.processEvents()
            self.assertEqual(controller.currentView, "Data")
            self.assertEqual(str(controller.activeTableId), table_id)
        finally:
            controller._dirty = False
            window.hide()
            window.deleteLater()
            component.deleteLater()
            engine.deleteLater()
            self.app.processEvents()

    def test_data_view_value_filter_search_uses_full_filtered_source_and_typed_keys(self) -> None:
        controller = self.controller()
        model = controller._table_model
        rows = [
            {"Region": "East" if index % 2 == 0 else "West", "Category": f"C-{index:04d}"}
            for index in range(2_005)
        ]
        model.replace_data(
            ["Region", "Category"], rows, table_key="large", column_types={"Region": "text", "Category": "text"}
        )

        all_values = model.columnFilterValues("Category", "")
        self.assertEqual(all_values["matchCount"], 2_005)
        self.assertEqual(len(all_values["values"]), 2_000)
        outside_visible_cap = model.columnFilterValues("Category", "C-2004")
        self.assertEqual(outside_visible_cap["matchCount"], 1)
        self.assertEqual(outside_visible_cap["values"][0]["label"], "C-2004")
        late_key = outside_visible_cap["values"][0]["key"]

        model.setColumnFilter("Region", "equals", "East")
        self.assertEqual(model.columnFilterValues("Category", "")["matchCount"], 1_003)
        self.assertEqual(model.columnFilterValues("Category", "C-2003")["matchCount"], 0)
        self.assertEqual(model.columnFilterValues("Category", "C-2004")["matchCount"], 1)
        model.setColumnValueFilter("Category", False, [late_key])
        self.assertEqual(model.rowCount(), 1)
        self.assertEqual(model.data(model.index(0, 1)), "C-2004")
        refreshed_rows = rows[:-1]
        model.replace_data(
            ["Region", "Category"],
            refreshed_rows,
            table_key="large",
            column_types={"Region": "text", "Category": "text"},
        )
        self.assertEqual(
            model.columnFilter("Category"),
            {"operator": "values", "all": False, "keys": []},
        )
        self.assertEqual(model.rowCount(), 0)
        # An Apply racing with the refresh normalizes stale keys instead of
        # silently retaining the old filter after the dialog closes.
        model.setColumnValueFilter("Category", True, [late_key])
        self.assertEqual(model.columnFilter("Category"), {})
        self.assertEqual(model.pageRange, "Rows 1–500 of 1,002")
        self.assertEqual(model.pageCount, 3)
        # The current column's filter does not hide options from its own checklist.
        self.assertEqual(model.columnFilterValues("Category", "C-2002")["matchCount"], 1)
        model.setColumnFilter("Category", "equals", "C-0002")
        self.assertEqual(model.rowCount(), 1)
        self.assertEqual(model.data(model.index(0, 1)), "C-0002")
        self.assertEqual(model.columnFilter("Category")["operator"], "equals")

        typed_rows = [
            {"Value": 1},
            {"Value": "1"},
            {"Value": None},
            {"Value": ""},
            {"Value": "(Null)"},
            {"Value": Decimal("1.0")},
            {"Value": PowerQueryCellError("DataFormat.Error", "invalid number", row=1)},
            {"Value": PowerQueryCellError("DataFormat.Error", "invalid number", row=2)},
            {"Value": "1 (Number)"},
        ]
        model.replace_data(["Value"], typed_rows, table_key="typed", column_types={"Value": "text"})
        typed_values = model.columnFilterValues("Value", "")
        options = typed_values["values"]
        self.assertEqual(typed_values["matchCount"], 7)
        self.assertEqual(len({option["key"] for option in options}), 7)
        labels = [option["label"] for option in options]
        self.assertEqual(len(set(labels)), 7)
        self.assertIn("1 (Number) (option 2)", labels)
        null_matches = model.columnFilterValues("Value", "(Null)")["values"]
        self.assertEqual(len(null_matches), 2)
        error_matches = [
            option for option in options
            if option["label"] == "Error: invalid number (Error)"
        ]
        self.assertEqual(len(error_matches), 1)
        model.setColumnValueFilter("Value", False, [error_matches[0]["key"]])
        self.assertEqual(model.rowCount(), 2)
        numeric_option = next(option for option in options if option["label"] == "1 (Number)")
        text_option = next(option for option in options if option["label"] == "1 (Text)")
        model.setColumnValueFilter("Value", False, [numeric_option["key"], text_option["key"]])
        self.assertEqual(model.rowCount(), 3)

        model.replace_data(["Other"], [{"Other": "x"}], table_key="other")
        self.assertEqual(model.activeFilterColumns, [])
        model.replace_data(["Value"], typed_rows, table_key="typed", column_types={"Value": "text"})
        self.assertEqual(model.activeFilterColumns, ["Value"])
        self.assertEqual(model.rowCount(), 3)

    def test_data_view_value_filter_qml_search_apply_cancel_clear_and_preview_scope(self) -> None:
        source = self.root / "ValueFilter.csv"
        source.write_text(
            "Category,Region\n" + "".join(
                f"C-{index:04d},{'East' if index % 2 == 0 else 'West'}\n"
                for index in range(2_005)
            ),
            encoding="utf-8",
        )
        controller = self.controller()
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        source_id = str(controller.tableCatalog[0]["sourceId"])
        loaded_rows = deepcopy(controller._loaded_candidates[source_id].rows)
        controller.setCurrentView("Data")
        controller._dirty = False

        engine, component, window = self.load_main(controller)
        window.resize(720, 520)
        window.show()
        self.app.processEvents()

        def item_named(name: str) -> QQuickItem:
            matches = [
                item for item in _quick_items(window.contentItem())
                if item.objectName() == name and item.isVisible()
            ]
            self.assertTrue(matches, f"Visible QML item {name!r} was not found.")
            return matches[-1]

        def click_item(item: QQuickItem) -> None:
            scene_point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2))
            point = QPoint(round(scene_point.x()), round(scene_point.y()))
            QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
            self.app.processEvents()

        def find_category_filter_button() -> QQuickItem:
            matches = [
                item for item in _quick_items(window.contentItem())
                if item.objectName() == "dataViewFilterColumn_0" and item.isVisible()
            ]
            self.assertTrue(matches)
            return max(matches, key=lambda item: item.mapToScene(QPointF(0, 0)).x())

        model = controller._table_model
        click_item(find_category_filter_button())

        filter_dialog = window.findChild(QObject, "dataViewColumnFilterDialog")
        self.assertIsNotNone(filter_dialog)
        self.assertTrue(filter_dialog.property("visible"))
        self.assertLessEqual(filter_dialog.property("width"), window.width())
        self.assertLessEqual(filter_dialog.property("height"), window.height())
        self.assertGreaterEqual(float(filter_dialog.property("x")), 0)
        self.assertGreaterEqual(float(filter_dialog.property("y")), 0)
        self.assertLessEqual(
            float(filter_dialog.property("x")) + float(filter_dialog.property("width")),
            window.width(),
        )
        self.assertLessEqual(
            float(filter_dialog.property("y")) + float(filter_dialog.property("height")),
            window.height(),
        )
        window.resize(360, 300)
        self.app.processEvents()
        self.assertLessEqual(
            float(filter_dialog.property("x")) + float(filter_dialog.property("width")),
            window.width(),
        )
        self.assertLessEqual(
            float(filter_dialog.property("y")) + float(filter_dialog.property("height")),
            window.height(),
        )
        compact_search = window.findChild(QObject, "dataViewFilterSearch")
        self.assertIsNotNone(compact_search)
        compact_search.setProperty("text", "C-2004")
        self.app.processEvents()
        compact_option = item_named("dataViewFilterValueOption_0")
        self.assertTrue(compact_option.property("checked"))
        click_item(compact_option)
        self.assertFalse(compact_option.property("checked"))
        compact_apply = window.findChild(QObject, "dataViewApplyColumnFilter")
        self.assertIsNotNone(compact_apply)
        click_item(compact_apply)
        self.assertEqual(model.pageRange, "Rows 1–500 of 2,004")
        window.resize(720, 520)
        self.app.processEvents()
        click_item(find_category_filter_button())
        compact_clear = window.findChild(QObject, "dataViewClearColumnFilter")
        self.assertIsNotNone(compact_clear)
        click_item(compact_clear)
        self.assertEqual(model.pageRange, "Rows 1–500 of 2,005")
        click_item(find_category_filter_button())
        self.app.processEvents()
        window.resize(392, 392)
        self.app.processEvents()
        search = window.findChild(QObject, "dataViewFilterSearch")
        search.setProperty("text", "C-200")
        self.app.processEvents()
        first_compact_option = item_named("dataViewFilterValueOption_0")
        second_compact_option = item_named("dataViewFilterValueOption_1")
        tabs = window.findChild(QObject, "dataViewFilterTabs")
        _tabs_name, tabs_description, _tabs_disabled = self.accessible_name_and_description(tabs)
        self.assertIn("replaces the current filter", tabs_description)
        click_item(first_compact_option)
        self.assertFalse(first_compact_option.property("checked"))
        click_item(second_compact_option)
        self.assertFalse(second_compact_option.property("checked"))
        compact_apply = window.findChild(QObject, "dataViewApplyColumnFilter")
        _apply_name, apply_description, _apply_disabled = self.accessible_name_and_description(compact_apply)
        self.assertIn("replaces the current filter", apply_description)
        click_item(compact_apply)
        self.assertEqual(model.pageRange, "Rows 1–500 of 2,003")
        window.resize(720, 520)
        self.app.processEvents()
        click_item(find_category_filter_button())
        compact_clear = window.findChild(QObject, "dataViewClearColumnFilter")
        click_item(compact_clear)
        self.assertEqual(model.pageRange, "Rows 1–500 of 2,005")
        click_item(find_category_filter_button())
        self.app.processEvents()
        values_tab = window.findChild(QObject, "dataViewFilterTabValues")
        self.assertIsNotNone(values_tab)
        tab_name, _tab_description, tab_disabled = self.accessible_name_and_description(values_tab)
        self.assertIn("Category", tab_name)
        self.assertFalse(tab_disabled)

        model.setColumnFilter("Region", "equals", "East")
        self.app.processEvents()
        search = window.findChild(QObject, "dataViewFilterSearch")
        self.assertIsNotNone(search)
        search_name, search_description, search_disabled = self.accessible_name_and_description(search)
        self.assertIn("Search values in Category", search_name)
        self.assertIn("display limit does not limit search", search_description)
        self.assertFalse(search_disabled)
        notice = window.findChild(QObject, "dataViewFilterValueNotice")
        self.assertIsNotNone(notice)
        self.assertIn("1003 distinct values", str(notice.property("text")))

        search.setProperty("text", "C-2004")
        self.app.processEvents()
        value_check = item_named("dataViewFilterValueOption_0")
        self.assertTrue(value_check.property("checked"))
        value_name, _value_description, value_disabled = self.accessible_name_and_description(value_check)
        self.assertIn("C-2004", value_name)
        self.assertFalse(value_disabled)
        value_check.forceActiveFocus()
        self.assertTrue(value_check.property("activeFocus"))
        QTest.keyClick(window, Qt.Key.Key_Space)
        self.app.processEvents()
        self.assertFalse(value_check.property("checked"))

        search.setProperty("text", "C-2003")
        self.app.processEvents()
        self.assertFalse(any(
            item.objectName().startswith("dataViewFilterValueOption_") and item.isVisible()
            for item in _quick_items(window.contentItem())
        ))
        select_all = window.findChild(QObject, "dataViewSelectAllValues")
        select_none = window.findChild(QObject, "dataViewSelectNoValues")
        self.assertIsNotNone(select_all)
        self.assertIsNotNone(select_none)
        all_name, all_description, _ = self.accessible_name_and_description(select_all)
        none_name, none_description, _ = self.accessible_name_and_description(select_none)
        self.assertIn("Select all values in Category", all_name)
        self.assertIn("hidden by search", all_description)
        self.assertIn("Select no values in Category", none_name)
        self.assertIn("hidden by search", none_description)
        search.setProperty("text", "C-2004")
        self.app.processEvents()
        value_check = item_named("dataViewFilterValueOption_0")
        self.assertFalse(
            value_check.property("checked"),
            "The excluded value must remain excluded when search changes.",
        )
        click_item(select_all)
        search.setProperty("text", "C-2002")
        self.app.processEvents()
        hidden_value_check = item_named("dataViewFilterValueOption_0")
        self.assertTrue(
            hidden_value_check.property("checked"),
            "Select all must include values hidden by the prior search.",
        )
        click_item(select_none)
        search.setProperty("text", "C-2004")
        self.app.processEvents()
        value_check = item_named("dataViewFilterValueOption_0")
        self.assertFalse(
            value_check.property("checked"),
            "Select no values must deselect values hidden by the prior search.",
        )
        selection_summary = window.findChild(QObject, "dataViewFilterSelectionSummary")
        self.assertIsNotNone(selection_summary)
        self.assertEqual(str(selection_summary.property("text")), "0 values selected")

        apply_button = window.findChild(QObject, "dataViewApplyColumnFilter")
        self.assertIsNotNone(apply_button)
        click_item(apply_button)
        self.assertEqual(model.rowCount(), 0)
        self.assertEqual(model.pageRange, "No rows")
        self.assertEqual(model.activeFilterColumns, ["Region", "Category"])
        self.assertEqual(controller._loaded_candidates[source_id].rows, loaded_rows)
        self.assertFalse(controller._dirty)

        click_item(find_category_filter_button())
        self.assertTrue(filter_dialog.property("visible"))
        self.assertEqual(
            str(selection_summary.property("text")), "0 values selected"
        )
        clear_button = window.findChild(QObject, "dataViewClearColumnFilter")
        self.assertIsNotNone(clear_button)
        self.assertTrue(clear_button.property("enabled"))
        click_item(clear_button)
        self.assertEqual(model.pageRange, "Rows 1–500 of 1,003")
        self.assertEqual(model.activeFilterColumns, ["Region"])

        next_button = item_named("dataViewNextPage")
        self.assertTrue(next_button.property("enabled"))
        clipping_ancestor = next_button.parentItem()
        while clipping_ancestor is not None and not clipping_ancestor.clip():
            clipping_ancestor = clipping_ancestor.parentItem()
        self.assertIsNotNone(clipping_ancestor)
        next_center = next_button.mapToItem(
            clipping_ancestor,
            QPointF(next_button.width() / 2, next_button.height() / 2),
        )
        self.assertGreaterEqual(next_center.x(), 0)
        self.assertGreaterEqual(next_center.y(), 0)
        self.assertLessEqual(next_center.x(), clipping_ancestor.width())
        self.assertLessEqual(next_center.y(), clipping_ancestor.height())
        click_item(next_button)
        self.assertEqual(model.pageRange, "Rows 501–1,000 of 1,003")
        click_item(find_category_filter_button())
        search = window.findChild(QObject, "dataViewFilterSearch")
        search.setProperty("text", "C-2004")
        self.app.processEvents()
        value_check = item_named("dataViewFilterValueOption_0")
        self.assertTrue(value_check.property("checked"))
        click_item(value_check)
        self.assertFalse(value_check.property("checked"))
        click_item(apply_button)
        self.assertEqual(model.rowCount(), 500)
        self.assertEqual(model.pageCount, 3)
        self.assertEqual(model.pageRange, "Rows 1–500 of 1,002")
        self.assertEqual(controller.rowCount, 2_005)
        self.assertEqual(len(controller._loaded_candidates[source_id].rows), 2_005)
        self.assertEqual(controller._loaded_candidates[source_id].rows, loaded_rows)
        self.assertFalse(controller._dirty)

        model.nextPage()
        self.app.processEvents()
        self.assertEqual(model.pageRange, "Rows 501–1,000 of 1,002")
        click_item(find_category_filter_button())
        clear_button = window.findChild(QObject, "dataViewClearColumnFilter")
        self.assertIsNotNone(clear_button)
        self.assertTrue(clear_button.property("enabled"))
        click_item(clear_button)
        self.assertEqual(model.pageRange, "Rows 1–500 of 1,003")
        self.assertEqual(model.activeFilterColumns, ["Region"])
        self.assertEqual(controller._loaded_candidates[source_id].rows, loaded_rows)
        self.assertFalse(controller._dirty)

        window.close()
        window.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_data_fields_pane_switches_between_loaded_tables(self) -> None:
        sales_path = self.root / "Sales.csv"
        sales_path.write_text("Customer,Sales\nA,10\n", encoding="utf-8")
        regions_path = self.root / "Regions.csv"
        regions_path.write_text("Region,Target\nNorth,20\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(sales_path, parse_file(sales_path)))
        sales_id = str(controller.activeTableId)
        self.assertTrue(controller._commit_import(regions_path, parse_file(regions_path)))
        regions_id = str(controller.activeTableId)
        self.assertTrue(controller.selectTable(sales_id))
        controller.setCurrentView("Report")

        engine, component, window = self.load_main(controller)
        window.resize(1280, 800)
        window.show()
        self.app.processEvents()
        selector = _quick_item_named(window.contentItem(), "reportTableSelector")
        field_list = _quick_item_named(window.contentItem(), "reportFieldsList")
        self.assertIsNotNone(selector)
        self.assertIsNotNone(field_list)
        self.assertEqual(controller.activeTableId, sales_id)
        self.assertIsNotNone(_quick_item_named(field_list, "reportFieldSelect_Customer"))
        self.assertIsNone(_quick_item_named(field_list, "reportFieldSelect_Region"))

        selector.forceActiveFocus()
        QTest.keyClick(window, Qt.Key.Key_Down)
        self.app.processEvents()
        self.assertEqual(controller.activeTableId, regions_id)
        self.assertEqual(controller.headers, ["Region", "Target"])
        self.assertIsNotNone(_quick_item_named(field_list, "reportFieldSelect_Region"))
        self.assertIsNone(_quick_item_named(field_list, "reportFieldSelect_Customer"))

        self.assertTrue(controller.selectTable(sales_id))
        controller.setCurrentView("Data")
        self.app.processEvents()
        data_selector = _quick_item_named(window.contentItem(), "dataPaneTableSelector")
        data_field_list = _quick_item_named(window.contentItem(), "dataFieldsList")
        self.assertIsNotNone(data_selector)
        self.assertIsNotNone(data_field_list)
        data_selector.forceActiveFocus()
        QTest.keyClick(window, Qt.Key.Key_Down)
        self.app.processEvents()
        self.assertEqual(controller.activeTableId, regions_id)
        self.assertIsNotNone(
            _quick_item_named(data_field_list, "dataFieldSelect_Region")
        )
        self.assertIsNone(
            _quick_item_named(data_field_list, "dataFieldSelect_Customer")
        )

        controller._dirty = False
        window.hide()
        window.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_model_data_pane_keeps_fields_with_their_table(self) -> None:
        sales_path = self.root / "Sales.csv"
        sales_path.write_text("Customer,Sales\nA,10\n", encoding="utf-8")
        targets_path = self.root / "Targets.csv"
        targets_path.write_text("Region,Target\nNorth,20\n", encoding="utf-8")

        controller = self.controller()
        self.assertTrue(controller._commit_import(sales_path, parse_file(sales_path)))
        sales_id = str(controller.activeTableId)
        self.assertTrue(controller._commit_import(targets_path, parse_file(targets_path)))
        targets_id = str(controller.activeTableId)
        controller.setCurrentView("Model")

        def assert_table_fields(
            window, expected: dict[str, tuple[str, set[str]]]
        ) -> None:
            pane = _quick_item_named(window.contentItem(), "modelDataTableList")
            self.assertIsNotNone(pane)
            entries = [
                item for item in _quick_items(pane)
                if item.objectName() == "modelDataTableEntry"
            ]
            self.assertEqual(
                {str(item.property("tableSourceId")) for item in entries},
                set(expected),
            )
            for entry in entries:
                source_id = str(entry.property("tableSourceId"))
                table_name = next(
                    str(item.property("text"))
                    for item in _quick_items(entry)
                    if item.objectName() == "modelDataTableName"
                )
                expected_name, expected_fields = expected[source_id]
                self.assertEqual(table_name, expected_name)
                fields = {
                    str(item.property("text"))
                    for item in _quick_items(entry)
                    if item.objectName() == "modelDataTableField"
                }
                self.assertEqual(fields, expected_fields)

        engine, component, window = self.load_main(controller)
        window.resize(1280, 800)
        window.show()
        self.app.processEvents()
        expected_fields = {
            sales_id: ("Sales", {"Customer", "Sales"}),
            targets_id: ("Targets", {"Region", "Target"}),
        }
        assert_table_fields(window, expected_fields)

        self.assertTrue(controller.selectTable(sales_id))
        self.app.processEvents()
        assert_table_fields(window, expected_fields)

        project_path = self.root / "model-data-pane.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.activeTableId, sales_id)
        reopened.setCurrentView("Model")
        reopened_engine, reopened_component, reopened_window = self.load_main(reopened)
        reopened_window.resize(1280, 800)
        reopened_window.show()
        self.app.processEvents()
        assert_table_fields(reopened_window, expected_fields)

        reopened._loaded_candidates.pop(targets_id, None)
        reopened._refresh_model_view()
        reopened.stateChanged.emit()
        self.app.processEvents()
        assert_table_fields(
            reopened_window,
            {
                sales_id: ("Sales", {"Customer", "Sales"}),
                targets_id: ("Targets", set()),
            },
        )
        target_entry = next(
            item for item in _quick_items(reopened_window.contentItem())
            if item.objectName() == "modelDataTableEntry"
            and str(item.property("tableSourceId")) == targets_id
        )
        unavailable_label = next(
            item for item in _quick_items(target_entry)
            if item.objectName() == "modelDataTableUnavailable"
        )
        self.assertTrue(unavailable_label.property("visible"))
        self.assertEqual(unavailable_label.property("text"), "Source unavailable")

        window.close()
        reopened_window.close()
        window.deleteLater()
        reopened_window.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        reopened_component.deleteLater()
        reopened_engine.deleteLater()
        self.app.processEvents()

    def test_model_field_selection_inspector_and_summarization_are_table_scoped(self) -> None:
        sales_path = self.root / "Sales.csv"
        sales_path.write_text(
            "Shared,Revenue,Label\n1,10,North\n2,20,South\n", encoding="utf-8"
        )
        targets_path = self.root / "Targets.csv"
        targets_path.write_text(
            "Shared,Revenue,Label\n3,30,East\n4,40,West\n", encoding="utf-8"
        )

        controller = self.controller()
        self.assertTrue(controller._commit_import(sales_path, parse_file(sales_path)))
        self.assertTrue(controller._commit_import(targets_path, parse_file(targets_path)))
        sales = next(table for table in controller.tableCatalog if table["displayName"] == "Sales")
        targets = next(table for table in controller.tableCatalog if table["displayName"] == "Targets")
        sales_id = str(sales["id"])
        targets_id = str(targets["id"])

        engine, component, view, window = self.load_model_window(controller)
        combo = _quick_item_named(view, "modelColumnDefaultSummarization")
        inspector = _quick_item_named(view, "modelColumnInspector")
        self.assertIsNotNone(combo, "The Model view should expose the selected-column property editor.")
        self.assertIsNotNone(inspector)
        self.assertFalse(combo.property("enabled"), "No selection must leave the default disabled.")
        no_selection_name, no_selection_description, no_selection_disabled = (
            self.accessible_name_and_description(combo)
        )
        self.assertTrue(no_selection_name)
        self.assertTrue(no_selection_disabled)
        self.assertIn("select", no_selection_description.casefold())

        sales_shared = _quick_item_named(view, f"modelFieldSelect_{sales_id}_Shared")
        targets_shared = _quick_item_named(view, f"modelFieldSelect_{targets_id}_Shared")
        self.assertIsNotNone(sales_shared, "Numeric fields need a focusable table-scoped selector.")
        self.assertIsNotNone(targets_shared, "The same field name in another table needs its own selector.")
        self.assertTrue(sales_shared.property("activeFocusOnTab"))
        sales_name, sales_description, sales_disabled = self.accessible_name_and_description(sales_shared)
        self.assertFalse(sales_disabled)
        self.assertIn("Sales", sales_name)
        self.assertIn("Shared", sales_name)
        self.assertIn("Sales", sales_description)
        self.assertIn("Shared", sales_description)
        self.assertIn(sales_id, sales_shared.objectName())
        self.assertIn("Shared", sales_shared.objectName())

        self.activate_with_keyboard(window, sales_shared)
        self.assertTrue(combo.property("enabled"))
        self.assertEqual(str(combo.property("currentValue")), "auto")
        inspector_text = self.visible_text(inspector).casefold()
        self.assertIn("sales", inspector_text)
        self.assertIn("shared", inspector_text)
        self.assertIn("whole", inspector_text)
        self.assertIn("number", inspector_text)
        self.assertIn("auto", inspector_text)

        for value in ("auto", "sum", "average", "count"):
            self.select_summarization_with_keyboard(window, combo, value)
            sales = next(table for table in controller.tableCatalog if table["id"] == sales_id)
            self.assertEqual(
                sales["columnSummarizations"].get("Shared"), value,
                "The keyboard-activated option should be sent for this model table ID and column.",
            )

        self.select_summarization_with_keyboard(window, combo, "average")
        targets_shared = _quick_item_named(view, f"modelFieldSelect_{targets_id}_Shared")
        self.activate_with_keyboard(window, targets_shared)
        self.assertEqual(str(combo.property("currentValue")), "auto")
        target_name, target_description, target_disabled = self.accessible_name_and_description(targets_shared)
        self.assertFalse(target_disabled)
        self.assertIn("Targets", target_name)
        self.assertIn("Shared", target_name)
        self.assertIn("Targets", target_description)
        self.assertIn("Shared", target_description)
        self.assertIn(targets_id, targets_shared.objectName())
        self.select_summarization_with_keyboard(window, combo, "count")
        catalog = {str(table["id"]): table for table in controller.tableCatalog}
        self.assertEqual(catalog[sales_id]["columnSummarizations"].get("Shared"), "average")
        self.assertEqual(catalog[targets_id]["columnSummarizations"].get("Shared"), "count")

        window.close()
        window.deleteLater()
        view.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_model_sort_picker_is_keyboard_accessible_table_scoped_and_clearable(self) -> None:
        sales_path = self.root / "Sales.csv"
        sales_path.write_text(
            "Month,MonthNumber,Revenue\nMarch,3,30\nJanuary,1,10\nFebruary,2,20\n",
            encoding="utf-8",
        )
        targets_path = self.root / "Targets.csv"
        targets_path.write_text(
            "Month,MonthNumber,Revenue\nMarch,3,300\nJanuary,1,100\nFebruary,2,200\n",
            encoding="utf-8",
        )

        controller = self.controller()
        self.assertTrue(controller._commit_import(sales_path, parse_file(sales_path)))
        self.assertTrue(controller._commit_import(targets_path, parse_file(targets_path)))
        sales_id = next(
            str(table["id"]) for table in controller.tableCatalog
            if table["displayName"] == "Sales"
        )
        targets_id = next(
            str(table["id"]) for table in controller.tableCatalog
            if table["displayName"] == "Targets"
        )

        engine, component, view, window = self.load_model_window(controller)
        sort_combo = _quick_item_named(view, "modelColumnSortBy")
        self.assertIsNotNone(
            sort_combo,
            "The selected-column inspector should expose Sort by column.",
        )
        self.assertFalse(sort_combo.property("enabled"), "No selection must leave sorting disabled.")
        no_selection_name, no_selection_description, no_selection_disabled = (
            self.accessible_name_and_description(sort_combo)
        )
        self.assertTrue(no_selection_name)
        self.assertTrue(no_selection_disabled)
        self.assertIn("select", no_selection_description.casefold())

        sales_month = _quick_item_named(view, f"modelFieldSelect_{sales_id}_Month")
        targets_month = _quick_item_named(view, f"modelFieldSelect_{targets_id}_Month")
        self.assertIsNotNone(sales_month)
        self.assertIsNotNone(targets_month)
        self.activate_with_keyboard(window, sales_month)
        self.assertTrue(sort_combo.property("enabled"))
        values = [str(option.get("value")) for option in sort_combo.property("model")]
        self.assertIn("", values, "The picker needs a keyboard-accessible no-sort choice.")
        self.assertIn("MonthNumber", values)
        self.assertNotIn("Month", values, "A category cannot be its own sort key.")
        sort_name, sort_description, sort_disabled = self.accessible_name_and_description(sort_combo)
        self.assertFalse(sort_disabled)
        self.assertIn("Sales", sort_name)
        self.assertIn("Month", sort_name)
        self.assertIn("Sales", sort_description)
        self.assertIn("Month", sort_description)

        self.select_model_sort_with_keyboard(window, sort_combo, "MonthNumber")
        sales = next(table for table in controller.tableCatalog if table["id"] == sales_id)
        self.assertEqual(sales["columnSortBy"].get("Month"), "MonthNumber")
        self.assertTrue(sales["columnSortByStatuses"]["Month"]["active"])
        _active_name, active_description, _active_disabled = self.accessible_name_and_description(sort_combo)
        self.assertIn("active", active_description.casefold())

        targets_month = _quick_item_named(view, f"modelFieldSelect_{targets_id}_Month")
        self.assertIsNotNone(targets_month)
        self.activate_with_keyboard(window, targets_month)
        self.assertEqual(str(sort_combo.property("currentValue")), "")
        self.select_model_sort_with_keyboard(window, sort_combo, "MonthNumber")
        catalog = {str(table["id"]): table for table in controller.tableCatalog}
        self.assertEqual(catalog[sales_id]["columnSortBy"].get("Month"), "MonthNumber")
        self.assertEqual(catalog[targets_id]["columnSortBy"].get("Month"), "MonthNumber")

        sales_month = _quick_item_named(view, f"modelFieldSelect_{sales_id}_Month")
        self.assertIsNotNone(sales_month)
        self.activate_with_keyboard(window, sales_month)
        clear_button = _quick_item_named(view, "modelColumnSortClearSelected")
        self.assertIsNotNone(clear_button, "The selected rule needs a distinct Clear action.")
        clear_name, clear_description, clear_disabled = self.accessible_name_and_description(clear_button)
        self.assertFalse(clear_disabled)
        self.assertIn("Sales", clear_name)
        self.assertIn("Month", clear_name)
        self.assertIn("Sales", clear_description)
        self.assertIn("Month", clear_description)
        self.activate_button_with_keyboard(window, clear_button)
        catalog = {str(table["id"]): table for table in controller.tableCatalog}
        self.assertNotIn("Month", catalog[sales_id]["columnSortBy"])
        self.assertEqual(catalog[targets_id]["columnSortBy"].get("Month"), "MonthNumber")
        self.select_model_sort_with_keyboard(window, sort_combo, "MonthNumber")
        self.select_model_sort_with_keyboard(window, sort_combo, "")
        catalog = {str(table["id"]): table for table in controller.tableCatalog}
        self.assertNotIn("Month", catalog[sales_id]["columnSortBy"])

        window.close()
        window.deleteLater()
        view.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_model_saved_sort_rules_clear_missing_category_and_sort_key(self) -> None:
        source = self.root / "Sales.csv"
        source.write_text(
            "Month,MonthNumber,Revenue\nMarch,3,30\nJanuary,1,10\nFebruary,2,20\n",
            encoding="utf-8",
        )
        controller = self.controller()
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        table_id = str(controller.tableCatalog[0]["id"])
        source_id = str(controller.tableCatalog[0]["sourceId"])

        engine, component, view, window = self.load_model_window(controller)
        saved_rules = _quick_item_named(view, "modelSavedSortRules")
        self.assertIsNotNone(saved_rules, "Saved sort rules need a table-independent recovery panel.")

        controller.set_model_column_sort_by(table_id, "Month", "MonthNumber")
        controller._loaded_candidates[source_id] = parse_file(source)
        controller._refresh_model_view()
        controller.stateChanged.emit()
        self.app.processEvents()

        # The category itself is now gone, so its rule must remain discoverable and clearable.
        source.write_text(
            "MonthNumber,Revenue\n3,30\n1,10\n2,20\n",
            encoding="utf-8",
        )
        controller._loaded_candidates[source_id] = parse_file(source)
        controller._refresh_model_view()
        controller.stateChanged.emit()
        self.app.processEvents()
        missing_category_clear = _quick_item_named(
            view, f"modelSavedSortRuleClear_{table_id}_Month"
        )
        self.assertIsNotNone(missing_category_clear)
        category_name, category_description, category_disabled = self.accessible_name_and_description(
            missing_category_clear
        )
        self.assertFalse(category_disabled)
        self.assertIn("Sales", category_name)
        self.assertIn("Month", category_name)
        self.assertIn("Sales", category_description)
        self.assertIn("Month", category_description)
        category_status = controller.tableCatalog[0]["columnSortByStatuses"]["Month"]
        self.assertFalse(category_status["active"])
        self.assertTrue(category_status["reason"])
        self.assertIn("inactive", category_description.casefold())
        self.assertIn("MonthNumber", self.visible_text(saved_rules))
        self.activate_button_with_keyboard(window, missing_category_clear)
        self.assertNotIn("Month", controller.tableCatalog[0]["columnSortBy"])

        # A missing sort key is different: the category remains selectable in the inspector.
        source.write_text(
            "Month,MonthNumber,Revenue\nMarch,3,30\nJanuary,1,10\nFebruary,2,20\n",
            encoding="utf-8",
        )
        controller._loaded_candidates[source_id] = parse_file(source)
        controller._refresh_model_view()
        controller.set_model_column_sort_by(table_id, "Month", "MonthNumber")
        source.write_text(
            "Month,Revenue\nMarch,30\nJanuary,10\nFebruary,20\n",
            encoding="utf-8",
        )
        controller._loaded_candidates[source_id] = parse_file(source)
        controller._refresh_model_view()
        controller.stateChanged.emit()
        self.app.processEvents()

        month_field = _quick_item_named(view, f"modelFieldSelect_{table_id}_Month")
        self.assertIsNotNone(month_field)
        self.activate_with_keyboard(window, month_field)
        sort_combo = _quick_item_named(view, "modelColumnSortBy")
        clear_selected = _quick_item_named(view, "modelColumnSortClearSelected")
        self.assertIsNotNone(sort_combo)
        self.assertIsNotNone(clear_selected)
        _sort_name, sort_description, sort_disabled = self.accessible_name_and_description(sort_combo)
        self.assertFalse(sort_disabled)
        self.assertIn("inactive", sort_description.casefold())
        self.assertIn("MonthNumber", sort_description)
        self.assertIn("inactive", self.visible_text(view).casefold())
        self.assertIn("MonthNumber", self.visible_text(view))
        clear_name, clear_description, clear_disabled = self.accessible_name_and_description(clear_selected)
        self.assertFalse(clear_disabled)
        self.assertIn("Sales", clear_name)
        self.assertIn("Month", clear_name)
        self.assertIn("Sales", clear_description)
        self.assertIn("Month", clear_description)
        self.activate_button_with_keyboard(window, clear_selected)
        self.assertNotIn("Month", controller.tableCatalog[0]["columnSortBy"])

        window.close()
        window.deleteLater()
        view.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_model_saved_sort_rules_keep_disabled_query_clearable(self) -> None:
        left = self.root / "North.csv"
        left.write_text("Month,MonthNumber\nMarch,3\nJanuary,1\n", encoding="utf-8")
        right = self.root / "South.csv"
        right.write_text("Month,MonthNumber\nFebruary,2\nApril,4\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(left, parse_file(left)))
        north_id = str(controller.activeTableId)
        self.assertTrue(controller._commit_import(right, parse_file(right)))
        south_id = str(controller.activeTableId)
        from analytics_studio.query_engine import append_candidates

        candidates = [controller._loaded_candidates[north_id], controller._loaded_candidates[south_id]]
        query_candidate = append_candidates(candidates)
        self.assertTrue(controller._create_saved_query(
            "Combined",
            [north_id, south_id],
            query_candidate,
            {"operation": "append", "source_ids": [north_id, south_id]},
            {"Month": "text", "MonthNumber": "text"},
        ))
        query_id = str(controller.activeTableId)
        query_table_id = next(
            str(table["id"]) for table in controller.tableCatalog
            if table["sourceId"] == query_id
        )
        engine, component, view, window = self.load_model_window(controller)
        saved_rules = _quick_item_named(view, "modelSavedSortRules")
        self.assertIsNotNone(saved_rules)

        controller.set_model_column_sort_by(query_table_id, "Month", "MonthNumber")
        self.assertTrue(controller.setQueryLoadEnabled(query_id, False))
        entry = next(table for table in controller.tableCatalog if table["id"] == query_table_id)
        self.assertFalse(entry["loadEnabled"])

        clear = _quick_item_named(view, f"modelSavedSortRuleClear_{query_table_id}_Month")
        self.assertIsNotNone(saved_rules)
        self.assertIsNotNone(clear, "A load-disabled query's rule must remain clearable.")
        self.assertIn("Combined", self.visible_text(saved_rules))
        name, description, disabled = self.accessible_name_and_description(clear)
        self.assertFalse(disabled)
        self.assertIn("Combined", name)
        self.assertIn("Month", name)
        self.assertIn("Combined", description)
        self.assertIn("Month", description)
        self.assertIn("inactive", description.casefold())
        self.activate_button_with_keyboard(window, clear)
        entry = next(table for table in controller.tableCatalog if table["id"] == query_table_id)
        self.assertNotIn("Month", entry["columnSortBy"])

        window.close()
        window.deleteLater()
        view.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_model_table_list_search_finds_columns_clears_and_opens_data(self) -> None:
        input_tables = {
            "Orders.csv": "OrderId,CustomerId,NetAmount\n1,10,25\n2,11,30\n",
            "Customers.csv": "CustomerId,CustomerName\n10,Ada\n11,Lin\n",
            "Products.csv": "ProductId,StockKeepingUnit,ProductName\n5,SKU-5,Widget\n",
        }
        controller = self.controller()
        source_ids: dict[str, str] = {}
        for filename, contents in input_tables.items():
            path = self.root / filename
            path.write_text(contents, encoding="utf-8")
            self.assertTrue(controller._commit_import(path, parse_file(path)))
            source_ids[path.stem] = str(controller.activeTableId)
        products_id = source_ids["Products"]
        self.assertTrue(controller.selectTable(source_ids["Orders"]))
        controller.setCurrentView("Model")
        controller._dirty = False
        saved_project = deepcopy(controller._project)
        saved_rows = deepcopy(controller._loaded_candidates[products_id].rows)

        engine, component, window = self.load_main(controller)
        cleaned = False

        def cleanup_model_window() -> None:
            nonlocal cleaned
            if cleaned:
                return
            cleaned = True
            controller._dirty = False
            window.hide()
            window.deleteLater()
            component.deleteLater()
            engine.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.app.processEvents()

        self.addCleanup(cleanup_model_window)
        window.resize(1280, 900)
        window.show()
        self.app.processEvents()
        model_view = _quick_item_named(window.contentItem(), "modelViewRoot")
        self.assertIsNotNone(model_view)
        model_view.setProperty("diagramMode", False)
        self.app.processEvents()

        workspace = _quick_item_named(model_view, "modelTableWorkspace")
        header = _quick_item_named(model_view, "modelTableHeaderRegion")
        search_row = _quick_item_named(model_view, "modelTableSearchRow")
        search = _quick_item_named(model_view, "modelTableSearch")
        cards = _quick_item_named(model_view, "modelTableCardsFlow")
        self.assertIsNotNone(workspace)
        self.assertIsNotNone(header)
        self.assertIsNotNone(search_row)
        self.assertIsNotNone(search)
        self.assertIsNotNone(cards)
        self.assertEqual(QColor(search.property("color")).name().upper(), "#344251")
        self.assertEqual(
            QColor(search.property("placeholderTextColor")).name().upper(),
            "#657483",
        )
        search_background = search.property("background")
        self.assertIsNotNone(search_background)
        self.assertEqual(
            search_background.objectName(), "modelTableSearchBackground"
        )
        self.assertEqual(
            QColor(search_background.property("color")).name().upper(), "#FFFFFF"
        )
        self.assertEqual(
            QColor(search_background.property("searchBorderColor")).name().upper(),
            "#7C8993",
        )
        search_background_color = QColor(search_background.property("color"))
        self.assertGreaterEqual(
            _contrast_ratio(
                QColor(search.property("placeholderTextColor")),
                search_background_color,
            ),
            4.5,
        )
        self.assertGreaterEqual(
            _contrast_ratio(
                QColor(search_background.property("searchBorderColor")),
                search_background_color,
            ),
            3.0,
        )
        workspace_origin = workspace.mapToItem(model_view, QPointF(0, 0))
        header_origin = header.mapToItem(model_view, QPointF(0, 0))
        cards_origin = cards.mapToItem(model_view, QPointF(0, 0))
        self.assertLessEqual(abs(header_origin.x() - workspace_origin.x()), 2)
        self.assertGreaterEqual(header.width(), workspace.width() - 2)
        self.assertGreaterEqual(search_row.width(), header.width() - 2)
        self.assertGreaterEqual(cards_origin.y(), header_origin.y() + header.height() - 1)
        search_name, search_description, disabled = self.accessible_name_and_description(search)
        self.assertFalse(disabled)
        self.assertIn("tables and columns", search_name.casefold())
        self.assertIn("does not filter table rows", search_description.casefold())

        def visible_open_buttons() -> list[QQuickItem]:
            return [
                item for item in _quick_items(cards)
                if item.objectName() == "openModelTableDataButton" and item.isVisible()
            ]

        def type_query(query: str) -> None:
            for character in query.upper():
                QTest.keyClick(window, getattr(Qt.Key, f"Key_{character}"))

        self.assertEqual(len(visible_open_buttons()), 3)
        search.forceActiveFocus()
        self.assertTrue(search.property("activeFocus"))
        self.assertEqual(
            QColor(search_background.property("searchBorderColor")).name().upper(),
            "#107C71",
        )
        self.assertGreaterEqual(
            _contrast_ratio(
                QColor(search_background.property("searchBorderColor")),
                search_background_color,
            ),
            3.0,
        )
        type_query("stockkeepingunit")
        self.app.processEvents()
        self.assertEqual(
            str(search.property("text")).casefold(), "stockkeepingunit",
            f"Search text did not reach the TextField: {search.property('text')!r}",
        )
        self.assertEqual(
            str(model_view.property("modelTableSearchText")).casefold(),
            "stockkeepingunit",
        )
        matched_buttons = visible_open_buttons()
        self.assertEqual(len(matched_buttons), 1)
        self.assertEqual(str(matched_buttons[0].property("tableSourceId")), products_id)
        model_view.selectModelColumn(products_id, "StockKeepingUnit")
        self.app.processEvents()
        self.assertEqual(str(model_view.property("selectedModelTableId")), products_id)
        self.assertEqual(
            str(model_view.property("selectedModelColumn")), "StockKeepingUnit"
        )
        selection_notice = _quick_item_named(
            model_view, "modelTableSearchSelectionNotice"
        )
        self.assertIsNotNone(selection_notice)
        self.assertFalse(selection_notice.isVisible())

        clear_button = _quick_item_named(model_view, "clearModelTableSearchButton")
        self.assertIsNotNone(clear_button)
        self.assertTrue(clear_button.isVisible())
        self.activate_button_with_keyboard(window, clear_button)
        self.assertEqual(len(visible_open_buttons()), 3)
        empty_state = _quick_item_named(model_view, "modelTableSearchEmptyState")
        self.assertIsNotNone(empty_state)
        self.assertFalse(empty_state.isVisible())

        search.forceActiveFocus()
        type_query("customers")
        self.app.processEvents()
        matched_buttons = visible_open_buttons()
        self.assertEqual(len(matched_buttons), 1)
        self.assertEqual(
            str(matched_buttons[0].property("tableSourceId")),
            source_ids["Customers"],
        )
        self.assertTrue(selection_notice.isVisible())
        self.assertIn("card is hidden", str(selection_notice.property("text")))
        self.assertIn("properties remain available", str(selection_notice.property("text")))
        self.assertEqual(str(model_view.property("selectedModelTableId")), products_id)
        self.assertEqual(
            str(model_view.property("selectedModelColumn")), "StockKeepingUnit"
        )
        inspector = _quick_item_named(model_view, "modelColumnInspector")
        self.assertIsNotNone(inspector)
        self.assertTrue(inspector.isVisible())
        self.activate_button_with_keyboard(window, clear_button)
        self.assertEqual(len(visible_open_buttons()), 3)
        self.assertFalse(selection_notice.isVisible())

        search.forceActiveFocus()
        type_query("nomatchfield")
        self.app.processEvents()
        self.assertTrue(empty_state.isVisible())
        self.assertTrue(selection_notice.isVisible())
        self.assertIn("No tables or columns match", str(empty_state.property("text")))
        self.assertEqual(visible_open_buttons(), [])
        self.activate_button_with_keyboard(window, clear_button)
        self.assertEqual(len(visible_open_buttons()), 3)

        search.forceActiveFocus()
        type_query("stockkeepingunit")
        self.app.processEvents()
        matched_buttons = visible_open_buttons()
        self.assertEqual(len(matched_buttons), 1)
        self.assertEqual(controller._project, saved_project)
        self.assertEqual(controller._loaded_candidates[products_id].rows, saved_rows)
        self.assertFalse(controller.dirty)
        self.activate_button_with_keyboard(window, matched_buttons[0])
        self.assertEqual(controller.currentView, "Data")
        self.assertEqual(controller.activeTableId, products_id)
        self.assertEqual(controller.headers, ["ProductId", "StockKeepingUnit", "ProductName"])

        cleanup_model_window()

    def test_model_relationship_diagram_routes_each_saved_endpoint_and_selects_fields(self) -> None:
        regions_path = self.root / "Regions.csv"
        regions_path.write_text(
            "RegionID,Region\n1,East\n2,West\n", encoding="utf-8"
        )
        orders_path = self.root / "Orders.csv"
        orders_path.write_text(
            "OrderID,RegionID,BillingRegionID,Revenue\n100,1,2,125\n101,2,1,90\n",
            encoding="utf-8",
        )
        controller = self.controller()
        self.assertTrue(controller._commit_import(regions_path, parse_file(regions_path)))
        self.assertTrue(controller._commit_import(orders_path, parse_file(orders_path)))
        self.create_numeric_calculated_column(controller)
        self.assertTrue(controller.create_measure("Order total", "SUM([Revenue])"))
        regions, orders = controller.tableCatalog
        regions_id = str(regions["id"])
        orders_id = str(orders["id"])
        controller._project["model"]["relationships"] = [{
            "relationship_version": 1,
            "id": "orders-regions",
            "from": "Orders[RegionID]",
            "to": "Regions[RegionID]",
            "from_table_id": orders_id,
            "from_column": "RegionID",
            "to_table_id": regions_id,
            "to_column": "RegionID",
            "cardinality": "many_to_one",
            "cross_filter_direction": "single",
            "is_active": True,
        }, {
            "relationship_version": 1,
            "id": "orders-billing-regions",
            "from": "Orders[BillingRegionID]",
            "to": "Regions[RegionID]",
            "from_table_id": orders_id,
            "from_column": "BillingRegionID",
            "to_table_id": regions_id,
            "to_column": "RegionID",
            "cardinality": "many_to_one",
            "cross_filter_direction": "single",
            "is_active": False,
        }, {
            "relationship_version": 0,
            "id": "legacy-display-link",
            "from": "Old[Key]",
            "to": "Other[Key]",
        }]
        controller._refresh_model_view()
        controller.stateChanged.emit()

        engine, component, view, window = self.load_model_window(
            controller, diagram_mode=None
        )
        def cleanup_model_window() -> None:
            window.close()
            window.deleteLater()
            view.deleteLater()
            component.deleteLater()
            engine.deleteLater()
            self.app.processEvents()

        self.addCleanup(cleanup_model_window)
        toggle = _quick_item_named(view, "toggleModelDiagramButton")
        diagram = _quick_item_named(view, "modelRelationshipDiagram")
        source_summary = _quick_item_named(view, "modelSourceSummary")
        active_fields = _quick_item_named(view, "modelActiveTableFields")
        measures_section = _quick_item_named(view, "daxMeasuresSection")
        self.assertIsNotNone(toggle)
        self.assertIsNotNone(diagram)
        self.assertIsNotNone(source_summary)
        self.assertIsNotNone(active_fields)
        self.assertIsNotNone(measures_section)
        measure_summary = _quick_item_named(view, "diagramMeasuresSummary")
        measure_details = _quick_item_named(view, "daxMeasureDetails")
        calculated_definitions = _quick_item_named(view, "calculatedTableDefinitions")
        column_inspector = _quick_item_named(view, "modelColumnInspector")
        show_definitions = _quick_item_named(view, "showModelMeasureDefinitionsButton")
        self.assertIsNotNone(measure_summary)
        self.assertIsNotNone(measure_details)
        self.assertIsNotNone(calculated_definitions)
        self.assertIsNotNone(column_inspector)
        self.assertIsNotNone(show_definitions)
        self.assertTrue(view.property("diagramMode"))
        self.assertTrue(diagram.property("visible"))
        self.assertFalse(source_summary.property("visible"))
        self.assertFalse(active_fields.property("visible"))
        self.assertTrue(measures_section.property("visible"))
        self.assertTrue(measure_summary.property("visible"))
        self.assertFalse(measure_details.property("visible"))
        self.assertFalse(calculated_definitions.property("visible"))
        self.assertFalse(column_inspector.property("visible"))
        self.assertEqual(len(view.property("diagramNodes").toVariant()), 2)
        self.assertEqual(len(view.property("diagramRelationships").toVariant()), 2)
        relationship = view.property("diagramRelationships").toVariant()[0]
        self.assertEqual(relationship["cardinality"], "many_to_one")
        self.assertEqual(relationship["cross_filter_direction"], "single")
        routes = view.property("diagramRelationshipRoutes").toVariant()
        self.assertEqual(len(routes), 2)
        self.assertEqual(
            {route["relationshipId"] for route in routes},
            {"orders-regions", "orders-billing-regions"},
        )
        self.assertEqual({route["laneOffset"] for route in routes}, {-10, 10})
        self.assertGreater(
            abs(routes[0]["controlX"] - routes[1]["controlX"])
            + abs(routes[0]["controlY"] - routes[1]["controlY"]),
            20,
        )
        self.assertFalse(routes[0]["active"] == routes[1]["active"])
        active_route = next(route for route in routes if route["active"])
        self.assertEqual(active_route["fromMark"], "*")
        self.assertEqual(active_route["toMark"], "1")
        self.assertEqual(active_route["filterDirections"], ["to_from"])

        active_link = _quick_item_named(
            view, "modelDiagramRelationshipLink_orders-regions"
        )
        inactive_link = _quick_item_named(
            view, "modelDiagramRelationshipLink_orders-billing-regions"
        )
        self.assertIsNotNone(active_link)
        self.assertIsNotNone(inactive_link)
        active_name, active_description, _ = self.accessible_name_and_description(active_link)
        inactive_name, inactive_description, _ = self.accessible_name_and_description(inactive_link)
        self.assertIn("Active relationship", active_name)
        self.assertIn("Orders[RegionID]", active_name)
        self.assertIn("Regions[RegionID]", active_name)
        self.assertIn("Filters flow from Regions to Orders", active_description)
        self.assertIn("Inactive relationship", inactive_name)
        self.assertIn("Orders[BillingRegionID]", inactive_name)
        self.assertIn("Regions[RegionID]", inactive_name)
        self.assertIn("dashed inactive relationship", inactive_description.casefold())
        self.assertIn("Configured filter direction", inactive_description)
        self.assertIn("Configured filter direction is from Regions to Orders", inactive_description)
        inactive_link.forceActiveFocus()
        self.app.processEvents()
        self.assertTrue(inactive_link.property("activeFocus"))
        link_background = _quick_item_named(
            view, "modelDiagramRelationshipLinkBackground_orders-billing-regions"
        )
        self.assertIsNotNone(link_background)
        self.assertEqual(int(link_background.property("effectiveBorderWidth")), 2)
        self.assertEqual(
            link_background.property("effectiveBorderColor").name(), "#005a9e"
        )
        self.app.processEvents()
        image = window.grabWindow()
        self.assertFalse(image.isNull())

        def has_route_color(route: dict, color_name: str) -> bool:
            expected = QColor(color_name)
            ratio = image.devicePixelRatio()
            for amount in (0.16, 0.2, 0.24, 0.28, 0.72, 0.76, 0.8, 0.84):
                inverse = 1 - amount
                x = (
                    inverse * inverse * float(route["fromX"])
                    + 2 * inverse * amount * float(route["controlX"])
                    + amount * amount * float(route["toX"])
                )
                y = (
                    inverse * inverse * float(route["fromY"])
                    + 2 * inverse * amount * float(route["controlY"])
                    + amount * amount * float(route["toY"])
                )
                scene_point = diagram.mapToItem(window.contentItem(), QPointF(x, y))
                pixel_x = round(scene_point.x() * ratio)
                pixel_y = round(scene_point.y() * ratio)
                for delta_x in range(-2, 3):
                    for delta_y in range(-2, 3):
                        sample_x = pixel_x + delta_x
                        sample_y = pixel_y + delta_y
                        if not (0 <= sample_x < image.width() and 0 <= sample_y < image.height()):
                            continue
                        sample = image.pixelColor(sample_x, sample_y)
                        if (
                            abs(sample.red() - expected.red()) <= 28
                            and abs(sample.green() - expected.green()) <= 28
                            and abs(sample.blue() - expected.blue()) <= 28
                        ):
                            return True
            return False

        self.assertTrue(has_route_color(active_route, "#107c71"))
        inactive_route = next(route for route in routes if not route["active"])
        self.assertTrue(has_route_color(inactive_route, "#8a949d"))

        self.activate_button_with_keyboard(window, inactive_link)
        self.assertEqual(str(view.property("selectedModelTableId")), orders_id)
        self.assertEqual(str(view.property("selectedModelColumn")), "BillingRegionID")

        self.activate_button_with_keyboard(window, show_definitions)
        self.assertFalse(view.property("diagramMode"))
        self.assertFalse(diagram.property("visible"))
        self.assertTrue(source_summary.property("visible"))
        self.assertTrue(active_fields.property("visible"))
        self.assertTrue(measures_section.property("visible"))
        self.assertFalse(measure_summary.property("visible"))
        self.assertTrue(measure_details.property("visible"))
        self.assertTrue(calculated_definitions.property("visible"))
        self.assertIn("Order total", self.visible_text(measure_details))
        self.assertIn("SUM([Revenue])", self.visible_text(measure_details))
        self.assertIn("Calculated Revenue", self.visible_text(calculated_definitions))
        self.assertIn("[Revenue] * 2", self.visible_text(calculated_definitions))
        table_cards = _quick_item_named(view, "modelTableCardsFlow")
        self.assertTrue(table_cards.property("visible"))
        self.activate_button_with_keyboard(window, toggle)

        self.assertTrue(view.property("diagramMode"))
        self.assertTrue(diagram.property("visible"))
        self.assertEqual(len(view.property("diagramNodes").toVariant()), 2)
        self.assertEqual(len(view.property("diagramRelationships").toVariant()), 2)
        self.assertEqual(view.property("diagramUnmappedRelationshipCount"), 1)
        field = _quick_item_named(
            view, f"modelDiagramFieldSelect_{regions_id}_RegionID"
        )
        self.assertIsNotNone(field)
        field_name, _field_description, _field_disabled = (
            self.accessible_name_and_description(field)
        )
        self.assertIn("Regions column RegionID", field_name)
        self.activate_button_with_keyboard(window, field)
        self.assertEqual(str(view.property("selectedModelTableId")), regions_id)
        self.assertEqual(str(view.property("selectedModelColumn")), "RegionID")
        self.assertTrue(column_inspector.property("visible"))

    def test_compact_model_diagram_keeps_measure_details_and_inspector_out_of_initial_view(self) -> None:
        sales_path = self.root / "Sales.csv"
        sales_path.write_text(
            "ProductKey,Revenue\n1,125\n2,90\n", encoding="utf-8"
        )
        products_path = self.root / "Products.csv"
        products_path.write_text(
            "ProductKey,Product\n1,Widget\n2,Gadget\n", encoding="utf-8"
        )
        controller = self.controller()
        self.assertTrue(controller._commit_import(sales_path, parse_file(sales_path)))
        self.assertTrue(
            controller._commit_import(products_path, parse_file(products_path))
        )
        sales_id = next(
            str(table["id"]) for table in controller.tableCatalog
            if table["name"] == "Sales"
        )
        products_id = next(
            str(table["id"]) for table in controller.tableCatalog
            if table["name"] == "Products"
        )
        self.assertTrue(controller.selectTable(sales_id))
        self.create_numeric_calculated_column(controller)
        self.assertTrue(controller.create_measure("Sales total", "SUM([Revenue])"))
        controller._project["model"]["relationships"] = [{
            "relationship_version": 1,
            "id": "sales-products",
            "from": "Sales[ProductKey]",
            "to": "Products[ProductKey]",
            "from_table_id": sales_id,
            "from_column": "ProductKey",
            "to_table_id": products_id,
            "to_column": "ProductKey",
            "cardinality": "many_to_one",
            "cross_filter_direction": "single",
            "is_active": True,
        }]
        controller._refresh_model_view()
        controller.stateChanged.emit()

        engine, component, view, window = self.load_model_window(
            controller, width=800, diagram_mode=True
        )

        def cleanup_model_window() -> None:
            window.close()
            window.deleteLater()
            view.deleteLater()
            component.deleteLater()
            engine.deleteLater()
            self.app.processEvents()

        self.addCleanup(cleanup_model_window)
        workspace = _quick_item_named(view, "modelTableWorkspace")
        canvas_scroll = _quick_item_named(view, "modelCanvasScrollView")
        diagram = _quick_item_named(view, "modelRelationshipDiagram")
        measure_summary = _quick_item_named(view, "diagramMeasuresSummary")
        measure_details = _quick_item_named(view, "daxMeasureDetails")
        calculated_definitions = _quick_item_named(view, "calculatedTableDefinitions")
        column_inspector = _quick_item_named(view, "modelColumnInspector")
        self.assertIsNotNone(workspace)
        self.assertIsNotNone(canvas_scroll)
        self.assertIsNotNone(diagram)
        self.assertIsNotNone(measure_summary)
        self.assertIsNotNone(measure_details)
        self.assertIsNotNone(calculated_definitions)
        self.assertIsNotNone(column_inspector)
        self.app.processEvents()

        self.assertEqual(int(workspace.property("columns")), 1)
        self.assertTrue(diagram.property("visible"))
        self.assertTrue(measure_summary.property("visible"))
        self.assertFalse(measure_details.property("visible"))
        self.assertFalse(calculated_definitions.property("visible"))
        self.assertFalse(column_inspector.property("visible"))
        self.assertEqual(len(view.property("diagramNodes").toVariant()), 2)
        self.assertEqual(len(view.property("diagramRelationships").toVariant()), 1)
        diagram_bottom = diagram.mapToItem(
            canvas_scroll, QPointF(0, diagram.height())
        ).y()
        self.assertLessEqual(diagram_bottom, float(canvas_scroll.property("availableHeight")))

        show_definitions = _quick_item_named(
            view, "showModelMeasureDefinitionsButton"
        )
        toggle = _quick_item_named(view, "toggleModelDiagramButton")
        self.assertIsNotNone(show_definitions)
        self.assertIsNotNone(toggle)
        self.activate_button_with_keyboard(window, show_definitions)
        self.assertFalse(view.property("diagramMode"))
        self.assertTrue(measure_details.property("visible"))
        self.assertTrue(calculated_definitions.property("visible"))
        self.assertTrue(column_inspector.property("visible"))
        self.activate_button_with_keyboard(window, toggle)
        self.assertTrue(view.property("diagramMode"))
        self.assertTrue(measure_summary.property("visible"))
        self.assertFalse(column_inspector.property("visible"))


    def test_model_diagram_places_linked_tables_together_around_unrelated_table(self) -> None:
        paths = {}
        for table_name in ("Alpha", "Middle", "Omega"):
            path = self.root / f"{table_name}.csv"
            path.write_text("Key,Value\n1,10\n", encoding="utf-8")
            paths[table_name] = path

        controller = self.controller()
        for table_name in ("Alpha", "Middle", "Omega"):
            self.assertTrue(controller._commit_import(
                paths[table_name], parse_file(paths[table_name])
            ))
        table_ids = {
            str(table["name"]): str(table["id"])
            for table in controller.tableCatalog
        }
        alpha_id = table_ids["Alpha"]
        omega_id = table_ids["Omega"]
        controller._project["model"]["relationships"] = [{
            "relationship_version": 1,
            "id": "alpha-omega",
            "from": "Alpha[Key]",
            "to": "Omega[Key]",
            "from_table_id": alpha_id,
            "from_column": "Key",
            "to_table_id": omega_id,
            "to_column": "Key",
            "cardinality": "many_to_one",
            "cross_filter_direction": "single",
            "is_active": True,
        }]
        controller._refresh_model_view()
        controller.stateChanged.emit()

        engine, component, view, window = self.load_model_window(
            controller, diagram_mode=None
        )
        def cleanup_model_window() -> None:
            window.close()
            window.deleteLater()
            view.deleteLater()
            component.deleteLater()
            engine.deleteLater()
            self.app.processEvents()

        self.addCleanup(cleanup_model_window)
        nodes = view.property("diagramNodes").toVariant()
        node_ids = [str(node["id"]) for node in nodes]
        self.assertEqual(len(nodes), 3)
        self.assertEqual(abs(node_ids.index(alpha_id) - node_ids.index(omega_id)), 1)

        route = view.property("diagramRelationshipRoutes").toVariant()[0]
        link = _quick_item_named(view, "modelDiagramRelationshipLink_alpha-omega")
        self.assertIsNotNone(link)
        self.assertTrue(link.property("visible"))
        middle_node = next(node for node in nodes if str(node["id"]) == table_ids["Middle"])
        link_center_x = float(link.x()) + float(link.width()) / 2
        link_center_y = float(link.y()) + float(link.height()) / 2
        self.assertFalse(
            float(middle_node["x"]) <= link_center_x <= float(middle_node["x"]) + float(middle_node["width"])
            and float(middle_node["y"]) <= link_center_y <= float(middle_node["y"]) + float(middle_node["height"])
        )
        self.assertEqual(route["filterDirections"], ["to_from"])
        self.assertEqual(route["fromMark"], "*")
        self.assertEqual(route["toMark"], "1")
        self.activate_button_with_keyboard(window, link)
        self.assertEqual(str(view.property("selectedModelTableId")), alpha_id)
        self.assertEqual(str(view.property("selectedModelColumn")), "Key")

    def test_model_diagram_routes_hub_relationship_around_connected_middle_table(self) -> None:
        paths = {}
        for table_name in ("Alpha", "Beta", "Gamma"):
            path = self.root / f"{table_name}.csv"
            path.write_text("Key,Value\n1,10\n", encoding="utf-8")
            paths[table_name] = path

        controller = self.controller()
        for table_name in ("Alpha", "Beta", "Gamma"):
            self.assertTrue(controller._commit_import(
                paths[table_name], parse_file(paths[table_name])
            ))
        table_ids = {
            str(table["name"]): str(table["id"])
            for table in controller.tableCatalog
        }
        relationships = []
        for relationship_id, target_name in (("alpha-beta", "Beta"), ("alpha-gamma", "Gamma")):
            relationships.append({
                "relationship_version": 1,
                "id": relationship_id,
                "from": "Alpha[Key]",
                "to": f"{target_name}[Key]",
                "from_table_id": table_ids["Alpha"],
                "from_column": "Key",
                "to_table_id": table_ids[target_name],
                "to_column": "Key",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": True,
            })
        controller._project["model"]["relationships"] = relationships
        controller._refresh_model_view()
        controller.stateChanged.emit()

        engine, component, view, window = self.load_model_window(
            controller, width=1500, diagram_mode=None
        )

        def cleanup_model_window() -> None:
            window.close()
            window.deleteLater()
            view.deleteLater()
            component.deleteLater()
            engine.deleteLater()
            self.app.processEvents()

        self.addCleanup(cleanup_model_window)
        nodes = view.property("diagramNodes").toVariant()
        self.assertEqual(len(nodes), 3)
        alpha = next(node for node in nodes if str(node["id"]) == table_ids["Alpha"])
        beta = next(node for node in nodes if str(node["id"]) == table_ids["Beta"])
        gamma = next(node for node in nodes if str(node["id"]) == table_ids["Gamma"])
        self.assertEqual((alpha["row"], alpha["column"]), (0, 1))
        self.assertEqual((beta["row"], gamma["row"]), (1, 1))
        self.assertEqual({beta["column"], gamma["column"]}, {0, 2})

        routes = view.property("diagramRelationshipRoutes").toVariant()
        blockers = {"alpha-gamma": beta, "alpha-beta": gamma}
        for relationship_id, blocker in blockers.items():
            route = next(
                route for route in routes
                if str(route["relationshipId"]) == relationship_id
            )
            self.assertEqual(float(route["detourOffset"]), 0.0)
            blocker_left = float(blocker["x"]) - 16
            blocker_right = float(blocker["x"]) + float(blocker["width"]) + 16
            blocker_top = float(blocker["y"]) - 16
            blocker_bottom = float(blocker["y"]) + float(blocker["height"]) + 16
            for sample_index in range(1, 40):
                amount = sample_index / 40
                inverse = 1 - amount
                x = (
                    inverse * inverse * float(route["fromX"])
                    + 2 * inverse * amount * float(route["controlX"])
                    + amount * amount * float(route["toX"])
                )
                y = (
                    inverse * inverse * float(route["fromY"])
                    + 2 * inverse * amount * float(route["controlY"])
                    + amount * amount * float(route["toY"])
                )
                self.assertFalse(
                    blocker_left <= x <= blocker_right
                    and blocker_top <= y <= blocker_bottom,
                    f"The {relationship_id} link passes behind {blocker['table']['displayName']} "
                    f"at ({x:.1f}, {y:.1f}).",
                )

            link = _quick_item_named(
                view, f"modelDiagramRelationshipLink_{relationship_id}"
            )
            self.assertIsNotNone(link)
            self.assertTrue(link.property("visible"))
            link_left = float(link.x())
            link_top = float(link.y())
            link_right = link_left + float(link.width())
            link_bottom = link_top + float(link.height())
            self.assertFalse(
                link_left < float(blocker["x"]) + float(blocker["width"])
                and link_right > float(blocker["x"])
                and link_top < float(blocker["y"]) + float(blocker["height"])
                and link_bottom > float(blocker["y"]),
                f"The {relationship_id} hit target overlaps {blocker['table']['displayName']}.",
            )

        link = _quick_item_named(view, "modelDiagramRelationshipLink_alpha-gamma")
        self.assertIsNotNone(link)
        self.assertGreaterEqual(
            float(view.property("diagramSceneHeight")),
            max(float(node["y"]) + float(node["height"]) for node in nodes) + 24,
        )
        self.activate_button_with_keyboard(window, link)
        self.assertEqual(str(view.property("selectedModelTableId")), table_ids["Alpha"])
        self.assertEqual(str(view.property("selectedModelColumn")), "Key")

    def test_model_diagram_routes_four_table_hub_without_covering_links(self) -> None:
        paths = {}
        for table_name in ("Alpha", "Beta", "Gamma", "Delta"):
            path = self.root / f"{table_name}.csv"
            path.write_text("Key,Value\n1,10\n", encoding="utf-8")
            paths[table_name] = path

        controller = self.controller()
        for table_name in paths:
            self.assertTrue(controller._commit_import(
                paths[table_name], parse_file(paths[table_name])
            ))
        table_ids = {
            str(table["name"]): str(table["id"])
            for table in controller.tableCatalog
        }
        relationships = []
        for relationship_id, target_name in (
            ("alpha-beta", "Beta"),
            ("alpha-gamma", "Gamma"),
            ("alpha-delta", "Delta"),
        ):
            relationships.append({
                "relationship_version": 1,
                "id": relationship_id,
                "from": "Alpha[Key]",
                "to": f"{target_name}[Key]",
                "from_table_id": table_ids["Alpha"],
                "from_column": "Key",
                "to_table_id": table_ids[target_name],
                "to_column": "Key",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": True,
            })
        controller._project["model"]["relationships"] = relationships
        controller._refresh_model_view()
        controller.stateChanged.emit()

        engine, component, view, window = self.load_model_window(
            controller, width=1500, diagram_mode=None
        )

        def cleanup_model_window() -> None:
            window.close()
            window.deleteLater()
            view.deleteLater()
            component.deleteLater()
            engine.deleteLater()
            self.app.processEvents()

        self.addCleanup(cleanup_model_window)
        nodes = view.property("diagramNodes").toVariant()
        self.assertEqual(len(nodes), 4)
        routes = view.property("diagramRelationshipRoutes").toVariant()
        self.assertEqual(len(routes), 3)
        for route in routes:
            relationship_id = str(route["relationshipId"])
            from_id = str(route["relationship"]["from_table_id"])
            to_id = str(route["relationship"]["to_table_id"])
            link = _quick_item_named(
                view, f"modelDiagramRelationshipLink_{relationship_id}"
            )
            self.assertIsNotNone(link, relationship_id)
            self.assertTrue(link.property("visible"), relationship_id)
            for blocker in nodes:
                if str(blocker["id"]) in (from_id, to_id):
                    continue
                left = float(blocker["x"]) - 16
                right = float(blocker["x"]) + float(blocker["width"]) + 16
                top = float(blocker["y"]) - 16
                bottom = float(blocker["y"]) + float(blocker["height"]) + 16
                for sample_index in range(1, 40):
                    amount = sample_index / 40
                    inverse = 1 - amount
                    x = (
                        inverse * inverse * float(route["fromX"])
                        + 2 * inverse * amount * float(route["controlX"])
                        + amount * amount * float(route["toX"])
                    )
                    y = (
                        inverse * inverse * float(route["fromY"])
                        + 2 * inverse * amount * float(route["controlY"])
                        + amount * amount * float(route["toY"])
                    )
                    self.assertFalse(
                        left <= x <= right and top <= y <= bottom,
                        f"The {relationship_id} link passes behind "
                        f"{blocker['table']['displayName']} at ({x:.1f}, {y:.1f}).",
                    )

                link_left = float(link.x())
                link_top = float(link.y())
                link_right = link_left + float(link.width())
                link_bottom = link_top + float(link.height())
                self.assertFalse(
                    link_left < float(blocker["x"]) + float(blocker["width"])
                    and link_right > float(blocker["x"])
                    and link_top < float(blocker["y"]) + float(blocker["height"])
                    and link_bottom > float(blocker["y"]),
                    f"The {relationship_id} hit target overlaps "
                    f"{blocker['table']['displayName']}.",
                )

    def test_model_diagram_keeps_star_layout_when_an_unrelated_table_is_present(self) -> None:
        table_names = ("Alpha", "Beta", "Gamma", "Epsilon")
        paths = {}
        for table_name in table_names:
            path = self.root / f"{table_name}.csv"
            path.write_text("Key,Value\n1,10\n", encoding="utf-8")
            paths[table_name] = path

        controller = self.controller()
        for table_name in table_names:
            self.assertTrue(controller._commit_import(
                paths[table_name], parse_file(paths[table_name])
            ))
        table_ids = {
            str(table["name"]): str(table["id"])
            for table in controller.tableCatalog
        }
        relationships = []
        for relationship_id, target_name in (
            ("alpha-beta", "Beta"),
            ("alpha-gamma", "Gamma"),
        ):
            relationships.append({
                "relationship_version": 1,
                "id": relationship_id,
                "from": "Alpha[Key]",
                "to": f"{target_name}[Key]",
                "from_table_id": table_ids["Alpha"],
                "from_column": "Key",
                "to_table_id": table_ids[target_name],
                "to_column": "Key",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": True,
            })
        controller._project["model"]["relationships"] = relationships
        controller._refresh_model_view()
        controller.stateChanged.emit()

        engine, component, view, window = self.load_model_window(
            controller, width=1500, diagram_mode=None
        )

        def cleanup_model_window() -> None:
            window.close()
            window.deleteLater()
            view.deleteLater()
            component.deleteLater()
            engine.deleteLater()
            self.app.processEvents()

        self.addCleanup(cleanup_model_window)
        nodes = view.property("diagramNodes").toVariant()
        node_by_name = {
            str(node["table"]["name"]): node for node in nodes
        }
        self.assertEqual(len(nodes), 4)
        self.assertEqual(
            (node_by_name["Alpha"]["row"], node_by_name["Alpha"]["column"]),
            (0, 1),
        )
        self.assertEqual(node_by_name["Epsilon"]["row"], 2)

        route = next(
            route for route in view.property("diagramRelationshipRoutes").toVariant()
            if str(route["relationshipId"]) == "alpha-gamma"
        )
        blocker = node_by_name["Beta"]
        left = float(blocker["x"]) - 16
        right = float(blocker["x"]) + float(blocker["width"]) + 16
        top = float(blocker["y"]) - 16
        bottom = float(blocker["y"]) + float(blocker["height"]) + 16
        for sample_index in range(1, 40):
            amount = sample_index / 40
            inverse = 1 - amount
            x = (
                inverse * inverse * float(route["fromX"])
                + 2 * inverse * amount * float(route["controlX"])
                + amount * amount * float(route["toX"])
            )
            y = (
                inverse * inverse * float(route["fromY"])
                + 2 * inverse * amount * float(route["controlY"])
                + amount * amount * float(route["toY"])
            )
            self.assertFalse(
                left <= x <= right and top <= y <= bottom,
                f"The alpha-gamma link passes behind Beta at ({x:.1f}, {y:.1f}).",
            )
        link = _quick_item_named(view, "modelDiagramRelationshipLink_alpha-gamma")
        self.assertIsNotNone(link)
        self.assertFalse(
            float(link.x()) < float(blocker["x"]) + float(blocker["width"])
            and float(link.x()) + float(link.width()) > float(blocker["x"])
            and float(link.y()) < float(blocker["y"]) + float(blocker["height"])
            and float(link.y()) + float(link.height()) > float(blocker["y"]),
            "The alpha-gamma hit target overlaps Beta.",
        )

    def test_model_diagram_splits_larger_hub_and_spreads_relationship_ports(self) -> None:
        table_names = ("Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta")
        paths = {}
        for table_name in table_names:
            path = self.root / f"{table_name}.csv"
            path.write_text("Key,Value\n1,10\n", encoding="utf-8")
            paths[table_name] = path

        controller = self.controller()
        for table_name in table_names:
            self.assertTrue(controller._commit_import(
                paths[table_name], parse_file(paths[table_name])
            ))
        table_ids = {
            str(table["name"]): str(table["id"])
            for table in controller.tableCatalog
        }
        relationships = []
        for target_name in table_names[1:]:
            relationships.append({
                "relationship_version": 1,
                "id": f"alpha-{target_name.lower()}",
                "from": "Alpha[Key]",
                "to": f"{target_name}[Key]",
                "from_table_id": table_ids["Alpha"],
                "from_column": "Key",
                "to_table_id": table_ids[target_name],
                "to_column": "Key",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": True,
            })
        controller._project["model"]["relationships"] = relationships
        controller._refresh_model_view()
        controller.stateChanged.emit()

        engine, component, view, window = self.load_model_window(
            controller, width=1500, diagram_mode=None
        )

        def cleanup_model_window() -> None:
            window.close()
            window.deleteLater()
            view.deleteLater()
            component.deleteLater()
            engine.deleteLater()
            self.app.processEvents()

        self.addCleanup(cleanup_model_window)
        nodes = view.property("diagramNodes").toVariant()
        self.assertEqual(len(nodes), 6)
        node_by_id = {str(node["id"]): node for node in nodes}
        hub = node_by_id[table_ids["Alpha"]]
        self.assertEqual(hub["row"], 1)
        upper_leaves = [node for node in nodes if node["row"] == 0]
        lower_leaves = [node for node in nodes if node["row"] == 2]
        self.assertEqual(len(upper_leaves), 3)
        self.assertEqual(len(lower_leaves), 2)

        routes = view.property("diagramRelationshipRoutes").toVariant()
        self.assertEqual(len(routes), 5)
        source_ports_by_row = {0: [], 2: []}
        for route in routes:
            relationship_id = str(route["relationshipId"])
            target_id = str(route["relationship"]["to_table_id"])
            target = node_by_id[target_id]
            source_ports_by_row[int(target["row"])].append(float(route["fromX"]))
            link = _quick_item_named(
                view, f"modelDiagramRelationshipLink_{relationship_id}"
            )
            self.assertIsNotNone(link, relationship_id)
            self.assertTrue(link.property("visible"), relationship_id)
            for blocker in nodes:
                if str(blocker["id"]) in (str(hub["id"]), target_id):
                    continue
                left = float(blocker["x"]) - 16
                right = float(blocker["x"]) + float(blocker["width"]) + 16
                top = float(blocker["y"]) - 16
                bottom = float(blocker["y"]) + float(blocker["height"]) + 16
                for sample_index in range(1, 40):
                    amount = sample_index / 40
                    inverse = 1 - amount
                    x = (
                        inverse * inverse * float(route["fromX"])
                        + 2 * inverse * amount * float(route["controlX"])
                        + amount * amount * float(route["toX"])
                    )
                    y = (
                        inverse * inverse * float(route["fromY"])
                        + 2 * inverse * amount * float(route["controlY"])
                        + amount * amount * float(route["toY"])
                    )
                    self.assertFalse(
                        left <= x <= right and top <= y <= bottom,
                        f"The {relationship_id} link passes behind "
                        f"{blocker['table']['displayName']} at ({x:.1f}, {y:.1f}).",
                    )

                link_left = float(link.x())
                link_top = float(link.y())
                link_right = link_left + float(link.width())
                link_bottom = link_top + float(link.height())
                self.assertFalse(
                    link_left < float(blocker["x"]) + float(blocker["width"])
                    and link_right > float(blocker["x"])
                    and link_top < float(blocker["y"]) + float(blocker["height"])
                    and link_bottom > float(blocker["y"]),
                    f"The {relationship_id} hit target overlaps "
                    f"{blocker['table']['displayName']}.",
                )

        for row, ports in source_ports_by_row.items():
            self.assertGreaterEqual(
                len({round(port, 2) for port in ports}),
                2,
                f"Hub relationship ports for row {row} should be spread across the card edge.",
            )

    def test_model_diagram_stacks_large_hub_without_covering_relationships(self) -> None:
        table_names = (
            "Alpha", "Beta", "Gamma", "Delta",
            "Epsilon", "Zeta", "Eta", "Theta",
        )
        paths = {}
        for table_name in table_names:
            path = self.root / f"{table_name}.csv"
            path.write_text("Key,Value\n1,10\n", encoding="utf-8")
            paths[table_name] = path

        controller = self.controller()
        for table_name in table_names:
            self.assertTrue(controller._commit_import(
                paths[table_name], parse_file(paths[table_name])
            ))
        table_ids = {
            str(table["name"]): str(table["id"])
            for table in controller.tableCatalog
        }
        relationships = []
        for target_name in table_names[1:]:
            relationships.append({
                "relationship_version": 1,
                "id": f"alpha-{target_name.lower()}",
                "from": "Alpha[Key]",
                "to": f"{target_name}[Key]",
                "from_table_id": table_ids["Alpha"],
                "from_column": "Key",
                "to_table_id": table_ids[target_name],
                "to_column": "Key",
                "cardinality": "one_to_many",
                "cross_filter_direction": "single",
                "is_active": True,
            })
        controller._project["model"]["relationships"] = relationships
        controller._refresh_model_view()
        controller.stateChanged.emit()

        engine, component, view, window = self.load_model_window(
            controller, width=1500, diagram_mode=None
        )

        def cleanup_model_window() -> None:
            window.close()
            window.deleteLater()
            view.deleteLater()
            component.deleteLater()
            engine.deleteLater()
            self.app.processEvents()

        self.addCleanup(cleanup_model_window)
        nodes = view.property("diagramNodes").toVariant()
        self.assertEqual(len(nodes), 8)
        node_by_id = {str(node["id"]): node for node in nodes}
        hub = node_by_id[table_ids["Alpha"]]
        self.assertEqual(hub["diagramLayout"], "hub_stack")
        self.assertEqual(hub["column"], 0)
        leaves = [node for node in nodes if str(node["id"]) != str(hub["id"])]
        self.assertTrue(all(node["column"] == 1 for node in leaves))
        self.assertEqual({int(node["row"]) for node in nodes}, set(range(7)))

        routes = view.property("diagramRelationshipRoutes").toVariant()
        self.assertEqual(len(routes), 7)
        hub_ports = []
        for route in routes:
            relationship_id = str(route["relationshipId"])
            target_id = str(route["relationship"]["to_table_id"])
            hub_ports.append(round(float(route["fromY"]), 2))
            link = _quick_item_named(
                view, f"modelDiagramRelationshipLink_{relationship_id}"
            )
            self.assertIsNotNone(link, relationship_id)
            self.assertTrue(link.property("visible"), relationship_id)
            for blocker in nodes:
                if str(blocker["id"]) in (str(hub["id"]), target_id):
                    continue
                left = float(blocker["x"]) - 16
                right = float(blocker["x"]) + float(blocker["width"]) + 16
                top = float(blocker["y"]) - 16
                bottom = float(blocker["y"]) + float(blocker["height"]) + 16
                for sample_index in range(1, 40):
                    amount = sample_index / 40
                    inverse = 1 - amount
                    x = (
                        inverse * inverse * float(route["fromX"])
                        + 2 * inverse * amount * float(route["controlX"])
                        + amount * amount * float(route["toX"])
                    )
                    y = (
                        inverse * inverse * float(route["fromY"])
                        + 2 * inverse * amount * float(route["controlY"])
                        + amount * amount * float(route["toY"])
                    )
                    self.assertFalse(
                        left <= x <= right and top <= y <= bottom,
                        f"The {relationship_id} link passes behind "
                        f"{blocker['table']['displayName']} at ({x:.1f}, {y:.1f}).",
                    )

                link_left = float(link.x())
                link_top = float(link.y())
                link_right = link_left + float(link.width())
                link_bottom = link_top + float(link.height())
                self.assertFalse(
                    link_left < float(blocker["x"]) + float(blocker["width"])
                    and link_right > float(blocker["x"])
                    and link_top < float(blocker["y"]) + float(blocker["height"])
                    and link_bottom > float(blocker["y"]),
                    f"The {relationship_id} hit target overlaps "
                    f"{blocker['table']['displayName']}.",
                )

        self.assertEqual(
            len(set(hub_ports)),
            len(routes),
            "Each stacked hub relationship should use its own point on the hub edge.",
        )

    def test_model_view_defaults_to_one_table_diagram_without_relationships(self) -> None:
        source = self.root / "OnlyTable.csv"
        source.write_text("Key,Value\nA,10\n", encoding="utf-8")
        controller = self.controller()
        self.assertTrue(controller._commit_import(source, parse_file(source)))

        engine, component, view, window = self.load_model_window(
            controller, diagram_mode=None
        )
        diagram = _quick_item_named(view, "modelRelationshipDiagram")
        toggle = _quick_item_named(view, "toggleModelDiagramButton")
        self.assertIsNotNone(diagram)
        self.assertIsNotNone(toggle)
        self.assertTrue(view.property("diagramMode"))
        self.assertTrue(diagram.property("visible"))
        self.assertEqual(len(view.property("diagramNodes").toVariant()), 1)
        self.assertEqual(view.property("diagramRelationships").toVariant(), [])

        self.activate_button_with_keyboard(window, toggle)
        self.assertFalse(view.property("diagramMode"))
        self.assertIsNotNone(
            _quick_item_named(
                view,
                f"modelFieldSelect_{controller.tableCatalog[0]['id']}_Key",
            )
        )
        self.activate_button_with_keyboard(window, toggle)
        self.assertTrue(view.property("diagramMode"))
        self.assertEqual(len(view.property("diagramNodes").toVariant()), 1)
        self.assertEqual(view.property("diagramRelationships").toVariant(), [])

        window.close()
        window.deleteLater()
        view.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_model_summarization_inspector_explains_disabled_field_states(self) -> None:
        sales_path = self.root / "Sales.csv"
        sales_path.write_text(
            "Revenue,Label\n10,North\n20,South\n", encoding="utf-8"
        )
        targets_path = self.root / "Targets.csv"
        targets_path.write_text(
            "Revenue,Label\n30,East\n40,West\n", encoding="utf-8"
        )

        controller = self.controller()
        self.assertTrue(controller._commit_import(sales_path, parse_file(sales_path)))
        sales = next(table for table in controller.tableCatalog if table["displayName"] == "Sales")
        sales_id = str(sales["id"])
        self.assertTrue(controller._commit_import(targets_path, parse_file(targets_path)))
        targets = next(table for table in controller.tableCatalog if table["displayName"] == "Targets")
        targets_id = str(targets["id"])
        self.create_numeric_calculated_column(controller)

        engine, component, view, window = self.load_model_window(controller)
        combo = _quick_item_named(view, "modelColumnDefaultSummarization")
        self.assertIsNotNone(combo)

        sales_label = _quick_item_named(view, f"modelFieldSelect_{sales_id}_Label")
        self.assertIsNotNone(sales_label)
        self.activate_with_keyboard(window, sales_label)
        self.assertFalse(combo.property("enabled"))
        _name, text_description, disabled = self.accessible_name_and_description(combo)
        self.assertTrue(disabled)
        self.assertIn("numeric", text_description.casefold())

        calculated = _quick_item_named(view, f"modelFieldSelect_{targets_id}_Calculated Revenue")
        self.assertIsNotNone(calculated, "Calculated fields should remain selectable to explain their state.")
        self.activate_with_keyboard(window, calculated)
        self.assertFalse(combo.property("enabled"))
        _name, calculated_description, disabled = self.accessible_name_and_description(combo)
        self.assertTrue(disabled)
        self.assertIn("calculated", calculated_description.casefold())

        sales_revenue = _quick_item_named(view, f"modelFieldSelect_{sales_id}_Revenue")
        self.assertIsNotNone(sales_revenue)
        self.activate_with_keyboard(window, sales_revenue)
        self.assertTrue(combo.property("enabled"))
        controller._loaded_candidates.pop(str(sales["sourceId"]), None)
        controller._refresh_model_view()
        controller.stateChanged.emit()
        self.app.processEvents()
        self.assertFalse(combo.property("enabled"))
        _name, unavailable_description, disabled = self.accessible_name_and_description(combo)
        self.assertTrue(disabled)
        self.assertIn("unavailable", unavailable_description.casefold())

        window.close()
        window.deleteLater()
        view.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_model_column_inspector_moves_below_cards_on_narrow_layout(self) -> None:
        source = self.root / "Sales.csv"
        source.write_text(
            "Revenue,Label,Month,MonthNumber\n10,North,March,3\n20,South,January,1\n",
            encoding="utf-8",
        )
        controller = self.controller()
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        table_id = str(controller.tableCatalog[0]["id"])

        engine, component, view, window = self.load_model_window(controller, width=1280)
        cards = _quick_item_named(view, "modelTableCardsFlow")
        inspector = _quick_item_named(view, "modelColumnInspector")
        combo = _quick_item_named(view, "modelColumnDefaultSummarization")
        sort_combo = _quick_item_named(view, "modelColumnSortBy")
        field = _quick_item_named(view, f"modelFieldSelect_{table_id}_Revenue")
        self.assertIsNotNone(cards)
        self.assertIsNotNone(inspector)
        self.assertIsNotNone(combo)
        self.assertIsNotNone(sort_combo)
        self.assertIsNotNone(field)
        self.activate_with_keyboard(window, field)
        self.assertTrue(combo.property("enabled"))

        card_point = cards.mapToItem(view, QPointF(0, 0))
        inspector_point = inspector.mapToItem(view, QPointF(0, 0))
        self.assertGreater(inspector_point.x(), card_point.x() + cards.width() * 0.45)
        self.assertLessEqual(abs(inspector_point.y() - card_point.y()), 24)

        window.resize(560, 900)
        view.setWidth(560)
        self.app.processEvents()
        card_point = cards.mapToItem(view, QPointF(0, 0))
        inspector_point = inspector.mapToItem(view, QPointF(0, 0))
        self.assertLessEqual(abs(inspector_point.x() - card_point.x()), 24)
        self.assertGreaterEqual(inspector_point.y(), card_point.y() + cards.height() - 1)
        self.assertGreater(inspector.width(), 200, "The stacked inspector must remain readable.")
        self.assertGreater(combo.width(), 0, "The default control must stay operable when stacked.")
        self.assertGreater(sort_combo.width(), 0, "The sort control must stay operable when stacked.")
        self.assertTrue(combo.property("enabled"))
        self.select_summarization_with_keyboard(window, combo, "sum")
        self.assertEqual(
            controller.tableCatalog[0]["columnSummarizations"].get("Revenue"), "sum"
        )
        self.assertTrue(sort_combo.property("enabled"))
        self.select_model_sort_with_keyboard(window, sort_combo, "Month")
        saved_panel = _quick_item_named(view, "modelSavedSortRules")
        saved_clear = _quick_item_named(view, f"modelSavedSortRuleClear_{table_id}_Revenue")
        self.assertIsNotNone(saved_panel)
        self.assertIsNotNone(saved_clear, "The narrow layout must expose saved-rule recovery.")
        self.assertTrue(saved_panel.property("visible"))
        self.assertGreater(saved_panel.width(), 200, "Saved sort rules must remain readable when stacked.")
        self.assertGreater(saved_clear.width(), 0, "The saved-rule action must remain visible at narrow width.")
        clear_name, clear_description, clear_disabled = self.accessible_name_and_description(saved_clear)
        self.assertFalse(clear_disabled)
        self.assertIn("Sales", clear_name)
        self.assertIn("Revenue", clear_name)
        self.assertIn("Sales", clear_description)
        self.assertIn("Revenue", clear_description)
        self.activate_button_with_keyboard(window, saved_clear)
        self.assertNotIn("Revenue", controller.tableCatalog[0]["columnSortBy"])

        window.close()
        window.deleteLater()
        view.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_data_view_import_button_loads_data_and_clears_field_search(self) -> None:
        source = self.root / "Imported.csv"
        source.write_text(
            "Date,Revenue\n2026-01-01,10\n2026-01-02,20\n",
            encoding="utf-8",
        )
        controller = self.controller()
        engine = QQmlEngine()
        component = QQmlComponent(engine)
        component.loadUrl(QUrl.fromLocalFile(str(self.qml_dir / "Main.qml")))
        self.assertFalse(
            component.isError(), "\n".join(error.toString() for error in component.errors())
        )
        window = component.createWithInitialProperties({"studioController": controller})
        self.assertIsNotNone(
            window, "\n".join(error.toString() for error in component.errors())
        )
        self.app.processEvents()
        window.resize(1280, 800)
        window.show()
        self.app.processEvents()

        controller.setFieldQuery("no matching field")
        self.assertEqual(controller.filteredFields, [])
        controller.setCurrentView("Data")
        self.app.processEvents()

        import_button = _quick_item_named(window.contentItem(), "dataViewImportButton")
        self.assertIsNotNone(import_button)
        point = import_button.mapToScene(
            QPointF(import_button.width() / 2, import_button.height() / 2)
        )

        def accept_preview(dialog: FileImportPreviewDialog) -> int:
            deadline = time.monotonic() + 5
            while not dialog.import_button.isEnabled() and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.005)
            self.assertTrue(dialog.import_button.isEnabled())
            dialog._accept_candidate()
            return QDialog.DialogCode.Accepted

        with (
            patch(
                "analytics_studio.controller.QFileDialog.getOpenFileName",
                return_value=(str(source), "CSV files (*.csv)"),
            ),
            patch.object(FileImportPreviewDialog, "exec", new=accept_preview),
        ):
            QTest.mouseClick(
                window,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                QPoint(round(point.x()), round(point.y())),
            )

        self.app.processEvents()
        self.assertTrue(controller.sourceLoaded)
        self.assertEqual(controller.headers, ["Date", "Revenue"])
        self.assertEqual(controller.rowCount, 2)
        self.assertEqual(controller.filteredFields, ["Date", "Revenue"])
        self.assertEqual(window.property("fieldSearchQuery"), "")
        self.assertTrue(window.property("dataPaneExpanded"))

        controller.setCurrentView("Report")
        self.app.processEvents()
        field_list = _quick_item_named(window.contentItem(), "reportFieldsList")
        self.assertIsNotNone(field_list)
        self.assertIsNotNone(_quick_item_named(field_list, "reportFieldSelect_Date"))
        self.assertIsNotNone(_quick_item_named(field_list, "reportFieldSelect_Revenue"))

        controller._dirty = False
        window.close()
        window.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_data_field_selection_updates_column_profile_and_shows_saved_dax(self) -> None:
        source = self.root / "Sales.csv"
        source.write_text(
            "Date,Revenue\n2026-01-01,10\n2026-01-02,20\n",
            encoding="utf-8",
        )
        controller = self.controller()
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        self.assertTrue(
            controller.create_measure("Total Revenue", "SUM('Sales'[Revenue])"),
            controller.statusMessage,
        )
        controller.setCurrentView("Data")

        engine = QQmlEngine()
        component = QQmlComponent(engine)
        component.loadUrl(QUrl.fromLocalFile(str(self.qml_dir / "Main.qml")))
        self.assertFalse(
            component.isError(), "\n".join(error.toString() for error in component.errors())
        )
        window = component.createWithInitialProperties({"studioController": controller})
        self.assertIsNotNone(
            window, "\n".join(error.toString() for error in component.errors())
        )
        window.show()
        self.app.processEvents()
        self.assertTrue(window.property("dataPaneExpanded"))

        visual_root = window.contentItem()
        field_list = _quick_item_named(visual_root, "dataFieldsList")
        self.assertIsNotNone(field_list)
        field_button = _quick_item_named(field_list, "dataFieldSelect_Revenue")
        self.assertIsNotNone(field_button, "Data view fields should be clickable controls.")
        point = field_button.mapToScene(
            QPointF(field_button.width() / 2, field_button.height() / 2)
        )
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(round(point.x()), round(point.y())),
        )
        self.app.processEvents()
        self.assertEqual(window.property("selectedFieldBinding"), "Revenue")
        column_combo = _quick_item_named(visual_root, "typeColumnCombo")
        self.assertIsNotNone(column_combo)
        self.assertEqual(column_combo.property("currentText"), "Revenue")
        data_page = _quick_item_named(visual_root, "dataPage")
        self.assertIsNotNone(data_page)
        self.assertEqual(
            data_page.property("activeColumnProfile")["column"],
            "Revenue",
            "Selecting a field should refresh the profile to that same column.",
        )

        column_combo.forceActiveFocus()
        QTest.keyClick(window, Qt.Key.Key_Up)
        self.app.processEvents()
        self.assertEqual(
            window.property("selectedFieldBinding"),
            "Date",
            "Changing the profile selector should update the shared field selection.",
        )
        point = field_button.mapToScene(
            QPointF(field_button.width() / 2, field_button.height() / 2)
        )
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(round(point.x()), round(point.y())),
        )
        self.app.processEvents()
        self.assertEqual(window.property("selectedFieldBinding"), "Revenue")
        self.assertEqual(column_combo.property("currentText"), "Revenue")
        self.assertEqual(data_page.property("activeColumnProfile")["column"], "Revenue")

        measure_button = _quick_item_named(
            field_list, "dataFieldSelect___dax_measure__:Total Revenue"
        )
        self.assertIsNotNone(measure_button, "Saved measures should be selectable fields.")
        point = measure_button.mapToScene(
            QPointF(measure_button.width() / 2, measure_button.height() / 2)
        )
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            QPoint(round(point.x()), round(point.y())),
        )
        self.app.processEvents()
        self.assertEqual(window.property("expandedMeasureName"), "Total Revenue")
        formula_text = [
            str(item.property("text"))
            for item in _quick_items(field_list)
            if item.metaObject().indexOfProperty("text") >= 0
            and "SUM('Sales'[Revenue])" in str(item.property("text"))
        ]
        self.assertTrue(formula_text, "The saved DAX expression should be visible in the pane.")

        controller._dirty = False
        window.close()
        window.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_pathless_connector_imports_reset_search_and_open_report_fields(self) -> None:
        cases = (
            (
                "web",
                lambda controller, candidate: controller._commit_web_import(
                    {"url": "https://data.example.test/metrics.json"}, candidate
                ),
                ImportCandidate(
                    "web", ["id", "amount"], [{"id": "1", "amount": "10"}],
                    {"resource_type": "json", "json_path": ["data"]}, [],
                ),
            ),
            (
                "odata",
                lambda controller, candidate: controller._commit_odata_import(
                    {"service_root": "https://data.example.test/odata/"}, candidate
                ),
                ImportCandidate(
                    "odata", ["id", "amount"], [{"id": "1", "amount": "10"}],
                    {
                        "entity_set_name": "Metrics",
                        "entity_url": "https://data.example.test/odata/Metrics",
                    }, [],
                ),
            ),
            (
                "sql_server",
                lambda controller, candidate: controller._commit_sql_server_import(
                    {
                        "server": "sql.example.test", "port": 1433,
                        "database": "analytics", "username": "tester",
                        "driver": "ODBC Driver 18 for SQL Server", "encrypt": True,
                    },
                    "local-secret",
                    candidate,
                ),
                ImportCandidate(
                    "sql_server", ["id", "amount"], [{"id": "1", "amount": "10"}],
                    {
                        "schema": "dbo", "table_name": "Metrics",
                        "object_type": "TABLE",
                    }, [],
                ),
            ),
        )

        for index, (kind, commit, candidate) in enumerate(cases):
            with self.subTest(kind=kind):
                controller = StudioController(
                    self.app,
                    QSettings(
                        str(self.root / f"{kind}-{index}.ini"),
                        QSettings.Format.IniFormat,
                    ),
                )
                engine, component, window = self.load_main(controller)
                window.show()
                self.app.processEvents()
                controller.setFieldQuery("no matching field")
                self.assertEqual(controller.filteredFields, [])

                with patch("analytics_studio.controller.QMessageBox.critical") as error_dialog:
                    with patch("analytics_studio.controller.set_sql_server_password"):
                        committed = commit(controller, candidate)
                error_detail = (
                    str(error_dialog.call_args.args[-1])
                    if error_dialog.called else controller.statusMessage
                )
                self.assertTrue(committed, error_detail)
                self.app.processEvents()
                QTest.qWait(100)
                self.app.processEvents()

                self.assertTrue(controller.sourceLoaded)
                self.assertEqual(controller.filteredFields, ["id", "amount"])
                self.assertEqual(window.property("fieldSearchQuery"), "")
                self.assertTrue(window.property("dataPaneExpanded"))
                field_list = _quick_item_named(window.contentItem(), "reportFieldsList")
                self.assertIsNotNone(field_list)
                self.assertIsNotNone(_quick_item_named(field_list, "reportFieldSelect_id"))
                self.assertIsNotNone(_quick_item_named(field_list, "reportFieldSelect_amount"))

                controller._dirty = False
                window.close()
                window.deleteLater()
                component.deleteLater()
                engine.deleteLater()
                self.app.processEvents()

    def test_opening_populated_project_expands_and_resets_report_fields(self) -> None:
        source = self.root / "Sales.csv"
        source.write_text("Date,Revenue\n2026-01-01,10\n", encoding="utf-8")
        saved = self.controller()
        self.assertTrue(saved._commit_import(source, parse_file(source)))
        project_path = self.root / "Sales.npa"
        self.assertTrue(saved._save_to(project_path))

        reopened = StudioController(
            self.app,
            QSettings(str(self.root / "reopened.ini"), QSettings.Format.IniFormat),
        )
        engine, component, window = self.load_main(reopened)
        window.show()
        self.app.processEvents()
        self.assertFalse(window.property("dataPaneExpanded"))
        reopened.setFieldQuery("no matching field")
        self.assertTrue(reopened.open_project_path(project_path), reopened.statusMessage)
        self.app.processEvents()

        self.assertTrue(reopened.sourceLoaded)
        self.assertEqual(reopened.filteredFields, ["Date", "Revenue"])
        self.assertEqual(window.property("fieldSearchQuery"), "")
        self.assertTrue(window.property("dataPaneExpanded"))
        field_list = _quick_item_named(window.contentItem(), "reportFieldsList")
        self.assertIsNotNone(field_list)
        self.assertIsNotNone(_quick_item_named(field_list, "reportFieldSelect_Date"))
        self.assertIsNotNone(_quick_item_named(field_list, "reportFieldSelect_Revenue"))

        reopened._dirty = False
        window.close()
        window.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_field_drag_adds_to_visual_well_and_filter_builder(self) -> None:
        source = self.root / "Sales.csv"
        source.write_text(
            "Date,Revenue\n2026-01-01,10\n2026-01-02,20\n",
            encoding="utf-8",
        )
        controller = self.controller()
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        self.assertTrue(
            controller.create_measure("Total Revenue", "SUM('Sales'[Revenue])"),
            controller.statusMessage,
        )
        controller.add_visual("column", "Sales by Date", 50, 50, 450, 300)
        engine, component, window = self.load_main(controller)
        window.resize(1280, 800)
        window.show()
        self.app.processEvents()
        QTest.qWait(200)
        self.app.processEvents()

        def drag(
            source_item: QQuickItem,
            target_item: QQuickItem,
            target_local: QPointF | None = None,
        ) -> None:
            start = source_item.mapToScene(
                QPointF(source_item.width() / 2, source_item.height() / 2)
            )
            end = target_item.mapToScene(target_local or QPointF(
                target_item.width() / 2, target_item.height() / 2
            ))
            start_point = QPoint(round(start.x()), round(start.y()))
            target_point = QPoint(round(end.x()), round(end.y()))
            QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=start_point)
            QTest.mouseMove(
                window,
                QPoint(start_point.x() + 12, start_point.y() + 2),
                delay=80,
            )
            QTest.mouseMove(window, target_point, delay=120)
            QTest.mouseRelease(
                window,
                Qt.MouseButton.LeftButton,
                pos=target_point,
            )
            self.app.processEvents()

        date_field = _quick_item_named(window.contentItem(), "reportFieldSelect_Date")
        x_axis_drop = _quick_item_named(window.contentItem(), "visualFieldDrop_X_axis")
        self.assertIsNotNone(date_field)
        self.assertIsNotNone(x_axis_drop)
        visual = next(
            item for item in controller.activeVisualObjects
            if item["title"] == "Sales by Date"
        )
        self.assertEqual(visual.get("fields", {}).get("X-axis", []), [])
        drag(date_field, x_axis_drop)
        self.assertEqual(visual["fields"].get("X-axis"), ["Date"])
        QTest.qWait(100)
        self.app.processEvents()

        measure_binding = "__dax_measure__:Total Revenue"
        measure_field = _quick_item_named(
            window.contentItem(), "reportFieldSelect_" + measure_binding
        )
        y_axis_drop = _quick_item_named(window.contentItem(), "visualFieldDrop_Y_axis")
        self.assertIsNotNone(measure_field)
        self.assertIsNotNone(y_axis_drop)
        drag(measure_field, y_axis_drop)
        self.assertEqual(visual["fields"].get("Y-axis"), [measure_binding])

        direct_visual_id = controller.add_visual("bar", "Direct drop target", 550, 50, 400, 300)
        QTest.qWait(100)
        self.app.processEvents()
        date_field = _quick_item_named(window.contentItem(), "reportFieldSelect_Date")
        direct_visual = _quick_item_named(window.contentItem(), "reportVisual_" + direct_visual_id)
        self.assertIsNotNone(date_field)
        self.assertIsNotNone(direct_visual)
        drag(date_field, direct_visual)
        direct_visual_model = next(
            item for item in controller.activeVisualObjects if item["id"] == direct_visual_id
        )
        self.assertEqual(direct_visual_model["fields"].get("X-axis"), ["Date"])
        QTest.qWait(100)
        self.app.processEvents()
        direct_visual = _quick_item_named(
            window.contentItem(), "reportVisual_" + direct_visual_id
        )
        self.assertIsNotNone(direct_visual)
        drag(measure_field, direct_visual)
        self.assertEqual(
            direct_visual_model["fields"].get("Y-axis"), [measure_binding]
        )

        report_canvas = _quick_item_named(window.contentItem(), "reportPageBody")
        self.assertIsNotNone(report_canvas)
        revenue_field = _quick_item_named(window.contentItem(), "reportFieldSelect_Revenue")
        drag(revenue_field, report_canvas, QPointF(1120, 650))
        created_table = next(
            item for item in controller.activeVisualObjects if item["type"] == "table"
        )
        self.assertEqual(created_table["fields"].get("Fields"), ["Revenue"])
        self.assertLessEqual(created_table["x"] + created_table["width"], 1280)
        self.assertLessEqual(created_table["y"] + created_table["height"], 720)
        drag(measure_field, report_canvas, QPointF(450, 550))
        created_card = next(
            item for item in controller.activeVisualObjects if item["type"] == "card"
        )
        self.assertEqual(
            created_card["fields"].get("Fields"), [measure_binding]
        )

        window.setProperty("filtersExpanded", True)
        self.app.processEvents()
        QTest.qWait(250)
        self.app.processEvents()
        revenue_field = _quick_item_named(window.contentItem(), "reportFieldSelect_Revenue")
        filter_drop = _quick_item_named(window.contentItem(), "filterFieldDropTarget")
        self.assertIsNotNone(revenue_field)
        self.assertIsNotNone(filter_drop)
        self.assertTrue(filter_drop.isVisible())
        drag(revenue_field, filter_drop)
        filter_combo = _quick_item_named(window.contentItem(), "pageFilterFieldCombo")
        self.assertIsNotNone(filter_combo)
        filter_index = int(filter_combo.property("currentIndex"))
        self.assertEqual(
            controller.pageFilterFields[filter_index]["column"],
            "Revenue",
        )
        self.assertEqual(controller.activePageFilters, [])

        drag(
            _quick_item_named(
                window.contentItem(), "reportFieldSelect_" + measure_binding
            ),
            filter_drop,
        )
        self.assertEqual(
            controller.pageFilterFields[int(filter_combo.property("currentIndex"))]["column"],
            "Revenue",
        )
        self.assertIn("DAX measures cannot be used as filter columns", controller.statusMessage)

        scope_combo = _quick_item_named(window.contentItem(), "filterScopeCombo")
        operator_combo = _quick_item_named(window.contentItem(), "pageFilterOperatorCombo")
        value_combo = _quick_item_named(window.contentItem(), "pageFilterValueCombo")
        apply_button = _quick_item_named(window.contentItem(), "applyFieldFilterButton")
        self.assertIsNotNone(scope_combo)
        self.assertIsNotNone(operator_combo)
        self.assertIsNotNone(value_combo)
        self.assertIsNotNone(apply_button)
        scope_combo.setProperty("currentIndex", 1)
        field = controller.pageFilterFields[filter_index]
        operators = controller.pageFilterOperators(str(field["columnType"]))
        equals_operator_index = next(
            index for index, option in enumerate(operators)
            if str(option["value"]) == "equals"
        )
        operator_combo.setProperty("currentIndex", equals_operator_index)
        value_combo.setProperty("editText", "10")
        self.app.processEvents()
        self.assertTrue(apply_button.isEnabled())
        apply_point = apply_button.mapToGlobal(
            QPointF(apply_button.width() / 2, apply_button.height() / 2).toPoint()
        )
        apply_point = window.mapFromGlobal(apply_point.toPoint())
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            apply_point,
        )
        self.app.processEvents()
        self.assertEqual(controller.activePageFilters[0]["column"], "Revenue")
        rows_by_table, _, _ = controller._report_filter_context("Sales by Date")
        filtered_rows = rows_by_table[controller.activeTableId]
        self.assertEqual([row["Revenue"] for row in filtered_rows], ["10"])

        date_field_index = next(
            index for index, item in enumerate(controller.pageFilterFields)
            if item["column"] == "Date"
        )
        date_field = controller.pageFilterFields[date_field_index]
        equals_operator_index = next(
            index for index, option in enumerate(
                controller.pageFilterOperators(str(date_field["columnType"]))
            )
            if str(option["value"]) == "equals"
        )
        scope_combo.setProperty("currentIndex", 0)
        filter_field_combo = _quick_item_named(window.contentItem(), "pageFilterFieldCombo")
        filter_field_combo.setProperty("currentIndex", date_field_index)
        operator_combo.setProperty("currentIndex", equals_operator_index)
        value_combo.setProperty("editText", "2026-01-01")
        self.app.processEvents()
        QTest.qWait(100)
        self.app.processEvents()
        self.assertTrue(apply_button.isEnabled())
        apply_point = window.mapFromGlobal(
            apply_button.mapToGlobal(
                QPointF(apply_button.width() / 2, apply_button.height() / 2).toPoint()
            )
        ).toPoint()
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            apply_point,
        )
        self.app.processEvents()
        self.assertEqual(controller.activeReportFilters[0]["column"], "Date")
        self.assertEqual(controller.activePageFilters[0]["column"], "Revenue")

        scope_combo.setProperty("currentIndex", 2)
        controller.selectVisual("Sales by Date")
        visual_target_combo = _quick_item_named(window.contentItem(), "visualFilterTargetCombo")
        self.assertIsNotNone(visual_target_combo)
        self.assertEqual(
            visual_target_combo.property("currentIndex"),
            controller.activePageVisuals.index("Sales by Date"),
        )
        filter_field_combo.setProperty("currentIndex", date_field_index)
        value_combo.setProperty("editText", "2026-01-02")
        self.app.processEvents()
        QTest.qWait(100)
        self.app.processEvents()
        self.assertTrue(apply_button.isEnabled())
        apply_point = window.mapFromGlobal(
            apply_button.mapToGlobal(
                QPointF(apply_button.width() / 2, apply_button.height() / 2).toPoint()
            )
        ).toPoint()
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            apply_point,
        )
        self.app.processEvents()
        self.assertEqual(controller.activeVisualFilters[0]["visualName"], "Sales by Date")
        self.assertEqual(controller.activeVisualFilters[0]["column"], "Date")

        clear_filters_button = _quick_item_named(
            window.contentItem(), "clearFiltersButton"
        )
        self.assertIsNotNone(clear_filters_button)
        self.assertTrue(clear_filters_button.isEnabled())
        clear_point = window.mapFromGlobal(
            clear_filters_button.mapToGlobal(
                QPointF(
                    clear_filters_button.width() / 2,
                    clear_filters_button.height() / 2,
                ).toPoint()
            ).toPoint()
        )
        QTest.mouseClick(
            window,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            clear_point,
        )
        self.app.processEvents()
        self.assertEqual(controller.activeReportFilters, [])
        self.assertEqual(controller.activePageFilters, [])
        self.assertEqual(controller.activeVisualFilters, [])

        controller._dirty = False
        window.close()
        window.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_report_fields_add_columns_and_measures_to_valid_visual_wells(self) -> None:
        source = self.root / "Sales.csv"
        source.write_text(
            "Date,Revenue\n2026-01-01,10\n2026-01-02,20\n",
            encoding="utf-8",
        )
        controller = self.controller()
        self.assertTrue(controller._commit_import(source, parse_file(source)))
        self.assertTrue(
            controller.create_measure("Total Revenue", "SUM('Sales'[Revenue])"),
            controller.statusMessage,
        )
        controller.add_visual("column", "Revenue by Date", 50, 50, 450, 300)
        controller.setCurrentView("Report")

        engine = QQmlEngine()
        component = QQmlComponent(engine)
        component.loadUrl(QUrl.fromLocalFile(str(self.qml_dir / "Main.qml")))
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

        visual_root = window.contentItem()
        field_list = _quick_item_named(visual_root, "reportFieldsList")
        self.assertIsNotNone(field_list)

        def click_item(item: QQuickItem) -> None:
            point = item.mapToScene(
                QPointF(item.width() / 2, item.height() / 2)
            )
            QTest.mouseClick(
                window,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
                QPoint(round(point.x()), round(point.y())),
            )
            self.app.processEvents()

        date_field = _quick_item_named(field_list, "reportFieldSelect_Date")
        date_add = _quick_item_named(field_list, "reportFieldAdd_Date")
        self.assertIsNotNone(date_field)
        self.assertIsNotNone(date_add)
        click_item(date_field)
        self.assertEqual(window.property("selectedFieldBinding"), "Date")
        click_item(date_add)
        x_axis = _quick_item_named(visual_root, "reportFieldWell_X-axis")
        self.assertIsNotNone(x_axis)
        click_item(x_axis)

        measure_binding = "__dax_measure__:Total Revenue"
        measure_field = _quick_item_named(
            field_list, "reportFieldSelect_" + measure_binding
        )
        measure_add = _quick_item_named(
            field_list, "reportFieldAdd_" + measure_binding
        )
        self.assertIsNotNone(measure_field)
        self.assertIsNotNone(measure_add)
        click_item(measure_field)
        formula_text = [
            str(item.property("text"))
            for item in _quick_items(field_list)
            if item.metaObject().indexOfProperty("text") >= 0
        ]
        self.assertIn("SUM('Sales'[Revenue])", formula_text)
        click_item(measure_add)
        visible_wells = [
            item.objectName()
            for item in _quick_items(visual_root)
            if item.objectName().startswith("reportFieldWell_") and item.isVisible()
        ]
        self.assertEqual(visible_wells, ["reportFieldWell_Y-axis"])
        y_axis = _quick_item_named(visual_root, "reportFieldWell_Y-axis")
        self.assertIsNotNone(y_axis)
        click_item(y_axis)

        visual = controller._project["report"]["pages"][0]["visuals"][-1]
        self.assertEqual(visual["fields"]["X-axis"], ["Date"])
        self.assertEqual(visual["fields"]["Y-axis"], [measure_binding])

        controller.add_visual("scatter", "Revenue Scatter", 520, 50, 400, 300)
        self.app.processEvents()
        measure_add = _quick_item_named(
            field_list, "reportFieldAdd_" + measure_binding
        )
        self.assertIsNotNone(measure_add)
        self.assertFalse(
            measure_add.property("enabled"),
            "Scatter charts have no field well that accepts DAX measures.",
        )

        controller._dirty = False
        window.close()
        window.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        self.app.processEvents()

    def test_model_view_renders_created_relationship_after_reopen_and_refresh(self) -> None:
        regions_path = self.root / "Regions.csv"
        regions_path.write_text(
            "RegionID,Region,Multiplier\n1,East,2\n2,West,3\n",
            encoding="utf-8",
        )
        orders_path = self.root / "Orders.csv"
        orders_path.write_text(
            "OrderID,RegionID,Amount\n100,1,10\n101,1,5\n102,2,20\n",
            encoding="utf-8",
        )

        controller = self.controller()
        self.assertTrue(controller._commit_import(regions_path, parse_file(regions_path)))
        regions_id = str(controller.activeTableId)
        self.assertTrue(controller._commit_import(orders_path, parse_file(orders_path)))
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
            relationship_dialog.cross_filter.findData("both")
        )
        relationship_dialog.active_check.setChecked(True)
        relationship_dialog._apply_form()

        def accept_relationship() -> QDialog.DialogCode:
            relationship_dialog._save()
            return relationship_dialog.result()

        with (
            patch(
                "analytics_studio.controller.RelationshipDialog",
                return_value=relationship_dialog,
            ),
            patch.object(relationship_dialog, "exec", side_effect=accept_relationship),
        ):
            self.assertTrue(controller.manage_relationships(), controller.statusMessage)
        relationship_dialog.deleteLater()

        orders_table = controller._model_table_for_source(
            controller._project, orders_id
        )
        self.assertIsNotNone(orders_table)
        self.assertTrue(controller.create_measure(
            "Weighted sales",
            "SUMX('Orders', 'Orders'[Amount] * RELATED('Regions'[Multiplier]))",
        ), controller.statusMessage)
        self.assertEqual(controller.reportKpis["Weighted sales"], "90")

        project_path = self.root / "model-view-lifecycle.npa"
        self.assertTrue(controller._save_to(project_path))
        reopened = self.controller()
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual(reopened.reportKpis["Weighted sales"], "90")
        relationship_text = reopened.modelRelationships[0]
        self.assertIn("Regions[RegionID]", relationship_text)
        self.assertIn("Orders[RegionID]", relationship_text)
        self.assertIn("one-to-many", relationship_text)
        engine, component, view = self.load_view(reopened, "ModelView.qml")
        repeater = view.findChild(QObject, "savedRelationshipRepeater")
        self.assertIsNotNone(repeater)
        self.assertEqual(repeater.property("count"), 1)
        self.assertEqual(repeater.property("model"), [relationship_text])
        empty_message = next(
            obj for obj in view.findChildren(QObject)
            if obj.metaObject().indexOfProperty("text") >= 0
            and str(obj.property("text")).startswith("No relationships yet.")
        )
        self.assertFalse(empty_message.property("visible"))

        orders_path.write_text(
            "OrderID,RegionID,Amount\n100,1,12\n101,1,5\n102,2,20\n",
            encoding="utf-8",
        )
        reopened.refresh_all_sources()
        self.assertEqual(reopened.reportKpis["Weighted sales"], "94")

        view.deleteLater()
        component.deleteLater()
        engine.deleteLater()
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
