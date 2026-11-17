"""Tests for Task 197: Power BI Split Column by Delimiter dialog."""

from unittest import TestCase
import unittest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QLineEdit,
    QRadioButton,
    QSpinBox,
    QToolButton,
)

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import (
    SplitColumnByDelimiterDialog,
    TransformDataDialog,
)
from analytics_studio.power_query_m import (
    parse_m_script,
    steps_to_m_script,
)
from analytics_studio.transformations import (
    apply_transformations,
)


def _cand(headers: list[str], rows: list[dict[str, str]]) -> ImportCandidate:
    return ImportCandidate("inline", headers, rows, {}, [])


def _sample_source() -> ImportCandidate:
    return _cand(
        ["Id", "Text", "Count"],
        [
            {"Id": "1", "Text": "apple,banana,cherry", "Count": "10"},
            {"Id": "2", "Text": "dog,elephant,fox", "Count": "20"},
            {"Id": "3", "Text": "no_delimiter_here", "Count": "30"},
        ],
    )


class SplitColumnByDelimiterDialogTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["split by delimiter tests"])

    def test_default_delimiter_detection(self) -> None:
        source_comma = _cand(["Col"], [{"Col": "a,b"}])
        dlg1 = SplitColumnByDelimiterDialog("Col", candidate=source_comma)
        dlg1.show()
        self.app.processEvents()
        self.assertEqual(dlg1.delimiter(), ",")
        self.assertEqual(dlg1.splitDelimiterCombo.currentText(), "Comma")
        self.assertFalse(dlg1.splitCustomDelimiterEdit.isVisible())
        dlg1.deleteLater()

        source_space = _cand(["Col"], [{"Col": "a b"}])
        dlg2 = SplitColumnByDelimiterDialog("Col", candidate=source_space)
        dlg2.show()
        self.app.processEvents()
        self.assertEqual(dlg2.delimiter(), " ")
        self.assertEqual(dlg2.splitDelimiterCombo.currentText(), "Space")
        self.assertFalse(dlg2.splitCustomDelimiterEdit.isVisible())
        dlg2.deleteLater()

        source_colon = _cand(["Col"], [{"Col": "a:b"}])
        dlg3 = SplitColumnByDelimiterDialog("Col", candidate=source_colon)
        dlg3.show()
        self.app.processEvents()
        self.assertEqual(dlg3.delimiter(), ":")
        self.assertEqual(dlg3.splitDelimiterCombo.currentText(), "Colon")
        dlg3.deleteLater()

        source_none = _cand(["Col"], [{"Col": "abc"}])
        dlg4 = SplitColumnByDelimiterDialog("Col", candidate=source_none)
        dlg4.show()
        self.app.processEvents()
        self.assertEqual(dlg4.splitDelimiterCombo.currentText(), "--Custom--")
        self.assertTrue(dlg4.splitCustomDelimiterEdit.isVisible())
        self.assertEqual(dlg4.delimiter(), "")
        self.assertFalse(dlg4.ok_button.isEnabled())
        dlg4.deleteLater()

    def test_custom_delimiter_enables_and_disables_ok(self) -> None:
        source = _cand(["Col"], [{"Col": "a-b"}])
        dlg = SplitColumnByDelimiterDialog("Col", candidate=source)
        # Defaults to custom because '-' is not standard
        self.assertEqual(dlg.splitDelimiterCombo.currentText(), "--Custom--")
        self.assertFalse(dlg.ok_button.isEnabled())

        dlg.splitCustomDelimiterEdit.setText("-")
        self.assertTrue(dlg.ok_button.isEnabled())
        self.assertEqual(dlg.delimiter(), "-")

        dlg.splitCustomDelimiterEdit.setText("")
        self.assertFalse(dlg.ok_button.isEnabled())

    def test_engine_leftmost_split(self) -> None:
        source = _cand(["Text"], [{"Text": "a,b,c"}])
        res = apply_transformations(
            source, [{"op": "split_column", "column": "Text", "delimiter": ","}]
        )
        self.assertEqual(res.headers, ["Text.1", "Text.2"])
        self.assertEqual(res.rows[0], {"Text.1": "a", "Text.2": "b,c"})

    def test_engine_rightmost_split(self) -> None:
        source = _cand(["Text"], [{"Text": "a,b,c"}])
        res = apply_transformations(
            source,
            [{"op": "split_column", "column": "Text", "delimiter": ",", "from_end": True}],
        )
        self.assertEqual(res.headers, ["Text.1", "Text.2"])
        self.assertEqual(res.rows[0], {"Text.1": "a,b", "Text.2": "c"})

    def test_engine_rightmost_split_no_delimiter_found(self) -> None:
        source = _cand(["Text"], [{"Text": "abc"}])
        res = apply_transformations(
            source,
            [{"op": "split_column", "column": "Text", "delimiter": ",", "from_end": True}],
        )
        self.assertEqual(res.headers, ["Text.1", "Text.2"])
        self.assertEqual(res.rows[0], {"Text.1": "abc", "Text.2": ""})

    def test_split_at_radios_and_rows_columns(self) -> None:
        source = _sample_source()
        dlg = SplitColumnByDelimiterDialog("Text", candidate=source)

        # Default is left-most -> Columns
        self.assertTrue(dlg.splitAtLeftRadio.isChecked())
        self.assertFalse(dlg.splitIntoRowsRadio.isEnabled())
        step = dlg.step()
        self.assertEqual(step["op"], "split_column")
        self.assertNotIn("from_end", step)

        # Right-most -> Columns
        dlg.splitAtRightRadio.setChecked(True)
        self.assertFalse(dlg.splitIntoRowsRadio.isEnabled())
        step = dlg.step()
        self.assertEqual(step["op"], "split_column")
        self.assertTrue(step.get("from_end"))

        # Each occurrence -> Columns
        dlg.splitAtEachRadio.setChecked(True)
        self.assertTrue(dlg.splitIntoRowsRadio.isEnabled())
        dlg.splitIntoColumnsRadio.setChecked(True)
        step = dlg.step()
        self.assertEqual(step["op"], "split_column_by_each_delimiter")

        # Each occurrence -> Rows
        dlg.splitIntoRowsRadio.setChecked(True)
        step = dlg.step()
        self.assertEqual(step["op"], "split_column_to_rows")

        # Switch back to Left-most -> Rows must be disabled and revert to Columns
        dlg.splitAtLeftRadio.setChecked(True)
        self.assertFalse(dlg.splitIntoRowsRadio.isEnabled())
        self.assertTrue(dlg.splitIntoColumnsRadio.isChecked())

    def test_advanced_panel_controls(self) -> None:
        source = _sample_source()
        dlg = SplitColumnByDelimiterDialog("Text", candidate=source)
        dlg.show()
        self.app.processEvents()
        self.assertFalse(dlg._advanced_panel.isVisible())
        dlg.splitAdvancedToggle.click()
        self.app.processEvents()
        self.assertTrue(dlg._advanced_panel.isVisible())

        # Column count spin is disabled with tooltip
        self.assertFalse(dlg.splitColumnCountSpin.isEnabled())
        self.assertEqual(
            dlg.splitColumnCountSpin.toolTip(),
            "Not supported yet; the column count comes from the data",
        )

        # Quote combo has None selected and tooltip
        self.assertEqual(dlg.splitQuoteCombo.currentText(), "None")
        self.assertEqual(dlg.splitQuoteCombo.toolTip(), "Quote character not supported yet")
        dlg.deleteLater()

    def test_m_generation_and_roundtrip_rightmost(self) -> None:
        steps = [
            {"op": "split_column", "column": "Text", "delimiter": ",", "from_end": True}
        ]
        script = steps_to_m_script(steps, "Source")
        self.assertIn(
            'Splitter.SplitTextByEachDelimiter({","}, QuoteStyle.None, true)', script
        )
        parsed = parse_m_script(script, "Source")
        self.assertEqual(parsed, steps)

    def test_m_generation_and_roundtrip_leftmost(self) -> None:
        steps = [{"op": "split_column", "column": "Text", "delimiter": ","}]
        script = steps_to_m_script(steps, "Source")
        self.assertIn(
            'Splitter.SplitTextByEachDelimiter({","}, QuoteStyle.None)', script
        )
        self.assertNotIn(", true", script)
        parsed = parse_m_script(script, "Source")
        self.assertEqual(parsed, steps)

    def test_ribbon_split_column_dropdown_and_dialog_open(self) -> None:
        source = _sample_source()
        dialog = TransformDataDialog(source, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        button = dialog.ribbon_command_buttons.get("split_column")
        self.assertIsNotNone(button)
        menu = button.menu()
        self.assertIsNotNone(menu)
        actions = menu.actions()
        self.assertEqual(len(actions), 7)

        # 2 enabled, 5 disabled
        self.assertEqual(actions[0].text(), "By Delimiter...")
        self.assertTrue(actions[0].isEnabled())
        self.assertEqual(actions[1].text(), "By Positions...")
        self.assertTrue(actions[1].isEnabled())

        expected_disabled = [
            "By Number of Characters...",
            "By Lowercase to Uppercase",
            "By Uppercase to Lowercase",
            "By Digit to Non-Digit",
            "By Non-Digit to Digit",
        ]
        for idx, text in enumerate(expected_disabled, start=2):
            self.assertEqual(actions[idx].text(), text)
            self.assertFalse(actions[idx].isEnabled())
            self.assertEqual(actions[idx].toolTip(), "Not supported yet")

        # Select column 1 ("Text")
        dialog.preview.selectColumn(1)
        dialog.preview.setCurrentIndex(dialog.preview.model().index(0, 1))
        self.app.processEvents()

        # Click the ribbon button opens dialog
        button.click()
        self.app.processEvents()
        sub = dialog._operation_dialog
        self.assertIsInstance(sub, SplitColumnByDelimiterDialog)
        self.assertEqual(dialog.operation_combo.currentData(), "split_column")
        self.assertEqual(sub._column, "Text")
        self.assertEqual(sub.delimiter(), ",")
        sub.reject()
        self.app.processEvents()
        self.assertIsNone(dialog._operation_dialog)
        self.assertEqual(dialog.step_list.count(), 0)

    def test_gear_edit_prefills_and_replaces_step(self) -> None:
        source = _sample_source()
        initial_steps = [
            {"op": "split_column", "column": "Text", "delimiter": " "}
        ]
        dialog = TransformDataDialog(source, initial_steps, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        dialog.step_list.setCurrentRow(0)
        self.app.processEvents()

        # Trigger gear-edit
        dialog._edit_selected_step_settings()
        self.app.processEvents()
        sub = dialog._operation_dialog
        self.assertIsInstance(sub, SplitColumnByDelimiterDialog)
        self.assertEqual(sub.delimiter(), " ")

        # Change delimiter to custom "a"
        custom_idx = sub.splitDelimiterCombo.findData("--custom--")
        sub.splitDelimiterCombo.setCurrentIndex(custom_idx)
        sub.splitCustomDelimiterEdit.setText("a")
        sub.accept()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(dialog._steps[0]["delimiter"], "a")
        expected_candidate = apply_transformations(source, dialog._steps)
        self.assertEqual(dialog._preview_candidate.rows, expected_candidate.rows)

    def test_gear_edit_cancel_leaves_steps_unchanged(self) -> None:
        source = _sample_source()
        initial_steps = [
            {"op": "split_column", "column": "Text", "delimiter": ","}
        ]
        dialog = TransformDataDialog(source, initial_steps, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        dialog.step_list.setCurrentRow(0)
        self.app.processEvents()

        dialog._edit_selected_step_settings()
        self.app.processEvents()
        sub = dialog._operation_dialog
        self.assertIsInstance(sub, SplitColumnByDelimiterDialog)
        sub.splitAtRightRadio.setChecked(True)
        sub.reject()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(dialog._steps[0]["delimiter"], ",")
        self.assertNotIn("from_end", dialog._steps[0])


if __name__ == "__main__":
    unittest.main()
