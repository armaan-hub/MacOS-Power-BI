"""Tests for Task 196: Replace Values dialog, typed values, null, ReplaceText, and special characters."""

from unittest import TestCase
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
)

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import (
    ReplaceValuesDialog,
    TransformDataDialog,
)
from analytics_studio.power_query_m import (
    _step_to_m_call,
    parse_m_script,
    steps_to_m_script,
)
from analytics_studio.transformations import (
    TransformationError,
    apply_transformations,
)


class ReplaceValuesTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_engine_text_value_exact(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Status"],
            [{"Status": "Open"}, {"Status": "open"}, {"Status": "Opened"}],
            {},
            [],
        )
        step = {
            "op": "replace_value",
            "column": "Status",
            "value": "Open",
            "replacement": "Closed",
            "replacer": "value",
        }
        res = apply_transformations(source, [step])
        self.assertEqual(res.rows[0]["Status"], "Closed")
        self.assertEqual(res.rows[1]["Status"], "open")
        self.assertEqual(res.rows[2]["Status"], "Opened")

    def test_engine_text_substring(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Code"],
            [{"Code": "a-b-a"}],
            {},
            [],
        )
        step = {
            "op": "replace_value",
            "column": "Code",
            "value": "a",
            "replacement": "x",
            "replacer": "text",
        }
        res = apply_transformations(source, [step])
        self.assertEqual(res.rows[0]["Code"], "x-b-x")

    def test_engine_number_column_typed_not_string(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Amount"],
            [{"Amount": 5}, {"Amount": "5"}, {"Amount": 5.0}],
            {},
            [],
        )
        step = {
            "op": "replace_value",
            "column": "Amount",
            "value": 5,
            "replacement": 7,
            "replacer": "value",
        }
        res = apply_transformations(source, [step])
        self.assertEqual(res.rows[0]["Amount"], 7)
        self.assertEqual(res.rows[1]["Amount"], "5")
        self.assertEqual(res.rows[2]["Amount"], 7)

    def test_engine_null_replacement_on_text(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Note"],
            [{"Note": None}, {"Note": "existing"}],
            {},
            [],
        )
        step = {
            "op": "replace_value",
            "column": "Note",
            "value": None,
            "replacement": "n/a",
            "replacer": "value",
        }
        res = apply_transformations(source, [step])
        self.assertEqual(res.rows[0]["Note"], "n/a")
        self.assertEqual(res.rows[1]["Note"], "existing")

    def test_engine_text_on_number_cell_refused(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Amount"],
            [{"Amount": 42}],
            {},
            [],
        )
        step = {
            "op": "replace_value",
            "column": "Amount",
            "value": "4",
            "replacement": "5",
            "replacer": "text",
        }
        with self.assertRaises(TransformationError) as ctx:
            apply_transformations(source, [step])
        self.assertIn("Amount", str(ctx.exception))

    def test_emitted_m_exact_string_and_round_trip(self) -> None:
        step_text = {
            "op": "replace_value",
            "column": "Col",
            "value": "a",
            "replacement": "b",
            "replacer": "text",
        }
        self.assertEqual(
            _step_to_m_call('#"Prev"', step_text),
            'Table.ReplaceValue(#"Prev", "a", "b", Replacer.ReplaceText, {"Col"})',
        )

        step_num = {
            "op": "replace_value",
            "column": "Amount",
            "value": 5,
            "replacement": 7,
            "replacer": "value",
        }
        self.assertEqual(
            _step_to_m_call('#"Prev"', step_num),
            'Table.ReplaceValue(#"Prev", 5, 7, Replacer.ReplaceValue, {"Amount"})',
        )

        step_null = {
            "op": "replace_value",
            "column": "Col",
            "value": None,
            "replacement": "n/a",
            "replacer": "value",
        }
        self.assertEqual(
            _step_to_m_call('#"Prev"', step_null),
            'Table.ReplaceValue(#"Prev", null, "n/a", Replacer.ReplaceValue, {"Col"})',
        )

        # Round trips
        for step in (step_text, step_num, step_null):
            script = steps_to_m_script([step], "Query")
            parsed = parse_m_script(script, "Query")
            self.assertEqual(parsed, [step])

    def test_old_step_without_replacer_still_runs(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Status"],
            [{"Status": "Open"}],
            {},
            [],
        )
        old_step = {
            "op": "replace_value",
            "column": "Status",
            "value": "Open",
            "replacement": "Closed",
        }
        res = apply_transformations(source, [old_step])
        self.assertEqual(res.rows[0]["Status"], "Closed")

    def test_dialog_advanced_options_visibility_by_type(self) -> None:
        # Text column shows advanced toggle
        dlg_text = ReplaceValuesDialog("Name", column_type="text")
        dlg_text.show()
        self.app.processEvents()
        self.assertTrue(dlg_text.advanced_toggle.isVisible())
        self.assertFalse(dlg_text.advanced_panel.isVisible())
        dlg_text.advanced_toggle.click()
        self.assertTrue(dlg_text.advanced_panel.isVisible())
        dlg_text.deleteLater()

        # Number column hides advanced toggle and panel
        dlg_num = ReplaceValuesDialog("Amount", column_type="whole_number")
        dlg_num.show()
        self.app.processEvents()
        self.assertFalse(dlg_num.advanced_toggle.isVisible())
        self.assertFalse(dlg_num.advanced_panel.isVisible())
        dlg_num.deleteLater()

    def test_dialog_special_characters_insertion_and_unescape(self) -> None:
        dlg = ReplaceValuesDialog("TextCol", column_type="text")
        dlg.find_edit.setFocus()
        dlg.advanced_toggle.click()
        dlg.special_chars_box.setChecked(True)
        self.assertTrue(dlg.insert_special_combo.isEnabled())

        # Select Tab from dropdown
        tab_index = -1
        for i in range(dlg.insert_special_combo.count()):
            if dlg.insert_special_combo.itemData(i) == "#(tab)":
                tab_index = i
                break
        self.assertGreater(tab_index, 0)
        dlg.insert_special_combo.activated.emit(tab_index)
        self.assertIn("#(tab)", dlg.find_edit.text())

        # Replace With field
        dlg.replace_edit.setFocus()
        dlg.replace_edit.setText("val")

        step = dlg.step()
        self.assertEqual(step["value"], "\t")
        self.assertEqual(step["replacement"], "val")
        dlg.deleteLater()

    def test_dialog_special_characters_unchecked_keeps_literal(self) -> None:
        dlg = ReplaceValuesDialog("TextCol", column_type="text")
        dlg.find_edit.setText("#(tab)")
        dlg.replace_edit.setText("x")
        # special_chars_box unchecked
        self.assertFalse(dlg.special_chars_box.isChecked())
        step = dlg.step()
        self.assertEqual(step["value"], "#(tab)")
        self.assertEqual(step["replacement"], "x")
        dlg.deleteLater()

    def test_dialog_number_column_invalid_value_refused(self) -> None:
        dlg = ReplaceValuesDialog("Amount", column_type="whole_number")
        dlg.show()
        self.app.processEvents()
        dlg.find_edit.setText("5")
        dlg.replace_edit.setText("abc")
        dlg.ok_button.click()
        self.app.processEvents()
        self.assertTrue(dlg.error_label.isVisible())
        self.assertIn("Replace With", dlg.error_label.text())
        self.assertNotEqual(dlg.result(), ReplaceValuesDialog.DialogCode.Accepted)
        dlg.deleteLater()

    def test_dialog_gear_edit_replaces_step_in_editor(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Region", "Sales"],
            [{"Region": "East", "Sales": 100}],
            {},
            [],
        )
        initial_steps = [
            {"op": "replace_value", "column": "Region", "value": "East", "replacement": "North"}
        ]
        dialog = TransformDataDialog(source, initial_steps, query_name="TestQuery")
        dialog.step_list.setCurrentRow(0)

        # Gear-edit opens ReplaceValuesDialog
        dialog._edit_selected_step_settings()
        sub = dialog._operation_dialog
        self.assertIsInstance(sub, ReplaceValuesDialog)
        self.assertEqual(sub.find_edit.text(), "East")
        self.assertEqual(sub.replace_edit.text(), "North")

        sub.replace_edit.setText("Central")
        sub.ok_button.click()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(dialog._steps[0]["replacement"], "Central")
        self.assertEqual(
            dialog._preview_candidate.rows,
            apply_transformations(source, dialog._steps).rows,
        )
        dialog.deleteLater()

    def test_dialog_cancel_adds_nothing(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Region"],
            [{"Region": "East"}],
            {},
            [],
        )
        dialog = TransformDataDialog(source, [], query_name="TestQuery")
        dialog._open_replace_values_dialog(column="Region")
        sub = dialog._operation_dialog
        self.assertIsInstance(sub, ReplaceValuesDialog)
        sub.cancel_button.click()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 0)
        self.assertIsNone(dialog._operation_dialog)
        dialog.deleteLater()


