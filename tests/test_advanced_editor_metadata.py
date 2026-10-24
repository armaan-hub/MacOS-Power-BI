"""Critic I10 + M block comments: step metadata follows step identity; /* ... */ is whitespace."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from analytics_studio.power_query_m import PowerQueryMScriptError, parse_m_query_script
from tests.test_advanced_editor import (
    EditorInsideQueryWindowTests,
    PowerQueryMEditorDialog,
)

CHAIN = (
    'let\n    Source = #"Sheet_1",\n'
    '    #"Removed Columns" = Table.RemoveColumns(Source, {"Column2"}),\n'
    '    #"Removed Columns1" = Table.RemoveColumns(#"Removed Columns", {"Column3"}),\n'
    '    #"Removed Columns2" = Table.RemoveColumns(#"Removed Columns1", {"Column4"})\n'
    'in\n    #"Removed Columns2"'
)


class StepMetadataIdentityTests(EditorInsideQueryWindowTests):
    def three_described_steps(self):
        dialog = self.open_transform()
        for column in ("Column2", "Column3", "Column4"):
            self.remove_column(dialog, column)
        for index, column in enumerate(("Column2", "Column3", "Column4")):
            dialog._edit_selected_step_metadata(index, description=f"why {column}")
        return dialog

    def apply_script(self, dialog, script: str) -> None:
        def edit_and_done(editor: PowerQueryMEditorDialog) -> None:
            editor.editor.setPlainText(script)
            self.assertTrue(editor.done_button.isEnabled())
            editor.done_button.click()

        self.with_editor(dialog, edit_and_done)

    def descriptions(self, dialog) -> list[tuple[str, str]]:
        return [
            (step["column"], dialog._step_metadata[index].get("description", ""))
            for index, step in enumerate(dialog._steps)
        ]

    def test_deleting_the_first_step_keeps_each_description_on_its_own_step(self) -> None:
        dialog = self.three_described_steps()
        self.apply_script(dialog, (
            'let\n    Source = #"Sheet_1",\n'
            '    #"Removed Columns1" = Table.RemoveColumns(Source, {"Column3"}),\n'
            '    #"Removed Columns2" = Table.RemoveColumns(#"Removed Columns1", {"Column4"})\n'
            'in\n    #"Removed Columns2"'
        ))
        self.assertEqual(
            self.descriptions(dialog), [("Column3", "why Column3"), ("Column4", "why Column4")])

    def test_deleting_a_middle_step_keeps_the_others(self) -> None:
        dialog = self.three_described_steps()
        self.apply_script(dialog, (
            'let\n    Source = #"Sheet_1",\n'
            '    #"Removed Columns" = Table.RemoveColumns(Source, {"Column2"}),\n'
            '    #"Removed Columns2" = Table.RemoveColumns(#"Removed Columns", {"Column4"})\n'
            'in\n    #"Removed Columns2"'
        ))
        self.assertEqual(
            self.descriptions(dialog), [("Column2", "why Column2"), ("Column4", "why Column4")])

    def test_renaming_a_step_in_the_text_keeps_its_description(self) -> None:
        dialog = self.three_described_steps()
        self.apply_script(dialog, CHAIN.replace("Removed Columns1", "Dropped Three"))
        self.assertEqual(
            self.descriptions(dialog),
            [("Column2", "why Column2"), ("Column3", "why Column3"), ("Column4", "why Column4")])
        self.assertEqual(dialog._step_metadata[1].get("name"), "Dropped Three")

    def test_a_changed_operation_does_not_inherit_the_old_description(self) -> None:
        dialog = self.three_described_steps()
        self.apply_script(dialog, CHAIN.replace(
            'Table.RemoveColumns(#"Removed Columns", {"Column3"})',
            'Table.SelectRows(#"Removed Columns", each [Region] = "East")'))
        self.assertEqual(dialog._steps[1]["op"], "filter_rows")
        self.assertEqual(dialog._step_metadata[1], {})
        self.assertEqual(dialog._step_metadata[2].get("description"), "why Column4")

    def test_unchanged_text_keeps_every_description(self) -> None:
        dialog = self.three_described_steps()
        self.apply_script(dialog, CHAIN)
        self.assertEqual(
            self.descriptions(dialog),
            [("Column2", "why Column2"), ("Column3", "why Column3"), ("Column4", "why Column4")])


class BlockCommentTests(unittest.TestCase):
    def parse(self, script: str):
        return parse_m_query_script(script, "Sheet_1")[1]

    def test_block_comments_are_whitespace_everywhere(self) -> None:
        scripts = [
            '/* header */ let\n    Source = #"Sheet_1"\nin\n    Source',
            'let /* c */\n    Source = #"Sheet_1" /* after source */\nin\n    Source',
            'let\n    Source = #"Sheet_1",\n'
            '    #"Removed Columns" = Table.RemoveColumns(Source, /* which */ {"Column2"})\n'
            'in\n    #"Removed Columns"',
            'let\n    Source = #"Sheet_1",\n    /* multi\n       line */\n'
            '    #"Removed Columns" = Table.RemoveColumns(Source, {"Column2"})\n'
            'in\n    #"Removed Columns" /* end */',
            'let\n    Source = #"Sheet_1" // a /* b\nin\n    Source',
            'let\n    Source = #"Sheet_1" /* a // b */\nin\n    Source',
        ]
        for script in scripts:
            with self.subTest(script=script):
                self.parse(script)

    def test_comment_markers_inside_text_are_text(self) -> None:
        steps = self.parse(
            'let\n    Source = #"Sheet_1",\n'
            '    #"Filtered Rows" = Table.SelectRows(Source, each [Region] = "/* not a comment */")\n'
            'in\n    #"Filtered Rows"'
        )
        self.assertEqual(steps[0]["value"], "/* not a comment */")

    def test_unterminated_block_comment_has_a_precise_message(self) -> None:
        with self.assertRaises(PowerQueryMScriptError) as caught:
            self.parse('let\n    Source = #"Sheet_1" /* oops\nin\n    Source')
        self.assertIn("block comment", str(caught.exception))
        self.assertEqual(caught.exception.line, 2)

    def test_a_bad_step_after_a_block_comment_is_still_located(self) -> None:
        with self.assertRaises(PowerQueryMScriptError) as caught:
            self.parse('/* c\nc */ let\n    Source = #"Sheet_1",\n    Bad = Foo.Bar(Source)\nin\n    Bad')
        self.assertEqual(caught.exception.line, 4)


if __name__ == "__main__":
    unittest.main()
