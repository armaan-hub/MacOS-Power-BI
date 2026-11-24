"""Tests for controller store import commit step (Stage B4b task 11b)."""

from __future__ import annotations

import csv
from copy import deepcopy
from pathlib import Path
import threading
from typing import Any
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.project import validate_project
from analytics_studio.store.candidate import LargeTableError, StoreCandidate
from analytics_studio.store.large_import import LargeImportResult, run_large_import
from analytics_studio.store.table_model import StoreTableModel


@pytest.fixture
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["controller_store_commit_test"])
    return app


def _assert_no_blocking_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:
    def bad_dialog(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Blocking dialog was unexpectedly invoked!")

    monkeypatch.setattr(QFileDialog, "getOpenFileName", bad_dialog)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", bad_dialog)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", bad_dialog)
    monkeypatch.setattr(QMessageBox, "information", bad_dialog)
    monkeypatch.setattr(QMessageBox, "warning", bad_dialog)
    monkeypatch.setattr(QMessageBox, "critical", bad_dialog)
    monkeypatch.setattr(QMessageBox, "question", bad_dialog)
    monkeypatch.setattr(QInputDialog, "getText", bad_dialog)
    monkeypatch.setattr(QInputDialog, "getItem", bad_dialog)
    monkeypatch.setattr(QDialog, "exec", bad_dialog)
    monkeypatch.setattr(QDialog, "exec_", bad_dialog)
    monkeypatch.setattr(QDialog, "open", bad_dialog)
    monkeypatch.setattr(QDialog, "show", bad_dialog)


def _generate_csv_file(tmp_path: Path, row_count: int = 2000) -> Path:
    csv_file = tmp_path / "data_2000.csv"
    headers = ["id", "val_float", "event_date", "description", "blank_col"]
    rows: list[list[str]] = []
    for i in range(1, row_count + 1):
        if i % 10 == 0:
            rows.append([str(i), "", "", "", ""])
        else:
            rows.append([
                str(i),
                f"{i * 1.5:.2f}",
                f"2026-08-{((i % 28) + 1):02d}",
                f"Description {i}",
                "",
            ])
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    return csv_file


def _generate_parquet_file(tmp_path: Path, row_count: int = 2000) -> Path:
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    pq_file = tmp_path / "data_2000.parquet"
    ids = list(range(1, row_count + 1))
    floats = [None if i % 10 == 0 else i * 1.5 for i in ids]
    dates = [None if i % 10 == 0 else f"2026-08-{((i % 28) + 1):02d}" for i in ids]
    descs = [None if i % 10 == 0 else f"Description {i}" for i in ids]
    blanks = [None] * row_count

    table = pa.Table.from_arrays(
        [
            pa.array(ids, type=pa.int64()),
            pa.array(floats, type=pa.float64()),
            pa.array(dates, type=pa.string()),
            pa.array(descs, type=pa.string()),
            pa.array(blanks, type=pa.string()),
        ],
        names=["id", "val_float", "event_date", "description", "blank_col"],
    )
    pq.write_table(table, pq_file)
    return pq_file


