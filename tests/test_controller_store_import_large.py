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

    rows_read_count = 0
    orig_fget = StoreCandidate.rows.fget

    def counting_rows(self: StoreCandidate) -> Any:
        nonlocal rows_read_count
        rows_read_count += 1
        return orig_fget(self)

    with patch.object(StoreCandidate, "rows", new=property(counting_rows)):
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

            # Instrument candidate.rows: wrap StoreCandidate.rows and verify 0 reads during flow
            assert rows_read_count == 0

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
    small_csv = _generate_csv(tmp_path / "small_m.csv", rows=100)
    csv_file = _generate_csv(tmp_path / "big_conf_m.csv", rows=2000)
    controller = StudioController()
    try:
        from analytics_studio.file_import import parse_file
        controller._commit_import(small_csv, parse_file(small_csv))
        created = controller.create_measure("M1", "SUM(small_m[score])")
        assert created is True
        assert bool(controller._project.get("model", {}).get("measures"))

        # No -> False, no store opened, no job
        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as mock_q:
                success = controller._import_file_path(csv_file)
        assert success is False
        assert mock_q.called
        assert controller._large_import_job is None
        assert controller._project_store is None
        assert controller._store_tables_loaded() is False

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
    small_csv = _generate_csv(tmp_path / "small_v.csv", rows=100)
    csv_file = _generate_csv(tmp_path / "big_conf_v.csv", rows=2000)
    controller = StudioController()
    try:
        from analytics_studio.file_import import parse_file
        controller._commit_import(small_csv, parse_file(small_csv))
        visual_id = controller.add_visual("column", "Test Visual", 0, 0, 300, 200)
        assert bool(visual_id)
        assert bool(controller._project["report"]["pages"][0].get("visuals"))

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
    small_csv1 = _generate_csv(tmp_path / "small_r1.csv", rows=100)
    small_csv2 = _generate_csv(tmp_path / "small_r2.csv", rows=100)
    csv_file = _generate_csv(tmp_path / "big_conf_r.csv", rows=2000)
    controller = StudioController()
    try:
        from analytics_studio.file_import import parse_file
        controller._commit_import(small_csv1, parse_file(small_csv1))
        controller._commit_import(small_csv2, parse_file(small_csv2))
        t1_id = controller._project["model"]["tables"][0]["id"]
        t2_id = controller._project["model"]["tables"][1]["id"]
        rel = {
            "id": "rel1",
            "from": "small_r1[id]",
            "to": "small_r2[id]",
            "from_table_id": t1_id,
            "from_column": "id",
            "to_table_id": t2_id,
            "to_column": "id",
            "cardinality": "one_to_one",
            "cross_filtering": "both",
            "active": True,
        }
        ok_rel = controller._save_validated_relationships([rel])
        assert ok_rel is True
        assert bool(controller._project["model"].get("relationships"))

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
    small_csv = _generate_csv(tmp_path / "small_q.csv", rows=100)
    csv_file = _generate_csv(tmp_path / "big_conf_q.csv", rows=2000)
    controller = StudioController()
    try:
        from analytics_studio.file_import import parse_file
        controller._commit_import(small_csv, parse_file(small_csv))
        cand = parse_file(small_csv)
        src_id = controller._project["data_sources"][0]["id"]
        q_created = controller._create_saved_query(
            "MyRefQuery",
            [src_id],
            cand,
            {"operation": "reference", "source_ids": [src_id]},
            {"id": "whole_number", "score": "decimal_number"},
        )
        assert q_created is True
        assert any(s.get("kind") == "query" for s in controller._project.get("data_sources", []))

        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as mock_q:
                success = controller._import_file_path(csv_file)
        assert success is False
        assert mock_q.called
        assert controller._large_import_job is None
        assert controller._project_store is None
    finally:
        controller._close_project_store()


