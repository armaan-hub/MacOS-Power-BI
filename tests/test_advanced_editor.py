"""Advanced Editor: generated M correctness, Power BI step names and a real editable editor."""

from __future__ import annotations

import os
import random
import re
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QKeySequence, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QToolButton

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import TransformDataDialog
from analytics_studio.power_query_m import (
    PowerQueryMEditorDialog,
    PowerQueryMScriptError,
    m_script_matches_steps,
    parse_m_query_script,
    steps_to_m_script,
)
from analytics_studio.power_query_step_names import assign_step_names, power_bi_step_name
from analytics_studio.transformations import TransformationError, apply_transformations

BINDING = re.compile(r'^\s{4}(#"(?:[^"]|"")*"|[A-Za-z_][A-Za-z0-9_]*) = (.*)$')


def bindings_of(script: str) -> tuple[list[tuple[str, str]], str]:
    lines = script.splitlines()
    in_at = lines.index("in")
    pairs = []
    for line in lines[1:in_at]:
        match = BINDING.match(line.rstrip(","))
        assert match, line
        pairs.append((match.group(1), match.group(2)))
    return pairs, lines[in_at + 1].strip()


def assert_linear_chain(test: unittest.TestCase, script: str) -> list[str]:
    pairs, output = bindings_of(script)
    test.assertEqual(pairs[0][0], "Source")
    for index in range(1, len(pairs)):
        previous = pairs[index - 1][0]
        test.assertIn(f"({previous},", pairs[index][1], script)
    test.assertEqual(output, pairs[-1][0], script)
    names = [name for name, _ in pairs]
    test.assertEqual(len(set(name.casefold() for name in names)), len(names))
    return names


def make_source() -> ImportCandidate:
    headers = ["Column1", "Column2", "Column3", "Column4", "Amount", "Region"]
    rows = [
        {"Column1": f"a{i}", "Column2": f"b{i}", "Column3": f"c{i}", "Column4": f"d{i}",
         "Amount": str(10 * i), "Region": "East" if i % 2 else "West"}
        for i in range(1, 7)
    ]
    return ImportCandidate("inline", headers, rows, {}, [])


class AdvancedEditorBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["Advanced Editor tests"])


