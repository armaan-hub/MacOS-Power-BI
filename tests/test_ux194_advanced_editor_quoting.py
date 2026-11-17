"""Tests for Task 194: Advanced Editor fallback quoting."""

from __future__ import annotations

from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QDialog

from analytics_studio.file_import import ImportCandidate
from analytics_studio.local_table_dialogs import TransformDataDialog
from analytics_studio.power_query_m import (
    PowerQueryMEditorDialog,
    m_compatibility_issues,
    steps_to_m_script as real_steps_to_m_script,
)


def _get_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _open_advanced_editor_with_failing_prefix(query_name: str) -> PowerQueryMEditorDialog:
    _get_app()
    source = ImportCandidate(
        "inline",
        ["Region"],
        [{"Region": "North"}, {"Region": "South"}],
        {},
        [],
    )
    # A step list that causes m_compatibility_issues (triggering read_only_issues)
    steps = [
        {"op": "convert_type", "column": "Region", "type": "whole_number"},
        {"op": "keep_duplicates", "columns": ["Region"]},
    ]
    assert len(m_compatibility_issues(steps)) > 0, "Precondition: steps must have compatibility issues"

    dialog = TransformDataDialog(source, steps, query_name=query_name)
    captured_editor: list[PowerQueryMEditorDialog] = []

    def fake_steps_to_m_script(*args, **kwargs):
        # Allow compatibility probe to succeed, but fail when building the prefix script inside dialog init
        if kwargs.get("step_names") is not None:
            raise RuntimeError("Forced prefix script failure")
        return real_steps_to_m_script(*args, **kwargs)

    def fake_exec(dlg_self: PowerQueryMEditorDialog) -> int:
        captured_editor.append(dlg_self)
        return QDialog.DialogCode.Accepted

    with patch.object(PowerQueryMEditorDialog, "exec", new=fake_exec):
        with patch("analytics_studio.power_query_m.steps_to_m_script", side_effect=fake_steps_to_m_script):
            dialog._open_advanced_editor()

    assert len(captured_editor) == 1
    editor_dialog = captured_editor[0]
    dialog.deleteLater()
    return editor_dialog


def test_advanced_editor_fallback_quoting_sales() -> None:
    dlg = _open_advanced_editor_with_failing_prefix("Sales")
    text = dlg.editor.toPlainText()
    assert dlg.editor.isReadOnly()
    assert "Source = Sales" in text
    assert "#'" not in text
    dlg.deleteLater()


def test_advanced_editor_fallback_quoting_my_query() -> None:
    dlg = _open_advanced_editor_with_failing_prefix("My Query")
    text = dlg.editor.toPlainText()
    assert dlg.editor.isReadOnly()
    assert 'Source = #"My Query"' in text
    assert "#'" not in text
    dlg.deleteLater()


def test_advanced_editor_fallback_quoting_with_inner_quotes() -> None:
    dlg = _open_advanced_editor_with_failing_prefix('My "Q" 1')
    text = dlg.editor.toPlainText()
    assert dlg.editor.isReadOnly()
    assert 'Source = #"My ""Q"" 1"' in text
    assert "#'" not in text
    dlg.deleteLater()
