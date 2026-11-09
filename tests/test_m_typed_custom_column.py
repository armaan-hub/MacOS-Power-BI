"""Custom-column M formulas see typed cells, as after Power BI's Changed Type step (Task 110).

Spec: docs/plans/2026-11-09-m-typed-100-spec.json (26 formulas measured on Power BI Desktop over a fixed 4-row text
table; ``types`` is the Changed Type step). The spec is read only by this test; the app code never reads it.

Every spec cell must be Power BI's answer or the whole custom-column step must be refused. Nothing may be wrong.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from decimal import Decimal, InvalidOperation
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from analytics_studio.file_import import ImportCandidate
from analytics_studio.m_custom_column import (
    MFormulaRefused,
    UnconvertedCell,
    compile_m_formula,
    evaluate_m_formula,
)
from analytics_studio.power_query_values import PowerQueryCellError
from analytics_studio.transformations import (
    TransformationError,
    apply_transformations,
    infer_column_types,
)

SPEC_PATH = Path(__file__).resolve().parents[1] / "docs" / "plans" / "2026-11-09-m-typed-100-spec.json"
HEADERS = ["Name", "Units", "Price", "Day", "Flag"]
# Power BI's Changed Type step in the app's type names (Int64.Type, number, date, logical, text).
SPEC_TYPES = {
    "Name": "text",
    "Units": "whole_number",
    "Price": "decimal_number",
    "Day": "date",
    "Flag": "boolean",
}
RAW_ROWS = [
    {"Name": "Alpha", "Units": "2", "Price": "10.5", "Day": "2024-01-15", "Flag": "TRUE"},
    {"Name": "beta", "Units": "0", "Price": "3", "Day": "2024-02-29", "Flag": "false"},
    {"Name": "", "Units": "7", "Price": "0.25", "Day": "2023-12-31", "Flag": "true"},
    {"Name": "Gamma", "Units": "12", "Price": "1000", "Day": "2024-06-01", "Flag": "FALSE"},
]

# Formulas whose Power BI answer is an infinite number (or NaN) cannot be stored: the step is refused.
# Value.Type([Units]) = Int64.Type is refused too: the engine has no measured answer for Value.Type of an Int64 cell.
REFUSED_CASES = frozenset({2, 16, 17})
# The M parser has no `??` (the small evaluator answers it); it is the only formula that is not M.
OLD_ONLY_CASES = frozenset({15})


def load_spec() -> dict:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def base_candidate(rows: list[dict] | None = None) -> ImportCandidate:
    return ImportCandidate(
        "inline", list(HEADERS), [dict(row) for row in (rows or RAW_ROWS)],
        {"source_id": "task110-typed-table"}, [],
    )


def stored_matches(stored: object, canonical: str) -> bool:
    """Whether a stored custom-column cell is Power BI's answer (canonical M text from the spec)."""
    if canonical in {"true", "false"}:
        return stored == canonical
    if canonical.startswith("number:"):
        try:
            return isinstance(stored, str) and Decimal(stored) == Decimal(canonical[len("number:"):])
        except InvalidOperation:
            return False
    if canonical.startswith("text:"):
        return stored == json.loads(canonical[len("text:"):])
    if canonical.startswith("date:"):
        return stored == canonical[len("date:"):]
    return False


