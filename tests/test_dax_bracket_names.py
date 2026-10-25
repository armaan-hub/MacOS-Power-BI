"""DAX names that contain a closing bracket: ``[Net]] Sales]`` is the name ``Net] Sales``.

Inside ``[...]`` a ``]`` is written twice; ``'...'`` table names write ``'`` twice.  Every scanner of a ``[name]``
token must read the pair as part of the name and every writer of a ``[name]`` token must double the bracket.
(Power BI Desktop's own handling of ``]]`` was not re-observed live for this slice: it follows the documented
DAX lexical rule that the existing IntelliSense tests already assumed.)
"""

from __future__ import annotations

import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from analytics_studio import dax_intellisense
from analytics_studio.measures import (
    MeasureError,
    escape_bracket_name,
    evaluate_calculated_table,
    evaluate_measures,
    normalize_calculated_table_expression,
    normalize_measure,
    rename_table_references,
    tokenize,
)

COLUMN = "Net] Sales"
MEASURE = "A]B"


def reference(table: str, name: str) -> str:
    return f"{table}\0{name}"


def evaluate(measures: list[dict[str, str]], names: list[str] | None = None) -> dict:
    rows = [{COLUMN: "10", "Qty": "2"}, {COLUMN: "5", "Qty": "3"}]
    return evaluate_measures(
        measures, rows, [COLUMN, "Qty"], "T",
        measure_names=names or [item["name"] for item in measures],
    )


class TokenizerTests(unittest.TestCase):
    def kinds(self, text: str) -> list[tuple[str, str]]:
        return [(token.kind, token.value) for token in tokenize(text)]

    def test_doubled_bracket_is_part_of_the_name(self) -> None:
        self.assertEqual(self.kinds("[A]] B]"), [("reference", reference("", "A] B"))])

    def test_name_ending_in_a_doubled_bracket(self) -> None:
        self.assertEqual(self.kinds("[Total]]]"), [("reference", reference("", "Total]"))])

    def test_several_doubled_brackets(self) -> None:
        self.assertEqual(self.kinds("[A]]]]]"), [("reference", reference("", "A]]"))])
        self.assertEqual(self.kinds("[]]]"), [("reference", reference("", "]"))])

    def test_qualified_references(self) -> None:
        self.assertEqual(self.kinds("'T'[Net]] Sales]"), [("reference", reference("T", COLUMN))])
        self.assertEqual(self.kinds("T[Net]] Sales]"), [("reference", reference("T", COLUMN))])
        self.assertEqual(self.kinds("'It''s'[Qty]]]"), [("reference", reference("It's", "Qty]"))])

    def test_text_after_the_reference_is_still_tokenized(self) -> None:
        self.assertEqual(
            self.kinds("SUM(T[Net]] Sales]) + [A]]B]"),
            [("identifier", "SUM"), ("(", "("), ("reference", reference("T", COLUMN)), (")", ")"),
             ("+", "+"), ("reference", reference("", "A]B"))],
        )

    def test_ordinary_names_are_unchanged(self) -> None:
        self.assertEqual(self.kinds("[A] + [B]"), [
            ("reference", reference("", "A")), ("+", "+"), ("reference", reference("", "B"))])
        self.assertEqual(self.kinds("T[ Qty ]"), [("reference", reference("T", " Qty "))])
        self.assertEqual(self.kinds("[Net [USD]"), [("reference", reference("", "Net [USD"))])

    def test_malformed_input_errors_exactly_as_before(self) -> None:
        for text, message in [
            ("[abc", "Unsupported character at position 1."),
            ("[abc]]", "Unsupported character at position 6."),
            ("[a]] ", "Unsupported character at position 4."),
            ("]", "Unsupported character at position 1."),
            ("[]", "Unsupported character at position 1."),
            ("T[x", "Unsupported character at position 2."),
            ("[a\nb]", "Unsupported character at position 1."),
            ("[ ]", "A column reference cannot be empty."),
        ]:
            with self.subTest(text=text), self.assertRaises(MeasureError) as caught:
                tokenize(text)
            self.assertEqual(str(caught.exception), message)