def test_commit_csv(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv_file(tmp_path, 2000)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    project_store = controller._ensure_project_store()

    with project_store.job():
        result = run_large_import(
            project_store.store,
            csv_file,
            "csv",
            {},
            source_id="src_csv_commit",
            cancel_event=threading.Event(),
            max_rows=1_000_000,
        )

    # Monkeypatch StoreCandidate.rows to ensure nothing reads rows
    def forbidden_rows(self: StoreCandidate) -> list[dict[str, Any]]:
        raise LargeTableError("test_forbidden_rows: rows accessed!")

    monkeypatch.setattr(StoreCandidate, "rows", property(forbidden_rows))

    # Spy on _set_status to ensure no large table error or traceback is swallowed
    status_calls: list[str] = []
    real_set_status = controller._set_status

    def spy_set_status(msg: str) -> None:
        if "too large" in msg.lower() or "traceback" in msg.lower() or "test_forbidden_rows" in msg:
            raise AssertionError(f"Unexpected status message: {msg}")
        status_calls.append(msg)
        real_set_status(msg)

    monkeypatch.setattr(controller, "_set_status", spy_set_status)

    success = controller._commit_store_import(csv_file, result, project_store)
    assert success is True
    assert controller.rowCount == 2000
    assert isinstance(controller.dataModel, StoreTableModel)
    assert controller.fieldNames == ["id", "val_float", "event_date", "description", "blank_col"]

    # First cells and headers check
    model = controller.dataModel
    assert model.headerData(0, Qt.Orientation.Horizontal) == "id"
    assert model.headerData(1, Qt.Orientation.Horizontal) == "val_float"
    assert model.data(model.index(0, 0)) == "1"
    assert model.data(model.index(0, 1)) == "1.50"

    # Project validation
    store_record = controller._project["data_sources"][0]["store"]
    validate_project(controller._project)

    # Bare file name check
    data_file = store_record["data_file"]
    assert "/" not in data_file and "\\" not in data_file and ".." not in data_file
    assert data_file == Path(project_store.path).name

    # Model types match and were properly passed to StoreTableModel
    table_record = controller._project["model"]["tables"][0]
    assert table_record["column_types"] == result.model_types
    assert controller.dataModel._column_types == result.model_types

    # Candidates dicts
    source_id = controller._active_source_id
    assert source_id is not None
    assert controller._loaded_candidates[source_id] is controller._active_store_candidate
    assert controller._raw_candidates[source_id] is controller._active_store_candidate
    assert controller._query_candidates[source_id] is controller._active_store_candidate

    # Status exact text
    expected_status = f"Loaded {result.row_count:,} rows into the large-data store: {csv_file.name}."
    assert controller.statusMessage == expected_status
    assert controller._dirty is True
    assert controller._active_store_candidate.stats is result.stats
    assert controller._silent_refusal_notice_shown is False

    project_store.close()


def test_commit_parquet(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    pytest.importorskip("pyarrow.parquet")
    pq_file = _generate_parquet_file(tmp_path, 2000)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    project_store = controller._ensure_project_store()

    with project_store.job():
        result = run_large_import(
            project_store.store,
            pq_file,
            "parquet",
            {},
            source_id="src_pq_commit",
            cancel_event=threading.Event(),
            max_rows=1_000_000,
        )

    # Monkeypatch StoreCandidate.rows to ensure nothing reads rows
    def forbidden_rows(self: StoreCandidate) -> list[dict[str, Any]]:
        raise LargeTableError("test_forbidden_rows: rows accessed!")

    monkeypatch.setattr(StoreCandidate, "rows", property(forbidden_rows))

    success = controller._commit_store_import(pq_file, result, project_store)
    assert success is True
    assert controller.rowCount == 2000
    assert isinstance(controller.dataModel, StoreTableModel)
    assert controller.fieldNames == ["id", "val_float", "event_date", "description", "blank_col"]

    store_record = controller._project["data_sources"][0]["store"]
    assert "source_arrow_types" in store_record
    assert len(store_record["source_arrow_types"]) == 5
    validate_project(controller._project)

    project_store.close()


def test_user_action_refused_after_commit(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv_file(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    project_store = controller._ensure_project_store()

    with project_store.job():
        result = run_large_import(
            project_store.store,
            csv_file,
            "csv",
            {},
            source_id="src_csv_commit",
            cancel_event=threading.Event(),
            max_rows=1_000_000,
        )

    assert controller._commit_store_import(csv_file, result, project_store) is True

    # Check setColumnType is refused with exact R1/R2 refusal text
    ret = controller.setColumnType("val_float", "whole_number")
    assert ret is False
    expected_refusal = (
        "Power Query transformations is not available for large-data tables yet. "
        "Tables up to 100,000 rows work everywhere; large tables support the data grid, "
        "sort, filter, column statistics and export. Other features arrive in a later release."
    )
    assert controller.statusMessage == expected_refusal

    project_store.close()


def test_existing_project_with_ordinary_table(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    # First load an ordinary table
    small_csv = tmp_path / "small.csv"
    small_csv.write_text("col_a,col_b\n1,foo\n2,bar\n", encoding="utf-8")

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    assert controller._commit_import(small_csv, parse_file(small_csv)) is True
    assert len(controller._project["data_sources"]) == 1
    assert controller.rowCount == 2

    # Now commit store import
    store_csv = _generate_csv_file(tmp_path, 2000)
    project_store = controller._ensure_project_store()
    with project_store.job():
        result = run_large_import(
            project_store.store,
            store_csv,
            "csv",
            {},
            source_id="src_store_csv_commit",
            cancel_event=threading.Event(),
            max_rows=1_000_000,
        )

    success = controller._commit_store_import(store_csv, result, project_store)
    assert success is True

    # Both sources exist
    assert len(controller._project["data_sources"]) == 2
    sources = controller._project["data_sources"]
    assert sources[0]["kind"] == "csv"
    assert "store" not in sources[0]
    assert sources[1]["kind"] == "csv"
    assert "store" in sources[1]

    # Active source is the store one
    assert controller._active_source_id == sources[1]["id"]
    assert controller.rowCount == 2000
    assert isinstance(controller.dataModel, StoreTableModel)

    project_store.close()


def test_failure_paths_leave_no_half_state(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    csv_file = _generate_csv_file(tmp_path, 500)
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    project_store = controller._ensure_project_store()

    with project_store.job():
        result = run_large_import(
            project_store.store,
            csv_file,
            "csv",
            {},
            source_id="src_csv_commit",
            cancel_event=threading.Event(),
            max_rows=1_000_000,
        )

    # Take baseline snapshot of clean state
    orig_project = deepcopy(controller._project)
    orig_loaded_keys = set(controller._loaded_candidates.keys())
    orig_raw_keys = set(controller._raw_candidates.keys())
    orig_query_keys = set(controller._query_candidates.keys())
    orig_active_id = controller._active_source_id
    orig_active_store = controller._active_store_candidate

    critical_dialog_calls: list[str] = []

    def mock_critical(parent: Any, title: str, text: str) -> None:
        critical_dialog_calls.append(f"{title}: {text}")

    monkeypatch.setattr(QMessageBox, "critical", mock_critical)

    # (a) validate_table failure: call with result whose row_count is wrong
    bad_result_a = LargeImportResult(
        table=result.table,
        row_count=result.row_count + 999,  # wrong row count
        headers=result.headers,
        physical_types=result.physical_types,
        model_types=result.model_types,
        source_arrow_types=result.source_arrow_types,
        kind=result.kind,
        options=result.options,
        fingerprint=result.fingerprint,
        notices=result.notices,
        source_id=result.source_id,
        stats=result.stats,
    )
    ret_a = controller._commit_store_import(csv_file, bad_result_a, project_store)
    assert ret_a is False
    assert len(critical_dialog_calls) == 1
    assert "Could not import data" in critical_dialog_calls[0]
    assert controller._project == orig_project
    assert set(controller._loaded_candidates.keys()) == orig_loaded_keys
    assert set(controller._raw_candidates.keys()) == orig_raw_keys
    assert set(controller._query_candidates.keys()) == orig_query_keys
    assert controller._active_source_id == orig_active_id
    assert controller._active_store_candidate == orig_active_store

    # (b) validate_project failure: result with bad fingerprint hash
    critical_dialog_calls.clear()
    bad_fp = dict(result.fingerprint)
    bad_fp["head_tail_sha256"] = "invalid_hash"
    bad_result_b = LargeImportResult(
        table=result.table,
        row_count=result.row_count,
        headers=result.headers,
        physical_types=result.physical_types,
        model_types=result.model_types,
        source_arrow_types=result.source_arrow_types,
        kind=result.kind,
        options=result.options,
        fingerprint=bad_fp,
        notices=result.notices,
        source_id=result.source_id,
        stats=result.stats,
    )
    ret_b = controller._commit_store_import(csv_file, bad_result_b, project_store)
    assert ret_b is False
    assert len(critical_dialog_calls) == 1
    assert "Could not import data" in critical_dialog_calls[0]
    assert controller._project == orig_project
    assert set(controller._loaded_candidates.keys()) == orig_loaded_keys
    assert set(controller._raw_candidates.keys()) == orig_raw_keys
    assert set(controller._query_candidates.keys()) == orig_query_keys
    assert controller._active_source_id == orig_active_id
    assert controller._active_store_candidate == orig_active_store

    # (c) _install_source failure: monkeypatch StoreTableModel.replace_store to return False
    critical_dialog_calls.clear()
    monkeypatch.setattr(StoreTableModel, "replace_store", lambda *args, **kwargs: False)
    ret_c = controller._commit_store_import(csv_file, result, project_store)
    assert ret_c is False
    assert len(critical_dialog_calls) == 0  # no critical dialog on grid install fail
    assert controller._project == orig_project
    assert set(controller._loaded_candidates.keys()) == orig_loaded_keys
    assert set(controller._raw_candidates.keys()) == orig_raw_keys
    assert set(controller._query_candidates.keys()) == orig_query_keys
    assert controller._active_source_id == orig_active_id
    assert controller._active_store_candidate == orig_active_store
    assert "Could not load table from store" in controller.statusMessage

    project_store.close()