class TypedCustomColumnTests(unittest.TestCase):
    def test_every_spec_cell_is_power_bi_or_the_step_is_refused(self) -> None:
        spec = load_spec()
        self.assertEqual(len(spec["cases"]), 26)
        counts = {"exact": 0, "refused": 0, "wrong": 0}
        wrong: list[tuple[int, int, str, str]] = []
        for index, case in enumerate(spec["cases"]):
            try:
                result = apply_transformations(
                    base_candidate(),
                    [{"op": "add_custom_column", "name": "C", "expression": case["formula"]}],
                    initial_types=SPEC_TYPES,
                )
            except TransformationError:
                counts["refused"] += len(RAW_ROWS)
                self.assertIn(index, REFUSED_CASES, case["formula"])
                continue
            self.assertNotIn(index, REFUSED_CASES, case["formula"])
            for row_index, (row, cell) in enumerate(zip(result.rows, case["cells"])):
                stored = row["C"]
                if isinstance(stored, PowerQueryCellError):
                    counts["wrong"] += 1
                    wrong.append((index, row_index, repr(stored), cell))
                    continue
                if cell.startswith("ERR:"):
                    counts["wrong"] += 1
                    wrong.append((index, row_index, repr(stored), cell))
                    continue
                canonical = cell[2:]
                if stored_matches(stored, canonical):
                    counts["exact"] += 1
                else:
                    counts["wrong"] += 1
                    wrong.append((index, row_index, repr(stored), cell))
        print(f"\n26 formulas x 4 rows, typed cells: {counts}")
        self.assertEqual(wrong, [])
        self.assertEqual(counts["wrong"], 0)
        self.assertEqual(sum(counts.values()), 26 * len(RAW_ROWS))
        # Three formulas are refused (12 cells: an infinite number twice, and Value.Type of an Int64 cell); the
        # old-evaluator formula `??` is exact, so 92 of the 104 cells are exact.
        self.assertGreaterEqual(counts["exact"], 92)
        self.assertEqual(counts["refused"], 12)

    def test_types_inferred_from_the_text_match_the_spec_changed_type_step(self) -> None:
        self.assertEqual(infer_column_types(HEADERS, RAW_ROWS), SPEC_TYPES)

    def test_default_inference_gives_the_same_cells_as_the_explicit_types(self) -> None:
        spec = load_spec()
        for index, case in enumerate(spec["cases"]):
            if index in REFUSED_CASES:
                continue
            with_types = apply_transformations(
                base_candidate(),
                [{"op": "add_custom_column", "name": "C", "expression": case["formula"]}],
                initial_types=SPEC_TYPES,
            )
            inferred = apply_transformations(
                base_candidate(),
                [{"op": "add_custom_column", "name": "C", "expression": case["formula"]}],
            )
            self.assertEqual([row["C"] for row in with_types.rows], [row["C"] for row in inferred.rows], index)

    def test_a_logical_column_and_a_whole_number_column_are_typed_not_text(self) -> None:
        result = apply_transformations(
            base_candidate(),
            [
                {"op": "add_custom_column", "name": "Big", "expression": "[Units] > 1"},
                {"op": "add_custom_column", "name": "Two", "expression": "[Units] = 2"},
                {"op": "add_custom_column", "name": "Year", "expression": "Date.Year([Day])"},
                {"op": "add_custom_column", "name": "Yes", "expression": 'if [Flag] then "Y" else "N"'},
            ],
            initial_types=SPEC_TYPES,
        )
        self.assertEqual([row["Big"] for row in result.rows], ["true", "false", "true", "true"])
        self.assertEqual([row["Two"] for row in result.rows], ["true", "false", "false", "false"])
        self.assertEqual([row["Year"] for row in result.rows], ["2024", "2024", "2023", "2024"])
        self.assertEqual([row["Yes"] for row in result.rows], ["Y", "N", "Y", "N"])

    def test_a_cell_that_does_not_convert_refuses_only_the_formula_that_reads_it(self) -> None:
        rows = [dict(row) for row in RAW_ROWS]
        rows[1]["Units"] = "not a number"
        types = dict(SPEC_TYPES, Units="whole_number")
        result = apply_transformations(
            base_candidate(rows),
            [{"op": "add_custom_column", "name": "Label", "expression": '[Name] & "!"'}],
            initial_types=types,
        )
        self.assertEqual([row["Label"] for row in result.rows], ["Alpha!", "beta!", "!", "Gamma!"])
        with self.assertRaises(TransformationError) as raised:
            apply_transformations(
                base_candidate(rows),
                [{"op": "add_custom_column", "name": "Next", "expression": "[Units] + 1"}],
                initial_types=types,
            )
        self.assertTrue(str(raised.exception).startswith("Custom column formula: "))
        with self.assertRaises(TransformationError):
            apply_transformations(
                base_candidate(rows),
                [{"op": "add_custom_column", "name": "Next", "expression": "Text.From([Units])"}],
                initial_types=types,
            )

    def test_a_blank_text_cell_in_a_typed_column_is_a_null_that_equals_nothing(self) -> None:
        rows = [dict(row) for row in RAW_ROWS]
        rows[2]["Units"] = ""
        result = apply_transformations(
            base_candidate(rows),
            [{"op": "add_custom_column", "name": "Two", "expression": "[Units] = 2"}],
            initial_types=SPEC_TYPES,
        )
        # M's `=` never gives null for a null operand: null = 2 is false (the engine answers V:false for it).
        self.assertEqual(result.rows[2]["Two"], "false")

    def test_the_m_engine_sees_a_typed_cell_not_its_text(self) -> None:
        typed = {"Name": "Alpha", "Units": 2, "Price": Decimal("10.5"), "Day": None, "Flag": True}
        self.assertIs(evaluate_m_formula(compile_m_formula("[Units] = 2"), typed), True)
        self.assertIsNone(evaluate_m_formula(compile_m_formula("[Day]"), typed))
        # A cell that did not convert refuses the formula that reads it (MFormulaRefused, never a guessed value).
        with self.assertRaises(MFormulaRefused):
            evaluate_m_formula(compile_m_formula("[Units] + 1"), {**typed, "Units": UnconvertedCell("bad")})

    def test_real_app_types_an_imported_csv_before_custom_columns(self) -> None:
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication

        from analytics_studio.controller import StudioController
        from analytics_studio.file_import import parse_file
        from analytics_studio.local_table_dialogs import TransformDataDialog

        app = QApplication.instance() or QApplication(["Analytics Studio tests"])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "typed.csv"
            source.write_text(
                "Name,Units,Day\nAlpha,2,2024-01-15\nbeta,0,2024-02-29\nGamma,12,2024-06-01\n",
                encoding="utf-8",
            )
            controller = StudioController(app, QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat))
            raw = parse_file(source)
            self.assertTrue(controller._commit_import(source, raw))
            source_id = controller.activeTableId
            dialog = TransformDataDialog(raw)
            for name, formula in (
                ("Two", "[Units] = 2"),
                ("Year", "Date.Year([Day])"),
            ):
                dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData("add_custom_column"))
                dialog.value_edit.setText(name)
                dialog.custom_expression_edit.setPlainText(formula)
                dialog._add_step()
            self.assertEqual([row["Two"] for row in dialog._preview_candidate.rows], ["true", "false", "false"])
            self.assertEqual([row["Year"] for row in dialog._preview_candidate.rows], ["2024", "2024", "2024"])
            dialog._accept_candidate()
            self.assertTrue(controller._commit_transform_steps(
                source_id, dialog.steps, dialog.candidate, previewed_source=raw
            ))
            dialog.deleteLater()
            self.assertEqual([row["Two"] for row in controller._rows], ["true", "false", "false"])
            self.assertEqual([row["Year"] for row in controller._rows], ["2024", "2024", "2024"])


if __name__ == "__main__":
    unittest.main()
