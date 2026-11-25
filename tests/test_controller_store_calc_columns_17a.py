"""Tests for calculated columns on ordinary tables in the presence of store tables (Stage B4b task 17a Item 1)."""

from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from analytics_studio import file_import
from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.project import load_project, save_project
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


def _make_csv(path: Path, rows: int = 10, cols: list[str] | None = None) -> Path:
    cols = cols or ["id", "amt"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for i in range(rows):
            w.writerow([i, i * 2])
    return path


def test_reimport_ordinary_table_preserves_calc_columns_with_store_table_present(
    qapp: QApplication, tmp_path: Path, small_limit: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repro (a): ordinary table with calculated column Dbl plus large table; reimport ordinary file preserves Dbl."""
    _assert_no_blocking_dialogs(monkeypatch)
    app_data = tmp_path / "appdata"
    monkeypatch.setattr(StudioController, "_effective_app_data_dir", lambda self: str(app_data))

    small = _make_csv(tmp_path / "small.csv", 10)
    c0 = StudioController()
    assert c0._commit_import(small, parse_file(small)) is True
    p2 = tmp_path / "p2.npa"
    assert c0._save_to(p2) is True

    # Inject calculated column Dbl on the ordinary table in p2
    doc, _ = load_project(p2)
    tbl0 = doc["model"]["tables"][0]
    tbl0["calculated_columns"] = [{"name": "Dbl", "expression": "[amt] * 2"}]
    save_project(p2, doc)

    # Controller loads p2
    c = StudioController()
    c._dirty = False
    assert c.open_project_path(p2) is True
    assert "Dbl" in c._headers

    # Now import a large table into c
    big = _make_csv(tmp_path / "big.csv", 2000)
    assert c._import_large(big, {"path": str(big), "kind": "csv", "options": {}}) is True
    _wait_for_large_job(c)
    assert c._store_tables_loaded() is True

    sid_small = [s["id"] for s in c._project["data_sources"] if s["name"] == "small.csv"][0]
    assert "Dbl" in c._loaded_candidates[sid_small].headers

    # Re-import ordinary file via _commit_import
    ok = c._commit_import(small, parse_file(small))
    assert ok is True

    # After fix: Dbl must remain in headers, column_types, rows and JSON
    small_cand = c._loaded_candidates[sid_small]
    assert "Dbl" in small_cand.headers
    assert any("Dbl" in row for row in small_cand.rows)
    t = [t for t in c._project["model"]["tables"] if t.get("source_id") == sid_small][0]
    assert "Dbl" in t.get("column_types", {})
    assert any(c_def.get("name") == "Dbl" for c_def in t.get("calculated_columns", []))
    c._close_project_store()


def test_open_ordinary_project_with_calc_column_when_window_holds_store_table(
    qapp: QApplication, tmp_path: Path, small_limit: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Repro (b): window holds a store table, then opens an ordinary project with calc column -> kept."""
    _assert_no_blocking_dialogs(monkeypatch)
    app_data = tmp_path / "appdata"
    monkeypatch.setattr(StudioController, "_effective_app_data_dir", lambda self: str(app_data))

    # Ordinary project p_ord
    small = _make_csv(tmp_path / "small.csv", 10)
    c0 = StudioController()
    assert c0._commit_import(small, parse_file(small)) is True
    p_ord = tmp_path / "p_ord.npa"
    assert c0._save_to(p_ord) is True

    doc, _ = load_project(p_ord)
    tbl0 = doc["model"]["tables"][0]
    tbl0["calculated_columns"] = [{"name": "Dbl", "expression": "[amt] * 2"}]
    save_project(p_ord, doc)

    # Controller c1 loads a store table
    big = _make_csv(tmp_path / "big.csv", 2000)
    c1 = StudioController()
    assert c1._import_large(big, {"path": str(big), "kind": "csv", "options": {}}) is True
    _wait_for_large_job(c1)
    p_big = tmp_path / "p_big.npa"
    assert c1._save_to(p_big) is True
    assert c1._store_tables_loaded() is True

    # Now open p_ord in c1
    c1._dirty = False
    assert c1.open_project_path(p_ord) is True
    assert "Dbl" in c1._headers
    ord_tbl = c1._project["model"]["tables"][0]
    assert "Dbl" in ord_tbl.get("column_types", {})
    assert any(c_def.get("name") == "Dbl" for c_def in ord_tbl.get("calculated_columns", []))
    c1._close_project_store()


def test_mixed_ordinary_and_store_table_save_and_reopen_calc_columns(
    qapp: QApplication, tmp_path: Path, small_limit: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Project holding both ordinary table with calc column and store table saves and reopens intact."""
    _assert_no_blocking_dialogs(monkeypatch)
    app_data = tmp_path / "appdata"
    monkeypatch.setattr(StudioController, "_effective_app_data_dir", lambda self: str(app_data))

    big = _make_csv(tmp_path / "big.csv", 2000)
    c = StudioController()
    assert c._import_large(big, {"path": str(big), "kind": "csv", "options": {}}) is True
    _wait_for_large_job(c)
    p_mixed = tmp_path / "p_mixed.npa"
    assert c._save_to(p_mixed) is True
    c._close_project_store()

    # Inject ordinary source with calc column into p_mixed
    doc, _ = load_project(p_mixed)
    ord_csv = _make_csv(tmp_path / "ord.csv", 10)
    ord_sid = "src_ord_mixed"
    doc["data_sources"].append({
        "id": ord_sid,
        "name": "ord.csv",
        "kind": "csv",
        "path": str(ord_csv),
        "parser_options": {},
    })
    doc["model"]["tables"].append({
        "id": ord_sid,
        "source_id": ord_sid,
        "name": "ord",
        "column_types": {"id": "whole_number", "amt": "whole_number"},
        "calculated_columns": [{"name": "Dbl", "expression": "[amt] * 2"}],
    })
    save_project(p_mixed, doc)

    # Reopen p_mixed in fresh controller
    fresh = StudioController()
    assert fresh.open_project_path(p_mixed) is True
    ord_tbl = next((t for t in fresh._project["model"]["tables"] if t.get("name") == "ord"), None)
    assert ord_tbl is not None
    assert "Dbl" in ord_tbl.get("column_types", {})
    assert any(c_def.get("name") == "Dbl" for c_def in ord_tbl.get("calculated_columns", []))
    assert "Dbl" in fresh._loaded_candidates[ord_sid].headers
    fresh._close_project_store()


def test_store_table_with_calc_definitions_does_not_materialize_or_crash(
    qapp: QApplication, tmp_path: Path, small_limit: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Store table with calculated column definitions keeps definitions in JSON, never materialised, no crash."""
    _assert_no_blocking_dialogs(monkeypatch)
    app_data = tmp_path / "appdata"
    monkeypatch.setattr(StudioController, "_effective_app_data_dir", lambda self: str(app_data))

    big = _make_csv(tmp_path / "big.csv", 2000)
    c = StudioController()
    assert c._import_large(big, {"path": str(big), "kind": "csv", "options": {}}) is True
    _wait_for_large_job(c)
    p_store = tmp_path / "p_store.npa"
    assert c._save_to(p_store) is True
    c._close_project_store()

    # Inject calc column definition on the store table itself
    doc, _ = load_project(p_store)
    store_tbl = doc["model"]["tables"][0]
    store_tbl["calculated_columns"] = [{"name": "CalcOnStore", "expression": "[amt] * 2"}]
    save_project(p_store, doc)

    fresh = StudioController()
    assert fresh.open_project_path(p_store) is True
    tbl = fresh._project["model"]["tables"][0]
    # Definitions stay in JSON
    assert any(c_def.get("name") == "CalcOnStore" for c_def in tbl.get("calculated_columns", []))
    # Not materialised in column_types or headers
    assert "CalcOnStore" not in tbl.get("column_types", {})
    assert "CalcOnStore" not in fresh._headers
    fresh._close_project_store()
