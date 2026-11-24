"""Tests for the save and open review findings (Stage B4b task 13b)."""

from __future__ import annotations

import collections
import decimal
import os
import shutil
import threading
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from analytics_studio.controller import StudioController
from analytics_studio.project import load_project, save_project
from analytics_studio.store.base import StoreError
from analytics_studio.store.table_model import StoreTableModel
from tests.test_controller_store_save_open import (
    _assert_no_blocking_dialogs,
    _generate_csv_file,
    _import_large_table,
    qapp,
)

__all__ = ["qapp"]


def _csv(directory: Path, row_count: int = 2000) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return _generate_csv_file(directory, row_count)


def test_calculated_column_pin_on_ordinary_source(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Calculated column on an ordinary source in a project that also has a store source."""
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _csv(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    proj_path = tmp_path / "calc_col_ord.npa"
    assert controller._save_to(proj_path) is True
    controller._close_project_store()

    # Add an ordinary source and table with a calculated column
    doc, _ = load_project(proj_path)
    ord_csv = tmp_path / "ord.csv"
    ord_csv.write_text("cid,val\n1,10\n2,20\n", encoding="utf-8")
    doc["data_sources"].append({
        "id": "src_ord_1",
        "name": "ord",
        "kind": "csv",
        "path": str(ord_csv),
        "parser_options": {},
    })
    doc["model"]["tables"].append({
        "id": "src_ord_1",
        "source_id": "src_ord_1",
        "name": "ord",
        "column_types": {"cid": "whole_number", "val": "whole_number"},
        "calculated_columns": [
            {"name": "calc_ord", "expression": "[val] + 5"}
        ],
    })
    save_project(proj_path, doc)

    fresh = StudioController()
    opened = fresh.open_project_path(proj_path)
    assert opened is True
    # The ordinary source loads with its calculated column preserved
    ord_tbl = next((t for t in fresh._project["model"]["tables"] if t.get("name") == "ord"), None)
    assert ord_tbl is not None
    assert any(c.get("name") == "calc_ord" for c in ord_tbl.get("calculated_columns", []))


def test_m1_copy_failure_oserror_shows_critical_box(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M1: OSError (disk full) during copy -> critical box with that text, status not 'Save canceled.'"""
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _csv(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    critical_boxes = []
    monkeypatch.setattr(QMessageBox, "critical", lambda parent, title, text: critical_boxes.append((title, text)))

    def fail_copy(*args: Any, progress: Any = None, **kwargs: Any) -> None:
        if progress:
            progress(10, 100)
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(controller._project_store, "copy_to", fail_copy)

    project_path = tmp_path / "m1_disk_full.npa"
    success = controller._save_to(project_path)
    assert success is False
    assert controller.statusMessage != "Save canceled."
    assert len(critical_boxes) == 1
    assert "No space left on device" in critical_boxes[0][1]
    assert "Could not save the large-data table:" in critical_boxes[0][1]


def test_m1_copy_failure_store_error_shows_critical_box(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M1: StoreError('copy exploded') during copy -> critical box with that text, status not 'Save canceled.'"""
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _csv(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    critical_boxes = []
    monkeypatch.setattr(QMessageBox, "critical", lambda parent, title, text: critical_boxes.append((title, text)))

    def fail_copy(*args: Any, **kwargs: Any) -> None:
        raise StoreError("copy exploded")

    monkeypatch.setattr(controller._project_store, "copy_to", fail_copy)

    project_path = tmp_path / "m1_store_err.npa"
    success = controller._save_to(project_path)
    assert success is False
    assert controller.statusMessage != "Save canceled."
    assert len(critical_boxes) == 1
    assert "copy exploded" in critical_boxes[0][1]
    assert "Could not save the large-data table:" in critical_boxes[0][1]


def test_m1_real_cancel_sets_save_canceled_no_box(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M1: Real cancel -> no error box, status 'Save canceled.'"""
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _csv(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    critical_boxes = []
    monkeypatch.setattr(QMessageBox, "critical", lambda parent, title, text: critical_boxes.append((title, text)))

    orig_copy_to = controller._project_store.copy_to
    def cancel_copy(*args: Any, cancel_event: threading.Event | None = None, **kwargs: Any) -> None:
        if cancel_event is not None:
            cancel_event.set()
        return orig_copy_to(*args, cancel_event=cancel_event, **kwargs)

    monkeypatch.setattr(controller._project_store, "copy_to", cancel_copy)

    project_path = tmp_path / "m1_canceled.npa"
    success = controller._save_to(project_path)
    assert success is False
    assert controller.statusMessage == "Save canceled."
    assert len(critical_boxes) == 0


def test_m1_self_copy_refusal_shows_critical_box(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M1: Self-copy refusal (Save As to case-insensitive name or monkeypatched samefile) -> box with refusal text."""
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _csv(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    critical_boxes = []
    monkeypatch.setattr(QMessageBox, "critical", lambda parent, title, text: critical_boxes.append((title, text)))

    # Force copy_to to raise self-copy refusal
    def self_copy(*args: Any, **kwargs: Any) -> None:
        raise StoreError("Cannot copy the data file onto itself.")

    monkeypatch.setattr(controller._project_store, "copy_to", self_copy)

    project_path = tmp_path / "m1_self_copy.npa"
    success = controller._save_to(project_path)
    assert success is False
    assert len(critical_boxes) == 1
    assert "Cannot copy the data file onto itself." in critical_boxes[0][1]
    assert "Could not save the large-data table:" in critical_boxes[0][1]


def test_m2_open_a_then_c_missing_store_closes_old_store(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M2: Open A (store), then C (store data file missing): _project_store is None, A's data file can be opened by 2nd ProjectStore, Save As of C copies nothing and JSON store.data_file unchanged."""
    _assert_no_blocking_dialogs(monkeypatch)
    from analytics_studio.store.session import ProjectStore
    csv_file = _csv(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    proj_a = tmp_path / "proj_a.npa"
    assert controller._save_to(proj_a) is True
    data_a = Path(str(proj_a) + ".data")

    # Create project C with store pointing to missing file
    proj_c = tmp_path / "proj_c.npa"
    doc_c, _ = load_project(proj_a)
    doc_c["data_sources"][0]["store"]["data_file"] = "non_existent.npa.data"
    save_project(proj_c, doc_c)

    # Open C in the same controller
    opened_c = controller.open_project_path(proj_c)
    assert opened_c is True
    # Old store was closed, new store failed to open -> _project_store is None
    assert controller._project_store is None

    # A's data file can now be opened by a second ProjectStore (not locked)
    second_store = ProjectStore.open(str(data_a))
    assert not second_store.closed
    second_store.close()

    # Save As of C copies nothing and C's JSON store.data_file stays as it was
    proj_c_copy = tmp_path / "proj_c_copy.npa"
    save_as_success = controller._save_to(proj_c_copy)
    assert save_as_success is True
    # No data file was copied
    assert not Path(str(proj_c_copy) + ".data").exists()
    # C's JSON store.data_file kept its record unchanged
    saved_c_doc, _ = load_project(proj_c_copy)
    assert saved_c_doc["data_sources"][0]["store"]["data_file"] == "non_existent.npa.data"


def test_m2_save_as_one_working_and_one_failed_store_source(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M2: A project with one working store source and one failed store source saves only the working one's file."""
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file1 = _csv(tmp_path / "d1", 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file1, "csv")

    proj_mixed = tmp_path / "mixed.npa"
    assert controller._save_to(proj_mixed) is True
    controller._close_project_store()

    # Add a second store source to doc that points to a missing table/data file
    doc, _ = load_project(proj_mixed)
    failed_source = {
        "id": "src_failed_store",
        "name": "failed_store",
        "kind": "csv",
        "path": str(tmp_path / "missing.csv"),
        "parser_options": {},
        "store": {
            "source_id": "src_failed_store",
            "table": "src_missing_tbl",
            "data_file": "missing.npa.data",
            "row_count": 100,
            "headers": ["a"],
            "physical_types": ["text"],
            "column_types": {"a": "text"},
            "fingerprint": {"size": 100, "mtime_ns": 1000, "head_tail_sha256": "0" * 64},
            "generation": 1,
            "duckdb_version": "1.0.0",
        },
    }
    doc["data_sources"].append(failed_source)
    save_project(proj_mixed, doc)

    # Open mixed project
    fresh = StudioController()
    opened = fresh.open_project_path(proj_mixed)
    assert opened is True
    # The first source loaded, second failed
    assert "src_failed_store" in fresh._source_load_errors
    assert fresh._project_store is not None

    # Save As to mixed_save_as.npa
    mixed_save_as = tmp_path / "mixed_save_as.npa"
    assert fresh._save_to(mixed_save_as) is True

    # The working store's file is copied
    assert Path(str(mixed_save_as) + ".data").exists()
    # The failed source kept its old data_file record unchanged
    doc_after, _ = load_project(mixed_save_as)
    src_failed_after = next(s for s in doc_after["data_sources"] if s["id"] == "src_failed_store")
    assert src_failed_after["store"]["data_file"] == "missing.npa.data"


def test_m2_reopen_same_project_store_open_fails_leaves_no_locked_store(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M2: the first open of the data file fails when the same project is re-opened.

    The old store is restored, then closed because the new project has no usable store.
    Nothing stays locked and the project is open with a load error for the table.
    """
    _assert_no_blocking_dialogs(monkeypatch)
    from analytics_studio.store.session import ProjectStore

    csv_file = _csv(tmp_path, 500)
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    proj_path = tmp_path / "reopen_corrupt.npa"
    assert controller._save_to(proj_path) is True
    data_path = Path(str(proj_path) + ".data")

    real_open = ProjectStore.open
    calls: list[str] = []

    def open_fails_once(path: str) -> Any:
        calls.append(path)
        if len(calls) == 1:
            raise StoreError("data file corrupt simulated")
        return real_open(path)

    monkeypatch.setattr(ProjectStore, "open", staticmethod(open_fails_once))

    assert controller.open_project_path(proj_path) is True
    # first call failed, second call is the restore of the old store
    assert len(calls) == 2
    assert controller._project_store is None
    assert "src_large_1" in controller._source_load_errors
    assert controller._project["data_sources"][0]["store"]["data_file"] == data_path.name

    second = real_open(str(data_path))
    assert not second.closed
    second.close()


def test_m2_reopen_same_project_table_validation_fails_keeps_store_usable(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M2: the data file opens but the table fails validation: the live store stays usable."""
    _assert_no_blocking_dialogs(monkeypatch)
    from analytics_studio.store.session import ProjectStore

    csv_file = _csv(tmp_path, 500)
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    proj_path = tmp_path / "reopen_invalid.npa"
    assert controller._save_to(proj_path) is True

    def bad_validate(self: Any, *args: Any, **kwargs: Any) -> None:
        raise StoreError("table corrupt simulated")

    monkeypatch.setattr(ProjectStore, "validate_table", bad_validate)

    assert controller.open_project_path(proj_path) is True
    assert "src_large_1" in controller._source_load_errors
    assert controller._project_store is not None
    assert not controller._project_store.closed
    assert controller._project["data_sources"][0]["store"]["table"] == "src_src_large_1_g1"

    # O7b: a live store but no loaded store table: Save As copies nothing and keeps the record
    copy_target = tmp_path / "reopen_invalid_copy.npa"
    assert controller._save_to(copy_target) is True
    assert not Path(str(copy_target) + ".data").exists()
    saved, _ = load_project(copy_target)
    assert saved["data_sources"][0]["store"]["data_file"] == "reopen_invalid.npa.data"


def test_m2_open_a_then_b_swaps_store(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M2: open project A (store) then project B (other store): B's rows are live and A's file is not locked."""
    _assert_no_blocking_dialogs(monkeypatch)
    from analytics_studio.store.session import ProjectStore

    csv_a = _csv(tmp_path / "a", 300)
    ctl_a = StudioController()
    monkeypatch.setattr(ctl_a, "_effective_app_data_dir", lambda: str(tmp_path / "appdata_a"))
    _import_large_table(ctl_a, csv_a, "csv")
    proj_a = tmp_path / "proj_a.npa"
    assert ctl_a._save_to(proj_a) is True
    ctl_a._close_project_store()

    csv_b = _csv(tmp_path / "b", 700)
    ctl_b = StudioController()
    monkeypatch.setattr(ctl_b, "_effective_app_data_dir", lambda: str(tmp_path / "appdata_b"))
    _import_large_table(ctl_b, csv_b, "csv")
    proj_b = tmp_path / "proj_b.npa"
    assert ctl_b._save_to(proj_b) is True
    ctl_b._close_project_store()

    controller = StudioController()
    assert controller.open_project_path(proj_a) is True
    store_a = controller._project_store
    assert controller.rowCount == 300
    assert controller.open_project_path(proj_b) is True
    assert controller.rowCount == 700
    assert store_a is not None and store_a.closed
    assert controller._project_store is not store_a
    assert Path(controller._project_store.path).name == "proj_b.npa.data"

    second = ProjectStore.open(str(tmp_path / "proj_a.npa.data"))
    assert not second.closed
    second.close()


def test_m3_refresh_refusal_for_failed_store_source(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M3: Open a project whose store file is missing, call refresh_all_sources() and refresh_source(<id>) with parse_file spied:
    parse_file is never called for the store source, the source record is unchanged, an ordinary source still refreshes."""
    _assert_no_blocking_dialogs(monkeypatch)
    import analytics_studio.controller as ctrl_mod
    parse_file_calls = []
    real_parse_file = ctrl_mod.parse_file

    def spy_parse_file(path: Any, *args: Any, **kwargs: Any) -> Any:
        parse_file_calls.append(str(path))
        return real_parse_file(path, *args, **kwargs)

    monkeypatch.setattr(ctrl_mod, "parse_file", spy_parse_file)

    csv_file = _csv(tmp_path / "s", 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    proj_path = tmp_path / "m3_proj.npa"
    assert controller._save_to(proj_path) is True
    controller._close_project_store()

    # Add an ordinary source
    doc, _ = load_project(proj_path)
    ord_csv = tmp_path / "ord.csv"
    ord_csv.write_text("id,val\n1,10\n2,20\n", encoding="utf-8")
    doc["data_sources"].append({
        "id": "src_ord",
        "name": "ord",
        "kind": "csv",
        "path": str(ord_csv),
        "parser_options": {},
    })
    doc["model"]["tables"].append({
        "id": "src_ord",
        "source_id": "src_ord",
        "name": "ord",
        "column_types": {"id": "whole_number", "val": "whole_number"},
    })
    # Remove store data file so the store source fails to load
    data_path = Path(str(proj_path) + ".data")
    data_path.unlink()
    save_project(proj_path, doc)

    # Open project
    fresh = StudioController()
    opened = fresh.open_project_path(proj_path)
    assert opened is True
    assert "src_large_1" in fresh._source_load_errors

    parse_file_calls.clear()

    # Refresh all sources
    fresh.refresh_all_sources()
    # parse_file was called for ord_csv, but NOT for the store csv
    assert str(ord_csv) in parse_file_calls
    assert str(csv_file) not in parse_file_calls
    # Store source record, store key, and table record are untouched
    store_src = next(s for s in fresh._project["data_sources"] if s["id"] == "src_large_1")
    assert "store" in store_src
    assert store_src["store"]["table"] == "src_src_large_1_g1"

    # Refresh individual store source
    fresh._active_source_id = "src_large_1"
    fresh._active_source_path = Path(store_src["path"])
    fresh._active_source_kind = "csv"
    parse_file_calls.clear()
    fresh.refresh_source()
    assert str(csv_file) not in parse_file_calls
    assert "is a large-data table. Import the file again to reload it." in fresh.statusMessage


def test_m4_m15_discard_copy_called_on_copy_failure(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M4 / M15: assert discard_copy called and no <stem>.npa.data or temp left when copy fails."""
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _csv(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    monkeypatch.setattr(QMessageBox, "critical", lambda *args, **kwargs: None)
    discard_calls = []
    real_discard = controller._project_store.discard_copy
    def spy_discard(path: str) -> None:
        discard_calls.append(path)
        return real_discard(path)
    monkeypatch.setattr(controller._project_store, "discard_copy", spy_discard)

    def fail_copy(dest: str, *args: Any, **kwargs: Any) -> None:
        # Create a partial file at dest to verify discard_copy cleans it
        Path(dest).write_text("partial", encoding="utf-8")
        raise StoreError("copy failed")

    monkeypatch.setattr(controller._project_store, "copy_to", fail_copy)

    target = tmp_path / "m15_fail.npa"
    success = controller._save_to(target)
    assert success is False
    assert len(discard_calls) == 1
    assert not Path(str(target) + ".data").exists()
    assert len(list(tmp_path.glob("m15_fail.npa.data*"))) == 0


def test_m4_m18_rebind_failure_shows_critical_box_and_leaves_state(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M4 / M18: rebind fails after JSON written -> error box shown, state text."""
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _csv(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    critical_boxes = []
    monkeypatch.setattr(QMessageBox, "critical", lambda parent, title, text: critical_boxes.append((title, text)))

    def fail_rebind(*args: Any, **kwargs: Any) -> None:
        raise StoreError("rebind failed simulated")

    monkeypatch.setattr(controller._project_store, "rebind", fail_rebind)

    target = tmp_path / "m18_rebind_fail.npa"
    success = controller._save_to(target)
    assert success is False
    assert len(critical_boxes) == 1
    assert "rebind failed simulated" in critical_boxes[0][1]


def test_m4_o4_drop_unreferenced_called_on_open(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M4 / O4: drop_unreferenced called with store tables: stale extra table in data file is dropped on open."""
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _csv(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    project_path = tmp_path / "o4_stale.npa"
    assert controller._save_to(project_path) is True
    # Add a stale table starting with src_ to the data file
    controller._project_store.store.create_table("src_stale_extra", [("x", "whole")])
    assert "src_stale_extra" in controller._project_store.store.table_names()
    controller._close_project_store()

    fresh = StudioController()
    opened = fresh.open_project_path(project_path)
    assert opened is True
    # The stale table was dropped, the referenced table stays
    all_tbls = fresh._project_store.store.table_names()
    assert "src_stale_extra" not in all_tbls
    ref_tbl = fresh._project["data_sources"][0]["store"]["table"]
    assert ref_tbl in all_tbls


def test_m4_o11_column_types_fallback_from_table_record(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M4 / O11: store['column_types'] absent but table record has them -> types from table record."""
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _csv(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    project_path = tmp_path / "o11_col_types.npa"
    assert controller._save_to(project_path) is True
    controller._close_project_store()

    # Remove store['column_types'] from JSON but keep in table record
    doc, _ = load_project(project_path)
    doc["data_sources"][0]["store"].pop("column_types", None)
    doc["model"]["tables"][0]["column_types"] = {"id": "whole_number", "val_float": "decimal_number"}
    save_project(project_path, doc)

    fresh = StudioController()
    opened = fresh.open_project_path(project_path)
    assert opened is True
    cand = fresh._loaded_candidates["src_large_1"]
    assert cand.model_types.get("id") == "whole_number"
    assert cand.model_types.get("val_float") == "decimal_number"


def test_l1_data_model_updated_to_live_store_after_save_as(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """L1: After Save As the model's store IS the live session store and a page read works."""
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _csv(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    proj1 = tmp_path / "l1_proj1.npa"
    assert controller._save_to(proj1) is True

    proj2 = tmp_path / "l1_proj2.npa"
    assert controller._save_to(proj2) is True

    # Check model store
    data_model = controller.dataModel
    assert isinstance(data_model, StoreTableModel)
    assert data_model._store is controller._project_store.store
    # Page read works
    assert controller.rowCount == 500
    assert data_model.rowCount() == 500
    index = data_model.index(0, 0)
    assert data_model.data(index) is not None


def test_l3_disk_usage_error_handling(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """L3: disk_usage raising OSError -> save proceeds; raising ValueError -> error box, nothing written."""
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _csv(tmp_path, 500)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    critical_boxes = []
    monkeypatch.setattr(QMessageBox, "critical", lambda parent, title, text: critical_boxes.append((title, text)))

    # OSError from disk_usage -> logged warning and save proceeds
    def fake_copy_l3(target_data_path: str, *args: Any, **kwargs: Any) -> None:
        shutil.copyfile(controller._project_store.path, target_data_path)
    monkeypatch.setattr(controller._project_store, "copy_to", fake_copy_l3)

    def os_error_disk_usage(p: Any) -> Any:
        raise OSError("device not configured")

    monkeypatch.setattr(shutil, "disk_usage", os_error_disk_usage)
    proj_os = tmp_path / "l3_os.npa"
    assert controller._save_to(proj_os) is True
    assert proj_os.exists()

    # ValueError from disk_usage -> error box, nothing written
    def val_error_disk_usage(p: Any) -> Any:
        raise ValueError("corrupted parameter")

    monkeypatch.setattr(shutil, "disk_usage", val_error_disk_usage)
    critical_boxes.clear()
    proj_val = tmp_path / "l3_val.npa"
    success_val = controller._save_to(proj_val)
    assert success_val is False
    assert not proj_val.exists()
    assert len(critical_boxes) == 1
    assert "corrupted parameter" in critical_boxes[0][1]





# -----------------------------------------------------------------------------
# Tests that replace edits of existing tests (new names, existing tests untouched)
# -----------------------------------------------------------------------------

def _generate_decimal_parquet_file(tmp_path: Path, row_count: int = 600) -> Path:
    pa = pytest.importorskip("pyarrow")
    import pyarrow.parquet as pq

    tmp_path.mkdir(parents=True, exist_ok=True)
    pq_file = tmp_path / "data_decimal.parquet"
    ids = list(range(1, row_count + 1))
    decimals = [None if i % 10 == 0 else decimal.Decimal(f"{i * 2}.50") for i in ids]
    table = pa.Table.from_arrays(
        [pa.array(ids, type=pa.int64()), pa.array(decimals, type=pa.decimal128(10, 2))],
        names=["id", "dec_col"],
    )
    pq.write_table(table, pq_file)
    return pq_file


def test_o6_parquet_decimal_profile_and_export_equal_after_save_and_reopen(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """O6: source_arrow_types survive save+reopen: a DECIMAL column profiles and exports the same."""
    _assert_no_blocking_dialogs(monkeypatch)
    pq_file = _generate_decimal_parquet_file(tmp_path / "pq", 600)

    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, pq_file, "parquet")
    assert any("decimal" in str(t).lower() for t in controller._loaded_candidates["src_large_1"].source_arrow_types)

    pre_profile = {h: controller.profileColumn(h) for h in controller.fieldNames}
    pre_export = tmp_path / "pre.csv"
    assert controller.export_data_path(pre_export) is True

    project_path = tmp_path / "dec_proj.npa"
    assert controller._save_to(project_path) is True
    controller._close_project_store()

    fresh = StudioController()
    assert fresh.open_project_path(project_path) is True
    assert fresh._loaded_candidates["src_large_1"].source_arrow_types == controller._loaded_candidates["src_large_1"].source_arrow_types
    post_profile = {h: fresh.profileColumn(h) for h in fresh.fieldNames}
    post_export = tmp_path / "post.csv"
    assert fresh.export_data_path(post_export) is True

    assert post_profile == pre_profile
    assert post_export.read_bytes() == pre_export.read_bytes()


def test_m5b_overwrite_question_defaults_to_no(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M5b: the replace-existing-data-file question has No as the default button."""
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _csv(tmp_path, 500)
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    project_path = tmp_path / "m5b.npa"
    data_path = Path(str(project_path) + ".data")
    data_path.write_text("leftover", encoding="utf-8")

    seen: list[Any] = []

    def spy_question(parent: Any, title: str, text: str, buttons: Any = None, defaultButton: Any = None) -> Any:
        seen.append(defaultButton)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", spy_question)
    assert controller._save_to(project_path) is False
    assert seen == [QMessageBox.StandardButton.No]
    assert data_path.read_text(encoding="utf-8") == "leftover"
    assert not project_path.exists()


def test_m6b_free_space_margin_is_five_percent(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M6b: free = size*1.03 is refused, free = size*1.06 proceeds."""
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _csv(tmp_path, 500)
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")
    store = controller._project_store
    store.checkpoint()
    size = os.path.getsize(store.path)

    Usage = collections.namedtuple("usage", ["total", "used", "free"])
    copies: list[str] = []

    def fake_copy(target: str, *args: Any, **kwargs: Any) -> None:
        copies.append(target)
        shutil.copyfile(store.path, target)

    monkeypatch.setattr(store, "copy_to", fake_copy)
    monkeypatch.setattr(store, "checkpoint", lambda: None)

    project_path = tmp_path / "m6b.npa"
    monkeypatch.setattr(shutil, "disk_usage", lambda p: Usage(10 * size, 0, int(size * 1.03)))
    assert controller._save_to(project_path) is False
    assert "Not enough free space" in controller.statusMessage
    assert copies == []
    assert not project_path.exists()

    monkeypatch.setattr(shutil, "disk_usage", lambda p: Usage(10 * size, 0, int(size * 1.06)))
    assert controller._save_to(project_path) is True
    assert len(copies) == 1
    assert project_path.exists()


def test_o2b_fingerprint_mtime_only_and_size_only_both_warn(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """O2b: a changed mtime with equal size warns; a changed size with equal mtime warns; unchanged does not."""
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _csv(tmp_path / "src", 500)
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")
    project_path = tmp_path / "o2b.npa"
    assert controller._save_to(project_path) is True
    controller._close_project_store()

    warnings: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: warnings.append(text))

    def open_and_collect() -> list[str]:
        warnings.clear()
        fresh = StudioController()
        assert fresh.open_project_path(project_path) is True
        fresh._close_project_store()
        return list(warnings)

    assert not any("changed on disk" in w for w in open_and_collect())

    original = csv_file.stat()
    original_bytes = csv_file.read_bytes()

    # mtime only: same size, later mtime
    os.utime(csv_file, ns=(original.st_atime_ns, original.st_mtime_ns + 5_000_000_000))
    assert csv_file.stat().st_size == original.st_size
    assert any("changed on disk since it was imported" in w for w in open_and_collect())

    # size only: different size, original mtime restored
    csv_file.write_bytes(original_bytes + b"9999,1.0,2026-09-01,extra,\n")
    os.utime(csv_file, ns=(original.st_atime_ns, original.st_mtime_ns))
    assert csv_file.stat().st_mtime_ns == original.st_mtime_ns
    assert csv_file.stat().st_size != original.st_size
    assert any("changed on disk since it was imported" in w for w in open_and_collect())


def test_l2_busy_refusal_uses_shared_text(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """L2: Save refused while the store is busy uses the same text as import, profile and export."""
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _csv(tmp_path, 500)
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")

    project_path = tmp_path / "l2.npa"
    with controller._project_store.job():
        assert controller._save_to(project_path) is False
        assert controller.statusMessage == "The large-data store is busy. Try again in a moment."
    assert not project_path.exists()


def test_m1_real_self_copy_refusal_shows_box_with_refusal_text(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M1: Save As onto the open data file under another letter case: the real refusal reaches a box."""
    _assert_no_blocking_dialogs(monkeypatch)
    probe = tmp_path / "CaseProbe"
    probe.write_text("x", encoding="utf-8")
    case_insensitive = (tmp_path / "caseprobe").exists()

    csv_file = _csv(tmp_path / "src", 500)
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")
    upper = tmp_path / "B.npa"
    assert controller._save_to(upper) is True
    upper_before = upper.read_bytes()

    boxes: list[str] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda parent, title, text: boxes.append(text))
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

    if not case_insensitive:
        import analytics_studio.store.session as session_mod

        monkeypatch.setattr(session_mod.os.path, "samefile", lambda a, b: True)
        target = tmp_path / "other.npa"
        # samefile only matters when the target data file exists
        Path(str(target) + ".data").write_text("x", encoding="utf-8")
    else:
        target = tmp_path / "b.npa"

    assert controller._save_to(target) is False
    assert controller.statusMessage != "Save canceled."
    assert len(boxes) == 1
    assert "Cannot copy the data file onto itself." in boxes[0]
    assert upper.read_bytes() == upper_before
    if not case_insensitive:
        assert not target.exists()


def test_m3_raw_candidate_helpers_refuse_store_source_without_parsing(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M3: the shared raw-candidate helpers refuse a store source and never parse its file."""
    _assert_no_blocking_dialogs(monkeypatch)
    import analytics_studio.controller as ctrl_mod

    csv_file = _csv(tmp_path / "s", 500)
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")
    proj_path = tmp_path / "m3_raw.npa"
    assert controller._save_to(proj_path) is True
    controller._close_project_store()
    Path(str(proj_path) + ".data").unlink()

    fresh = StudioController()
    assert fresh.open_project_path(proj_path) is True
    source = fresh._project["data_sources"][0]
    before = dict(source)

    parsed: list[Any] = []
    monkeypatch.setattr(ctrl_mod, "parse_file", lambda *a, **k: parsed.append(a) or None)
    monkeypatch.setattr(ctrl_mod, "parse_folder", lambda *a, **k: parsed.append(a) or None)

    for helper in (fresh._raw_candidate_for_source, fresh._session_raw_candidate_for_source):
        with pytest.raises(ValueError, match="is a large-data table. Import the file again to reload it."):
            helper(source)
    assert parsed == []
    assert source == before
    assert "store" in source


def test_m18_rebind_failure_state_after_json_written(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M18: rebind fails after the JSON was written: one error box, no 'Saved' status, app keeps the old path."""
    _assert_no_blocking_dialogs(monkeypatch)
    csv_file = _csv(tmp_path / "s", 500)
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    _import_large_table(controller, csv_file, "csv")
    path_before = controller._project_path
    store_before = controller._project_store
    store_file_before = store_before.path

    boxes: list[tuple[str, str]] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda parent, title, text: boxes.append((title, text)))

    def fail_rebind(*args: Any, **kwargs: Any) -> None:
        raise StoreError("rebind failed simulated")

    monkeypatch.setattr(store_before, "rebind", fail_rebind)

    target = tmp_path / "m18_state.npa"
    assert controller._save_to(target) is False
    assert len(boxes) == 1 and "rebind failed simulated" in boxes[0][1]
    assert not controller.statusMessage.startswith("Saved")
    assert controller._project_path == path_before
    assert controller._project_store is store_before
    assert store_before.path == store_file_before
    # the JSON was already written, so a retry can succeed
    assert target.exists()
