"""Tests for controller store sweep and LargeTableError sites (Stage B4b task 8)."""

from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pyarrow as pa
import pytest
from PySide6.QtCore import Property, QMetaMethod
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from analytics_studio.controller import StudioController, _visual_measure_binding
from analytics_studio.file_import import ImportCandidate
from analytics_studio.store.candidate import LargeTableError, StoreCandidate
from analytics_studio.store.session import ProjectStore


@pytest.fixture
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["controller_store_sweep_test"])
    return app


# Names that raise a real exception today and are owned by later tasks (9, 10, 11, 12).
# name -> exception type. Strict: a listed name that stops raising fails, an unlisted raise fails.
# Every entry below raised LargeTableError when the sweep was written (measured), through
# _report_filter_context -> _measure_table_context, which read store rows.
KNOWN_FUTURE: dict[str, type[Exception]] = {}


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


# Slots whose first argument is a visual title and that only read data. Each one is
# called once per visual of the sweep fixture, so no call hits the "visual not found"
# early return.
VISUAL_READ_SLOTS = (
    "monthlySeriesForVisual",
    "regionSeriesForVisual",
    "visualSeries",
    "visualErrorMessage",
    "visualLineSeries",
    "visualLineHighlightSeries",
    "visualGaugeData",
    "visualGaugeHighlightData",
    "visualKpiData",
    "visualMapData",
    "visualShapeMapData",
    "visualScatterData",
    "visualTableData",
    "visualMatrixData",
    "visualCardData",
    "visualHighlightSeries",
)

# Slots Qt registers on the instance when a signal is connected, so the static
# meta-object of the class does not list them.
DYNAMIC_SLOTS = ("_on_relative_filter_boundary",)

# Non-QML methods that read report data. They are called by the sweep too.
EXTRA_CALLABLES = ("_refresh_report", "_generate_dynamic_visual_series")


def _slot_names(meta: Any) -> list[str]:
    """Unique Slot names of a meta-object in declaration order (overloads collapse)."""
    names: list[str] = []
    for i in range(meta.methodCount()):
        m = meta.method(i)
        if m.methodType() != QMetaMethod.MethodType.Slot:
            continue
        name = m.name().data().decode("utf-8")
        if name not in names:
            names.append(name)
    return names


def _property_names(meta: Any) -> list[str]:
    return [meta.property(i).name() for i in range(meta.propertyCount())]


SWEEP_PROPERTIES = _property_names(StudioController.staticMetaObject)
# Properties defined in Python run a getter in controller.py; the rest come from QObject.
PYTHON_PROPERTIES = {
    name for name in SWEEP_PROPERTIES if isinstance(StudioController.__dict__.get(name), Property)
}
SWEEP_SLOTS = [
    name for name in _slot_names(StudioController.staticMetaObject) + list(DYNAMIC_SLOTS)
    if name not in SKIPPED_SLOTS_REASONS
]


def _block_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:
    def bad_dialog(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Blocking dialog opened!")

    for cls, attr in (
        (QFileDialog, "getOpenFileName"),
        (QFileDialog, "getSaveFileName"),
        (QFileDialog, "getExistingDirectory"),
        (QMessageBox, "information"),
        (QMessageBox, "warning"),
        (QMessageBox, "critical"),
        (QMessageBox, "question"),
        (QInputDialog, "getText"),
        (QInputDialog, "getItem"),
    ):
        monkeypatch.setattr(cls, attr, bad_dialog)


def _sweep_visual_specs() -> list[tuple[str, str, dict[str, Any]]]:
    """(title, type, fields) for one visual of every kind the report supports on the store table."""
    measure = _visual_measure_binding("TotalSales")
    cat = ("tbl_store", "cat")
    return [
        ("SwCard", "card", {"Fields": [measure]}),
        ("SwGauge", "gauge", {"Value": [measure]}),
        ("SwTable", "table", {"Fields": ["cat", measure]}),
        ("SwTablePlain", "table", {"Fields": ["cat", "val"]}),
        ("SwMatrix", "matrix", {"Rows": [cat], "Columns": [cat], "Values": [measure]}),
        ("SwColumn", "clusteredColumn", {"X-axis": [cat], "Y-axis": [measure]}),
        ("SwLine", "line", {"X-axis": [cat], "Y-axis": [measure]}),
        ("SwKpi", "kpi", {"Indicator": [measure], "Trend axis": [cat]}),
        ("SwScatter", "scatter", {"X-axis": [cat], "Y-axis": [measure]}),
        ("SwMap", "map", {"Location": [cat], "Latitude": [cat], "Longitude": [cat], "Size": [measure]}),
        ("SwShapeMap", "shapeMap", {"Location": [cat], "Values": [measure]}),
        ("SwSlicer", "slicer", {"Fields": [cat]}),
    ]


def _write_boundary_file(tmp_path: Path) -> Path:
    """A one-polygon GeoJSON file whose feature id matches the first category of the store table."""
    path = tmp_path / "sweep_boundary.geojson"
    path.write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"id": "cat_0"},
            "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        }],
    }), encoding="utf-8")
    return path


