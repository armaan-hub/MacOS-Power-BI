"""Tests for controller plumbing for large-data store tables (Stage B4b task 7)."""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path
from types import TracebackType
from typing import Any

import pyarrow as pa
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController
from analytics_studio.file_import import ImportCandidate
from analytics_studio.main import _on_about_to_quit, install_excepthook
from analytics_studio.store.candidate import StoreCandidate
from analytics_studio.store.session import ProjectStore
from analytics_studio.store.table_model import StoreTableModel


@pytest.fixture
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["controller_store_plumbing_test"])
    return app


def test_controller_rows_property_and_assignment(qapp: QApplication) -> None:
    controller = StudioController()
    assert controller.rowCount == 0
    controller._rows = [{"a": "1"}]
    assert controller.rowCount == 1
    assert controller._rows == [{"a": "1"}]

    # When a StoreCandidate is active, _rows getter returns []
    fake_candidate = StoreCandidate(
        "csv",
        ["a"],
        {},
        [],
        store_table="fake_tbl",
        row_count=42,
        session=None,
    )
    controller._active_store_candidate = fake_candidate
    assert controller._rows == []
    assert controller.rowCount == 42

    # Clear active store candidate; backing list is restored
    controller._active_store_candidate = None
    assert controller._rows == [{"a": "1"}]
    assert controller.rowCount == 1

    # Assignment works while or after store candidate was active
    controller._rows = [{"b": "2"}, {"b": "3"}]
    assert controller.rowCount == 2
    assert controller._rows == [{"b": "2"}, {"b": "3"}]

    # In-place mutation preserved: setter preserves list identity (kills M02)
    new_list = [{"c": "3"}]
    controller._rows = new_list
    assert controller._rows_backing is new_list
    controller._rows_backing.append({"c": "4"})
    assert controller.rowCount == 2
    assert controller._rows == [{"c": "3"}, {"c": "4"}]

    # _active_row_count with store candidate vs ordinary (kills M03)
    assert controller._active_row_count() == 2
    controller._active_store_candidate = fake_candidate
    assert controller._active_row_count() == 42
    controller._active_store_candidate = None
    assert controller._active_row_count() == 2


def test_store_candidate_install_and_grid_switch(qapp: QApplication, tmp_path: Path) -> None:
    data_file = tmp_path / "project.npa.data"
    project_store = ProjectStore.open(str(data_file))

    # Build 2,000-row table
    batch = pa.RecordBatch.from_arrays(
        [pa.array([f"val_{i}" for i in range(2000)])],
        names=["col_text"],
    )
    project_store.store.create_table_from_arrow("tbl_2000", [("col_text", "text")], [batch])

    store_candidate = StoreCandidate(
        "csv",
        ["col_text"],
        {},
        [],
        store_table="tbl_2000",
        row_count=2000,
        session=project_store,
    )

    controller = StudioController()

    # Install the store candidate
    controller._install_source(None, "src_store_1", store_candidate)

    assert controller.rowCount == 2000
    assert controller.headers == ["col_text"]
    assert controller.columnCount == 1

    # Grid model is StoreTableModel with 500 rows on first page
    model = controller.dataModel
    assert isinstance(model, StoreTableModel)
    assert model.rowCount() == 500
    assert model.columnCount() == 1
    index_first = model.index(0, 0)
    assert model.data(index_first) == "val_0"
    # table_key not None is stored on store model (kills M10)
    assert model._table_key == "src_store_1"

    # Install an ordinary candidate afterwards
    ordinary_rows = [{"col_a": "10", "col_b": "20"}]
    ordinary_candidate = ImportCandidate("csv", ["col_a", "col_b"], ordinary_rows, {}, [])
    controller._install_source(None, "src_ord_1", ordinary_candidate)

    assert controller.rowCount == 1
    assert controller.headers == ["col_a", "col_b"]
    assert controller.columnCount == 2
    assert controller.dataModel is controller._table_model
    assert controller.dataModel.rowCount() == 1
    assert controller._active_store_candidate is None
    # Ordinary install after store install clears store model (kills M07)
    assert controller._store_table_model is not None
    assert controller._store_table_model.rowCount() == 0

    # Re-install store candidate to test _clear_source from store-active state (kills M08, M09)
    controller._install_source(None, "src_store_1", store_candidate)
    assert controller._active_store_candidate is not None
    assert controller.dataModel is controller._store_table_model
    assert controller.dataModel.rowCount() == 500

    # _clear_source clears everything from store-active state
    controller._clear_source()
    assert controller.rowCount == 0
    assert controller.columnCount == 0
    assert controller.dataModel is controller._table_model
    assert controller._active_store_candidate is None
    assert controller._store_table_model.rowCount() == 0

    project_store.close()


