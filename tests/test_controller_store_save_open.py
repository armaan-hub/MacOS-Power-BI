"""Tests for controller store save and open (Stage B4b task 13)."""

from __future__ import annotations

import csv
import os
from pathlib import Path
import shutil
import threading
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox

from analytics_studio.controller import StudioController
from analytics_studio.project import validate_project, load_project, save_project
from analytics_studio.store.base import StoreError
from analytics_studio.store.candidate import LargeTableError, StoreCandidate
from analytics_studio.store.large_import import run_large_import
from analytics_studio.store.table_model import StoreTableModel


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance()
    if app is None:
        app = QApplication(["controller_store_save_open_test"])
    return app


def _assert_no_blocking_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:
    def bad_dialog(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"Blocking dialog was unexpectedly invoked: {args} {kwargs}")

    monkeypatch.setattr(QFileDialog, "getOpenFileName", bad_dialog)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", bad_dialog)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", bad_dialog)
    monkeypatch.setattr(QMessageBox, "information", bad_dialog)
    monkeypatch.setattr(QMessageBox, "critical", bad_dialog)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(QInputDialog, "getText", bad_dialog)
    monkeypatch.setattr(QInputDialog, "getItem", bad_dialog)
    monkeypatch.setattr(QDialog, "exec", bad_dialog)
    monkeypatch.setattr(QDialog, "exec_", bad_dialog)


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


def _import_large_table(controller: StudioController, file_path: Path, kind: str = "csv") -> None:
    """Helper to commit a large table directly using run_large_import and _commit_store_import."""
    project_store = controller._ensure_project_store()
    with project_store.job():
        result = run_large_import(
            project_store.store,
            file_path,
            kind,
            {},
            source_id="src_large_1",
            cancel_event=threading.Event(),
            max_rows=1_000_000,
        )
    success = controller._commit_store_import(file_path, result, project_store)
    assert success is True