def test_confirmation_dialog_transform_steps_power_query(qapp: QApplication, tmp_path: Path) -> None:
    small_csv = _generate_csv(tmp_path / "small_steps.csv", rows=100)
    csv_file = _generate_csv(tmp_path / "big_conf_steps.csv", rows=2000)
    controller = StudioController()
    try:
        from analytics_studio.file_import import parse_file
        controller._commit_import(small_csv, parse_file(small_csv))

        # With empty transform_steps, confirmation is NOT asked for an ordinary table
        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
            with patch.object(QMessageBox, "question") as mock_q_empty:
                success1 = controller._import_file_path(csv_file)
        assert success1 is True
        _wait_for_large_job(controller)
        assert not mock_q_empty.called

        # Now test with non-empty transform_steps
        controller._close_project_store()
        controller2 = StudioController()
        controller2._commit_import(small_csv, parse_file(small_csv))
        controller2._project["data_sources"][0]["transform_steps"] = [
            {"op": "convert_type", "column": "id", "type": "text"}
        ]

        with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No) as mock_q_steps:
                success2 = controller2._import_file_path(csv_file)
        assert success2 is False
        assert mock_q_steps.called
        assert controller2._large_import_job is None
        assert controller2._project_store is None
    finally:
        controller._close_project_store()
        if "controller2" in locals():
            controller2._close_project_store()


def test_confirmation_dialog_calculated_column(qapp: QApplication, tmp_path: Path) -> None:
    small_csv = _generate_csv(tmp_path / "small_cc.csv", rows=100)
    csv_file = _generate_csv(tmp_path / "big_conf_cc.csv", rows=2000)
    controller = StudioController()
    try:
        from analytics_studio.file_import import parse_file
        controller._commit_import(small_csv, parse_file(small_csv))
        res = controller.save_calculated_column("calc_score", "[score] * 2")
        assert res == ""
        assert bool(controller._project["model"]["tables"][0].get("calculated_columns"))

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
    """shutdown_store() while an import job is running cancels it, WAITS for it, and only then says True.

    The job is held on `release_event` after it saw the cancel. shutdown_store runs in a thread; while the job is held
    the thread must still be alive (a shutdown that does not wait would have returned), and once the job is released it
    must have ended BEFORE shutdown returned. No assertion depends on a clock: the 10 s waits are hang guards only,
    the 0.5 s join is a negative check (a shutdown that waits can never finish while the job is held).
    """
    csv_file = _generate_csv(tmp_path / "slow.csv", rows=2000)
    controller = StudioController()
    monkeypatch.setattr(controller, "_effective_app_data_dir", lambda: str(tmp_path / "appdata"))

    started_event = threading.Event()
    woken_by_cancel = threading.Event()  # set inside request_cancel: shutdown really asked the job to cancel
    release_event = threading.Event()  # the test lets the held job go on
    job_ended_event = threading.Event()
    job_saw_cancel: list[bool] = []

    from analytics_studio.store import large_import as li_mod
    from analytics_studio.store.session import ProjectStore
    orig_run = li_mod.run_large_import
    orig_request_cancel = ProjectStore.request_cancel

    def slow_run(*args, **kwargs):
        started_event.set()
        # The job waits for the cancel (hang guard 10 s), then is held until the test releases it (hang guard 10 s).
        job_saw_cancel.append(woken_by_cancel.wait(10.0))
        release_event.wait(10.0)
        try:
            return orig_run(*args, **kwargs)
        finally:
            job_ended_event.set()

    def cancel_then_note(self: Any) -> None:
        orig_request_cancel(self)
        woken_by_cancel.set()

    monkeypatch.setattr(li_mod, "run_large_import", slow_run)
    monkeypatch.setattr(ProjectStore, "request_cancel", cancel_then_note)

    with patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog):
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            controller._import_file_path(csv_file)

    # Wait until job has started running in background (bounded number of event-loop turns).
    for _ in range(1000):
        if started_event.is_set():
            break
        qapp.processEvents()
        time.sleep(0.01)
    assert started_event.wait(10.0), "the import job never started"
    assert controller._large_import_job is not None

    results: list[tuple[bool, bool]] = []

    def run_shutdown() -> None:
        closed_now = controller.shutdown_store(timeout=10.0)
        results.append((closed_now, job_ended_event.is_set()))

    thread = threading.Thread(target=run_shutdown, daemon=True)
    thread.start()
    try:
        assert woken_by_cancel.wait(10.0), "shutdown_store never asked the store to cancel the job"
        thread.join(0.5)
        assert thread.is_alive(), "shutdown_store returned while the import job was still held (it did not wait)"
        assert not job_ended_event.is_set()
    finally:
        release_event.set()  # whatever happened above, let the job go on
    thread.join(10.0)
    assert not thread.is_alive(), "shutdown_store did not return after the job was released"
    assert job_saw_cancel == [True], "the job was not woken by the cancel"
    assert results == [(True, True)], f"shutdown_store must say True and only after the job ended: {results}"

    # Wait for job to finish done handler
    _wait_for_large_job(controller)
    assert controller._project_store is None
    assert controller.sourceLoaded is False