class EvaluationTests(unittest.TestCase):
    def test_column_with_a_bracket_in_an_aggregate(self) -> None:
        result = evaluate([{"name": "M", "expression": "SUM('T'[Net]] Sales])"}])
        self.assertEqual(result["M"], Decimal(15))

    def test_unqualified_and_iterator_references(self) -> None:
        result = evaluate([
            {"name": "X", "expression": "SUMX(T, [Net]] Sales] * [Qty])"},
            {"name": "Y", "expression": "SUMX(T, T[Net]] Sales])"},
        ])
        self.assertEqual(result["X"], Decimal(10 * 2 + 5 * 3))
        self.assertEqual(result["Y"], Decimal(15))

    def test_measure_named_with_a_bracket(self) -> None:
        result = evaluate([
            {"name": MEASURE, "expression": "SUM('T'[Net]] Sales])"},
            {"name": "Twice", "expression": "[A]]B] * 2"},
            {"name": "Total]", "expression": "[A]]B] + 1"},
            {"name": "Last", "expression": "[Total]]]"},
        ])
        self.assertEqual(result[MEASURE], Decimal(15))
        self.assertEqual(result["Twice"], Decimal(30))
        self.assertEqual(result["Total]"], Decimal(16))
        self.assertEqual(result["Last"], Decimal(16))

    def test_a_missing_name_is_reported_with_the_unescaped_name(self) -> None:
        with self.assertRaises(MeasureError) as caught:
            evaluate([{"name": "M", "expression": "SUM('T'[Gross]] Sales])"}])
        self.assertIn("Gross] Sales", str(caught.exception))

    def test_measure_names_with_a_closing_bracket_are_accepted(self) -> None:
        self.assertEqual(normalize_measure("A]B", "1")["name"], "A]B")
        self.assertEqual(normalize_measure("Measure", "[A]] B] = 1")["name"], "A] B")
        for bad in ("A[B", "A\nB"):
            with self.subTest(bad=bad), self.assertRaises(MeasureError):
                normalize_measure(bad, "1")

    def test_ordinary_assignment_is_unchanged(self) -> None:
        item = normalize_measure("Measure", "[Total Sales] = SUM([Qty])")
        self.assertEqual((item["name"], item["expression"]), ("Total Sales", "SUM([Qty])"))

    def test_calculated_table_over_a_column_with_a_bracket(self) -> None:
        definition = normalize_calculated_table_expression(
            "DISTINCT('T'[Net]] Sales])", "T", [COLUMN, "Qty"])
        self.assertEqual(definition["column"], COLUMN)
        headers, rows = evaluate_calculated_table(
            definition["expression"],
            SimpleNamespace(headers=[COLUMN, "Qty"], rows=[{COLUMN: "10", "Qty": "2"}, {COLUMN: "10", "Qty": "3"}]),
            "T",
        )
        self.assertEqual(headers, [COLUMN])
        self.assertEqual(len(rows), 1)


class RenderTests(unittest.TestCase):
    NAMES = ["Sales", "Net] Sales", "Total]", "]", "]]", "A]]B", "a[b]c", "x ] y ]"]

    def test_escape_doubles_every_closing_bracket_only(self) -> None:
        self.assertEqual(escape_bracket_name("Sales"), "Sales")
        self.assertEqual(escape_bracket_name("Net] Sales"), "Net]] Sales")
        self.assertEqual(escape_bracket_name("Total]"), "Total]]")  # written as [Total]]]
        self.assertEqual(escape_bracket_name("a[b"), "a[b")

    def test_rendered_names_round_trip_through_the_tokenizer(self) -> None:
        for name in self.NAMES:
            with self.subTest(name=name):
                self.assertEqual(
                    tokenize(f"[{escape_bracket_name(name)}]")[0].value, reference("", name))
                self.assertEqual(
                    tokenize(f"'T'[{escape_bracket_name(name)}]")[0].value, reference("T", name))

    def test_rename_table_keeps_a_bracket_column_intact(self) -> None:
        self.assertEqual(
            rename_table_references("SUM('T'[Net]] Sales]) + [A]]B]", "T", "Orders"),
            "SUM('Orders'[Net]] Sales]) + [A]]B]",
        )
        self.assertEqual(
            rename_table_references("SUM(T[Qty]]]) + SUM(T[Net]] Sales])", "T", "O'Neil"),
            "SUM('O''Neil'[Qty]]]) + SUM('O''Neil'[Net]] Sales])",
        )

    def test_a_bracket_name_that_looks_like_a_table_is_not_renamed(self) -> None:
        self.assertEqual(rename_table_references("[T]] x]", "T", "U"), "[T]] x]")


class IntelliSenseTests(unittest.TestCase):
    MODEL = {
        "home_table": "T",
        "tables": [{"name": "T", "columns": [
            {"name": COLUMN, "type": "number"}, {"name": "Qty", "type": "number"}]}],
        "measures": [{"name": MEASURE, "table": "T", "type": "number"}],
    }

    def item(self, text: str, label: str, caret: int | None = None) -> dict:
        items = dax_intellisense.complete(text, len(text) if caret is None else caret, self.MODEL)
        return next(item for item in items if item["label"] == label)

    def test_column_insertion_is_escaped_and_reparses_to_the_same_name(self) -> None:
        text = "SUM(T[Net"
        new_text, _caret = dax_intellisense.apply_completion(text, self.item(text, COLUMN))
        self.assertEqual(new_text, "SUM(T[Net]] Sales]")
        self.assertEqual(tokenize(new_text + ")")[2].value, reference("T", COLUMN))

    def test_measure_insertion_is_escaped_and_reparses_to_the_same_name(self) -> None:
        text = "A"
        new_text, caret = dax_intellisense.apply_completion(text, self.item(text, MEASURE))
        self.assertEqual(new_text, "[A]]B]")
        self.assertEqual(caret, len(new_text))
        self.assertEqual(tokenize(new_text)[0].value, reference("", MEASURE))

    def test_caret_after_an_escaped_pair_stays_inside_the_name(self) -> None:
        text = "SUM(T[Net]] S"
        labels = [item["label"] for item in dax_intellisense.complete(text, len(text), self.MODEL)]
        self.assertEqual(labels, [COLUMN])

    def test_a_finished_reference_is_not_inside_a_bracket(self) -> None:
        text = "SUM(T[Net]] Sales]) + "
        self.assertEqual(dax_intellisense._scan(text, len(text)).state, "normal")

    def test_name_ending_in_a_doubled_bracket_is_scanned_to_its_closer(self) -> None:
        text = "[Total]]]"
        self.assertEqual(dax_intellisense._scan(text, len(text)).state, "normal")
        text = "[Total]]"
        self.assertEqual(dax_intellisense._scan(text, len(text)).state, "bracket")