def test_save_as_and_open_round_trip_csv(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv_file(tmp_path, 2000)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    temp_store_path = Path(controller._project_store.path)
    assert temp_store_path.exists()

    # Save As to a project file
    project_path = tmp_path / "projects" / "test_project.npa"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    saved = controller._save_to(project_path)
    assert saved is True

    # Both .npa and .npa.data exist
    assert project_path.exists()
    data_path = Path(str(project_path) + ".data")
    assert data_path.exists()

    # Check project JSON validates
    loaded_doc, _ = load_project(project_path)
    validate_project(loaded_doc)

    # Bare filename in data_file
    store_record = loaded_doc["data_sources"][0]["store"]
    assert store_record["data_file"] == data_path.name
    assert "/" not in store_record["data_file"] and "\\" not in store_record["data_file"]

    # Temp store deleted on rebind
    assert not temp_store_path.exists()

    # Verify controller state after save
    assert controller._project_store.path == str(data_path)
    assert controller.dirty is False
    controller._close_project_store()

    # Open in fresh controller
    fresh_controller = StudioController()
    monkeypatch.setattr(fresh_controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata2"))

    # Assert StoreCandidate.rows is never accessed
    def forbidden_rows(self: StoreCandidate) -> list[dict[str, Any]]:
        raise LargeTableError("test_forbidden_rows: rows accessed during open!")

    monkeypatch.setattr(StoreCandidate, "rows", property(forbidden_rows))

    opened = fresh_controller.open_project_path(project_path)
    assert opened is True
    assert fresh_controller.rowCount == 2000
    assert fresh_controller.fieldNames == ["id", "val_float", "event_date", "description", "blank_col"]
    assert isinstance(fresh_controller.dataModel, StoreTableModel)
    assert fresh_controller.dataModel.rowCount() == 500  # Default initial window of StoreTableModel is 500

    # First cells match
    model = fresh_controller.dataModel
    assert model.headerData(0, Qt.Orientation.Horizontal) == "id"
    assert model.headerData(1, Qt.Orientation.Horizontal) == "val_float"
    assert model.data(model.index(0, 0)) == "1"
    assert model.data(model.index(0, 1)) == "1.50"

    # Status message starts with Opened
    assert fresh_controller.statusMessage.startswith("Opened ")


def test_round_trip_parquet_with_arrow_types(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    pq_file = _generate_parquet_file(tmp_path, 2000)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, pq_file, "parquet")

    pre_save_profile = {h: controller.profileColumn(h) for h in controller.fieldNames}
    project_path = tmp_path / "parquet_proj.npa"
    assert controller._save_to(project_path) is True
    controller._close_project_store()

    fresh = StudioController()
    monkeypatch.setattr(fresh, "_effective_app_data_dir", lambda: str(tmp_path / "appdata_fresh"))
    assert fresh.open_project_path(project_path) is True
    assert fresh.rowCount == 2000

    post_save_profile = {h: fresh.profileColumn(h) for h in fresh.fieldNames}
    assert post_save_profile == pre_save_profile


def test_plain_save_after_save_as(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv_file(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    project_path = tmp_path / "plain_save.npa"
    assert controller._save_to(project_path) is True

    data_path = Path(str(project_path) + ".data")
    initial_stat = data_path.stat()

    # Track copy_to calls
    copy_to_called = []
    real_copy_to = controller._project_store.copy_to

    def spy_copy_to(*args: Any, **kwargs: Any) -> None:
        copy_to_called.append(True)
        return real_copy_to(*args, **kwargs)

    monkeypatch.setattr(controller._project_store, "copy_to", spy_copy_to)

    # Change metadata to make dirty
    controller.rename_page(controller._active_page_id, "New Name")
    assert controller.dirty is True

    # Call save_current_project() (plain Save)
    assert controller.save_current_project() is True
    assert controller.dirty is False
    assert len(copy_to_called) == 0

    post_stat = data_path.stat()
    assert post_stat.st_mtime_ns == initial_stat.st_mtime_ns
    assert post_stat.st_size == initial_stat.st_size


def test_save_as_of_saved_project_to_second_folder(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv_file(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    proj1 = tmp_path / "folder1" / "proj.npa"
    proj1.parent.mkdir(parents=True, exist_ok=True)
    assert controller._save_to(proj1) is True
    data1 = Path(str(proj1) + ".data")
    assert data1.exists()

    proj2 = tmp_path / "folder2" / "proj.npa"
    proj2.parent.mkdir(parents=True, exist_ok=True)
    assert controller._save_to(proj2) is True
    data2 = Path(str(proj2) + ".data")
    assert data2.exists()

    # Both data files exist
    assert data1.exists()
    assert data2.exists()

    # Verify bare filename rewritten in JSON doc
    doc2, _ = load_project(proj2)
    assert doc2["data_sources"][0]["store"]["data_file"] == data2.name
    controller._close_project_store()

    # Move folder2 to folder3 (different directory path); since data_file is bare filename next to project, it opens!
    folder3 = tmp_path / "folder3"
    folder2 = tmp_path / "folder2"
    folder2.rename(folder3)
    proj3 = folder3 / "proj.npa"

    c3 = StudioController()
    assert c3.open_project_path(proj3) is True
    assert c3.rowCount == 500
    c3._close_project_store()

    # Open proj1 in fresh controller
    c1 = StudioController()
    assert c1.open_project_path(proj1) is True
    assert c1.rowCount == 500
    c1._close_project_store()


def test_atomicity_json_write_failure(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv_file(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    initial_store_path = controller._project_store.path
    project_path = tmp_path / "fail_json.npa"
    data_path = Path(str(project_path) + ".data")

    # Mock save_project to fail
    def mock_save_project(path: Any, doc: Any, **kwargs: Any) -> None:
        raise OSError("Disk write failed!")

    monkeypatch.setattr("analytics_studio.controller.save_project", mock_save_project)

    critical_boxes = []
    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: critical_boxes.append(args))

    success = controller._save_to(project_path)
    assert success is False
    assert not data_path.exists()
    assert not project_path.exists()
    assert controller._project_store.path == initial_store_path
    assert len(critical_boxes) > 0


def test_atomicity_copy_to_failure(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv_file(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    project_path = tmp_path / "fail_copy.npa"
    data_path = Path(str(project_path) + ".data")

    def mock_copy_to(*args: Any, **kwargs: Any) -> None:
        raise StoreError("Copy failed mid-way")

    monkeypatch.setattr(controller._project_store, "copy_to", mock_copy_to)

    success = controller._save_to(project_path)
    assert success is False
    assert not data_path.exists()
    assert not project_path.exists()


def test_atomicity_cancel_progress(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv_file(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    project_path = tmp_path / "cancel_copy.npa"
    data_path = Path(str(project_path) + ".data")

    orig_copy_to = controller._project_store.copy_to

    def cancel_on_copy(dest: str, *args: Any, cancel_event: threading.Event | None = None, **kwargs: Any) -> None:
        if cancel_event is not None:
            cancel_event.set()
        return orig_copy_to(dest, *args, cancel_event=cancel_event, **kwargs)

    monkeypatch.setattr(controller._project_store, "copy_to", cancel_on_copy)

    success = controller._save_to(project_path)
    assert success is False
    assert not data_path.exists()
    assert not project_path.exists()


def test_target_data_file_exists_dialog(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    csv_file = _generate_csv_file(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    project_path = tmp_path / "existing_data.npa"
    data_path = Path(str(project_path) + ".data")
    data_path.write_text("dummy leftover file", encoding="utf-8")

    # Answer No
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)
    ans_no = controller._save_to(project_path)
    assert ans_no is False
    assert not project_path.exists()
    assert data_path.read_text(encoding="utf-8") == "dummy leftover file"

    # Answer Yes
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    ans_yes = controller._save_to(project_path)
    assert ans_yes is True
    assert project_path.exists()
    assert data_path.stat().st_size > 1000


def test_free_space_check_refusal(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv_file(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    project_path = tmp_path / "no_space.npa"

    # Mock shutil.disk_usage to return 10 bytes free
    import collections
    Usage = collections.namedtuple("usage", ["total", "used", "free"])
    monkeypatch.setattr(shutil, "disk_usage", lambda p: Usage(1_000_000, 999_990, 10))

    success = controller._save_to(project_path)
    assert success is False
    assert "Not enough free space" in controller.statusMessage


def test_store_busy_refusal(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv_file(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    project_path = tmp_path / "busy.npa"

    # Acquire job to make busy
    with controller._project_store.job():
        success = controller._save_to(project_path)
        assert success is False
        assert "Cannot save while a store operation is in progress" in controller.statusMessage


def test_open_missing_data_file(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv_file(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    project_path = tmp_path / "missing_data.npa"
    assert controller._save_to(project_path) is True

    # Delete data file
    data_path = Path(str(project_path) + ".data")
    data_path.unlink()

    fresh = StudioController()
    opened = fresh.open_project_path(project_path)
    assert opened is True
    # Store source has load error with specific guidance
    source_id = "src_large_1"
    assert source_id in fresh._source_load_errors
    err_msg = fresh._source_load_errors[source_id]
    assert "is missing:" in err_msg
    assert "Import data_2000.csv again." in err_msg


def test_open_table_missing_or_corrupt(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv_file(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    project_path = tmp_path / "corrupt_data.npa"
    assert controller._save_to(project_path) is True
    controller._close_project_store()

    # Modify JSON doc to expect a table that doesn't exist
    doc, _ = load_project(project_path)
    doc["data_sources"][0]["store"]["table"] = "non_existent_table"
    save_project(project_path, doc)

    fresh = StudioController()
    opened = fresh.open_project_path(project_path)
    assert opened is True
    assert "src_large_1" in fresh._source_load_errors
    assert "non_existent_table" in fresh._source_load_errors["src_large_1"]


def test_open_fingerprint_changed_warning(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv_file(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    project_path = tmp_path / "fp_change.npa"
    assert controller._save_to(project_path) is True
    controller._close_project_store()

    # Append to original CSV to change size and mtime
    with open(csv_file, "a", encoding="utf-8") as f:
        f.write("9999,99.9,2026-09-01,extra,extra\n")

    warning_dialogs: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: warning_dialogs.append(text))

    fresh = StudioController()
    opened = fresh.open_project_path(project_path)
    assert opened is True
    assert fresh.rowCount == 500  # Still loads store table fine!
    assert any("changed on disk since it was imported" in w for w in warning_dialogs)

    # Missing original file produces no warning
    csv_file.unlink()
    fresh._close_project_store()
    warning_dialogs.clear()

    fresh2 = StudioController()
    opened2 = fresh2.open_project_path(project_path)
    assert opened2 is True
    assert not any("changed on disk since it was imported" in w for w in warning_dialogs)


def test_reopen_same_project_path(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv_file(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    project_path = tmp_path / "reopen.npa"
    assert controller._save_to(project_path) is True

    # Reopen same project path in the same controller instance
    opened = controller.open_project_path(project_path)
    assert opened is True
    assert controller.rowCount == 500
    assert controller._project_store is not None
    assert not controller._project_store.closed


def test_open_project_a_then_b_closes_store(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv_file(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    proj_a = tmp_path / "proj_a.npa"
    assert controller._save_to(proj_a) is True
    store_a = controller._project_store

    # Create project B (ordinary inline/csv source, no store)
    from analytics_studio.file_import import parse_file
    controller_b = StudioController()
    normal_csv = tmp_path / "small.csv"
    normal_csv.write_text("a,b\n1,2\n", encoding="utf-8")
    assert controller_b._commit_import(normal_csv, parse_file(normal_csv)) is True
    proj_b = tmp_path / "proj_b.npa"
    assert controller_b._save_to(proj_b) is True

    # Open project B in controller
    opened_b = controller.open_project_path(proj_b)
    assert opened_b is True
    assert controller._project_store is None
    assert store_a.closed is True


def test_open_project_a_then_new_project_closes_store(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv_file(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    proj_a = tmp_path / "proj_a.npa"
    assert controller._save_to(proj_a) is True
    store_a = controller._project_store

    controller._replace_with_new_project()
    assert controller._project_store is None
    assert store_a.closed is True


def test_calculated_column_pin(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv_file(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    proj_path = tmp_path / "calc_col.npa"
    assert controller._save_to(proj_path) is True
    controller._close_project_store()

    # Inject calculated column definition into project JSON
    doc, _ = load_project(proj_path)
    tbl = doc["model"]["tables"][0]
    tbl.setdefault("calculated_columns", []).append({
        "name": "calc_x",
        "expression": "[id] * 2",
    })
    save_project(proj_path, doc)

    fresh = StudioController()
    opened = fresh.open_project_path(proj_path)
    assert opened is True
    # Store table still loads
    assert fresh.rowCount == 500
    assert "id" in fresh.fieldNames


def test_shutdown_leaves_no_wal(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv_file(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    proj_path = tmp_path / "wal_check.npa"
    assert controller._save_to(proj_path) is True

    data_path = Path(str(proj_path) + ".data")
    wal_path = Path(str(data_path) + ".wal")

    # Shutdown store
    controller._close_project_store()
    assert not wal_path.exists()


def test_checkpoint_called_on_save(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv_file(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    checkpoint_called = []
    real_checkpoint = controller._project_store.checkpoint

    def spy_checkpoint() -> None:
        checkpoint_called.append(True)
        return real_checkpoint()

    monkeypatch.setattr(controller._project_store, "checkpoint", spy_checkpoint)

    project_path = tmp_path / "checkpoint.npa"
    assert controller._save_to(project_path) is True
    assert len(checkpoint_called) == 1