def _make_sweep_controller(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ProjectStore, StudioController, list[str]]:
    """Controller with a store candidate installed, one measure and one visual of each kind."""
    _block_dialogs(monkeypatch)
    ps, ctrl = _setup_visual_controller(tmp_path)
    page = ctrl._active_page()
    titles: list[str] = []
    for index, (title, v_type, fields) in enumerate(_sweep_visual_specs()):
        visual: dict[str, Any] = {
            "id": f"v_sweep_{index}", "title": title, "type": v_type,
            "table_id": "tbl_store", "fields": fields,
        }
        if v_type == "shapeMap":
            visual["shape_map_file"] = str(_write_boundary_file(tmp_path))
            visual["shape_map_key"] = "id"
        page["visuals"].append(visual)
        titles.append(title)
    return ps, ctrl, titles


def _assert_store_installed(ctrl: StudioController, titles: list[str]) -> None:
    """The sweep is only meaningful with the store candidate live and the visuals present."""
    candidate = ctrl._active_store_candidate
    assert isinstance(candidate, StoreCandidate), "store candidate is not installed"
    page_titles = [v.get("title") for v in ctrl._active_page()["visuals"]]
    assert titles and all(t in page_titles for t in titles)
    assert ctrl._project["model"]["measures"], "sweep fixture has no measure"


def _sweep_args(fn: Any) -> list[Any]:
    """Trivial arguments for a slot, from its annotations."""
    args: list[Any] = []
    for param in inspect.signature(fn).parameters.values():
        if param.name == "self" or param.default is not inspect.Parameter.empty:
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
    return args


def _call_sets(ctrl: StudioController, name: str, titles: list[str]) -> list[list[Any]]:
    """Argument lists to call the named slot with. Visual read slots get every visual title."""
    if name in VISUAL_READ_SLOTS:
        return [[title] for title in titles]
    if name == "_generate_dynamic_visual_series":
        return [[title] for title in titles if title in {"SwColumn", "SwLine"}]
    return [_sweep_args(getattr(ctrl, name))]


def _check_outcomes(name: str, outcomes: list[BaseException]) -> None:
    """Strict check of what a name raised against KNOWN_FUTURE.

    A listed name must raise the listed type (and nothing else); a listed name that no
    longer raises fails, so the entry has to be removed. An unlisted raise fails.
    """
    if name not in KNOWN_FUTURE:
        if outcomes:
            raise outcomes[0]
        return
    expected = KNOWN_FUTURE[name]
    if not outcomes:
        pytest.fail(f"{name} is in KNOWN_FUTURE but no longer raises; remove the entry")
    wrong = [exc for exc in outcomes if not isinstance(exc, expected)]
    if wrong:
        raise wrong[0]


def _traced(executed: set[str], call: Any) -> Any:
    """Wrap a call so the names of the controller functions it runs are collected.

    The sweep asserts that the Python body of every Property getter and Slot really ran,
    so a sweep that stops calling things cannot pass by doing nothing.
    """
    controller_file = Path(inspect.getsourcefile(StudioController) or "").resolve()

    def profiler(frame: Any, event: str, arg: Any) -> None:
        if event == "call" and Path(frame.f_code.co_filename).resolve() == controller_file:
            executed.add(frame.f_code.co_name)

    def wrapped() -> Any:
        previous = sys.getprofile()
        sys.setprofile(profiler)
        try:
            return call()
        finally:
            sys.setprofile(previous)

    return wrapped


def _run_calls(name: str, calls: list[Any]) -> int:
    """Run every call, collect the exceptions, apply the strict check, return the call count."""
    outcomes: list[BaseException] = []
    for call in calls:
        try:
            call()
        except Exception as exc:  # noqa: BLE001 - collected and judged by _check_outcomes
            outcomes.append(exc)
    _check_outcomes(name, outcomes)
    return len(calls)


