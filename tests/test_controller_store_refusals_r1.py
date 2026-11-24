"""Tests for controller store refusals R1 (report, measures, filters) (Stage B4b task 9)."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pyarrow as pa
import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.measures import MeasureError
from analytics_studio.store.candidate import StoreCandidate
from analytics_studio.store.session import ProjectStore


@pytest.fixture
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["controller_store_refusals_test"])
    return app


def _make_store_candidate(tmp_path: Path, table_name: str = "tbl_refusals", row_count: int = 1000) -> tuple[ProjectStore, StoreCandidate]:
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
    ps, sc = _make_store_candidate(tmp_path, "tbl_store_refusal", 500)
    ctrl = StudioController()
    ctrl._install_source(None, "s_store", sc)
    ctrl._project["data_sources"].append({"id": "s_store", "name": "TStore", "kind": "csv"})
    ctrl._project["model"]["tables"].append({
        "id": "tbl_store", "source_id": "s_store", "name": "TStore",
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


def test_refusal_helpers(qapp: QApplication, tmp_path: Path) -> None:
    """Helper _store_tables_loaded and _large_data_refusal produce expected output."""
    ctrl = StudioController()
    assert not ctrl._store_tables_loaded()
    expected_msg = (
        "Something is not available for large-data tables yet. "
        "Tables up to 100,000 rows work everywhere; large tables support the data grid, "
        "sort, filter, column statistics and export. Other features arrive in a later release."
    )
    assert ctrl._large_data_refusal("Something") == expected_msg

    ps, sc = _make_store_candidate(tmp_path, "tbl_hlp", 100)
    try:
        ctrl._loaded_candidates["s_test"] = sc
        assert ctrl._store_tables_loaded()
    finally:
        ps.close()


def test_status_spam_prevention(qapp: QApplication, tmp_path: Path) -> None:
    """Repeated setter calls with same message do not trigger repeat state/status updates."""
    ctrl = StudioController()
    msg = ctrl._large_data_refusal("Report view")
    ctrl._set_status(msg)
    assert ctrl._status_message == msg

    emitted = []
    ctrl.statusChanged.connect(lambda m: emitted.append(m))
    ctrl._set_status(msg)
    assert emitted == []


def test_refusal_refresh_report(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_refresh_report clears visuals and sets status to refusal without raising."""
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        ctrl._set_status("")
        ctrl._refresh_report()
        expected = ctrl._large_data_refusal("Report view")
        assert ctrl._status_message == expected
        assert ctrl._monthly_series == []
        assert ctrl._region_series == []
        assert ctrl._monthly_chart_message == expected
        assert ctrl._region_chart_message == expected
    finally:
        ps.close()


