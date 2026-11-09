"""M scripts the step editor cannot map run on the M engine (Task 111, m-script-101).

A whole ``let ... in`` script becomes one ``m_script`` step. Its first binding names the source; that binding is bound
to the typed input table and its own expression is not evaluated. Every answer below is Power BI's (the spec
``docs/plans/2026-11-09-m-script-101-spec.json``, measured on Power BI Desktop 2.157): a script's table must match it
exactly, or the step is refused. A wrong answer fails the test.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from analytics_studio.file_import import ImportCandidate
from analytics_studio.power_query_m import (
    PowerQueryMEditorDialog,
    PowerQueryMScriptError,
    m_script_matches_steps,
    parse_m_query_script,
    steps_to_m_script,
)
from analytics_studio.power_query_values import PowerQueryCellError
from analytics_studio.transformations import (
    TransformationError,
    apply_transformations,
    column_types_after_steps,
    validate_steps,
)

SPEC = Path(__file__).resolve().parent.parent / "docs" / "plans" / "2026-11-09-m-script-101-spec.json"
HEADERS = ["Region", "Product", "Units", "Price", "Day"]
INITIAL_TYPES = {
    "Region": "text", "Product": "text", "Units": "whole_number", "Price": "decimal_number", "Day": "date",
}
RAW_ROWS = [
    ["North", "Pen", "2", "1.5", "2024-01-15"],
    ["South", "Pen", "5", "1.5", "2024-01-20"],
    ["North", "Ink", "1", "12", "2024-02-03"],
    ["East", "Pad", "10", "0.75", "2024-02-29"],
    ["South", "Ink", "3", "12", "2024-03-01"],
]
# Power BI's answers name a column type "number" for both whole and decimal columns (its canonical text).
APP_TYPES_OF_PB = {
    "number": {"whole_number", "decimal_number"}, "text": {"text"}, "date": {"date"}, "datetime": {"datetime"},
    "time": {"time"}, "logical": {"boolean"}, "any": {"any"},
}
# The four scripts the engine refuses on purpose: a nested table cell, a number result, a column of mixed
# types (an engine gap) and a non-finite number (the app does not store one).
REFUSED_SCRIPTS = {"Joined", "Profile", "Unpivot", "Err"}
MINIMUM_EXACT_SCRIPTS = 28


def spec() -> dict:
    with SPEC.open(encoding="utf-8") as handle:
        return json.load(handle)


def source_candidate() -> ImportCandidate:
    return ImportCandidate("inline", list(HEADERS), [dict(zip(HEADERS, row)) for row in RAW_ROWS], {}, [])


def step_for(script: str) -> list[dict]:
    return [{"op": "m_script", "script": script, "source_binding": "Source"}]


def query_script(script: str, query: str = "Sales") -> str:
    """The spec script with its Source written as a reference to the current query, as the editor reads it."""
    return script.replace(spec()["source_table"], f'#"{query}"')


# ---- Power BI's canonical table text ----------------------------------------------------------

def _split_top(text: str) -> list[str]:
    """Split on commas that are outside brackets and quotes."""
    parts, depth, quoted, current = [], 0, False, ""
    for char in text:
        if char == '"':
            quoted = not quoted
        elif not quoted and char == "[":
            depth += 1
        elif not quoted and char == "]":
            depth -= 1
        if char == "," and depth == 0 and not quoted:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    if current.strip():
        parts.append(current.strip())
    return parts


def _pb_cell(token: str):
    if token == "null":
        return None
    tag, _, value = token.partition(":")
    if tag == "text":
        return value[1:-1]
    if tag == "number":
        return Decimal(value)
    if tag == "date":
        return dt.date.fromisoformat(value)
    if tag == "logical":
        return value == "true"
    raise AssertionError(f"unexpected Power BI cell {token!r}")


def _pb_table(text: str) -> tuple[list[tuple[str, str]], list[list]]:
    match = re.fullmatch(r"V:table:cols=\[(.*?)\];rows=\[(.*)\]", text, re.S)
    assert match, text[:80]
    columns = re.findall(r'"([^"]*)":"([^"]*)"', match.group(1))
    rows = []
    for row in _split_top(match.group(2)):
        assert row.startswith("list:[") and row.endswith("]"), row[:60]
        rows.append([_pb_cell(token) for token in _split_top(row[len("list:["):-1])])
    return columns, rows


def _same_table(power_bi: str, result: ImportCandidate) -> str:
    """'' when the result is Power BI's table exactly, else the first difference."""
    columns, rows = _pb_table(power_bi)
    if [name for name, _ in columns] != result.headers:
        return f"headers {result.headers}"
    if len(rows) != len(result.rows):
        return f"row count {len(result.rows)} != {len(rows)}"
    for index, (pb_row, app_row) in enumerate(zip(rows, result.rows)):
        for (name, pb_type), pb_value in zip(columns, pb_row):
            app_value = app_row[name]
            if isinstance(app_value, PowerQueryCellError):
                return f"row {index} {name}: error cell"
            if pb_value is None or app_value is None:
                if pb_value is not app_value:
                    return f"row {index} {name}: {pb_value!r} != {app_value!r}"
                continue
            if isinstance(pb_value, Decimal):
                if not isinstance(app_value, (int, Decimal)) or Decimal(app_value) != pb_value:
                    return f"row {index} {name}: {pb_value} != {app_value!r}"
            elif pb_value != app_value or type(pb_value) is not type(app_value):
                return f"row {index} {name}: {pb_value!r} != {app_value!r}"
    return ""