@pytest.mark.parametrize("name", SWEEP_PROPERTIES)
def test_sweep_property(
    name: str, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every Property read through Python (QMetaProperty.read swallows exceptions)."""
    ps, ctrl, titles = _make_sweep_controller(tmp_path, monkeypatch)
    try:
        _assert_store_installed(ctrl, titles)
        executed: set[str] = set()
        reads: list[Any] = []
        count = _run_calls(name, [_traced(executed, lambda: reads.append(getattr(ctrl, name)))])
        assert count == 1
        if name in PYTHON_PROPERTIES and name not in KNOWN_FUTURE:
            assert name in executed, f"getter of property {name} did not run"
            assert len(reads) == 1
    finally:
        ps.close()


@pytest.mark.parametrize("name", SWEEP_SLOTS)
def test_sweep_slot(
    name: str, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every Slot that opens no dialog, called with trivial arguments (visual slots per visual)."""
    ps, ctrl, titles = _make_sweep_controller(tmp_path, monkeypatch)
    try:
        _assert_store_installed(ctrl, titles)
        fn = getattr(ctrl, name)
        arg_sets = _call_sets(ctrl, name, titles)
        called: list[list[Any]] = []

        def make_call(args: list[Any]) -> Any:
            def call() -> None:
                called.append(args)
                fn(*args)
            return call

        ran: set[str] = set()
        count = _run_calls(name, [_traced(ran, make_call(args)) for args in arg_sets])
        assert count == len(arg_sets) == len(called) >= 1
        assert name in ran, f"slot {name} did not run"
        if name in VISUAL_READ_SLOTS:
            assert len(called) == len(titles)
    finally:
        ps.close()


@pytest.mark.parametrize("name", EXTRA_CALLABLES)
def test_sweep_report_callable(
    name: str, qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-QML report entry points that read table rows: _refresh_report and the series builder."""
    ps, ctrl, titles = _make_sweep_controller(tmp_path, monkeypatch)
    try:
        _assert_store_installed(ctrl, titles)
        fn = getattr(ctrl, name)
        arg_sets = _call_sets(ctrl, name, titles) if name != "_refresh_report" else [[]]
        ran: set[str] = set()
        count = _run_calls(name, [_traced(ran, lambda args=args: fn(*args)) for args in arg_sets])
        assert count == len(arg_sets) >= 1
        assert name in ran, f"{name} did not run"
    finally:
        ps.close()


def test_sweep_inventory(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The names the sweep runs are exactly what the controller's meta-object declares."""
    ps, ctrl, titles = _make_sweep_controller(tmp_path, monkeypatch)
    try:
        _assert_store_installed(ctrl, titles)
        meta = ctrl.metaObject()
        live_slots = _slot_names(meta)
        live_props = _property_names(meta)

        assert SWEEP_PROPERTIES == live_props
        assert len(SWEEP_PROPERTIES) == meta.propertyCount() > 0
        # Only the QObject built-in objectName has no Python getter; 67 getters must be traced.
        assert set(SWEEP_PROPERTIES) - PYTHON_PROPERTIES == {"objectName"}
        assert len(PYTHON_PROPERTIES) == len(SWEEP_PROPERTIES) - 1
        # Every live slot is either swept or skipped for a stated reason; nothing is lost.
        assert set(live_slots) == set(SWEEP_SLOTS) | set(SKIPPED_SLOTS_REASONS)
        assert len(SWEEP_SLOTS) == len(live_slots) - len(SKIPPED_SLOTS_REASONS)
        assert len(SWEEP_SLOTS) == len(set(SWEEP_SLOTS))
        # Skip list, visual read slots, dynamic slots and extras must all be real names.
        for group in (SKIPPED_SLOTS_REASONS, VISUAL_READ_SLOTS, DYNAMIC_SLOTS):
            assert set(group) <= set(live_slots), set(group) - set(live_slots)
        assert all(callable(getattr(ctrl, name)) for name in EXTRA_CALLABLES)
        # KNOWN_FUTURE only names things the sweep actually calls.
        sweep_names = set(SWEEP_PROPERTIES) | set(SWEEP_SLOTS) | set(EXTRA_CALLABLES)
        assert set(KNOWN_FUTURE) <= sweep_names, set(KNOWN_FUTURE) - sweep_names
        # Every visual kind of the fixture exists, one visual read per slot per visual.
        assert len(titles) == len(_sweep_visual_specs()) == len(set(titles))
    finally:
        ps.close()


def test_known_future_is_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    """A KNOWN_FUTURE entry that stops raising fails; an unlisted raise fails; a wrong type fails."""
    monkeypatch.setitem(KNOWN_FUTURE, "fake_listed_quiet", LargeTableError)
    monkeypatch.setitem(KNOWN_FUTURE, "fake_listed_wrong", LargeTableError)

    with pytest.raises(pytest.fail.Exception, match="no longer raises"):
        _run_calls("fake_listed_quiet", [lambda: None])

    def raise_runtime() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        _run_calls("fake_listed_wrong", [raise_runtime])
    with pytest.raises(RuntimeError):
        _run_calls("fake_unlisted", [raise_runtime])

    def raise_large() -> None:
        raise LargeTableError("x")

    assert _run_calls("fake_listed_quiet", [raise_large]) == 1
    assert _run_calls("fake_unlisted_quiet", [lambda: None]) == 1
    with pytest.raises(LargeTableError):
        _run_calls("fake_unlisted", [raise_large])


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
        with patch.object(ctrl, "_store_tables_loaded", return_value=False):
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
        with patch.object(ctrl, "_store_tables_loaded", return_value=False):
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
        with patch.object(ctrl, "_store_tables_loaded", return_value=False):
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
        with patch.object(ctrl, "_store_tables_loaded", return_value=False):
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
        with patch.object(ctrl, "_store_tables_loaded", return_value=False):
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
        with patch.object(ctrl, "_store_tables_loaded", return_value=False):
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
        with patch.object(ctrl, "_store_tables_loaded", return_value=False):
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


def test_controller_import_does_not_load_the_store_stack() -> None:
    """Importing the controller must not pull duckdb or pyarrow into every app start.

    Baseline (commit before task 8, measured): duckdb and pyarrow are not loaded by
    ``import analytics_studio.controller``. They load only when a store is opened.
    """
    root = Path(__file__).resolve().parents[1]
    code = (
        "import sys\n"
        "import analytics_studio.controller\n"
        "print(','.join(m for m in ('duckdb', 'pyarrow', 'analytics_studio.store') if m in sys.modules))\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-400:]
    assert result.stdout.strip() == "", f"controller import loaded: {result.stdout.strip()}"


def test_large_table_error_is_one_class_everywhere() -> None:
    """The controller and the store package catch and raise the same LargeTableError class."""
    from analytics_studio import controller as controller_module
    from analytics_studio.store import candidate as candidate_module

    assert controller_module.LargeTableError is candidate_module.LargeTableError
    assert issubclass(candidate_module.LargeTableError, ValueError)


# ---------------------------------------------------------------------------
# Old behaviour on an ordinary (in-memory) table: the LargeTableError branches sit
# next to the branches that produce "Error", "—" and friends, and none of those
# results may change. No mocking here: a real 3-row table through the real
# controller and the real measure engine.
# ---------------------------------------------------------------------------


def _setup_ordinary_controller(tmp_path: Path, cell_error_value: bool = False) -> StudioController:
    rows: list[dict[str, Any]] = [
        {"cat": "A", "val": 1}, {"cat": "B", "val": 2}, {"cat": "C", "val": 3},
    ]
    if cell_error_value:
        from analytics_studio.power_query_values import PowerQueryCellError

        rows[1] = {"cat": "B", "val": PowerQueryCellError("Expression.Error", "bad cell")}
    candidate = ImportCandidate("csv", ["cat", "val"], rows, {}, [])
    ctrl = StudioController()
    ctrl._install_source(None, "s_ord", candidate)
    ctrl._project["data_sources"].append({"id": "s_ord", "name": "TOrd", "kind": "csv"})
    ctrl._project["model"]["tables"].append({
        "id": "tbl_ord", "source_id": "s_ord", "name": "TOrd",
        "column_types": {"cat": "text", "val": "number"},
    })
    for name, expression in (
        ("Good", "SUM(TOrd[val])"),
        ("Bad", "SUM(TOrd[nope])"),
        ("Blank", "IF(FALSE(), 1)"),
    ):
        ctrl._project["model"]["measures"].append({
            "name": name, "expression": expression, "home_table_id": "tbl_ord",
        })
    ctrl._refresh_model_view()
    page = ctrl._active_page()
    good, bad, blank = (_visual_measure_binding(n) for n in ("Good", "Bad", "Blank"))
    cat = ("tbl_ord", "cat")
    val = ("tbl_ord", "val")
    boundary = _write_boundary_file(tmp_path)
    specs: list[tuple[str, str, dict[str, Any]]] = [
        ("GaugeGood", "gauge", {"Value": [good]}),
        ("GaugeBad", "gauge", {"Value": [bad]}),
        ("CardGood", "card", {"Fields": [good]}),
        ("CardBad", "card", {"Fields": [bad]}),
        ("CardBlank", "card", {"Fields": [blank]}),
        ("TableGood", "table", {"Fields": ["cat", good]}),
        ("TableBad", "table", {"Fields": ["cat", bad]}),
        ("MatrixGood", "matrix", {"Rows": [cat], "Columns": [cat], "Values": [good]}),
        ("MatrixBad", "matrix", {"Rows": [cat], "Columns": [cat], "Values": [bad]}),
        ("MatrixCell", "matrix", {"Rows": [cat], "Columns": [cat], "Values": [val]}),
        ("ColumnGood", "clusteredColumn", {"X-axis": [cat], "Y-axis": [good]}),
        ("ColumnBad", "clusteredColumn", {"X-axis": [cat], "Y-axis": [bad]}),
        ("MapGood", "shapeMap", {"Location": [cat], "Values": [good]}),
        ("MapBad", "shapeMap", {"Location": [cat], "Values": [bad]}),
    ]
    for index, (title, v_type, fields) in enumerate(specs):
        visual: dict[str, Any] = {
            "id": f"v_ord_{index}", "title": title, "type": v_type,
            "table_id": "tbl_ord", "fields": fields,
        }
        if v_type == "shapeMap":
            visual["shape_map_file"] = str(boundary)
            visual["shape_map_key"] = "id"
        page["visuals"].append(visual)
    return ctrl


def test_ordinary_gauge_keeps_old_results(qapp: QApplication, tmp_path: Path) -> None:
    """Gauge branch: a good measure gives its value; a bad one gives neutral values and no status."""
    ctrl = _setup_ordinary_controller(tmp_path)
    ctrl._set_status("")
    good = ctrl.visualGaugeData("GaugeGood")
    assert good["value"] == 6.0 and good["has_value"] is True
    ctrl._set_status("")
    bad = ctrl.visualGaugeData("GaugeBad")
    assert bad["value"] == 0.0 and bad["has_value"] is False
    assert ctrl._status_message == ""


def test_ordinary_card_keeps_old_results(qapp: QApplication, tmp_path: Path) -> None:
    """Card branch: value text is the number, "Error" for a bad measure, "—" for a blank one."""
    ctrl = _setup_ordinary_controller(tmp_path)
    assert ctrl.visualCardData("CardGood")["value"] == "6"
    assert ctrl.visualCardData("CardBad")["value"] == "Error"
    assert ctrl.visualCardData("CardBlank")["value"] == "—"
    assert ctrl.visualCardData("CardBad")["highlight_value"] == ""


def test_ordinary_card_highlight_keeps_old_results(qapp: QApplication, tmp_path: Path) -> None:
    """Card highlight branch: "1" for a good measure, "Error" for a bad one, "—" for a blank one."""
    ctrl = _setup_ordinary_controller(tmp_path)
    for target in ("CardGood", "CardBad", "CardBlank"):
        ctrl.set_visual_interaction("ColumnGood", target, "highlight")
    ctrl._cross_filters["ColumnGood"] = ["A"]
    good = ctrl.visualCardData("CardGood")
    bad = ctrl.visualCardData("CardBad")
    blank = ctrl.visualCardData("CardBlank")
    assert good["has_highlights"] is True
    assert (good["highlight_value"], bad["highlight_value"], blank["highlight_value"]) == ("1", "Error", "—")


def test_ordinary_table_visual_keeps_old_results(qapp: QApplication, tmp_path: Path) -> None:
    """Table visual branch: real rows for a good measure, a "could not be evaluated" error for a bad one."""
    ctrl = _setup_ordinary_controller(tmp_path)
    good = ctrl.visualTableData("TableGood")
    assert [row["values"] for row in good["rows"]] == [["A", "1"], ["B", "2"], ["C", "3"]]
    bad = ctrl.visualTableData("TableBad")
    assert bad["rows"] == [] and bad["total_rows"] == 0
    assert bad["error"].startswith("Measure 'Bad' could not be evaluated:")


def test_ordinary_matrix_keeps_old_results(qapp: QApplication, tmp_path: Path) -> None:
    """Matrix branches: good cells, "Error" cells for a bad measure, "Error" for a cell-error value."""
    ctrl = _setup_ordinary_controller(tmp_path)
    good = ctrl.visualMatrixData("MatrixGood")
    assert [row["values"] for row in good["rows"]] == [
        ["A", "1", "", ""], ["B", "", "2", ""], ["C", "", "", "3"],
    ]
    bad = ctrl.visualMatrixData("MatrixBad")
    assert [row["values"] for row in bad["rows"]] == [
        ["A", "Error", "", ""], ["B", "", "Error", ""], ["C", "", "", "Error"],
    ]
    cell_ctrl = _setup_ordinary_controller(tmp_path, cell_error_value=True)
    cells = cell_ctrl.visualMatrixData("MatrixCell")
    assert [row["values"] for row in cells["rows"]] == [
        ["A", "1", "", ""], ["B", "", "Error", ""], ["C", "", "", "3"],
    ]


def test_ordinary_series_keeps_old_results(qapp: QApplication, tmp_path: Path) -> None:
    """Dynamic series branch: points for a good measure, an empty list and no status for a bad one."""
    ctrl = _setup_ordinary_controller(tmp_path)
    good = ctrl._generate_dynamic_visual_series("ColumnGood")
    assert [(p["label"], p["value"]) for p in good] == [("A", 1.0), ("B", 2.0), ("C", 3.0)]
    ctrl._set_status("")
    assert ctrl._generate_dynamic_visual_series("ColumnBad") == []
    assert ctrl._status_message == ""


def test_ordinary_shape_map_keeps_old_results(qapp: QApplication, tmp_path: Path) -> None:
    """Shape map branch: a bad measure leaves the metric empty and sets no status."""
    ctrl = _setup_ordinary_controller(tmp_path)
    ctrl._set_status("")
    bad = ctrl.visualShapeMapData("MapBad")
    assert ctrl._status_message == ""
    assert bad and all(item["value"] is None for item in bad)


# The store-candidate branches below are reached with mocks. A real store table raises
# earlier, inside _report_filter_context (the KNOWN_FUTURE entries), so these branches
# cannot be reached for real until tasks 9 and 10 land.


def test_site_7_card_highlight_and_empty_message(qapp: QApplication, tmp_path: Path) -> None:
    """Card highlight branch with a LargeTableError: message shown, empty message gets the fallback text."""
    ps, ctrl = _setup_visual_controller(tmp_path)
    try:
        with patch.object(ctrl, "_store_tables_loaded", return_value=False):
            m_bind = _visual_measure_binding("TotalSales")
            page = ctrl._active_page()
            page["visuals"].append({
                "id": "v_hl_card", "title": "HlCard", "type": "card", "table_id": "tbl_store",
                "fields": {"Fields": [m_bind]},
            })
            page["visuals"].append({
                "id": "v_hl_src", "title": "HlSource", "type": "clusteredColumn", "table_id": "tbl_store",
                "fields": {"X-axis": [("tbl_store", "cat")], "Y-axis": [m_bind]},
            })
            mock_rows = [{"cat": "A", "val": "1"}]
            mock_context = (
                {"tbl_store": mock_rows},
                [{"id": "tbl_store", "name": "TStore", "headers": ["cat", "val"], "rows": mock_rows}],
                set(),
            )
            fallback = "table is stored in the large-data store"
            with patch.object(ctrl, "_report_filter_context", return_value=mock_context):
                # set_visual_interaction refreshes the report, which raises for a real store table.
                ctrl.set_visual_interaction("HlSource", "HlCard", "highlight")
                ctrl._cross_filters["HlSource"] = ["cat_0"]
                with patch.object(ctrl, "_measure_value_for_visual_group", side_effect=LargeTableError("highlight refused")):
                    res = ctrl.visualCardData("HlCard")
                    assert res["has_highlights"] is True
                    assert res["value"] == "highlight refused"
                    assert res["highlight_value"] == "highlight refused"
                with patch.object(ctrl, "_measure_value_for_visual_group", side_effect=LargeTableError("")):
                    res_empty = ctrl.visualCardData("HlCard")
                    assert res_empty["value"] == fallback
                    assert res_empty["highlight_value"] == fallback
    finally:
        ps.close()
