"""Tests for controller store reload (Stage B4b task 16)."""

from __future__ import annotations

import collections
import csv
import os
from pathlib import Path
import time
from typing import Any
import pytest

from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox

from analytics_studio.controller import StudioController
from analytics_studio.file_import import ImportCancelledError
from analytics_studio.store.session import ProjectStore


@pytest.fixture
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["controller_store_reload_test"])
    return app


def _assert_no_blocking_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:
    def bad_dialog(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"Blocking dialog was unexpectedly invoked: {args} {kwargs}")

    monkeypatch.setattr(QFileDialog, "getOpenFileName", bad_dialog)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", bad_dialog)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", bad_dialog)
    monkeypatch.setattr(QMessageBox, "information", bad_dialog)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "critical", bad_dialog)
    monkeypatch.setattr(QInputDialog, "getText", bad_dialog)
    monkeypatch.setattr(QInputDialog, "getItem", bad_dialog)
    monkeypatch.setattr(QDialog, "exec", bad_dialog)
    monkeypatch.setattr(QDialog, "exec_", bad_dialog)


def _generate_csv(path: Path, headers: list[str], rows: list[list[str]]) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def _wait_for_job(controller: StudioController, timeout: float = 15.0) -> None:
    qapp = QApplication.instance()
    deadline = time.monotonic() + timeout
    while controller._large_import_job is not None and time.monotonic() < deadline:
        if qapp is not None:
            qapp.processEvents()
        time.sleep(0.01)
    if qapp is not None:
        qapp.processEvents()
    if controller._large_import_job is not None:
        raise TimeoutError("Large import job timed out.")


def _import_initial(controller: StudioController, path: Path) -> None:
    request = {"kind": "csv", "options": {}}
    assert controller._import_large(path, request) is True
    _wait_for_job(controller)


def test_reload_same_columns_new_content(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv(tmp_path / "data.csv", ["id", "val"], [["1", "Apple"], ["2", "Banana"]])
    controller = StudioController()
    try:
        _import_initial(controller, csv_file)
        store = controller._project_store
        source_id = controller._active_store_candidate.source_id
        g1_table = ProjectStore.table_name(source_id, 1)
        g2_table = ProjectStore.table_name(source_id, 2)
        g3_table = ProjectStore.table_name(source_id, 3)

        # Sort by id descending
        controller._store_table_model.sortByColumn(0)
        assert controller._store_table_model.sortColumn == "id"
        assert controller._store_table_model.sortDirection == "ascending"
        controller._store_table_model.sortByColumn(0)
        assert controller._store_table_model.sortDirection == "descending"

        # Update CSV with new rows
        _generate_csv(csv_file, ["id", "val"], [["3", "Cherry"], ["4", "Date"]])
        assert controller.reloadLargeTable() is True
        _wait_for_job(controller)

        assert "Reloaded 2 rows" in controller.statusMessage
        assert controller.dirty is True
        assert controller._active_store_candidate.row_count == 2
        # Verify sort persisted
        assert controller._store_table_model.sortColumn == "id"
        assert controller._store_table_model.sortDirection == "descending"

        # Check generation in memory
        source_rec = next(s for s in controller._project["data_sources"] if s["id"] == source_id)
        assert source_rec["store"]["generation"] == 2
        assert source_rec["store"]["table"] == g2_table

        # List tables in store: both g1 and g2 exist right now
        tables = store.call(lambda s: s.table_names())
        assert g1_table in tables
        assert g2_table in tables

        # Save project
        proj_path = tmp_path / "project.npa"
        assert controller._save_to(proj_path) is True
        assert controller.dirty is False

        # Old table g1 should now be dropped after Save
        tables_after_save = store.call(lambda s: s.table_names())
        assert g1_table not in tables_after_save
        assert g2_table in tables_after_save

        controller._close_project_store()

        # Reopen project and check no fingerprint warning
        c2 = StudioController()
        try:
            warnings: list[str] = []
            monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: warnings.append(text))
            assert c2.open_project_path(proj_path) is True
            assert c2.largeTableLoaded is True
            assert not any("changed on disk" in w for w in warnings)

            # Second reload on c2 should use generation 3
            _generate_csv(csv_file, ["id", "val"], [["5", "Elderberry"]])
            assert c2.reloadLargeTable() is True
            _wait_for_job(c2)

            source_rec3 = next(s for s in c2._project["data_sources"] if s["id"] == source_id)
            assert source_rec3["store"]["generation"] == 3
            assert source_rec3["store"]["table"] == g3_table
        finally:
            c2._close_project_store()
    finally:
        controller._close_project_store()


