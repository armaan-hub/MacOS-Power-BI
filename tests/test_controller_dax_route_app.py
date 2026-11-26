"""Real-app test of the large-table DAX route (Stage C2a): measures, cards, edit and delete on a 300,000-row table.

The real controller imports a 300,000-row CSV through the real large-import path, so the table lands in the
store. The same rows are loaded into a second controller in memory (the row limit is raised for that one), and
every card text must be identical. Only the file dialogs and the confirmation boxes are patched.
"""

from __future__ import annotations

import csv
import datetime
import os
import random
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from analytics_studio import file_import, transformations
from analytics_studio.controller import StudioController
from analytics_studio.file_import import parse_file
from analytics_studio.measures import normalize_measure
from analytics_studio.store.dax_route import MIXED_MODEL_REASON
from tests.test_controller_store_real_app_300k import _FakeLargeDialog, _wait_for_job

ROWS = 300_000
HEADERS = ["id", "region", "product", "amount", "qty", "order_date", "is_paid"]
REGIONS = ["North", "South", "East", "West", "Central", "Coastal", "Inland", "Remote"]
IMPORT_LIMIT_SECONDS = 240.0

CATALOG: list[tuple[str, str]] = [
    ("Total Amount", "SUM(sales[amount])"),
    ("Avg Amount", "AVERAGE(sales[amount])"),
    ("Min Amount", "MIN(sales[amount])"),
    ("Max Amount", "MAX(sales[amount])"),
    ("Total Qty", "SUM(sales[qty])"),
    ("Avg Qty", "AVERAGE(sales[qty])"),
    ("Min Qty", "MIN(sales[qty])"),
    ("Max Qty", "MAX(sales[qty])"),
    ("Amount Count", "COUNT(sales[amount])"),
    ("Region Count A", "COUNTA(sales[region])"),
    ("Row Count", "COUNTROWS(sales)"),
    ("Amount Blank", "COUNTBLANK(sales[amount])"),
    ("Products", "DISTINCTCOUNT(sales[product])"),
    ("Regions", "DISTINCTCOUNT(sales[region])"),
    ("Paid Flags", "DISTINCTCOUNT(sales[is_paid])"),
    ("First Order", "MIN(sales[order_date])"),
    ("Last Order", "MAX(sales[order_date])"),
    ("East Amount", "CALCULATE(SUM(sales[amount]), sales[region] = \"East\")"),
    ("Two Regions", "CALCULATE(SUM(sales[amount]), sales[region] IN {\"East\", \"West\"})"),
    ("Big Orders", "CALCULATE(COUNTROWS(sales), sales[qty] > 5)"),
    ("P017 Qty", "CALCULATE(SUM(sales[qty]), sales[product] = \"P017\")"),
    ("Recent Orders", "CALCULATE(COUNTROWS(sales), sales[order_date] >= DATE(2024, 1, 1))"),
    ("Avg Large", "CALCULATE(AVERAGE(sales[amount]), sales[amount] >= 100)"),
    ("Last Qty 3", "CALCULATE(MAX(sales[order_date]), sales[qty] = 3)"),
    ("West Not 3", "CALCULATE(SUM(sales[amount]), sales[qty] <> 3, sales[region] = \"West\")"),
    ("Same Total", "[Total Amount]"),
    ("North Total", "CALCULATE([Total Amount], sales[region] = \"North\")"),
    ("North Products", "CALCULATE(DISTINCTCOUNT(sales[product]), sales[region] = \"North\")"),
    ("Blank Regions", "CALCULATE(COUNTBLANK(sales[region]), sales[qty] > 0)"),
    ("Qty 3 or 4", "CALCULATE(SUM(sales[qty]), sales[qty] = 3 || sales[qty] = 4)"),
    # Aliases (C2a2): a measure whose whole body is another measure. These are allowed because the outer filter is on
    # another column than the inner one, and they must agree with the engine.
    ("East Qty", "CALCULATE(SUM(sales[qty]), sales[region] = \"East\")"),
    ("East Alias", "[East Qty]"),
    ("East Alias 2", "[East Alias]"),
    ("East Alias Big", "CALCULATE([East Alias 2], sales[qty] > 3)"),
]
REFUSED: list[tuple[str, str]] = [
    # Same column filtered inside the alias chain and outside: the engine replaces the inner filter, the store ANDs.
    ("Alias Same Column", "CALCULATE([East Alias], sales[region] = \"West\")"),
    ("Alias Same Column 2", "CALCULATE([East Alias 2], sales[region] = \"West\")"),
    ("Bad All", "CALCULATE(SUM(sales[amount]), ALL(sales))"),
    ("Bad Iterator", "SUMX(sales, sales[amount] * 2)"),
    ("Bad Ratio", "SUM(sales[amount]) / SUM(sales[qty])"),
]


