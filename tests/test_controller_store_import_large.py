"""Tests for controller large-file import flow (_import_large, _commit_store_import) (Stage B4b task 11)."""

from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import threading
import time
from typing import Any
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from analytics_studio import file_import
from analytics_studio.controller import StudioController
from analytics_studio.project import validate_project
from analytics_studio.store.candidate import StoreCandidate
from analytics_studio.store.table_model import StoreTableModel
from analytics_studio.transformations import infer_column_types

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    HAS_PYARROW = True
except ImportError:
    HAS_PYARROW = False


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(["Analytics Studio tests"])


@pytest.fixture
def small_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_import, "MAX_DATA_ROWS", 500)


def _wait_for_large_job(controller: StudioController, timeout: float = 30.0) -> None:
    """Helper that processes Qt events until controller._large_import_job is None."""
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


def _generate_csv(path: Path, rows: int = 2000, delimiter: str = ",") -> Path:
    lines = [f"id{delimiter}name{delimiter}score{delimiter}is_active{delimiter}created_at"]
    for i in range(rows):
        lines.append(f"{i}{delimiter}name_{i}{delimiter}{i * 1.5}{delimiter}{'true' if i % 2 == 0 else 'false'}{delimiter}2026-01-01 12:00:00")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _generate_mixed_csv(path: Path, rows: int = 2000) -> Path:
    lines = ["int_col,float_col,date_col,text_col,blank_col"]
    for i in range(rows):
        b = "" if i % 2 == 0 else "something"
        lines.append(f"{i},{i * 2.5},2026-05-10,sample text {i},{b}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class _FakeLargeDialog:
    """Headless fake for FileImportPreviewDialog in large mode."""

    def __init__(self, path: Path, **kwargs: Any) -> None:
        self.path = Path(path)
        self.kwargs = kwargs
        self.candidate = None
        self.large_request = {
            "path": str(self.path.resolve()),
            "kind": "parquet" if self.path.suffix.lower() == ".parquet" else "csv",
            "options": {"delimiter": ",", "has_header": True} if self.path.suffix.lower() != ".parquet" else {},
            "limit_kind": "rows",
        }
        self.selected_action = "load"

    def exec(self) -> int:
        return 1  # QDialog.DialogCode.Accepted.value


def test_import_large_csv_end_to_end(qapp: QApplication, tmp_path: Path) -> None:
    csv_file = _generate_csv(tmp_path / "big.csv", rows=2000)
    controller = StudioController()
    try:
        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                success = controller._import_file_path(csv_file)
        assert success is True

        _wait_for_large_job(controller)

        assert controller.sourceLoaded is True
        assert controller.rowCount == 2000
        candidate = controller._active_store_candidate
        assert isinstance(candidate, StoreCandidate)
        assert candidate.row_count == 2000
        assert controller.dataModel is not None
        assert isinstance(controller.dataModel, StoreTableModel)
        assert controller.dataModel.rowCount() == 500

        # Check first cells / headers
        headers = controller.headers
        assert headers == ["id", "name", "score", "is_active", "created_at"]
        assert controller.dataModel.data(controller.dataModel.index(0, 0)) == "0"
        assert controller.dataModel.data(controller.dataModel.index(0, 1)) == "name_0"

        # Check column types
        types_by_col = {item["column"]: item["type"] for item in controller.columnTypes}
        assert types_by_col["score"] == "decimal_number"
        assert types_by_col["is_active"] == "boolean"
        assert types_by_col["created_at"] == "datetime"

        # Check store busy is False
        ps = controller._ensure_project_store()
        assert ps.busy is False

        # Progress dialog is closed / cleaned up
        assert controller._large_import_dialog is None

        # Status text
        assert f"Loaded 2,000 rows into the large-data store: {csv_file.name}." in controller.statusMessage

        # Instrument candidate.rows: no .rows access during import
        with pytest.raises(Exception):
            _ = candidate.rows

        # Project document validation
        doc = controller._document_for_save(tmp_path / "proj.npa")
        validated = validate_project(doc)
        assert validated is not None
        source_rec = doc["data_sources"][0]
        assert "store" in source_rec
        store_meta = source_rec["store"]
        assert store_meta["row_count"] == 2000
        assert store_meta["table"] == candidate.store_table
        assert store_meta["headers"] == headers
        assert hasattr(candidate, "stats")
    finally:
        controller._close_project_store()


@pytest.mark.skipif(not HAS_PYARROW, reason="pyarrow required for parquet tests")
def test_import_large_parquet_end_to_end(qapp: QApplication, tmp_path: Path) -> None:
    parquet_file = tmp_path / "big.parquet"
    rows = 2000
    table = pa.Table.from_arrays(
        [
            pa.array(list(range(rows)), type=pa.int64()),
            pa.array([f"item_{i}" for i in range(rows)], type=pa.string()),
            pa.array([i * 0.5 for i in range(rows)], type=pa.float64()),
            pa.array([i % 2 == 0 for i in range(rows)], type=pa.bool_()),
        ],
        names=["id", "item", "val", "flag"],
    )
    pq.write_table(table, parquet_file)

    controller = StudioController()
    try:
        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                success = controller._import_file_path(parquet_file)
        assert success is True

        _wait_for_large_job(controller)

        assert controller.sourceLoaded is True
        assert controller.rowCount == 2000
        candidate = controller._active_store_candidate
        assert isinstance(candidate, StoreCandidate)
        assert candidate.row_count == 2000
        from analytics_studio.store.table_model import StoreTableModel
        assert controller.dataModel is not None
        assert isinstance(controller.dataModel, StoreTableModel)
        assert controller.dataModel.rowCount() == 500
        assert controller.headers == ["id", "item", "val", "flag"]

        ps = controller._ensure_project_store()
        assert ps.busy is False
        assert f"Loaded 2,000 rows into the large-data store: {parquet_file.name}." in controller.statusMessage

        doc = controller._document_for_save(tmp_path / "proj_pq.npa")
        validated = validate_project(doc)
        assert validated is not None
    finally:
        controller._close_project_store()


def test_csv_differential_types(qapp: QApplication, tmp_path: Path) -> None:
    csv_file = _generate_mixed_csv(tmp_path / "mixed.csv", rows=2000)

    # 1. Old importer types on the same file with a large MAX_DATA_ROWS
    with patch.object(file_import, "MAX_DATA_ROWS", 100_000):
        parsed_old = file_import.parse_file(csv_file)
        old_types = infer_column_types(parsed_old.headers, parsed_old.rows)

    # 2. Large importer types
    controller = StudioController()
    try:
        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                success = controller._import_file_path(csv_file)
        assert success is True

        _wait_for_large_job(controller)

        candidate = controller._active_store_candidate
        assert isinstance(candidate, StoreCandidate)
        assert candidate.model_types == old_types
    finally:
        controller._close_project_store()


def test_confirmation_dialog_measure(qapp: QApplication, tmp_path: Path) -> None:
    csv_file = _generate_csv(tmp_path / "big_conf_m.csv", rows=2000)
    controller = StudioController()
    try:
        controller._project["model"]["tables"] = [{"id": "t1", "name": "Table1"}]
        controller._project["model"]["measures"] = [
            {"name": "M1", "expression": "1", "home_table_id": "t1"}
        ]

        # No -> False, no store opened, no job
        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as mock_q:
                success = controller._import_file_path(csv_file)
        assert success is False
        assert mock_q.called
        assert controller._large_import_job is None
        assert controller._project_store is None
        assert controller.sourceLoaded is False

        # Yes -> True, proceeds
        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes) as mock_q2:
                success2 = controller._import_file_path(csv_file)
        assert success2 is True
        _wait_for_large_job(controller)
        assert mock_q2.called
        assert controller.sourceLoaded is True
    finally:
        controller._close_project_store()