def test_reload_cancel_and_failure(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv(tmp_path / "data.csv", ["id", "val"], [["1", "A"], ["2", "B"]])
    controller = StudioController()
    proj_path = tmp_path / "saved_for_cancel.npa"
    try:
        _import_initial(controller, csv_file)
        assert controller._save_to(proj_path) is True
        store = controller._project_store
        source_id = controller._active_store_candidate.source_id
        g1_table = ProjectStore.table_name(source_id, 1)
        g2_table = ProjectStore.table_name(source_id, 2)

        # 1. Cancel from job
        import analytics_studio.store.large_import as li_mod

        def canceling_run(*args: Any, **kwargs: Any) -> Any:
            raise ImportCancelledError("Import canceled.")

        monkeypatch.setattr(li_mod, "run_large_import", canceling_run)
        assert controller.reloadLargeTable() is True
        _wait_for_job(controller)

        assert "Reload canceled." in controller.statusMessage
        assert controller.dirty is False
        tables = store.call(lambda s: s.table_names())
        assert g1_table in tables
        assert g2_table not in tables

        # 2. Failure: ragged/corrupt file or over max_rows
        monkeypatch.undo()
        _assert_no_blocking_dialogs(monkeypatch)
        from analytics_studio.file_import import FileImportError

        def failing_run(*args: Any, **kwargs: Any) -> Any:
            raise FileImportError("The file exceeds the row import limit.")

        monkeypatch.setattr(li_mod, "run_large_import", failing_run)
        assert controller.reloadLargeTable() is True
        _wait_for_job(controller)

        assert "import limit" in controller.statusMessage.lower() or "error" in controller.statusMessage.lower()
        tables = store.call(lambda s: s.table_names())
        assert g1_table in tables
        assert g2_table not in tables
        assert controller._active_store_candidate.row_count == 2
        assert controller.dirty is False
    finally:
        controller._close_project_store()


def test_reload_order_discard_and_save_fail(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv(tmp_path / "data.csv", ["id", "val"], [["1", "Original"]])
    controller = StudioController()
    proj_path = tmp_path / "saved.npa"
    try:
        _import_initial(controller, csv_file)
        assert controller._save_to(proj_path) is True
        source_id = controller._active_store_candidate.source_id
        g1_table = ProjectStore.table_name(source_id, 1)
        g2_table = ProjectStore.table_name(source_id, 2)

        # Reload with new data
        _generate_csv(csv_file, ["id", "val"], [["2", "Reloaded"]])
        assert controller.reloadLargeTable() is True
        _wait_for_job(controller)
        assert controller.dirty is True

        # Reopen saved project without saving current -> discards reload
        monkeypatch.setattr(controller, "_confirm_replace_project", lambda: True)
        assert controller.open_project_path(proj_path) is True
        # Check that it reopened with OLD rows and g2 was dropped by open
        assert controller._active_store_candidate.row_count == 1
        tables = controller._project_store.call(lambda s: s.table_names())
        assert g1_table in tables
        assert g2_table not in tables

        # Reload again, then save_project fails
        assert controller.reloadLargeTable() is True
        _wait_for_job(controller)

        import analytics_studio.controller as ctrl_mod
        def failing_save(*args: Any, **kwargs: Any) -> Any:
            raise OSError("Disk write error")

        critical_calls: list[str] = []
        monkeypatch.setattr(QMessageBox, "critical", lambda parent, title, msg: critical_calls.append(msg))
        monkeypatch.setattr(ctrl_mod, "save_project", failing_save)

        assert controller._save_to(proj_path) is False
        assert len(critical_calls) == 1
        # Check old table still in the file, no table lost
        tables = controller._project_store.call(lambda s: s.table_names())
        assert g1_table in tables
        assert g2_table in tables
    finally:
        controller._close_project_store()


def test_reload_crash_leftover(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv(tmp_path / "data.csv", ["id", "val"], [["1", "A"]])
    controller = StudioController()
    try:
        _import_initial(controller, csv_file)
        store = controller._project_store
        source_id = controller._active_store_candidate.source_id

        # Pre-create a leftover table src_<id>_g2 in store
        leftover_table = ProjectStore.table_name(source_id, 2)
        store.call(lambda s: s.create_table(leftover_table, [("id", "text")]))

        tables_before = store.call(lambda s: s.table_names())
        assert leftover_table in tables_before

        # Reload should skip g2 and use g3
        _generate_csv(csv_file, ["id", "val"], [["2", "B"]])
        assert controller.reloadLargeTable() is True
        _wait_for_job(controller)

        assert "Reloaded 1 rows" in controller.statusMessage
        source_rec = next(s for s in controller._project["data_sources"] if s["id"] == source_id)
        assert source_rec["store"]["generation"] == 3
        assert source_rec["store"]["table"] == ProjectStore.table_name(source_id, 3)
    finally:
        controller._close_project_store()


def test_reload_changed_columns(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv(tmp_path / "data.csv", ["id", "amount", "category"], [["1", "10", "A"]])
    controller = StudioController()
    try:
        _import_initial(controller, csv_file)
        source_id = controller._active_store_candidate.source_id
        g1_table = ProjectStore.table_name(source_id, 1)
        g2_table = ProjectStore.table_name(source_id, 2)
        store = controller._project_store

        # 1. Column used by measure -> reload removes it -> Refused
        controller._project.setdefault("model", {}).setdefault("measures", []).append({
            "name": "TotalAmount",
            "expression": "SUM([amount])",
        })

        _generate_csv(csv_file, ["id", "category"], [["1", "A"]])
        assert controller.reloadLargeTable() is True
        _wait_for_job(controller)

        assert "The reloaded file no longer has the columns amount that the project uses. The large-data table was not reloaded." in controller.statusMessage
        # Check new table dropped, old table kept
        tables = store.call(lambda s: s.table_names())
        assert g1_table in tables
        assert g2_table not in tables

        # Clean measure
        controller._project["model"]["measures"].clear()

        # 2. Renamed column -> prompt question -> Answer No drops new table, changes nothing
        question_calls: list[str] = []
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda parent, title, msg, buttons, default: question_calls.append(msg) or QMessageBox.StandardButton.No,
        )

        _generate_csv(csv_file, ["id", "total_amt", "category"], [["1", "10", "A"]])
        assert controller.reloadLargeTable() is True
        _wait_for_job(controller)

        assert len(question_calls) == 1
        assert "differ from the current table" in question_calls[0]
        tables = store.call(lambda s: s.table_names())
        assert g1_table in tables
        assert g2_table not in tables
        assert controller._active_store_candidate.headers == ["id", "amount", "category"]

        # 3. Answer Yes -> swaps table
        question_calls.clear()
        monkeypatch.setattr(
            QMessageBox,
            "question",
            lambda parent, title, msg, buttons, default: question_calls.append(msg) or QMessageBox.StandardButton.Yes,
        )
        assert controller.reloadLargeTable() is True
        _wait_for_job(controller)

        assert len(question_calls) == 1
        assert controller._active_store_candidate.headers == ["id", "total_amt", "category"]
        assert g2_table in store.call(lambda s: s.table_names())

        # 4. Type change clears only filter of that column
        # Set filter on category and total_amt
        controller._store_table_model.setColumnFilter("category", "equals", "A")
        controller._store_table_model.setColumnFilter("total_amt", "equals", "10")
        assert controller._store_table_model.isColumnFiltered("category") is True
        assert controller._store_table_model.isColumnFiltered("total_amt") is True

        # Change total_amt to string text values like "Ten" so its detected type becomes text instead of whole_number
        _generate_csv(csv_file, ["id", "total_amt", "category"], [["1", "Ten", "A"]])
        assert controller.reloadLargeTable() is True
        _wait_for_job(controller)

        # category filter preserved, total_amt filter cleared due to type change
        assert controller._store_table_model.isColumnFiltered("category") is True
        assert controller._store_table_model.isColumnFiltered("total_amt") is False
    finally:
        controller._close_project_store()


def test_reload_preconditions(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    controller = StudioController()
    try:
        # 1. No large table loaded
        assert controller.reloadLargeTable() is False
        assert "Open a large-data table first." in controller.statusMessage

        # Load table
        csv_file = _generate_csv(tmp_path / "data.csv", ["id"], [["1"]])
        _import_initial(controller, csv_file)

        # 2. Busy store
        ps = controller._project_store
        ps._busy = True
        assert controller.reloadLargeTable() is False
        assert "The large-data store is busy. Try again in a moment." in controller.statusMessage
        ps._busy = False

        # 3. Missing file
        csv_file.unlink()
        assert controller.reloadLargeTable() is False
        assert "was not found. The large-data table was not reloaded." in controller.statusMessage

        # Re-create file
        _generate_csv(csv_file, ["id"], [["1"]])

        # 4. Free space check: mock shutil.disk_usage
        import shutil
        Usage = collections.namedtuple("usage", ["total", "used", "free"])
        table_size = os.path.getsize(ps.path)

        # 1.05x (less than 1.1x) -> failure
        monkeypatch.setattr(shutil, "disk_usage", lambda p: Usage(10 * table_size, 0, int(table_size * 1.05)))
        assert controller.reloadLargeTable() is False
        assert "Not enough free disk space to reload the table." in controller.statusMessage

        # 1.15x (more than 1.1x) -> passes precondition and proceeds
        monkeypatch.setattr(shutil, "disk_usage", lambda p: Usage(10 * table_size, 0, int(table_size * 1.15)))
        assert controller.reloadLargeTable() is True
        _wait_for_job(controller)
        assert "Reloaded 1 rows" in controller.statusMessage
    finally:
        controller._close_project_store()


def test_reload_save_as(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv(tmp_path / "data.csv", ["id", "val"], [["1", "Original"]])
    controller = StudioController()
    proj_a = tmp_path / "proj_a.npa"
    proj_b = tmp_path / "proj_b.npa"
    try:
        _import_initial(controller, csv_file)
        assert controller._save_to(proj_a) is True

        # Reload with new rows
        _generate_csv(csv_file, ["id", "val"], [["2", "Reloaded"]])
        assert controller.reloadLargeTable() is True
        _wait_for_job(controller)

        # Save As to proj_b
        assert controller._save_to(proj_b) is True
        controller._close_project_store()

        # Old project opens with g1 (old rows)
        c_old = StudioController()
        try:
            assert c_old.open_project_path(proj_a) is True
            assert c_old._active_store_candidate.row_count == 1
            src_a = next(s for s in c_old._project["data_sources"] if s.get("store"))
            assert src_a["store"]["generation"] == 1
        finally:
            c_old._close_project_store()

        # New project opens with g2 (reloaded rows)
        c_new = StudioController()
        try:
            assert c_new.open_project_path(proj_b) is True
            assert c_new._active_store_candidate.row_count == 1
            src_b = next(s for s in c_new._project["data_sources"] if s.get("store"))
            assert src_b["store"]["generation"] == 2
        finally:
            c_new._close_project_store()
    finally:
        controller._close_project_store()


def test_qml_reload_table_button() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    text = (repo_root / "analytics_studio" / "qml" / "DataView.qml").read_text(encoding="utf-8")
    assert 'text: "Reload table"' in text
    assert 'root.appController.reloadLargeTable()' in text
    assert 'visible: root.appController.largeTableLoaded' in text


def test_existing_first_import_generation_one(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _generate_csv(tmp_path / "data.csv", ["id"], [["1"]])
    controller = StudioController()
    try:
        _import_initial(controller, csv_file)
        source_rec = next(s for s in controller._project["data_sources"] if s.get("store"))
        assert source_rec["store"]["generation"] == 1
        assert source_rec["store"]["table"].endswith("_g1")
    finally:
        controller._close_project_store()
