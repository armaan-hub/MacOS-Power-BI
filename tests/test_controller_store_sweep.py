"""Tests for controller store sweep and LargeTableError sites (Stage B4b task 8)."""

from __future__ import annotations

import inspect
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pyarrow as pa
import pytest
from PySide6.QtCore import QMetaMethod
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from analytics_studio.controller import StudioController, _visual_measure_binding
from analytics_studio.store.candidate import LargeTableError, StoreCandidate
from analytics_studio.store.session import ProjectStore


@pytest.fixture
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["controller_store_sweep_test"])
    return app


# Dictionary of known future work that produces an explicit refusal message or is planned for later tasks.
# Each entry is strict xfail so later tasks (9, 10, 11, 12) must remove or update the entry.
KNOWN_FUTURE: dict[str, str] = {}


SKIPPED_SLOTS_REASONS: dict[str, str] = {
    "deleteLater": "Destroys the QObject / Qt lifecycle method",
    "confirmClose": "Quits or prompts user to save unsaved project",
    "openRecentSource": "Opens file / prompts to load a recent external source",
    "power_query_m_editor_dialog": "Opens modal Power Query M editor dialog",
    "calculated_table_dialog": "Opens modal calculated table dialog",
    "calendar_table_dialog": "Opens modal calendar table dialog",
    "mark_date_table_dialog": "Opens modal mark date table dialog",
    "calculated_column_dialog": "Opens modal calculated column dialog",
    "choose_shape_map_file": "Opens modal file dialog for shape map file",
    "insert_image": "Opens modal file dialog to insert image",
    "exportReportPdfImages": "Shells out or writes file report PDF/images",
    "manage_relationships": "Opens modal relationship manager dialog",
    "connectDataSource": "Opens modal connect data source dialog",
    "editMeasure": "Opens modal DAX measure dialog",
    "deleteMeasure": "Prompts with modal question box to delete measure",
}


def _make_store_candidate(tmp_path: Path, table_name: str = "tbl_sweep", row_count: int = 2000) -> tuple[ProjectStore, StoreCandidate]:
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


