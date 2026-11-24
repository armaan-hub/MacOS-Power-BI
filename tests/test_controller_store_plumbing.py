"""Tests for controller plumbing for large-data store tables (Stage B4b task 7)."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import TracebackType

import pyarrow as pa
import pytest
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

    # _clear_source clears everything
    controller._clear_source()
    assert controller.rowCount == 0
    assert controller.columnCount == 0
    assert controller.dataModel is controller._table_model
    assert controller._active_store_candidate is None

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


def test_ensure_project_store_lifecycle(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    app_data_dir = tmp_path / "app_data"
    app_data_dir.mkdir(parents=True, exist_ok=True)

    reap_calls: list[str] = []
    original_reap = ProjectStore.reap_stale

    def spy_reap(path: str, max_age_hours: float = 24.0, now: float | None = None) -> list[str]:
        reap_calls.append(path)
        return original_reap(path, max_age_hours, now)

    monkeypatch.setattr(ProjectStore, "reap_stale", spy_reap)

    controller = StudioController()
    controller._app_data_dir = str(app_data_dir)

    # 1. Unsaved project store
    ps_unsaved = controller._ensure_project_store()
    assert ps_unsaved.unsaved is True
    assert str(app_data_dir) in ps_unsaved.path

    # Second call returns the exact same object
    ps_unsaved_2 = controller._ensure_project_store()
    assert ps_unsaved is ps_unsaved_2

    # Shutdown store closes it
    assert controller.shutdown_store() is True
    assert ps_unsaved._closed is True
    assert controller._project_store is None

    # 2. Saved project store layout
    project_path = tmp_path / "saved_report.npa"
    controller._project_path = project_path
    ps_saved = controller._ensure_project_store()
    assert ps_saved.unsaved is False
    expected_data_path = ProjectStore.data_file_for(str(project_path))
    assert ps_saved.path == expected_data_path

    # Close project store helper
    controller._close_project_store()
    assert ps_saved._closed is True
    assert controller._project_store is None

    # 3. Reap stale failure inside __init__ only logs and does not raise
    def failing_reap(path: str, max_age_hours: float = 24.0, now: float | None = None) -> list[str]:
        raise PermissionError("Simulated reap failure")

    monkeypatch.setattr(ProjectStore, "reap_stale", failing_reap)
    controller_reap_fail = StudioController()
    controller_reap_fail._app_data_dir = str(app_data_dir)
    assert controller_reap_fail is not None


def test_main_on_about_to_quit(qapp: QApplication, tmp_path: Path) -> None:
    controller = StudioController()
    controller._app_data_dir = str(tmp_path / "app_data")
    ps = controller._ensure_project_store()
    assert not ps._closed

    _on_about_to_quit(controller)

    assert ps._closed is True
    assert controller._project_store is None


def test_excepthook_wrapper(caplog: pytest.LogCaptureFixture) -> None:
    old_hook = sys.excepthook
    chained_calls: list[tuple[type[BaseException], BaseException, TracebackType | None]] = []

    def mock_hook(
        exc_type: type[BaseException],
        exc_val: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        chained_calls.append((exc_type, exc_val, exc_tb))

    sys.excepthook = mock_hook
    try:
        install_excepthook()
        err = ValueError("Test exception hook")
        with caplog.at_level(logging.ERROR, logger="analytics_studio.main"):
            sys.excepthook(ValueError, err, None)

        assert len(chained_calls) == 1
        assert chained_calls[0][1] is err
        assert "Uncaught exception: Test exception hook" in caplog.text
    finally:
        sys.excepthook = old_hook


def test_store_table_model_replace_store(tmp_path: Path) -> None:
    data_file = tmp_path / "test_replace_store.npa.data"
    project_store = ProjectStore.open(str(data_file))

    batch = pa.RecordBatch.from_arrays(
        [pa.array(["row1", "row2"])],
        names=["heading"],
    )
    project_store.store.create_table_from_arrow("t_sm", [("heading", "text")], [batch])

    model = StoreTableModel(project_store.store)
    success = model.replace_store(
        table_name="t_sm",
        headers=["heading"],
        column_types={"heading": "text"},
        row_count=2,
        table_key="key_sm",
    )
    assert success is True
    assert model.rowCount() == 2
    assert model.columnCount() == 1
    assert model.data(model.index(0, 0)) == "row1"

    model.clear()
    assert model.rowCount() == 0
    project_store.close()
