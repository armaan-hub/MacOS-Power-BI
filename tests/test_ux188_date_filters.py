from __future__ import annotations

from datetime import date, datetime
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.file_import import ImportCandidate
from analytics_studio.power_query_m import m_compatibility_issues, parse_m_script, steps_to_m_script
from analytics_studio.transformations import apply_transformations

# Ensure offscreen Qt application exists for UI tests
_APP = QApplication.instance() or QApplication([])


class TestDateFiltersEngine(unittest.TestCase):
    def test_date_column_operators(self) -> None:
        # Values: 2026-07-31, 2026-08-01, 2026-08-02, null, empty string
        headers = ["ID", "D"]
        rows = [
            {"ID": "1", "D": "2026-07-31"},
            {"ID": "2", "D": "2026-08-01"},
            {"ID": "3", "D": "2026-08-02"},
            {"ID": "4", "D": None},
            {"ID": "5", "D": ""},
        ]
        candidate = ImportCandidate("table", headers, rows, {}, [])
        steps_prep = [{"op": "convert_type", "column": "D", "type": "date"}]
        typed = apply_transformations(candidate, steps_prep)

        # date_before 2026-08-01 -> keeps only 2026-07-31 (row 1)
        res = apply_transformations(typed, [{"op": "filter_rows", "column": "D", "operator": "date_before", "value": "2026-08-01"}])
        self.assertEqual([r["ID"] for r in res.rows], ["1"])

        # date_after 2026-08-01 -> keeps only 2026-08-02 (row 3)
        res = apply_transformations(typed, [{"op": "filter_rows", "column": "D", "operator": "date_after", "value": "2026-08-01"}])
        self.assertEqual([r["ID"] for r in res.rows], ["3"])

        # Between (greater_than_or_equal 2026-08-01 and less_than_or_equal 2026-08-02) -> keeps rows 2 and 3
        res = apply_transformations(typed, [{
            "op": "filter_rows_advanced",
            "clauses": [
                {"column": "D", "operator": "greater_than_or_equal", "value": "2026-08-01", "join": "and"},
                {"column": "D", "operator": "less_than_or_equal", "value": "2026-08-02", "join": "and"},
            ],
        }])
        self.assertEqual([r["ID"] for r in res.rows], ["2", "3"])

        # is_earliest -> keeps 2026-07-31 (row 1)
        res = apply_transformations(typed, [{"op": "filter_rows", "column": "D", "operator": "is_earliest", "value": ""}])
        self.assertEqual([r["ID"] for r in res.rows], ["1"])

        # is_latest -> keeps 2026-08-02 (row 3)
        res = apply_transformations(typed, [{"op": "filter_rows", "column": "D", "operator": "is_latest", "value": ""}])
        self.assertEqual([r["ID"] for r in res.rows], ["3"])

    def test_datetime_column_operators(self) -> None:
        headers = ["ID", "DT"]
        rows = [
            {"ID": "1", "DT": "2026-08-01 09:00:00"},
            {"ID": "2", "DT": "2026-08-01 12:00:00"},
            {"ID": "3", "DT": "2026-08-01 18:00:00"},
            {"ID": "4", "DT": None},
            {"ID": "5", "DT": ""},
        ]
        candidate = ImportCandidate("table", headers, rows, {}, [])
        steps_prep = [{"op": "convert_type", "column": "DT", "type": "datetime"}]
        typed = apply_transformations(candidate, steps_prep)

        # date_before 2026-08-01 12:00:00 -> keeps row 1
        res = apply_transformations(typed, [{"op": "filter_rows", "column": "DT", "operator": "date_before", "value": "2026-08-01 12:00:00"}])
        self.assertEqual([r["ID"] for r in res.rows], ["1"])

        # date_after 2026-08-01 12:00:00 -> keeps row 3
        res = apply_transformations(typed, [{"op": "filter_rows", "column": "DT", "operator": "date_after", "value": "2026-08-01 12:00:00"}])
        self.assertEqual([r["ID"] for r in res.rows], ["3"])

        # is_earliest -> row 1
        res = apply_transformations(typed, [{"op": "filter_rows", "column": "DT", "operator": "is_earliest", "value": ""}])
        self.assertEqual([r["ID"] for r in res.rows], ["1"])

        # is_latest -> row 3
        res = apply_transformations(typed, [{"op": "filter_rows", "column": "DT", "operator": "is_latest", "value": ""}])
        self.assertEqual([r["ID"] for r in res.rows], ["3"])

    def test_is_earliest_with_ties_keeps_all_tied_rows(self) -> None:
        headers = ["ID", "D"]
        rows = [
            {"ID": "1", "D": "2026-08-01"},
            {"ID": "2", "D": "2026-08-02"},
            {"ID": "3", "D": "2026-08-01"},
            {"ID": "4", "D": None},
        ]
        candidate = ImportCandidate("table", headers, rows, {}, [])
        res = apply_transformations(candidate, [{"op": "filter_rows", "column": "D", "operator": "is_earliest", "value": ""}])
        self.assertEqual([r["ID"] for r in res.rows], ["1", "3"])

    def test_all_null_column_returns_no_rows(self) -> None:
        headers = ["ID", "D"]
        rows = [
            {"ID": "1", "D": None},
            {"ID": "2", "D": ""},
            {"ID": "3", "D": None},
        ]
        candidate = ImportCandidate("table", headers, rows, {}, [])
        for op in ("date_before", "date_after"):
            with self.subTest(op):
                res = apply_transformations(candidate, [{"op": "filter_rows", "column": "D", "operator": op, "value": "2026-08-01"}])
                self.assertEqual(len(res.rows), 0)
        for op in ("is_earliest", "is_latest"):
            with self.subTest(op):
                res = apply_transformations(candidate, [{"op": "filter_rows", "column": "D", "operator": op, "value": ""}])
                self.assertEqual(len(res.rows), 0)


