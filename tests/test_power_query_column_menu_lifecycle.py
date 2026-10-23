"""The Power Query column-header dropdown follows Power BI's menu layout.

Power BI shows, top to bottom: Sort Ascending, Sort Descending, Clear Sort,
Clear Filter, Remove Empty, a type-specific "Text/Number/Date Filters" submenu,
a search box, a checkbox list of the column's distinct values and OK / Cancel.
Everything is driven headlessly (QT_QPA_PLATFORM=offscreen) against the real
dialog, the real filter engine and the real M round trip.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMenu

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import TransformDataDialog
from analytics_studio.power_query_m import (
    m_script_matches_steps,
    parse_m_script,
    steps_to_m_script,
)

NOT_SUPPORTED = "Not supported yet"


def _source() -> ImportCandidate:
    return ImportCandidate(
        "inline",
        ["Region", "Amount", "Day"],
        [
            {"Region": "East", "Amount": "10", "Day": "2026-01-01"},
            {"Region": "West", "Amount": "20", "Day": "2026-01-02"},
            {"Region": "East", "Amount": "30", "Day": "2026-01-03"},
            {"Region": "", "Amount": "40", "Day": "2026-01-04"},
            {"Region": None, "Amount": "50", "Day": "2026-01-05"},
        ],
        {},
        [],
    )


TYPED = [
    {"op": "convert_type", "column": "Amount", "type": "whole_number"},
    {"op": "convert_type", "column": "Day", "type": "date"},
]


def _texts(menu: QMenu) -> list[str]:
    return [action.text() for action in menu.actions() if not action.isSeparator()
            and action.text()]


class ColumnMenuTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["column menu tests"])

    def make(self, steps=None) -> TransformDataDialog:
        dialog = TransformDataDialog(_source(), steps=steps, query_name="Sales")
        self.addCleanup(dialog.deleteLater)
        return dialog

    # ----- layout -------------------------------------------------------

    def test_text_column_menu_has_power_bi_layout(self) -> None:
        info = self.make()._build_preview_column_menu(0)
        self.assertEqual(
            _texts(info.menu),
            ["Sort Ascending", "Sort Descending", "Clear Sort", "Clear Filter",
             "Remove Empty", "Text Filters"],
        )
        self.assertEqual(
            _texts(info.action("Text Filters").menu()),
            ["Equals…", "Does Not Equal…", "Begins With…", "Does Not Begin With…",
             "Ends With…", "Does Not End With…", "Contains…", "Does Not Contain…"],
        )
        for text in _texts(info.action("Text Filters").menu()):
            self.assertTrue(info.action(f"Text Filters/{text}").isEnabled(), text)
        # The widget below the submenu: search box, value list, OK / Cancel.
        self.assertIn(info.widget_action, info.menu.actions())
        self.assertIs(info.widget_action.defaultWidget(), info.panel)
        self.assertEqual(info.panel.search_edit.placeholderText(), "Search")
        self.assertEqual(info.panel.ok_button.text(), "OK")
        self.assertEqual(info.panel.cancel_button.text(), "Cancel")

    def test_number_column_menu_offers_number_filters(self) -> None:
        info = self.make(TYPED)._build_preview_column_menu(1)
        self.assertEqual(_texts(info.menu)[5], "Number Filters")
        submenu = info.action("Number Filters").menu()
        self.assertEqual(
            _texts(submenu),
            ["Equals…", "Does Not Equal…", "Greater Than…",
             "Greater Than Or Equal To…", "Less Than…", "Less Than Or Equal To…",
             "Between…"],
        )
        for text in _texts(submenu):
            self.assertTrue(info.action(f"Number Filters/{text}").isEnabled(), text)

    def test_date_column_menu_enables_only_supported_items_and_never_fakes_the_rest(self) -> None:
        info = self.make(TYPED)._build_preview_column_menu(2)
        self.assertEqual(_texts(info.menu)[5], "Date Filters")
        submenu = info.action("Date Filters").menu()
        self.assertEqual(
            _texts(submenu),
            ["Equals…", "Before…", "After…", "Between…", "In the Next…",
             "In the Previous…", "Is Earliest", "Is Latest", "Year", "Quarter",
             "Month", "Week", "Day"],
        )
        self.assertTrue(info.action("Date Filters/Equals…").isEnabled())
        for text in _texts(submenu)[1:]:
            action = info.action(f"Date Filters/{text}")
            self.assertFalse(action.isEnabled(), text)
            self.assertEqual(action.toolTip(), NOT_SUPPORTED, text)
        self.assertTrue(info.menu.toolTipsVisible())

    def test_value_list_has_select_all_blank_values_and_search(self) -> None:
        panel = self.make()._build_preview_column_menu(0).panel
        labels = [panel.value_list.item(i).text() for i in range(panel.value_list.count())]
        self.assertEqual(labels, ["(Select All)", "(Blank)", "East", "West"])
        for index in range(panel.value_list.count()):
            self.assertEqual(
                panel.value_list.item(index).checkState(), Qt.CheckState.Checked
            )
        self.assertTrue(panel.truncated_note.isHidden())
        self.assertTrue(panel.ok_button.isEnabled())
        panel.search_edit.setText("we")
        visible = [panel.value_list.item(i).text()
                   for i in range(panel.value_list.count())
                   if not panel.value_list.item(i).isHidden()]
        self.assertEqual(visible, ["(Select All)", "West"])

    def test_long_value_list_is_truncated_with_a_note(self) -> None:
        rows = [{"Region": f"R{index:05d}", "Amount": "1", "Day": "2026-01-01"}
                for index in range(1_200)]
        dialog = TransformDataDialog(
            ImportCandidate("inline", ["Region", "Amount", "Day"], rows, {}, []),
            query_name="Big",
        )
        self.addCleanup(dialog.deleteLater)
        panel = dialog._build_preview_column_menu(0).panel
        self.assertEqual(panel.value_list.count(), 1 + 1_000)
        self.assertFalse(panel.truncated_note.isHidden())
        self.assertEqual(panel.truncated_note.text(), "List may be incomplete")

    # ----- sort ---------------------------------------------------------

    def test_sort_then_clear_sort_removes_the_sort_step(self) -> None:
        dialog = self.make()
        info = dialog._build_preview_column_menu(0)
        self.assertFalse(info.action("Clear Sort").isEnabled())
        info.trigger("Sort Descending")
        self.assertEqual(dialog._steps[-1],
                         {"op": "sort_rows", "column": "Region", "direction": "desc"})
        self.assertEqual(dialog._preview_candidate.rows[0]["Region"], "West")

        info = dialog._build_preview_column_menu(0)
        self.assertTrue(info.action("Clear Sort").isEnabled())
        # A sort on another column does not enable Clear Sort here.
        self.assertFalse(dialog._build_preview_column_menu(1).action("Clear Sort").isEnabled())
        info.trigger("Clear Sort")
        self.assertEqual(dialog._steps, [])
        self.assertEqual(len(dialog._step_metadata), 0)
        self.assertEqual(dialog._preview_candidate.rows[0]["Region"], "East")
        self.assertFalse(dialog._build_preview_column_menu(0).action("Clear Sort").isEnabled())

    def test_clear_sort_drops_only_this_column_from_a_multi_column_sort(self) -> None:
        dialog = self.make([{
            "op": "sort_rows_by_columns",
            "sorts": [{"column": "Region", "direction": "asc"},
                      {"column": "Amount", "direction": "desc"}],
        }])
        dialog._build_preview_column_menu(0).trigger("Clear Sort")
        self.assertEqual(dialog._steps, [{
            "op": "sort_rows_by_columns",
            "sorts": [{"column": "Amount", "direction": "desc"}],
        }])

    # ----- filters ------------------------------------------------------

    def test_remove_empty_filters_null_and_empty_text_and_round_trips_m(self) -> None:
        dialog = self.make()
        info = dialog._build_preview_column_menu(0)
        self.assertFalse(info.action("Clear Filter").isEnabled())
        info.trigger("Remove Empty")
        self.assertEqual(dialog._steps[-1], {
            "op": "filter_rows", "column": "Region",
            "operator": "is_not_blank", "value": "",
        })
        self.assertEqual([row["Region"] for row in dialog._preview_candidate.rows],
                         ["East", "West", "East"])
        script = steps_to_m_script(dialog._steps, "Sales")
        self.assertIn('([#"Region"] <> null and [#"Region"] <> "")', script)
        self.assertTrue(m_script_matches_steps(script, "Sales", dialog._steps))
        self.assertEqual(parse_m_script(script, "Sales"), dialog._steps)
        self.assertTrue(dialog.preview_header._profiles[0]["filter_active"])

    def test_clear_filter_removes_this_columns_filter_steps_only(self) -> None:
        dialog = self.make()
        dialog._build_preview_column_menu(0).trigger("Remove Empty")
        dialog._build_preview_column_menu(1).trigger("Remove Empty")
        self.assertEqual(len(dialog._steps), 2)
        dialog._build_preview_column_menu(0).trigger("Clear Filter")
        self.assertEqual([step["column"] for step in dialog._steps], ["Amount"])
        self.assertEqual(len(dialog._step_metadata), 1)
        self.assertFalse(dialog.preview_header._profiles[0]["filter_active"])
        self.assertTrue(dialog.preview_header._profiles[1]["filter_active"])

    def _run_condition(self, dialog, path: str, column: int, values: list[str]):
        with patch(
            "analytics_studio.local_table_dialogs._PowerQueryConditionDialog"
        ) as condition_type:
            condition = condition_type.return_value
            condition.exec.return_value = QDialog.DialogCode.Accepted
            condition.values.return_value = values
            dialog._build_preview_column_menu(column).trigger(path)
        return condition_type

    def test_text_filter_contains_adds_a_filter_step(self) -> None:
        dialog = self.make()
        condition_type = self._run_condition(
            dialog, "Text Filters/Contains…", 0, ["as"]
        )
        self.assertEqual(condition_type.call_args.args[0], "Region")
        self.assertIn("Contains", condition_type.call_args.args[1])
        self.assertEqual(dialog._steps[-1], {
            "op": "filter_rows", "column": "Region",
            "operator": "contains", "value": "as",
        })
        self.assertEqual([row["Region"] for row in dialog._preview_candidate.rows],
                         ["East", "East"])

    def test_every_text_filter_item_maps_to_its_engine_operator(self) -> None:
        expected = {
            "Equals…": "equals", "Does Not Equal…": "not_equals",
            "Begins With…": "begins_with",
            "Does Not Begin With…": "does_not_begin_with",
            "Ends With…": "ends_with", "Does Not End With…": "does_not_end_with",
            "Contains…": "contains", "Does Not Contain…": "does_not_contain",
        }
        for label, operator in expected.items():
            with self.subTest(label):
                dialog = self.make()
                self._run_condition(dialog, f"Text Filters/{label}", 0, ["E"])
                self.assertEqual(dialog._steps[-1]["operator"], operator)

    def test_number_filters_use_numeric_operators_and_between_uses_two_clauses(self) -> None:
        dialog = self.make(TYPED)
        self._run_condition(dialog, "Number Filters/Greater Than…", 1, ["20"])
        self.assertEqual(dialog._steps[-1], {
            "op": "filter_rows", "column": "Amount",
            "operator": "greater_than", "value": "20",
        })
        self.assertEqual([row["Amount"] for row in dialog._preview_candidate.rows],
                         [30, 40, 50])
        dialog = self.make(TYPED)
        self._run_condition(dialog, "Number Filters/Between…", 1, ["20", "40"])
        self.assertEqual(dialog._steps[-1], {
            "op": "filter_rows_advanced",
            "clauses": [
                {"column": "Amount", "operator": "greater_than_or_equal",
                 "value": "20", "join": "and"},
                {"column": "Amount", "operator": "less_than_or_equal",
                 "value": "40", "join": "and"},
            ],
        })
        self.assertEqual([row["Amount"] for row in dialog._preview_candidate.rows],
                         [20, 30, 40])
        script = steps_to_m_script(dialog._steps, "Sales")
        self.assertEqual(parse_m_script(script, "Sales"), dialog._steps)

    def test_date_equals_filters_the_column(self) -> None:
        dialog = self.make(TYPED)
        self._run_condition(dialog, "Date Filters/Equals…", 2, ["2026-01-02"])
        self.assertEqual(len(dialog._preview_candidate.rows), 1)

    def test_cancelled_condition_dialog_adds_nothing(self) -> None:
        dialog = self.make()
        with patch(
            "analytics_studio.local_table_dialogs._PowerQueryConditionDialog"
        ) as condition_type:
            condition_type.return_value.exec.return_value = QDialog.DialogCode.Rejected
            dialog._build_preview_column_menu(0).trigger("Text Filters/Contains…")
        self.assertEqual(dialog._steps, [])

    def test_condition_dialog_validates_its_inputs(self) -> None:
        from analytics_studio.local_table_dialogs import _PowerQueryConditionDialog
        one = _PowerQueryConditionDialog("Region", "Contains", 1)
        self.addCleanup(one.deleteLater)
        self.assertFalse(one.ok_button.isEnabled())
        one.edits[0].setText("x")
        self.assertTrue(one.ok_button.isEnabled())
        self.assertEqual(one.values(), ["x"])
        two = _PowerQueryConditionDialog("Amount", "Between", 2)
        self.addCleanup(two.deleteLater)
        two.edits[0].setText("1")
        self.assertFalse(two.ok_button.isEnabled())
        two.edits[1].setText("2")
        self.assertTrue(two.ok_button.isEnabled())
        self.assertEqual(two.values(), ["1", "2"])

    # ----- value list ---------------------------------------------------

    def _item(self, panel, text: str):
        return next(panel.value_list.item(i) for i in range(panel.value_list.count())
                    if panel.value_list.item(i).text() == text)

    def test_unchecking_a_value_filters_with_does_not_equal_and_closes_the_menu(self) -> None:
        dialog = self.make()
        info = dialog._build_preview_column_menu(0)
        self._item(info.panel, "West").setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(
            self._item(info.panel, "(Select All)").checkState(),
            Qt.CheckState.PartiallyChecked,
        )
        info.menu.show()
        info.panel.ok_button.click()
        self.assertFalse(info.menu.isVisible())
        self.assertEqual(dialog._steps[-1], {
            "op": "filter_rows", "column": "Region",
            "operator": "not_equals", "value": "West",
        })
        self.assertEqual([row["Region"] for row in dialog._preview_candidate.rows],
                         ["East", "East", "", None])
        script = steps_to_m_script(dialog._steps, "Sales")
        self.assertTrue(m_script_matches_steps(script, "Sales", dialog._steps))
        self.assertTrue(dialog.preview_header._profiles[0]["filter_active"])

    def test_checking_only_some_values_keeps_just_those(self) -> None:
        dialog = self.make()
        info = dialog._build_preview_column_menu(0)
        select_all = self._item(info.panel, "(Select All)")
        select_all.setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(self._item(info.panel, "East").checkState(),
                         Qt.CheckState.Unchecked)
        self.assertFalse(info.panel.ok_button.isEnabled())
        self._item(info.panel, "East").setCheckState(Qt.CheckState.Checked)
        info.panel.ok_button.click()
        self.assertEqual(dialog._steps[-1], {
            "op": "filter_rows", "column": "Region",
            "operator": "equals", "value": "East",
        })
        self.assertEqual([row["Region"] for row in dialog._preview_candidate.rows],
                         ["East", "East"])

    def test_unchecking_blank_keeps_only_nonblank_rows(self) -> None:
        dialog = self.make()
        info = dialog._build_preview_column_menu(0)
        self._item(info.panel, "(Blank)").setCheckState(Qt.CheckState.Unchecked)
        info.panel.ok_button.click()
        self.assertEqual(dialog._steps[-1], {
            "op": "filter_rows", "column": "Region",
            "operator": "is_not_blank", "value": "",
        })
        self.assertEqual([row["Region"] for row in dialog._preview_candidate.rows],
                         ["East", "West", "East"])

    def test_ok_with_everything_selected_and_cancel_add_no_step(self) -> None:
        dialog = self.make()
        info = dialog._build_preview_column_menu(0)
        info.panel.ok_button.click()
        self.assertEqual(dialog._steps, [])
        info = dialog._build_preview_column_menu(0)
        self._item(info.panel, "East").setCheckState(Qt.CheckState.Unchecked)
        info.panel.cancel_button.click()
        self.assertEqual(dialog._steps, [])

    def test_select_all_applies_only_to_search_results(self) -> None:
        dialog = self.make()
        panel = dialog._build_preview_column_menu(0).panel
        panel.search_edit.setText("ea")
        self._item(panel, "(Select All)").setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(self._item(panel, "East").checkState(), Qt.CheckState.Unchecked)
        self.assertEqual(self._item(panel, "West").checkState(), Qt.CheckState.Checked)

    # ----- opening the menu from the header ------------------------------

    def test_header_button_opens_the_menu_at_the_button_and_runs_the_chosen_action(self) -> None:
        dialog = self.make()
        dialog.resize(1100, 720)
        dialog.show()
        self.app.processEvents()
        button = next(b for b in dialog.preview_header._filter_buttons
                      if b.property("logicalIndex") == 0)
        seen: dict = {}

        class RecordingMenu(QMenu):
            def exec(self, position=None, *args):  # noqa: A003
                seen["menu"] = self
                seen["position"] = position
                return next(a for a in self.actions() if a.text() == "Remove Empty")

        with patch("analytics_studio.local_table_dialogs.QMenu", RecordingMenu):
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            self.app.processEvents()
        self.assertEqual(seen["position"], button.mapToGlobal(QPoint(0, button.height())))
        self.assertEqual(dialog._steps[-1]["operator"], "is_not_blank")


if __name__ == "__main__":
    unittest.main()
