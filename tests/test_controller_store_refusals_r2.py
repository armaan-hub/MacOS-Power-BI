"""Tests for controller store refusals R2 (Stage B4b task 10)."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pyarrow as pa
import pytest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QInputDialog, QMessageBox

from analytics_studio.controller import StudioController
from analytics_studio.file_import import ImportCandidate, parse_file
from analytics_studio.measures import MeasureError
from analytics_studio.query_engine import QueryError
from analytics_studio.relationships import RelationshipError
from analytics_studio.store.candidate import LargeTableError, StoreCandidate
from analytics_studio.store.session import ProjectStore


@pytest.fixture
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["controller_store_refusals_r2_test"])
    return app


def _make_store_candidate(tmp_path: Path, table_name: str = "tbl_refusals_r2", row_count: int = 1000) -> tuple[ProjectStore, StoreCandidate]:
    data_file = tmp_path / f"{table_name}.npa.data"
    project_store = ProjectStore.open(str(data_file))
    batch = pa.RecordBatch.from_arrays(
        [
            pa.array([f"cat_{i % 10}" for i in range(row_count)]),
            pa.array([f"val_{i}" for i in range(row_count)]),
        ],
        names=["cat", "val"],
    )
    project_store.store.create_table_from_arrow(table_name, [("cat", "text"), ("val", "text")], [batch])
    candidate = StoreCandidate(
        "csv",
        ["cat", "val"],
        {},
        [],
        store_table=table_name,
        row_count=row_count,
        session=project_store,
    )
    return project_store, candidate


def _setup_store_controller(tmp_path: Path) -> tuple[ProjectStore, StudioController]:
    ps, sc = _make_store_candidate(tmp_path, "tbl_store_refusal_r2", 500)
    ctrl = StudioController()
    ctrl._install_source(None, "s_store", sc)
    ctrl._project["data_sources"].append({
        "id": "s_store",
        "name": "TStore",
        "kind": "csv",
        "load_enabled": True,
        "include_in_report_refresh": True,
    })
    ctrl._project["model"]["tables"].append({
        "id": "tbl_store",
        "source_id": "s_store",
        "name": "TStore",
        "column_types": {"cat": "text", "val": "text"},
    })
    ctrl._refresh_model_view()
    return ps, ctrl


def _assert_no_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:
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


# --- Literal full refusal text tests ---

@pytest.mark.parametrize(
    ("what", "expected_literal"),
    [
        (
            "Model relationships",
            "Model relationships is not available for large-data tables yet. "
            "Tables up to 100,000 rows work everywhere; large tables support the data grid, "
            "sort, filter, column statistics and export. Other features arrive in a later release.",
        ),
        (
            "Power Query transformations",
            "Power Query transformations is not available for large-data tables yet. "
            "Tables up to 100,000 rows work everywhere; large tables support the data grid, "
            "sort, filter, column statistics and export. Other features arrive in a later release.",
        ),
        (
            "DAX calculated columns",
            "DAX calculated columns is not available for large-data tables yet. "
            "Tables up to 100,000 rows work everywhere; large tables support the data grid, "
            "sort, filter, column statistics and export. Other features arrive in a later release.",
        ),
        (
            "Append queries",
            "Append queries is not available for large-data tables yet. "
            "Tables up to 100,000 rows work everywhere; large tables support the data grid, "
            "sort, filter, column statistics and export. Other features arrive in a later release.",
        ),
        (
            "Merge queries",
            "Merge queries is not available for large-data tables yet. "
            "Tables up to 100,000 rows work everywhere; large tables support the data grid, "
            "sort, filter, column statistics and export. Other features arrive in a later release.",
        ),
        (
            "Date table",
            "Date table is not available for large-data tables yet. "
            "Tables up to 100,000 rows work everywhere; large tables support the data grid, "
            "sort, filter, column statistics and export. Other features arrive in a later release.",
        ),
        (
            "Key column",
            "Key column is not available for large-data tables yet. "
            "Tables up to 100,000 rows work everywhere; large tables support the data grid, "
            "sort, filter, column statistics and export. Other features arrive in a later release.",
        ),
        (
            "Sort by column",
            "Sort by column is not available for large-data tables yet. "
            "Tables up to 100,000 rows work everywhere; large tables support the data grid, "
            "sort, filter, column statistics and export. Other features arrive in a later release.",
        ),
        (
            "Report refresh",
            "Report refresh is not available for large-data tables yet. "
            "Tables up to 100,000 rows work everywhere; large tables support the data grid, "
            "sort, filter, column statistics and export. Other features arrive in a later release.",
        ),
        (
            "Import",
            "Import is not available for large-data tables yet. "
            "Tables up to 100,000 rows work everywhere; large tables support the data grid, "
            "sort, filter, column statistics and export. Other features arrive in a later release.",
        ),
        (
            "DAX calculated tables",
            "DAX calculated tables is not available for large-data tables yet. "
            "Tables up to 100,000 rows work everywhere; large tables support the data grid, "
            "sort, filter, column statistics and export. Other features arrive in a later release.",
        ),
        (
            "DAX calendar tables",
            "DAX calendar tables is not available for large-data tables yet. "
            "Tables up to 100,000 rows work everywhere; large tables support the data grid, "
            "sort, filter, column statistics and export. Other features arrive in a later release.",
        ),
    ],
)
def test_r2_refusal_literal_text_per_what(what: str, expected_literal: str) -> None:
    ctrl = StudioController()
    actual = ctrl._large_data_refusal(what)
    assert actual == expected_literal


# --- Guard & Real-Argument Sweep for R2 User-Initiated Slots ---

_R2_SLOTS_AND_CALLS = [
    ("manage_relationships", lambda c: c.manage_relationships(), bool, False, "Model relationships"),
    ("createRelationshipFromDrag", lambda c: c.createRelationshipFromDrag("tbl_store", "cat", "tbl_other", "cat"), bool, False, "Model relationships"),
    ("editRelationship", lambda c: c.editRelationship("rel_123"), bool, False, "Model relationships"),
    ("deleteRelationship", lambda c: c.deleteRelationship("rel_123"), bool, False, "Model relationships"),
    ("transform_data_dialog", lambda c: c.transform_data_dialog(), bool, False, "Power Query transformations"),
    ("power_query_m_editor_dialog", lambda c: c.power_query_m_editor_dialog(), bool, False, "Power Query transformations"),
    ("calculated_column_dialog", lambda c: c.calculated_column_dialog(), bool, False, "DAX calculated columns"),
    ("validate_calculated_column", lambda c: c.validate_calculated_column("NewCol", "[cat]"), str, "DAX calculated columns", "DAX calculated columns"),
    ("save_calculated_column", lambda c: c.save_calculated_column("NewCol", "[cat]"), str, "DAX calculated columns", "DAX calculated columns"),
    ("append_queries_dialog", lambda c: c.append_queries_dialog(), bool, False, "Append queries"),
    ("merge_queries_dialog", lambda c: c.merge_queries_dialog(), bool, False, "Merge queries"),
    ("calculated_table_dialog", lambda c: c.calculated_table_dialog(), bool, False, "DAX calculated tables"),
    ("calendar_table_dialog", lambda c: c.calendar_table_dialog(), bool, False, "DAX calendar tables"),
    ("mark_date_table_dialog", lambda c: c.mark_date_table_dialog(), bool, False, "Date table"),
    ("set_model_key_column", lambda c: c.set_model_key_column("tbl_store", "cat"), bool, False, "Key column"),
    ("set_model_column_sort_by", lambda c: c.set_model_column_sort_by("tbl_store", "cat", "val"), bool, False, "Sort by column"),
    ("refresh_source", lambda c: c.refresh_source(), type(None), None, "Report refresh"),
    ("refresh_all_sources", lambda c: c.refresh_all_sources(), type(None), None, "Report refresh"),
    ("connectDataSource", lambda c: c.connectDataSource("file_text_csv"), bool, False, "Import"),
    ("import_folder_dialog", lambda c: c.import_folder_dialog(), type(None), None, "Import"),
    ("import_folder_path", lambda c: c.import_folder_path(Path("/fake/path")), bool, False, "Import"),
    ("import_data_dialog", lambda c: c.import_data_dialog(), type(None), None, "Import"),
]


@pytest.mark.parametrize(
    ("slot_name", "caller", "expected_type", "expected_ret", "what"),
    _R2_SLOTS_AND_CALLS,
    ids=[item[0] for item in _R2_SLOTS_AND_CALLS],
)
def test_r2_user_initiated_slots_sweep_refuses_cleanly(
    qapp: QApplication,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    slot_name: str,
    caller: Any,
    expected_type: type,
    expected_ret: Any,
    what: str,
) -> None:
    """Each user-initiated slot returns neutral value, sets exact refusal, mutates nothing, reads 0 rows."""
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        # Snapshot before
        project_before = deepcopy(ctrl._project)
        candidates_before = list(ctrl._loaded_candidates.keys())

        # Instrument candidate rows and controller rows
        row_reads = 0

        def counting_rows(self: StoreCandidate) -> Any:
            nonlocal row_reads
            row_reads += 1
            raise LargeTableError("rows accessed!")

        monkeypatch.setattr(StoreCandidate, "rows", property(counting_rows))

        # Clear status
        ctrl._set_status("")

        ret = caller(ctrl)

        if expected_ret == "DAX calculated columns":
            assert ret == ctrl._large_data_refusal(what)
        else:
            assert ret == expected_ret
        assert isinstance(ret, expected_type)

        expected_msg = ctrl._large_data_refusal(what)
        assert ctrl._status_message == expected_msg

        # No row reads
        assert row_reads == 0

        # No mutation
        assert ctrl._project == project_before
        assert list(ctrl._loaded_candidates.keys()) == candidates_before
    finally:
        ps.close()


# --- Internal method refusals (query_candidate, validate_relationship_candidate, etc.) ---

def test_validate_relationship_candidate_refusal(qapp: QApplication, tmp_path: Path) -> None:
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        with pytest.raises(RelationshipError, match="Model relationships is not available for large-data tables yet"):
            ctrl._validate_relationship_candidate([])
    finally:
        ps.close()


def test_validate_loaded_relationship_candidates_noop_with_store(qapp: QApplication, tmp_path: Path) -> None:
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        # candidate.rows would raise LargeTableError if accessed
        with patch.object(StoreCandidate, "rows", property(lambda self: (_ for _ in ()).throw(LargeTableError("rows accessed!")))):
            ctrl._validate_loaded_relationship_candidates(ctrl._project)
    finally:
        ps.close()


def test_cross_table_relationship_error_reads_no_store_rows(qapp: QApplication, tmp_path: Path) -> None:
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        # Does not access candidate.rows
        with patch.object(StoreCandidate, "rows", property(lambda self: (_ for _ in ()).throw(LargeTableError("rows accessed!")))):
            err = StudioController._cross_table_relationship_error(
                "dim", "fact", [{"id": "dim"}, {"id": "fact"}], []
            )
            assert err is not None
    finally:
        ps.close()


def test_commit_transform_steps_refusal(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        ctrl._set_status("")
        ret = ctrl._commit_transform_steps("s_store", [], ImportCandidate("csv", ["cat"], [], {}, []))
        assert ret is False
        assert ctrl._status_message == ctrl._large_data_refusal("Power Query transformations")
    finally:
        ps.close()


def test_commit_transform_session_refusal(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        ctrl._set_status("")
        ret = ctrl._commit_transform_session({})
        assert ret is False
        assert ctrl._status_message == ctrl._large_data_refusal("Power Query transformations")
    finally:
        ps.close()


def test_refresh_transform_query_preview_refusal(qapp: QApplication, tmp_path: Path) -> None:
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        with pytest.raises(QueryError, match="Power Query transformations is not available for large-data tables yet"):
            ctrl._refresh_transform_query_preview("s_store")
    finally:
        ps.close()


def test_create_saved_query_refusal(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        ctrl._set_status("")
        ret = ctrl._create_saved_query("Q1", ["s_store"], ImportCandidate("csv", ["cat"], [], {}, []), {}, {})
        assert ret is False
        assert ctrl._status_message == ctrl._large_data_refusal("Power Query transformations")
    finally:
        ps.close()


def test_query_candidate_refusal(qapp: QApplication, tmp_path: Path) -> None:
    ps, sc = _make_store_candidate(tmp_path, "tbl_store_qc", 100)
    try:
        source = {
            "id": "q1",
            "query_definition": {"operation": "reference", "source_ids": ["s_store"]},
        }
        with pytest.raises(QueryError, match="Power Query transformations is not available for large-data tables yet"):
            StudioController._query_candidate(source, {"s_store": sc})
    finally:
        ps.close()


def test_plan_calculated_column_change_refusal(qapp: QApplication, tmp_path: Path) -> None:
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        with pytest.raises(MeasureError, match="DAX calculated columns is not available for large-data tables yet"):
            ctrl._plan_calculated_column_change("s_store", "save", "col", {"name": "col", "expression": "[cat]"})
        assert ctrl._status_message == ctrl._large_data_refusal("DAX calculated columns")
    finally:
        ps.close()


def test_apply_calculated_columns_noop_with_store(qapp: QApplication, tmp_path: Path) -> None:
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        cand = ctrl._loaded_candidates["s_store"]
        with patch.object(StoreCandidate, "rows", property(lambda self: (_ for _ in ()).throw(LargeTableError("rows accessed!")))):
            res_cand, type_map = ctrl._apply_calculated_columns("s_store", cand)
            assert res_cand is cand
            assert type_map == {}
    finally:
        ps.close()


def test_validate_model_column_sort_rule_refusal(qapp: QApplication, tmp_path: Path) -> None:
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        order, reason = ctrl._validate_model_column_sort_rule("tbl_store", "cat", "val")
        assert order is None
        assert reason == ctrl._large_data_refusal("Sort by column")
    finally:
        ps.close()


def test_commit_web_import_refusal(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        ctrl._set_status("")
        ret = ctrl._commit_web_import({"url": "http://example.com"}, ImportCandidate("web", ["c"], [], {}, []))
        assert ret is False
        assert ctrl._status_message == ctrl._large_data_refusal("Import")
    finally:
        ps.close()


def test_commit_odata_import_refusal(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        ctrl._set_status("")
        ret = ctrl._commit_odata_import({"service_root": "http://example.com/odata"}, ImportCandidate("odata", ["c"], [], {"entity_set_name": "T"}, []))
        assert ret is False
        assert ctrl._status_message == ctrl._large_data_refusal("Import")
    finally:
        ps.close()


def test_commit_sql_server_import_refusal(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        ctrl._set_status("")
        ret = ctrl._commit_sql_server_import({"server": "s", "port": 1433, "database": "d", "username": "u"}, "pw", ImportCandidate("sql_server", ["c"], [], {"schema": "s", "table_name": "t"}, []))
        assert ret is False
        assert ctrl._status_message == ctrl._large_data_refusal("Import")
    finally:
        ps.close()


# --- Model view and dependent tests ---

def test_model_view_and_cards_work_without_reading_store_rows(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_refresh_model_view and Model view table cards display metadata and row_count without reading rows."""
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        # Instrument candidate.rows to prove 0 reads
        row_reads = 0

        def counting_rows(self: StoreCandidate) -> Any:
            nonlocal row_reads
            row_reads += 1
            raise LargeTableError("rows accessed in model view!")

        monkeypatch.setattr(StoreCandidate, "rows", property(counting_rows))

        ctrl._refresh_model_view()

        assert row_reads == 0
        # Catalog contains tbl_store
        store_entry = next((t for t in ctrl._table_catalog if t.get("sourceId") == "s_store"), None)
        assert store_entry is not None
        assert store_entry["name"] == "TStore"
        assert store_entry["rowCount"] == 500
        assert store_entry["headers"] == ["cat", "val"]
        assert store_entry["loaded"] is True
    finally:
        ps.close()