def test_refusal_refresh_report_async(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_refresh_report_async cancels worker, clears visuals and sets status to refusal."""
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        ctrl._set_status("")
        ctrl._refresh_report_async()
        expected = ctrl._large_data_refusal("Report view")
        assert ctrl._status_message == expected
        assert ctrl._monthly_series == []
        assert ctrl._region_series == []
        assert ctrl._monthly_chart_message == expected
        assert ctrl._region_chart_message == expected
    finally:
        ps.close()


def test_refusal_regions_property(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """regions property returns neutral ['All regions'] and sets status to refusal."""
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        ctrl._set_status("")
        val = ctrl.regions
        assert val == ["All regions"]
        assert ctrl._status_message == ctrl._large_data_refusal("Region filter")
    finally:
        ps.close()


def test_refusal_page_filter_values(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """pageFilterValues returns [] and sets status to refusal."""
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        ctrl._set_status("")
        val = ctrl.pageFilterValues("tbl_store", "cat")
        assert val == []
        assert ctrl._status_message == ctrl._large_data_refusal("Page filter values")
    finally:
        ps.close()


def test_refusal_search_page_filter_values(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """searchPageFilterValues returns [] and sets status to refusal."""
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        ctrl._set_status("")
        val = ctrl.searchPageFilterValues("tbl_store", "cat", "cat_1")
        assert val == []
        assert ctrl._status_message == ctrl._large_data_refusal("Page filter values")
    finally:
        ps.close()


def test_refusal_report_filter_context(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_report_filter_context returns ({}, [], set()) and sets status to refusal."""
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        ctrl._set_status("")
        rows_by_id, context, filter_ids = ctrl._report_filter_context()
        assert rows_by_id == {}
        assert context == []
        assert filter_ids == set()
        assert ctrl._status_message == ctrl._large_data_refusal("Report filters")
    finally:
        ps.close()


def test_refusal_visual_getters(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """All visual*Data getters return neutral values and set status to refusal."""
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        expected = ctrl._large_data_refusal("Report visual data")

        ctrl._set_status("")
        res_gauge = ctrl.visualGaugeData("TestGauge")
        assert res_gauge == {
            "value": 0.0, "minimum": 0.0, "maximum": 1.0,
            "target": None, "highlight_value": None, "has_value": False,
        }
        assert ctrl._status_message == expected

        ctrl._set_status("")
        res_kpi = ctrl.visualKpiData("TestKpi")
        assert res_kpi == {
            "field": "", "trend_field": "", "value": 0.0, "target": None,
            "trend": [], "highlight_value": None, "has_value": False,
        }
        assert ctrl._status_message == expected

        ctrl._set_status("")
        res_map = ctrl.visualMapData("TestMap")
        assert res_map == []
        assert ctrl._status_message == expected

        ctrl._set_status("")
        res_smap = ctrl.visualShapeMapData("TestShapeMap")
        assert res_smap == []
        assert ctrl._status_message == expected

        ctrl._set_status("")
        res_scatter = ctrl.visualScatterData("TestScatter")
        assert res_scatter == []
        assert ctrl._status_message == expected

        ctrl._set_status("")
        res_table = ctrl.visualTableData("TestTable")
        assert res_table == {"columns": [], "rows": [], "total_rows": 0}
        assert ctrl._status_message == expected

        ctrl._set_status("")
        res_matrix = ctrl.visualMatrixData("TestMatrix")
        assert res_matrix == {"columns": [], "rows": [], "total_rows": 0}
        assert ctrl._status_message == expected

        ctrl._set_status("")
        res_card = ctrl.visualCardData("TestCard")
        assert res_card == {
            "label": "", "value": "", "aggregation": "",
            "highlight_value": "", "has_highlights": False,
        }
        assert ctrl._status_message == expected

        ctrl._set_status("")
        res_series = ctrl._generate_dynamic_visual_series("TestChart")
        assert res_series == []
        assert ctrl._status_message == expected
    finally:
        ps.close()


def test_refusal_create_measure(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """create_measure returns False, leaves measures unchanged, sets status to refusal."""
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        ctrl._set_status("")
        snap = deepcopy(ctrl._project.get("model", {}).get("measures", []))
        ok = ctrl.create_measure("M1", "1 + 1")
        assert ok is False
        assert ctrl._project.get("model", {}).get("measures", []) == snap
        assert ctrl._status_message == ctrl._large_data_refusal("DAX measures")
    finally:
        ps.close()


def test_refusal_update_measure(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """update_measure returns False, leaves measures unchanged, sets status to refusal."""
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        ctrl._set_status("")
        snap = deepcopy(ctrl._project.get("model", {}).get("measures", []))
        ok = ctrl.update_measure("M1", "M1", "2 + 2")
        assert ok is False
        assert ctrl._project.get("model", {}).get("measures", []) == snap
        assert ctrl._status_message == ctrl._large_data_refusal("DAX measures")
    finally:
        ps.close()


def test_refusal_remove_measure(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """remove_measure returns False, leaves measures unchanged, sets status to refusal."""
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        ctrl._set_status("")
        snap = deepcopy(ctrl._project.get("model", {}).get("measures", []))
        ok = ctrl.remove_measure("M1")
        assert ok is False
        assert ctrl._project.get("model", {}).get("measures", []) == snap
        assert ctrl._status_message == ctrl._large_data_refusal("DAX measures")
    finally:
        ps.close()


def test_refusal_measure_dialog_slots(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_measure_dialog, editMeasure, deleteMeasure refuse without popping dialogs."""
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        ctrl._set_status("")
        assert ctrl._measure_dialog(quick=False) is False
        assert ctrl._status_message == ctrl._large_data_refusal("DAX measures")

        ctrl._set_status("")
        assert ctrl.editMeasure("M1") is False
        assert ctrl._status_message == ctrl._large_data_refusal("DAX measures")

        ctrl._set_status("")
        assert ctrl.deleteMeasure("M1") is False
        assert ctrl._status_message == ctrl._large_data_refusal("DAX measures")
    finally:
        ps.close()


def test_refusal_measure_preview(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Preview functions refuse and return neutral string/invoke callback with refusal text."""
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        ctrl._set_status("")
        with pytest.raises(MeasureError) as exc_info:
            ctrl._build_preview_inputs("M1", "1 + 1")
        assert ctrl._large_data_refusal("DAX measures") in str(exc_info.value)
        assert ctrl._status_message == ctrl._large_data_refusal("DAX measures")

        ctrl._set_status("")
        res = ctrl._preview_measure_expression("M1", "1 + 1")
        assert res == "—"
        assert ctrl._status_message == ctrl._large_data_refusal("DAX measures")

        ctrl._set_status("")
        callback_res = []
        ctrl._preview_measure_expression_async("M1", "1 + 1", on_done=lambda val: callback_res.append(val))
        assert ctrl._status_message == ctrl._large_data_refusal("DAX measures")
        assert callback_res == [ctrl._large_data_refusal("DAX measures")]
    finally:
        ps.close()


def test_refusal_add_report_filter(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_add_report_filter returns False and leaves report filters unchanged."""
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        ctrl._set_status("")
        snap = deepcopy(ctrl._project.get("report", {}).get("filters", []))
        ok = ctrl._add_report_filter(
            table_id="tbl_store", column="cat", operator="equals", value="val_1", report_scope=True
        )
        assert ok is False
        assert ctrl._project.get("report", {}).get("filters", []) == snap
        assert ctrl._status_message == ctrl._large_data_refusal("Report filters")
    finally:
        ps.close()


def test_refusal_add_field_to_well(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """add_field_to_well returns None, sets status, leaves well unchanged."""
    _assert_no_dialogs(monkeypatch)
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        ctrl._selected_visual = "TestTable"
        page = ctrl._active_page()
        page["visuals"].append({
            "id": "v_table", "title": "TestTable", "type": "table", "table_id": "tbl_store",
            "fields": {"Fields": []},
        })
        ctrl._set_status("")
        snap_visual = deepcopy(page["visuals"])
        ctrl.add_field_to_well("Fields", "cat")
        assert page["visuals"] == snap_visual
        assert ctrl._status_message == ctrl._large_data_refusal("Visual fields")
    finally:
        ps.close()


def test_refusal_measure_table_context(qapp: QApplication, tmp_path: Path) -> None:
    """_measure_table_context raises MeasureError with exact refusal text when store table is loaded."""
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        with pytest.raises(MeasureError) as exc_info:
            ctrl._measure_table_context()
        assert str(exc_info.value) == ctrl._large_data_refusal("DAX measures")
    finally:
        ps.close()


def test_behavior_with_no_store_table(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When only ordinary (ImportCandidate) tables are loaded, measures and filters work as before."""
    source_path = tmp_path / "ord.csv"
    source_path.write_text("id,amount\n1,10\n2,20\n3,30\n", encoding="utf-8")
    ctrl = StudioController()
    assert ctrl._commit_import(source_path, parse_file(source_path))

    assert not ctrl._store_tables_loaded()

    # Create measure should succeed
    active_tbl = ctrl._active_model_table_id()
    ok_m = ctrl.create_measure("TotalAmount", f"SUM([{ctrl._headers[1]}])", home_table_id=active_tbl)
    assert ok_m is True
    assert any(m["name"] == "TotalAmount" for m in ctrl._project["model"]["measures"])

    # Add filter should succeed
    ok_f = ctrl._add_report_filter(
        table_id=active_tbl, column=ctrl._headers[0], operator="equals", value="1", report_scope=True
    )
    assert ok_f is True
    assert any(f["table_id"] == active_tbl for f in ctrl._project["report"]["filters"])


def test_remove_table_with_store_loaded_does_not_read_rows(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """removeTable path on store table does not read candidate.rows."""
    ps, ctrl = _setup_store_controller(tmp_path)
    try:
        # Patch QMessageBox.question to accept deletion
        monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

        # If candidate.rows is accessed, StoreCandidate raises LargeTableError
        with patch.object(StoreCandidate, "rows", property(lambda self: (_ for _ in ()).throw(RuntimeError("rows accessed!")))):
            res = ctrl.removeTable("s_store")
            assert res is True
            assert "s_store" not in ctrl._loaded_candidates
            assert not ctrl._store_tables_loaded()
    finally:
        ps.close()