def test_cancel_progress_dialog_cancels_job_and_cleans_up(qapp: QApplication, tmp_path: Path) -> None:
    """Kills S5, S6, S7, S8, H5-H10: drive real progress dialog, cancel, check modal, label, binder, done cleanup."""
    import shiboken6
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton
    from analytics_studio.store import large_import as li_mod

    csv_file = _generate_csv(tmp_path / "cancel_diag.csv", rows=2000)
    controller = StudioController()

    started_event = threading.Event()
    gate_event = threading.Event()
    received_cancel_events: list[threading.Event] = []
    orig_run = li_mod.run_large_import

    def gated_run(*args: Any, **kwargs: Any) -> Any:
        prog = kwargs.get("progress")
        cancel_ev = kwargs.get("cancel_event")
        assert cancel_ev is not None, "cancel_event was None (kills S5)!"
        received_cancel_events.append(cancel_ev)
        assert prog is not None, "progress callback was None (kills S6)!"
        prog("Reading rows from disk...")
        started_event.set()
        gate_event.wait(timeout=10.0)
        return orig_run(*args, **kwargs)

    with patch("analytics_studio.store.large_import.run_large_import", side_effect=gated_run):
        req = {"path": str(csv_file), "kind": "csv", "options": {}}
        ok = controller._import_large(csv_file, req)
        assert ok is True

        dialog = controller._large_import_dialog
        assert dialog is not None
        # S7: dialog modality is ApplicationModal
        assert dialog.windowModality() == Qt.WindowModality.ApplicationModal
        # H9/H10: dialog flags
        assert dialog.autoClose() is False
        assert dialog.autoReset() is False
        assert dialog.minimumDuration() == 0

        # Wait until importer has started and sent progress
        for _ in range(1000):
            if started_event.is_set():
                break
            qapp.processEvents()
            time.sleep(0.01)
        assert started_event.wait(10.0), "the import job never started"

        # Let progress events dispatch
        for _ in range(5):
            qapp.processEvents()
            time.sleep(0.01)

        # S6: labelText updated by progress adapter
        assert dialog.labelText() == "Reading rows from disk..."

        # S8 / S5: binder connects Cancel button -> clicks cancel
        cancel_buttons = [b for b in dialog.findChildren(QPushButton) if b.text() == "Cancel"]
        assert len(cancel_buttons) >= 1
        cancel_buttons[0].click()
        qapp.processEvents()

        # cancel_event was set by click
        assert len(received_cancel_events) == 1
        assert received_cancel_events[0].is_set()

        # release worker
        gate_event.set()

        _wait_for_large_job(controller)

        # Process deferred deletions
        for _ in range(5):
            qapp.processEvents()
            time.sleep(0.01)

        assert controller.statusMessage == "Import canceled."
        assert len(controller._project["model"]["tables"]) == 0

        # H5-H8: all _large_import_* references cleared
        assert controller._large_import_binder is None
        assert controller._large_import_dialog is None
        assert controller._large_import_path is None
        assert controller._large_import_project_store is None
        assert controller._large_import_job is None

        # H6: dialog deleteLater ran
        assert not shiboken6.isValid(dialog)


