"""Tests for Task 199: Unpivot commands like Power BI."""

import unittest
from PySide6.QtCore import QItemSelection, QItemSelectionModel, Qt
from PySide6.QtWidgets import QApplication

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import TransformDataDialog
from analytics_studio.power_query_m import steps_to_m_script
from analytics_studio.transformations import apply_transformations


def _cand(headers: list[str], rows: list[dict[str, str]]) -> ImportCandidate:
    return ImportCandidate("inline", headers, rows, {}, [])


def _sample_source() -> ImportCandidate:
    # Source table headers Region, Q1, Q2, Q3 with 2 rows
    return _cand(
        ["Region", "Q1", "Q2", "Q3"],
        [
            {"Region": "North", "Q1": "10", "Q2": "20", "Q3": "30"},
            {"Region": "South", "Q1": "15", "Q2": "25", "Q3": "35"},
        ],
    )


class UnpivotCommandsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["unpivot commands tests"])

    def _select_columns(self, dialog: TransformDataDialog, column_names: list[str]) -> None:
        headers = dialog._selected_preview_candidate().headers
        model = dialog.preview.model()
        selection_model = dialog.preview.selectionModel()
        selection_model.clearSelection()
        for i, name in enumerate(column_names):
            if name in headers:
                col_idx = headers.index(name)
                if i == 0:
                    dialog.preview.selectColumn(col_idx)
                else:
                    selection_model.select(
                        QItemSelection(
                            model.index(0, col_idx),
                            model.index(model.rowCount() - 1, col_idx),
                        ),
                        QItemSelectionModel.SelectionFlag.Select,
                    )

    def test_ribbon_dropdown_has_three_actions_in_order_and_no_separate_unpivot_other_button(self) -> None:
        source = _sample_source()
        dialog = TransformDataDialog(source, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        self.assertNotIn("unpivot_other_columns", dialog.ribbon_command_buttons)
        button = dialog.ribbon_command_buttons.get("unpivot_columns")
        self.assertIsNotNone(button)
        menu = button.menu()
        self.assertIsNotNone(menu)
        actions = menu.actions()
        self.assertEqual(len(actions), 3)

        self.assertEqual(actions[0].text(), "Unpivot Columns")
        self.assertEqual(actions[0].objectName(), "unpivotColumnsAction")
        self.assertTrue(actions[0].isEnabled())

        self.assertEqual(actions[1].text(), "Unpivot Other Columns")
        self.assertEqual(actions[1].objectName(), "unpivotOtherColumnsAction")
        self.assertTrue(actions[1].isEnabled())

        self.assertEqual(actions[2].text(), "Unpivot Only Selected Columns")
        self.assertEqual(actions[2].objectName(), "unpivotOnlySelectedColumnsAction")
        self.assertTrue(actions[2].isEnabled())

    def test_unpivot_columns_with_q1_and_q2_selected(self) -> None:
        source = _sample_source()
        dialog = TransformDataDialog(source, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        # Select Q1 + Q2
        self._select_columns(dialog, ["Q1", "Q2"])
        self.assertEqual(dialog._selected_preview_columns(), ["Q1", "Q2"])

        button = dialog.ribbon_command_buttons["unpivot_columns"]
        action = next(a for a in button.menu().actions() if a.objectName() == "unpivotColumnsAction")
        action.trigger()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(
            dialog._steps[-1],
            {
                "op": "unpivot_other_columns",
                "columns": ["Region", "Q3"],
                "attribute_name": "Attribute",
                "value_name": "Value",
            },
        )
        self.assertEqual(dialog.step_list.item(0).text(), "Unpivoted Columns")

        preview = dialog._preview_candidate
        self.assertEqual(preview.headers, ["Region", "Q3", "Attribute", "Value"])
        expected = apply_transformations(source, dialog._steps)
        self.assertEqual(preview.headers, expected.headers)
        self.assertEqual(preview.rows, expected.rows)

    def test_unpivot_other_columns_with_region_selected(self) -> None:
        source = _sample_source()
        dialog = TransformDataDialog(source, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        self._select_columns(dialog, ["Region"])
        self.assertEqual(dialog._selected_preview_columns(), ["Region"])

        button = dialog.ribbon_command_buttons["unpivot_columns"]
        action = next(a for a in button.menu().actions() if a.objectName() == "unpivotOtherColumnsAction")
        action.trigger()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(
            dialog._steps[-1],
            {
                "op": "unpivot_other_columns",
                "columns": ["Region"],
                "attribute_name": "Attribute",
                "value_name": "Value",
            },
        )
        self.assertEqual(dialog.step_list.item(0).text(), "Unpivoted Other Columns")

    def test_unpivot_only_selected_columns_and_m_script(self) -> None:
        source = _sample_source()
        dialog = TransformDataDialog(source, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        self._select_columns(dialog, ["Q1", "Q2"])
        self.assertEqual(dialog._selected_preview_columns(), ["Q1", "Q2"])

        button = dialog.ribbon_command_buttons["unpivot_columns"]
        action = next(a for a in button.menu().actions() if a.objectName() == "unpivotOnlySelectedColumnsAction")
        action.trigger()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(
            dialog._steps[-1],
            {
                "op": "unpivot_columns",
                "columns": ["Q1", "Q2"],
                "attribute_name": "Attribute",
                "value_name": "Value",
            },
        )
        self.assertEqual(dialog.step_list.item(0).text(), "Unpivoted Only Selected Columns")

        m_script = steps_to_m_script(dialog._steps, "TestQuery")
        self.assertIn("Table.Unpivot(", m_script)

    def test_unpivot_columns_twice_gives_sequential_names(self) -> None:
        source = _sample_source()
        dialog = TransformDataDialog(source, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        # Step 1: unpivot columns Q1 + Q2
        self._select_columns(dialog, ["Q1", "Q2"])
        button = dialog.ribbon_command_buttons["unpivot_columns"]
        action = next(a for a in button.menu().actions() if a.objectName() == "unpivotColumnsAction")
        action.trigger()
        self.app.processEvents()
        self.assertEqual(dialog.step_list.item(0).text(), "Unpivoted Columns")

        # Step 2: unpivot another column (rename existing output columns first to avoid collision)
        dialog._add_step({"op": "rename_column", "column": "Attribute", "new_name": "Attr1"}, power_bi_name=True)
        dialog._add_step({"op": "rename_column", "column": "Value", "new_name": "Val1"}, power_bi_name=True)

        self._select_columns(dialog, ["Region"])
        action.trigger()
        self.app.processEvents()

        step_names = [dialog.step_list.item(i).text() for i in range(len(dialog._steps))]
        self.assertIn("Unpivoted Columns", step_names)
        self.assertIn("Unpivoted Columns1", step_names)

    def test_selecting_columns_in_reverse_order_preserves_table_order(self) -> None:
        source = _sample_source()
        dialog = TransformDataDialog(source, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        # Select Q2 then Q1
        self._select_columns(dialog, ["Q2", "Q1"])
        button = dialog.ribbon_command_buttons["unpivot_columns"]
        action = next(a for a in button.menu().actions() if a.objectName() == "unpivotOnlySelectedColumnsAction")
        action.trigger()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(dialog._steps[0]["columns"], ["Q1", "Q2"])

    def test_no_selection_shows_error_and_adds_no_step(self) -> None:
        source = _sample_source()
        dialog = TransformDataDialog(source, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        # Clear any selection and current index
        dialog.preview.selectionModel().clearSelection()
        dialog.preview.setCurrentIndex(dialog.preview.model().index(-1, -1))

        button = dialog.ribbon_command_buttons["unpivot_columns"]
        action = next(a for a in button.menu().actions() if a.objectName() == "unpivotColumnsAction")
        action.trigger()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 0)
        self.assertTrue(dialog.error_label.isVisible())
        self.assertEqual(dialog.error_label.text(), "Select one or more columns in the preview first.")

    def test_all_columns_selected_shows_engine_error_and_adds_no_step(self) -> None:
        source = _sample_source()
        dialog = TransformDataDialog(source, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        # Select every column
        self._select_columns(dialog, ["Region", "Q1", "Q2", "Q3"])
        button = dialog.ribbon_command_buttons["unpivot_columns"]
        action = next(a for a in button.menu().actions() if a.objectName() == "unpivotColumnsAction")
        action.trigger()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 0)
        self.assertTrue(dialog.error_label.isVisible())
        self.assertEqual(dialog.error_label.text(), "Transformation step 1 needs one or more columns.")

    def test_right_click_menu_unpivot_only_selected_columns_enabled_and_adds_step(self) -> None:
        source = _sample_source()
        dialog = TransformDataDialog(source, query_name="TestQuery")
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        self.app.processEvents()

        # Select Q1 and Q2 in the preview
        self._select_columns(dialog, ["Q1", "Q2"])

        menu = dialog._build_header_context_menu(1)  # Q1 header
        unpivot_selected_action = next(
            a for a in menu.actions() if a.text() == "Unpivot Only Selected Columns"
        )
        self.assertTrue(unpivot_selected_action.isEnabled())

        unpivot_selected_action.trigger()
        self.app.processEvents()

        self.assertEqual(len(dialog._steps), 1)
        self.assertEqual(
            dialog._steps[-1],
            {
                "op": "unpivot_columns",
                "columns": ["Q1", "Q2"],
                "attribute_name": "Attribute",
                "value_name": "Value",
            },
        )
        self.assertEqual(dialog.step_list.item(0).text(), "Unpivoted Only Selected Columns")