class TestDateFiltersM(unittest.TestCase):
    def test_steps_to_m_and_round_trip(self) -> None:
        # Date column
        before_step = [{"op": "filter_rows", "column": "D", "operator": "date_before", "value": "2026-08-01"}]
        m_before = steps_to_m_script(before_step, "Sales", initial_column_types={"D": "date"})
        self.assertIn('Table.SelectRows(Source, each [D] < #date(2026, 8, 1))', m_before)
        self.assertEqual(parse_m_script(m_before, "Sales", initial_column_types={"D": "date"}), before_step)

        after_step = [{"op": "filter_rows", "column": "D", "operator": "date_after", "value": "2026-08-01"}]
        m_after = steps_to_m_script(after_step, "Sales", initial_column_types={"D": "date"})
        self.assertIn('Table.SelectRows(Source, each [D] > #date(2026, 8, 1))', m_after)
        self.assertEqual(parse_m_script(m_after, "Sales", initial_column_types={"D": "date"}), after_step)

        between_steps = [{
            "op": "filter_rows_advanced",
            "clauses": [
                {"column": "D", "operator": "greater_than_or_equal", "value": "2026-08-01", "join": "and"},
                {"column": "D", "operator": "less_than_or_equal", "value": "2026-08-02", "join": "and"},
            ],
        }]
        m_between = steps_to_m_script(between_steps, "Sales", initial_column_types={"D": "date"})
        self.assertIn('each ([D] >= #date(2026, 8, 1) and [D] <= #date(2026, 8, 2))', m_between)
        self.assertEqual(parse_m_script(m_between, "Sales", initial_column_types={"D": "date"}), between_steps)

        earliest_step = [{"op": "filter_rows", "column": "D", "operator": "is_earliest", "value": ""}]
        m_earliest = steps_to_m_script(earliest_step, "Sales", initial_column_types={"D": "date"})
        self.assertIn('let earliest = List.Min(Source[D]) in Table.SelectRows(Source, each [D] = earliest)', m_earliest)
        self.assertEqual(parse_m_script(m_earliest, "Sales", initial_column_types={"D": "date"}), earliest_step)

        latest_step = [{"op": "filter_rows", "column": "D", "operator": "is_latest", "value": ""}]
        m_latest = steps_to_m_script(latest_step, "Sales", initial_column_types={"D": "date"})
        self.assertIn('let latest = List.Max(Source[D]) in Table.SelectRows(Source, each [D] = latest)', m_latest)
        self.assertEqual(parse_m_script(m_latest, "Sales", initial_column_types={"D": "date"}), latest_step)

        # Datetime column
        before_dt = [{"op": "filter_rows", "column": "D", "operator": "date_before", "value": "2026-08-01 00:00:00"}]
        m_dt = steps_to_m_script(before_dt, "Sales", initial_column_types={"D": "datetime"})
        self.assertIn('Table.SelectRows(Source, each [D] < #datetime(2026, 8, 1, 0, 0, 0))', m_dt)
        self.assertEqual(parse_m_script(m_dt, "Sales", initial_column_types={"D": "datetime"}), before_dt)

        # Compatibility issues
        for step in (before_step, after_step, between_steps, earliest_step, latest_step):
            self.assertEqual(m_compatibility_issues(step, initial_column_types={"D": "date"}), [])