def _types_match(power_bi: str, types: dict[str, str]) -> str:
    columns, _ = _pb_table(power_bi)
    for name, pb_type in columns:
        if types[name] not in APP_TYPES_OF_PB.get(pb_type, set()):
            return f"type of {name}: {types[name]} is not Power BI's {pb_type}"
    return ""


class SpecScriptTests(unittest.TestCase):
    """The 32 measured scripts: each is exactly Power BI's table, or refused by the step; none is wrong."""

    def test_every_script_is_exact_or_refused_and_none_is_wrong(self) -> None:
        exact, refused, wrong = [], [], []
        for script in spec()["scripts"]:
            name, expected = script["name"], script["power_bi"]
            if not expected.startswith("V:table:"):
                with self.assertRaises(TransformationError, msg=name):
                    apply_transformations(source_candidate(), step_for(script["script"]), initial_types=INITIAL_TYPES)
                refused.append(name)
                continue
            try:
                result = apply_transformations(
                    source_candidate(), step_for(script["script"]), initial_types=INITIAL_TYPES
                )
            except TransformationError:
                refused.append(name)
                continue
            types = column_types_after_steps(
                HEADERS, step_for(script["script"]), initial_types=INITIAL_TYPES, output_headers=result.headers
            )
            difference = _same_table(expected, result) or _types_match(expected, types)
            if difference:
                wrong.append(f"{name}: {difference}")
            else:
                exact.append(name)
        self.assertEqual(wrong, [], "\n".join(wrong))
        self.assertGreaterEqual(len(exact), MINIMUM_EXACT_SCRIPTS)
        self.assertEqual(set(refused), REFUSED_SCRIPTS)