class GeneratedMTests(AdvancedEditorBase):
    def test_three_removals_through_the_dialog_chain_and_match_the_preview(self) -> None:
        dialog = TransformDataDialog(make_source(), query_name="Sheet_1")
        dialog.resize(1300, 800)
        dialog.show()
        self.app.processEvents()
        for column in ("Column2", "Column3", "Column4"):
            index = dialog._preview_candidate.headers.index(column)
            dialog.preview.selectColumn(index)
            dialog.preview.setCurrentIndex(dialog.preview.model().index(0, index))
            dialog.ribbon_command_buttons["remove_column"].click()
            self.app.processEvents()
        self.assertEqual(
            [dialog.step_list.item(i).text() for i in range(dialog.step_list.count())],
            ["Removed Columns", "Removed Columns1", "Removed Columns2"],
        )
        self.assertEqual(
            [step["column"] for step in dialog._steps], ["Column2", "Column3", "Column4"]
        )
        shown: list[str] = []

        def capture(editor: PowerQueryMEditorDialog) -> QDialog.DialogCode:
            shown.append(editor.editor.toPlainText())
            return QDialog.DialogCode.Rejected

        with patch.object(PowerQueryMEditorDialog, "exec", new=capture):
            dialog._open_advanced_editor()
        script = shown[0]
        names = assert_linear_chain(self, script)
        self.assertEqual(
            names, ['Source', '#"Removed Columns"', '#"Removed Columns1"', '#"Removed Columns2"']
        )
        self.assertIn('Table.RemoveColumns(#"Removed Columns1", {"Column4"})', script)
        _sources, parsed = parse_m_query_script(script, "Sheet_1")
        replay = apply_transformations(make_source(), parsed)
        self.assertEqual(replay.rows, dialog._preview_candidate.rows)
        self.assertEqual(replay.headers, dialog._preview_candidate.headers)
        dialog.deleteLater()

    def test_step_names_follow_power_bi(self) -> None:
        cases = {
            "remove_column": "Removed Columns", "rename_column": "Renamed Columns",
            "filter_rows": "Filtered Rows", "filter_rows_advanced": "Filtered Rows",
            "sort_rows": "Sorted Rows", "convert_type": "Changed Type",
            "promote_headers": "Promoted Headers", "add_custom_column": "Added Custom",
            "conditional_column": "Added Conditional Column",
            "replace_value": "Replaced Value", "split_column": "Split Column by Delimiter",
            "keep_columns": "Removed Other Columns",
        }
        for op, expected in cases.items():
            self.assertEqual(power_bi_step_name({"op": op}), expected, op)
        steps = [{"op": "remove_column"}] * 3 + [{"op": "filter_rows"}, {"op": "remove_column"}]
        self.assertEqual(
            assign_step_names(steps, reserved=["Source"]),
            ["Removed Columns", "Removed Columns1", "Removed Columns2",
             "Filtered Rows", "Removed Columns3"],
        )
        self.assertEqual(
            assign_step_names([{"op": "filter_rows"}] * 2, custom_names=["Filtered Rows", ""],
                              reserved=["Source"]),
            ["Filtered Rows", "Filtered Rows1"],
        )

    def test_conditional_column_m_is_an_if_then_else_with_bare_literals(self) -> None:
        step = {
            "op": "conditional_column", "name": "Label",
            "clauses": [{
                "column": "Region", "operator": "equals", "test_value": "East",
                "test_value_kind": "value", "output": "five", "output_kind": "value",
            }],
            "else_value": "Column1", "else_kind": "column",
        }
        script = steps_to_m_script([step], "Sheet_1")
        self.assertIn(
            'Table.AddColumn(Source, "Label", each if [Region] = "East" then "five" '
            'else [Column1], type text)', script,
        )
        self.assertNotIn("Text.From", script)
        self.assertIn('#"Added Conditional Column"', script)
        _sources, parsed = parse_m_query_script(script, "Sheet_1")
        self.assertEqual(parsed, [step])
        self.assertEqual(
            apply_transformations(make_source(), parsed).rows[0]["Label"], "five"
        )
        self.assertEqual(apply_transformations(make_source(), parsed).rows[1]["Label"], "a2")

    def test_legacy_step_n_scripts_still_match_their_steps(self) -> None:
        legacy = (
            'let\n    Source = #"Sheet_1",\n'
            '    #"Step 1" = Table.RemoveColumns(Source, {"Column2"}),\n'
            '    #"Step 2" = Table.RemoveColumns(#"Step 1", {"Column3"})\n'
            'in\n    #"Step 2"'
        )
        steps = [{"op": "remove_column", "column": "Column2"},
                 {"op": "remove_column", "column": "Column3"}]
        self.assertTrue(m_script_matches_steps(legacy, "Sheet_1", steps))
        dialog = PowerQueryMEditorDialog(make_source(), steps, "Sheet_1", initial_script=legacy)
        self.assertEqual(dialog.editor.toPlainText(), legacy)
        dialog.deleteLater()

    def test_the_reported_broken_script_is_rejected_with_a_line_number(self) -> None:
        broken = (
            'let\n    Source = #"Sheet_1",\n'
            '    #"Step 1" = Table.RemoveColumns(Source, {"Column2"}),\n'
            '    #"Step 2" = Table.RemoveColumns(#"Step 1", {"Column3"}),\n'
            '    #"Step 3" = Table.RemoveColumns(#"Step 1", {"Column4"})\n'
            'in\n    #"Step 4"'
        )
        with self.assertRaises(PowerQueryMScriptError) as caught:
            parse_m_query_script(broken, "Sheet_1")
        self.assertEqual(caught.exception.line, 5)
        self.assertGreaterEqual(caught.exception.column, 1)

    def test_random_step_sequences_chain_round_trip_and_match_preview(self) -> None:
        rng = random.Random(84)
        source = make_source()
        checked = 0
        for _ in range(300):
            steps: list[dict] = []
            headers = list(source.headers)
            for _step in range(rng.randint(1, 8)):
                kind = rng.choice(["remove", "rename", "filter", "sort", "type"])
                if kind == "remove" and len(headers) > 2:
                    column = rng.choice(headers)
                    steps.append({"op": "remove_column", "column": column})
                    headers.remove(column)
                elif kind == "rename":
                    column = rng.choice(headers)
                    new = f"R{rng.randint(0, 9999)}"
                    steps.append({"op": "rename_column", "column": column, "new_name": new})
                    headers[headers.index(column)] = new
                elif kind == "filter":
                    steps.append({"op": "filter_rows", "column": rng.choice(headers),
                                  "operator": "not_equals", "value": "zzz"})
                elif kind == "sort":
                    steps.append({"op": "sort_rows", "column": rng.choice(headers),
                                  "direction": rng.choice(["asc", "desc"])})
                else:
                    steps.append({"op": "convert_type", "column": rng.choice(headers),
                                  "type": "text"})
            try:
                expected = apply_transformations(source, steps)
            except TransformationError:
                continue
            script = steps_to_m_script(steps, "Sheet_1")
            names = assert_linear_chain(self, script)
            self.assertEqual(len(names), len(steps) + 1)
            _sources, parsed = parse_m_query_script(script, "Sheet_1")
            replay = apply_transformations(source, parsed)
            self.assertEqual(replay.headers, expected.headers)
            self.assertEqual(replay.rows, expected.rows)
            self.assertTrue(m_script_matches_steps(script, "Sheet_1", steps))
            checked += 1
        self.assertGreater(checked, 200)