def test_confirmation_dialog_visual(qapp: QApplication, tmp_path: Path) -> None:
    csv_file = _generate_csv(tmp_path / "big_conf_v.csv", rows=2000)
    controller = StudioController()
    try:
        controller._project["report"]["pages"][0]["visuals"] = [{
            "id": "v1", "type": "column", "title": "Test Visual",
            "x": 0, "y": 0, "width": 300, "height": 200, "z_index": 1,
            "field": "Amount", "wells": {}
        }]

        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as mock_q:
                success = controller._import_file_path(csv_file)
        assert success is False
        assert mock_q.called
        assert controller._large_import_job is None
        assert controller._project_store is None
    finally:
        controller._close_project_store()


def test_confirmation_dialog_relationship(qapp: QApplication, tmp_path: Path) -> None:
    csv_file = _generate_csv(tmp_path / "big_conf_r.csv", rows=2000)
    controller = StudioController()
    try:
        controller._project["model"]["tables"] = [
            {"id": "t1", "name": "Table1"},
            {"id": "t2", "name": "Table2"},
        ]
        controller._project["model"]["relationships"] = [{
            "id": "r1", "from": "Table1[c1]", "to": "Table2[c2]",
            "from_table_id": "t1", "from_column": "c1",
            "to_table_id": "t2", "to_column": "c2", "cardinality": "many_to_one",
            "cross_filtering": "single", "active": True
        }]

        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as mock_q:
                success = controller._import_file_path(csv_file)
        assert success is False
        assert mock_q.called
        assert controller._large_import_job is None
        assert controller._project_store is None
    finally:
        controller._close_project_store()