class TestDateFiltersUI(unittest.TestCase):
    def _make_dialog(self):
        from analytics_studio.local_table_dialogs import TransformDataDialog
        from tests.test_power_query_column_menu_lifecycle import _source, TYPED
        return TransformDataDialog(_source(), steps=TYPED, query_name="Sales")

    def test_menu_items_enabled_and_disabled_states(self) -> None:
        dialog = self._make_dialog()
        info = dialog._build_preview_column_menu(2)  # Day column (type: date)
        enabled_items = ["Equals…", "Before…", "After…", "Between…", "Is Earliest", "Is Latest"]
        for text in enabled_items:
            action = info.action(f"Date Filters/{text}")
            self.assertIsNotNone(action, text)
            self.assertTrue(action.isEnabled(), text)

        disabled_items = ["In the Next…", "In the Previous…", "Year", "Quarter", "Month", "Week", "Day"]
        for text in disabled_items:
            action = info.action(f"Date Filters/{text}")
            self.assertIsNotNone(action, text)
            self.assertFalse(action.isEnabled(), text)

    def test_before_with_condition_dialog_adds_step_and_filters(self) -> None:
        dialog = self._make_dialog()
        # Original rows have Day: 2026-01-01, 2026-01-02, 2026-01-03, 2026-01-04, 2026-01-05
        with patch("analytics_studio.local_table_dialogs._PowerQueryConditionDialog") as condition_type:
            condition = condition_type.return_value
            condition.exec.return_value = QDialog.DialogCode.Accepted
            condition.values.return_value = ["2026-01-03"]
            dialog._build_preview_column_menu(2).trigger("Date Filters/Before…")

        self.assertEqual(dialog._steps[-1], {
            "op": "filter_rows", "column": "Day",
            "operator": "date_before", "value": "2026-01-03",
        })
        # 2026-01-01 and 2026-01-02 kept -> row count is 2
        self.assertEqual(len(dialog._preview_candidate.rows), 2)

    def test_is_latest_adds_the_step(self) -> None:
        dialog = self._make_dialog()
        dialog._build_preview_column_menu(2).trigger("Date Filters/Is Latest")
        self.assertEqual(dialog._steps[-1], {
            "op": "filter_rows", "column": "Day",
            "operator": "is_latest", "value": "",
        })
        # Latest date is 2026-01-05 -> exactly 1 row
        self.assertEqual(len(dialog._preview_candidate.rows), 1)
        self.assertEqual(dialog._preview_candidate.rows[0]["Day"], date(2026, 1, 5))