class EditorFallbackTests(unittest.TestCase):
    """The editor keeps every script it maps (and refuses the forms it does not write back); a script with a call it
    has no mapping for becomes one m_script step that holds the whole script, and round-trips to the same text."""

    def scripts(self, *names: str) -> dict[str, str]:
        return {item["name"]: item["script"] for item in spec()["scripts"] if item["name"] in names}

    def test_unmapped_call_becomes_one_script_step_that_round_trips(self) -> None:
        for name, script in self.scripts("Joined", "Profile").items():
            text = query_script(script)
            source_names, steps = parse_m_query_script(text, "Sales", initial_column_types=INITIAL_TYPES)
            self.assertIsNone(source_names, name)
            self.assertEqual(steps, [{"op": "m_script", "script": text.strip(), "source_binding": "Source"}], name)
            self.assertEqual(steps_to_m_script(steps, "Sales", initial_column_types=INITIAL_TYPES), text.strip(), name)
            self.assertTrue(m_script_matches_steps(text, "Sales", steps, initial_column_types=INITIAL_TYPES), name)

    def test_mapped_call_in_a_refused_form_stays_an_editor_error(self) -> None:
        for name, script in self.scripts("Grouped", "Pivot", "Unpivot").items():
            with self.assertRaises(PowerQueryMScriptError, msg=name):
                parse_m_query_script(query_script(script), "Sales", initial_column_types=INITIAL_TYPES)

    def test_a_literal_source_is_not_a_fallback(self) -> None:
        script = self.scripts("Joined")["Joined"]  # its Source is a literal table: the editor cannot bind it
        with self.assertRaises(PowerQueryMScriptError):
            parse_m_query_script(script, "Sales", initial_column_types=INITIAL_TYPES)

    def test_the_mapped_scripts_are_still_editor_steps(self) -> None:
        names, steps = parse_m_query_script(query_script(self.scripts("Added")["Added"]), "Sales",
                                            initial_column_types=INITIAL_TYPES)
        self.assertIsNone(names)
        self.assertEqual([step["op"] for step in steps], ["add_custom_column"])


class ScriptRunRefusalTests(unittest.TestCase):
    def test_a_result_that_is_not_a_table_is_refused(self) -> None:
        with self.assertRaisesRegex(TransformationError, "must return a table"):
            apply_transformations(source_candidate(), step_for(
                "let Source = Sales, Count = Table.RowCount(Source) in Count"), initial_types=INITIAL_TYPES)

    def test_an_engine_gap_is_refused_with_the_engine_message(self) -> None:
        unpivot = next(item["script"] for item in spec()["scripts"] if item["name"] == "Unpivot")
        with self.assertRaisesRegex(TransformationError, "not supported by this engine yet"):
            apply_transformations(source_candidate(), step_for(unpivot), initial_types=INITIAL_TYPES)

    def test_a_nested_table_cell_is_refused(self) -> None:
        joined = next(item["script"] for item in spec()["scripts"] if item["name"] == "Joined")
        with self.assertRaises(TransformationError):
            apply_transformations(source_candidate(), step_for(joined), initial_types=INITIAL_TYPES)

    def test_a_genuine_cell_error_is_an_error_cell(self) -> None:
        script = ('let Source = Sales, Bad = Table.AddColumn(Source, "Bad", each Number.From([Region])) in Bad')
        result = apply_transformations(source_candidate(), step_for(script), initial_types=INITIAL_TYPES)
        self.assertEqual([row["Bad"].reason for row in result.rows], ["DataFormat.Error"] * 5)
        self.assertEqual(result.rows[0]["Bad"].message, "We couldn't convert to Number.")
        self.assertEqual(result.rows[0]["Units"], 2)

    def test_the_first_binding_must_be_the_source_binding(self) -> None:
        with self.assertRaises(TransformationError):
            apply_transformations(source_candidate(), step_for("let Other = Sales in Other"), initial_types=INITIAL_TYPES)

    def test_a_script_that_does_not_parse_is_refused(self) -> None:
        with self.assertRaises(TransformationError):
            apply_transformations(source_candidate(), step_for("let Source = Sales Source in"), initial_types=INITIAL_TYPES)

    def test_an_input_cell_that_does_not_convert_refuses_the_step(self) -> None:
        candidate = ImportCandidate("inline", ["Units"], [{"Units": "x"}], {}, [])
        with self.assertRaises(TransformationError):
            apply_transformations(candidate, step_for("let Source = Sales in Source"),
                                  initial_types={"Units": "whole_number"})

    def test_step_validation_rejects_a_bad_script_step(self) -> None:
        good = {"op": "m_script", "script": "let Source = Sales in Source", "source_binding": "Source"}
        self.assertEqual(validate_steps([good])[0]["op"], "m_script")
        for bad in (
            {**good, "source_binding": "not a name"},
            {**good, "script": 3},
            {**good, "script": "   "},
            {**good, "extra": 1},
        ):
            with self.assertRaises(TransformationError, msg=str(bad)):
                validate_steps([bad])


