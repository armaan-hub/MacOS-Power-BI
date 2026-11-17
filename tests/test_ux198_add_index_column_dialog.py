"""Tests for Task 198: Add Index Column like Power BI."""

from unittest import TestCase
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QLineEdit,
    QPushButton,
    QToolButton,
)

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import (
    AddIndexColumnDialog,
    TransformDataDialog,
)
from analytics_studio.power_query_m import steps_to_m_script
from analytics_studio.transformations import apply_transformations


def _cand(headers: list[str], rows: list[dict[str, str]]) -> ImportCandidate:
    return ImportCandidate("inline", headers, rows, {}, [])


def _sample_source() -> ImportCandidate:
    return _cand(
        ["Name", "Score"],
        [
            {"Name": "Alice", "Score": "90"},
            {"Name": "Bob", "Score": "85"},
            {"Name": "Charlie", "Score": "95"},
        ],
    )


class AddIndexColumnDialogTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["add index column tests"])

    def test_ribbon_menu_entries_and_order(self) -> None:
        source = _sample_source()
        dialog = TransformDataDialog(source, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        button = dialog.ribbon_command_buttons.get("add_index_column")
        self.assertIsNotNone(button)
        menu = button.menu()
        self.assertIsNotNone(menu)
        actions = menu.actions()
        self.assertEqual(len(actions), 3)

        self.assertEqual(actions[0].text(), "From 0")
        self.assertEqual(actions[0].objectName(), "indexColumnFrom0Action")
        self.assertTrue(actions[0].isEnabled())

        self.assertEqual(actions[1].text(), "From 1")
        self.assertEqual(actions[1].objectName(), "indexColumnFrom1Action")
        self.assertTrue(actions[1].isEnabled())

        self.assertEqual(actions[2].text(), "Custom...")
        self.assertEqual(actions[2].objectName(), "indexColumnCustomAction")
        self.assertTrue(actions[2].isEnabled())

    def test_from_0_adds_step_and_preview(self) -> None:
        source = _sample_source()
        dialog = TransformDataDialog(source, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        button = dialog.ribbon_command_buttons["add_index_column"]
        action_from_0 = next(a for a in button.menu().actions() if a.objectName() == "indexColumnFrom0Action")
        action_from_0.trigger()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(
            dialog._steps[0],
            {"op": "add_index_column", "new_name": "Index", "start": 0, "increment": 1},
        )
        self.assertEqual(dialog.step_list.item(0).text(), "Added Index")

        preview = dialog._preview_candidate
        self.assertIn("Index", preview.headers)
        self.assertEqual([row["Index"] for row in preview.rows], [0, 1, 2])

    def test_from_1_adds_step_and_preview(self) -> None:
        source = _sample_source()
        dialog = TransformDataDialog(source, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        button = dialog.ribbon_command_buttons["add_index_column"]
        action_from_1 = next(a for a in button.menu().actions() if a.objectName() == "indexColumnFrom1Action")
        action_from_1.trigger()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(
            dialog._steps[0],
            {"op": "add_index_column", "new_name": "Index", "start": 1, "increment": 1},
        )
        self.assertEqual(dialog.step_list.item(0).text(), "Added Index")

        preview = dialog._preview_candidate
        self.assertIn("Index", preview.headers)
        self.assertEqual([row["Index"] for row in preview.rows], [1, 2, 3])

    def test_custom_dialog_defaults_execution_and_m_script(self) -> None:
        source = _sample_source()
        dialog = TransformDataDialog(source, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        button = dialog.ribbon_command_buttons["add_index_column"]
        action_custom = next(a for a in button.menu().actions() if a.objectName() == "indexColumnCustomAction")
        action_custom.trigger()
        self.app.processEvents()

        sub = dialog._operation_dialog
        self.assertIsInstance(sub, AddIndexColumnDialog)
        self.assertEqual(sub.windowTitle(), "Add Index Column")
        self.assertEqual(sub.windowModality(), Qt.WindowModality.ApplicationModal)
        self.assertEqual(sub.start_edit.text(), "0")
        self.assertEqual(sub.increment_edit.text(), "1")

        sub.start_edit.setText("10")
        sub.increment_edit.setText("5")
        sub.ok_button.click()
        self.app.processEvents()

        self.assertIsNone(dialog._operation_dialog)
        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(
            dialog._steps[0],
            {"op": "add_index_column", "new_name": "Index", "start": 10, "increment": 5},
        )
        self.assertEqual(dialog.step_list.item(0).text(), "Added Index")

        preview = dialog._preview_candidate
        self.assertIn("Index", preview.headers)
        self.assertEqual([row["Index"] for row in preview.rows], [10, 15, 20])

        m_code = steps_to_m_script(dialog._steps, "TestQuery")
        self.assertIn("Table.AddIndexColumn(", m_code)
        self.assertIn('"Index", 10, 5, Int64.Type)', m_code)

    def test_ok_button_validation(self) -> None:
        dlg = AddIndexColumnDialog()
        self.addCleanup(dlg.deleteLater)
        dlg.show()
        self.app.processEvents()

        # Defaults (0, 1) -> OK enabled
        self.assertTrue(dlg.ok_button.isEnabled())

        # Empty -> disabled
        dlg.start_edit.setText("")
        self.assertFalse(dlg.ok_button.isEnabled())

        # "abc" -> rejected by validator, text remains "" or invalid
        dlg.start_edit.setText("abc")
        self.assertFalse(dlg.ok_button.isEnabled())

        # "1.5" -> rejected by validator / not whole number
        dlg.start_edit.setText("1.5")
        self.assertFalse(dlg.ok_button.isEnabled())

        # "-3" -> valid signed whole number
        dlg.start_edit.setText("-3")
        self.assertTrue(dlg.ok_button.isEnabled())

        # Same checks on increment_edit
        dlg.increment_edit.setText("")
        self.assertFalse(dlg.ok_button.isEnabled())

        dlg.increment_edit.setText("abc")
        self.assertFalse(dlg.ok_button.isEnabled())

        dlg.increment_edit.setText("1.5")
        self.assertFalse(dlg.ok_button.isEnabled())

        dlg.increment_edit.setText("-2")
        self.assertTrue(dlg.ok_button.isEnabled())

    def test_cancel_adds_no_step(self) -> None:
        source = _sample_source()
        dialog = TransformDataDialog(source, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        button = dialog.ribbon_command_buttons["add_index_column"]
        action_custom = next(a for a in button.menu().actions() if a.objectName() == "indexColumnCustomAction")
        action_custom.trigger()
        self.app.processEvents()

        sub = dialog._operation_dialog
        self.assertIsInstance(sub, AddIndexColumnDialog)
        sub.start_edit.setText("100")
        sub.cancel_button.click()
        self.app.processEvents()

        self.assertIsNone(dialog._operation_dialog)
        self.assertEqual(len(dialog._steps), 0)

    def test_gear_edit_preserves_new_name_and_updates_step(self) -> None:
        source = _sample_source()
        step = {"op": "add_index_column", "new_name": "Row", "start": 0, "increment": 1}
        dialog = TransformDataDialog(source, [step], query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        dialog.step_list.setCurrentRow(0)
        self.app.processEvents()

        dialog._edit_selected_step_settings()
        self.app.processEvents()

        sub = dialog._operation_dialog
        self.assertIsInstance(sub, AddIndexColumnDialog)
        self.assertEqual(sub.start_edit.text(), "0")
        self.assertEqual(sub.increment_edit.text(), "1")

        sub.start_edit.setText("7")
        sub.ok_button.click()
        self.app.processEvents()

        self.assertIsNone(dialog._operation_dialog)
        self.assertEqual(
            dialog._steps[0],
            {"op": "add_index_column", "new_name": "Row", "start": 7, "increment": 1},
        )
        self.assertEqual(
            dialog._preview_candidate,
            apply_transformations(source, dialog._steps),
        )
        self.assertEqual([row["Row"] for row in dialog._preview_candidate.rows], [7, 8, 9])