def test_table_catalog_entry_for_store_table(qapp: QApplication, tmp_path: Path) -> None:
    data_file = tmp_path / "catalog_test.npa.data"
    project_store = ProjectStore.open(str(data_file))

    batch = pa.RecordBatch.from_arrays(
        [pa.array([f"v_{i}" for i in range(2000)])],
        names=["field1"],
    )
    project_store.store.create_table_from_arrow("t_cat", [("field1", "text")], [batch])

    store_candidate = StoreCandidate(
        "csv",
        ["field1"],
        {},
        [],
        store_table="t_cat",
        row_count=2000,
        session=project_store,
    )

    controller = StudioController()
    source_id = "src_store_cat"
    controller._loaded_candidates[source_id] = store_candidate
    controller._project["data_sources"].append({
        "id": source_id,
        "name": "StoreTableCat",
        "kind": "csv",
    })
    controller._project["model"]["tables"].append({
        "id": "tbl_cat_1",
        "source_id": source_id,
        "name": "StoreTableCat",
        "column_types": {"field1": "text"},
    })

    controller._refresh_model_view()

    entry = next(
        (item for item in controller.tableCatalog if item.get("id") == "tbl_cat_1"),
        None,
    )
    assert entry is not None
    assert entry["rowCount"] == 2000
    assert entry["columnCount"] == 1
    assert entry["headers"] == ["field1"]

    project_store.close()