class EditorWindowTests(AdvancedEditorBase):
    def editor(self, steps=None, script=None) -> PowerQueryMEditorDialog:
        dialog = PowerQueryMEditorDialog(
            make_source(), steps or [], "Sheet_1", initial_script=script
        )
        dialog.show()
        self.app.processEvents()
        return dialog

    def test_window_chrome_matches_power_bi(self) -> None:
        dialog = self.editor()
        self.assertEqual(dialog.windowTitle(), "Advanced Editor")
        self.assertEqual(dialog.query_name_label.text(), "Sheet_1")
        self.assertEqual(dialog.done_button.text(), "Done")
        self.assertEqual(dialog.cancel_button.text(), "Cancel")
        self.assertFalse(dialog.editor.isReadOnly())
        self.assertTrue(dialog.editor.font().fixedPitch() or "mono" in dialog.editor.font().family().lower()
                        or dialog.editor.font().styleHint() == dialog.editor.font().StyleHint.Monospace)
        self.assertEqual(dialog.status_label.text(), "✓ No syntax errors have been detected.")
        self.assertIn("#1a7f37", dialog.status_label.styleSheet())
        self.assertTrue(dialog.done_button.isEnabled())
        self.assertFalse(hasattr(dialog, "preview_button"))
        dialog.deleteLater()

    def test_typing_edits_the_text_and_validates_live(self) -> None:
        dialog = self.editor()
        dialog.editor.moveCursor(QTextCursor.MoveOperation.End)
        QTest.keyClicks(dialog.editor, " x")  # real keystrokes reach the editor
        self.assertTrue(dialog.editor.toPlainText().endswith("Source x"))
        self.assertFalse(dialog.done_button.isEnabled())
        self.assertIn("#a4262c", dialog.status_label.styleSheet())
        QTest.keyClick(dialog.editor, Qt.Key.Key_Backspace)
        QTest.keyClick(dialog.editor, Qt.Key.Key_Backspace)
        self.assertTrue(dialog.done_button.isEnabled())
        self.assertEqual(dialog.status_label.text(), "✓ No syntax errors have been detected.")
        dialog.deleteLater()

    def test_syntax_error_reports_line_and_column_in_red(self) -> None:
        dialog = self.editor()
        dialog.editor.setPlainText(
            'let\n    Source = #"Sheet_1",\n'
            '    A = Table.RemoveColumns(Source, {"Column2"}),\n'
            '    B = Table.RemoveColumns(Source, {"Column3"})\nin\n    B'
        )
        self.assertFalse(dialog.done_button.isEnabled())
        self.assertIn("line 4", dialog.status_label.text().lower())
        self.assertIn("column", dialog.status_label.text().lower())
        self.assertIn("preceding step", dialog.status_label.text())
        self.assertIn("#a4262c", dialog.status_label.styleSheet())
        dialog.deleteLater()

    def test_tab_indents_with_spaces_and_undo_redo_work(self) -> None:
        dialog = self.editor()
        dialog.editor.setPlainText("")
        dialog.editor.document().clearUndoRedoStacks()
        QTest.keyClick(dialog.editor, Qt.Key.Key_Tab)
        self.assertEqual(dialog.editor.toPlainText(), "    ")
        QTest.keyClicks(dialog.editor, "ab")
        self.assertEqual(dialog.editor.toPlainText(), "    ab")
        for _ in range(5):
            dialog.editor.undo()
        self.assertEqual(dialog.editor.toPlainText(), "")
        for _ in range(5):
            dialog.editor.redo()
        self.assertEqual(dialog.editor.toPlainText(), "    ab")
        dialog.editor.setPlainText("a\nb")
        dialog.editor.selectAll()
        QTest.keyClick(dialog.editor, Qt.Key.Key_Tab)
        self.assertEqual(dialog.editor.toPlainText(), "    a\n    b")
        QTest.keyClick(dialog.editor, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(dialog.editor.toPlainText(), "a\nb")
        dialog.deleteLater()

    def test_line_numbers_are_shown(self) -> None:
        dialog = self.editor()
        self.assertGreater(dialog.line_number_area.width(), 0)
        self.assertEqual(dialog.editor.blockCount(), 4)
        dialog.deleteLater()

    def test_done_applies_edited_text_without_a_preview_step_and_round_trips(self) -> None:
        dialog = self.editor()
        edited = (
            'let\n    Source = #"Sheet_1",\n'
            '    #"Filtered Rows" = Table.SelectRows(Source, each [Region] = "East"),\n'
            '    #"Removed Columns" = Table.RemoveColumns(#"Filtered Rows", {"Column2"})\n'
            'in\n    #"Removed Columns"'
        )
        dialog.editor.setPlainText(edited)
        self.assertTrue(dialog.done_button.isEnabled())
        dialog.done_button.click()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual([s["op"] for s in dialog.steps], ["filter_rows", "remove_column"])
        self.assertEqual(len(dialog.candidate.rows), 3)
        self.assertNotIn("Column2", dialog.candidate.headers)
        self.assertEqual(dialog.script, edited)
        reopened = PowerQueryMEditorDialog(
            make_source(), dialog.steps, "Sheet_1", initial_script=dialog.script
        )
        self.assertEqual(reopened.editor.toPlainText(), edited)
        dialog.deleteLater()
        reopened.deleteLater()

    def test_unsupported_function_is_refused_by_name_and_text_is_preserved(self) -> None:
        dialog = self.editor()
        text = (
            'let\n    Source = #"Sheet_1",\n'
            '    B = Table.Buffer(Source),\n    C = List.Sum(B)\nin\n    C'
        )
        dialog.editor.setPlainText(text)
        self.assertFalse(dialog.done_button.isEnabled())
        self.assertIn("Table.Buffer", dialog.status_label.text())
        dialog._accept_query()
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.editor.toPlainText(), text)
        self.assertIn("Table.Buffer", dialog.status_label.text())
        dialog.deleteLater()

    def test_runtime_error_is_shown_and_blocks_done(self) -> None:
        dialog = self.editor()
        dialog.editor.setPlainText(
            'let\n    Source = #"Sheet_1",\n'
            '    A = Table.RemoveColumns(Source, {"Nope"})\nin\n    A'
        )
        self.assertFalse(dialog.done_button.isEnabled())
        self.assertIn("Nope", dialog.status_label.text())
        dialog.deleteLater()

    def test_cancel_asks_to_discard_only_when_the_text_was_edited(self) -> None:
        dialog = self.editor()
        with patch.object(QMessageBox, "question") as ask:
            dialog.cancel_button.click()
        ask.assert_not_called()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Rejected)

        dialog = self.editor()
        dialog.editor.setPlainText(dialog.editor.toPlainText() + "\n// note")
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.No) as ask:
            dialog.cancel_button.click()
        ask.assert_called_once()
        self.assertEqual(ask.call_args.args[1], "Discard changes?")
        self.assertTrue(dialog.isVisible())
        self.assertIn("// note", dialog.editor.toPlainText())
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes):
            dialog.cancel_button.click()
        self.assertFalse(dialog.isVisible())
        self.assertIsNone(dialog.steps)
        dialog.deleteLater()