class ReplaceValuesReviewTests(TestCase):
    """Review additions (Team-Thinker): typed matching, validation, ribbon and insert-after."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _run(rows, **step):
        source = ImportCandidate("inline", ["C"], [{"C": value} for value in rows], {}, [])
        full = {"op": "replace_value", "column": "C", **step}
        return [row["C"] for row in apply_transformations(source, [full]).rows]

    def test_value_replacer_is_kind_exact(self) -> None:
        from datetime import date, datetime
        from decimal import Decimal

        self.assertEqual(
            self._run([5, "5", Decimal("5"), True, None], value=5, replacement=7, replacer="value"),
            [7, "5", 7, True, None],
        )
        self.assertEqual(
            self._run([True, 1, "true"], value=True, replacement=False, replacer="value"),
            [False, 1, "true"],
        )
        self.assertEqual(
            self._run([None, "", 0], value=None, replacement="n/a", replacer="value"),
            ["n/a", "", 0],
        )
        self.assertEqual(
            self._run(
                [date(2026, 8, 1), datetime(2026, 8, 1), None],
                value="2026-08-01", replacement="2026-09-01", replacer="value",
            ),
            ["2026-09-01", datetime(2026, 8, 1), None],
        )

    def test_text_replacer_refuses_unsafe_steps(self) -> None:
        for step in (
            {"value": "", "replacement": "-", "replacer": "text"},
            {"value": "a", "replacement": None, "replacer": "text"},
            {"value": "a", "replacement": 5, "replacer": "text"},
            {"value": 5, "replacement": "x", "replacer": "text"},
            {"value": ["a"], "replacement": "x", "replacer": "value"},
            {"value": float("inf"), "replacement": "x", "replacer": "value"},
        ):
            with self.subTest(step=step), self.assertRaises(TransformationError):
                self._run(["abc"], **step)

    def test_text_replacer_leaves_null_alone(self) -> None:
        self.assertEqual(self._run(["abc", None], value="b", replacement="x", replacer="text"), ["axc", None])

    def test_dialog_whole_number_keeps_large_integers_and_text_null_replacement_refused(self) -> None:
        sub = ReplaceValuesDialog("N", column_type="whole_number")
        sub.find_edit.setText("9007199254740993")
        sub.replace_edit.setText("1")
        self.assertEqual(sub.step()["value"], 9007199254740993)
        sub.find_edit.setText("1.5")
        with self.assertRaises(TransformationError):
            sub.step()
        dec = ReplaceValuesDialog("D", column_type="decimal_number")
        dec.find_edit.setText("1e999")
        with self.assertRaises(TransformationError):
            dec.step()
        text = ReplaceValuesDialog("T", column_type="text")
        text.find_edit.setText("a")
        text.replace_edit.setText("null")
        with self.assertRaises(TransformationError):
            text.step()

    def test_ribbon_route_sets_operation_dialog_and_inserts_after_selected_step(self) -> None:
        source = ImportCandidate(
            "inline", ["Region", "Amount"],
            [{"Region": "East", "Amount": 5}, {"Region": "West", "Amount": 6}], {}, [],
        )
        steps = [
            {"op": "rename_column", "column": "Region", "new_name": "Area"},
            {"op": "filter_rows", "column": "Amount", "operator": "equals", "value": "5"},
        ]
        dialog = TransformDataDialog(source, steps, query_name="Q")
        dialog.step_list.setCurrentRow(0)

        def answer_insert() -> None:
            box = self.app.activeModalWidget()
            if not (isinstance(box, QDialog) and box.objectName() == "powerQueryInsertStepPrompt"):
                QTimer.singleShot(10, answer_insert)
                return
            next(b for b in box.findChildren(QPushButton) if b.text().replace("&", "") == "Insert").click()

        QTimer.singleShot(0, answer_insert)
        dialog.ribbon_command_buttons["replace_value"].click()
        sub = dialog._operation_dialog
        self.assertIsInstance(sub, ReplaceValuesDialog)
        self.assertEqual(dialog.operation_combo.currentData(), "replace_value")
        sub.find_edit.setText("East")
        sub.replace_edit.setText("North")
        sub.ok_button.click()
        self.app.processEvents()
        self.assertIsNone(dialog._operation_dialog)
        self.assertEqual([s["op"] for s in dialog._steps], ["rename_column", "replace_value", "filter_rows"])
        dialog.deleteLater()

    def test_selecting_typed_replace_step_fills_form_without_error(self) -> None:
        import sys

        source = ImportCandidate("inline", ["Amount"], [{"Amount": 5}], {}, [])
        steps = [
            {"op": "replace_value", "column": "Amount", "value": 5, "replacement": None, "replacer": "value"},
            {"op": "replace_value", "column": "Amount", "value": None, "replacement": 7, "replacer": "value"},
        ]
        dialog = TransformDataDialog(source, steps, query_name="Q")
        errors = []
        previous = sys.excepthook
        sys.excepthook = lambda *args: errors.append(args)
        try:
            for row, expected in ((0, ("5", "null")), (1, ("null", "7"))):
                dialog.step_list.setCurrentRow(row)
                self.app.processEvents()
                self.assertEqual((dialog.value_edit.text(), dialog.replacement_edit.text()), expected)
        finally:
            sys.excepthook = previous
        self.assertEqual(errors, [])
        dialog.deleteLater()
