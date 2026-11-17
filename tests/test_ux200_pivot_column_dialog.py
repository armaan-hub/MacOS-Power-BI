"""Tests for Task 200: Pivot Column dialog like Power BI."""

from unittest import TestCase
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QLabel,
    QPushButton,
    QToolButton,
)

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import (
    PivotColumnDialog,
    TransformDataDialog,
)
from analytics_studio.power_query_m import steps_to_m_script
from analytics_studio.power_query_values import PowerQueryCellError
from analytics_studio.transformations import apply_transformations


def _sample_source() -> ImportCandidate:
    headers = ["Country", "Date", "Value"]
    rows = [
        {"Country": "USA", "Date": "2020-01-01", "Value": "10"},
        {"Country": "USA", "Date": "2020-01-01", "Value": "20"},
        {"Country": "USA", "Date": "2020-01-02", "Value": "30"},
        {"Country": "CAN", "Date": "2020-01-01", "Value": "40"},
    ]
    return ImportCandidate(
        "inline",
        headers,
        rows,
        {},
        ["text", "text", "text"],
    )


class PivotColumnDialogTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _select_column(self, dialog: TransformDataDialog, col_name: str) -> None:
        headers = dialog._selected_preview_candidate().headers
        col_idx = headers.index(col_name)
        dialog.preview.selectColumn(col_idx)
        dialog.preview.setCurrentIndex(dialog.preview.model().index(0, col_idx))

    def test_ribbon_pivot_column_opens_dialog_with_expected_defaults(self) -> None:
        source = _sample_source()
        dialog = TransformDataDialog(source, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        self._select_column(dialog, "Date")

        dialog.ribbon_command_buttons["pivot_column"].click()
        self.app.processEvents()

        sub = dialog._operation_dialog
        self.assertIsInstance(sub, PivotColumnDialog)
        self.assertEqual(sub.objectName(), "powerQueryPivotColumnDialog")
        self.assertEqual(sub.windowTitle(), "Pivot Column")
        self.assertEqual(sub.windowModality(), Qt.WindowModality.ApplicationModal)

        # description_label
        self.assertIn('column "Date"', sub.description_label.text())

        # values combo
        self.assertEqual(
            [sub.values_combo.itemText(i) for i in range(sub.values_combo.count())],
            ["Country", "Value"],
        )

        # aggregation combo item texts and order
        expected_choices = [
            ("Don't aggregate", "none"),
            ("Count (All)", "count_all"),
            ("Count (Not Blank)", "count_non_blank"),
            ("Minimum", "min"),
            ("Maximum", "max"),
            ("Median", "median"),
            ("Sum", "sum"),
            ("Average", "average"),
        ]
        self.assertEqual(
            [
                (sub.aggregation_combo.itemText(i), sub.aggregation_combo.itemData(i))
                for i in range(sub.aggregation_combo.count())
            ],
            expected_choices,
        )

        # default aggregation is "sum", advanced collapsed
        self.assertEqual(sub.aggregation_combo.currentData(), "sum")
        self.assertFalse(sub.advanced_toggle.isChecked())
        self.assertFalse(sub.advanced_panel.isVisible())

        sub.reject()

    def test_ok_with_value_and_sum_adds_step_and_generates_m(self) -> None:
        source = _sample_source()
        dialog = TransformDataDialog(source, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        self._select_column(dialog, "Date")
        dialog.ribbon_command_buttons["pivot_column"].click()
        self.app.processEvents()

        sub = dialog._operation_dialog
        self.assertIsInstance(sub, PivotColumnDialog)
        sub.values_combo.setCurrentText("Value")
        idx = sub.aggregation_combo.findData("sum")
        sub.aggregation_combo.setCurrentIndex(idx)

        sub.ok_button.click()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        expected_step = {
            "op": "pivot_column",
            "attribute_column": "Date",
            "value_column": "Value",
            "aggregation": "sum",
        }
        self.assertEqual(dialog._steps[-1], expected_step)

        # preview equals apply_transformations
        expected_preview = apply_transformations(source, dialog._steps)
        self.assertEqual(dialog._preview_candidate.headers, expected_preview.headers)
        self.assertEqual(dialog._preview_candidate.rows, expected_preview.rows)

        # generated M contains Table.Pivot( and List.Sum
        m_script = steps_to_m_script(dialog._steps, "TestQuery")
        self.assertIn("Table.Pivot(", m_script)
        self.assertIn("List.Sum", m_script)

    def test_dont_aggregate_on_duplicate_pairs_keeps_error_cells_and_adds_step(self) -> None:
        # Task 215b: Power BI keeps a repeated row-key/category pair as an error cell and the
        # step succeeds; this test used to assert the old refusal ("multiple values").
        source = _sample_source()
        dialog = TransformDataDialog(source, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        self._select_column(dialog, "Date")
        dialog.ribbon_command_buttons["pivot_column"].click()
        self.app.processEvents()

        sub = dialog._operation_dialog
        self.assertIsInstance(sub, PivotColumnDialog)
        sub.values_combo.setCurrentText("Value")
        idx = sub.aggregation_combo.findData("none")
        sub.aggregation_combo.setCurrentIndex(idx)

        sub.ok_button.click()
        self.app.processEvents()

        # Task 215b: the step is added and the repeated pair is an error cell in the preview.
        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(dialog._steps[-1]["aggregation"], "none")
        self.assertTrue(any(
            isinstance(value, PowerQueryCellError)
            for row in dialog._preview_candidate.rows
            for value in row.values()
        ))

    def test_dont_aggregate_on_distinct_pairs_adds_step(self) -> None:
        # Without duplicate pairs for the row key, aggregation="none" succeeds and adds the step
        source = ImportCandidate(
            "inline",
            ["Country", "Date", "Value"],
            [
                {"Country": "USA", "Date": "2020-01-01", "Value": "10"},
                {"Country": "USA", "Date": "2020-01-02", "Value": "20"},
                {"Country": "CAN", "Date": "2020-01-01", "Value": "30"},
            ],
            {},
            ["text", "text", "text"],
        )
        dialog = TransformDataDialog(source, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        self._select_column(dialog, "Date")
        dialog.ribbon_command_buttons["pivot_column"].click()
        self.app.processEvents()

        sub = dialog._operation_dialog
        self.assertIsInstance(sub, PivotColumnDialog)
        sub.values_combo.setCurrentText("Value")
        idx = sub.aggregation_combo.findData("none")
        sub.aggregation_combo.setCurrentIndex(idx)

        sub.ok_button.click()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(
            dialog._steps[-1],
            {
                "op": "pivot_column",
                "attribute_column": "Date",
                "value_column": "Value",
                "aggregation": "none",
            },
        )
        expected_preview = apply_transformations(source, dialog._steps)
        self.assertEqual(dialog._preview_candidate.headers, expected_preview.headers)
        self.assertEqual(dialog._preview_candidate.rows, expected_preview.rows)

    def test_no_selection_opens_dialog_for_first_column_and_cancel_adds_nothing(self) -> None:
        source = _sample_source()
        dialog = TransformDataDialog(source, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        # Clear selection
        dialog.preview.selectionModel().clearSelection()
        dialog.preview.setCurrentIndex(dialog.preview.model().index(-1, -1))
        self.assertEqual(dialog._selected_preview_columns(), [])

        dialog.ribbon_command_buttons["pivot_column"].click()
        self.app.processEvents()

        sub = dialog._operation_dialog
        self.assertIsInstance(sub, PivotColumnDialog)
        # Opens for first column ("Country")
        self.assertIn('column "Country"', sub.description_label.text())
        self.assertEqual(
            [sub.values_combo.itemText(i) for i in range(sub.values_combo.count())],
            ["Date", "Value"],
        )

        # Cancel adds nothing
        sub.cancel_button.click()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 0)
        self.assertIsNone(dialog._operation_dialog)

    def test_gear_edit_existing_pivot_step_prefills_and_updates(self) -> None:
        source = _sample_source()
        initial_steps = [
            {
                "op": "pivot_column",
                "attribute_column": "Date",
                "value_column": "Value",
                "aggregation": "max",
            }
        ]
        dialog = TransformDataDialog(source, initial_steps, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        dialog.step_list.setCurrentRow(0)
        dialog._edit_selected_step_settings()
        self.app.processEvents()

        sub = dialog._operation_dialog
        self.assertIsInstance(sub, PivotColumnDialog)
        self.assertEqual(sub.values_combo.currentText(), "Value")
        self.assertEqual(sub.aggregation_combo.currentData(), "max")
        # Advanced expanded because aggregation != "sum"
        self.assertTrue(sub.advanced_toggle.isChecked())
        self.assertTrue(sub.advanced_panel.isVisible())

        # Change to "min" and OK
        min_idx = sub.aggregation_combo.findData("min")
        sub.aggregation_combo.setCurrentIndex(min_idx)
        sub.ok_button.click()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(dialog._steps[0]["aggregation"], "min")
        self.assertEqual(dialog._steps[0]["attribute_column"], "Date")
        self.assertEqual(dialog._steps[0]["value_column"], "Value")