def generate_csv(path: Path, rows: int = ROWS, seed: int = 20260126) -> Path:
    rnd = random.Random(seed)
    base = datetime.date(2022, 1, 1)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS)
        for i in range(rows):
            region = "" if rnd.random() < 0.02 else REGIONS[rnd.randrange(8)]
            amount = "" if rnd.random() < 0.05 else f"{rnd.randrange(-20_000, 2_000_000) / 100:.2f}"
            qty = "" if rnd.random() < 0.05 else str(rnd.randrange(-2, 12))
            day = (base + datetime.timedelta(days=rnd.randrange(0, 1500))).isoformat()
            paid = "TRUE" if rnd.random() < 0.6 else "FALSE"
            writer.writerow([i + 1, region, f"P{rnd.randrange(200):03d}", amount, qty, day, paid])
    return path


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(["Analytics Studio dax route tests"])


def make_store_controller(
    tmp_path: Path,
    rows: list[list[Any]],
    *,
    headers: tuple[str, ...] = ("id", "region", "product", "qty", "amt", "neg", "pay", "paid"),
    stem: str = "t",
) -> tuple[StudioController, Any]:
    """A real controller whose table (file `<stem>.csv`) went through the real large-import path."""
    path = tmp_path / f"{stem}.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    return import_store_controller(path, tmp_path)


def import_store_controller(path: Path, appdata_parent: Path) -> tuple[StudioController, Any]:
    controller = StudioController()
    appdata = appdata_parent / "appdata_store"
    appdata.mkdir(exist_ok=True)
    controller._effective_app_data_dir = lambda: str(appdata)  # type: ignore[method-assign]
    with patch.object(file_import, "MAX_DATA_ROWS", 500), \
            patch("analytics_studio.import_preview_dialog.FileImportPreviewDialog", new=_FakeLargeDialog), \
            patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes), \
            patch.object(StudioController, "_run_store_summary_dialog", lambda self, candidate: None):
        assert controller._import_file_path(path) is True
        _wait_for_job(controller, IMPORT_LIMIT_SECONDS)
    assert controller._store_tables_loaded()
    assert controller._project_store is not None
    return controller, controller._project_store