# --- Ordinary table behaviour unchanged ---

def test_ordinary_tables_behave_normally_without_store(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With NO store table loaded, ordinary tables allow normal operations."""
    ctrl = StudioController()
    csv1 = tmp_path / "table1.csv"
    csv1.write_text("id,name\n1,Alpha\n2,Beta\n", encoding="utf-8")
    csv2 = tmp_path / "table2.csv"
    csv2.write_text("id,val\n1,100\n2,200\n", encoding="utf-8")

    assert ctrl._commit_import(csv1, parse_file(csv1)) is True
    assert ctrl._commit_import(csv2, parse_file(csv2)) is True
    assert not ctrl._store_tables_loaded()

    # Can set model key column
    assert ctrl.set_model_key_column(ctrl._active_source_id, "id") is True

    # Can save calculated column
    err = ctrl.save_calculated_column("DoubleVal", "[id] * 2")
    assert err == ""


# --- B4b-t10b items ---

def test_open_recent_source_refusal_when_store_loaded(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 1: openRecentSource refuses Import when store tables are loaded, without opening dialogs or calling import."""
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        source_entry = type("RecentSource", (), {
            "path": str(tmp_path / "recent.csv"),
            "exists": True,
            "kind": "csv",
            "display_name": "recent",
            "parser_options": {},
        })()
        ctrl._recent_source_store = type("RecentStore", (), {"sources": [source_entry]})()

        def _forbidden_import(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("_import_file_path or _import_folder_path should never be called when store table is loaded")

        monkeypatch.setattr(ctrl, "_import_file_path", _forbidden_import)
        monkeypatch.setattr(ctrl, "_import_folder_path", _forbidden_import)

        ctrl._set_status("")
        ret = ctrl.openRecentSource(0)
        assert ret is False
        assert ctrl._status_message == ctrl._large_data_refusal("Import")
    finally:
        ps.close()


def test_set_column_type_refusal_when_store_loaded(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 2: setColumnType refuses Power Query transformations when store tables are loaded."""
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        def _forbidden_raw(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError("_raw_candidate_for_source should never be called when store table is loaded")

        monkeypatch.setattr(ctrl, "_raw_candidate_for_source", _forbidden_raw)

        ctrl._set_status("")
        ret = ctrl.setColumnType("val", "whole_number")
        assert ret is False
        assert ctrl._status_message == ctrl._large_data_refusal("Power Query transformations")
        # Ensure column types were not mutated
        col_type = ctrl._active_column_type_map().get("val")
        assert col_type != "whole_number"
    finally:
        ps.close()


def test_apply_calculated_columns_drops_when_store_loaded(
    qapp: QApplication, tmp_path: Path
) -> None:
    """Item 3: _apply_calculated_columns returns candidate, {} whenever any store table is loaded.

    KNOWN: task 13 (open project with mixed ordinary and store tables) must replace this whole-model drop with per-table handling
    """
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        ordinary_candidate = ImportCandidate("csv", ["x", "y"], [{"x": "1", "y": "2"}], {}, [])
        cand, types = ctrl._apply_calculated_columns("s_store", ordinary_candidate)
        assert cand is ordinary_candidate
        assert types == {}
    finally:
        ps.close()


def test_query_candidate_exact_refusal_text() -> None:
    """Item 5: _query_candidate refusal text matches the exact standard format."""
    expected = (
        "Power Query transformations is not available for large-data tables yet. "
        "Tables up to 100,000 rows work everywhere; large tables support the data grid, "
        "sort, filter, column statistics and export. Other features arrive in a later release."
    )
    # Instantiate a dummy store candidate and pass to _query_candidate
    dummy_sc = StoreCandidate("csv", ["a"], {}, [], store_table="dummy", row_count=100, session=None)
    with pytest.raises(QueryError) as exc_info:
        StudioController._query_candidate({"query_definition": {"source_ids": ["s1"]}}, {"s1": dummy_sc})
    assert str(exc_info.value) == expected