def test_ensure_project_store_lifecycle(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    app_data_dir = tmp_path / "app_data"
    app_data_dir.mkdir(parents=True, exist_ok=True)

    reap_calls: list[str] = []
    original_reap = ProjectStore.reap_stale

    def spy_reap(path: str, max_age_hours: float = 24.0, now: float | None = None) -> list[str]:
        reap_calls.append(path)
        return original_reap(path, max_age_hours, now)

    monkeypatch.setattr(ProjectStore, "reap_stale", spy_reap)

    # 0. Reap called with app_data_dir keyword (kills M15, M17)
    controller = StudioController(app_data_dir=str(app_data_dir))
    assert reap_calls == [str(app_data_dir)]
    reap_calls.clear()

    # With ANALYTICS_STUDIO_NO_REAP set and no dir, reap_stale is NOT called
    monkeypatch.setenv("ANALYTICS_STUDIO_NO_REAP", "1")
    controller_no_reap = StudioController()
    assert controller_no_reap is not None
    assert reap_calls == []

    # 1. Unsaved project store
    controller._app_data_dir = str(app_data_dir)
    ps_unsaved = controller._ensure_project_store()
    assert ps_unsaved.unsaved is True
    assert str(app_data_dir) in ps_unsaved.path

    # Second call returns the exact same object
    ps_unsaved_2 = controller._ensure_project_store()
    assert ps_unsaved is ps_unsaved_2

    # A closed store is replaced by a new one (kills M11)
    ps_unsaved.close()
    assert ps_unsaved.closed is True
    ps_fresh = controller._ensure_project_store()
    assert ps_fresh is not ps_unsaved
    assert ps_fresh.closed is False
    controller._project_store = ps_fresh

    # Shutdown store closes it
    assert controller.shutdown_store() is True
    assert ps_fresh.closed is True
    assert controller._project_store is None

    # 2. Saved project store layout
    project_path = tmp_path / "saved_report.npa"
    controller._project_path = project_path
    ps_saved = controller._ensure_project_store()
    assert ps_saved.unsaved is False
    expected_data_path = ProjectStore.data_file_for(str(project_path))
    assert ps_saved.path == expected_data_path

    # Close project store helper (kills M18)
    # Monkeypatch store.shutdown to return False; close() must still be called to close the store
    monkeypatch.setattr(ps_saved, "shutdown", lambda timeout=15.0: False)
    controller._close_project_store()
    assert ps_saved.closed is True
    assert controller._project_store is None

    # 3. Reap stale failure inside __init__ only logs a warning and does not raise (assert caplog)
    def failing_reap(path: str, max_age_hours: float = 24.0, now: float | None = None) -> list[str]:
        raise PermissionError("Simulated reap failure")

    monkeypatch.setattr(ProjectStore, "reap_stale", failing_reap)
    monkeypatch.delenv("ANALYTICS_STUDIO_NO_REAP", raising=False)
    with caplog.at_level(logging.WARNING, logger="analytics_studio.controller"):
        controller_reap_fail = StudioController(app_data_dir=str(app_data_dir))
    assert controller_reap_fail is not None
    assert "Failed to reap stale project stores: Simulated reap failure" in caplog.text


def test_main_on_about_to_quit(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    controller = StudioController()
    controller._app_data_dir = str(tmp_path / "app_data")
    ps = controller._ensure_project_store()
    assert not ps.closed

    request_cancel_called = []
    orig_cancel = ps.request_cancel
    def spy_cancel() -> None:
        request_cancel_called.append(True)
        orig_cancel()
    monkeypatch.setattr(ps, "request_cancel", spy_cancel)

    orig_shutdown = controller.shutdown_store
    def spy_shutdown(timeout: float = 15.0) -> bool:
        # Check that request_cancel has already been called before shutdown_store is invoked (kills M23)
        assert len(request_cancel_called) >= 1
        return orig_shutdown(timeout=timeout)
    monkeypatch.setattr(controller, "shutdown_store", spy_shutdown)

    wait_for_done_calls = []
    from PySide6.QtCore import QThreadPool
    global_pool = QThreadPool.globalInstance()
    orig_wait = global_pool.waitForDone
    def spy_wait(msecs: int = -1) -> bool:
        wait_for_done_calls.append(msecs)
        return orig_wait(msecs)
    monkeypatch.setattr(global_pool, "waitForDone", spy_wait)

    _on_about_to_quit(controller)

    assert len(request_cancel_called) >= 1
    assert wait_for_done_calls == [15000]
    assert ps.closed is True
    assert controller._project_store is None

    # Test busy store retry path: first shutdown fails, second succeeds after job ends
    ps_busy = controller._ensure_project_store()
    job_started = threading.Event()
    def background_job() -> None:
        with ps_busy.job():
            job_started.set()
            time.sleep(0.5)

    th = threading.Thread(target=background_job)
    th.start()
    job_started.wait()

    # shutdown_store first returns False, pointer stays
    assert controller.shutdown_store(timeout=0.05) is False
    assert controller._project_store is ps_busy
    assert ps_busy.closed is False

    th.join()
    # Second call returns True, pointer cleared
    assert controller.shutdown_store(timeout=5.0) is True
    assert controller._project_store is None
    assert ps_busy.closed is True

    # Test retry path in _on_about_to_quit where shutdown continues to fail and logs error
    controller._ensure_project_store()
    monkeypatch.setattr(controller, "shutdown_store", lambda timeout=15.0: False)
    with caplog.at_level(logging.ERROR, logger="analytics_studio.main"):
        _on_about_to_quit(controller)
    assert "Failed to shutdown ProjectStore on aboutToQuit after retry." in caplog.text


def test_excepthook_wrapper(caplog: pytest.LogCaptureFixture) -> None:
    old_hook = sys.excepthook
    old_thread_hook = getattr(threading, "excepthook", None)
    chained_calls: list[tuple[type[BaseException], BaseException, TracebackType | None]] = []
    thread_chained_calls: list[Any] = []

    def mock_hook(
        exc_type: type[BaseException],
        exc_val: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        chained_calls.append((exc_type, exc_val, exc_tb))

    def mock_thread_hook(args: Any) -> None:
        thread_chained_calls.append(args)

    sys.excepthook = mock_hook
    if hasattr(threading, "excepthook"):
        threading.excepthook = mock_thread_hook
    try:
        install_excepthook()
        installed_sys_hook = sys.excepthook
        installed_thread_hook = getattr(threading, "excepthook", None)

        # Calling twice must not stack wrappers
        install_excepthook()
        assert sys.excepthook is installed_sys_hook
        if hasattr(threading, "excepthook"):
            assert threading.excepthook is installed_thread_hook

        err = ValueError("Test exception hook")
        with caplog.at_level(logging.ERROR, logger="analytics_studio.main"):
            sys.excepthook(ValueError, err, None)

        assert len(chained_calls) == 1
        assert chained_calls[0][1] is err
        assert "Uncaught exception: Test exception hook" in caplog.text

        # Test threading.excepthook logging and chaining
        if hasattr(threading, "excepthook"):
            class FakeArgs:
                thread = threading.current_thread()
                exc_type = TypeError
                exc_value = TypeError("Test thread hook")
                exc_traceback = None

            caplog.clear()
            with caplog.at_level(logging.ERROR, logger="analytics_studio.main"):
                threading.excepthook(FakeArgs())
            assert len(thread_chained_calls) == 1
            assert "Uncaught exception in thread" in caplog.text
            assert "Test thread hook" in caplog.text
    finally:
        sys.excepthook = old_hook
        if old_thread_hook is not None and hasattr(threading, "excepthook"):
            threading.excepthook = old_thread_hook


def test_store_table_model_replace_store(tmp_path: Path) -> None:
    data_file = tmp_path / "test_replace_store.npa.data"
    project_store = ProjectStore.open(str(data_file))

    batch = pa.RecordBatch.from_arrays(
        [pa.array(["row1", "row2"]), pa.array(["extra1", "extra2"])],
        names=["heading_a", "heading_b"],
    )
    project_store.store.create_table_from_arrow(
        "t_sm", [("heading_a", "text"), ("heading_b", "text")], [batch]
    )

    model = StoreTableModel(project_store.store)
    # Passed headers (subset/reordered) are used (kills M28), returns bool (kills M29), table_key stored
    success = model.replace_store(
        table_name="t_sm",
        headers=["heading_b"],
        column_types={"heading_b": "text"},
        row_count=2,
        table_key="key_sm",
    )
    assert success is True
    assert model.rowCount() == 2
    assert model.columnCount() == 1
    assert model.headerData(0, Qt.Orientation.Horizontal) == "heading_b"
    assert model.data(model.index(0, 0)) == "extra1"
    assert model._table_key == "key_sm"
    assert model._headers == ["heading_b"]

    # Test replace_store propagates bool False from replace_data (kills M29)
    fail_res = model.replace_store("t_sm", headers=["missing_column"])
    assert fail_res is False

    model.clear()
    assert model.rowCount() == 0
    project_store.close()


def test_install_source_rebinds_to_new_project_store(qapp: QApplication, tmp_path: Path) -> None:
    """Probe A repro: StoreTableModel replaces model on new ProjectStore session."""
    ps1 = ProjectStore.open(str(tmp_path / "session_1.npa.data"))
    b1 = pa.RecordBatch.from_arrays([pa.array([f"A_{i}" for i in range(600)])], names=["c"])
    ps1.store.create_table_from_arrow("t1", [("c", "text")], [b1])
    c1 = StoreCandidate("csv", ["c"], {}, [], store_table="t1", row_count=600, session=ps1)

    controller = StudioController()
    controller._install_source(None, "src_ps1", c1)
    m1 = controller.dataModel
    assert isinstance(m1, StoreTableModel)
    assert m1.parent() is controller
    assert m1._store is ps1.store
    assert m1.data(m1.index(0, 0)) == "A_0"
    assert controller.rowCount == 600

    # Install candidate from second ProjectStore
    ps2 = ProjectStore.open(str(tmp_path / "session_2.npa.data"))
    b2 = pa.RecordBatch.from_arrays([pa.array([f"B_{i}" for i in range(700)])], names=["c"])
    ps2.store.create_table_from_arrow("t2", [("c", "text")], [b2])
    c2 = StoreCandidate("csv", ["c"], {}, [], store_table="t2", row_count=700, session=ps2)

    controller._install_source(None, "src_ps2", c2)
    m2 = controller.dataModel
    assert isinstance(m2, StoreTableModel)
    assert m2 is not m1
    assert m2._store is ps2.store
    assert m2.data(m2.index(0, 0)) == "B_0"
    assert controller.rowCount == 700

    # Closing the first store does not break the grid
    ps1.close()
    assert ps1.closed is True
    assert m2.data(m2.index(0, 0)) == "B_0"
    assert m2._last_error == ""

    ps2.close()


def test_install_source_handles_replace_store_failure(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Probe B repro: when replace_store returns False (e.g. busy store StoreError),
    candidate is not set active, previous source is preserved, and status message is surfaced."""
    ps = ProjectStore.open(str(tmp_path / "busy_test.npa.data"))
    b = pa.RecordBatch.from_arrays([pa.array([f"D_{i}" for i in range(900)])], names=["c"])
    ps.store.create_table_from_arrow("t_busy", [("c", "text")], [b])
    cand = StoreCandidate("csv", ["c"], {}, [], store_table="t_busy", row_count=900, session=ps)

    controller = StudioController()
    # First install an ordinary candidate
    ord_cand = ImportCandidate("csv", ["col_orig"], [{"col_orig": "orig_val"}], {}, [])
    controller._install_source(None, "src_orig", ord_cand)
    assert controller.rowCount == 1
    assert controller._rows == [{"col_orig": "orig_val"}]

    # Simulate replace_store failing (returns False)
    def failing_replace_store(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(StoreTableModel, "replace_store", failing_replace_store)

    controller._install_source(None, "src_busy", cand)

    # Active candidate must NOT be set
    assert controller._active_store_candidate is None
    # Previous source state remains in place
    assert controller.statusMessage == "Could not load table from store: t_busy"

    ps.close()


def test_store_candidate_status_text_and_export(qapp: QApplication, tmp_path: Path) -> None:
    """Test status text and export for store candidate uses store row count (kills M19)."""
    ps = ProjectStore.open(str(tmp_path / "status_export.npa.data"))
    b = pa.RecordBatch.from_arrays([pa.array([f"E_{i}" for i in range(800)])], names=["c"])
    ps.store.create_table_from_arrow("t_exp", [("c", "text")], [b])
    cand = StoreCandidate("csv", ["c"], {}, [], store_table="t_exp", row_count=800, session=ps)

    controller = StudioController()
    controller._install_source(None, "src_exp", cand)
    assert controller.rowCount == 800

    out_csv = tmp_path / "exported.csv"
    res = controller.export_data_path(out_csv)
    assert res is True
    assert controller.statusMessage == f"Exported 800 rows to {out_csv.name}"

    ps.close()
