"""Tests for Task 187: Advanced Editor M syntax colours and always opens."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import patch

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import TransformDataDialog
from analytics_studio.m_code_editor import MCodeEditor, MSyntaxHighlighter
from analytics_studio.power_query_m import PowerQueryMEditorDialog, m_compatibility_issues


def _get_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_highlighter_colours_tokens() -> None:
    _get_app()
    editor = MCodeEditor()
    editor.setPlainText(
        'let\n'
        '    Source = "text",\n'
        '    Comment = // c\n'
        '    Num = 123\n'
        'in\n'
        '    Num'
    )

    # let is blue #0000FF
    fmt_let = editor.format_at(0, 1)
    assert fmt_let is not None
    assert fmt_let.foreground().color().name().upper() == "#0000FF"

    # "text" is dark red #A31515
    # line 1: '    Source = "text",' -> "text" starts at index 13
    fmt_str = editor.format_at(1, 15)
    assert fmt_str is not None
    assert fmt_str.foreground().color().name().upper() == "#A31515"

    # // c is green #008000
    # line 2: '    Comment = // c' -> // starts at index 14
    fmt_comment = editor.format_at(2, 15)
    assert fmt_comment is not None
    assert fmt_comment.foreground().color().name().upper() == "#008000"

    # 123 is dark green #098658
    # line 3: '    Num = 123' -> 123 starts at index 10
    fmt_num = editor.format_at(3, 11)
    assert fmt_num is not None
    assert fmt_num.foreground().color().name().upper() == "#098658"


def test_let_inside_string_is_not_blue() -> None:
    _get_app()
    editor = MCodeEditor()
    editor.setPlainText('let\n    Source = "let in each"')

    # line 1: inside "let in each", "let" is at col 14-16
    fmt_str_let = editor.format_at(1, 15)
    assert fmt_str_let is not None
    assert fmt_str_let.foreground().color().name().upper() == "#A31515"
    assert fmt_str_let.foreground().color().name().upper() != "#0000FF"


def test_multiline_block_comment_keeps_let_green() -> None:
    _get_app()
    editor = MCodeEditor()
    editor.setPlainText("/* a\nlet\n*/")

    # line 1 is "let" inside block comment -> should be green #008000
    fmt_comment_let = editor.format_at(1, 1)
    assert fmt_comment_let is not None
    assert fmt_comment_let.foreground().color().name().upper() == "#008000"
    assert fmt_comment_let.foreground().color().name().upper() != "#0000FF"


def test_date_intrinsic_is_dark_blue() -> None:
    _get_app()
    editor = MCodeEditor()
    editor.setPlainText("let\n    Source = #date(2026, 1, 1)\nin\n    Source")

    # line 1: #date is at index 13-17
    fmt_date = editor.format_at(1, 14)
    assert fmt_date is not None
    assert fmt_date.foreground().color().name().upper() == "#001080"


def test_table_selectrows_is_not_blue() -> None:
    _get_app()
    editor = MCodeEditor()
    editor.setPlainText("let\n    Source = Table.SelectRows(x, each true)\nin\n    Source")

    # line 1: Table.SelectRows: 'Table' is at 13-17, 'SelectRows' is at 19-28
    fmt_table = editor.format_at(1, 14)
    assert fmt_table is None or fmt_table.foreground().color().name().upper() != "#0000FF"

    fmt_selectrows = editor.format_at(1, 20)
    assert fmt_selectrows is None or fmt_selectrows.foreground().color().name().upper() != "#0000FF"


def test_open_advanced_editor_with_issues_opens_readonly_and_does_not_modify_steps() -> None:
    _get_app()
    source = ImportCandidate(
        "inline",
        ["Region"],
        [{"Region": "North"}, {"Region": "South"}],
        {},
        [],
    )
    # A step list that causes m_compatibility_issues:
    steps = [
        {"op": "convert_type", "column": "Region", "type": "whole_number"},
        {"op": "keep_duplicates", "columns": ["Region"]},
    ]
    issues = m_compatibility_issues(steps)
    assert len(issues) > 0, "Precondition: steps must have compatibility issues"

    dialog = TransformDataDialog(source, steps, query_name="Sales Data")
    original_steps = deepcopy(dialog._steps)

    captured_editor: list[PowerQueryMEditorDialog] = []

    def fake_exec(dlg_self: PowerQueryMEditorDialog) -> int:
        captured_editor.append(dlg_self)
        return QDialog.DialogCode.Accepted

    with patch.object(PowerQueryMEditorDialog, "exec", new=fake_exec):
        dialog._open_advanced_editor()

    assert len(captured_editor) == 1
    m_dialog = captured_editor[0]
    # Check dialog properties
    assert m_dialog.editor.isReadOnly()
    assert not m_dialog.done_button.isEnabled()
    assert "Read-only: some steps cannot be shown as M yet. Edit them in Applied Steps." == m_dialog.status_label.text()
    assert "// Step" in m_dialog.editor.toPlainText()
    assert "/* Not shown in M yet" in m_dialog.editor.toPlainText()

    # Steps are unchanged after exec returns Accepted
    assert dialog._steps == original_steps
    dialog.deleteLater()


def test_fully_supported_query_still_opens_editable() -> None:
    _get_app()
    source = ImportCandidate(
        "inline",
        ["Region"],
        [{"Region": "North"}, {"Region": "South"}],
        {},
        [],
    )
    steps = [
        {"op": "convert_type", "column": "Region", "type": "text"},
    ]
    assert m_compatibility_issues(steps) == []

    dialog = TransformDataDialog(source, steps, query_name="Sales Data")

    captured_editor: list[PowerQueryMEditorDialog] = []

    def fake_exec(dlg_self: PowerQueryMEditorDialog) -> int:
        captured_editor.append(dlg_self)
        return QDialog.DialogCode.Rejected

    with patch.object(PowerQueryMEditorDialog, "exec", new=fake_exec):
        dialog._open_advanced_editor()

    assert len(captured_editor) == 1
    m_dialog = captured_editor[0]
    assert not m_dialog.editor.isReadOnly()
    assert m_dialog.done_button.isEnabled()
    dialog.deleteLater()