def test_controller_store_sweep(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Enumerate every QML-bound Property and Slot of StudioController with a StoreCandidate active."""
    # Monkeypatch blocking dialogs to raise
    def bad_dialog(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Blocking dialog opened!")

    monkeypatch.setattr(QFileDialog, "getOpenFileName", bad_dialog)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", bad_dialog)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", bad_dialog)
    monkeypatch.setattr(QMessageBox, "information", bad_dialog)
    monkeypatch.setattr(QMessageBox, "warning", bad_dialog)
    monkeypatch.setattr(QMessageBox, "critical", bad_dialog)
    monkeypatch.setattr(QMessageBox, "question", bad_dialog)
    monkeypatch.setattr(QInputDialog, "getText", bad_dialog)
    monkeypatch.setattr(QInputDialog, "getItem", bad_dialog)

    ps, candidate = _make_store_candidate(tmp_path, "tbl_sweep", 2000)
    try:
        controller = StudioController()
        controller._install_source(None, "src_sweep_1", candidate)

        meta = controller.metaObject()

        # Call every property getter
        prop_count = meta.propertyCount()
        for i in range(prop_count):
            prop = meta.property(i)
            # Must not raise
            val = prop.read(controller)
            assert val is not None or prop.isValid()

        # Call every Slot that can be called with trivial/default arguments
        slots_called = 0
        called_names: set[str] = set()

        for i in range(meta.methodCount()):
            m = meta.method(i)
            if m.methodType() != QMetaMethod.MethodType.Slot:
                continue
            name = m.name().data().decode("utf-8")
            if name in SKIPPED_SLOTS_REASONS:
                continue

            fn = getattr(controller, name, None)
            if fn is None:
                continue

            sig = inspect.signature(fn)
            args = []
            for param in sig.parameters.values():
                if param.name == "self":
                    continue
                if param.default is not inspect.Parameter.empty:
                    continue
                ann = param.annotation
                if ann in {str, "str", "QString"}:
                    args.append("")
                elif ann in {int, "int", "qint64", "long"}:
                    args.append(0)
                elif ann in {bool, "bool"}:
                    args.append(False)
                elif ann in {list, "list", "QVariantList", "QList<QVariant>"}:
                    args.append([])
                elif ann in {dict, "dict", "QVariantMap", "QMap<QString,QVariant>"}:
                    args.append({})
                else:
                    args.append("")

            if name in KNOWN_FUTURE:
                with pytest.raises(Exception):
                    fn(*args)
            else:
                fn(*args)
                slots_called += 1
                called_names.add(name)

        assert prop_count == 68
        assert slots_called == 136
    finally:
        ps.close()


def _setup_visual_controller(tmp_path: Path) -> tuple[ProjectStore, StudioController]:
    ps, sc = _make_store_candidate(tmp_path, "tbl_sites", 100)
    ctrl = StudioController()
    ctrl._install_source(None, "s_store", sc)
    ctrl._project["data_sources"].append({"id": "s_store", "name": "TStore", "kind": "csv"})
    ctrl._project["data_sources"].append({"id": "s_dim", "name": "TDim", "kind": "csv"})
    ctrl._project["model"]["tables"].append({
        "id": "tbl_store", "source_id": "s_store", "name": "TStore",
        "column_types": {"cat": "text", "val": "text"},
    })
    ctrl._project["model"]["tables"].append({
        "id": "tbl_dim", "source_id": "s_dim", "name": "TDim",
        "column_types": {"cat": "text"},
    })
    ctrl._project["model"]["measures"].append({
        "name": "TotalSales", "expression": "SUM(TStore[val])", "home_table_id": "tbl_store",
    })
    ctrl._refresh_model_view()
    return ps, ctrl


def test_site_1_visual_gauge_data(qapp: QApplication, tmp_path: Path) -> None:
    """Site 1 (was 3227): visualGaugeData surfaces LargeTableError in status message."""
    ps, ctrl = _setup_visual_controller(tmp_path)
    try:
        m_bind = _visual_measure_binding("TotalSales")
        page = ctrl._active_page()
        page["visuals"].append({
            "id": "v_gauge", "title": "TestGauge", "type": "gauge", "table_id": "tbl_store",
            "fields": {"Value": [m_bind]},
        })
        mock_rows = [{"cat": "A", "val": "1"}]
        mock_context = (
            {"tbl_store": mock_rows},
            [{"id": "tbl_store", "name": "TStore", "headers": ["cat", "val"], "rows": mock_rows}],
            set(),
        )

        msg = "Large table refusal: gauge unavailable"
        with patch.object(ctrl, "_report_filter_context", return_value=mock_context):
            with patch.object(ctrl, "_measure_value_for_visual_group", side_effect=LargeTableError(msg)):
                ctrl._set_status("")
                res = ctrl.visualGaugeData("TestGauge")
                assert ctrl._status_message == msg
                assert res["value"] == 0.0

            with patch.object(ctrl, "_measure_value_for_visual_group", return_value=Decimal("42")):
                ctrl._set_status("")
                res_ord = ctrl.visualGaugeData("TestGauge")
                assert res_ord["value"] == 42.0
    finally:
        ps.close()


def test_site_2_visual_shape_map_data(qapp: QApplication, tmp_path: Path) -> None:
    """Site 2 (was 3544): visualShapeMapData surfaces LargeTableError in status message."""
    ps, ctrl = _setup_visual_controller(tmp_path)
    try:
        m_bind = _visual_measure_binding("TotalSales")
        page = ctrl._active_page()
        page["visuals"].append({
            "id": "v_map", "title": "TestMap", "type": "shapeMap", "table_id": "tbl_store",
            "shape_map_file": "fake_map", "shape_map_key": "id",
            "fields": {"Location": [("tbl_store", "cat")], "Values": [m_bind]},
        })
        mock_rows = [{"cat": "A", "val": "1"}]
        mock_context = (
            {"tbl_store": mock_rows},
            [{"id": "tbl_store", "name": "TStore", "headers": ["cat", "val"], "rows": mock_rows}],
            set(),
        )

        msg = "Large table refusal: map unavailable"
        with patch.object(ctrl, "_report_filter_context", return_value=mock_context):
            with patch("analytics_studio.controller.load_boundary_features", return_value=[{"id": "A", "properties": {"id": "A"}}]):
                with patch.object(ctrl, "_measure_value_for_visual_group", side_effect=LargeTableError(msg)):
                    ctrl._set_status("")
                    res = ctrl.visualShapeMapData("TestMap")
                    assert ctrl._status_message == msg
                    assert len(res) == 1
                    assert res[0]["value"] is None

                with patch.object(ctrl, "_measure_value_for_visual_group", return_value=Decimal("42")):
                    ctrl._set_status("")
                    res_ord = ctrl.visualShapeMapData("TestMap")
                    assert len(res_ord) == 1
                    assert res_ord[0]["value"] == 42.0
    finally:
        ps.close()


def test_site_4_cross_table_table_data(qapp: QApplication, tmp_path: Path) -> None:
    """Site 4 (was 3909): _cross_table_table_data surfaces LargeTableError message in error field."""
    ps, ctrl = _setup_visual_controller(tmp_path)
    try:
        m_bind = _visual_measure_binding("TotalSales")
        page = ctrl._active_page()
        page["visuals"].append({
            "id": "v_cross_table", "title": "CrossTable", "type": "table", "table_id": "tbl_dim",
            "fields": {"Fields": [{"table_id": "tbl_dim", "column": "cat"}, {"table_id": "tbl_store", "column": m_bind}]},
        })
        mock_rows = [{"cat": "A"}]
        mock_context = (
            {"tbl_dim": mock_rows, "tbl_store": []},
            [
                {"id": "tbl_dim", "name": "TDim", "headers": ["cat"], "rows": mock_rows},
                {"id": "tbl_store", "name": "TStore", "headers": ["cat", "val"], "rows": []},
            ],
            set(),
        )

        msg = "Large table refusal: cross table unavailable"
        with patch.object(ctrl, "_report_filter_context", return_value=mock_context):
            with patch.object(ctrl, "_measure_table_context", return_value=mock_context[1]):
                with patch.object(ctrl, "_measure_reference_table_id", return_value=("tbl_store", None)):
                    with patch.object(ctrl, "_cross_table_relationship_error", return_value=None):
                        with patch.object(ctrl, "_measure_value_for_visual_group", side_effect=LargeTableError(msg)):
                            res = ctrl.visualTableData("CrossTable")
                            assert res.get("error") == msg

                        with patch.object(ctrl, "_measure_value_for_visual_group", return_value=Decimal("42")):
                            res_ord = ctrl.visualTableData("CrossTable")
                            assert "error" not in res_ord or not res_ord.get("error")
                            assert len(res_ord["rows"]) == 1
                            assert res_ord["rows"][0]["values"] == ["A", "42"]
    finally:
        ps.close()


def test_site_5_visual_table_data(qapp: QApplication, tmp_path: Path) -> None:
    """Site 5 (was 4064): visualTableData surfaces LargeTableError in error detail."""
    ps, ctrl = _setup_visual_controller(tmp_path)
    try:
        m_bind = _visual_measure_binding("TotalSales")
        page = ctrl._active_page()
        page["visuals"].append({
            "id": "v_table", "title": "TestTable", "type": "table", "table_id": "tbl_store",
            "fields": {"Fields": ["cat", m_bind]},
        })
        mock_rows = [{"cat": "A", "val": "1"}]
        mock_context = (
            {"tbl_store": mock_rows},
            [{"id": "tbl_store", "name": "TStore", "headers": ["cat", "val"], "rows": mock_rows}],
            set(),
        )

        msg = "Large table refusal: table visual unavailable"
        with patch.object(ctrl, "_report_filter_context", return_value=mock_context):
            with patch.object(ctrl, "_measure_table_context", return_value=mock_context[1]):
                with patch.object(ctrl, "_measure_value_for_visual_group", side_effect=LargeTableError(msg)):
                    res = ctrl.visualTableData("TestTable")
                    assert res.get("error") == msg

                with patch.object(ctrl, "_measure_value_for_visual_group", return_value=Decimal("42")):
                    res_ord = ctrl.visualTableData("TestTable")
                    assert "error" not in res_ord or not res_ord.get("error")
                    assert len(res_ord["rows"]) == 1
                    assert res_ord["rows"][0]["values"] == ["A", "42"]
    finally:
        ps.close()


def test_site_6_visual_matrix_data(qapp: QApplication, tmp_path: Path) -> None:
    """Site 6 (was 4172): visualMatrixData surfaces LargeTableError in matrix cells."""
    ps, ctrl = _setup_visual_controller(tmp_path)
    try:
        m_bind = _visual_measure_binding("TotalSales")
        page = ctrl._active_page()
        page["visuals"].append({
            "id": "v_matrix", "title": "TestMatrix", "type": "matrix", "table_id": "tbl_store",
            "fields": {"Rows": [("tbl_store", "cat")], "Columns": [("tbl_store", "cat")], "Values": [m_bind]},
        })
        mock_rows = [{"cat": "A", "val": "1"}]
        mock_context = (
            {"tbl_store": mock_rows},
            [{"id": "tbl_store", "name": "TStore", "headers": ["cat", "val"], "rows": mock_rows}],
            set(),
        )

        msg = "Large table refusal: matrix cell unavailable"
        with patch.object(ctrl, "_report_filter_context", return_value=mock_context):
            with patch.object(ctrl, "_measure_value_for_visual_group", side_effect=LargeTableError(msg)):
                res = ctrl.visualMatrixData("TestMatrix")
                assert res["rows"][0]["values"][1] == msg

            with patch.object(ctrl, "_measure_value_for_visual_group", return_value=Decimal("42")):
                res_ord = ctrl.visualMatrixData("TestMatrix")
                assert res_ord["rows"][0]["values"][1] == "42"
    finally:
        ps.close()


def test_site_7_visual_card_data(qapp: QApplication, tmp_path: Path) -> None:
    """Site 7 (was 4289, 4314): visualCardData surfaces LargeTableError in card value and highlight."""
    ps, ctrl = _setup_visual_controller(tmp_path)
    try:
        m_bind = _visual_measure_binding("TotalSales")
        page = ctrl._active_page()
        page["visuals"].append({
            "id": "v_card", "title": "TestCard", "type": "card", "table_id": "tbl_store",
            "fields": {"Fields": [m_bind]},
        })
        mock_rows = [{"cat": "A", "val": "1"}]
        mock_context = (
            {"tbl_store": mock_rows},
            [{"id": "tbl_store", "name": "TStore", "headers": ["cat", "val"], "rows": mock_rows}],
            set(),
        )

        msg = "Large table refusal: card unavailable"
        with patch.object(ctrl, "_report_filter_context", return_value=mock_context):
            with patch.object(ctrl, "_measure_value_for_visual_group", side_effect=LargeTableError(msg)):
                res = ctrl.visualCardData("TestCard")
                assert res["value"] == msg

            with patch.object(ctrl, "_measure_value_for_visual_group", return_value=Decimal("42")):
                res_ord = ctrl.visualCardData("TestCard")
                assert res_ord["value"] == "42"
    finally:
        ps.close()


def test_site_8_dynamic_visual_series(qapp: QApplication, tmp_path: Path) -> None:
    """Site 8 (was 15225): _generate_dynamic_visual_series surfaces LargeTableError in status message."""
    ps, ctrl = _setup_visual_controller(tmp_path)
    try:
        m_bind = _visual_measure_binding("TotalSales")
        page = ctrl._active_page()
        page["visuals"].append({
            "id": "v_chart", "title": "TestChart", "type": "clusteredColumn", "table_id": "tbl_store",
            "fields": {"X-axis": [("tbl_store", "cat")], "Y-axis": [m_bind]},
        })
        mock_rows = [{"cat": "A", "val": "1"}, {"cat": "B", "val": "2"}]
        mock_context = (
            {"tbl_store": mock_rows},
            [{"id": "tbl_store", "name": "TStore", "headers": ["cat", "val"], "rows": mock_rows}],
            set(),
        )

        msg = "Large table refusal: series unavailable"
        with patch.object(ctrl, "_report_filter_context", return_value=mock_context):
            with patch.object(ctrl, "_measure_value_for_visual_group", side_effect=LargeTableError(msg)):
                ctrl._set_status("")
                res = ctrl._generate_dynamic_visual_series("TestChart")
                assert ctrl._status_message == msg
                assert res == []

            with patch.object(ctrl, "_measure_value_for_visual_group", return_value=Decimal("42")):
                ctrl._set_status("")
                res_ord = ctrl._generate_dynamic_visual_series("TestChart")
                assert len(res_ord) == 2
                assert res_ord[0]["value"] == 42.0
    finally:
        ps.close()