def test_confirmation_dialog_query(qapp: QApplication, tmp_path: Path) -> None:
    csv_file = _generate_csv(tmp_path / "big_conf_q.csv", rows=2000)
    controller = StudioController()
    try:
        controller._project["data_sources"] = [
            {"id": "base1", "name": "base.csv", "kind": "csv", "path": "base.csv", "parser_options": {}, "transform_steps": []},
            {"id": "q1", "name": "Query 1", "kind": "query", "query_name": "Query1", "query_definition": {"operation": "reference", "source_ids": ["base1"]}, "transform_steps": []}
        ]

        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as mock_q:
                success = controller._import_file_path(csv_file)
        assert success is False
        assert mock_q.called
        assert controller._large_import_job is None
        assert controller._project_store is None
    finally:
        controller._close_project_store()


def test_confirmation_dialog_calculated_column(qapp: QApplication, tmp_path: Path) -> None:
    csv_file = _generate_csv(tmp_path / "big_conf_cc.csv", rows=2000)
    controller = StudioController()
    try:
        controller._project["model"]["tables"] = [
            {"id": "t1", "name": "Table1", "calculated_columns": [{"name": "cc1", "expression": "1"}]}
        ]

        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as mock_q:
                success = controller._import_file_path(csv_file)
        assert success is False
        assert mock_q.called
        assert controller._large_import_job is None
        assert controller._project_store is None
    finally:
        controller._close_project_store()


def test_empty_project_no_confirmation(qapp: QApplication, tmp_path: Path) -> None:
    csv_file = _generate_csv(tmp_path / "big_empty.csv", rows=2000)
    controller = StudioController()
    try:
        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
            with patch.object(QMessageBox, "question") as mock_q:
                success = controller._import_file_path(csv_file)
        assert success is True
        _wait_for_large_job(controller)
        assert not mock_q.called
        assert controller.sourceLoaded is True
    finally:
        controller._close_project_store()


def test_second_large_import_refused(qapp: QApplication, tmp_path: Path) -> None:
    csv_file1 = _generate_csv(tmp_path / "big1.csv", rows=2000)
    csv_file2 = _generate_csv(tmp_path / "big2.csv", rows=2000)
    controller = StudioController()
    try:
        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                success1 = controller._import_file_path(csv_file1)
        assert success1 is True
        _wait_for_large_job(controller)
        assert controller.sourceLoaded is True

        # Second import should be refused immediately with Import refusal text, no job started
        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
            success2 = controller._import_file_path(csv_file2)
        assert success2 is False
        assert controller._large_data_refusal("Import") in controller.statusMessage
        assert controller._large_import_job is None
    finally:
        controller._close_project_store()


def test_second_large_import_while_job_running_refused(qapp: QApplication, tmp_path: Path) -> None:
    csv_file1 = _generate_csv(tmp_path / "big_run1.csv", rows=2000)
    csv_file2 = _generate_csv(tmp_path / "big_run2.csv", rows=2000)
    controller = StudioController()
    try:
        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                success1 = controller._import_file_path(csv_file1)
        assert success1 is True
        # Immediately try a second import while the first job is running
        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
            success2 = controller._import_file_path(csv_file2)
        assert success2 is False
        assert "A large-data import is already running." in controller.statusMessage

        _wait_for_large_job(controller)
        assert controller.sourceLoaded is True
    finally:
        controller._close_project_store()


