"""Tests for refusal of unguarded import entry points when a store table is loaded (Stage B4b task 17a Item 2)."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from analytics_studio import file_import
from analytics_studio.controller import StudioController
from tests.test_controller_store_import_large import _wait_for_large_job


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(["Analytics Studio tests"])


@pytest.fixture
def small_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_import, "MAX_DATA_ROWS", 500)


def _assert_no_blocking_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: QMessageBox.StandardButton.Ok,
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args, **kwargs: QMessageBox.StandardButton.Ok,
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda *args, **kwargs: QMessageBox.StandardButton.Ok,
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(
        StudioController,
        "_run_store_summary_dialog",
        lambda self, candidate: None,
    )


def _make_csv(path: Path, rows: int = 10) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "amt"])
        for i in range(rows):
            w.writerow([i, i * 2])
    return path


def _setup_controller_with_store_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> StudioController:
    _assert_no_blocking_dialogs(monkeypatch)
    app_data = tmp_path / "appdata"
    monkeypatch.setattr(StudioController, "_effective_app_data_dir", lambda self: str(app_data))

    big = _make_csv(tmp_path / "big.csv", 2000)
    c = StudioController()
    assert c._import_large(big, {"path": str(big), "kind": "csv", "options": {}}) is True
    _wait_for_large_job(c)
    assert c._store_tables_loaded() is True
    return c


def _snapshot(c: StudioController) -> dict[str, Any]:
    return {
        "sources": json.dumps(c._project.get("data_sources", []), sort_keys=True, default=str),
        "tables": json.dumps(c._project.get("model", {}).get("tables", []), sort_keys=True, default=str),
        "loaded_keys": set(c._loaded_candidates.keys()),
        "dirty": c._dirty,
    }


def _fail_guard(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("guard missing")


def test_load_sample_data_refused_when_store_table_loaded(
    qapp: QApplication, tmp_path: Path, small_limit: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = _setup_controller_with_store_table(tmp_path, monkeypatch)
    snap_before = _snapshot(c)
    monkeypatch.setattr(c, "_commit_inline", _fail_guard)

    res = c.load_sample_data()
    assert res is False
    assert c._status_message == c._large_data_refusal("Import")
    assert _snapshot(c) == snap_before
    c._close_project_store()


def test_enter_data_dialog_refused_when_store_table_loaded(
    qapp: QApplication, tmp_path: Path, small_limit: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = _setup_controller_with_store_table(tmp_path, monkeypatch)
    snap_before = _snapshot(c)
    monkeypatch.setattr(c, "_commit_inline", _fail_guard)
    monkeypatch.setattr("analytics_studio.controller.EnterDataDialog.exec", _fail_guard)

    with patch("analytics_studio.controller.EnterDataDialog") as mock_dlg:
        mock_dlg.side_effect = lambda *a, **k: (_ for _ in ()).throw(AssertionError("guard missing"))
        res = c.enter_data_dialog()
        assert res is False
        assert mock_dlg.call_count == 0

    assert c._status_message == c._large_data_refusal("Import")
    assert _snapshot(c) == snap_before
    c._close_project_store()


def test_ribbon_commands_refused_when_store_table_loaded(
    qapp: QApplication, tmp_path: Path, small_limit: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = _setup_controller_with_store_table(tmp_path, monkeypatch)
    monkeypatch.setattr(c, "_commit_inline", _fail_guard)
    monkeypatch.setattr("analytics_studio.controller.EnterDataDialog.exec", _fail_guard)

    with patch("analytics_studio.controller.EnterDataDialog") as mock_dlg:
        mock_dlg.side_effect = lambda *a, **k: (_ for _ in ()).throw(AssertionError("guard missing"))
        # enterData
        snap = _snapshot(c)
        c.executeCommand("enterData")
        assert mock_dlg.call_count == 0
        assert c._status_message == c._large_data_refusal("Import")
        assert _snapshot(c) == snap

        # pasteData
        snap = _snapshot(c)
        c.executeCommand("pasteData")
        assert mock_dlg.call_count == 0
        assert c._status_message == c._large_data_refusal("Import")
        assert _snapshot(c) == snap

        # sampleData
        snap = _snapshot(c)
        c.executeCommand("sampleData")
        assert c._status_message == c._large_data_refusal("Import")
        assert _snapshot(c) == snap

    c._close_project_store()


def test_import_paths_refused_when_store_table_loaded(
    qapp: QApplication, tmp_path: Path, small_limit: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = _setup_controller_with_store_table(tmp_path, monkeypatch)
    dummy_csv = _make_csv(tmp_path / "dummy.csv", 5)
    monkeypatch.setattr(c, "_import_file_path", _fail_guard)
    monkeypatch.setattr(c, "_commit_import", _fail_guard)

    snap = _snapshot(c)
    assert c.import_data_path(dummy_csv) is False
    assert c._status_message == c._large_data_refusal("Import")
    assert _snapshot(c) == snap

    snap = _snapshot(c)
    assert c.import_csv_path(dummy_csv) is False
    assert c._status_message == c._large_data_refusal("Import")
    assert _snapshot(c) == snap

    snap = _snapshot(c)
    dummy_excel = tmp_path / "dummy.xlsx"
    dummy_excel.write_bytes(b"dummy")
    assert c.import_excel_path(dummy_excel) is False
    assert c._status_message == c._large_data_refusal("Import")
    assert _snapshot(c) == snap

    c._close_project_store()


def test_entry_points_work_when_no_store_table_loaded(
    qapp: QApplication, tmp_path: Path, small_limit: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    c = StudioController()
    assert c._store_tables_loaded() is False

    # 1. load_sample_data
    assert c.load_sample_data() is True
    assert any(s["name"] == "Sample data" for s in c._project["data_sources"])

    # 2. enter_data_dialog with mocked dialog
    from analytics_studio.file_import import ImportCandidate, parse_file
    from PySide6.QtWidgets import QDialog
    with patch("analytics_studio.controller.EnterDataDialog") as mock_dlg_cls:
        inst = mock_dlg_cls.return_value
        inst.exec.return_value = QDialog.DialogCode.Accepted
        inst.candidate = ImportCandidate(
            kind="inline",
            headers=["col1", "col2"],
            rows=[{"col1": "a", "col2": "b"}],
            options={"name": "PastedTable"},
            notices=[],
        )
        assert c.enter_data_dialog() is True
        assert any(s["name"] == "PastedTable" for s in c._project["data_sources"])

    # Mock FileImportPreviewDialog for path import functions
    csv1 = _make_csv(tmp_path / "csv1.csv", 5)
    with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog") as mock_prev_cls:
        inst = mock_prev_cls.return_value
        inst.exec.return_value = QDialog.DialogCode.Accepted
        inst.large_request = None
        inst.selected_action = "load"
        inst.candidate = parse_file(csv1)
        inst.checked_sheets = []

        # 3. import_csv_path
        assert c.import_csv_path(csv1) is True
        assert any(s["name"] == "csv1.csv" for s in c._project["data_sources"])

        # 4. import_data_path
        csv2 = _make_csv(tmp_path / "csv2.csv", 5)
        inst.candidate = parse_file(csv2)
        assert c.import_data_path(csv2) is True
        assert any(s["name"] == "csv2.csv" for s in c._project["data_sources"])

        # 5. import_excel_path
        excel_dummy = tmp_path / "test.xlsx"
        excel_dummy.write_bytes(b"dummy")
        inst.candidate = ImportCandidate(
            kind="excel",
            headers=["ea", "eb"],
            rows=[{"ea": "1", "eb": "2"}],
            options={"sheet_name": "Sheet1"},
            notices=[],
        )
        inst.checked_sheets = ["Sheet1"]
        assert c.import_excel_path(excel_dummy) is True
        assert any(s["name"] == "test.xlsx" for s in c._project["data_sources"])