def test_busy_refusals_pre_and_post(qapp: QApplication, tmp_path: Path) -> None:
    """Kills G3/G4: (a) store busy before _ensure_project_store; (b) busy after _ensure_project_store."""
    from unittest.mock import MagicMock
    csv_file = _generate_csv(tmp_path / "busy_test.csv", rows=2000)
    controller = StudioController()
    try:
        req = {"path": str(csv_file), "kind": "csv", "options": {}}

        # (a) store busy before _ensure_project_store (G3)
        ps = controller._ensure_project_store()
        with ps.job():
            with patch.object(controller, "_ensure_project_store", side_effect=AssertionError("_ensure_project_store called when store was already busy!")):
                ok = controller._import_large(csv_file, req)
            assert ok is False
            assert "The large-data store is busy. Try again in a moment." in controller.statusMessage
            assert controller._large_import_job is None

        # (b) second busy check after _ensure_project_store (G4)
        mock_ps = MagicMock()
        mock_ps.closed = False
        mock_ps.busy = True
        with patch.object(controller, "_ensure_project_store", return_value=mock_ps):
            ok2 = controller._import_large(csv_file, req)
            assert ok2 is False
            assert "The large-data store is busy. Try again in a moment." in controller.statusMessage
            assert controller._large_import_job is None
    finally:
        controller._close_project_store()


def test_ensure_project_store_raising_store_error(qapp: QApplication, tmp_path: Path) -> None:
    """Kills S4: _ensure_project_store raising StoreError shows critical message box and returns False."""
    from analytics_studio.store.base import StoreError
    csv_file = _generate_csv(tmp_path / "store_err.csv", rows=2000)
    controller = StudioController()
    req = {"path": str(csv_file), "kind": "csv", "options": {}}

    with patch.object(controller, "_ensure_project_store", side_effect=StoreError("Store disk is corrupt")):
        with patch.object(QMessageBox, "critical") as mock_crit:
            ok = controller._import_large(csv_file, req)
            assert ok is False
            assert mock_crit.called
            title, msg = mock_crit.call_args[0][1:3]
            assert title == "Could not open the large-data store"
            assert "Store disk is corrupt" in msg
            assert controller._large_import_job is None


def test_job_start_raising_store_error(qapp: QApplication, tmp_path: Path) -> None:
    """Kills T5/T6: StoreJob.start raising StoreError clears refs, cleans attempt store, sets status."""
    from analytics_studio.store.base import StoreError
    from analytics_studio.store.jobs import StoreJob

    csv_file = _generate_csv(tmp_path / "job_err.csv", rows=2000)
    controller = StudioController()
    req = {"path": str(csv_file), "kind": "csv", "options": {}}

    with patch.object(StoreJob, "start", side_effect=StoreError("ThreadPool rejected")):
        ok = controller._import_large(csv_file, req)
        assert ok is False
        assert "ThreadPool rejected" in controller.statusMessage
        assert controller._large_import_job is None
        assert controller._large_import_binder is None
        assert controller._large_import_dialog is None
        assert controller._large_import_path is None
        assert controller._large_import_project_store is None
        # Attempt-created store was closed
        assert controller._project_store is None


def test_options_reach_importer(qapp: QApplication, tmp_path: Path) -> None:
    """Kills S3: semicolon delimiter in options reaches importer, parses columns correctly."""
    p_csv = tmp_path / "semi.csv"
    p_csv.write_text("id;product;price\n1;Widget;19.99\n2;Gadget;29.99\n", encoding="utf-8")
    controller = StudioController()
    try:
        req = {
            "path": str(p_csv),
            "kind": "csv",
            "options": {"delimiter": ";", "has_header": True},
        }
        ok = controller._import_large(p_csv, req)
        assert ok is True
        _wait_for_large_job(controller)

        assert controller.sourceLoaded is True
        assert controller._headers == ["id", "product", "price"]
        assert controller.rowCount == 2
    finally:
        controller._close_project_store()