def test_ordinary_small_file_import_unchanged(qapp: QApplication, tmp_path: Path) -> None:
    small_csv = _generate_csv(tmp_path / "small.csv", rows=100)
    controller = StudioController()
    try:
        from analytics_studio.file_import import parse_file
        parsed = parse_file(small_csv)
        created_kwargs = {}

        class FakeSmallDialog:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                created_kwargs.update(kwargs)
                self.candidate = parsed
                self.large_request = None
                self.selected_action = "load"
                self.checked_sheets = []

            def exec(self) -> int:
                return 1

        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=FakeSmallDialog):
            success = controller._import_file_path(small_csv)
        assert success is True
        assert created_kwargs.get("large_mode_enabled") is True
        assert controller.sourceLoaded is True
        assert controller.rowCount == 100
        assert controller._active_store_candidate is None
    finally:
        controller._close_project_store()


def test_large_import_failure(qapp: QApplication, tmp_path: Path) -> None:
    csv_file = _generate_csv(tmp_path / "fail.csv", rows=2000)
    controller = StudioController()
    try:
        from analytics_studio.file_import import FileImportError

        def failing_run(*args: Any, **kwargs: Any):
            raise FileImportError("Test import failure error message.")

        with patch("analytics_studio.store.large_import.run_large_import", side_effect=failing_run):
            with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
                success = controller._import_file_path(csv_file)
            assert success is True

            _wait_for_large_job(controller)

        assert "Test import failure error message." in controller.statusMessage
        assert controller.sourceLoaded is False
        assert controller._large_import_job is None
    finally:
        controller._close_project_store()


def test_large_import_cancel(qapp: QApplication, tmp_path: Path) -> None:
    csv_file = _generate_csv(tmp_path / "cancel.csv", rows=2000)
    controller = StudioController()
    try:
        from analytics_studio.file_import import ImportCancelledError

        def canceling_run(*args: Any, **kwargs: Any):
            raise ImportCancelledError("Import canceled.")

        with patch("analytics_studio.store.large_import.run_large_import", side_effect=canceling_run):
            with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
                success = controller._import_file_path(csv_file)
            assert success is True

            _wait_for_large_job(controller)

        assert controller.statusMessage == "Import canceled."
        assert controller.sourceLoaded is False
        assert controller._large_import_job is None
    finally:
        controller._close_project_store()


def test_silent_refusal_notice_reset_after_large_commit(qapp: QApplication, tmp_path: Path) -> None:
    csv_file = _generate_csv(tmp_path / "notice_reset.csv", rows=2000)
    controller = StudioController()
    try:
        # Trip the silent refusal notice
        controller._silent_refusal_notice_shown = True

        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                success = controller._import_file_path(csv_file)
        assert success is True

        _wait_for_large_job(controller)

        # After commit, the notice should have been reset to False
        assert controller._silent_refusal_notice_shown is False
    finally:
        controller._close_project_store()