class OutputTypeTests(unittest.TestCase):
    def test_the_script_output_types_come_from_the_engine_table_type(self) -> None:
        pivot = next(item["script"] for item in spec()["scripts"] if item["name"] == "Pivot")
        types = column_types_after_steps(HEADERS, step_for(pivot), initial_types=INITIAL_TYPES)
        self.assertEqual(types, {"Region": "text", "Ink": "decimal_number", "Pad": "decimal_number",
                                 "Pen": "decimal_number"})
        grouped = next(item["script"] for item in spec()["scripts"] if item["name"] == "Grouped")
        self.assertEqual(column_types_after_steps(HEADERS, step_for(grouped), initial_types=INITIAL_TYPES),
                         {"Region": "text", "Total": "decimal_number", "Rows": "whole_number"})

    def test_a_script_step_can_be_followed_by_ordinary_steps(self) -> None:
        reversed_script = 'let Source = Sales, Reversed = Table.ReverseRows(Source) in Reversed'
        result = apply_transformations(
            source_candidate(),
            [*step_for(reversed_script), {"op": "keep_top_rows", "count": 2}],
            initial_types=INITIAL_TYPES,
        )
        self.assertEqual([row["Region"] for row in result.rows], ["South", "East"])


class RealAppScriptStepTests(unittest.TestCase):
    """Paste an unmappable script into the query, apply it, save, reopen and refresh (StudioController offscreen)."""

    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(["Analytics Studio tests"])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.source_path = self.root / "Sales.csv"
        self.source_path.write_text(
            "Region,Product,Units,Price,Day\n"
            "North,Pen,2,1.5,2024-01-15\nSouth,Pen,5,1.5,2024-01-20\nNorth,Ink,1,12,2024-02-03\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def controller(self, name: str):
        from PySide6.QtCore import QSettings

        from analytics_studio.controller import StudioController

        return StudioController(self.app, QSettings(str(self.root / name), QSettings.Format.IniFormat))

    def test_paste_apply_save_reopen_and_refresh_a_script_step(self) -> None:
        from analytics_studio.file_import import parse_file

        controller = self.controller("settings.ini")
        self.assertTrue(controller._commit_import(self.source_path, parse_file(self.source_path)))
        query = controller._active_model_table_name()
        script = (
            f'let\n    Source = #"{query}",\n'
            '    Reversed = Table.ReverseRows(Source),\n'
            '    Sales = Table.AddColumn(Reversed, "Sales", each [Units] * [Price], type number)\n'
            "in\n    Sales"
        )

        class PastedEditor(PowerQueryMEditorDialog):
            def exec(self) -> int:  # the user pastes the script, the editor previews it, then Done
                self.editor.setPlainText(script)
                self._preview_query()
                self._accept_query()
                return self.result()

        with patch("analytics_studio.controller.PowerQueryMEditorDialog", PastedEditor):
            self.assertTrue(controller.power_query_m_editor_dialog())
        self.assertEqual(controller._headers, ["Region", "Product", "Units", "Price", "Day", "Sales"])
        self.assertEqual([row["Region"] for row in controller._rows], ["North", "South", "North"])
        self.assertEqual([row["Sales"] for row in controller._rows], [Decimal("12"), Decimal("7.5"), Decimal("3")])
        project_path = self.root / "script.npa"
        self.assertTrue(controller._save_to(project_path))

        reopened = self.controller("reopened.ini")
        self.assertTrue(reopened.open_project_path(project_path))
        self.assertEqual([row["Sales"] for row in reopened._rows], [Decimal("12"), Decimal("7.5"), Decimal("3")])
        self.source_path.write_text(
            "Region,Product,Units,Price,Day\nEast,Pad,4,2,2024-03-01\n", encoding="utf-8"
        )
        reopened.refresh_source()
        self.assertEqual([row["Region"] for row in reopened._rows], ["East"])
        self.assertEqual([row["Sales"] for row in reopened._rows], [Decimal("8")])


if __name__ == "__main__":
    unittest.main()