@pytest.fixture(scope="module")
def big_csv(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return generate_csv(tmp_path_factory.mktemp("dax_route_300k") / "sales.csv")


@pytest.fixture(scope="module")
def store_app(qapp: QApplication, big_csv: Path, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    started = time.monotonic()
    controller, project_store = import_store_controller(big_csv, tmp_path_factory.mktemp("dax_route_store"))
    state: dict[str, Any] = {"controller": controller, "import_s": time.monotonic() - started}
    state["table"] = str(controller._project["model"]["tables"][0]["name"])
    yield state
    controller._close_project_store()


@pytest.fixture(scope="module")
def memory_twin(qapp: QApplication, big_csv: Path, tmp_path_factory: pytest.TempPathFactory) -> StudioController:
    """The same 300,000 rows in memory: the row limit is raised for this one controller only."""
    controller = StudioController()
    appdata = tmp_path_factory.mktemp("dax_route_twin")
    controller._effective_app_data_dir = lambda: str(appdata)  # type: ignore[method-assign]
    with patch.object(file_import, "MAX_DATA_ROWS", 1_000_000), \
            patch.object(file_import, "MAX_SOURCE_BYTES", 1024 * 1024 * 1024), \
            patch.object(file_import, "MAX_CELLS", 100_000_000), \
            patch.object(transformations, "MAX_DATA_ROWS", 1_000_000), \
            patch.object(transformations, "MAX_CELLS", 100_000_000):
        candidate = parse_file(big_csv)
        errors: list[str] = []
        with patch.object(QMessageBox, "critical", lambda *args: errors.append(str(args[2]))):
            imported = controller._commit_import(big_csv, candidate)
        assert imported, errors
    assert not controller._store_tables_loaded()
    return controller


def _measure_text(controller: StudioController, name: str) -> str:
    return controller._measure_values.get(name, "<missing>")


def test_store_table_is_imported_as_store(store_app: dict[str, Any]) -> None:
    controller = store_app["controller"]
    assert controller.rowCount == ROWS
    assert store_app["table"] == "sales"
    types = controller._project["model"]["tables"][0]["column_types"]
    assert types["amount"] == "decimal_number" and types["qty"] == "whole_number"
    assert types["order_date"] == "date" and types["region"] == "text"


def test_thirty_measures_match_the_in_memory_engine(
    store_app: dict[str, Any], memory_twin: StudioController, monkeypatch: pytest.MonkeyPatch
) -> None:
    from analytics_studio.store import dax_route

    # 30 cards at 300,000 rows take about 1.4 s, close to the 1.5 s refresh deadline; this test compares VALUES,
    # so the deadline is lifted here (the 10-card test below keeps the real one).
    monkeypatch.setattr(dax_route, "refresh_deadline", lambda: time.monotonic() + 120.0)
    controller = store_app["controller"]
    assert len(CATALOG) == 34  # the 30 of the brief plus 4 alias measures
    created_started = time.monotonic()
    for name, expression in CATALOG:
        assert controller.create_measure(name, expression) is True, (name, controller.statusMessage)
    create_s = time.monotonic() - created_started
    # The twin gets the same 30 measures straight into its project (one refresh, not 30).
    aid = memory_twin._active_model_table_id()
    twin_measures = [normalize_measure(name, expression, home_table_id=aid) for name, expression in CATALOG]
    memory_twin._project["model"]["measures"] = twin_measures
    twin_started = time.monotonic()
    memory_twin._refresh_report()
    twin_s = time.monotonic() - twin_started

    store_started = time.monotonic()
    controller._refresh_report()
    store_s = time.monotonic() - store_started
    differences = []
    for name, _ in CATALOG:
        got, want = _measure_text(controller, name), _measure_text(memory_twin, name)
        if got != want:
            differences.append((name, got, want))
    assert controller._measure_errors == {}
    assert not differences, differences
    identical = len(CATALOG) - len(differences)
    print(f"[measured] {identical} of {len(CATALOG)} card texts identical to the in-memory engine")
    print(f"[measured] 30 create_measure calls (each refreshes the cards): {create_s:.2f} s")
    print(f"[measured] GUI-thread card refresh, 30 cards, {ROWS:,} rows: {store_s:.2f} s (in-memory twin {twin_s:.2f} s)")
    state_sample = {name: _measure_text(controller, name) for name, _ in CATALOG[:5]}
    print(f"[measured] sample values {state_sample}")


def test_ten_cards_gui_thread_time(store_app: dict[str, Any]) -> None:
    controller = store_app["controller"]
    full = list(controller._project["model"]["measures"])
    assert len(full) >= 10
    controller._project["model"]["measures"] = full[:10]
    try:
        times = []
        for _ in range(3):
            started = time.monotonic()
            controller._refresh_report()
            times.append(time.monotonic() - started)
        assert controller._measure_errors == {}
        assert len(controller._measure_values) == 10
        print(f"[measured] GUI-thread card refresh, 10 cards, {ROWS:,} rows: "
              f"{', '.join(f'{t:.3f}' for t in times)} s (3 runs)")
        started = time.monotonic()
        controller._refresh_report_async()
        print(f"[measured] same through _refresh_report_async: {time.monotonic() - started:.3f} s")
        assert len(controller._measure_values) == 10
    finally:
        controller._project["model"]["measures"] = full
        controller._refresh_report()


def test_refused_measures_name_the_measure_and_a_reason(store_app: dict[str, Any]) -> None:
    controller = store_app["controller"]
    before = [str(m["name"]) for m in controller._project["model"]["measures"]]
    for name, expression in REFUSED:
        assert controller.create_measure(name, expression) is False
        status = controller.statusMessage
        assert name in status, status
        assert "cannot be computed on a large table yet" in status, status
        assert "not available for large-data tables" not in status
    assert [str(m["name"]) for m in controller._project["model"]["measures"]] == before


def test_update_and_remove_follow_the_store(store_app: dict[str, Any]) -> None:
    controller = store_app["controller"]
    controller._refresh_report()
    old_total = _measure_text(controller, "Total Qty")
    assert controller.update_measure("Total Qty", "Total Qty", "SUM(sales[qty]) ", description="x") is True
    assert _measure_text(controller, "Total Qty") == old_total
    assert controller.update_measure(
        "Total Qty", "Total Qty", "CALCULATE(SUM(sales[qty]), sales[qty] > 5)"
    ) is True
    assert _measure_text(controller, "Total Qty") != old_total
    # An edit the store cannot compute is blocked and nothing changes.
    kept = _measure_text(controller, "Total Qty")
    assert controller.update_measure("Total Qty", "Total Qty", "SUMX(sales, sales[qty])") is False
    assert "Total Qty cannot be computed on a large table yet" in controller.statusMessage
    assert _measure_text(controller, "Total Qty") == kept
    # A measure used by another measure cannot be removed; an unused one can.
    assert controller.remove_measure("Total Amount") is False
    assert "Could not delete measure" in controller.statusMessage
    assert "Total Amount" in controller._measure_values
    assert controller.remove_measure("Min Qty") is True
    assert "Min Qty" not in controller._measure_values
    assert "Min Qty" not in [str(m["name"]) for m in controller._project["model"]["measures"]]
    # A rename keeps the dependents computable only when they still resolve: a rename of a used measure is refused.
    assert controller.update_measure("Total Amount", "Total Amt Renamed", "SUM(sales[amount])") is False
    assert "Could not update measure" in controller.statusMessage


def test_dialog_slots_open_for_a_store_table(store_app: dict[str, Any]) -> None:
    from analytics_studio import controller as controller_module

    controller = store_app["controller"]
    shown: list[dict[str, Any]] = []

    class FakeDialog:
        def __init__(self, headers: Any, names: Any, **kwargs: Any) -> None:
            shown.append(kwargs)
            self.measure = None

        def exec(self) -> int:
            return 0

    with patch.object(controller_module, "MeasureDialog", FakeDialog):
        assert controller.new_measure_dialog() is False  # the dialog opened and was cancelled
        assert controller.editMeasure("Total Amount") is False
    assert len(shown) == 2
    preview = shown[0]["preview_callback"]
    assert preview("Draft", "SUM(sales[qty])") != "—"
    with pytest.raises(Exception, match="cannot be computed on a large table yet"):
        preview("Draft2", "CALCULATE(SUM(sales[qty]), ALL(sales))")
    done: list[str] = []
    shown[0]["preview_async_callback"]("Draft3", "COUNTROWS(sales)", done.append)
    assert done and done[0].startswith("300,000")
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        assert controller.deleteMeasure("Max Qty") is True
    assert "Max Qty" not in controller._measure_values


def test_store_plus_ordinary_table_is_refused_as_today(qapp: QApplication, tmp_path: Path) -> None:
    rows = [[i, "East", "P01", i % 7, f"{i}.50", "-1.00", "2024-01-01", "TRUE"] for i in range(1, 801)]
    controller, project_store = make_store_controller(tmp_path, rows)
    try:
        assert controller.create_measure("Qty Sum", "SUM(t[qty])") is True
        assert controller._measure_values["Qty Sum"] != "—"
        controller._project["model"]["tables"].append(
            {"id": "ordinary", "source_id": "ordinary", "name": "Small", "column_types": {"a": "text"}}
        )
        controller._reset_silent_refusal_notice()
        controller._refresh_report()
        assert controller._measure_values == {}
        assert controller.create_measure("Another", "COUNTROWS(t)") is False
        assert controller._large_data_refusal("DAX measures") in controller.statusMessage
        assert MIXED_MODEL_REASON in controller.statusMessage
        assert controller.remove_measure("Qty Sum") is False
        assert controller._large_data_refusal("DAX measures") in controller.statusMessage
    finally:
        controller._close_project_store()


def test_store_with_a_relationship_is_refused_as_today(qapp: QApplication, tmp_path: Path) -> None:
    rows = [[i, "East", "P01", i % 7, f"{i}.50", "-1.00", "2024-01-01", "TRUE"] for i in range(1, 801)]
    controller, project_store = make_store_controller(tmp_path, rows)
    try:
        controller._project["model"]["relationships"] = [{"id": "r"}]
        assert controller.create_measure("Qty Sum", "SUM(t[qty])") is False
        assert controller._large_data_refusal("DAX measures") in controller.statusMessage
        controller._reset_silent_refusal_notice()
        controller._refresh_report()
        assert controller._measure_values == {}
    finally:
        controller._close_project_store()


def test_busy_store_shows_a_card_refusal_not_a_value(qapp: QApplication, tmp_path: Path) -> None:
    rows = [[i, "East", "P01", i % 7, f"{i}.50", "-1.00", "2024-01-01", "TRUE"] for i in range(1, 801)]
    controller, project_store = make_store_controller(tmp_path, rows)
    try:
        assert controller.create_measure("Qty Sum", "SUM(t[qty])") is True
        with project_store.job():
            controller._refresh_report()
        assert "Qty Sum" not in controller._measure_values
        assert "busy" in controller._measure_errors["Qty Sum"]
        controller._refresh_report()
        assert controller._measure_values["Qty Sum"] != "—" and controller._measure_errors == {}
    finally:
        controller._close_project_store()


# ---------------------------------------------------------------------------------------------------
# Mutant proofs for the controller rules (small 800-row table: fast). Each patched rule must make its check fail.
# ---------------------------------------------------------------------------------------------------
def _small_rows() -> list[list[Any]]:
    return [[i, "East", "P01", i % 7, f"{i}.50", "-1.00", "2024-01-01", "TRUE"] for i in range(1, 801)]


def _check_refused_create_is_blocked(controller: StudioController) -> None:
    assert controller.create_measure("Bad All", "CALCULATE(SUM(t[qty]), ALL(t))") is False
    assert "Bad All" not in [str(m["name"]) for m in controller._project["model"]["measures"]]


def _check_dependent_blocks_delete(controller: StudioController) -> None:
    assert controller.create_measure("Base Qty", "SUM(t[qty])") is True
    assert controller.create_measure("Uses Base", "[Base Qty]") is True
    assert controller.remove_measure("Base Qty") is False
    assert "Base Qty" in [str(m["name"]) for m in controller._project["model"]["measures"]]


def _check_refusal_is_an_error_not_a_value(controller: StudioController) -> None:
    assert controller.create_measure("Qty Sum", "SUM(t[qty])") is True
    controller._project["model"]["measures"].append(
        {"name": "Forced Bad", "expression": "CALCULATE(SUM(t[qty]), ALL(t))", "home_table_id": ""}
    )
    controller._refresh_report()
    assert "Forced Bad" not in controller._measure_values and "Forced Bad" not in controller._kpis
    assert "Forced Bad cannot be computed on a large table yet" in controller._measure_errors["Forced Bad"]
    assert controller._measure_values["Qty Sum"] != "—"


@pytest.mark.parametrize("check", [
    _check_refused_create_is_blocked, _check_dependent_blocks_delete, _check_refusal_is_an_error_not_a_value,
])
def test_controller_rule_checks_pass_on_the_real_code(qapp: QApplication, tmp_path: Path, check: Any) -> None:
    controller, _ = make_store_controller(tmp_path, _small_rows())
    try:
        check(controller)
    finally:
        controller._close_project_store()


def test_mutant_create_does_not_validate_with_the_store(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(StudioController, "_validate_store_measures", lambda self, measures, names: None)
    controller, _ = make_store_controller(tmp_path, _small_rows())
    try:
        with pytest.raises(AssertionError):
            _check_refused_create_is_blocked(controller)
    finally:
        controller._close_project_store()


def test_mutant_delete_ignores_dependents(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from analytics_studio.store import dax_route

    monkeypatch.setattr(dax_route, "measures_depending_on", lambda measures, names: [])
    controller, _ = make_store_controller(tmp_path, _small_rows())
    try:
        with pytest.raises(AssertionError):
            _check_dependent_blocks_delete(controller)
    finally:
        controller._close_project_store()


def test_mutant_refusal_written_as_a_value(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from analytics_studio.store.dax_route import RouteRefusal, StoreAnswer

    real = StudioController._route_store_measure

    def refusal_as_zero(self: StudioController, name: str, **kwargs: Any) -> Any:
        out = real(self, name, **kwargs)
        return StoreAnswer("scalar", None, [], 0.0, "t") if isinstance(out, RouteRefusal) else out

    controller, _ = make_store_controller(tmp_path, _small_rows())
    try:
        monkeypatch.setattr(StudioController, "_route_store_measure", refusal_as_zero)
        with pytest.raises(AssertionError):
            _check_refusal_is_an_error_not_a_value(controller)
    finally:
        controller._close_project_store()


def test_mutant_store_project_falls_back_to_the_memory_path(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the shape gate said 'not S1' for a store project, the card path would show no values at all."""
    controller, _ = make_store_controller(tmp_path, _small_rows())
    try:
        assert controller.create_measure("Qty Sum", "SUM(t[qty])") is True
        assert controller._measure_values["Qty Sum"] != "—"
        monkeypatch.setattr(StudioController, "_store_s1", lambda self: False)
        controller._refresh_report()
        assert controller._measure_values == {}
        monkeypatch.undo()
        controller._refresh_report()
        assert controller._measure_values["Qty Sum"] != "—"
    finally:
        controller._close_project_store()


# ---------------------------------------------------------------------------------------------------
# C2a2: refresh deadline, BLANK card, exceptions, Parquet, closure cost
# ---------------------------------------------------------------------------------------------------
def _slow_plan_execute(self: Any, store: Any) -> Any:
    return store.execute("SELECT count(*) FROM range(10000000000)")


def _check_refresh_stops_at_the_shared_deadline(controller: StudioController) -> None:
    from analytics_studio.store import dax_route

    assert controller.create_measure("M One", "SUM(t[qty])") is True
    for name in ("M Two", "M Three", "M Four"):
        assert controller.create_measure(name, "COUNTROWS(t)") is True
    with patch.object(dax_route, "refresh_deadline", lambda: time.monotonic() + 0.3), \
            patch("analytics_studio.store.dax_sql.MeasurePlan.execute", _slow_plan_execute):
        started = time.monotonic()
        controller._refresh_report()
        elapsed = time.monotonic() - started
    assert elapsed < 0.9, elapsed
    assert controller._measure_values == {}
    assert "took longer than" in controller._measure_errors["M One"]
    for name in ("M Two", "M Three", "M Four"):
        assert controller._measure_errors[name] == dax_route.DEADLINE_MESSAGE


def test_card_refresh_stops_at_the_shared_deadline(qapp: QApplication, tmp_path: Path) -> None:
    controller, _ = make_store_controller(tmp_path, _small_rows())
    try:
        _check_refresh_stops_at_the_shared_deadline(controller)
    finally:
        controller._close_project_store()


def test_mutant_card_refresh_passes_no_deadline(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = StudioController._route_store_measure

    controller, _ = make_store_controller(tmp_path, _small_rows())
    try:
        def no_deadline(self: StudioController, name: str, **kwargs: Any) -> Any:
            kwargs["deadline"] = None
            return real(self, name, **kwargs)

        monkeypatch.setattr(StudioController, "_route_store_measure", no_deadline)
        with pytest.raises(AssertionError):
            _check_refresh_stops_at_the_shared_deadline(controller)
    finally:
        controller._close_project_store()


def _check_blank_card_is_a_dash(controller: StudioController) -> None:
    assert controller.create_measure("Nothing", "CALCULATE(SUM(t[qty]), t[qty] = 99999)") is True
    assert controller._measure_values["Nothing"] == "—"
    assert controller._kpis["Nothing"] == "—"
    assert controller.create_measure("Rows", "COUNTROWS(t)") is True
    assert controller._measure_values["Rows"] == "800"


def test_blank_store_value_shows_a_dash_not_zero(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    controller, _ = make_store_controller(tmp_path, _small_rows())
    try:
        _check_blank_card_is_a_dash(controller)
    finally:
        controller._close_project_store()
    mutant_dir = tmp_path / "mutant"
    mutant_dir.mkdir()
    monkeypatch.setattr(
        StudioController, "_store_answer_text",
        staticmethod(lambda answer: "0" if answer.value is None else "7"),
    )
    controller, _ = make_store_controller(mutant_dir, _small_rows())
    try:
        with pytest.raises(AssertionError):
            _check_blank_card_is_a_dash(controller)
    finally:
        controller._close_project_store()


def _check_exception_in_execute_is_a_refusal(controller: StudioController) -> None:
    assert controller.create_measure("Qty Sum", "SUM(t[qty])") is True
    assert controller.create_measure("Rows", "COUNTROWS(t)") is True
    real = None

    def raising(self: Any, store: Any) -> Any:
        if "qty" in self.sql:
            raise RuntimeError("programmer error")
        return real(self, store)

    from analytics_studio.store import dax_sql

    real = dax_sql.MeasurePlan.execute
    with patch.object(dax_sql.MeasurePlan, "execute", raising):
        controller._refresh_report()
        assert "RuntimeError" in controller._measure_errors["Qty Sum"]
        assert "Qty Sum" not in controller._measure_values
        assert controller._measure_values["Rows"] == "800"
        before = [str(m["name"]) for m in controller._project["model"]["measures"]]
        assert controller.create_measure("More Qty", "SUM(t[qty])") is False
        assert "could not be computed" in controller.statusMessage
        assert [str(m["name"]) for m in controller._project["model"]["measures"]] == before
        assert "RuntimeError" in _preview_text(controller, "Draft", "SUM(t[qty])")


def test_exception_in_the_store_path_is_a_refusal_everywhere(qapp: QApplication, tmp_path: Path) -> None:
    controller, _ = make_store_controller(tmp_path, _small_rows())
    try:
        _check_exception_in_execute_is_a_refusal(controller)
    finally:
        controller._close_project_store()


def _preview_text(controller: StudioController, name: str, expression: str) -> str:
    try:
        return controller._preview_measure_expression(name, expression)
    except Exception as exc:
        return str(exc)


def test_parquet_store_table_says_so_first(qapp: QApplication, tmp_path: Path) -> None:
    controller, _ = make_store_controller(tmp_path, _small_rows())
    try:
        assert controller.create_measure("Qty Sum", "SUM(t[qty])") is True
        for candidate in controller._loaded_candidates.values():
            candidate.kind = "parquet"
        for source in controller._project["data_sources"]:
            source["kind"] = "parquet"
        controller._refresh_report()
        sentence = "tables loaded from Parquet files cannot compute measures yet"
        assert sentence in controller._measure_errors["Qty Sum"]
        assert "Qty Sum" not in controller._measure_values
        assert controller.create_measure("Other", "CALCULATE(SUM(t[qty]), ALL(t))") is False
        assert sentence in controller.statusMessage
        assert "ALL" not in controller.statusMessage
    finally:
        controller._close_project_store()


def test_eight_decimal_cards_at_300k_rows_all_answer(
    qapp: QApplication, tmp_path_factory: pytest.TempPathFactory
) -> None:
    # The timing against the real deadline is a measured number, not an assertion:
    # the shared deadline itself is tested by test_card_refresh_stops_at_the_shared_deadline.
    directory = tmp_path_factory.mktemp("dax_route_8dec")
    rnd = random.Random(8)
    path = directory / "wide.csv"
    columns = [f"d{i}" for i in range(1, 9)]
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", *columns])
        for i in range(ROWS):
            writer.writerow([i + 1, *(f"{rnd.randrange(-50_000, 5_000_000) / 100:.2f}" for _ in columns)])
    controller, _ = import_store_controller(path, directory)
    try:
        table = str(controller._project["model"]["tables"][0]["name"])
        from analytics_studio.store import dax_route

        deadline_patch = patch.object(dax_route, "refresh_deadline", lambda: time.monotonic() + 600.0)
        times = []
        with deadline_patch:
            for i, column in enumerate(columns, start=1):
                assert controller.create_measure(f"Sum {i}", f"SUM({table}[{column}])") is True, controller.statusMessage
            for _ in range(3):
                started = time.monotonic()
                controller._refresh_report()
                times.append(time.monotonic() - started)
        assert controller._measure_errors == {}, controller._measure_errors
        assert len(controller._measure_values) == 8
        print(f"[measured] GUI-thread refresh, 8 decimal cards, {ROWS:,} rows, deadline lifted to 600 s: "
              f"{', '.join(f'{t:.3f}' for t in times)} s")
        assert max(times) < 15.0, f"hang guard: {times}"
    finally:
        controller._close_project_store()


def test_route_measure_itself_raising_is_a_card_refusal(qapp: QApplication, tmp_path: Path) -> None:
    from analytics_studio.store import dax_route

    controller, _ = make_store_controller(tmp_path, _small_rows())
    try:
        assert controller.create_measure("Qty Sum", "SUM(t[qty])") is True
        assert controller.create_measure("Rows", "COUNTROWS(t)") is True
        before = [str(m["name"]) for m in controller._project["model"]["measures"]]

        def boom(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("route exploded")

        with patch.object(dax_route, "route_measure", boom):
            controller._refresh_report()
            for name in ("Qty Sum", "Rows"):
                assert "could not be computed (RuntimeError)" in controller._measure_errors[name]
                assert name not in controller._measure_values
            assert controller.create_measure("More", "SUM(t[qty])") is False
            assert "could not be computed" in controller.statusMessage
            assert [str(m["name"]) for m in controller._project["model"]["measures"]] == before
        controller._refresh_report()
        assert controller._measure_values["Rows"] == "800" and controller._measure_errors == {}
    finally:
        controller._close_project_store()
