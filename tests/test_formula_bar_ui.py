"""Drive the real QML window: ribbon commands, the formula bar, IntelliSense popup and banner."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QSettings, Qt, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file

QQuickStyle.setStyle("Basic")
QML = Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml"


class FormulaBarWindowTests(unittest.TestCase):
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
            {"studioController": self.controller})
        self.assertIsNotNone(self.window, "\n".join(e.toString() for e in self.component.errors()))
        self.window.resize(1500, 900)
        self.window.show()
        self.window.requestActivate()
        QTest.qWaitForWindowExposed(self.window)
        self.controller.setCurrentView("Data")
        self.process()
        self.bar = self.controller.formulaBar

    def tearDown(self) -> None:
        self.controller._dirty = False
        self.bar.cancel()  # closing the window now asks about an unsaved draft
        self.window.close()
        self.window.deleteLater()
        self.component.deleteLater()
        self.engine.deleteLater()
        self.process()
        self.temp_dir.cleanup()

    def process(self) -> None:
        for _ in range(4):
            self.app.processEvents()
            QTest.qWait(10)

    def child(self, name: str) -> QObject:
        """Find an item by objectName: object tree first, then the visual tree (repeater delegates)."""
        item = self.window.findChild(QObject, name)
        if item is None:
            matches: list[QObject] = []

            def walk(parent: QObject) -> None:
                for candidate in parent.childItems():
                    if candidate.objectName() == name:
                        matches.append(candidate)
                    walk(candidate)

            walk(self.window.contentItem())
            item = next((m for m in matches if m.isVisible()), matches[0] if matches else None)
        self.assertIsNotNone(item, name)
        return item

    def type_text(self, text: str) -> None:
        for character in text:
            QTest.keyClick(self.window, character)
            self.app.processEvents()
        self.process()

    def type_formula(self, name: str, expression: str) -> None:
        """Type like a user: replace the selected name, then continue after the existing ' = '."""
        self.type_text(name)
        self.key(Qt.Key.Key_End)
        self.type_text(expression)

    def key(self, key: Qt.Key, modifier: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> None:
        QTest.keyClick(self.window, key, modifier)
        self.process()

    def measure(self, name: str) -> dict | None:
        return next((m for m in self.controller.modelMeasures if m["name"] == name), None)

    def completion_labels(self) -> list[str]:
        root = self.child("formulaBarRoot")
        return [item["label"] for item in root.property("completionItems").toVariant()] \
            if hasattr(root.property("completionItems"), "toVariant") else \
            [item["label"] for item in root.property("completionItems")]

    def popup_open(self) -> bool:
        return bool(self.child("formulaBarCompletionPopup").property("opened"))

    def banner_text(self) -> str:
        banner = self.child("formulaBarBanner")
        return str(self.child("formulaBarBannerText").property("text")) if banner.isVisible() else ""

    def open_measure(self) -> None:
        self.window.runCommand("data.newMeasure")
        self.process()

    # ------------------------------------------------------------------ tests

    def test_new_measure_command_opens_the_bar_with_the_name_selected(self) -> None:
        root = self.child("formulaBarRoot")
        self.assertFalse(root.isVisible())
        self.open_measure()
        self.assertTrue(self.bar.active)
        self.assertTrue(root.isVisible())
        editor = self.child("formulaBarEditor")
        self.assertEqual(editor.property("text"), "Measure = ")
        self.assertEqual(editor.property("selectedText"), "Measure")
        self.assertTrue(editor.property("activeFocus"))
        self.assertEqual(self.child("formulaBarLineNumbers").childItems()[0].property("text") or "1", "1")

    def test_type_accept_with_tab_and_commit_with_enter(self) -> None:
        self.open_measure()
        self.type_formula("Total qty", "SUM(Orders[Qu")
        self.assertTrue(self.popup_open(), "typing after Table[ shows the column list")
        self.assertEqual(self.completion_labels(), ["Quantity"])
        self.key(Qt.Key.Key_Tab)
        editor = self.child("formulaBarEditor")
        self.assertEqual(editor.property("text"), "Total qty = SUM(Orders[Quantity]")
        self.assertFalse(self.popup_open())
        self.type_text(")")
        self.key(Qt.Key.Key_Return)
        # like Power BI the committed measure stays selected and its saved formula stays shown
        self.assertTrue(self.bar.active)
        self.assertFalse(self.bar.isNew)
        self.assertFalse(self.bar.dirty)
        self.assertEqual(self.bar.text, "Total qty = SUM(Orders[Quantity])")
        self.assertEqual(self.bar.error, "")
        created = self.measure("Total qty")
        self.assertIsNotNone(created)
        self.assertEqual(created["expression"], "SUM(Orders[Quantity])")
        self.assertEqual(created["value"], "5")

    def test_typing_d_lists_the_date_functions_and_enter_accepts_the_first(self) -> None:
        self.open_measure()
        self.type_formula("Date check", "d")
        labels = self.completion_labels()
        self.assertEqual(labels[:4], ["DATATABLE", "DATE", "DATEADD", "DATEDIFF"])
        self.assertTrue(self.popup_open())
        self.key(Qt.Key.Key_Down)
        self.key(Qt.Key.Key_Return)  # accepts DATE( - it must not commit the formula
        self.assertTrue(self.bar.active)
        self.assertEqual(self.child("formulaBarEditor").property("text"), "Date check = DATE(")
        self.assertIsNone(self.measure("Date check"))
        hint = self.child("formulaBarSignaturePopup")
        self.assertTrue(hint.property("opened"), "the parameter hint follows the accepted function")

    def test_invalid_formula_shows_the_engine_error_in_the_banner_and_is_not_committed(self) -> None:
        self.open_measure()
        self.type_formula("Bad", "SUM(Orders[Nope])")
        self.assertTrue(self.bar.active)
        self.key(Qt.Key.Key_Return)
        self.assertTrue(self.bar.active, "a failed commit keeps the bar open")
        self.assertIn("Nope", self.banner_text())
        self.assertIsNone(self.measure("Bad"))

    def test_live_validation_shows_the_banner_while_typing(self) -> None:
        self.open_measure()
        self.type_formula("Bad", "FOO(1)")
        self.assertEqual(self.banner_text(), "")
        QTest.qWait(700)
        self.process()
        self.assertIn("FOO", self.banner_text())
        self.assertIsNone(self.measure("Bad"))

    def test_escape_closes_the_popup_first_then_cancels(self) -> None:
        self.open_measure()
        self.type_formula("Measure", "su")
        self.assertTrue(self.popup_open())
        self.key(Qt.Key.Key_Escape)
        self.assertFalse(self.popup_open())
        self.assertTrue(self.bar.active)
        self.key(Qt.Key.Key_Escape)
        self.assertFalse(self.bar.active)
        self.assertFalse(self.child("formulaBarRoot").isVisible())
        self.assertEqual(self.controller.modelMeasures, [])

    def test_shift_enter_inserts_a_line_and_adds_a_line_number(self) -> None:
        self.open_measure()
        self.type_formula("Two", "1")
        self.key(Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        self.type_text("+ 1")
        self.assertTrue(self.bar.active)
        editor = self.child("formulaBarEditor")
        self.assertEqual(editor.property("text"), "Two = 1\n+ 1")
        self.assertEqual(editor.property("lineCount"), 2)
        numbers = [c.property("text") for c in self.child("formulaBarLineNumbers").childItems()
                   if c.property("text")]
        self.assertEqual(numbers, ["1", "2"])
        self.key(Qt.Key.Key_Return)
        self.assertEqual(self.measure("Two")["value"], "2")

    def test_check_and_cross_buttons(self) -> None:
        self.open_measure()
        self.type_formula("Total qty", "SUM(Orders[Quantity])")
        self.child("formulaBarCommit").click()
        self.process()
        self.assertIsNotNone(self.measure("Total qty"))
        self.open_measure()
        self.child("formulaBarCancel").click()
        self.process()
        self.assertFalse(self.bar.active)

    def test_unsupported_function_cannot_be_accepted_and_says_why(self) -> None:
        self.open_measure()
        self.type_formula("Wtd", "dateswtd")
        self.assertIn("DATESWTD", self.completion_labels())
        self.key(Qt.Key.Key_Tab)
        editor = self.child("formulaBarEditor")
        self.assertEqual(editor.property("text"), "Wtd = dateswtd", "nothing was inserted")
        self.assertIn("not supported", self.banner_text().lower())

    def test_new_column_command_uses_the_same_bar(self) -> None:
        self.window.runCommand("model.newCalculatedColumn")
        self.process()
        self.assertTrue(self.bar.active)
        self.assertEqual(self.bar.mode, "column")
        self.type_formula("Line total", "[Qu")
        self.assertEqual(self.completion_labels(), ["Quantity"])
        self.key(Qt.Key.Key_Tab)
        self.type_text(" * [Unit")
        self.key(Qt.Key.Key_Tab)
        self.key(Qt.Key.Key_Return)
        self.assertEqual(self.bar.error, "")
        self.assertEqual(self.controller._headers, ["Quantity", "Unit price", "Line total"])
        self.assertTrue(self.bar.active)
        self.assertFalse(self.bar.isNew, "the saved column's formula stays shown, like Power BI")
        self.assertEqual(self.bar.text, "Line total = [Quantity] * [Unit price]")

    def test_works_from_report_view_too(self) -> None:
        self.controller.setCurrentView("Report")
        self.process()
        self.open_measure()
        self.assertTrue(self.child("formulaBarRoot").isVisible())
        self.type_formula("Total qty", "SUM(Orders[Quantity])")
        self.key(Qt.Key.Key_Return)
        self.assertIsNotNone(self.measure("Total qty"))

    # ------------------------------------------------------------------ contextual ribbon tabs

    def tabs(self) -> list[str]:
        return [str(tab) for tab in self.window.property("visibleRibbonTabs").toVariant()] \
            if hasattr(self.window.property("visibleRibbonTabs"), "toVariant") \
            else [str(tab) for tab in self.window.property("visibleRibbonTabs")]

    def test_table_tools_tab_appears_in_data_view_only(self) -> None:
        self.assertIn("Table tools", self.tabs())
        self.assertNotIn("Measure tools", self.tabs())
        self.controller.setCurrentView("Report")
        self.process()
        self.assertNotIn("Table tools", self.tabs())

    def test_new_measure_switches_to_the_measure_tools_tab_with_working_controls(self) -> None:
        self.open_measure()
        self.assertIn("Measure tools", self.tabs())
        self.assertEqual(self.window.property("ribbonTabName"), "Measure tools")
        name_box = self.child("measureNameBox")
        self.assertEqual(name_box.property("text"), "Measure")
        self.assertTrue(name_box.property("enabled"))
        name_box.setProperty("text", "Total qty")
        name_box.metaObject().invokeMethod(name_box, "editingFinished")
        self.process()
        self.assertEqual(self.bar.text, "Total qty = ")
        self.assertEqual(self.child("formulaBarEditor").property("text"), "Total qty = ")
        self.assertEqual(self.child("measureHomeTableBox").property("displayText"), "Orders")

    def test_unsupported_ribbon_controls_are_disabled_with_a_reason(self) -> None:
        self.open_measure()
        for name in ("measureFormatBox", "measureDataCategoryBox"):
            box = self.child(name)
            self.assertFalse(box.property("enabled"), name)
            self.assertIn("not supported", str(box.property("disabledReason")).lower())

    def test_leaving_the_measure_closes_the_measure_tools_tab(self) -> None:
        self.open_measure()
        self.bar.cancel()
        self.process()
        self.assertNotIn("Measure tools", self.tabs())
        self.assertEqual(self.window.property("ribbonTabName"), "Home")

    def test_selecting_a_measure_in_the_data_pane_shows_its_formula(self) -> None:
        self.assertTrue(self.controller.create_measure("Total qty", "SUM(Orders[Quantity])"))
        self.process()
        self.window.setProperty("selectedFieldBinding", "__dax_measure__:Total qty")
        self.process()
        self.assertIn("Measure tools", self.tabs())
        self.assertTrue(self.bar.active)
        self.assertEqual(self.bar.text, "Total qty = SUM(Orders[Quantity])")
        self.assertEqual(self.window.property("ribbonTabName"), "Measure tools")
        self.window.setProperty("selectedFieldBinding", "Quantity")
        self.process()
        self.assertFalse(self.bar.active)
        self.assertNotIn("Measure tools", self.tabs())

    def test_editing_the_selected_measure_renames_and_updates_it(self) -> None:
        self.assertTrue(self.controller.create_measure("Total qty", "SUM(Orders[Quantity])"))
        self.window.setProperty("selectedFieldBinding", "__dax_measure__:Total qty")
        self.process()
        editor = self.child("formulaBarEditor")
        editor.forceActiveFocus()
        self.key(Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
        self.type_text(" + 1")
        self.assertTrue(self.bar.dirty)
        self.key(Qt.Key.Key_Return)
        self.assertEqual(self.measure("Total qty")["value"], "6")
        self.assertEqual(len(self.controller.modelMeasures), 1)

    def test_right_click_menu_on_a_field_offers_new_measure_and_new_column(self) -> None:
        from PySide6.QtCore import QPointF
        field = self.child("dataFieldSelect_Quantity")
        center = field.mapToScene(QPointF(field.width() / 2, field.height() / 2)).toPoint()
        QTest.mouseClick(self.window, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, center)
        self.process()
        menu = self.child("fieldContextMenu")
        self.assertTrue(menu.property("visible"), "right-click opens the field menu")
        self.assertEqual(self.window.property("selectedFieldBinding"), "Quantity")
        self.child("fieldMenuNewColumn").click()
        self.process()
        self.assertTrue(self.bar.active)
        self.assertEqual(self.bar.mode, "column")
        self.bar.cancel()
        self.process()
        QTest.mouseClick(self.window, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, center)
        self.process()
        self.child("fieldMenuNewMeasure").click()
        self.process()
        self.assertEqual(self.bar.mode, "measure")
        self.assertTrue(self.bar.isNew)

    def click_item(self, item: QObject) -> None:
        from PySide6.QtCore import QPointF
        center = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        QTest.mouseClick(self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
        self.process()

    def test_clicking_the_real_ribbon_buttons_opens_the_bar_and_the_quick_measure_dialog(self) -> None:
        from unittest.mock import patch
        self.window.setProperty("ribbonTabName", "Table tools")
        self.process()
        self.click_item(self.child("ribbonCommand_data.newMeasure"))
        self.assertTrue(self.bar.active)
        self.assertEqual(self.bar.mode, "measure")
        self.assertEqual(self.window.property("ribbonTabName"), "Measure tools")
        self.bar.cancel()
        self.window.setProperty("ribbonTabName", "Table tools")
        self.process()
        self.click_item(self.child("ribbonCommand_model.newCalculatedColumn"))
        self.assertTrue(self.bar.active)
        self.assertEqual(self.bar.mode, "column")
        self.bar.cancel()
        self.window.setProperty("ribbonTabName", "Table tools")
        self.process()
        with patch.object(self.controller, "quick_measure_dialog") as quick:
            self.click_item(self.child("ribbonCommand_data.quickMeasure"))
        quick.assert_called_once_with()

    def test_clicking_a_completion_row_accepts_it_and_the_hint_shows_with_the_list(self) -> None:
        self.open_measure()
        self.type_formula("Total qty", "SUM(Orders[Q")
        self.assertTrue(self.popup_open())
        self.assertTrue(self.child("formulaBarSignaturePopup").property("opened"),
                        "the SUM(ColumnName) hint stays up while the column list is open")
        self.click_item(self.child("formulaBarCompletionItem_Quantity"))
        self.assertEqual(self.child("formulaBarEditor").property("text"), "Total qty = SUM(Orders[Quantity]")
        self.assertFalse(self.popup_open())

    def test_parse_error_banner_has_the_engine_message(self) -> None:
        self.open_measure()
        self.type_formula("Bad", "SUM(")
        self.key(Qt.Key.Key_Return)
        self.assertIn("ends unexpectedly", self.banner_text())
        self.assertIsNone(self.measure("Bad"))

    def test_closing_the_window_with_an_unsaved_draft_asks_and_cancel_keeps_it(self) -> None:
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox

        self.open_measure()
        self.type_formula("Draft", "SUM(Orders[Quantity])")
        self.assertTrue(self.bar.dirty)
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Cancel) as ask:
            self.window.close()
            self.process()
        self.assertEqual(ask.call_count, 1)
        self.assertTrue(self.window.isVisible())
        self.assertTrue(self.bar.dirty)
        self.assertEqual(self.bar.text, "Draft = SUM(Orders[Quantity])")

    def test_editing_another_measure_with_an_unsaved_draft_asks_first(self) -> None:
        from unittest.mock import patch
        from PySide6.QtWidgets import QMessageBox

        self.assertTrue(self.controller.create_measure("Other", "SUM(Orders[Quantity])"))
        self.open_measure()
        self.type_formula("Draft", "SUM(Orders[Quantity])")
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Cancel) as ask:
            self.window.runCommand("data.newMeasure")
            self.assertFalse(self.bar.beginEditMeasure("Other"))
        self.assertEqual(ask.call_count, 2)
        self.assertEqual(self.bar.text, "Draft = SUM(Orders[Quantity])")

    def test_quick_measure_stays_enabled_because_its_engine_exists(self) -> None:
        self.assertTrue(self.window.commandAvailable("data.quickMeasure"))


if __name__ == "__main__":
    unittest.main()