def test_confirmation_question_default_button_no(qapp: QApplication, tmp_path: Path) -> None:
    """Kills C8: QMessageBox.question called with defaultButton=QMessageBox.StandardButton.No."""
    small_csv = _generate_csv(tmp_path / "small_c8.csv", rows=100)
    csv_file = _generate_csv(tmp_path / "big_c8.csv", rows=2000)
    controller = StudioController()
    try:
        from analytics_studio.file_import import parse_file
        controller._commit_import(small_csv, parse_file(small_csv))
        controller.create_measure("M_c8", "SUM(small_c8[score])")

        call_args_list = []

        def fake_q(*args: Any, **kwargs: Any) -> QMessageBox.StandardButton:
            call_args_list.append((args, kwargs))
            return QMessageBox.StandardButton.No

        with patch.object(QMessageBox, "question", side_effect=fake_q):
            req = {"path": str(csv_file), "kind": "csv", "options": {}}
            controller._import_large(csv_file, req)

        assert len(call_args_list) == 1
        args, _ = call_args_list[0]
        # args: (parent, title, text, buttons, defaultButton)
        assert args[1] == "Add a large table"
        assert args[3] == (QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        assert args[4] == QMessageBox.StandardButton.No
    finally:
        controller._close_project_store()


def test_real_file_import_preview_dialog_e2e_csv_and_parquet(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Pins large_mode_enabled=True and large_request wiring by driving real FileImportPreviewDialog."""
    from PySide6.QtCore import QTimer
    monkeypatch.setattr(file_import, "MAX_DATA_ROWS", 500)

    def drive_dialog(timeout: float = 20.0) -> None:
        t0 = time.monotonic()
        def tick() -> None:
            w = QApplication.activeModalWidget()
            if w is not None and hasattr(w, "import_button") and w.import_button.isEnabled():
                w.import_button.click()
                return
            if time.monotonic() - t0 > timeout:
                if w is not None:
                    w.reject()
                return
            QTimer.singleShot(20, tick)
        QTimer.singleShot(20, tick)

    # 1. Real CSV
    p_csv = _generate_csv(tmp_path / "real_big.csv", rows=2000)
    controller1 = StudioController()
    try:
        drive_dialog()
        ok1 = controller1._import_file_path(p_csv, "csv", {})
        assert ok1 is True
        _wait_for_large_job(controller1)
        assert controller1.sourceLoaded is True
        assert controller1.rowCount == 2000
        assert isinstance(controller1._active_store_candidate, StoreCandidate)
    finally:
        controller1._close_project_store()

    # 2. Real Parquet
    if HAS_PYARROW:
        p_pq = tmp_path / "real_big.parquet"
        pq.write_table(
            pa.table({"id": list(range(2000)), "score": [i * 1.5 for i in range(2000)]}),
            p_pq,
        )
        controller2 = StudioController()
        try:
            drive_dialog()
            ok2 = controller2._import_file_path(p_pq, "parquet", {})
            assert ok2 is True
            _wait_for_large_job(controller2)
            assert controller2.sourceLoaded is True
            assert controller2.rowCount == 2000
            assert isinstance(controller2._active_store_candidate, StoreCandidate)
        finally:
            controller2._close_project_store()


@pytest.mark.xfail(
    strict=True,
    reason="reap_stale imports duckdb at controller start; make it lazy/background in a later task",
)
def test_controller_init_does_not_import_duckdb_without_env_var() -> None:
    """L1: StudioController.__init__ runs reap_stale which imports duckdb when ANALYTICS_STUDIO_NO_REAP is unset."""
    import subprocess
    import sys

    code = (
        "import os, sys\n"
        "os.environ.pop('ANALYTICS_STUDIO_NO_REAP', None)\n"
        "from analytics_studio.controller import StudioController\n"
        "c = StudioController()\n"
        "assert 'duckdb' not in sys.modules, 'duckdb was imported at controller start'\n"
    )
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