class EditorInsideQueryWindowTests(AdvancedEditorBase):
    """Drive the real Transform Data window, its real Advanced Editor and real buttons."""

    def open_transform(self) -> TransformDataDialog:
        dialog = TransformDataDialog(make_source(), query_name="Sheet_1")
        dialog.resize(1300, 800)
        dialog.show()
        self.app.processEvents()
        self.addCleanup(dialog.deleteLater)
        return dialog

    def remove_column(self, dialog: TransformDataDialog, column: str) -> None:
        index = dialog._preview_candidate.headers.index(column)
        dialog.preview.selectColumn(index)
        dialog.preview.setCurrentIndex(dialog.preview.model().index(0, index))
        dialog.ribbon_command_buttons["remove_column"].click()
        self.app.processEvents()

    def with_editor(self, dialog: TransformDataDialog, act) -> str:
        """Open the Advanced Editor from the ribbon button, run ``act(editor)``; return its text."""
        seen: list[str] = []

        def drive() -> None:
            editor = next(
                widget for widget in QApplication.topLevelWidgets()
                if isinstance(widget, PowerQueryMEditorDialog) and widget.isVisible()
            )
            seen.append(editor.editor.toPlainText())
            act(editor)
            if editor.isVisible():
                with patch.object(QMessageBox, "question",
                                  return_value=QMessageBox.StandardButton.Yes):
                    editor.cancel_button.click()

        QTimer.singleShot(0, drive)
        dialog.advanced_editor_button.click()
        return seen[0]

    def test_edit_in_the_real_editor_and_click_done_updates_steps_and_preview(self) -> None:
        dialog = self.open_transform()
        for column in ("Column2", "Column3", "Column4"):
            self.remove_column(dialog, column)
        edited = (
            'let\n    Source = #"Sheet_1",\n'
            '    #"Removed Columns" = Table.RemoveColumns(Source, {"Column2", "Column3"}),\n'
            '    #"Filtered Rows" = Table.SelectRows(#"Removed Columns", each [Region] = "East")\n'
            'in\n    #"Filtered Rows"'
        )

        def edit_and_done(editor: PowerQueryMEditorDialog) -> None:
            editor.editor.selectAll()
            QTest.keyClicks(editor.editor, "x")  # a real keystroke replaces the selection
            self.assertFalse(editor.done_button.isEnabled())  # "x" alone is not valid M
            editor.editor.setPlainText(edited)
            self.assertTrue(editor.done_button.isEnabled())
            editor.done_button.click()

        first = self.with_editor(dialog, edit_and_done)
        self.assertIn('#"Removed Columns2"', first)
        self.assertEqual(
            [step["op"] for step in dialog._steps],
            ["remove_column", "remove_column", "filter_rows"],
        )
        self.assertEqual(
            dialog._preview_candidate.headers, ["Column1", "Column4", "Amount", "Region"]
        )
        self.assertEqual(len(dialog._preview_candidate.rows), 3)
        # Reopening shows exactly the text that was applied (stable formatting).
        second = self.with_editor(dialog, lambda editor: None)
        self.assertEqual(second, edited)

    def test_cancel_in_the_real_editor_keeps_the_query_unchanged(self) -> None:
        dialog = self.open_transform()
        self.remove_column(dialog, "Column2")
        before = [dict(step) for step in dialog._steps]

        def edit_then_cancel(editor: PowerQueryMEditorDialog) -> None:
            editor.editor.setPlainText('let\n    Source = #"Sheet_1"\nin\n    Source')
            with patch.object(QMessageBox, "question",
                              return_value=QMessageBox.StandardButton.Yes):
                editor.cancel_button.click()

        self.with_editor(dialog, edit_then_cancel)
        self.assertEqual(dialog._steps, before)

    def test_custom_step_names_flow_into_the_m_text_and_formula_bar(self) -> None:
        dialog = self.open_transform()
        self.remove_column(dialog, "Column2")
        self.remove_column(dialog, "Column3")
        dialog._step_metadata[0] = {"name": "Dropped Two"}
        dialog._render_steps()
        text = self.with_editor(dialog, lambda editor: None)
        self.assertIn('#"Dropped Two" = Table.RemoveColumns(Source,', text)
        self.assertIn('#"Removed Columns1" = Table.RemoveColumns(#"Dropped Two",', text)
        dialog.step_list.setCurrentRow(1)
        self.assertIn('Table.RemoveColumns(#"Dropped Two"', dialog.formula_bar.text())


class EditorKeyboardTests(AdvancedEditorBase):
    def test_escape_and_close_ask_to_discard_only_when_edited(self) -> None:
        dialog = PowerQueryMEditorDialog(make_source(), [], "Sheet_1")
        dialog.show()
        with patch.object(QMessageBox, "question") as ask:
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
        ask.assert_not_called()
        self.assertFalse(dialog.isVisible())

        dialog = PowerQueryMEditorDialog(make_source(), [], "Sheet_1")
        dialog.show()
        dialog.editor.setPlainText(dialog.editor.toPlainText() + "\n")
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.No) as ask:
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
        ask.assert_called_once()
        self.assertTrue(dialog.isVisible())
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.No):
            dialog.close()
        self.assertTrue(dialog.isVisible())
        with patch.object(QMessageBox, "question",
                          return_value=QMessageBox.StandardButton.Yes):
            dialog.close()
        self.assertFalse(dialog.isVisible())


if __name__ == "__main__":
    unittest.main()
