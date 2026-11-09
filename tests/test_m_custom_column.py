"""Custom columns with Power Query M formulas: the M engine answers, or the step is refused.

Spec: docs/plans/2026-11-09-m-wire-99-spec.json (48 formulas measured on Power BI Desktop over a fixed 4-row
table). The spec is read only by this test; the app code never reads it.

Formulas the small evaluator accepts keep that evaluator (see OLD_PATH_* below). Formulas it rejects go to the
M engine, where every cell must be Power BI's cell or the whole step must be refused.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from analytics_studio.file_import import ImportCandidate
from analytics_studio.m_custom_column import (
    MFormulaRefused,
    cell_to_m,
    compile_m_formula,
    evaluate_m_formula,
    m_to_cell,
    usable_m_formula,
)
from analytics_studio.m_engine import values as V
from analytics_studio.m_engine.canonical import to_canonical
from analytics_studio.power_query_expression import (
    ExpressionError as PowerQueryExpressionError,
    ExpressionError,
    compile_expression,
    evaluate_expression,
    expression_value_to_text,
)
from analytics_studio.power_query_values import PowerQueryCellError
from analytics_studio.transformations import TransformationError, apply_transformations

SPEC_PATH = Path(__file__).resolve().parents[1] / "docs" / "plans" / "2026-11-09-m-wire-99-spec.json"

SPEC_ROWS = [
    {"Name": "Alpha", "Amount": Decimal("120.5"), "Qty": Decimal(3), "Day": date(2024, 1, 15), "Code": "A-01"},
    {"Name": "beta", "Amount": Decimal("-40"), "Qty": Decimal(0), "Day": date(2024, 2, 29), "Code": "B-22"},
    {"Name": None, "Amount": Decimal("0.1"), "Qty": Decimal(7), "Day": None, "Code": ""},
    {"Name": "Gamma Ray", "Amount": Decimal("1000000"), "Qty": Decimal(-2), "Day": date(2023, 12, 31), "Code": "C-3"},
]
SPEC_HEADERS = ["Name", "Amount", "Qty", "Day", "Code"]

# Formulas the M engine cannot compile (here `??`, which its parser lacks) keep the small evaluator. Every other
# spec formula goes to the M engine first, even when the small evaluator also accepts it.
OLD_ONLY_CASES = (30, 38)

# Step-level refusals (nothing is stored): 1 and 31 give an infinite number, 13 a duration, 15 and 37 lists, 36 a
# function, 33 a column the table does not have.
REFUSED_STEP_CASES = frozenset({1, 13, 15, 31, 33, 36, 37})


def load_spec() -> dict:
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def spec_cell(text: str) -> tuple:
    """('V', canonical) or ('ERR', reason, message) from one spec cell."""
    if text.startswith("ERR:"):
        reason, message = text[4:].split(": ", 1)
        return ("ERR", reason, message)
    return ("V", text[2:])


def is_old_path(formula: str) -> bool:
    try:
        compile_expression(formula, allowed_symbols=set(), function_names=set())
    except ExpressionError:
        return False
    return True


def candidate(rows: list[dict] | None = None) -> ImportCandidate:
    return ImportCandidate(
        "inline", list(SPEC_HEADERS), [dict(row) for row in (rows or SPEC_ROWS)],
        {"source_id": "task109-spec-table"}, [],
    )


def judge(got, expected: tuple) -> bool:
    """Whether one row's answer (a cell value or PowerQueryCellError) matches Power BI's spec cell."""
    if isinstance(got, PowerQueryCellError):
        return expected[0] == "ERR" and (got.reason, got.message) == (expected[1], expected[2])
    return expected[0] == "V" and to_canonical(cell_to_m(got)) == expected[1]


class MCustomColumnTests(unittest.TestCase):
    def test_spec_loads_and_covers_forty_eight_formulas(self) -> None:
        spec = load_spec()
        self.assertEqual(len(spec["cases"]), 48)
        for case in spec["cases"]:
            self.assertEqual(len(case["cells"]), len(SPEC_ROWS))

    def test_every_spec_cell_is_exact_or_refused_never_wrong(self) -> None:
        spec = load_spec()
        counts = {"exact": 0, "refused": 0, "wrong": 0}
        wrong: list[tuple[int, int]] = []
        old_only: list[int] = []
        for index, case in enumerate(spec["cases"]):
            try:
                apply_transformations(candidate(), [
                    {"op": "add_custom_column", "name": "C", "expression": case["formula"]},
                ])
            except TransformationError:
                counts["refused"] += len(SPEC_ROWS)
                continue
            compiled = usable_m_formula(case["formula"])
            if compiled is None:
                old_only.append(index)
                old = compile_expression(case["formula"], allowed_symbols=set(), function_names=set())
            for row_index, (row, cell) in enumerate(zip(SPEC_ROWS, case["cells"])):
                try:
                    if compiled is not None:
                        got = evaluate_m_formula(compiled, dict(row))
                    else:
                        got = evaluate_expression(old, dict(row), {}, {})
                except MFormulaRefused:
                    counts["refused"] += 1
                    continue
                except ExpressionError as exc:
                    got = PowerQueryCellError(reason="Expression.Error", message=str(exc))
                if judge(got, spec_cell(cell)):
                    counts["exact"] += 1
                else:
                    counts["wrong"] += 1
                    wrong.append((index, row_index))
        print(f"\nAll 48 formulas, 4 rows each: {counts}")
        self.assertEqual(wrong, [])
        self.assertEqual(tuple(old_only), OLD_ONLY_CASES)
        self.assertEqual(sum(counts.values()), 48 * len(SPEC_ROWS))
        self.assertGreaterEqual(counts["exact"], 150)

    def test_the_m_engine_answers_first_even_when_the_small_evaluator_accepts_the_formula(self) -> None:
        spec = load_spec()
        # Formulas the small evaluator also accepts, where it differs from Power BI (28-digit division, decimal
        # scale, error text): the stored value must be the M engine's, which is Power BI's.
        for index in (2, 3, 34):
            case = spec["cases"][index]
            self.assertTrue(is_old_path(case["formula"]), index)
            self.assertIsNotNone(usable_m_formula(case["formula"]), index)
            result = apply_transformations(candidate(), [
                {"op": "add_custom_column", "name": "C", "expression": case["formula"]},
            ])
            compiled = compile_m_formula(case["formula"])
            for row, source in zip(result.rows, SPEC_ROWS):
                got = evaluate_m_formula(compiled, dict(source))
                if isinstance(got, PowerQueryCellError):
                    self.assertEqual((row["C"].reason, row["C"].message), (got.reason, got.message), index)
                else:
                    self.assertEqual(row["C"], expression_value_to_text(got), index)

    def test_a_step_that_gives_an_infinite_number_or_a_container_is_refused_not_guessed(self) -> None:
        spec = load_spec()
        for index in sorted(REFUSED_STEP_CASES):
            with self.assertRaises(TransformationError, msg=index):
                apply_transformations(candidate(), [
                    {"op": "add_custom_column", "name": "C", "expression": spec["cases"][index]["formula"]},
                ])

    def test_m_path_formulas_end_to_end_store_only_power_bi_answers_or_refuse(self) -> None:
        spec = load_spec()
        for index, case in enumerate(spec["cases"]):
            compiled = usable_m_formula(case["formula"])
            if compiled is None or index in REFUSED_STEP_CASES:
                continue
            expected_rows = []
            refused = False
            for row, cell in zip(SPEC_ROWS, case["cells"]):
                try:
                    got = evaluate_m_formula(compiled, dict(row))
                except MFormulaRefused:
                    refused = True
                    break
                expected_rows.append((got, cell))
            if refused:
                with self.assertRaises(TransformationError) as raised:
                    apply_transformations(candidate(), [
                        {"op": "add_custom_column", "name": "C", "expression": case["formula"]},
                    ])
                self.assertTrue(str(raised.exception).startswith("Custom column formula: "), index)
                continue
            result = apply_transformations(candidate(), [
                {"op": "add_custom_column", "name": "C", "expression": case["formula"]},
            ])
            for row, (got, cell) in zip(result.rows, expected_rows):
                stored = row["C"]
                if isinstance(got, PowerQueryCellError):
                    self.assertIsInstance(stored, PowerQueryCellError, index)
                    self.assertEqual((stored.reason, stored.message), (got.reason, got.message), index)
                    self.assertEqual(stored.target_type, "text", index)
                    self.assertIsNotNone(stored.row, index)
                else:
                    self.assertEqual(stored, expression_value_to_text(got) if got is not None else None, index)
                if not isinstance(got, PowerQueryCellError):
                    self.assertTrue(judge(got, spec_cell(cell)), index)

    def test_refused_formulas_never_store_a_guessed_value(self) -> None:
        for formula in (
            "{[Qty], [Amount]}",        # list result
            "[Day] - #date(2024,1,1)",  # duration result
            "each 1",                   # function result
        ):
            if is_old_path(formula):
                continue
            with self.assertRaises(TransformationError, msg=formula):
                apply_transformations(candidate(), [
                    {"op": "add_custom_column", "name": "C", "expression": formula},
                ])

    def test_non_finite_and_unsupported_engine_gaps_are_refused(self) -> None:
        # Power BI gives -Infinity here; a custom-column cell cannot hold a non-finite number.
        with self.assertRaises(TransformationError):
            apply_transformations(candidate(), [
                {"op": "add_custom_column", "name": "C", "expression": "try [Amount] / 0 otherwise -1"},
            ])
        # An engine gap is not turned into a value by try/otherwise (it is refused before evaluation).
        with self.assertRaises(TransformationError):
            apply_transformations(candidate(), [
                {"op": "add_custom_column", "name": "C", "expression": "Date.IsInNextNDays([Day], 5)"},
            ])

    def test_app_parameter_inside_m_formula_is_refused(self) -> None:
        with self.assertRaises(TransformationError):
            apply_transformations(
                candidate(),
                [{"op": "add_custom_column", "name": "C", "expression": "Text.Split([Code], Delim){0}"}],
                parameters={"Delim": "-"},
            )

    def test_syntax_error_in_both_evaluators_raises_the_original_error(self) -> None:
        with self.assertRaises(PowerQueryExpressionError):
            compile_m_formula("[Amount] +")
        with self.assertRaises(TransformationError) as raised:
            apply_transformations(candidate(), [
                {"op": "add_custom_column", "name": "C", "expression": "Text.Split([Code], \"-\") +"},
            ])
        self.assertTrue(str(raised.exception).startswith("Custom column formula"))

    def test_typed_output_type_applies_to_m_results(self) -> None:
        result = apply_transformations(candidate(), [
            {"op": "add_custom_column", "name": "Next", "expression": "Date.AddMonths([Day], 1)",
             "output_type": "date"},
            {"op": "add_custom_column", "name": "Sq", "expression": "Number.Power([Qty], 2)",
             "output_type": "whole_number"},
        ])
        self.assertEqual(result.rows[0]["Next"], date(2024, 2, 15))
        self.assertIsNone(result.rows[2]["Next"])
        self.assertEqual(result.rows[0]["Sq"], Decimal(9))
        self.assertEqual(result.rows[3]["Sq"], Decimal(4))

    def test_round_trip_between_cells_and_m_values(self) -> None:
        self.assertEqual(to_canonical(cell_to_m(Decimal("126.520"))), "number:126.520")
        self.assertEqual(to_canonical(cell_to_m(Decimal("-40"))), "number:-40")
        self.assertEqual(to_canonical(cell_to_m(None)), "null")
        self.assertEqual(to_canonical(cell_to_m(True)), "true")
        self.assertEqual(to_canonical(cell_to_m(date(2024, 1, 15))), "date:2024-01-15")
        self.assertEqual(to_canonical(cell_to_m(time(12, 0, 0))), "time:12:00:00.0000000")
        self.assertEqual(m_to_cell(V.Number(0.1)), Decimal("0.1"))
        self.assertIsNone(m_to_cell(V.Null()))
        self.assertEqual(m_to_cell(V.Text("x")), "x")
        self.assertEqual(
            m_to_cell(V.DateTime(0)), datetime(1, 1, 1, 0, 0)
        )
        with self.assertRaises(MFormulaRefused):
            m_to_cell(V.Number(float("inf")))
        with self.assertRaises(MFormulaRefused):
            m_to_cell(V.Record(()))

    def test_cell_error_is_raised_when_the_m_formula_reads_it(self) -> None:
        error_row = dict(SPEC_ROWS[0])
        error_row["Qty"] = PowerQueryCellError(reason="Expression.Error", message="bad quantity")
        compiled = compile_m_formula("[Qty] + 1")
        got = evaluate_m_formula(compiled, error_row)
        self.assertIsInstance(got, PowerQueryCellError)
        self.assertEqual((got.reason, got.message), ("Expression.Error", "bad quantity"))

    def test_try_otherwise_cannot_turn_an_engine_gap_into_a_value(self) -> None:
        # The engine has no measured answer for this culture: try ... otherwise must not hide that behind "x".
        for formula in (
            'try Number.ToText([Amount], "F1", "fr-FR") otherwise "x"',
            'try Number.ToText([Amount], "F1", "fr-FR") catch (e) => "x"',
        ):
            compiled = compile_m_formula(formula)
            with self.assertRaises(MFormulaRefused, msg=formula):
                evaluate_m_formula(compiled, dict(SPEC_ROWS[0]))
            with self.assertRaises(TransformationError, msg=formula):
                apply_transformations(candidate(), [
                    {"op": "add_custom_column", "name": "C", "expression": formula},
                ])
        # A genuine Power BI error inside try is still caught.
        got = evaluate_m_formula(
            compile_m_formula('try Text.From([Amount], "zz") otherwise "x"'), dict(SPEC_ROWS[0])
        )
        self.assertEqual(got, "x")
        got = evaluate_m_formula(compile_m_formula('try Text.Upper([Amount]) otherwise "none"'), dict(SPEC_ROWS[0]))
        self.assertEqual(got, "none")

    def test_m_only_steps_round_trip_through_the_step_list_and_the_m_script(self) -> None:
        from analytics_studio.power_query_m import parse_m_script, steps_to_m_script
        from analytics_studio.transformations import validate_steps

        step = {"op": "add_custom_column", "name": "Head", "expression": 'Text.Split([Code], "-"){0}'}
        self.assertEqual(validate_steps([step]), [step])
        script = steps_to_m_script([step], "Codes")
        self.assertIn('Table.AddColumn(Source, "Head", each Text.From(Text.Split([Code], "-"){0}), type text)', script)
        self.assertEqual(parse_m_script(script, "Codes"), [step])
        # A formula neither evaluator can run is still rejected.
        with self.assertRaises(TransformationError):
            validate_steps([{"op": "add_custom_column", "name": "X", "expression": "Text.Split([Code], \"-\") +"}])

    def test_real_app_adds_saves_reopens_and_refreshes_m_only_custom_columns(self) -> None:
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication

        from analytics_studio.controller import StudioController
        from analytics_studio.file_import import parse_file
        from analytics_studio.local_table_dialogs import TransformDataDialog

        app = QApplication.instance() or QApplication(["Analytics Studio tests"])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "codes.csv"
            source.write_text("Product,Code,Day\nWidget,A-01,2024-01-15\npear,B-22,2024-02-29\nberry,C-3,2023-12-31\n",
                              encoding="utf-8")
            controller = StudioController(app, QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat))
            raw = parse_file(source)
            self.assertTrue(controller._commit_import(source, raw))
            source_id = controller.activeTableId
            dialog = TransformDataDialog(raw)
            for name, formula in (
                ("Head", 'Text.Split([Code], "-"){0}'),
                ("Month", "Date.MonthName(Date.From([Day]))"),
            ):
                dialog.operation_combo.setCurrentIndex(dialog.operation_combo.findData("add_custom_column"))
                dialog.value_edit.setText(name)
                dialog.custom_expression_edit.setPlainText(formula)
                dialog._add_step()
            self.assertEqual([row["Head"] for row in dialog._preview_candidate.rows], ["A", "B", "C"])
            self.assertEqual([row["Month"] for row in dialog._preview_candidate.rows],
                             ["January", "February", "December"])
            dialog._accept_candidate()
            self.assertTrue(controller._commit_transform_steps(
                source_id, dialog.steps, dialog.candidate, previewed_source=raw
            ))
            dialog.deleteLater()

            project = root / "m-columns.npa"
            self.assertTrue(controller._save_to(project))
            source.write_text("Product,Code,Day\nmug,D-9,2024-03-01\ncup,E-10,2024-04-30\n", encoding="utf-8")
            reopened = StudioController(app, QSettings(str(root / "reopened.ini"), QSettings.Format.IniFormat))
            self.assertTrue(reopened.open_project_path(project))
            self.assertEqual([row["Head"] for row in reopened._rows], ["D", "E"])
            self.assertEqual([row["Month"] for row in reopened._rows], ["March", "April"])
            source.write_text("Product,Code,Day\nbook,F-7,2024-05-02\n", encoding="utf-8")
            reopened.refresh_source()
            self.assertEqual([row["Head"] for row in reopened._rows], ["F"])
            self.assertEqual([row["Month"] for row in reopened._rows], ["May"])


if __name__ == "__main__":
    unittest.main()