class EditorHelpersTests(unittest.TestCase):
    def test_reference_completion_context_reads_the_doubled_bracket(self) -> None:
        from analytics_studio.measure_dialog import _dax_reference_completion_context

        text = "SUM('T'[Net]] S"
        kind, prefix, start, end, table, has_closer = _dax_reference_completion_context(text, len(text))
        self.assertEqual((kind, prefix, table, has_closer), ("reference", "Net] S", "T", False))
        self.assertEqual((text[start:end]), "Net]] S")

        text = "SUM('T'[Net]] S])"
        position = len("SUM('T'[Net]] S")
        kind, prefix, start, end, table, has_closer = _dax_reference_completion_context(text, position)
        self.assertEqual((prefix, table, has_closer), ("Net] S", "T", True))
        self.assertEqual(text[start:end], "Net]] S")

    def test_reference_completion_context_ordinary_names_unchanged(self) -> None:
        from analytics_studio.measure_dialog import _dax_reference_completion_context

        text = "SUM('T'[Qt"
        self.assertEqual(
            _dax_reference_completion_context(text, len(text)),
            ("reference", "Qt", 8, 10, "T", False),
        )

    def test_lexical_state_skips_doubled_brackets(self) -> None:
        from analytics_studio.measure_dialog import _dax_lexical_state

        text = "SUM('T'[Net]] Sales], "
        safe, stack = _dax_lexical_state(text, len(text))
        self.assertTrue(safe)
        self.assertEqual([entry[:2] for entry in stack], [["SUM", 1]])
        text = "SUMX(T, [A]]B], "
        safe, stack = _dax_lexical_state(text, len(text))
        self.assertTrue(safe)
        self.assertEqual(stack[-1][1], 2)  # a comma inside the name would make it 3

    def test_template_arguments_skip_doubled_brackets(self) -> None:
        from analytics_studio.measure_dialog import _template_arguments

        self.assertEqual(
            _template_arguments("F(T[a]], b], c)"), ["T[a]], b]", "c"])

    def test_field_reference_parts_read_escaped_columns(self) -> None:
        from analytics_studio.measure_dialog import _dax_field_reference_parts

        self.assertEqual(_dax_field_reference_parts("'T'[Net]] Sales]"), ("T", COLUMN))
        self.assertEqual(_dax_field_reference_parts("'O''Neil'[Qty]]]"), ("O'Neil", "Qty]"))
        self.assertEqual(_dax_field_reference_parts("'T'[Qty]"), ("T", "Qty"))
        self.assertIsNone(_dax_field_reference_parts("'T'[Qty]x"))


class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication(["bracket names"])

    def test_quick_measure_escapes_the_column(self) -> None:
        from analytics_studio.measure_dialog import MeasureDialog

        dialog = MeasureDialog(
            [COLUMN], [], quick=True, default_column=COLUMN, quick_table_name="T",
            quick_table_display_name="T",
        )
        dialog._accept_measure()
        self.assertIsNotNone(dialog.measure)
        self.assertEqual(dialog.measure["expression"], "SUM('T'[Net]] Sales])")
        self.assertEqual(tokenize(dialog.measure["expression"])[2].value, reference("T", COLUMN))
        dialog.deleteLater()

    def test_model_field_pickers_offer_the_escaped_reference(self) -> None:
        from analytics_studio.controller import StudioController
        from PySide6.QtCore import QSettings

        with tempfile.TemporaryDirectory() as root:
            settings = QSettings(str(Path(root) / "settings.ini"), QSettings.Format.IniFormat)
            self._check_pickers(StudioController(self.app, settings))

    def _check_pickers(self, controller) -> None:
        from analytics_studio.inline_data import parse_pasted_table

        self.assertTrue(controller._commit_inline(parse_pasted_table("Net] Sales\n10\n5", name="T")))
        references = controller._dax_field_references()
        self.assertIn(("T[Net] Sales]", "'T'[Net]] Sales]"), references)
        self.assertEqual(
            controller._preview_measure_expression("Total", "SUM('T'[Net]] Sales])"), "15")


if __name__ == "__main__":
    unittest.main()