def test_failure_cancel_commit_failure_snapshot_and_lifetime(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test item 1 & 2: cancel mid-import, over max_rows, bad file, commit failure.
    Snapshot equality, store lifetime (closed if created by attempt, kept if existed before),
    no orphan tables left, new import works after each.
    """
    csv_file = _generate_csv(tmp_path / "valid.csv", rows=2000)
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))

    def snapshot() -> dict[str, Any]:
        return {
            "loaded_candidates": dict(controller._loaded_candidates),
            "raw_candidates": dict(controller._raw_candidates),
            "query_candidates": dict(controller._query_candidates),
            "project": deepcopy(controller._project),
            "active_source_id": controller._active_source_id,
            "dirty": controller._dirty,
            "active_store_candidate": controller._active_store_candidate,
            "grid_rows": controller._table_model.rowCount(),
            "grid_cols": controller._table_model.columnCount(),
            "store_table_model": controller._store_table_model,
        }

    base_snap = snapshot()

    # 1. Failure over max_rows
    from analytics_studio.store import large_import as li_mod
    orig_run = li_mod.run_large_import

    def run_small_max_rows(*args, **kwargs):
        kwargs["max_rows"] = 10
        return orig_run(*args, **kwargs)

    monkeypatch.setattr(li_mod, "run_large_import", run_small_max_rows)
    with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            controller._import_file_path(csv_file)
    _wait_for_large_job(controller)

    assert "import limit" in controller.statusMessage.lower()
    assert snapshot() == base_snap
    # Project store was created by this attempt and ended with no store table loaded -> closed
    assert controller._project_store is None
    monkeypatch.undo()

    # Verify a new large import works after a failed one
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            controller._import_file_path(csv_file)
    _wait_for_large_job(controller)

    assert controller.sourceLoaded is True
    assert controller._store_tables_loaded() is True
    assert controller._project_store is not None and not controller._project_store.closed
    assert controller._project_store.busy is False

    # Reset controller for clean test of Bad File
    controller._close_project_store()
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    base_snap = snapshot()

    # 2. Bad file failure
    bad_file = tmp_path / "corrupt.csv"
    bad_file.write_bytes(b"\x00\xff\xfe random binary junk")
    with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            controller._import_file_path(bad_file)
    _wait_for_large_job(controller)

    assert snapshot() == base_snap
    assert controller._project_store is None

    # Reset for Cancel test
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    base_snap = snapshot()

    # 3. Cancel mid-import from progress callback
    def cancel_on_progress(*args, **kwargs):
        prog = kwargs.get("progress")
        cancel_ev = kwargs.get("cancel_event")
        if prog is not None and cancel_ev is not None:
            # cancel from progress
            cancel_ev.set()
        return orig_run(*args, **kwargs)

    monkeypatch.setattr(li_mod, "run_large_import", cancel_on_progress)
    with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            controller._import_file_path(csv_file)
    _wait_for_large_job(controller)

    assert controller.statusMessage == "Import canceled."
    assert snapshot() == base_snap
    assert controller._project_store is None
    monkeypatch.undo()

    # Verify a new large import works after a canceled one
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            controller._import_file_path(csv_file)
    _wait_for_large_job(controller)

    assert controller.sourceLoaded is True
    assert controller._project_store is not None and not controller._project_store.closed
    assert controller._project_store.busy is False

    # 4. Commit failure (_install_source fails): orphan table dropped, store lifetime handled
    controller._close_project_store()
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))
    base_snap = snapshot()

    with patch.object(StoreTableModel, "replace_store", return_value=False):
        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                controller._import_file_path(csv_file)
        _wait_for_large_job(controller)

    assert "Could not load table from store" in controller.statusMessage
    assert snapshot() == base_snap
    # This attempt created the store and failed -> closed
    assert controller._project_store is None

    # Now test store lifetime when store existed BEFORE the failed attempt
    ps = controller._ensure_project_store()
    assert controller._project_store is ps
    with patch.object(StoreTableModel, "replace_store", return_value=False):
        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                controller._import_file_path(csv_file)
        _wait_for_large_job(controller)

    # Store existed before attempt -> left open!
    assert controller._project_store is ps
    assert not ps.closed
    assert ps.busy is False
    # Check that orphan table was dropped
    assert ps.call(lambda s: s.table_names()) == []
    controller._close_project_store()


def test_shutdown_store_while_job_running(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test item 3: shutdown_store() while an import job is running cancels it,
    returns True/False without crash or half-state, done handler does not touch dead objects.
    """
    csv_file = _generate_csv(tmp_path / "slow.csv", rows=2000)
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))

    started_event = threading.Event()
    continue_event = threading.Event()

    from analytics_studio.store import large_import as li_mod
    orig_run = li_mod.run_large_import

    def slow_run(*args, **kwargs):
        started_event.set()
        # Wait until test tells us or until timeout
        continue_event.wait(timeout=5.0)
        return orig_run(*args, **kwargs)

    monkeypatch.setattr(li_mod, "run_large_import", slow_run)

    with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            controller._import_file_path(csv_file)

    # Wait until job has started running in background
    deadline = time.monotonic() + 10.0
    while not started_event.is_set() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert controller._large_import_job is not None

    # Call shutdown_store while running
    closed = controller.shutdown_store(timeout=5.0)
    continue_event.set()

    # Wait for job to finish done handler
    _wait_for_large_job(controller)

    assert closed is True
    assert controller._project_store is None
    assert controller.sourceLoaded is False

