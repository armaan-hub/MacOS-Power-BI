"""Acceptance checks for the local Power Query M Advanced Editor subset."""

from __future__ import annotations

import os
import unittest
from copy import deepcopy
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QInputDialog,
    QMessageBox,
    QToolButton,
)

from analytics_studio.file_import import MAX_DATA_ROWS, ImportCandidate
from analytics_studio.power_query_expression import compile_expression, evaluate_expression
from analytics_studio.power_query_m import (
    PowerQueryMEditorDialog,
    PowerQueryMScriptError,
    m_compatibility_issues,
    m_script_matches_steps,
    parse_m_script,
    parse_m_query_script,
    rewrite_m_append_source_names,
    steps_to_m_script,
)
from analytics_studio.local_table_dialogs import TransformDataDialog
from analytics_studio.query_dependencies_dialog import QueryDependenciesDialog
from analytics_studio.transformations import (
    TransformationError,
    apply_transformations,
    column_types_after_steps,
)


class PowerQueryMEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Power Query M tests"])

    def setUp(self) -> None:
        self.source = ImportCandidate(
            "inline",
            ["Region", "Revenue", "Customer"],
            [
                {"Region": "East", "Revenue": "12", "Customer": "  Ada  "},
                {"Region": "West", "Revenue": "20", "Customer": "Lin"},
            ],
            {},
            [],
        )

    def test_power_query_windows_show_all_ribbon_tabs_with_light_controls(self) -> None:
        dialog = TransformDataDialog(self.source, query_name="Sales Data")
        self.assertEqual(
            [dialog.ribbon_tabs.tabText(index) for index in range(dialog.ribbon_tabs.count())],
            ["Home", "Transform", "Add Column", "View", "Tools", "Help"],
        )
        self.assertIn("background-color: #f4f6f8", dialog.styleSheet())

        advanced = PowerQueryMEditorDialog(self.source, [], "Sales Data")
        self.assertIn("background-color: #f4f6f8", advanced.styleSheet())
        dialog.deleteLater()
        advanced.deleteLater()

    def test_home_advanced_editor_opens_separate_dialog_for_active_query(self) -> None:
        steps = [{"op": "trim_text", "column": "Customer"}]
        dialog = TransformDataDialog(self.source, steps, query_name="Sales Data")
        before_steps = deepcopy(dialog._steps)
        before_preview = deepcopy(dialog._preview_candidate)
        home_index = dialog.ribbon_tabs.indexOf(
            next(
                dialog.ribbon_tabs.widget(index)
                for index in range(dialog.ribbon_tabs.count())
                if dialog.ribbon_tabs.tabText(index) == "Home"
            )
        )
        dialog.ribbon_tabs.setCurrentIndex(home_index)
        button = dialog.findChild(QToolButton, "openPowerQueryMEditorHomeButton")
        self.assertIsNotNone(button)
        self.assertIn(button, dialog.ribbon_tabs.currentWidget().findChildren(QToolButton))

        observed: dict[str, object] = {}

        def close_editor() -> None:
            editors = [
                widget for widget in QApplication.topLevelWidgets()
                if isinstance(widget, PowerQueryMEditorDialog) and widget.isVisible()
            ]
            if len(editors) != 1:
                observed["count"] = len(editors)
                for editor in editors:
                    editor.reject()
                modal = QApplication.activeModalWidget()
                if modal is not None and modal is not dialog:
                    modal.reject()
                return
            editor = editors[0]
            observed["window"] = editor.isWindow()
            observed["query_name"] = editor._query_name
            observed["source"] = editor._source_candidate
            observed["steps"] = deepcopy(editor._steps)
            observed["preview_rows"] = deepcopy(editor._candidate.rows)
            editor.reject()

        QTimer.singleShot(0, close_editor)
        button.click()

        self.assertTrue(observed.get("window"))
        self.assertEqual(observed.get("query_name"), "Sales Data")
        self.assertEqual(observed.get("source"), self.source)
        self.assertEqual(observed.get("steps"), steps)
        self.assertEqual(observed.get("preview_rows"), before_preview.rows)
        self.assertEqual(dialog._steps, before_steps)
        self.assertEqual(dialog._preview_candidate, before_preview)
        dialog.deleteLater()

    def test_home_refresh_preview_rereads_source_and_replays_current_steps(self) -> None:
        refreshed = ImportCandidate(
            "inline",
            ["Region", "Revenue", "Customer"],
            [{"Region": "East", "Revenue": "30", "Customer": "  Noor  "}],
            {},
            [],
        )
        calls: list[str] = []

        def refresh(
            query_id: str,
            _queries: dict[str, dict[str, object]],
            _parameters: dict[str, object],
        ) -> tuple[ImportCandidate, dict[str, str], dict[str, object]]:
            calls.append(query_id)
            return (
                refreshed,
                {"Region": "text", "Revenue": "whole_number", "Customer": "text"},
                {},
            )

        dialog = TransformDataDialog(
            self.source,
            [{"op": "trim_text", "column": "Customer"}],
            query_name="Sales Data",
            refresh_candidate=refresh,
        )
        button = dialog.findChild(QToolButton, "powerQueryRefreshPreviewButton")

        self.assertIsNotNone(button)
        self.assertTrue(button.isEnabled())
        button.click()

        self.assertEqual(calls, ["__active__"])
        self.assertEqual(dialog._source_candidate, refreshed)
        self.assertEqual(dialog._preview_candidate.rows[0]["Customer"], "Noor")
        self.assertEqual(dialog.count_label.toolTip(), "Preview refreshed from the current source data.")
        dialog.deleteLater()

    def test_refresh_preview_failure_keeps_the_staged_editor_snapshot(self) -> None:
        def refresh(
            _query_id: str,
            _queries: dict[str, dict[str, object]],
            _parameters: dict[str, object],
        ) -> tuple[ImportCandidate, dict[str, str], dict[str, object]]:
            raise OSError("source unavailable")

        dialog = TransformDataDialog(
            self.source,
            [{"op": "trim_text", "column": "Customer"}],
            query_name="Sales Data",
            refresh_candidate=refresh,
        )
        source_before = dialog._source_candidate
        preview_before = dialog._preview_candidate
        states_before = deepcopy(dialog._query_states)
        steps_before = deepcopy(dialog._steps)

        dialog.findChild(
            QToolButton, "powerQueryRefreshPreviewButton"
        ).click()

        self.assertIs(dialog._source_candidate, source_before)
        self.assertIs(dialog._preview_candidate, preview_before)
        self.assertEqual(dialog._query_states, states_before)
        self.assertEqual(dialog._steps, steps_before)
        self.assertFalse(dialog.error_label.isHidden())
        self.assertIn("source unavailable", dialog.error_label.text())
        dialog.deleteLater()

    def test_refresh_preview_is_disabled_for_queries_excluded_from_refresh(self) -> None:
        dialog = TransformDataDialog(
            self.source,
            query_name="Cached Query",
            queries=[{
                "id": "cached",
                "name": "Cached Query",
                "candidate": self.source,
                "is_saved_query": True,
                "include_in_report_refresh": False,
            }],
            active_query_id="cached",
            refresh_candidate=lambda *_args: (self.source, {}, {}),
        )
        button = dialog.findChild(
            QToolButton, "powerQueryRefreshPreviewButton"
        )

        self.assertFalse(button.isEnabled())
        self.assertIn("cached preview", button.toolTip())
        dialog.query_refresh_included_checkbox.setChecked(True)
        self.assertTrue(button.isEnabled())
        dialog.deleteLater()

    def test_query_dependency_diagram_shows_reference_and_merge_edges(self) -> None:
        dialog = QueryDependenciesDialog([
            {"id": "source", "name": "Sales", "query_definition": {}},
            {
                "id": "reference", "name": "Sales Reference",
                "query_definition": {"operation": "reference", "source_ids": ["source"]},
            },
            {
                "id": "merge", "name": "Sales by Region",
                "query_definition": {
                    "operation": "merge", "source_ids": ["source", "reference"],
                    "join_kind": "left_outer",
                },
                "steps": [{"op": "remove_blank_rows"}],
            },
            {
                "id": "missing", "name": "Unavailable",
                "query_definition": {"operation": "reference", "source_ids": ["outside"]},
                "is_unavailable": True,
            },
        ])

        self.assertEqual(set(dialog.node_items), {"source", "reference", "merge", "missing"})
        self.assertEqual(dialog.dependency_edges, [
            ("source", "reference"),
            ("source", "merge"),
            ("reference", "merge"),
        ])
        self.assertEqual(
            dialog.summary_label.text(),
            "4 queries · 3 dependencies · 1 parent reference(s) outside this session",
        )
        self.assertLess(
            dialog.node_items["source"].rect().x(),
            dialog.node_items["reference"].rect().x(),
        )
        dialog.deleteLater()

    def test_view_ribbon_opens_dependency_diagram_from_current_query_state(self) -> None:
        queries = [
            {
                "id": "source", "name": "Sales", "candidate": self.source,
                "steps": [], "query_definition": {},
            },
            {
                "id": "reference", "name": "Sales Reference", "candidate": self.source,
                "steps": [], "query_definition": {
                    "operation": "reference", "source_ids": ["source"],
                },
            },
        ]
        editor = TransformDataDialog(
            self.source, queries=queries, active_query_id="source"
        )
        button = editor.findChild(QToolButton, "powerQueryDiagramViewButton")
        self.assertIsNotNone(button)

        with patch.object(
            QueryDependenciesDialog,
            "exec",
            return_value=QDialog.DialogCode.Accepted,
        ) as show_dialog:
            button.click()

        show_dialog.assert_called_once()
        editor.deleteLater()

    def test_m_query_filters_cleans_adds_column_and_converts_type(self) -> None:
        script = '''let
    Source = #"Sales Data",
    Filtered = Table.SelectRows(Source, each [Region] = "East"),
    Trimmed = Table.TransformColumns(Filtered, {{"Customer", Text.Trim, type text}}),
    Typed = Table.TransformColumnTypes(Trimmed, {{"Revenue", type number}}),
    Added = Table.AddColumn(Typed, "Net", each Text.From([Revenue] * 0.9), type text)
in
    Added'''

        steps = parse_m_script(script, "Sales Data")
        result = apply_transformations(self.source, steps)

        self.assertEqual(result.headers, ["Region", "Revenue", "Customer", "Net"])
        self.assertEqual(result.rows, [
            {"Region": "East", "Revenue": "12", "Customer": "Ada", "Net": "10.8"},
        ])

    def test_advanced_filter_m_round_trip_keeps_and_before_or(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Region", "Revenue", "Customer"],
            [
                {"Region": "East", "Revenue": "12", "Customer": "Ada"},
                {"Region": "West", "Revenue": "20", "Customer": "Lin"},
                {"Region": "East", "Revenue": "20", "Customer": "Lin"},
            ],
            {},
            [],
        )
        step = {
            "op": "filter_rows_advanced",
            "clauses": [
                {"column": "Region", "operator": "equals", "value": "East", "join": "and"},
                {"column": "Revenue", "operator": "greater_than", "value": "11", "join": "and"},
                {"column": "Customer", "operator": "contains", "value": "Ada", "join": "and"},
                {"column": "Revenue", "operator": "equals", "value": "20", "join": "or"},
            ],
        }

        script = steps_to_m_script([step], "Sales Data")
        parsed = parse_m_script(script, "Sales Data")

        self.assertIn('([#"Region"] = "East" and (if [#"Revenue"] = null', script)
        self.assertIn('if [#"Customer"] = null or [#"Customer"] = "" then false', script)
        self.assertIn('Number.From([#"Revenue"]) > 11', script)
        self.assertIn(' or [#"Revenue"] = "20"', script)
        self.assertEqual(parsed, [step])
        self.assertEqual(m_compatibility_issues([step]), [])
        self.assertEqual(
            apply_transformations(source, parsed),
            apply_transformations(source, [step]),
        )
        self.assertEqual(
            [row["Customer"] for row in apply_transformations(source, parsed).rows],
            ["Ada", "Lin", "Lin"],
        )

    def test_one_clause_advanced_filter_round_trips_as_equivalent_simple_filter(self) -> None:
        step = {
            "op": "filter_rows_advanced",
            "clauses": [{
                "column": "Region", "operator": "equals", "value": "East",
                "join": "and",
            }],
        }
        script = steps_to_m_script([step], "Sales Data")
        parsed = parse_m_script(script, "Sales Data")

        self.assertEqual(parsed, [{
            "op": "filter_rows", "column": "Region", "operator": "equals",
            "value": "East",
        }])
        self.assertEqual(m_compatibility_issues([step]), [])
        self.assertTrue(m_script_matches_steps(script, "Sales Data", [step]))
        self.assertEqual(
            apply_transformations(self.source, parsed),
            apply_transformations(self.source, [step]),
        )

    def test_advanced_filter_m_rejects_grouping_outside_local_and_or_model(self) -> None:
        script = '''let
    Source = #"Sales Data",
    Filtered = Table.SelectRows(Source, each ([#"Region"] = "East" or [#"Region"] = "West") and [#"Customer"] = "Ada")
in
    Filtered'''

        with self.assertRaisesRegex(PowerQueryMScriptError, "grouped before OR"):
            parse_m_script(script, "Sales Data")

    def test_numeric_filter_m_converts_text_values_and_excludes_blanks(self) -> None:
        source = ImportCandidate(
            "inline", ["Amount"],
            [{"Amount": "10"}, {"Amount": "20"}, {"Amount": ""}], {}, [],
        )
        step = {
            "op": "filter_rows", "column": "Amount",
            "operator": "greater_than", "value": "15",
        }

        script = steps_to_m_script([step], "Sales Data")
        parsed = parse_m_script(script, "Sales Data")

        self.assertIn('if [#"Amount"] = null or [#"Amount"] = "" then false', script)
        self.assertIn('Number.From([#"Amount"]) > 15', script)
        self.assertEqual(parsed, [step])
        self.assertEqual(m_compatibility_issues([step]), [])
        self.assertEqual(
            apply_transformations(source, parsed),
            apply_transformations(source, [step]),
        )
        self.assertEqual(
            [row["Amount"] for row in apply_transformations(source, parsed).rows],
            ["20"],
        )

    def test_conditional_column_m_round_trip_preserves_ordered_rules_and_blank_text(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Region", "Revenue", "Customer"],
            [
                {"Region": "East", "Revenue": "12", "Customer": "Ada"},
                {"Region": "West", "Revenue": "20", "Customer": "Lin"},
                {"Region": "West", "Revenue": "8", "Customer": ""},
            ],
            {},
            [],
        )
        step = {
            "op": "conditional_column",
            "name": "Segment",
            "clauses": [
                {
                    "column": "Region", "operator": "equals", "test_value": "East",
                    "test_value_kind": "value", "output": "East sale", "output_kind": "value",
                },
                {
                    "column": "Customer", "operator": "does_not_contain", "test_value": "a",
                    "test_value_kind": "value", "output": "No a", "output_kind": "value",
                },
            ],
            "else_value": "Other",
            "else_kind": "value",
        }

        script = steps_to_m_script([step], "Sales Data")
        parsed = parse_m_script(script, "Sales Data")

        self.assertEqual(m_compatibility_issues([step]), [])
        self.assertEqual(parsed, [step])
        self.assertIn(
            'if [#"Customer"] = null then true else not Text.Contains', script
        )
        self.assertEqual(
            apply_transformations(source, parsed),
            apply_transformations(source, [step]),
        )
        self.assertEqual(
            [row["Segment"] for row in apply_transformations(source, parsed).rows],
            ["East sale", "No a", "No a"],
        )

    def test_numeric_conditional_m_round_trip_requires_and_keeps_numeric_conversion(self) -> None:
        script = '''let
    Source = #"Sales Data",
    Typed = Table.TransformColumnTypes(Source, {{"Revenue", type number}}),
    Added = Table.AddColumn(Typed, "Band", each if [Revenue] > 15 then Text.From([Revenue]) else "Low", type text)
in
    Added'''

        steps = parse_m_script(script, "Sales Data")
        generated = steps_to_m_script(steps, "Sales Data")

        self.assertEqual(steps[1]["op"], "conditional_column")
        self.assertEqual(steps[1]["clauses"][0]["operator"], "greater_than")
        self.assertIn('[#"Revenue"] > 15', generated)
        self.assertEqual(parse_m_script(generated, "Sales Data"), steps)
        self.assertEqual(m_compatibility_issues(steps), [])
        self.assertEqual(
            [row["Band"] for row in apply_transformations(self.source, steps).rows],
            ["Low", "20"],
        )

    def test_numeric_conditional_m_comparison_without_numeric_type_is_rejected(self) -> None:
        script = '''let
    Source = #"Sales Data",
    Added = Table.AddColumn(Source, "Band", each if [Revenue] > 15 then "High" else "Low", type text)
in
    Added'''

        with self.assertRaisesRegex(PowerQueryMScriptError, "explicit numeric type conversion"):
            parse_m_script(script, "Sales Data")

    def test_conditional_column_all_text_predicates_round_trip(self) -> None:
        source = ImportCandidate(
            "inline", ["Customer"],
            [{"Customer": "Ada"}, {"Customer": "Lin"}, {"Customer": ""}],
            {}, [],
        )
        cases = (
            ("begins_with", "A"),
            ("does_not_begin_with", "Z"),
            ("ends_with", "a"),
            ("does_not_end_with", "z"),
            ("contains", "d"),
            ("does_not_contain", "z"),
        )

        for operator, value in cases:
            with self.subTest(operator=operator):
                step = {
                    "op": "conditional_column", "name": "Matched",
                    "clauses": [{
                        "column": "Customer", "operator": operator,
                        "test_value": value, "test_value_kind": "value",
                        "output": "yes", "output_kind": "value",
                    }],
                    "else_value": "no", "else_kind": "value",
                }
                script = steps_to_m_script([step], "Customers")
                parsed = parse_m_script(script, "Customers")

                self.assertEqual(parsed, [step])
                self.assertEqual(m_compatibility_issues([step]), [])
                self.assertEqual(
                    apply_transformations(source, parsed),
                    apply_transformations(source, [step]),
                )

    def test_conditional_column_empty_text_predicates_preserve_blank_rows(self) -> None:
        source = ImportCandidate(
            "inline", ["Customer"],
            [{"Customer": "abc"}, {"Customer": ""}], {}, [],
        )
        operators = (
            "contains", "does_not_contain", "begins_with", "does_not_begin_with",
            "ends_with", "does_not_end_with",
        )

        for operator in operators:
            with self.subTest(operator=operator):
                step = {
                    "op": "conditional_column", "name": "Matched",
                    "clauses": [{
                        "column": "Customer", "operator": operator,
                        "test_value": "", "test_value_kind": "value",
                        "output": "yes", "output_kind": "value",
                    }],
                    "else_value": "no", "else_kind": "value",
                }
                script = steps_to_m_script([step], "Customers")
                parsed = parse_m_script(script, "Customers")

                self.assertEqual(m_compatibility_issues([step]), [])
                self.assertEqual(parsed, [step])
                self.assertEqual(
                    apply_transformations(source, parsed),
                    apply_transformations(source, [step]),
                )

    def test_conditional_numeric_equality_is_rejected(self) -> None:
        for operator, m_operator in (("equals", "="), ("not_equals", "<>")):
            for test_kind, right in (("value", "12.0"), ("column", "Region")):
                with self.subTest(operator=operator, test_kind=test_kind):
                    step = {
                        "op": "conditional_column", "name": "Matched",
                        "clauses": [{
                            "column": "Revenue", "operator": operator,
                            "test_value": right, "test_value_kind": test_kind,
                            "output": "yes", "output_kind": "value",
                        }],
                        "else_value": "no", "else_kind": "value",
                    }
                    steps = [
                        {"op": "convert_type", "column": "Revenue", "type": "decimal_number"},
                        {"op": "convert_type", "column": "Region", "type": "decimal_number"},
                        step,
                    ]
                    comparison = f"[{right}]" if test_kind == "column" else "12.0"
                    script = f'''let
    Source = #"Sales Data",
    Typed = Table.TransformColumnTypes(Source, {{{{"Revenue", type number}}, {{"Region", type number}}}}),
    Added = Table.AddColumn(Typed, "Matched", each if [Revenue] {m_operator} {comparison} then "yes" else "no", type text)
in
    Added'''

                    with self.assertRaisesRegex(PowerQueryMScriptError, "Numeric conditional equality"):
                        steps_to_m_script(steps, "Sales Data")
                    self.assertEqual(len(m_compatibility_issues(steps)), 1)
                    with self.assertRaisesRegex(PowerQueryMScriptError, "Numeric conditional equality"):
                        parse_m_script(script, "Sales Data")

    def test_ambiguous_text_conditional_comparisons_are_rejected(self) -> None:
        scripts = (
            '''let
    Source = #"Sales Data",
    Added = Table.AddColumn(Source, "Matched", each if [Customer] = "" then "yes" else "no", type text)
in
    Added''',
            '''let
    Source = #"Sales Data",
    Added = Table.AddColumn(Source, "Matched", each if [Customer] = [Region] then "yes" else "no", type text)
in
    Added''',
            '''let
    Source = #"Sales Data",
    Added = Table.AddColumn(Source, "Matched", each if [Customer] = null then false else Text.Contains([Customer], [Region]), type text)
in
    Added''',
            '''let
    Source = #"Sales Data",
    Added = Table.AddColumn(Source, "Matched", each if Text.Contains("abc", [Customer]) then "yes" else "no", type text)
in
    Added''',
            '''let
    Source = #"Sales Data",
    Added = Table.AddColumn(Source, "Matched", each if [Region] = "East" then (if Text.Contains("abc", [Customer]) then "yes" else "no") else "other", type text)
in
    Added''',
        )

        for script in scripts:
            with self.subTest(script=script):
                with self.assertRaisesRegex(
                    PowerQueryMScriptError,
                    "(conflates null and empty text|does not preserve nulls|same cell value|supported null guard)",
                ):
                    parse_m_script(script, "Sales Data")

        ambiguous_steps = (
            {
                "op": "conditional_column", "name": "Matched",
                "clauses": [{
                    "column": "Customer", "operator": "equals",
                    "test_value": "", "test_value_kind": "value",
                    "output": "yes", "output_kind": "value",
                }],
                "else_value": "no", "else_kind": "value",
            },
            {
                "op": "conditional_column", "name": "Matched",
                "clauses": [{
                    "column": "Customer", "operator": "contains",
                    "test_value": "Region", "test_value_kind": "column",
                    "output": "yes", "output_kind": "value",
                }],
                "else_value": "no", "else_kind": "value",
            },
        )
        for step in ambiguous_steps:
            with self.subTest(step=step):
                with self.assertRaisesRegex(PowerQueryMScriptError, "(conflates null and empty text|does not preserve nulls)"):
                    steps_to_m_script([step], "Sales Data")

    def test_locale_type_conversion_round_trips_and_replays_from_m(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Amount", "Units", "Date", "Stamp", "Clock"],
            [
                {
                    "Amount": "1.234,50", "Units": "2.000", "Date": "12/31/2024",
                    "Stamp": "12/31/2024 1:45 PM", "Clock": "1:45:30 PM",
                },
                {
                    "Amount": "2.500,25", "Units": "3.000", "Date": "01/01/2025",
                    "Stamp": "01/01/2025 12:00 AM", "Clock": "2:15 PM",
                },
            ],
            {},
            [],
        )
        script = '''let
    Source = #"Localized Sales",
    NumberTypes = Table.TransformColumnTypes(
        Source,
        {{"Amount", type number}, {"Units", Int64.Type}},
        "de-DE"),
    DateTimeTypes = Table.TransformColumnTypes(
        NumberTypes,
        {{"Date", type date}, {"Stamp", type datetime}, {"Clock", type time}},
        "en-US")
in
    DateTimeTypes'''

        parsed = parse_m_script(script, "Localized Sales")
        expected = [
            {"op": "convert_type_using_locale", "column": "Amount",
             "type": "decimal_number", "culture": "de-DE"},
            {"op": "convert_type_using_locale", "column": "Units",
             "type": "whole_number", "culture": "de-DE"},
            {"op": "convert_type_using_locale", "column": "Date",
             "type": "date", "culture": "en-US"},
            {"op": "convert_type_using_locale", "column": "Stamp",
             "type": "datetime", "culture": "en-US"},
            {"op": "convert_type_using_locale", "column": "Clock",
             "type": "time", "culture": "en-US"},
        ]
        self.assertEqual(parsed, expected)

        direct = apply_transformations(source, parsed)
        replayed = apply_transformations(source, parse_m_script(
            steps_to_m_script(parsed, "Localized Sales"), "Localized Sales"
        ))
        self.assertEqual(direct.headers, replayed.headers)
        self.assertEqual(direct.rows, replayed.rows)
        self.assertEqual(direct.rows, [
            {
                "Amount": "1234.50", "Units": "2000", "Date": "2024-12-31",
                "Stamp": "2024-12-31T13:45:00", "Clock": "13:45:30",
            },
            {
                "Amount": "2500.25", "Units": "3000", "Date": "2025-01-01",
                "Stamp": "2025-01-01T00:00:00", "Clock": "14:15:00",
            },
        ])
        self.assertEqual(
            column_types_after_steps(source.headers, parsed),
            column_types_after_steps(source.headers, parse_m_script(
                steps_to_m_script(parsed, "Localized Sales"), "Localized Sales"
            )),
        )
        uncanonical = [
            {**step, "culture": "de_de" if step["culture"] == "de-DE" else "en_us"}
            for step in parsed
        ]
        emitted = steps_to_m_script(uncanonical, "Localized Sales")
        self.assertIn('"de-DE"', emitted)
        self.assertIn('"en-US"', emitted)
        self.assertEqual(parse_m_script(emitted, "Localized Sales"), expected)
        self.assertEqual(m_compatibility_issues(parsed), [])

    def test_locale_type_conversion_rejects_unsupported_cultures_and_types(self) -> None:
        prefix = 'let Source = #"Sales Data", Typed = '
        suffix = " in Typed"
        invalid_calls = [
            ('Table.TransformColumnTypes(Source, {{"Revenue", type number}}, "zz-ZZ")', "Culture"),
            ('Table.TransformColumnTypes(Source, {{"Revenue", type text}}, "en-US")', "only supports"),
            ('Table.TransformColumnTypes(Source, {{"Revenue", type logical}}, "en-US")', "only supports"),
            ('Table.TransformColumnTypes(Source, {{"Revenue", Currency.Type}}, "en-US")', "Currency.Type"),
            ('Table.TransformColumnTypes(Source, {{"Revenue", type number}}, [Culture="en-US"])', "quoted M"),
        ]
        for call, message in invalid_calls:
            with self.subTest(call=call):
                with self.assertRaisesRegex(PowerQueryMScriptError, message):
                    parse_m_script(prefix + call + suffix, "Sales Data")

    def test_m_locale_whole_number_uses_even_rounding_and_int64_bounds(self) -> None:
        scripts = [
            '''let
    Source = #"Sales Data",
    Typed = Table.TransformColumnTypes(Source, {{"Units", Int64.Type}}, "en-US")
in
    Typed''',
            '''let
    Source = #"Sales Data",
    Typed = Table.TransformColumnTypes(Source, {{"Units", Int64.Type}})
in
    Typed''',
        ]
        step_sets = [parse_m_script(script, "Sales Data") for script in scripts]
        self.assertEqual(step_sets, [
            [{"op": "convert_type_using_locale", "column": "Units",
              "type": "whole_number", "culture": "en-US"}],
            [{"op": "convert_type", "column": "Units", "type": "whole_number"}],
        ])
        for raw, expected in (
            ("2.5", "2"), ("3.5", "4"), ("-2.5", "-2"),
            ("9223372036854775807", "9223372036854775807"),
            ("-9223372036854775808", "-9223372036854775808"),
        ):
            with self.subTest(raw=raw):
                for steps in step_sets:
                    source = ImportCandidate("inline", ["Units"], [{"Units": raw}], {}, [])
                    result = apply_transformations(source, steps)
                    self.assertEqual(result.rows[0]["Units"], expected)

        for raw in ("9223372036854775808", "-9223372036854775809"):
            with self.subTest(raw=raw):
                for steps in step_sets:
                    source = ImportCandidate("inline", ["Units"], [{"Units": raw}], {}, [])
                    with self.assertRaisesRegex(TransformationError, "to whole_number"):
                        apply_transformations(source, steps)

    def test_m_decimal_conversion_observes_double_overflow_and_underflow(self) -> None:
        scripts = [
            '''let
    Source = #"Sales Data",
    Typed = Table.TransformColumnTypes(Source, {{"Amount", type number}}, "en-US")
in
    Typed''',
            '''let
    Source = #"Sales Data",
    Typed = Table.TransformColumnTypes(Source, {{"Amount", type number}})
in
    Typed''',
        ]
        step_sets = [parse_m_script(script, "Sales Data") for script in scripts]
        self.assertEqual(step_sets, [
            [{"op": "convert_type_using_locale", "column": "Amount",
              "type": "decimal_number", "culture": "en-US"}],
            [{"op": "convert_type", "column": "Amount", "type": "decimal_number"}],
        ])

        for steps in step_sets:
            for raw in ("1E309", "-1E309"):
                source = ImportCandidate("inline", ["Amount"], [{"Amount": raw}], {}, [])
                with self.subTest(steps=steps, raw=raw):
                    with self.assertRaisesRegex(TransformationError, "to decimal_number"):
                        apply_transformations(source, steps)

            for raw, expected in (("1E-400", "0"), ("-1E-400", "-0")):
                source = ImportCandidate("inline", ["Amount"], [{"Amount": raw}], {}, [])
                with self.subTest(steps=steps, raw=raw):
                    result = apply_transformations(source, steps)
                    self.assertEqual(result.rows[0]["Amount"], expected)

    def test_table_transpose_round_trips_and_matches_local_output(self) -> None:
        steps = [{"op": "transpose_table"}]
        script = steps_to_m_script(steps, "Sales Data")
        self.assertIn("Table.Transpose", script)
        parsed = parse_m_script(script, "Sales Data")
        self.assertEqual(parsed, steps)
        self.assertEqual(m_compatibility_issues(steps), [])

        direct = apply_transformations(self.source, steps)
        replayed = apply_transformations(
            self.source, parse_m_script(steps_to_m_script(steps, "Sales Data"), "Sales Data")
        )
        self.assertEqual(direct.headers, ["Column1", "Column2"])
        self.assertEqual(direct.headers, replayed.headers)
        self.assertEqual(direct.rows, replayed.rows)
        self.assertEqual(
            column_types_after_steps(self.source.headers, steps),
            column_types_after_steps(self.source.headers, parsed),
        )

    def test_value_dependent_operations_after_transpose_are_rejected(self) -> None:
        unsupported_operations = [
            ('Grouped = Table.Group(Transposed, {"Column1"}, '
             '{{"Total", each List.Sum([Column2])}})', "Grouped"),
            ('Deduplicated = Table.Distinct(Transposed, {"Column1"})', "Deduplicated"),
            ('Filtered = Table.SelectRows(Transposed, each [Column1] = "")', "Filtered"),
        ]
        for operation, output in unsupported_operations:
            script = f'''let
    Source = #"Sales Data",
    Transposed = Table.Transpose(Source),
    {operation}
in
    {output}'''
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(
                    PowerQueryMScriptError, "distinguish null from empty text"
                ):
                    parse_m_script(script, "Sales Data")

        explicit_type_conversion = '''let
    Source = #"Sales Data",
    Transposed = Table.Transpose(Source),
    Typed = Table.TransformColumnTypes(Transposed, {{"Column1", Int64.Type}})
in
    Typed'''
        with self.subTest(operation="explicit type conversion"):
            with self.assertRaisesRegex(
                PowerQueryMScriptError, "distinguish null from empty text"
            ):
                parse_m_script(explicit_type_conversion, "Sales Data")

        safe_projection = '''let
    Source = #"Sales Data",
    Transposed = Table.Transpose(Source),
    Selected = Table.SelectColumns(Transposed, {"Column1"}),
    Limited = Table.FirstN(Selected, 1)
in
    Limited'''
        self.assertEqual(
            [step["op"] for step in parse_m_script(safe_projection, "Sales Data")],
            ["transpose_table", "keep_columns", "keep_top_rows"],
        )

    def test_generated_m_round_trips_existing_supported_steps(self) -> None:
        steps = [
            {"op": "rename_column", "column": "Region", "new_name": "Area"},
            {"op": "filter_rows", "column": "Area", "operator": "equals", "value": "East"},
            {"op": "trim_text", "column": "Customer"},
            {"op": "convert_type", "column": "Revenue", "type": "decimal_number"},
            {"op": "add_custom_column", "name": "Net", "expression": "[Revenue] * 0.9"},
        ]

        script = steps_to_m_script(steps, "Sales Data")

        self.assertEqual(parse_m_script(script, "Sales Data"), steps)
        self.assertIn('each Text.From([Revenue] * 0.9), type text)', script)
        self.assertEqual(
            apply_transformations(self.source, parse_m_script(script, "Sales Data")).rows[0]["Net"],
            "10.8",
        )

    def test_sort_and_legacy_numeric_type_round_trip_to_canonical_steps(self) -> None:
        steps = [
            {"op": "sort_rows", "column": "Revenue", "direction": "desc"},
            {"op": "convert_type", "column": "Revenue", "type": "number"},
            {"op": "sort_rows_by_columns", "sorts": [
                {"column": "Region", "direction": "asc"},
                {"column": "Revenue", "direction": "desc"},
            ]},
        ]

        script = steps_to_m_script(steps, "Sales Data")
        parsed = parse_m_script(script, "Sales Data")

        self.assertEqual(parsed, [
            {"op": "sort_rows_by_columns", "sorts": [
                {"column": "Revenue", "direction": "desc"},
            ]},
            {"op": "convert_type", "column": "Revenue", "type": "decimal_number"},
            {"op": "sort_rows_by_columns", "sorts": [
                {"column": "Region", "direction": "asc"},
                {"column": "Revenue", "direction": "desc"},
            ]},
        ])
        self.assertEqual(m_compatibility_issues(steps), [])

    def test_table_sort_accepts_default_and_mixed_column_criteria(self) -> None:
        script = '''let
    Source = #"Sales Data",
    Sorted = Table.Sort(Source, {{"Region", Order.Descending}, "Revenue"})
in
    Sorted'''

        self.assertEqual(parse_m_script(script, "Sales Data"), [{
            "op": "sort_rows_by_columns", "sorts": [
                {"column": "Region", "direction": "desc"},
                {"column": "Revenue", "direction": "asc"},
            ],
        }])

    def test_sort_and_rename_reject_nonstandard_m_identifiers(self) -> None:
        invalid_sort = '''let
    Source = #"Sales Data",
    Sorted = Table.Sort(Source, {{"Region", "Ascending"}})
in
    Sorted'''
        invalid_rename = '''let
    Source = #"Sales Data",
    Renamed = Table.RenameColumns(Source, {{"Region", Area}})
in
    Renamed'''

        with self.assertRaisesRegex(PowerQueryMScriptError, "Order.Ascending"):
            parse_m_script(invalid_sort, "Sales Data")
        with self.assertRaisesRegex(PowerQueryMScriptError, "quoted"):
            parse_m_script(invalid_rename, "Sales Data")

    def test_custom_column_preserves_a_declared_numeric_type(self) -> None:
        script = '''let
    Source = #"Sales Data",
    Typed = Table.TransformColumnTypes(Source, {{"Revenue", Int64.Type}}),
    Added = Table.AddColumn(Typed, "Net", each [Revenue] * 0.9, type number)
in
    Added'''

        steps = [
            {"op": "convert_type", "column": "Revenue", "type": "whole_number"},
            {
                "op": "add_custom_column", "name": "Net",
                "expression": "[Revenue] * 0.9", "output_type": "decimal_number",
            },
        ]
        parsed = parse_m_script(script, "Sales Data")
        self.assertEqual(parsed, steps)
        self.assertEqual(
            parse_m_script(steps_to_m_script(steps, "Sales Data"), "Sales Data"),
            steps,
        )
        source = ImportCandidate(
            "inline", ["Revenue"], [{"Revenue": "10"}, {"Revenue": "25"}], {}, [],
        )
        self.assertEqual(
            apply_transformations(source, parsed),
            apply_transformations(source, steps),
        )

    def test_m_custom_column_requires_a_text_producing_expression(self) -> None:
        for expression, declared_type in (("[Revenue]", ""), ("[Revenue] * 0.9", ", type text")):
            script = "\n".join([
                "let",
                '    Source = #"Sales Data",',
                '    Typed = Table.TransformColumnTypes(Source, {{"Revenue", Int64.Type}}),',
                f'    Added = Table.AddColumn(Typed, "Calc", each {expression}{declared_type}),',
                '    Split = Table.SplitColumn(Added, "Calc", '
                'Splitter.SplitTextByEachDelimiter({":"}, QuoteStyle.None), '
                '{"Calc.1", "Calc.2"}, "")',
                "in",
                "    Split",
            ])
            with self.subTest(expression=expression, declared_type=declared_type):
                with self.assertRaisesRegex(PowerQueryMScriptError, "must produce text"):
                    parse_m_script(script, "Sales Data")

        explicitly_text = "\n".join([
            "let",
            '    Source = #"Sales Data",',
            '    Typed = Table.TransformColumnTypes(Source, {{"Revenue", Int64.Type}}),',
            '    Added = Table.AddColumn(Typed, "Calc", each Text.From([Revenue])),',
            '    Split = Table.SplitColumn(Added, "Calc", '
            'Splitter.SplitTextByEachDelimiter({":"}, QuoteStyle.None), '
            '{"Calc.1", "Calc.2"}, "")',
            "in",
            "    Split",
        ])
        self.assertEqual(
            parse_m_script(explicitly_text, "Sales Data")[-2:],
            [
                {"op": "add_custom_column", "name": "Calc", "expression": "[Revenue]"},
                {"op": "split_column", "column": "Calc", "delimiter": ":"},
            ],
        )

    def test_m_text_cast_does_not_hide_an_invalid_nested_expression(self) -> None:
        script = "\n".join([
            "let",
            '    Source = #"Sales Data",',
            '    Typed = Table.TransformColumnTypes(Source, {{"Revenue", type text}}),',
            '    Added = Table.AddColumn(Typed, "Calc", '
            'each Text.From(Number.Abs([Revenue]))),',
            '    Split = Table.SplitColumn(Added, "Calc", '
            'Splitter.SplitTextByEachDelimiter({":"}, QuoteStyle.None), '
            '{"Calc.1", "Calc.2"}, "")',
            "in",
            "    Split",
        ])
        with self.assertRaisesRegex(PowerQueryMScriptError, "must produce text"):
            parse_m_script(script, "Sales Data")

    def test_m_expression_type_checks_known_arguments_alongside_unknown_fields(self) -> None:
        invalid_expressions = [
            'Text.From(Number.Round(1, "2"))',
            'Text.From(Number.Round(1, null))',
            'Text.From(Text.Replace("a", 1, [X]))',
            'Text.From(Text.Replace("a", null, [X]))',
            'Text.From(Text.Replace("a", "a", Text.From(null)))',
            'Text.From(Text.Contains([X], 1))',
            'Text.From(Text.Contains([X], null))',
            'Text.From(Text.StartsWith([X], 1))',
            'Text.From(Text.StartsWith([X], null))',
            'Text.From(Text.EndsWith([X], 1))',
            'Text.From(Text.EndsWith([X], null))',
            'Text.From(if null then "a" else "b")',
            'Text.From(if Number.Abs(null) then "a" else "b")',
        ]
        for expression in invalid_expressions:
            script = "\n".join([
                "let",
                '    Source = #"Sales Data",',
                "    Promoted = Table.PromoteHeaders(Source),",
                f'    Added = Table.AddColumn(Promoted, "Calc", each {expression})',
                "in",
                "    Added",
            ])
            with self.subTest(expression=expression):
                with self.assertRaisesRegex(PowerQueryMScriptError, "must produce text"):
                    parse_m_script(script, "Sales Data")

        valid = '''let
    Source = #"Sales Data",
    Added = Table.AddColumn(Source, "Calc", each Text.From(Number.Round(1.234, 2)))
in
    Added'''
        self.assertEqual(
            parse_m_script(valid, "Sales Data"),
            [{"op": "add_custom_column", "name": "Calc", "expression": "Number.Round(1.234, 2)"}],
        )

        nullable_arguments = '''let
    Source = #"Sales Data",
    Promoted = Table.PromoteHeaders(Source),
    Added = Table.AddColumn(Promoted, "Calc", each Text.From(Text.Replace(null, "a", [X])))
in
    Added'''
        self.assertEqual(
            parse_m_script(nullable_arguments, "Sales Data")[-1]["expression"],
            'Text.Replace(null, "a", [X])',
        )

        null_result = '''let
    Source = #"Sales Data",
    Added = Table.AddColumn(Source, "Calc", each Text.From(null))
in
    Added'''
        null_steps = parse_m_script(null_result, "Sales Data")
        self.assertEqual(null_steps[-1]["expression"], "null")
        self.assertEqual(
            [row["Calc"] for row in apply_transformations(self.source, null_steps).rows],
            ["", ""],
        )

    def test_custom_column_text_clean_round_trips_control_characters_and_null(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Customer"],
            [
                {"Customer": "A\x01B\x7f\u0085C\u200bD"},
                {"Customer": ""},
            ],
            {},
            [],
        )
        step = {
            "op": "add_custom_column",
            "name": "Cleaned",
            "expression": "Text.Clean([Customer])",
        }
        source_types = {"Customer": "text"}
        script = steps_to_m_script(
            [step], "Customers", initial_column_types=source_types
        )
        parsed = parse_m_script(
            script, "Customers", initial_column_types=source_types
        )
        direct = apply_transformations(source, [step])
        through_m = apply_transformations(source, parsed)

        self.assertIn("Text.Clean([Customer])", script)
        self.assertEqual(parsed, [step])
        self.assertEqual(through_m, direct)
        self.assertEqual(
            [row["Cleaned"] for row in through_m.rows], ["ABC\u200bD", ""]
        )
        self.assertEqual(
            column_types_after_steps(
                source.headers, parsed, output_headers=through_m.headers,
                initial_types=source_types,
            ),
            column_types_after_steps(
                source.headers, [step], output_headers=direct.headers,
                initial_types=source_types,
            ),
        )
        self.assertTrue(m_script_matches_steps(
            script, "Customers", [step], initial_column_types=source_types
        ))
        self.assertIsNone(
            evaluate_expression(compile_expression("Text.Clean(null)"), {})
        )

    def test_text_transform_rejects_a_declared_non_text_output_type(self) -> None:
        script = '''let
    Source = #"Sales Data",
    Changed = Table.TransformColumns(Source, {{"Revenue", Text.Trim, type number}})
in
    Changed'''

        with self.assertRaisesRegex(PowerQueryMScriptError, "non-text output type"):
            parse_m_script(script, "Sales Data")

    def test_add_index_column_uses_m_optional_defaults(self) -> None:
        script = '''let
    Source = #"Sales Data",
    Indexed = Table.AddIndexColumn(Source, "Index")
in
    Indexed'''

        self.assertEqual(parse_m_script(script, "Sales Data"), [{
            "op": "add_index_column", "new_name": "Index", "start": 0, "increment": 1,
        }])
        signed_steps = [{
            "op": "add_index_column", "new_name": "Sequence", "start": -2, "increment": -3,
        }]
        signed_script = steps_to_m_script(signed_steps, "Sales Data")
        self.assertEqual(parse_m_script(signed_script, "Sales Data"), signed_steps)
        self.assertEqual(
            apply_transformations(self.source, parse_m_script(signed_script, "Sales Data")),
            apply_transformations(self.source, signed_steps),
        )

    def test_table_group_aggregations_round_trip_and_match_local_output(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Region", "Net sales", "Customer"],
            [
                {"Region": "East", "Net sales": "12", "Customer": "Ada"},
                {"Region": "East", "Net sales": "12", "Customer": "Ada"},
                {"Region": "East", "Net sales": "20", "Customer": "Lin"},
                {"Region": "West", "Net sales": "5", "Customer": "Sam"},
            ],
            {},
            [],
        )
        step = {
            "op": "group_by",
            "columns": ["Region"],
            "aggregations": [
                {"operation": "sum", "column": "Net sales", "new_name": "Total"},
                {"operation": "average", "column": "Net sales", "new_name": "Average"},
                {"operation": "median", "column": "Net sales", "new_name": "Median"},
                {"operation": "min", "column": "Net sales", "new_name": "Minimum"},
                {"operation": "max", "column": "Net sales", "new_name": "Maximum"},
                {"operation": "count_rows", "new_name": "Rows"},
                {"operation": "count_distinct_rows", "new_name": "Unique rows"},
                {
                    "operation": "count_distinct_values",
                    "column": "Customer",
                    "new_name": "Customers",
                },
            ],
        }

        script = steps_to_m_script([step], "Sales Data")
        parsed = parse_m_script(script, "Sales Data")
        direct = apply_transformations(source, [step])
        through_m = apply_transformations(source, parsed)

        self.assertIn("Table.Group", script)
        self.assertIn('List.Sum([#"Net sales"])', script)
        self.assertEqual(parsed, [step])
        self.assertEqual(through_m, direct)
        self.assertEqual(
            through_m.rows,
            [
                {
                    "Region": "East", "Total": "44", "Average": "14.66666666666666666666666667",
                    "Median": "12", "Minimum": "12", "Maximum": "20", "Rows": "3",
                    "Unique rows": "2", "Customers": "2",
                },
                {
                    "Region": "West", "Total": "5", "Average": "5", "Median": "5",
                    "Minimum": "5", "Maximum": "5", "Rows": "1", "Unique rows": "1",
                    "Customers": "1",
                },
            ],
        )
        self.assertEqual(
            column_types_after_steps(source.headers, parsed, output_headers=through_m.headers),
            column_types_after_steps(source.headers, [step], output_headers=direct.headers),
        )
        self.assertEqual(m_compatibility_issues([step]), [])

    def test_table_unpivot_forms_round_trip_and_match_local_output(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Region", "2024", "2025"],
            [
                {"Region": "East", "2024": "10", "2025": "15"},
                {"Region": "West", "2024": "7", "2025": "9"},
            ],
            {},
            [],
        )
        cases = [
            {
                "op": "unpivot_columns",
                "columns": ["2024", "2025"],
                "attribute_name": "Year",
                "value_name": "Sales",
            },
            {
                "op": "unpivot_other_columns",
                "columns": ["Region"],
                "attribute_name": "Year",
                "value_name": "Sales",
            },
        ]

        for step in cases:
            with self.subTest(operation=step["op"]):
                script = steps_to_m_script([step], "Sales Data")
                parsed = parse_m_script(script, "Sales Data")
                direct = apply_transformations(source, [step])
                through_m = apply_transformations(source, parsed)
                self.assertIn(
                    "Table.UnpivotOtherColumns" if step["op"] == "unpivot_other_columns"
                    else "Table.Unpivot",
                    script,
                )
                self.assertEqual(parsed, [step])
                self.assertEqual(through_m, direct)
                self.assertEqual(
                    column_types_after_steps(source.headers, parsed, output_headers=through_m.headers),
                    column_types_after_steps(source.headers, [step], output_headers=direct.headers),
                )
                self.assertEqual(m_compatibility_issues([step]), [])

    def test_table_pivot_aggregations_round_trip_from_dynamic_values(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Region", "Year", "Sales"],
            [
                {"Region": "East", "Year": "2024", "Sales": "10"},
                {"Region": "East", "Year": "2024", "Sales": "5"},
                {"Region": "East", "Year": "2025", "Sales": "15"},
                {"Region": "West", "Year": "2024", "Sales": "7"},
                {"Region": "West", "Year": "2025", "Sales": "9"},
            ],
            {},
            [],
        )
        for aggregation in (
            "sum", "average", "median", "min", "max", "count_all", "count_non_blank",
        ):
            with self.subTest(aggregation=aggregation):
                step = {
                    "op": "pivot_column",
                    "attribute_column": "Year",
                    "value_column": "Sales",
                    "aggregation": aggregation,
                }
                script = steps_to_m_script([step], "Sales Data")
                parsed = parse_m_script(script, "Sales Data")
                direct = apply_transformations(source, [step])
                through_m = apply_transformations(source, parsed)
                self.assertIn("List.Distinct(Table.Column", script)
                self.assertEqual(parsed, [step])
                self.assertEqual(through_m, direct)
                self.assertEqual(
                    column_types_after_steps(source.headers, parsed, output_headers=through_m.headers),
                    column_types_after_steps(source.headers, [step], output_headers=direct.headers),
                )
                if aggregation in {"count_all", "count_non_blank"}:
                    types = column_types_after_steps(
                        source.headers, parsed, output_headers=through_m.headers
                    )
                    self.assertEqual(types["2024"], "whole_number")
                    self.assertEqual(types["2025"], "whole_number")
                self.assertEqual(m_compatibility_issues([step]), [])

        unique_source = ImportCandidate(
            "inline",
            ["Region", "Year", "Sales"],
            [
                {"Region": "East", "Year": "2024", "Sales": "10"},
                {"Region": "East", "Year": "2025", "Sales": "15"},
            ],
            {},
            [],
        )
        no_aggregation = {
            "op": "pivot_column",
            "attribute_column": "Year",
            "value_column": "Sales",
            "aggregation": "none",
        }
        script = steps_to_m_script([no_aggregation], "Sales Data")
        self.assertEqual(parse_m_script(script, "Sales Data"), [no_aggregation])
        self.assertEqual(
            apply_transformations(unique_source, parse_m_script(script, "Sales Data")),
            apply_transformations(unique_source, [no_aggregation]),
        )

    def test_table_pivot_count_non_blank_preserves_local_blank_semantics(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Region", "Year", "Sales"],
            [
                {"Region": "A", "Year": "2024", "Sales": "10"},
                {"Region": "A", "Year": "2024", "Sales": ""},
                {"Region": "A", "Year": "2024", "Sales": "0"},
                {"Region": "A", "Year": "2024", "Sales": "   "},
                {"Region": "A", "Year": "2025", "Sales": ""},
                {"Region": "B", "Year": "2024", "Sales": ""},
                {"Region": "B", "Year": "2025", "Sales": "9"},
                {"Region": "B", "Year": "2025", "Sales": "9"},
                {"Region": "C", "Year": "2025", "Sales": "6"},
                {"Region": "D", "Year": "2024", "Sales": "5"},
            ],
            {},
            [],
        )
        step = {
            "op": "pivot_column",
            "attribute_column": "Year",
            "value_column": "Sales",
            "aggregation": "count_non_blank",
        }
        script = steps_to_m_script([step], "Sales Data")
        parsed = parse_m_script(script, "Sales Data")
        direct = apply_transformations(source, [step])
        through_m = apply_transformations(source, parsed)

        self.assertIn(
            'each List.Count(List.RemoveItems(_, {null, ""}))', script
        )
        self.assertEqual(parsed, [step])
        self.assertEqual(through_m, direct)
        self.assertEqual(direct.headers, ["Region", "2024", "2025"])
        self.assertEqual(
            direct.rows,
            [
                {"Region": "A", "2024": "3", "2025": "0"},
                {"Region": "B", "2024": "0", "2025": "2"},
                {"Region": "C", "2024": "", "2025": "1"},
                {"Region": "D", "2024": "1", "2025": ""},
            ],
        )
        self.assertEqual(
            column_types_after_steps(source.headers, parsed, output_headers=through_m.headers),
            {"Region": "text", "2024": "whole_number", "2025": "whole_number"},
        )
        self.assertEqual(m_compatibility_issues([step]), [])

    def test_table_pivot_count_non_blank_rejects_noncanonical_m_lambdas(self) -> None:
        reversed_values = '''let
    Source = #"Sales Data",
    Pivoted = Table.Pivot(Source, List.Distinct(Table.Column(Source, "Year")), "Year", "Sales", each List.Count(List.RemoveItems(_, {"", null})))
in
    Pivoted'''
        other_blank = '''let
    Source = #"Sales Data",
    Pivoted = Table.Pivot(Source, List.Distinct(Table.Column(Source, "Year")), "Year", "Sales", each List.Count(List.RemoveItems(_, {null, " "})))
in
    Pivoted'''
        uppercase_each = '''let
    Source = #"Sales Data",
    Pivoted = Table.Pivot(Source, List.Distinct(Table.Column(Source, "Year")), "Year", "Sales", EACH List.Count(List.RemoveItems(_, {null, ""})))
in
    Pivoted'''

        for script in (reversed_values, other_blank, uppercase_each):
            with self.subTest(script=script):
                with self.assertRaisesRegex(PowerQueryMScriptError, "aggregation"):
                    parse_m_script(script, "Sales Data")

    def test_pivot_count_types_follow_promoted_header_key_columns(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Column1", "Column2", "Column3"],
            [
                {"Column1": "Region", "Column2": "Year", "Column3": "Sales"},
                {"Column1": "East", "Column2": "2024", "Column3": "10"},
                {"Column1": "West", "Column2": "2025", "Column3": "20"},
            ],
            {},
            [],
        )
        steps = [
            {"op": "promote_headers"},
            {
                "op": "pivot_column",
                "attribute_column": "Year",
                "value_column": "Sales",
                "aggregation": "count_non_blank",
            },
        ]
        script = steps_to_m_script(steps, "Sales Data")
        parsed = parse_m_script(script, "Sales Data")
        result = apply_transformations(source, parsed)

        self.assertEqual(result.headers, ["Region", "2024", "2025"])
        self.assertEqual(
            column_types_after_steps(
                source.headers, parsed, output_headers=result.headers
            ),
            {"Region": "text", "2024": "whole_number", "2025": "whole_number"},
        )

    def test_table_pivot_rejects_static_or_unrelated_category_values(self) -> None:
        static = '''let
    Source = #"Sales Data",
    Pivoted = Table.Pivot(Source, {"2024", "2025"}, "Year", "Sales", List.Sum)
in
    Pivoted'''
        unrelated = '''let
    Source = #"Sales Data",
    Pivoted = Table.Pivot(Source, List.Distinct(Table.Column(Source, "Region")), "Year", "Sales", List.Sum)
in
    Pivoted'''

        with self.assertRaisesRegex(PowerQueryMScriptError, "derive its category list"):
            parse_m_script(static, "Sales Data")
        with self.assertRaisesRegex(PowerQueryMScriptError, "current step's attribute column"):
            parse_m_script(unrelated, "Sales Data")

    def test_row_window_m_functions_round_trip_to_local_steps(self) -> None:
        cases = [
            ({"op": "remove_bottom_rows", "count": 1}, "Table.RemoveLastN"),
            ({"op": "keep_range_rows", "first_row": 2, "count": 1}, "Table.Range"),
            ({
                "op": "remove_alternate_rows",
                "first_row_to_remove": 2,
                "remove_count": 1,
                "keep_count": 1,
            }, "Table.AlternateRows"),
        ]
        for step, function in cases:
            with self.subTest(operation=step["op"]):
                script = steps_to_m_script([step], "Sales Data")
                parsed = parse_m_script(script, "Sales Data")
                direct = apply_transformations(self.source, [step])
                through_m = apply_transformations(self.source, parsed)

                self.assertIn(function, script)
                self.assertEqual(parsed, [step])
                self.assertEqual(through_m, direct)
                self.assertEqual(m_compatibility_issues([step]), [])
                self.assertEqual(
                    column_types_after_steps(
                        self.source.headers, parsed, output_headers=through_m.headers
                    ),
                    column_types_after_steps(
                        self.source.headers, [step], output_headers=direct.headers
                    ),
                )

    def test_row_window_m_functions_follow_m_optional_argument_behavior(self) -> None:
        remove_last_default = '''let
    Source = #"Sales Data",
    Rows = Table.RemoveLastN(Source)
in
    Rows'''
        range_without_count = '''let
    Source = #"Sales Data",
    Rows = Table.Range(Source, 1)
in
    Rows'''
        range_with_null_count = '''let
    Source = #"Sales Data",
    Rows = Table.Range(Source, 1, null)
in
    Rows'''

        self.assertEqual(parse_m_script(remove_last_default, "Sales Data"), [
            {"op": "remove_bottom_rows", "count": 1},
        ])
        self.assertEqual(parse_m_script(range_without_count, "Sales Data"), [
            {"op": "keep_range_rows", "first_row": 2, "count": MAX_DATA_ROWS},
        ])
        self.assertEqual(
            parse_m_script(range_with_null_count, "Sales Data"),
            parse_m_script(range_without_count, "Sales Data"),
        )

    def test_remove_blank_rows_round_trips_and_removes_only_null_and_empty_cells(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Region", "Revenue"],
            [
                {"Region": "", "Revenue": ""},
                {"Region": "East", "Revenue": ""},
                {"Region": "", "Revenue": "12"},
                {"Region": " ", "Revenue": ""},
            ],
            {},
            [],
        )
        step = {"op": "remove_blank_rows"}
        script = steps_to_m_script([step], "Sales Data")
        parsed = parse_m_script(script, "Sales Data")
        formatted = '''let
    Source = #"Sales Data",
    Filtered = Table.SelectRows(
        Source,
        each not List.IsEmpty(
            List.RemoveMatchingItems(Record.FieldValues(_), {null, ""})
        )
    )
in
    Filtered'''
        removes_space_value = '''let
    Source = #"Sales Data",
    Filtered = Table.SelectRows(
        Source,
        each not List.IsEmpty(List.RemoveMatchingItems(Record.FieldValues(_), {null, " "}))
    )
in
    Filtered'''
        direct = apply_transformations(source, [step])
        through_m = apply_transformations(source, parsed)

        self.assertIn("List.RemoveMatchingItems", script)
        self.assertEqual(parsed, [step])
        self.assertEqual(parse_m_script(formatted, "Sales Data"), [step])
        with self.assertRaises(PowerQueryMScriptError):
            parse_m_script(removes_space_value, "Sales Data")
        self.assertEqual(through_m, direct)
        self.assertEqual(len(through_m.rows), 3)
        self.assertEqual(m_compatibility_issues([step]), [])

    def test_delimiter_text_transforms_round_trip_and_match_local_output(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Code", "Note"],
            [
                {"Code": "a/b/c/d", "Note": "one [A] mid [B] end"},
                {"Code": "", "Note": ""},
            ],
            {},
            [],
        )
        cases = [
            {
                "op": "extract_text_by_delimiter", "column": "Code",
                "side": "before", "delimiter": "/", "occurrence": 1,
            },
            {
                "op": "extract_text_by_delimiter", "column": "Code",
                "side": "after", "delimiter": "/", "occurrence": 1,
            },
            {
                "op": "extract_text_between_delimiters", "column": "Note",
                "start_delimiter": "[", "end_delimiter": "]",
                "start_occurrence": 1, "end_occurrence": 0,
            },
            {
                "op": "extract_text_between_delimiters", "column": "Note",
                "start_delimiter": "[", "end_delimiter": "]",
                "start_occurrence": 0, "end_occurrence": 1,
            },
        ]

        for step in cases:
            with self.subTest(operation=step["op"], side=step.get("side")):
                script = steps_to_m_script([step], "Sales Data")
                parsed = parse_m_script(script, "Sales Data")
                direct = apply_transformations(source, [step])
                through_m = apply_transformations(source, parsed)
                self.assertEqual(parsed, [step])
                self.assertEqual(through_m, direct)
                self.assertEqual(
                    column_types_after_steps(source.headers, parsed, output_headers=through_m.headers),
                    column_types_after_steps(source.headers, [step], output_headers=direct.headers),
                )
                self.assertEqual(m_compatibility_issues([step]), [])
                if step["op"] == "extract_text_between_delimiters":
                    self.assertEqual(
                        through_m.rows[0]["Note"],
                        "B" if step["start_occurrence"] == 1 else "A] mid [B",
                    )

    def test_m_delimiter_extraction_guards_empty_values_and_rejects_from_end_indices(self) -> None:
        step = {
            "op": "extract_text_by_delimiter", "column": "Code",
            "side": "before", "delimiter": "||", "occurrence": 1,
        }
        source = ImportCandidate(
            "inline", ["Code"], [{"Code": ""}, {"Code": "a||b||c"}], {}, [],
        )
        script = steps_to_m_script([step], "Sales Data")
        self.assertIn(
            'if _ = null or _ = "" then "" else Text.BeforeDelimiter(_, "||", 1)',
            script,
        )
        result = apply_transformations(source, parse_m_script(script, "Sales Data"))
        self.assertEqual([row["Code"] for row in result.rows], ["", "a||b"])

        missing = ImportCandidate("inline", ["Code"], [{"Code": "plain text"}], {}, [],)
        with self.assertRaisesRegex(TransformationError, "Could not find zero-based delimiter"):
            apply_transformations(missing, parse_m_script(script, "Sales Data"))

        unguarded = '''let
    Source = #"Sales Data",
    Extracted = Table.TransformColumns(Source, {{"Code", each Text.BeforeDelimiter(_, "||", 1), type text}})
in
    Extracted'''
        relative_from_end = '''let
    Source = #"Sales Data",
    Extracted = Table.TransformColumns(Source, {{"Code", each if _ = null or _ = "" then "" else Text.BeforeDelimiter(_, "||", {1, RelativePosition.FromEnd}), type text}})
in
    Extracted'''
        with self.assertRaisesRegex(PowerQueryMScriptError, "normalize null and empty"):
            parse_m_script(unguarded, "Sales Data")
        with self.assertRaisesRegex(PowerQueryMScriptError, "whole-number argument"):
            parse_m_script(relative_from_end, "Sales Data")

    def test_split_column_shapes_round_trip_and_match_local_output(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Code", "Region"],
            [
                {"Code": "a:b:c", "Region": "East"},
                {"Code": "only", "Region": "West"},
                {"Code": "", "Region": "North"},
                {"Code": ":b", "Region": "South"},
                {"Code": "a:", "Region": "Central"},
                {"Code": "a::c:", "Region": "Coast"},
            ],
            {},
            [],
        )
        cases = [
            {"op": "split_column", "column": "Code", "delimiter": ":"},
            {"op": "split_column_by_each_delimiter", "column": "Code", "delimiter": ":"},
            {"op": "split_column_to_rows", "column": "Code", "delimiter": ":"},
            {"op": "split_column_by_positions", "column": "Code", "positions": [0, 2, 5]},
        ]

        for step in cases:
            with self.subTest(operation=step["op"]):
                script = steps_to_m_script([step], "Sales Data")
                parsed = parse_m_script(script, "Sales Data")
                direct = apply_transformations(source, [step])
                through_m = apply_transformations(source, parsed)
                self.assertEqual(parsed, [step])
                self.assertEqual(through_m, direct)
                self.assertEqual(
                    column_types_after_steps(source.headers, parsed, output_headers=through_m.headers),
                    column_types_after_steps(source.headers, [step], output_headers=direct.headers),
                )
                self.assertEqual(m_compatibility_issues([step]), [])
                if step["op"] == "split_column_to_rows":
                    self.assertIn(
                        'Text.Split(if _ = null then "" else _, ":")',
                        script,
                    )
                elif step["op"] == "split_column_by_each_delimiter":
                    self.assertIn(
                        'Text.Split(if _ = null then "" else _, ":")',
                        script,
                    )

        first_split = apply_transformations(source, [cases[0]])
        self.assertEqual(first_split.headers, ["Code.1", "Code.2", "Region"])
        self.assertEqual(first_split.rows[0], {"Code.1": "a", "Code.2": "b:c", "Region": "East"})
        self.assertEqual(first_split.rows[3], {"Code.1": "", "Code.2": "b", "Region": "South"})
        self.assertEqual(first_split.rows[4], {"Code.1": "a", "Code.2": "", "Region": "Central"})

        all_split = apply_transformations(source, [cases[1]])
        self.assertEqual(all_split.headers, ["Code.1", "Code.2", "Code.3", "Code.4", "Region"])
        self.assertEqual(
            all_split.rows[-1],
            {"Code.1": "a", "Code.2": "", "Code.3": "c", "Code.4": "", "Region": "Coast"},
        )

        row_split = apply_transformations(source, [cases[2]])
        self.assertEqual(
            [row["Code"] for row in row_split.rows[-4:]],
            ["a", "", "c", ""],
        )

        position_split = apply_transformations(source, [cases[3]])
        self.assertEqual(
            position_split.headers,
            ["Code.1", "Code.2", "Code.3", "Region"],
        )
        self.assertEqual(position_split.rows[0], {
            "Code.1": "a:", "Code.2": "b:c", "Code.3": "", "Region": "East",
        })
        self.assertIn(
            "Splitter.SplitTextByPositions({0, 2, 5})",
            steps_to_m_script([cases[3]], "Sales Data"),
        )

        wider = ImportCandidate(
            "inline", ["Code"], [{"Code": "p:q:r:s:t"}], {}, [],
        )
        wider_m = apply_transformations(wider, parse_m_script(
            steps_to_m_script([cases[1]], "Sales Data"), "Sales Data"
        ))
        self.assertEqual(wider_m.headers, [f"Code.{index}" for index in range(1, 6)])
        empty = ImportCandidate("inline", ["Code"], [], {}, [],)
        empty_m = apply_transformations(empty, parse_m_script(
            steps_to_m_script([cases[1]], "Sales Data"), "Sales Data"
        ))
        self.assertEqual(empty_m.headers, ["Code.1", "Code.2"])

        composed = [
            {"op": "rename_column", "column": "Code", "new_name": "Product Code"},
            {"op": "split_column_by_each_delimiter", "column": "Product Code", "delimiter": ":"},
        ]
        self.assertEqual(m_compatibility_issues(composed), [])
        self.assertEqual(
            apply_transformations(source, parse_m_script(
                steps_to_m_script(composed, "Sales Data"), "Sales Data"
            )),
            apply_transformations(source, composed),
        )

    def test_m_positional_split_rejects_unsupported_positions_and_column_names(self) -> None:
        wrong_names = (
            "let\n"
            '    Source = #"Sales Data",\n'
            '    Split = Table.SplitColumn(Source, "Code", Splitter.SplitTextByPositions({0, 3}), {"Left", "Right"}, "")\n'
            "in\n    Split"
        )
        invalid_positions = (
            "let\n"
            '    Source = #"Sales Data",\n'
            '    Split = Table.SplitColumn(Source, "Code", Splitter.SplitTextByPositions({1, 3}), {"Code.1", "Code.2"}, "")\n'
            "in\n    Split"
        )

        with self.assertRaisesRegex(PowerQueryMScriptError, "numbered output column names"):
            parse_m_script(wrong_names, "Sales Data")
        with self.assertRaisesRegex(PowerQueryMScriptError, "start at 0"):
            parse_m_script(invalid_positions, "Sales Data")

    def test_merge_columns_round_trips_and_matches_local_output(self) -> None:
        source = ImportCandidate(
            "inline",
            ["First", "Region", "Last"],
            [
                {"First": '"Ada, Inc."', "Region": "East", "Last": "Lovelace"},
                {"First": "Lin", "Region": "West", "Last": ""},
            ],
            {},
            [],
        )
        step = {
            "op": "merge_columns", "columns": ["Last", "First"],
            "separator": ", ", "new_name": "Full name",
        }
        script = steps_to_m_script([step], "Sales Data")
        parsed = parse_m_script(script, "Sales Data")
        direct = apply_transformations(source, [step])
        through_m = apply_transformations(source, parsed)

        self.assertIn("Table.CombineColumns", script)
        self.assertEqual(parsed, [step])
        self.assertEqual(through_m, direct)
        self.assertEqual(through_m.headers, ["Full name", "Region"])
        self.assertEqual(through_m.rows[0]["Full name"], 'Lovelace, "Ada, Inc."')
        self.assertEqual(through_m.rows[1]["Full name"], ", Lin")
        self.assertEqual(
            column_types_after_steps(source.headers, parsed, output_headers=through_m.headers),
            column_types_after_steps(source.headers, [step], output_headers=direct.headers),
        )
        self.assertEqual(m_compatibility_issues([step]), [])

        no_separator = {
            "op": "merge_columns", "columns": ["First", "Last"],
            "separator": "", "new_name": "Combined",
        }
        no_separator_script = steps_to_m_script([no_separator], "Sales Data")
        self.assertEqual(parse_m_script(no_separator_script, "Sales Data"), [no_separator])
        self.assertEqual(
            apply_transformations(source, parse_m_script(no_separator_script, "Sales Data")),
            apply_transformations(source, [no_separator]),
        )

    def test_m_text_operations_reject_non_text_input_and_fixed_dynamic_split_width(self) -> None:
        typed_then_split = '''let
    Source = #"Sales Data",
    Typed = Table.TransformColumnTypes(Source, {{"Code", Int64.Type}}),
    Split = Table.SplitColumn(
        Typed,
        "Code",
        Splitter.SplitTextByEachDelimiter({":"}, QuoteStyle.None),
        {"Code.1", "Code.2"},
        ""
    )
in
    Split'''
        fixed_dynamic_width = '''let
    Source = #"Sales Data",
    Split = Table.SplitColumn(
        Source,
        "Code",
        Splitter.SplitTextByDelimiter(":", QuoteStyle.None),
        4,
        ""
    )
in
    Split'''
        with self.assertRaisesRegex(PowerQueryMScriptError, "remain text-typed"):
            parse_m_script(typed_then_split, "Sales Data")
        with self.assertRaisesRegex(PowerQueryMScriptError, "derive its output width"):
            parse_m_script(fixed_dynamic_width, "Sales Data")

    def test_m_text_operations_reject_unpivoted_numeric_values_and_pivot_outputs(self) -> None:
        numeric_unpivot = '''let
    Source = #"Sales Data",
    Typed = Table.TransformColumnTypes(Source, {{"Revenue", Int64.Type}}),
    Unpivoted = Table.Unpivot(Typed, {"Revenue"}, "Attribute", "Value"),
    Split = Table.SplitColumn(
        Unpivoted,
        "Value",
        Splitter.SplitTextByEachDelimiter({":"}, QuoteStyle.None),
        {"Value.1", "Value.2"},
        ""
    )
in
    Split'''
        pivot_then_split = [
            {
                "op": "pivot_column", "attribute_column": "Year",
                "value_column": "Revenue", "aggregation": "sum",
            },
            {"op": "split_column", "column": "2026", "delimiter": ":"},
        ]

        with self.assertRaisesRegex(PowerQueryMScriptError, "remain text-typed"):
            parse_m_script(numeric_unpivot, "Sales Data")
        with self.assertRaisesRegex(PowerQueryMScriptError, "after Pivot"):
            steps_to_m_script(pivot_then_split, "Sales Data")

        promoted_then_split = [
            {"op": "promote_headers"},
            {"op": "split_column", "column": "Code", "delimiter": ":"},
        ]
        with self.assertRaisesRegex(PowerQueryMScriptError, "explicit text conversion"):
            steps_to_m_script(promoted_then_split, "Sales Data")
        promoted_cast_then_split = [
            {"op": "promote_headers"},
            {"op": "convert_type", "column": "Code", "type": "text"},
            {"op": "split_column", "column": "Code", "delimiter": ":"},
        ]
        promoted_script = steps_to_m_script(promoted_cast_then_split, "Sales Data")
        self.assertEqual(
            parse_m_script(promoted_script, "Sales Data"),
            promoted_cast_then_split,
        )

        explicit_text_cast = numeric_unpivot.replace(
            '    Split = Table.SplitColumn(\n',
            '    TextValue = Table.TransformColumnTypes(Unpivoted, {{"Value", type text}}),\n'
            '    Split = Table.SplitColumn(\n',
        ).replace("        Unpivoted,\n        \"Value\",", "        TextValue,\n        \"Value\",")
        self.assertEqual(
            parse_m_script(explicit_text_cast, "Sales Data")[-2:],
            [
                {"op": "convert_type", "column": "Value", "type": "text"},
                {"op": "split_column", "column": "Value", "delimiter": ":"},
            ],
        )

    def test_m_group_min_max_preserve_unpivoted_value_type(self) -> None:
        for function, output_name in (("List.Min", "Minimum"), ("List.Max", "Maximum")):
            script = "\n".join([
                "let",
                '    Source = #"Sales Data",',
                '    Typed = Table.TransformColumnTypes(Source, {{"Revenue", Int64.Type}}),',
                '    Unpivoted = Table.Unpivot(Typed, {"Revenue"}, "Attribute", "Value"),',
                '    Grouped = Table.Group(Unpivoted, {"Attribute"}, '
                f'{{{{"{output_name}", each {function}([Value])}}}}),',
                '    Split = Table.SplitColumn(Grouped, "' + output_name + '", '
                'Splitter.SplitTextByEachDelimiter({":"}, QuoteStyle.None), '
                '{"' + output_name + '.1", "' + output_name + '.2"}, "")',
                "in",
                "    Split",
            ])
            with self.subTest(function=function):
                with self.assertRaisesRegex(PowerQueryMScriptError, "remain text-typed"):
                    parse_m_script(script, "Sales Data")

        explicitly_text = "\n".join([
            "let",
            '    Source = #"Sales Data",',
            '    Typed = Table.TransformColumnTypes(Source, {{"Revenue", Int64.Type}}),',
            '    Unpivoted = Table.Unpivot(Typed, {"Revenue"}, "Attribute", "Value"),',
            '    TextValue = Table.TransformColumnTypes(Unpivoted, {{"Value", type text}}),',
            '    Grouped = Table.Group(TextValue, {"Attribute"}, '
            '{{"Minimum", each List.Min([Value])}}),',
            '    Split = Table.SplitColumn(Grouped, "Minimum", '
            'Splitter.SplitTextByEachDelimiter({":"}, QuoteStyle.None), '
            '{"Minimum.1", "Minimum.2"}, "")',
            "in",
            "    Split",
        ])
        self.assertEqual(
            [step["op"] for step in parse_m_script(explicitly_text, "Sales Data")[-3:]],
            ["convert_type", "group_by", "split_column"],
        )

    def test_m_text_literals_round_trip_character_escapes(self) -> None:
        values = ["\n", "\r\n", "\t", "#(lf)", "quote \" mark", "\u0085"]
        for delimiter in values:
            with self.subTest(delimiter=repr(delimiter)):
                step = {
                    "op": "extract_text_by_delimiter", "column": "Code",
                    "side": "before", "delimiter": delimiter, "occurrence": 0,
                }
                script = steps_to_m_script([step], "Sales Data")
                self.assertEqual(parse_m_script(script, "Sales Data"), [step])
                if delimiter == "\n":
                    self.assertIn("#(lf)", script)
                elif delimiter == "\r\n":
                    self.assertIn("#(cr)#(lf)", script)
                elif delimiter == "#(lf)":
                    self.assertIn("#(#)(lf)", script)

        escaped_input = '''let
    Source = #"Sales Data",
    Extracted = Table.TransformColumns(
        Source,
        {{"Code", each if _ = null or _ = "" then "" else Text.BeforeDelimiter(_, "#(lf)", 0), type text}}
    )
in
    Extracted'''
        self.assertEqual(
            parse_m_script(escaped_input, "Sales Data"),
            [{
                "op": "extract_text_by_delimiter", "column": "Code",
                "side": "before", "delimiter": "\n", "occurrence": 0,
            }],
        )

        raw_control = '''let
    Source = #"Sales Data",
    Split = Table.SplitColumn(Source, "Code", Splitter.SplitTextByEachDelimiter({"raw
line"}, QuoteStyle.None), {"Code.1", "Code.2"}, "")
in
    Split'''
        with self.assertRaisesRegex(PowerQueryMScriptError, "Non-graphic characters"):
            parse_m_script(raw_control, "Sales Data")

    def test_negative_text_filters_round_trip_and_keep_blank_rows(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Code"],
            [{"Code": ""}, {"Code": "A-100"}, {"Code": "B-200"}],
            {},
            [],
        )
        cases = (
            ("does_not_contain", "A-"),
            ("does_not_begin_with", "A-"),
            ("does_not_end_with", "100"),
        )
        for operator, value in cases:
            with self.subTest(operator=operator):
                step = {"op": "filter_rows", "column": "Code", "operator": operator, "value": value}
                script = steps_to_m_script([step], "Sales Data")
                self.assertIn("then true else not Text.", script)
                parsed = parse_m_script(script, "Sales Data")
                self.assertEqual(parsed, [step])
                result = apply_transformations(source, parsed)
                self.assertEqual(result, apply_transformations(source, [step]))
                self.assertEqual(
                    [row["Code"] for row in result.rows],
                    ["", "B-200"],
                )

    def test_negative_text_filter_requires_null_guard_and_text_type(self) -> None:
        unsafe = '''let
    Source = #"Sales Data",
    Filtered = Table.SelectRows(Source, each not Text.Contains([Code], "A-"))
in
    Filtered'''
        with self.assertRaisesRegex(PowerQueryMScriptError, "include null rows"):
            parse_m_script(unsafe, "Sales Data")

        typed_as_number = [
            {"op": "convert_type", "column": "Code", "type": "whole_number"},
            {"op": "filter_rows", "column": "Code", "operator": "does_not_contain", "value": "1"},
        ]
        self.assertEqual(m_compatibility_issues(typed_as_number)[0]["step"], 2)
        with self.assertRaisesRegex(PowerQueryMScriptError, "requires 'Code' to remain text-typed"):
            steps_to_m_script(typed_as_number, "Sales Data")

    def test_m_expression_literals_decode_character_escapes(self) -> None:
        split_script = "\n".join([
            "let",
            '    Source = #"Sales Data",',
            '    Added = Table.AddColumn(Source, "Calc", each Text.From("a#(lf)b")),',
            '    Split = Table.SplitColumn(Added, "Calc", '
            'Splitter.SplitTextByEachDelimiter({"#(lf)"}, QuoteStyle.None), '
            '{"Calc.1", "Calc.2"}, "")',
            "in",
            "    Split",
        ])
        steps = parse_m_script(split_script, "Sales Data")
        source = ImportCandidate("inline", ["Id"], [{"Id": "1"}], {}, [])
        result = apply_transformations(source, steps)
        self.assertEqual(result.rows, [{"Id": "1", "Calc.1": "a", "Calc.2": "b"}])

        quoted_field_script = "\n".join([
            "let",
            '    Source = #"Sales Data",',
            '    Added = Table.AddColumn(Source, "Calc", each Text.From([#"A#(lf)B"]))',
            "in",
            "    Added",
        ])
        quoted_field_steps = parse_m_script(quoted_field_script, "Sales Data")
        quoted_source = ImportCandidate("inline", ["A\nB"], [{"A\nB": "value"}], {}, [])
        self.assertEqual(
            apply_transformations(quoted_source, quoted_field_steps).rows,
            [{"A\nB": "value", "Calc": "value"}],
        )

    def test_each_declared_m_step_round_trips_and_replays_like_native_transform(self) -> None:
        cases = [
            {"op": "remove_column", "column": "Customer"},
            {"op": "keep_columns", "columns": ["Region", "Revenue"]},
            {"op": "rename_column", "column": "Region", "new_name": "Area"},
            *[
                {
                    "op": "filter_rows",
                    "column": "Revenue" if operator in {
                        "greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal",
                    } else "Region",
                    "operator": operator,
                    "value": value,
                }
                for operator, value in (
                    ("equals", "East"), ("not_equals", "East"),
                    ("greater_than", "15"), ("greater_than_or_equal", "15"),
                    ("less_than", "15"), ("less_than_or_equal", "15"),
                    ("contains", "a"), ("begins_with", "E"), ("ends_with", "t"),
                ("does_not_contain", "a"),
                ("does_not_begin_with", "E"),
                ("does_not_end_with", "t"),
                    ("is_blank", ""), ("is_not_blank", ""),
                )
            ],
            {"op": "add_custom_column", "name": "Net", "expression": "Text.From([Revenue])"},
            {
                "op": "conditional_column", "name": "Segment", "clauses": [{
                    "column": "Region", "operator": "equals", "test_value": "East",
                    "test_value_kind": "value", "output": "Priority", "output_kind": "value",
                }], "else_value": "Other", "else_kind": "value",
            },
            *[
                {"op": "convert_type", "column": "Revenue", "type": type_name}
                for type_name in (
                    "text", "whole_number", "decimal_number", "boolean",
                    "date", "datetime", "time",
                )
            ],
            {"op": "sort_rows", "column": "Revenue", "direction": "desc"},
            {"op": "sort_rows_by_columns", "sorts": [
                {"column": "Region", "direction": "asc"},
                {"column": "Revenue", "direction": "desc"},
            ]},
            {"op": "remove_duplicates"},
            {"op": "remove_duplicates", "columns": ["Region"]},
            {"op": "keep_top_rows", "count": 1},
            {"op": "remove_top_rows", "count": 1},
            {"op": "keep_bottom_rows", "count": 1},
            {"op": "remove_bottom_rows", "count": 1},
            {"op": "keep_range_rows", "first_row": 2, "count": 1},
            {
                "op": "remove_alternate_rows", "first_row_to_remove": 2,
                "remove_count": 1, "keep_count": 1,
            },
            {"op": "remove_blank_rows"},
            {"op": "replace_value", "column": "Region", "value": "East", "replacement": "North"},
            *[
                {"op": operation, "column": "Customer"}
                for operation in (
                    "trim_text", "clean_text", "lowercase_text",
                    "uppercase_text", "proper_case_text", "reverse_text",
                )
            ],
            {"op": "reorder_columns", "columns": ["Customer", "Region", "Revenue"]},
            {"op": "promote_headers"},
            {"op": "demote_headers"},
            {"op": "add_index_column", "new_name": "Index", "start": 0, "increment": 1},
            {"op": "duplicate_column", "column": "Revenue", "new_name": "Revenue copy"},
            {"op": "fill_down", "columns": ["Region", "Customer"]},
            {"op": "fill_up", "columns": ["Region", "Customer"]},
        ]

        additional_source = ImportCandidate(
            "inline",
            ["Region", "Revenue", "Customer"],
            [
                {"Region": "East", "Revenue": "12", "Customer": "alpha,beta"},
                {"Region": "West", "Revenue": "20", "Customer": "beta,gamma"},
                {"Region": "East", "Revenue": "5", "Customer": "gamma,alpha"},
            ],
            {},
            [],
        )
        pivot_source = ImportCandidate(
            "inline",
            ["Region", "Year", "Sales"],
            [
                {"Region": "East", "Year": "2024", "Sales": "10"},
                {"Region": "East", "Year": "2025", "Sales": "20"},
                {"Region": "West", "Year": "2024", "Sales": "5"},
            ],
            {},
            [],
        )
        additional_cases = [
            (
                additional_source,
                {"op": "filter_rows_advanced", "clauses": [{
                    "column": "Region", "operator": "equals", "value": "East",
                    "join": "and",
                }]},
            ),
            (
                additional_source,
                {"op": "convert_type_using_locale", "column": "Revenue",
                 "type": "decimal_number", "culture": "en-US"},
            ),
            (
                additional_source,
                {"op": "extract_text_by_delimiter", "column": "Customer",
                 "side": "before", "delimiter": ",", "occurrence": 0},
            ),
            (
                ImportCandidate(
                    "inline", ["Code"], [{"Code": "left[middle]right"}], {}, []
                ),
                {"op": "extract_text_between_delimiters", "column": "Code",
                 "start_delimiter": "[", "end_delimiter": "]",
                 "start_occurrence": 0, "end_occurrence": 0},
            ),
            (
                ImportCandidate(
                    "inline", ["Code"], [{"Code": "a:b:c"}, {"Code": "x:y"}], {}, []
                ),
                {"op": "split_column", "column": "Code", "delimiter": ":"},
            ),
            (
                ImportCandidate(
                    "inline", ["Code"], [{"Code": "a:b:c"}, {"Code": "x:y"}], {}, []
                ),
                {"op": "split_column_by_each_delimiter", "column": "Code",
                 "delimiter": ":"},
            ),
            (
                ImportCandidate(
                    "inline", ["Code"], [{"Code": "a:b:c"}, {"Code": "x:y"}], {}, []
                ),
                {"op": "split_column_to_rows", "column": "Code", "delimiter": ":"},
            ),
            (
                ImportCandidate(
                    "inline", ["Code"], [{"Code": "abcd"}, {"Code": "wxyz"}], {}, []
                ),
                {"op": "split_column_by_positions", "column": "Code",
                 "positions": [0, 2]},
            ),
            (
                additional_source,
                {"op": "merge_columns", "columns": ["Region", "Customer"],
                 "separator": "-", "new_name": "Joined"},
            ),
            (
                additional_source,
                {"op": "group_by", "columns": ["Region"], "aggregations": [{
                    "operation": "sum", "column": "Revenue", "new_name": "Total",
                }]},
            ),
            (
                additional_source,
                {"op": "unpivot_columns", "columns": ["Revenue", "Customer"],
                 "attribute_name": "Attribute", "value_name": "Value"},
            ),
            (
                additional_source,
                {"op": "unpivot_other_columns", "columns": ["Region"],
                 "attribute_name": "Attribute", "value_name": "Value"},
            ),
            (
                pivot_source,
                {"op": "pivot_column", "attribute_column": "Year",
                 "value_column": "Sales", "aggregation": "none"},
            ),
            (
                additional_source,
                {"op": "keep_duplicates", "columns": ["Region"]},
            ),
            (
                self.source,
                {"op": "transpose_table"},
            ),
        ]

        operation_dialog = TransformDataDialog(self.source, query_name="Sales Data")
        exposed_operations = {
            str(operation_dialog.operation_combo.itemData(index))
            for index in range(operation_dialog.operation_combo.count())
        }
        operation_dialog.deleteLater()
        covered_operations = {step["op"] for step in cases} | {
            step["op"] for _source, step in additional_cases
        }
        self.assertEqual(len(exposed_operations), 46)
        self.assertEqual(covered_operations, exposed_operations)

        for step in cases:
            with self.subTest(operation=step["op"], step=step):
                self.assertEqual(m_compatibility_issues([step]), [])
                script = steps_to_m_script([step], "Sales Data")
                parsed_steps = parse_m_script(script, "Sales Data")
                source = deepcopy(self.source)
                if step["op"] == "convert_type":
                    samples = {
                        "boolean": ["true", "false"],
                        "date": ["2026-08-01", "2026-08-02"],
                        "datetime": ["2026-08-01T10:30:00", "2026-08-02T11:30:00"],
                        "time": ["10:30:00", "11:30:00"],
                    }.get(step["type"])
                    if samples:
                        for row, value in zip(source.rows, samples):
                            row["Revenue"] = value
                direct = apply_transformations(source, [step])
                through_m = apply_transformations(source, parsed_steps)
                self.assertEqual(through_m, direct)
                self.assertEqual(
                    column_types_after_steps(source.headers, parsed_steps, output_headers=through_m.headers),
                    column_types_after_steps(source.headers, [step], output_headers=direct.headers),
                )

        for source, step in additional_cases:
            with self.subTest(operation=step["op"], step=step):
                self.assertEqual(m_compatibility_issues([step]), [])
                script = steps_to_m_script([step], "Sales Data")
                parsed_steps = parse_m_script(script, "Sales Data")
                direct = apply_transformations(source, [step])
                through_m = apply_transformations(source, parsed_steps)
                self.assertEqual(through_m, direct)
                self.assertEqual(
                    column_types_after_steps(
                        source.headers, parsed_steps, output_headers=through_m.headers
                    ),
                    column_types_after_steps(
                        source.headers, [step], output_headers=direct.headers
                    ),
                )

    def test_editor_previews_and_applies_without_committing_to_source(self) -> None:
        dialog = PowerQueryMEditorDialog(self.source, [], "Sales Data")
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertEqual(dialog.preview.model().rowCount(), 2)
        self.assertIn('Source = #"Sales Data"', dialog.editor.toPlainText())

        dialog.editor.setPlainText('''let
    Source = #"Sales Data",
    Filtered = Table.SelectRows(Source, each [Region] = "East")
in
    Filtered''')
        dialog.preview_button.click()
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertEqual(dialog.preview.model().rowCount(), 1)

        dialog.apply_button.click()

        self.assertIsNotNone(dialog.candidate)
        self.assertEqual(dialog.steps, [{
            "op": "filter_rows", "column": "Region", "operator": "equals", "value": "East",
        }])
        self.assertEqual(self.source.headers, ["Region", "Revenue", "Customer"])
        dialog.deleteLater()

    def test_transform_editor_formula_bar_tracks_the_selected_step(self) -> None:
        dialog = TransformDataDialog(self.source, query_name="Sales Data")
        dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData("trim_text"))
        dialog.column_combo.setCurrentText("Customer")

        dialog._add_step()

        self.assertEqual(dialog.step_list.currentRow(), 0)
        self.assertIn("Table.TransformColumns", dialog.formula_bar.text())
        self.assertIn('"Customer"', dialog.formula_bar.text())
        self.assertTrue(dialog.formula_edit_button.isEnabled())

        dialog.formula_bar.setText(dialog.formula_bar.text().replace("Text.Trim", "Text.Upper"))
        dialog.apply_formula_button.click()
        self.assertEqual(dialog._steps[0], {"op": "uppercase_text", "column": "Customer"})
        self.assertEqual(dialog._preview_candidate.rows[0]["Customer"], "  ADA  ")

        accepted_steps = deepcopy(dialog._steps)
        accepted_candidate = deepcopy(dialog._preview_candidate)
        dialog.formula_bar.setText("Table.TransformColumns(Source, {broken})")
        dialog.apply_formula_button.click()
        self.assertEqual(dialog._steps, accepted_steps)
        self.assertEqual(dialog._preview_candidate, accepted_candidate)
        dialog.deleteLater()

    def test_custom_column_settings_dialog_cancel_and_save_replay_downstream_steps(self) -> None:
        dialog = TransformDataDialog(
            self.source,
            [
                {
                    "op": "add_custom_column",
                    "name": "Band",
                    "expression": '"  gold  "',
                },
                {"op": "trim_text", "column": "Band"},
            ],
            query_name="Sales Data",
        )
        dialog.step_list.setCurrentRow(0)
        accepted_steps = deepcopy(dialog._steps)
        accepted_candidate = deepcopy(dialog._preview_candidate)

        def cancel_settings(settings: QDialog) -> QDialog.DialogCode:
            self.assertEqual(settings.windowTitle(), "Add custom column Settings")
            self.assertEqual(dialog.value_edit.text(), "Band")
            self.assertEqual(dialog.custom_expression_edit.toPlainText(), '"  gold  "')
            dialog.custom_expression_edit.setPlainText('" canceled "')
            settings.reject()
            return QDialog.DialogCode.Rejected

        with patch.object(QDialog, "exec", new=cancel_settings):
            dialog._edit_selected_step_settings()
        self.assertEqual(dialog._steps, accepted_steps)
        self.assertEqual(dialog._preview_candidate, accepted_candidate)
        self.assertEqual(dialog.custom_expression_edit.toPlainText(), '"  gold  "')

        def accept_settings(settings: QDialog) -> QDialog.DialogCode:
            buttons = settings.findChild(
                QDialogButtonBox, "powerQueryStepSettingsButtons"
            )
            self.assertIsNotNone(buttons)
            dialog.custom_expression_edit.setPlainText("Text.Unknown([Customer])")
            buttons.button(QDialogButtonBox.StandardButton.Save).click()
            self.assertFalse(dialog.error_label.isHidden())
            dialog.custom_expression_edit.setPlainText('"  silver  "')
            buttons.button(QDialogButtonBox.StandardButton.Save).click()
            return settings.result()

        with patch.object(QDialog, "exec", new=accept_settings):
            dialog._edit_selected_step_settings()
        self.assertEqual(dialog._steps[0]["expression"], '"  silver  "')
        self.assertEqual(dialog._steps[1], {"op": "trim_text", "column": "Band"})
        self.assertEqual(
            [row["Band"] for row in dialog._preview_candidate.rows],
            ["silver", "silver"],
        )
        self.assertIs(dialog.operation_settings_panel.parentWidget(), dialog.editor_panel)
        dialog.deleteLater()

    def test_step_settings_dialog_initializes_filter_type_split_and_replace_steps(self) -> None:
        cases = (
            (
                {"op": "filter_rows", "column": "Region", "operator": "equals", "value": "East"},
                lambda dialog: dialog.value_edit.setText("est"),
                lambda dialog: self.assertEqual(dialog._steps[0]["value"], "est"),
            ),
            (
                {"op": "convert_type", "column": "Revenue", "type": "whole_number"},
                lambda dialog: dialog._set_combo_data(dialog.option_combo, "decimal_number"),
                lambda dialog: self.assertEqual(dialog._steps[0]["type"], "decimal_number"),
            ),
            (
                {"op": "split_column", "column": "Customer", "delimiter": " "},
                lambda dialog: dialog.delimiter_edit.setText("a"),
                lambda dialog: self.assertEqual(dialog._steps[0]["delimiter"], "a"),
            ),
            (
                {"op": "replace_value", "column": "Region", "value": "East", "replacement": "North"},
                lambda dialog: dialog.replacement_edit.setText("Central"),
                lambda dialog: self.assertEqual(dialog._steps[0]["replacement"], "Central"),
            ),
        )
        for step, edit, verify in cases:
            with self.subTest(operation=step["op"]):
                dialog = TransformDataDialog(self.source, [step], query_name="Sales Data")
                dialog.step_list.setCurrentRow(0)

                def save_settings(settings: QDialog) -> QDialog.DialogCode:
                    edit(dialog)
                    buttons = settings.findChild(
                        QDialogButtonBox, "powerQueryStepSettingsButtons"
                    )
                    self.assertIsNotNone(buttons)
                    buttons.button(QDialogButtonBox.StandardButton.Save).click()
                    return settings.result()

                with patch.object(QDialog, "exec", new=save_settings):
                    dialog._edit_selected_step_settings()
                verify(dialog)
                settings_button = dialog.findChild(
                    QToolButton, "editAppliedStepSettingsButton"
                )
                self.assertIsNotNone(settings_button)
                self.assertTrue(settings_button.isEnabled())
                self.assertEqual(
                    dialog._preview_candidate,
                    apply_transformations(self.source, dialog._steps),
                )
                dialog.deleteLater()

    def test_step_settings_button_is_disabled_for_steps_without_options(self) -> None:
        dialog = TransformDataDialog(
            self.source, [{"op": "remove_blank_rows"}], query_name="Sales Data"
        )
        dialog.step_list.setCurrentRow(0)
        settings_button = dialog.findChild(
            QToolButton, "editAppliedStepSettingsButton"
        )
        self.assertIsNotNone(settings_button)
        self.assertFalse(settings_button.isEnabled())
        accepted_steps = deepcopy(dialog._steps)
        accepted_candidate = deepcopy(dialog._preview_candidate)

        dialog._edit_selected_step_settings()

        self.assertEqual(dialog._steps, accepted_steps)
        self.assertEqual(dialog._preview_candidate, accepted_candidate)
        dialog.deleteLater()

    def test_multiline_formula_is_routed_to_advanced_editor(self) -> None:
        dialog = TransformDataDialog(
            self.source,
            [{
                "op": "add_custom_column",
                "name": "Label",
                "expression": 'if Text.Length([Region]) > 0 then "High"\nelse "Low"',
            }],
            query_name="Sales Data",
        )
        dialog.step_list.setCurrentRow(0)

        self.assertFalse(dialog.formula_bar.isEnabled())
        self.assertFalse(dialog.apply_formula_button.isEnabled())
        self.assertIn("spans multiple lines", dialog.formula_bar.placeholderText())
        self.assertTrue(dialog.formula_edit_button.isEnabled())
        dialog.deleteLater()

    def test_preview_and_profile_follow_the_selected_applied_step(self) -> None:
        dialog = TransformDataDialog(
            self.source,
            [
                {"op": "trim_text", "column": "Customer"},
                {"op": "filter_rows", "column": "Region", "operator": "equals", "value": "East"},
            ],
        )
        self.assertEqual(dialog.preview.model().rowCount(), 1)

        dialog.step_list.setCurrentRow(0)

        self.assertEqual(dialog.preview.model().rowCount(), 2)
        self.assertEqual(dialog.preview.model().data(dialog.preview.model().index(0, 2)), "Ada")
        self.assertIn("2 rows after step 1", dialog.count_label.text())
        self.assertEqual(dialog.profile_table.item(2, 4).text(), "Ada (1), Lin (1)")
        self.assertEqual(dialog.quality_table.item(2, 1).text(), "100.0% (2)")

        dialog.step_list.setCurrentRow(1)
        self.assertEqual(dialog.preview.model().rowCount(), 1)
        self.assertIn("1 rows after step 2", dialog.count_label.text())
        self.assertEqual(dialog.profile_table.item(2, 4).text(), "Ada (1)")
        self.assertEqual(dialog.quality_table.item(2, 1).text(), "100.0% (1)")
        dialog.deleteLater()

    def test_applied_step_names_and_descriptions_follow_reordering(self) -> None:
        steps = [
            {"op": "trim_text", "column": "Customer"},
            {"op": "filter_rows", "column": "Region", "operator": "equals", "value": "East"},
        ]
        dialog = TransformDataDialog(
            self.source,
            queries=[{
                "id": "sales",
                "name": "Sales",
                "candidate": self.source,
                "steps": steps,
                "step_metadata": [{"name": "Clean customer", "description": "Trim extra spaces."}, {}],
            }],
            active_query_id="sales",
        )
        self.assertEqual(dialog.step_list.item(0).text(), "Clean customer")
        self.assertIn("Trim extra spaces.", dialog.step_list.item(0).toolTip())
        dialog.query_name_edit.setText("Regional Sales")
        dialog.query_description_edit.setPlainText("Sales prepared by region.")
        self.assertEqual(dialog.query_list.currentItem().text(), "Regional Sales")

        dialog.step_list.setCurrentRow(0)
        with patch.object(QInputDialog, "getText", return_value=("Normalize customer", True)):
            dialog._rename_selected_step()
        with patch.object(
            QInputDialog, "getMultiLineText", return_value=("Remove surrounding whitespace.", True)
        ):
            dialog._describe_selected_step()
        dialog._move_step(1)

        self.assertEqual(dialog.step_list.currentRow(), 1)
        self.assertEqual(dialog.step_list.item(1).text(), "Normalize customer")
        self.assertIn("Remove surrounding whitespace.", dialog.step_list.item(1).toolTip())
        dialog._accept_candidate()
        accepted = dialog.accepted_queries
        self.assertIsNotNone(accepted)
        self.assertEqual(accepted["sales"]["name"], "Regional Sales")
        self.assertEqual(accepted["sales"]["description"], "Sales prepared by region.")
        self.assertEqual(accepted["sales"]["step_metadata"], [
            {},
            {"name": "Normalize customer", "description": "Remove surrounding whitespace."},
        ])
        dialog.deleteLater()

    def test_transform_editor_discloses_multiline_m_formula_in_advanced_editor(self) -> None:
        dialog = TransformDataDialog(
            self.source,
            [{"op": "keep_duplicates", "columns": ["Region"]}],
            query_name="Sales Data",
        )
        dialog.step_list.setCurrentRow(0)

        self.assertFalse(dialog.formula_bar.isEnabled())
        self.assertIn("spans multiple lines", dialog.formula_bar.placeholderText())
        self.assertTrue(dialog.advanced_editor_button.isEnabled())
        dialog.deleteLater()

    def test_column_quality_and_profile_use_the_selected_row_scope(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Region"],
            [{"Region": "A"} for _ in range(100)]
            + [{"Region": ""} for _ in range(5)],
            {},
            [],
        )
        dialog = TransformDataDialog(source)

        self.assertEqual(dialog.quality_table.item(0, 1).text(), "95.2% (100)")
        self.assertEqual(dialog.quality_table.item(0, 2).text(), "4.8% (5)")
        self.assertEqual(dialog.quality_table.item(0, 3).text(), "Not tracked")
        self.assertEqual(dialog.profile_table.item(0, 2).text(), "1")
        self.assertEqual(dialog.profile_table.item(0, 3).text(), "0")
        self.assertEqual(dialog.profile_table.item(0, 4).text(), "A (100)")
        self.assertIn("105 rows", dialog.profile_scope_note.text())

        dialog.profile_scope_combo.setCurrentIndex(1)
        self.assertEqual(dialog.quality_table.item(0, 1).text(), "100.0% (100)")
        self.assertEqual(dialog.profile_table.item(0, 2).text(), "1")
        self.assertIn("100 rows", dialog.profile_scope_note.text())
        dialog.deleteLater()

        singleton_and_blank = ImportCandidate(
            "inline",
            ["Value"],
            [{"Value": "Solo"}, {"Value": ""}],
            {},
            [],
        )
        dialog = TransformDataDialog(singleton_and_blank)
        self.assertEqual(dialog.profile_table.item(0, 2).text(), "1")
        self.assertEqual(dialog.profile_table.item(0, 3).text(), "1")
        dialog.deleteLater()

    def test_failed_type_preview_shows_all_conversion_row_diagnostics(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Amount"],
            [
                {"Amount": "10"},
                {"Amount": "bad"},
                {"Amount": "20"},
                {"Amount": "also bad"},
            ],
            {},
            [],
        )
        dialog = TransformDataDialog(source)
        dialog.operation_combo.setCurrentIndex(
            dialog.operation_combo.findData("convert_type")
        )
        dialog.column_combo.setCurrentText("Amount")
        dialog._set_combo_data(dialog.option_combo, "whole_number")

        dialog._add_step()

        self.assertEqual(dialog._steps, [])
        self.assertIn("2 conversion errors total", dialog.error_label.text())
        self.assertIn("row 2", dialog.error_label.text())
        self.assertIn("row 4 value 'also bad'", dialog.error_label.text())
        dialog.deleteLater()

    def test_query_navigator_keeps_steps_and_preview_per_query(self) -> None:
        second = ImportCandidate(
            "inline",
            ["Customer", "Amount"],
            [{"Customer": "  Ada  ", "Amount": "12"}],
            {},
            [],
        )
        dialog = TransformDataDialog(
            self.source,
            query_name="Sales",
            queries=[
                {
                    "id": "sales",
                    "name": "Sales",
                    "candidate": self.source,
                    "steps": [],
                },
                {
                    "id": "customers",
                    "name": "Customers",
                    "candidate": second,
                    "steps": [],
                },
            ],
            active_query_id="customers",
        )
        self.assertEqual(dialog.apply_button.text(), "Close & Apply")
        self.assertFalse(dialog.query_panel.isHidden())
        self.assertEqual(dialog._query_name, "Customers")
        dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData("trim_text"))
        dialog.column_combo.setCurrentText("Customer")
        dialog._add_step()
        self.assertEqual(dialog.preview.model().rowCount(), 1)

        dialog.query_list.setCurrentRow(0)
        self.assertEqual(dialog._query_name, "Sales")
        self.assertEqual(dialog.step_list.count(), 0)
        dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData("trim_text"))
        dialog.column_combo.setCurrentText("Customer")
        dialog._add_step()
        dialog.query_list.setCurrentRow(1)
        self.assertEqual(dialog._preview_candidate.rows[0]["Customer"], "Ada")
        self.assertEqual(dialog.step_list.count(), 1)

        dialog._accept_candidate()
        self.assertEqual(set(dialog.accepted_queries), {"sales", "customers"})
        self.assertEqual(dialog.accepted_queries["sales"]["steps"][0]["column"], "Customer")
        self.assertEqual(dialog.accepted_queries["customers"]["steps"][0]["column"], "Customer")
        dialog.deleteLater()

    def test_query_navigator_duplicates_and_stages_query_deletions(self) -> None:
        dialog = TransformDataDialog(
            self.source,
            queries=[
                {
                    "id": "sales",
                    "name": "Sales",
                    "candidate": self.source,
                    "steps": [{"op": "trim_text", "column": "Customer"}],
                    "step_metadata": [{"name": "Trim customer"}],
                },
                {
                    "id": "archive",
                    "name": "Archive",
                    "candidate": self.source,
                    "is_saved_query": True,
                    "query_definition": {"operation": "reference", "source_ids": ["sales"]},
                },
            ],
            active_query_id="sales",
            reserved_query_names={"Sales"},
        )

        dialog._duplicate_selected_query()
        duplicate_id = dialog._active_query_id
        self.assertNotEqual(duplicate_id, "sales")
        duplicate = dialog._query_states[duplicate_id]
        self.assertEqual(duplicate["name"], "Sales (Copy)")
        self.assertEqual(duplicate["steps"], [{"op": "trim_text", "column": "Customer"}])
        self.assertEqual(duplicate["step_metadata"], [{"name": "Trim customer"}])
        self.assertEqual(duplicate["duplicate_of_id"], "sales")

        dialog._duplicate_selected_query()
        staged_copy_id = dialog._active_query_id
        self.assertEqual(dialog._query_states[staged_copy_id]["duplicate_of_id"], duplicate_id)
        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            dialog._delete_selected_query()
        self.assertNotIn(staged_copy_id, dialog._query_states)
        dialog.query_list.setCurrentRow(dialog._query_order.index(duplicate_id))

        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel
        ):
            dialog._delete_selected_query()
        self.assertIn(duplicate_id, dialog._query_states)

        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            dialog._delete_selected_query()
        self.assertNotIn(duplicate_id, dialog._query_states)

        dialog.query_list.setCurrentRow(dialog._query_order.index("archive"))
        with patch.object(
            QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
        ):
            dialog._delete_selected_query()
        dialog._accept_candidate()

        self.assertEqual(dialog.deleted_query_ids, {"archive"})
        self.assertEqual(set(dialog.accepted_queries), {"sales"})
        dialog.deleteLater()

    def test_query_navigator_blocks_deleting_a_parent_with_dependents(self) -> None:
        dialog = TransformDataDialog(
            self.source,
            queries=[
                {"id": "sales", "name": "Sales", "candidate": self.source},
                {
                    "id": "reference",
                    "name": "Reference",
                    "candidate": self.source,
                    "is_saved_query": True,
                    "query_definition": {"operation": "reference", "source_ids": ["sales"]},
                },
            ],
            active_query_id="reference",
            query_dependents={"sales": ["reference"]},
        )
        dialog.query_list.setCurrentRow(dialog._query_order.index("sales"))

        with patch.object(QMessageBox, "question") as confirm_delete:
            dialog._delete_selected_query()

        confirm_delete.assert_not_called()
        self.assertIn("Delete dependent queries first: Reference", dialog.error_label.text())
        self.assertIn("sales", dialog._query_states)
        dialog.deleteLater()

    def test_cancel_discards_m_preview_without_changing_source(self) -> None:
        dialog = PowerQueryMEditorDialog(self.source, [], "Sales Data")
        original_source = deepcopy(self.source)
        dialog.editor.setPlainText('''let
    Source = #"Sales Data",
    Filtered = Table.SelectRows(Source, each [Region] = "East")
in
    Filtered''')
        dialog._preview_query()
        self.assertEqual(dialog.preview.model().rowCount(), 1)
        dialog.reject()

        self.assertIsNone(dialog.candidate)
        self.assertIsNone(dialog.steps)
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(self.source, original_source)
        dialog.deleteLater()

    def test_invalid_edit_after_successful_preview_cannot_apply_stale_result(self) -> None:
        dialog = PowerQueryMEditorDialog(self.source, [], "Sales Data")
        dialog.editor.setPlainText('''let
    Source = #"Sales Data",
    Filtered = Table.SelectRows(Source, each [Region] = "East")
in
    Filtered''')
        dialog._preview_query()
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertEqual(dialog._steps, [{
            "op": "filter_rows", "column": "Region", "operator": "equals", "value": "East",
        }])

        original_source = deepcopy(self.source)
        dialog.editor.setPlainText('''let
    Source = #"Wrong Query"
in
    Source''')
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertEqual(dialog.preview.model().rowCount(), 0)
        dialog._accept_query()

        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertIsNone(dialog._steps)
        self.assertIsNone(dialog._candidate)
        self.assertEqual(self.source, original_source)
        self.assertIn("current query", dialog.error_label.text())
        dialog.deleteLater()

    def test_transform_replay_failure_after_successful_preview_cannot_apply_stale_result(self) -> None:
        dialog = PowerQueryMEditorDialog(self.source, [], "Sales Data")
        dialog.editor.setPlainText('''let
    Source = #"Sales Data",
    Filtered = Table.SelectRows(Source, each [Region] = "East")
in
    Filtered''')
        dialog._preview_query()
        self.assertTrue(dialog.apply_button.isEnabled())

        dialog.editor.setPlainText('''let
    Source = #"Sales Data",
    Removed = Table.RemoveColumns(Source, {"Region", "Revenue", "Customer"})
in
    Removed''')
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertEqual(dialog.preview.model().rowCount(), 0)
        dialog._accept_query()

        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertIsNone(dialog._steps)
        self.assertIsNone(dialog._candidate)
        self.assertIn("last column", dialog.error_label.text())
        dialog.deleteLater()

    def test_m_compatibility_report_accepts_keep_duplicates_and_rejects_typed_keys(self) -> None:
        steps = [
            {"op": "convert_type", "column": "Revenue", "type": "decimal_number"},
            {"op": "keep_duplicates", "columns": ["Region"]},
        ]

        self.assertEqual(m_compatibility_issues(steps), [])

        typed_key = [
            {"op": "convert_type", "column": "Region", "type": "whole_number"},
            {"op": "keep_duplicates", "columns": ["Region"]},
        ]
        issues = m_compatibility_issues(typed_key)
        self.assertEqual([(issue["step"], issue["operation"]) for issue in issues], [
            (2, "keep_duplicates"),
        ])
        self.assertIn("text-typed", issues[0]["message"])
        self.assertEqual(m_compatibility_issues([
            {"op": "trim_text", "column": "Customer"},
            {"op": "convert_type", "column": "Revenue", "type": "decimal_number"},
        ]), [])

    def test_transform_dialog_opens_advanced_editor_for_keep_duplicates(self) -> None:
        steps = [
            {
                "op": "convert_type_using_locale", "column": "Revenue",
                "type": "decimal_number", "culture": "en-US",
            },
            {"op": "keep_duplicates", "columns": ["Region"]},
        ]
        dialog = TransformDataDialog(self.source, steps, query_name="Sales Data")
        before_steps = deepcopy(dialog._steps)
        before_preview = deepcopy(dialog._preview_candidate)
        before_source = deepcopy(self.source)
        self.assertTrue(dialog.advanced_editor_button.isEnabled())

        with patch("analytics_studio.local_table_dialogs.PowerQueryMEditorDialog") as editor:
            editor.return_value.exec.return_value = QDialog.DialogCode.Rejected
            dialog._open_advanced_editor()

        editor.assert_called_once()
        self.assertTrue(dialog.error_label.isHidden())
        self.assertEqual(dialog._steps, before_steps)
        self.assertEqual(dialog._preview_candidate, before_preview)
        self.assertEqual(self.source, before_source)
        dialog.deleteLater()

    def test_keep_duplicates_m_round_trip_preserves_keys_rows_types_and_order(self) -> None:
        source = ImportCandidate(
            "inline",
            ["Key", "Region", "Revenue", "Row"],
            [
                {"Key": "1:a", "Region": "b", "Revenue": "1.25", "Row": "first"},
                {"Key": "B", "Region": "west", "Revenue": "2.50", "Row": "unique"},
                {"Key": "1:a", "Region": "b", "Revenue": "3.75", "Row": "second"},
                {"Key": "1", "Region": "a:b", "Revenue": "4.00", "Row": "separator-safe"},
                {"Key": "a", "Region": "west", "Revenue": "5.00", "Row": "case-single"},
                {"Key": "", "Region": "north", "Revenue": "6.00", "Row": "blank-copy"},
                {"Key": "", "Region": "north", "Revenue": "6.00", "Row": "blank-copy"},
                {"Key": "1:a", "Region": "south", "Revenue": "7.00", "Row": "other-key"},
                {"Key": "Case", "Region": "east", "Revenue": "8.00", "Row": "case-upper"},
                {"Key": "case", "Region": "east", "Revenue": "9.00", "Row": "case-lower"},
            ],
            {},
            [],
        )
        steps = [
            {"op": "convert_type", "column": "Revenue", "type": "decimal_number"},
            {"op": "keep_duplicates", "columns": ["Key", "Region"]},
        ]

        script = steps_to_m_script(steps, "Sales Data")
        parsed = parse_m_script(script, "Sales Data")
        direct = apply_transformations(source, steps)
        replayed = apply_transformations(source, parsed)

        self.assertEqual(parsed, steps)
        self.assertEqual(m_compatibility_issues(steps), [])
        self.assertIn("Comparer.Ordinal", script)
        self.assertIn("Table.Sort", script)
        self.assertIn('then "0:"', script)
        self.assertEqual(replayed, direct)
        self.assertEqual([row["Row"] for row in replayed.rows], [
            "first", "second", "blank-copy", "blank-copy",
        ])
        self.assertEqual(
            column_types_after_steps(source.headers, parsed),
            column_types_after_steps(source.headers, steps),
        )

        dialog = PowerQueryMEditorDialog(source, steps, "Sales Data")
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertEqual(dialog._steps, steps)
        self.assertEqual(dialog._candidate, direct)
        dialog._accept_query()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.steps, steps)
        self.assertEqual(dialog.candidate, direct)
        dialog.deleteLater()

    def test_keep_duplicates_m_keeps_empty_schema_and_rejects_non_text_keys(self) -> None:
        source = ImportCandidate(
            "inline", ["Key", "Amount"],
            [{"Key": "A", "Amount": "1"}, {"Key": "B", "Amount": "2"}], {}, [],
        )
        step = {"op": "keep_duplicates", "columns": ["Key"]}
        script = steps_to_m_script([step], "Sales Data")
        result = apply_transformations(source, parse_m_script(script, "Sales Data"))
        self.assertEqual(result.headers, source.headers)
        self.assertEqual(result.rows, [])

        numeric_key = [
            {"op": "convert_type", "column": "Key", "type": "whole_number"},
            step,
        ]
        with self.assertRaisesRegex(PowerQueryMScriptError, "requires 'Key' to remain text-typed"):
            steps_to_m_script(numeric_key, "Sales Data")
        self.assertEqual(m_compatibility_issues(numeric_key)[0]["step"], 2)

    def test_keep_duplicates_m_rejects_noncanonical_comparer_edits(self) -> None:
        script = steps_to_m_script(
            [{"op": "keep_duplicates", "columns": ["Region"]}], "Sales Data"
        )
        with self.assertRaisesRegex(PowerQueryMScriptError, "canonical form"):
            parse_m_script(
                script.replace("Comparer.Ordinal", "Comparer.OrdinalIgnoreCase"),
                "Sales Data",
            )

    def test_invalid_or_unsupported_m_is_rejected(self) -> None:
        script = '''let
    Source = #"Sales Data",
    Added = Table.AddColumn(Source, "Unsafe", each __import__("os"))
in
    Added'''
        with self.assertRaises(PowerQueryMScriptError):
            parse_m_script(script, "Sales Data")

        with self.assertRaises(PowerQueryMScriptError):
            parse_m_script('let Source = #"Other Query" in Source', "Sales Data")

    def test_append_source_and_steps_round_trip_through_m(self) -> None:
        steps = [{
            "op": "filter_rows",
            "column": "Region",
            "operator": "equals",
            "value": "North",
        }]
        source_names = ["North", "South"]
        script = steps_to_m_script(
            steps, "All regions", source_query_names=source_names
        )

        self.assertIn(
            'Source = Table.Combine({#"North", #"South"})', script
        )
        self.assertEqual(
            parse_m_query_script(script, "All regions"),
            (source_names, steps),
        )
        self.assertEqual(parse_m_script(script, "All regions"), steps)
        self.assertTrue(m_script_matches_steps(
            script, "All regions", steps, source_query_names=source_names
        ))
        self.assertFalse(m_script_matches_steps(script, "All regions", steps))
        self.assertFalse(m_script_matches_steps(
            script, "All regions", steps,
            source_query_names=["North", "West"],
        ))

    def test_append_parent_rename_rewrites_only_the_m_source_binding(self) -> None:
        steps = [{
            "op": "filter_rows",
            "column": "Region",
            "operator": "equals",
            "value": "North",
        }]
        script = '''// Keep this query note.
let
    Source = Table.Combine({#"North", // Keep source comments during a rename.
        #"South"}),
    // Keep the meaningful applied-step name.
    NorthOnly = Table.SelectRows(Source, each [Region] = "North")
in
    NorthOnly'''

        rewritten = rewrite_m_append_source_names(
            script,
            "All regions",
            steps,
            ["North", "South"],
            ["North Renamed", "South"],
        )

        self.assertIsNotNone(rewritten)
        self.assertIn(
            'Table.Combine({#"North Renamed", // Keep source comments during a rename.\n'
            '        #"South"})',
            rewritten,
        )
        self.assertIn("// Keep this query note.", rewritten)
        self.assertIn("// Keep the meaningful applied-step name.", rewritten)
        self.assertIn("NorthOnly = Table.SelectRows", rewritten)
        self.assertTrue(m_script_matches_steps(
            rewritten,
            "All regions",
            steps,
            source_query_names=["North Renamed", "South"],
        ))

    def test_power_query_session_rebinds_saved_append_m_after_parent_rename(self) -> None:
        from analytics_studio.query_engine import append_candidates

        north = ImportCandidate(
            "csv", ["Region", "Amount"],
            [{"Region": "North", "Amount": "12"}], {}, [],
        )
        south = ImportCandidate(
            "csv", ["Region", "Amount"],
            [{"Region": "South", "Amount": "20"}], {}, [],
        )
        combined = append_candidates([north, south])
        steps = [{
            "op": "filter_rows",
            "column": "Region",
            "operator": "equals",
            "value": "North",
        }]
        script = '''let
    Source = Table.Combine({#"North", // Keep the source note during parent rename.
        #"South"}),
    // Keep authored step names on parent rename.
    NorthOnly = Table.SelectRows(Source, each [Region] = "North")
in
    NorthOnly'''
        types = {"Region": "text", "Amount": "whole_number"}
        session = TransformDataDialog(
            combined,
            steps,
            query_name="All regions",
            queries=[
                {
                    "id": "north",
                    "name": "North",
                    "candidate": north,
                    "column_types": types,
                    "steps": [],
                },
                {
                    "id": "south",
                    "name": "South",
                    "candidate": south,
                    "column_types": types,
                    "steps": [],
                },
                {
                    "id": "append",
                    "name": "All regions",
                    "candidate": combined,
                    "source_column_types": types,
                    "column_types": types,
                    "steps": steps,
                    "m_script": script,
                    "query_definition": {
                        "operation": "append",
                        "source_ids": ["north", "south"],
                    },
                },
            ],
            active_query_id="north",
        )

        session.query_list.setCurrentRow(session._query_order.index("north"))
        session.query_name_edit.setText("North Renamed")
        session._save_active_query_state()
        session._accept_candidate()
        accepted = session.accepted_queries
        self.assertIsNotNone(accepted)
        rebound = accepted["append"]["m_script"]
        self.assertIn(
            'Table.Combine({#"North Renamed", // Keep the source note during parent rename.\n'
            '        #"South"})',
            rebound,
        )
        self.assertIn("// Keep the source note during parent rename.", rebound)
        self.assertIn("// Keep authored step names on parent rename.", rebound)
        self.assertIn("NorthOnly = Table.SelectRows", rebound)
        self.assertTrue(m_script_matches_steps(
            rebound,
            "All regions",
            steps,
            source_query_names=["North Renamed", "South"],
            initial_column_types=types,
        ))
        session.deleteLater()
        session.deleteLater()

    def test_append_m_editor_previews_combined_parent_queries(self) -> None:
        from analytics_studio.query_engine import append_candidates

        north = ImportCandidate(
            "csv", ["Region", "Revenue"],
            [{"Region": "North", "Revenue": "12"}], {}, [],
        )
        south = ImportCandidate(
            "csv", ["Region", "Revenue"],
            [{"Region": "South", "Revenue": "20"}], {}, [],
        )
        combined = append_candidates([north, south])
        source_names = ["North", "South"]
        query_sources = [
            {"id": "north-id", "name": "North", "candidate": north},
            {"id": "south-id", "name": "South", "candidate": south},
        ]
        dialog = PowerQueryMEditorDialog(
            combined, [], "All regions",
            source_query_names=source_names,
            query_sources=query_sources,
        )
        self.assertIn(
            'Table.Combine({#"North", #"South"})',
            dialog.editor.toPlainText(),
        )

        script = '''let
    Source = Table.Combine({#"North", #"South"}),
    NorthOnly = Table.SelectRows(Source, each [Region] = "North")
in
    NorthOnly'''
        dialog.editor.setPlainText(script)
        dialog._preview_query()
        self.assertEqual(dialog._candidate.rows, [
            {"Region": "North", "Revenue": "12"},
        ])
        self.assertEqual(dialog._preview_source_candidate, combined)
        dialog._accept_query()
        self.assertEqual(dialog.candidate.rows, [
            {"Region": "North", "Revenue": "12"},
        ])
        self.assertEqual(dialog.source_candidate, combined)
        dialog.deleteLater()

    def test_append_m_editor_rejects_changed_source_references(self) -> None:
        from analytics_studio.query_engine import append_candidates

        north = ImportCandidate("csv", ["Region"], [{"Region": "North"}], {}, [])
        south = ImportCandidate("csv", ["Region"], [{"Region": "South"}], {}, [])
        combined = append_candidates([north, south])
        dialog = PowerQueryMEditorDialog(
            combined, [], "All regions",
            source_query_names=["North", "South"],
            query_sources=[
                {"id": "north-id", "name": "North", "candidate": north},
                {"id": "south-id", "name": "South", "candidate": south},
            ],
        )
        dialog.editor.setPlainText(
            'let Source = Table.Combine({#"North", #"West"}) in Source'
        )
        dialog._preview_query()

        self.assertIsNone(dialog._candidate)
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertIn("Use Append Queries", dialog.error_label.text())
        dialog.deleteLater()

    def test_append_formula_bar_shows_placeholder_when_parent_is_unavailable(self) -> None:
        candidate = ImportCandidate(
            "query", ["Region"], [{"Region": "North"}], {}, [],
        )
        dialog = TransformDataDialog(
            candidate,
            [],
            query_name="All regions",
            queries=[{
                "id": "append",
                "name": "All regions",
                "candidate": candidate,
                "steps": [],
                "query_definition": {
                    "operation": "append",
                    "source_ids": ["missing-north", "missing-south"],
                },
            }],
            active_query_id="append",
        )

        self.assertFalse(dialog.formula_bar.isEnabled())
        self.assertIn("parent queries load", dialog.formula_bar.placeholderText())
        dialog.deleteLater()

    def test_append_m_editor_validates_against_inherited_source_column_types(self) -> None:
        from analytics_studio.query_engine import append_candidates

        north = ImportCandidate(
            "csv", ["Region", "Amount"],
            [{"Region": "North", "Amount": "12"}], {}, [],
        )
        south = ImportCandidate(
            "csv", ["Region", "Amount"],
            [{"Region": "South", "Amount": "20"}], {}, [],
        )
        combined = append_candidates([north, south])
        source_names = ["North", "South"]
        query_sources = [
            {"id": "north-id", "name": "North", "candidate": north},
            {"id": "south-id", "name": "South", "candidate": south},
        ]
        dialog = PowerQueryMEditorDialog(
            combined, [], "All regions",
            source_query_names=source_names,
            query_sources=query_sources,
            source_column_types={"Region": "text", "Amount": "whole_number"},
        )

        unsafe_script = '''let
    Source = Table.Combine({#"North", #"South"}),
    Trimmed = Table.TransformColumns(Source, {{"Amount", Text.Trim, type text}})
in
    Trimmed'''
        dialog.editor.setPlainText(unsafe_script)
        dialog._preview_query()
        self.assertIsNone(dialog._candidate)
        self.assertIn("'Amount' to remain text-typed", dialog.error_label.text())

        safe_script = '''let
    Source = Table.Combine({#"North", #"South"}),
    AsText = Table.TransformColumnTypes(Source, {{"Amount", type text}}),
    Trimmed = Table.TransformColumns(AsText, {{"Amount", Text.Trim, type text}})
in
    Trimmed'''
        dialog.editor.setPlainText(safe_script)
        dialog._preview_query()
        self.assertIsNotNone(dialog._candidate, dialog.error_label.text())
        self.assertEqual(
            [step["op"] for step in dialog._steps],
            ["convert_type", "trim_text"],
        )
        dialog.deleteLater()

    def test_accepted_authored_m_text_restores_comments_and_custom_step_names(self) -> None:
        steps = [{"op": "trim_text", "column": "Customer"}]
        script = '''// Keep this note with the query.
let
    Source = #"Sales Data",
    // Explain why the customer field is normalized.
    CleanedCustomers = Table.TransformColumns(Source, {{"Customer", Text.Trim, type text}})
in
    CleanedCustomers'''

        dialog = PowerQueryMEditorDialog(
            self.source, steps, "Sales Data", initial_script=script
        )
        self.assertEqual(dialog.editor.toPlainText(), script)
        self.assertTrue(m_script_matches_steps(script, "Sales Data", steps))
        dialog._accept_query()
        self.assertEqual(dialog.script, script)

    def test_m_text_for_stale_steps_falls_back_to_generated_script(self) -> None:
        steps = [{"op": "trim_text", "column": "Customer"}]
        stale_script = '''let
    Source = #"Sales Data",
    Filtered = Table.SelectRows(Source, each [Region] = "East")
in
    Filtered'''

        dialog = PowerQueryMEditorDialog(
            self.source, steps, "Sales Data", initial_script=stale_script
        )

        self.assertEqual(dialog.editor.toPlainText(), steps_to_m_script(steps, "Sales Data"))

    def test_power_query_session_drops_saved_m_text_after_rename_or_step_change(self) -> None:
        steps = [{"op": "trim_text", "column": "Customer"}]
        script = '''let
    Source = #"Sales Data",
    Cleaned = Table.TransformColumns(Source, {{"Customer", Text.Trim, type text}})
in
    Cleaned'''
        session = TransformDataDialog(
            self.source,
            steps,
            query_name="Sales Data",
            queries=[{
                "id": "sales",
                "name": "Sales Data",
                "candidate": self.source,
                "steps": steps,
                "m_script": script,
            }],
            active_query_id="sales",
        )

        session.query_name_edit.setText("Renamed Sales")
        session._save_active_query_state()
        self.assertNotIn("m_script", session._query_states["sales"])
        with patch("analytics_studio.local_table_dialogs.PowerQueryMEditorDialog") as editor:
            editor.return_value.exec.return_value = QDialog.DialogCode.Rejected
            session._open_advanced_editor()
        self.assertEqual(editor.call_args.args[2], "Renamed Sales")

        session._query_states["sales"]["m_script"] = script
        session.query_name_edit.setText("Sales Data")
        session._steps.append({"op": "remove_blank_rows"})
        session._save_active_query_state()
        self.assertNotIn("m_script", session._query_states["sales"])


if __name__ == "__main__":
    unittest.main()
