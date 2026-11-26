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


@pytest.fixture
def lifted_budgets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Value tests run with 600 s budgets, so a loaded machine can never turn a card or a bar into a timeout text.

    The default per-call budget is a keyword default of the three routes (patching the constant would change nothing),
    and the refresh and visual deadlines come from `refresh_deadline`. A test about a deadline or a budget patches its own
    small value inside its body, which replaces these for that test only.
    """
    from analytics_studio.store import dax_route

    monkeypatch.setattr(dax_route, "refresh_deadline", lambda seconds=0.0: time.monotonic() + 600.0)
    for route in (dax_route.route_measure, dax_route.route_grouped, dax_route.route_distinct_values):
        assert route.__kwdefaults__["budget_s"] == dax_route.DEFAULT_BUDGET_S
        monkeypatch.setitem(route.__kwdefaults__, "budget_s", 600.0)


pytestmark = pytest.mark.usefixtures("lifted_budgets")


def _real_call_budgets(monkeypatch: pytest.MonkeyPatch) -> None:
    """For a test ABOUT budgets or deadlines: the routes keep their real default call budget (0.5 s)."""
    from analytics_studio.store import dax_route

    for route in (dax_route.route_measure, dax_route.route_grouped, dax_route.route_distinct_values):
        monkeypatch.setitem(route.__kwdefaults__, "budget_s", dax_route.DEFAULT_BUDGET_S)


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
    assert elapsed < 5.0, elapsed  # hang guard only; the messages below are the behaviour
    assert controller._measure_values == {}
    assert "took longer than" in controller._measure_errors["M One"]
    for name in ("M Two", "M Three", "M Four"):
        assert controller._measure_errors[name] == dax_route.DEADLINE_MESSAGE


def test_card_refresh_stops_at_the_shared_deadline(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _real_call_budgets(monkeypatch)
    controller, _ = make_store_controller(tmp_path, _small_rows())
    try:
        _check_refresh_stops_at_the_shared_deadline(controller)
    finally:
        controller._close_project_store()


def test_mutant_card_refresh_passes_no_deadline(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _real_call_budgets(monkeypatch)
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


# ---------------------------------------------------------------------------------------------------
# C2b: visuals, slicers, report and page filters of a large table, compared with the in-memory twin.
# The comparison table has 40,000 rows and 120 different days: the in-memory path computes a visual one group at a
# time, so a 300,000-row twin with 1,500 days would run for many minutes. The 300,000-row store is used for the
# GUI-thread timing test below.
# ---------------------------------------------------------------------------------------------------
VISUAL_ROWS = 40_000


def generate_visual_csv(path: Path, rows: int = VISUAL_ROWS, seed: int = 20260402, days: int = 120) -> Path:
    rnd = random.Random(seed)
    base = datetime.date(2024, 1, 1)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS)
        for i in range(rows):
            region = "" if rnd.random() < 0.02 else REGIONS[rnd.randrange(8)]
            amount = "" if rnd.random() < 0.05 else f"{rnd.randrange(-20_000, 2_000_000) / 100:.2f}"
            qty = "" if rnd.random() < 0.05 else str(rnd.randrange(-2, 12))
            day = (base + datetime.timedelta(days=rnd.randrange(0, days))).isoformat()
            paid = "TRUE" if rnd.random() < 0.6 else "FALSE"
            writer.writerow([i + 1, region, f"P{rnd.randrange(200):03d}", amount, qty, day, paid])
    return path


VISUAL_MEASURES: list[tuple[str, str]] = [
    ("Sum Amount", "SUM(sales[amount])"),
    ("Sum Qty", "SUM(sales[qty])"),
    ("Row Count", "COUNTROWS(sales)"),
    ("Avg Amount", "AVERAGE(sales[amount])"),
    ("North Amount", "CALCULATE(SUM(sales[amount]), sales[region] = \"North\")"),
]
RATIO = ("Ratio", "DIVIDE([Sum Amount], [Sum Qty])")  # DIVIDE is not on the large-table whitelist
# (visual title, visual type, category column, measure)
VISUALS: list[tuple[str, str, str, str]] = [
    ("V1 amount by region", "bar", "region", "Sum Amount"),
    ("V2 rows by product", "column", "product", "Row Count"),
    ("V3 qty by day", "line", "order_date", "Sum Qty"),
    ("V4 amount by paid", "pie", "is_paid", "Sum Amount"),
    ("V6 average by region", "bar", "region", "Avg Amount"),
    ("V8 sliced by product", "bar", "product", "Sum Amount"),
    ("V9 filtered by region", "bar", "region", "Sum Amount"),
    ("V10 paged by region", "bar", "region", "Sum Amount"),
]
SLICER = "Region slicer"


@pytest.fixture(scope="module")
def visual_csv(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return generate_visual_csv(tmp_path_factory.mktemp("dax_route_visuals") / "sales.csv")


@pytest.fixture(scope="module")
def visual_store(qapp: QApplication, visual_csv: Path, tmp_path_factory: pytest.TempPathFactory) -> StudioController:
    controller, _ = import_store_controller(visual_csv, tmp_path_factory.mktemp("dax_route_visual_store"))
    yield controller
    controller._close_project_store()


@pytest.fixture(scope="module")
def visual_twin(qapp: QApplication, visual_csv: Path, tmp_path_factory: pytest.TempPathFactory) -> StudioController:
    controller = StudioController()
    appdata = tmp_path_factory.mktemp("dax_route_visual_twin")
    controller._effective_app_data_dir = lambda: str(appdata)  # type: ignore[method-assign]
    errors: list[str] = []
    with patch.object(QMessageBox, "critical", lambda *args: errors.append(str(args[2]))):
        assert controller._commit_import(visual_csv, parse_file(visual_csv)), errors
    assert not controller._store_tables_loaded()
    return controller


def _quiet(controller: StudioController) -> Any:
    """The in-memory twin recomputes every card on each edit; the visuals are read straight from their getters."""
    return patch.multiple(
        StudioController, _refresh_report=lambda self: None, _refresh_report_async=lambda self: None
    )


def _build_visual(controller: StudioController, vtype: str, title: str, column: str, measure: str) -> None:
    controller.add_visual(vtype, title, 0, 0, 300, 200)
    controller.add_field_to_well("X-axis", column)
    controller.add_field_to_well("Y-axis", f"__dax_measure__:{measure}")


def _read(controller: StudioController, title: str) -> list[dict[str, object]]:
    controller._report_filter_context_cache.clear()
    return controller.visualSeries(title)


@pytest.fixture(scope="module")
def visual_pages(visual_store: StudioController, visual_twin: StudioController) -> dict[str, Any]:
    """Both controllers get the same measures and the same 8 visuals plus a region slicer (built through the real getters
    of the store controller)."""
    from analytics_studio.store import dax_route

    state: dict[str, Any] = {}
    with patch.object(dax_route, "refresh_deadline", lambda seconds=0.0: time.monotonic() + 600.0):
        for name, expression in VISUAL_MEASURES:
            assert visual_store.create_measure(name, expression) is True, (name, visual_store.statusMessage)
        refused = visual_store.create_measure(*RATIO)
        state["ratio_created"] = refused
        state["ratio_status"] = visual_store.statusMessage
        twin_id = visual_twin._active_model_table_id()
        visual_twin._project["model"]["measures"] = [
            normalize_measure(name, expression, home_table_id=twin_id) for name, expression in [*VISUAL_MEASURES, RATIO]
        ]
        with _quiet(visual_twin):
            for controller in (visual_twin,):
                for title, vtype, column, measure in VISUALS:
                    _build_visual(controller, vtype, title, column, measure)
                controller.add_visual("slicer", SLICER, 0, 0, 300, 200)
                controller.add_field_to_well("Fields", "region")
                for title, *_ in VISUALS:
                    if title != "V8 sliced by product":
                        controller.set_visual_interaction(SLICER, title, "None")
        for title, vtype, column, measure in VISUALS:
            _build_visual(visual_store, vtype, title, column, measure)
        visual_store.add_visual("slicer", SLICER, 0, 0, 300, 200)
        visual_store.add_field_to_well("Fields", "region")
        for title, *_ in VISUALS:
            if title != "V8 sliced by product":
                visual_store.set_visual_interaction(SLICER, title, "None")
    return state


def _set_page_filter(controller: StudioController, column: str, values: list[str]) -> bool:
    from analytics_studio.controller import _encode_report_filter_value

    return controller._add_report_filter(
        table_id=controller._active_model_table_id(), column=column, operator="is_any_of", value="",
        multi_values=[_encode_report_filter_value(v) for v in values],
    )


def test_ratio_measure_is_refused_with_a_plain_sentence(visual_pages: dict[str, Any], visual_store: StudioController) -> None:
    assert visual_pages["ratio_created"] is False
    assert "Ratio cannot be computed on a large table yet" in visual_pages["ratio_status"]
    assert "DIVIDE" in visual_pages["ratio_status"]
    # A visual cannot be given the refused measure either: the well stays empty and the sentence says why.
    visual_store._project["model"]["measures"].append(
        {"name": RATIO[0], "expression": RATIO[1], "home_table_id": ""}
    )
    try:
        visual_store.add_visual("bar", "V5 ratio by region", 0, 0, 300, 200)
        visual_store.add_field_to_well("X-axis", "region")
        visual_store.add_field_to_well("Y-axis", "__dax_measure__:Ratio")
        assert "DIVIDE" in visual_store.statusMessage and "Ratio cannot be computed" in visual_store.statusMessage
        visual = next(v for v in visual_store._active_page()["visuals"] if v["title"] == "V5 ratio by region")
        assert not visual["fields"].get("Y-axis")
        # A project that already holds the visual (opened from a file) shows the same sentence and no bars.
        visual["fields"]["Y-axis"] = ["__dax_measure__:Ratio"]
        visual_store._reset_silent_refusal_notice()
        assert visual_store.visualSeries("V5 ratio by region") == []
        assert "Ratio cannot be computed on a large table yet" in visual_store.statusMessage
    finally:
        visual_store._project["model"]["measures"] = [
            m for m in visual_store._project["model"]["measures"] if m["name"] != RATIO[0]
        ]
        visual_store.remove_visual(visual["id"])


def test_eight_visuals_are_identical_to_the_in_memory_twin(
    visual_pages: dict[str, Any], visual_store: StudioController, visual_twin: StudioController
) -> None:
    from analytics_studio.controller import _encode_report_filter_value

    tid = visual_store._active_model_table_id()
    twin_tid = visual_twin._active_model_table_id()
    results: list[tuple[str, bool, int]] = []
    differences: list[Any] = []

    def check(title: str) -> None:
        got, want = _read(visual_store, title), _read(visual_twin, title)
        results.append((title, got == want and bool(got), len(got)))
        if got != want or not got:
            differences.append((title, got[:3], want[:3]))

    with _quiet(visual_twin):
        for title, *_ in VISUALS[:5]:
            check(title)
        # V8: a slicer on region (two regions) filters the product bars
        unfiltered = _read(visual_store, "V8 sliced by product")
        for label in ("East", "West"):
            visual_store.toggle_cross_filter(SLICER, label)
            visual_twin.toggle_cross_filter(SLICER, label)
        assert visual_store._cross_filters == {SLICER: ["East", "West"]}, visual_store.statusMessage
        check("V8 sliced by product")
        assert _read(visual_store, "V8 sliced by product") != unfiltered  # the slicer really changed the numbers
        for label in ("East", "West"):
            visual_store.toggle_cross_filter(SLICER, label)
            visual_twin.toggle_cross_filter(SLICER, label)
        assert _read(visual_store, "V8 sliced by product") == unfiltered
        # V9: a report filter is_paid = TRUE, V10: a page filter on three products
        for controller, table_id in ((visual_store, tid), (visual_twin, twin_tid)):
            assert controller._add_report_filter(
                table_id=table_id, column="is_paid", operator="equals", value="TRUE", report_scope=True
            ), controller.statusMessage
        check("V9 filtered by region")
        for controller in (visual_store, visual_twin):
            assert controller._remove_filter("report", 0)
        for controller in (visual_store, visual_twin):
            assert _set_page_filter(controller, "product", ["P001", "P002", "P150"]), controller.statusMessage
        check("V10 paged by region")
        for controller in (visual_store, visual_twin):
            assert controller._remove_filter("page", 0)
    print(f"[measured] {sum(1 for _, ok, _n in results if ok)} of {len(results)} visuals identical: "
          + ", ".join(f"{t.split()[0]}={n} keys" for t, _ok, n in results))
    assert not differences, differences
    assert len(results) == 8 and all(ok for _, ok, _ in results)
    assert _encode_report_filter_value("P001")


def test_slicer_value_list_equals_the_in_memory_list(
    visual_pages: dict[str, Any], visual_store: StudioController, visual_twin: StudioController
) -> None:
    got, want = _read(visual_store, SLICER), _read(visual_twin, SLICER)
    assert got == want and len(got) == 9  # 8 regions and the blank one
    assert got[0] == {"label": "", "value": 1.0}
    assert visual_store.regions == visual_twin.regions
    assert visual_store.regions[0] == "All regions" and len(visual_store.regions) == 9
    for column in ("region", "product", "order_date", "is_paid"):
        assert visual_store.pageFilterValues(visual_store._active_model_table_id(), column) == \
            visual_twin.pageFilterValues(visual_twin._active_model_table_id(), column), column
        assert visual_store.searchPageFilterValues(visual_store._active_model_table_id(), column, "1") == \
            visual_twin.searchPageFilterValues(visual_twin._active_model_table_id(), column, "1"), column


def _visual_of(controller: StudioController, title: str) -> dict[str, Any]:
    return next(v for v in controller._active_page()["visuals"] if v["title"] == title)


def test_visual_with_its_own_calculate_filter_is_refused_with_its_sentence(
    visual_pages: dict[str, Any], visual_store: StudioController
) -> None:
    """V7: the planner cannot group a measure that carries its own CALCULATE filter, whatever the column."""
    _build_visual(visual_store, "bar", "V7 north by product", "product", "North Amount")
    visual_store._reset_silent_refusal_notice()
    assert _read(visual_store, "V7 north by product") == []
    assert "North Amount cannot be computed on a large table yet" in visual_store.statusMessage
    assert "CALCULATE filter of its own" in visual_store.statusMessage
    assert "same column" not in visual_store.statusMessage
    visual_store.remove_visual(_visual_of(visual_store, "V7 north by product")["id"])


def test_slicer_on_the_group_by_column_is_refused_and_the_visual_is_unchanged(
    visual_pages: dict[str, Any], visual_store: StudioController
) -> None:
    before = _read(visual_store, "V1 amount by region")
    assert before
    visual_store.set_visual_interaction(SLICER, "V1 amount by region", "Filter")
    try:
        visual_store.toggle_cross_filter(SLICER, "East")
        assert visual_store._cross_filters == {}
        assert visual_store.statusMessage == (
            "A slicer on region cannot be used with a visual grouped by the same column on a large table yet."
        )
        assert _read(visual_store, "V1 amount by region") == before
    finally:
        visual_store.set_visual_interaction(SLICER, "V1 amount by region", "None")


def test_slicer_selection_loaded_from_a_file_still_refuses_in_the_visual(
    visual_pages: dict[str, Any], visual_store: StudioController
) -> None:
    visual_store.set_visual_interaction(SLICER, "V1 amount by region", "Filter")
    visual_store._cross_filters[SLICER] = ["East"]
    try:
        visual_store._reset_silent_refusal_notice()
        assert _read(visual_store, "V1 amount by region") == []
        assert visual_store.statusMessage == (
            "A slicer on region cannot be used with a visual grouped by the same column on a large table yet."
        )
    finally:
        visual_store._cross_filters.clear()
        visual_store.set_visual_interaction(SLICER, "V1 amount by region", "None")


def test_whole_number_group_by_two_fields_and_too_many_groups_are_refused(
    visual_pages: dict[str, Any], visual_store: StudioController
) -> None:
    _build_visual(visual_store, "bar", "G whole", "region", "Sum Amount")
    visual = _visual_of(visual_store, "G whole")
    try:
        visual["fields"]["X-axis"] = ["qty"]
        visual_store._reset_silent_refusal_notice()
        assert _read(visual_store, "G whole") == []
        assert visual_store.statusMessage == "Large tables can only group by text, date or yes/no columns for now."
        assert "whole" not in visual_store.statusMessage and "decimal" not in visual_store.statusMessage
        visual["fields"]["X-axis"] = ["region", "is_paid"]  # an 8-key by 2-key visual
        visual_store._reset_silent_refusal_notice()
        assert _read(visual_store, "G whole") == []
        assert visual_store.statusMessage == (
            "G whole uses more than one grouping field, which large tables do not support yet."
        )
        visual["fields"]["X-axis"] = ["region"]
        visual["fields"]["Legend"] = ["is_paid"]
        visual_store._reset_silent_refusal_notice()
        assert _read(visual_store, "G whole") == []
        assert "more than one grouping field" in visual_store.statusMessage
        del visual["fields"]["Legend"]
        visual["fields"]["X-axis"] = ["id"]  # 40,000 different values
        visual_store._reset_silent_refusal_notice()
        assert _read(visual_store, "G whole") == []
        assert visual_store.statusMessage == (
            "id has more than 2,000 groups; choose a column with fewer groups or filter first."
        )
    finally:
        visual_store.remove_visual(visual["id"])


def test_add_field_to_well_rules_for_a_large_table(
    visual_pages: dict[str, Any], visual_store: StudioController
) -> None:
    visual_store.add_visual("bar", "W bar", 0, 0, 300, 200)
    visual = _visual_of(visual_store, "W bar")
    try:
        visual_store.add_field_to_well("X-axis", "qty")
        assert visual_store.statusMessage == "Large tables can only group by text, date or yes/no columns for now."
        visual_store.add_field_to_well("Y-axis", "amount")
        assert "needs a DAX measure" in visual_store.statusMessage
        visual_store.add_field_to_well("Legend", "is_paid")
        assert "more than one grouping field" in visual_store.statusMessage
        assert not visual.get("fields", {}).get("X-axis") and not visual.get("fields", {}).get("Y-axis")
        visual_store.add_field_to_well("X-axis", "order_date")
        visual_store.add_field_to_well("Y-axis", "__dax_measure__:Sum Qty")
        assert visual["fields"]["X-axis"] == ["order_date"] and visual["fields"]["Y-axis"] == ["__dax_measure__:Sum Qty"]
        visual_store.add_field_to_well("X-axis", "region")
        assert "more than one grouping field" in visual_store.statusMessage
        assert visual["fields"]["X-axis"] == ["order_date"]
    finally:
        visual_store.remove_visual(visual["id"])
    visual_store.add_visual("gauge", "W gauge", 0, 0, 300, 200)
    visual_store.add_field_to_well("Value", "__dax_measure__:Sum Qty")
    assert visual_store.statusMessage == "A gauge visual cannot show a large table yet."
    visual_store.remove_visual(_visual_of(visual_store, "W gauge")["id"])


def test_filters_the_large_table_cannot_apply_are_not_created(
    visual_pages: dict[str, Any], visual_store: StudioController
) -> None:
    tid = visual_store._active_model_table_id()
    before = list(visual_store._project["report"].get("filters", []))
    cases = [
        ("region", "not_equals", "East", "The filter on region (is not) cannot be used on a large table yet"),
        ("region", "contains", "Ea", "The filter on region (contains) cannot be used on a large table yet"),
        ("amount", "equals", "1", "The filter on amount (is) cannot be used on a large table yet"),
        ("qty", "less_than", "5", "it would also select blank cells"),
    ]
    for column, operator, value, text in cases:
        assert visual_store._add_report_filter(
            table_id=tid, column=column, operator=operator, value=value, report_scope=True
        ) is False, (column, operator)
        assert text in visual_store.statusMessage, visual_store.statusMessage
    assert visual_store._add_report_filter(
        table_id=tid, column="order_date", operator="relative_date", value="", report_scope=True,
        relative_date_rule={"direction": "last", "count": 3, "unit": "days", "include_today": True},
    ) is False
    assert "relative date" in visual_store.statusMessage
    assert visual_store._project["report"].get("filters", []) == before


def test_case_and_space_variants_import_alike_in_both_paths(
    qapp: QApplication, tmp_path: Path
) -> None:
    """The app's own import already follows the load rules of Power BI, so both paths show one bar for variants."""
    rows = [[1, "North", "A", 10, "1", "1", "2024-01-01", "x"], [2, "north", "A", 20, "1", "1", "2024-01-01", "x"],
            [3, "North ", "A", 30, "1", "1", "2024-01-01", "x"], [4, "South", "A", 40, "1", "1", "2024-01-01", "x"]]
    rows += [[i, "East", "A", 1, "1", "1", "2024-01-01", "x"] for i in range(5, 801)]
    store, _ = make_store_controller(tmp_path, rows)
    try:
        assert store.create_measure("Qty Sum", "SUM(t[qty])") is True
        _build_visual(store, "bar", "Variants", "region", "Qty Sum")
        series = store.visualSeries("Variants")
        assert [item["label"] for item in series] == ["East", "North", "South"]
        assert dict((item["label"], item["value"]) for item in series)["North"] == 60.0
    finally:
        store._close_project_store()


def test_visual_case_variant_keys_differ_by_design(
    qapp: QApplication, tmp_path: Path
) -> None:
    """The store follows Power BI: spellings that differ only by ASCII case, or by trailing spaces, are ONE bar (the
    first spelling). The in-memory path groups by the exact cell, so when its cells do hold both spellings it shows
    TWO bars. That is a known difference of the in-memory path, to fix later (the parity ledger decides); it is
    reached only by cells that did not come through the app's import (which applies the same load rules).
    """
    rows = [[1, "North", "A", 10, "1", "1", "2024-01-01", "x"], [2, "north", "A", 20, "1", "1", "2024-01-01", "x"],
            [3, "North ", "A", 30, "1", "1", "2024-01-01", "x"], [4, "South", "A", 40, "1", "1", "2024-01-01", "x"]]
    rows += [[i, "East", "A", 1, "1", "1", "2024-01-01", "x"] for i in range(5, 801)]
    (tmp_path / "store").mkdir()
    store, _ = make_store_controller(tmp_path / "store", rows)
    path = tmp_path / "t.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "region", "product", "qty", "amt", "neg", "pay", "paid"])
        writer.writerows(rows)
    twin = StudioController()
    twin._effective_app_data_dir = lambda: str(tmp_path)  # type: ignore[method-assign]
    assert twin._commit_import(path, parse_file(path))
    try:
        assert store.create_measure("Qty Sum", "SUM(t[qty])") is True
        _build_visual(store, "bar", "Variants", "region", "Qty Sum")
        store_series = store.visualSeries("Variants")
        # The twin's cells hold the variants, as cells that were not imported through the app would.
        candidate = twin._loaded_candidates[twin._active_source_id]
        for row, spelling in zip(candidate.rows[:3], ["North", "north", "North "]):
            row["region"] = spelling
        twin_id = twin._active_model_table_id()
        twin._project["model"]["measures"] = [normalize_measure("Qty Sum", "SUM(t[qty])", home_table_id=twin_id)]
        with _quiet(twin):
            _build_visual(twin, "bar", "Variants", "region", "Qty Sum")
        twin_series = _read(twin, "Variants")
        assert [(i["label"], i["value"]) for i in store_series] == [("East", 796.0), ("North", 60.0), ("South", 40.0)]
        assert len(store_series) == 3
        assert sorted(i["label"] for i in twin_series) == ["East", "North", "North ", "South", "north"]
        assert len(twin_series) == 5
    finally:
        store._close_project_store()


def test_store_visuals_never_read_candidate_rows_or_the_in_memory_engine(
    visual_pages: dict[str, Any], visual_store: StudioController, monkeypatch: pytest.MonkeyPatch
) -> None:
    from analytics_studio import controller as controller_module
    from analytics_studio.store.candidate import StoreCandidate

    touched: list[str] = []

    def boom(name: str) -> Any:
        def inner(*args: Any, **kwargs: Any) -> Any:
            touched.append(name)
            raise AssertionError(f"{name} must not be used for a store table")
        return inner

    monkeypatch.setattr(StoreCandidate, "rows", property(lambda self: boom("StoreCandidate.rows")()))
    monkeypatch.setattr(controller_module, "evaluate_measures", boom("evaluate_measures"))
    monkeypatch.setattr(StudioController, "_measure_table_context", boom("_measure_table_context"))
    monkeypatch.setattr(StudioController, "_report_filter_context", boom("_report_filter_context"))
    monkeypatch.setattr(StudioController, "_measure_visual_series", boom("_measure_visual_series"))
    monkeypatch.setattr(StudioController, "_measure_value_for_visual_group", boom("_measure_value_for_visual_group"))
    tid = visual_store._active_model_table_id()
    with patch("analytics_studio.store.dax_route.refresh_deadline", lambda seconds=0.0: time.monotonic() + 600.0):
        for title, *_ in VISUALS + [("Region slicer",)]:
            assert visual_store.visualSeries(title), title
        assert visual_store.regions[0] == "All regions" and len(visual_store.regions) == 9
        assert visual_store.pageFilterValues(tid, "region") and visual_store.searchPageFilterValues(tid, "region", "e")
        visual_store.toggle_cross_filter(SLICER, "East")
        visual_store.toggle_cross_filter(SLICER, "East")
        assert visual_store._add_report_filter(
            table_id=tid, column="is_paid", operator="equals", value="TRUE", report_scope=True
        )
        assert visual_store.visualSeries("V8 sliced by product")
        assert visual_store._remove_filter("report", 0)
        visual_store._refresh_report()
        # The getters of the visuals that stay refused do not read rows either.
        for call in (visual_store.visualGaugeData, visual_store.visualKpiData, visual_store.visualMapData,
                     visual_store.visualShapeMapData, visual_store.visualScatterData, visual_store.visualTableData,
                     visual_store.visualMatrixData, visual_store.visualCardData):
            call("Anything")
    assert touched == []


def test_visual_refresh_stops_at_the_shared_deadline_and_says_so(
    visual_pages: dict[str, Any], visual_store: StudioController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slow plan is patched in; the batch deadline is 0.3 s. The first visual times out, the later ones are not run."""
    from analytics_studio.store import dax_route

    _real_call_budgets(monkeypatch)
    visual_store._reset_silent_refusal_notice()
    visual_store._store_visual_batch_deadline = None
    visual_store._store_visual_last_end = 0.0
    monkeypatch.setattr(dax_route, "refresh_deadline", lambda seconds=0.0: time.monotonic() + 0.3)
    monkeypatch.setattr("analytics_studio.store.dax_sql.GroupByPlan.execute", _slow_plan_execute)
    started = time.monotonic()
    first = visual_store.visualSeries("V1 amount by region")
    first_message = visual_store.statusMessage
    second = visual_store.visualSeries("V2 rows by product")
    elapsed = time.monotonic() - started
    assert first == [] and second == []
    assert elapsed < 5.0, elapsed  # hang guard: the slow plan would run for minutes
    assert "took longer than" in first_message, first_message
    visual_store._reset_silent_refusal_notice()
    visual_store.visualSeries("V3 qty by day")
    assert visual_store.statusMessage == dax_route.DEADLINE_MESSAGE  # started after the deadline: not run at all


def test_busy_store_gives_empty_visuals_and_a_sentence_not_a_value(
    visual_pages: dict[str, Any], visual_store: StudioController
) -> None:
    visual_store._reset_silent_refusal_notice()
    visual_store._store_visual_batch_deadline = None
    with visual_store._project_store.job():
        assert visual_store.visualSeries("V1 amount by region") == []
        assert "busy" in visual_store.statusMessage
    assert visual_store.visualSeries("V1 amount by region")


def test_ten_visuals_and_ten_cards_gui_thread_time_at_300k(
    store_app: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import uuid4

    from analytics_studio.store import dax_route

    controller = store_app["controller"]
    full = list(controller._project["model"]["measures"])
    names = ["Total Amount", "Row Count", "Max Amount", "Avg Amount"]  # plain measures: no CALCULATE of their own
    chosen = [m for m in full if m["name"] in names]
    assert len(chosen) == 4
    ten = (chosen + [m for m in full if m not in chosen])[:10]
    assert len(ten) == 10
    specs = [("bar", "region", 0), ("column", "product", 1), ("line", "order_date", 2), ("pie", "is_paid", 0),
             ("bar", "region", 3), ("bar", "product", 0), ("column", "region", 1), ("bar", "is_paid", 2),
             ("line", "order_date", 3), ("pie", "region", 0)]
    page = controller._active_page()
    old_visuals = list(page.get("visuals", []))
    controller._project["model"]["measures"] = ten
    try:
        for i, (vtype, column, which) in enumerate(specs):
            page.setdefault("visuals", []).append({
                "id": str(uuid4()), "type": vtype, "title": f"T{i}", "x": 0, "y": 0, "width": 300, "height": 200,
                "fields": {"X-axis": [column], "Y-axis": [f"__dax_measure__:{names[which]}"]},
            })
        monkeypatch.setattr(dax_route, "refresh_deadline", lambda seconds=0.0: time.monotonic() + 600.0)
        card_times, visual_times, counts = [], [], []
        for _ in range(3):
            started = time.monotonic()
            controller._refresh_report()
            card_times.append(time.monotonic() - started)
            started = time.monotonic()
            series = [controller.visualSeries(f"T{i}") for i in range(10)]
            visual_times.append(time.monotonic() - started)
            counts = [len(s) for s in series]
        assert all(counts), counts
        print(f"[measured] GUI-thread, {ROWS:,} rows: 10 cards {', '.join(f'{t:.3f}' for t in card_times)} s; "
              f"10 visuals {', '.join(f'{t:.3f}' for t in visual_times)} s (3 runs, deadline lifted); keys per visual {counts}")
        assert max(card_times) + max(visual_times) < 60.0, "hang guard"
    finally:
        controller._project["model"]["measures"] = full
        page["visuals"] = old_visuals
        controller._refresh_report()


def _same_cards(store: StudioController, twin: StudioController, names: list[str]) -> None:
    for name in names:
        assert store._measure_values.get(name, "<missing>") == twin._measure_values.get(name, "<missing>"), (
            name, store._measure_values.get(name), twin._measure_values.get(name),
        )


def test_cards_follow_report_filters_like_the_in_memory_twin(
    visual_pages: dict[str, Any], visual_store: StudioController, visual_twin: StudioController
) -> None:
    tid, twin_tid = visual_store._active_model_table_id(), visual_twin._active_model_table_id()
    plain = ["Sum Amount", "Sum Qty", "Row Count", "Avg Amount", "North Amount"]
    visual_store._refresh_report()
    visual_twin._refresh_report()
    _same_cards(visual_store, visual_twin, plain)
    unfiltered = dict(visual_store._measure_values)
    for controller, table_id in ((visual_store, tid), (visual_twin, twin_tid)):
        assert controller._add_report_filter(
            table_id=table_id, column="is_paid", operator="equals", value="TRUE", report_scope=True
        )
    assert visual_store._measure_values != unfiltered  # the filter reached the cards
    _same_cards(visual_store, visual_twin, plain)
    assert visual_store._measure_errors == {}
    # a filter on the column the measure itself filters: refused for that card, the others stay right
    for controller, table_id in ((visual_store, tid), (visual_twin, twin_tid)):
        assert controller._add_report_filter(
            table_id=table_id, column="region", operator="is_any_of", value="",
            multi_values=["East", "West"], report_scope=True,
        )
    assert "a slicer filters the same column as the formula" in visual_store._measure_errors["North Amount"]
    assert "North Amount" not in visual_store._measure_values
    _same_cards(visual_store, visual_twin, ["Sum Amount", "Sum Qty", "Row Count", "Avg Amount"])
    for controller in (visual_store, visual_twin):
        assert controller._remove_filter("report", 1) and controller._remove_filter("report", 0)
    assert visual_store._measure_values == unfiltered and visual_store._measure_errors == {}


def test_region_filter_and_visual_filter_match_the_in_memory_twin(
    visual_pages: dict[str, Any], visual_store: StudioController, visual_twin: StudioController
) -> None:
    tid, twin_tid = visual_store._active_model_table_id(), visual_twin._active_model_table_id()
    title = "V4 amount by paid"
    base = _read(visual_store, title)
    with _quiet(visual_twin):
        visual_store.setRegionFilter("East")
        visual_twin.setRegionFilter("East")
        try:
            assert visual_store.currentRegion == "East"
            filtered = _read(visual_store, title)
            assert filtered != base and filtered == _read(visual_twin, title)
            # the visual grouped by region itself is refused with the group-column sentence
            assert _read(visual_store, "V1 amount by region") == []
        finally:
            visual_store.setRegionFilter("All regions")
            visual_twin.setRegionFilter("All regions")
        assert _read(visual_store, title) == base == _read(visual_twin, title)
        visual_store.setRegionFilter("Atlantis")  # not in the list: ignored
        assert visual_store.currentRegion == "All regions"
        for controller, table_id in ((visual_store, tid), (visual_twin, twin_tid)):
            assert controller.addVisualFilter(title, table_id, "product", "P001")
        try:
            assert _read(visual_store, title) == _read(visual_twin, title) != base
            assert _read(visual_store, "V1 amount by region") == _read(visual_twin, "V1 amount by region")  # not its filter
        finally:
            for controller in (visual_store, visual_twin):
                controller._selected_visual = title
                assert controller._remove_filter("visual", 0)
    assert _read(visual_store, title) == base


def test_interactions_none_and_highlight_and_top_n_on_a_large_table(
    visual_pages: dict[str, Any], visual_store: StudioController, visual_twin: StudioController
) -> None:
    title = "V4 amount by paid"
    base = _read(visual_store, title)
    with _quiet(visual_twin):
        for controller in (visual_store, visual_twin):
            controller.set_visual_interaction(SLICER, title, "None")
        try:
            visual_store.toggle_cross_filter(SLICER, "East")
            visual_twin.toggle_cross_filter(SLICER, "East")
            assert _read(visual_store, title) == base == _read(visual_twin, title)  # no effect on a visual set to None
            visual_store.toggle_cross_filter(SLICER, "East")
            visual_twin.toggle_cross_filter(SLICER, "East")
            for controller in (visual_store, visual_twin):
                controller.set_visual_interaction(SLICER, title, "Highlight")
            visual_store.toggle_cross_filter(SLICER, "East")
            visual_twin.toggle_cross_filter(SLICER, "East")
            assert _read(visual_store, title) == base == _read(visual_twin, title)  # the bars are not filtered
            visual_store._reset_silent_refusal_notice()
            assert visual_twin.visualHighlightSeries(title)  # the in-memory path draws the highlight
            assert visual_store.visualHighlightSeries(title) == []
            assert visual_store.statusMessage == "Highlight interactions are not available on a large table yet."
        finally:
            for controller in (visual_store, visual_twin):
                controller._cross_filters.clear()
                controller.set_visual_interaction(SLICER, title, "None")
    page = visual_store._active_page()
    page.setdefault("visual_filters", []).append({
        "table_id": visual_store._active_model_table_id(), "column": "product", "visual_name": title, "logic": "and",
        "clauses": [{"operator": "top_n", "direction": "top", "count": 3,
                     "order_by": {"table_id": visual_store._active_model_table_id(), "column": "qty"}}],
    })
    try:
        visual_store._reset_silent_refusal_notice()
        assert _read(visual_store, title) == []
        assert visual_store.statusMessage == "A Top N filter cannot be used on a large table yet."
    finally:
        page["visual_filters"].clear()


def test_a_project_of_this_shape_does_not_say_the_report_view_is_unavailable(
    visual_pages: dict[str, Any], visual_store: StudioController
) -> None:
    visual_store._reset_silent_refusal_notice()
    visual_store._set_status("")
    visual_store._refresh_report()
    visual_store._refresh_report_async()
    visual_store.set_visual_interaction(SLICER, "V1 amount by region", "None")
    visual_store.toggle_cross_filter(SLICER, "East")
    visual_store.toggle_cross_filter(SLICER, "East")
    assert "Report view" not in visual_store.statusMessage
    assert "not available for large-data tables" not in visual_store.statusMessage


def test_visuals_asked_back_to_back_share_one_deadline_and_a_later_batch_gets_a_new_one(
    visual_pages: dict[str, Any], visual_store: StudioController
) -> None:
    from analytics_studio.store import dax_route

    now = time.monotonic()
    visual_store._reset_silent_refusal_notice()
    # an old batch whose deadline has passed, last used long ago: the next visual starts a new batch and is computed
    visual_store._store_visual_batch_deadline = now - 5.0
    visual_store._store_visual_last_end = now - 60.0
    assert visual_store.visualSeries("V1 amount by region")
    # the batch just used: its deadline is in the future now, so the next visual shares it and is computed
    assert visual_store.visualSeries("V4 amount by paid")
    # a deadline that passed a moment ago while visuals were still being asked for: not computed, and it says so
    visual_store._store_visual_batch_deadline = time.monotonic() - 0.01
    visual_store._store_visual_last_end = time.monotonic()
    visual_store._reset_silent_refusal_notice()
    assert visual_store.visualSeries("V1 amount by region") == []
    assert visual_store.statusMessage == dax_route.DEADLINE_MESSAGE
    visual_store._store_visual_batch_deadline = None


def test_a_click_that_cannot_filter_the_large_table_is_refused_and_not_stored(
    visual_pages: dict[str, Any], visual_store: StudioController
) -> None:
    visual_store.set_visual_interaction("V3 qty by day", "V4 amount by paid", "Filter")
    try:
        visual_store.toggle_cross_filter("V3 qty by day", "2024-01-05")  # a date selection
        assert visual_store._cross_filters == {}
        assert visual_store.statusMessage.startswith("The filter on order_date (is any of) cannot be used on a large table yet")
        assert "date column" in visual_store.statusMessage
        visual_store.toggle_cross_filter(SLICER, "")  # the blank group
        assert visual_store._cross_filters == {}
        assert "a blank value cannot be chosen" in visual_store.statusMessage
    finally:
        visual_store.set_visual_interaction("V3 qty by day", "V4 amount by paid", "None")


def test_top_n_and_relative_filters_are_not_created_on_a_large_table(
    visual_pages: dict[str, Any], visual_store: StudioController
) -> None:
    tid = visual_store._active_model_table_id()
    assert visual_store._add_report_filter(
        table_id=tid, column="region", operator="top_n", value="", visual_name="V1 amount by region",
        top_n_rule={"direction": "top", "count": 3, "order_by_column": "qty"},
    ) is False
    assert visual_store.statusMessage == "The filter on region (Top N) cannot be used on a large table yet."
    assert visual_store._add_report_filter(
        table_id=tid, column="order_date", operator="relative_time", value="", report_scope=True,
        relative_time_rule={"direction": "last", "count": 1, "unit": "hours"},
    ) is False
    assert "relative time" in visual_store.statusMessage
    assert visual_store._project["report"].get("filters", []) == []


def test_a_saved_filter_the_table_cannot_apply_shows_on_cards_and_visuals_not_as_a_wrong_number(
    visual_pages: dict[str, Any], visual_store: StudioController
) -> None:
    """A project file may hold a filter that could not be created now: nothing silently ignores it."""
    tid = visual_store._active_model_table_id()
    saved = {"table_id": tid, "column": "region", "logic": "and", "clauses": [{"operator": "not_equals", "value": "East"}]}
    visual_store._project["report"].setdefault("filters", []).append(saved)
    try:
        visual_store._refresh_report()
        assert visual_store._measure_values == {}
        assert all("The filter on region (is not) cannot be used on a large table yet" in m
                   for m in visual_store._measure_errors.values()) and len(visual_store._measure_errors) == 5
        visual_store._reset_silent_refusal_notice()
        assert _read(visual_store, "V2 rows by product") == []
        assert "The filter on region (is not)" in visual_store.statusMessage
    finally:
        visual_store._project["report"]["filters"].remove(saved)
        visual_store._refresh_report()
    assert visual_store._measure_errors == {} and len(visual_store._measure_values) == 5


def test_a_refused_visual_says_so_once_per_epoch_and_again_after_a_reset(
    visual_pages: dict[str, Any], visual_store: StudioController
) -> None:
    _build_visual(visual_store, "bar", "O once", "region", "North Amount")  # a measure with its own CALCULATE filter
    emitted: list[str] = []
    real = visual_store._set_status
    try:
        visual_store._set_status = lambda text: (emitted.append(text), real(text))[1]  # type: ignore[method-assign]
        visual_store._reset_silent_refusal_notice()
        for _ in range(3):
            assert _read(visual_store, "O once") == []
        assert len(emitted) == 1 and "North Amount cannot be computed" in emitted[0]
        visual_store._reset_silent_refusal_notice()
        _read(visual_store, "O once")
        assert len(emitted) == 2
    finally:
        visual_store._set_status = real  # type: ignore[method-assign]
        visual_store.remove_visual(_visual_of(visual_store, "O once")["id"])


def test_exceptions_in_the_store_path_are_refusals_in_visuals_lists_and_cards(
    visual_pages: dict[str, Any], visual_store: StudioController
) -> None:
    from analytics_studio.store import dax_route

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("route exploded")

    for name, expected in (("route_grouped", "could not be computed (RuntimeError)"),
                           ("route_filter_context", "could not be read (RuntimeError)")):
        with patch.object(dax_route, name, boom):
            visual_store._reset_silent_refusal_notice()
            assert _read(visual_store, "V9 filtered by region") == []
            assert expected in visual_store.statusMessage, visual_store.statusMessage
    with patch.object(dax_route, "route_distinct_values", boom):
        visual_store._reset_silent_refusal_notice()
        assert visual_store.regions == ["All regions"]
        assert "could not be listed (RuntimeError)" in visual_store.statusMessage
        visual_store._reset_silent_refusal_notice()
        assert visual_store.pageFilterValues(visual_store._active_model_table_id(), "region") == []
        assert _read(visual_store, SLICER) == []
    assert _read(visual_store, "V9 filtered by region")


def test_a_visual_without_a_measure_is_refused_in_words_and_a_date_measure_plots_like_in_memory(
    visual_pages: dict[str, Any], visual_store: StudioController, visual_twin: StudioController
) -> None:
    visual_store.add_visual("bar", "N none", 0, 0, 300, 200)
    visual_store.add_field_to_well("X-axis", "region")
    try:
        visual_store._reset_silent_refusal_notice()
        assert _read(visual_store, "N none") == []
        assert visual_store.statusMessage == "N none needs a DAX measure in its value well on a large table."
        # a measure that returns a date is a Decimal day number (DaxDateTime); both paths plot that number
        assert visual_store.create_measure("Last Day", "MAX(sales[order_date])") is True
        twin_id = visual_twin._active_model_table_id()
        twin_measures = list(visual_twin._project["model"]["measures"])
        visual_twin._project["model"]["measures"] = [*twin_measures, normalize_measure(
            "Last Day", "MAX(sales[order_date])", home_table_id=twin_id)]
        with _quiet(visual_twin):
            _build_visual(visual_twin, "pie", "N date", "is_paid", "Last Day")
        _build_visual(visual_store, "pie", "N date", "is_paid", "Last Day")
        got = _read(visual_store, "N date")
        assert got == _read(visual_twin, "N date") and len(got) == 2 and got[0]["value"] > 40000
    finally:
        visual_store.remove_visual(_visual_of(visual_store, "N none")["id"])
        visual_store.remove_visual(_visual_of(visual_store, "N date")["id"])
        visual_store._project["model"]["measures"] = [
            m for m in visual_store._project["model"]["measures"] if m["name"] != "Last Day"
        ]
        visual_twin._project["model"]["measures"] = twin_measures
        visual_twin.remove_visual(_visual_of(visual_twin, "N date")["id"])
        visual_store._refresh_report()


def test_filter_value_lists_cut_at_1000_and_200_like_the_in_memory_lists(
    visual_pages: dict[str, Any], visual_store: StudioController
) -> None:
    tid = visual_store._active_model_table_id()
    values = [f"v{i:04d}" for i in range(1500)]
    with patch.object(StudioController, "_store_distinct_values", lambda self, table_id, column, search="": list(values)):
        everything = visual_store.pageFilterValues(tid, "region")
        searched = visual_store.searchPageFilterValues(tid, "region", "v")
        narrow = visual_store.searchPageFilterValues(tid, "region", "v00")
        none = visual_store.searchPageFilterValues(tid, "region", "zzz")
    assert [item["label"] for item in everything] == values[:1000]
    assert [item["label"] for item in searched] == values[:200]
    assert [item["label"] for item in narrow] == values[:100] and none == []


def test_a_slicer_filters_the_cards_only_when_it_filters_some_visual(
    visual_pages: dict[str, Any], visual_store: StudioController, visual_twin: StudioController
) -> None:
    plain = ["Sum Amount", "Sum Qty", "Row Count", "Avg Amount"]
    visual_store._refresh_report()
    visual_twin._refresh_report()
    unfiltered = {name: visual_store._measure_values[name] for name in plain}
    target = "V8 sliced by product"  # the one visual the slicer filters
    with _quiet(visual_twin):
        for controller in (visual_store, visual_twin):
            controller.set_visual_interaction(SLICER, target, "None")
            controller.toggle_cross_filter(SLICER, "East")
    try:
        visual_store._refresh_report()
        visual_twin._refresh_report()
        assert {name: visual_store._measure_values[name] for name in plain} == unfiltered  # no visual takes the filter
        _same_cards(visual_store, visual_twin, plain)
        with _quiet(visual_twin):
            for controller in (visual_store, visual_twin):
                controller.set_visual_interaction(SLICER, target, "Filter")
        visual_store._refresh_report()
        visual_twin._refresh_report()
        assert {name: visual_store._measure_values[name] for name in plain} != unfiltered
        _same_cards(visual_store, visual_twin, plain)
    finally:
        with _quiet(visual_twin):
            for controller in (visual_store, visual_twin):
                controller._cross_filters.clear()
        visual_store._refresh_report()
        visual_twin._refresh_report()


def test_slicer_list_shows_only_the_values_that_still_have_rows_like_the_in_memory_list(
    visual_pages: dict[str, Any], visual_store: StudioController, visual_twin: StudioController
) -> None:
    tid, twin_tid = visual_store._active_model_table_id(), visual_twin._active_model_table_id()
    everything = _read(visual_store, SLICER)
    with _quiet(visual_twin):
        for controller, table_id in ((visual_store, tid), (visual_twin, twin_tid)):
            assert controller._add_report_filter(
                table_id=table_id, column="product", operator="equals", value="P001", report_scope=True)
            assert controller._add_report_filter(
                table_id=table_id, column="qty", operator="equals", value="11", report_scope=True)
        try:
            narrowed = _read(visual_store, SLICER)
            assert 0 < len(narrowed) < len(everything)
            assert narrowed == _read(visual_twin, SLICER)
        finally:
            for controller in (visual_store, visual_twin):
                assert controller._remove_filter("report", 1) and controller._remove_filter("report", 0)
    assert _read(visual_store, SLICER) == everything


def test_filter_value_case_differs_by_design(
    visual_pages: dict[str, Any], visual_store: StudioController, visual_twin: StudioController
) -> None:
    """A typed filter value is compared the way Power BI compares text: capital and small ASCII letters are the same.

    The store follows Power BI, so the value "north" selects the "North" rows. The in-memory report filter compares the
    exact text and selects nothing: a known difference of the in-memory path (the parity ledger decides). Values chosen
    from the value list always have the spelling of the data, where the two paths agree (see the eight-visual test).
    """
    title = "V4 amount by paid"
    for controller in (visual_store, visual_twin):
        assert controller._add_report_filter(
            table_id=controller._active_model_table_id(), column="region", operator="equals", value="north",
            report_scope=True)
    try:
        with _quiet(visual_twin):
            assert _read(visual_twin, title) == []
        got = _read(visual_store, title)
        assert [item["label"] for item in got] == ["FALSE", "TRUE"] and all(item["value"] > 0 for item in got)
    finally:
        for controller in (visual_store, visual_twin):
            assert controller._remove_filter("report", 0)


# ---------------------------------------------------------------------------------------------------
# C2b review gaps: blank values, first measure, clearing a selection, own selection, measure routing,
# names with a quote or a bracket, and the controller's loaded candidates.
# ---------------------------------------------------------------------------------------------------
def _csv_twin(tmp_path: Path, rows: list[list[Any]], headers: tuple[str, ...], stem: str) -> StudioController:
    """The same rows loaded in memory (the oracle for the small tables of these tests)."""
    path = tmp_path / f"{stem}.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    twin = StudioController()
    twin._effective_app_data_dir = lambda: str(tmp_path)  # type: ignore[method-assign]
    assert twin._commit_import(path, parse_file(path))
    return twin


def test_a_group_whose_measure_is_blank_is_dropped_like_in_memory(qapp: QApplication, tmp_path: Path) -> None:
    rows = [[i, ["East", "West", "North"][i % 3], "P1", "" if i % 3 == 0 else i % 7, "1.5", "1.0", "2024-01-01", "x"]
            for i in range(1, 801)]
    (tmp_path / "store").mkdir()
    store, _ = make_store_controller(tmp_path / "store", rows)
    twin = _csv_twin(tmp_path, rows, ("id", "region", "product", "qty", "amt", "neg", "pay", "paid"), "t")
    try:
        assert store.create_measure("Top Qty", "MAX(t[qty])") is True
        twin._project["model"]["measures"] = [
            normalize_measure("Top Qty", "MAX(t[qty])", home_table_id=twin._active_model_table_id())]
        with _quiet(twin):
            _build_visual(twin, "bar", "Blanks", "region", "Top Qty")
        _build_visual(store, "bar", "Blanks", "region", "Top Qty")
        got, want = _read(store, "Blanks"), _read(twin, "Blanks")
        assert got == want == [{"label": "North", "value": 6.0}, {"label": "West", "value": 6.0}]  # East has no value
    finally:
        store._close_project_store()


def test_a_value_well_holding_two_measures_uses_the_first_like_in_memory(
    visual_pages: dict[str, Any], visual_store: StudioController, visual_twin: StudioController
) -> None:
    fields = {"X-axis": ["is_paid"], "Y-axis": ["__dax_measure__:Sum Amount", "__dax_measure__:Row Count"]}
    for controller in (visual_store, visual_twin):
        with _quiet(controller):
            controller.add_visual("pie", "Two measures", 0, 0, 300, 200)
        _visual_of(controller, "Two measures")["fields"] = {k: list(v) for k, v in fields.items()}
    try:
        got, want = _read(visual_store, "Two measures"), _read(visual_twin, "Two measures")
        assert got == want and len(got) == 2
        assert got == _read(visual_store, "V4 amount by paid")  # the first measure, Sum Amount
        assert all(item["value"] > 1000 for item in got)  # a row count would be at most 40,000 in total
        assert got[0]["value"] + got[1]["value"] > 40_000
    finally:
        for controller in (visual_store, visual_twin):
            controller.remove_visual(_visual_of(controller, "Two measures")["id"])


def test_clearing_a_selection_is_never_refused_and_a_visual_is_not_filtered_by_its_own_selection(
    visual_pages: dict[str, Any], visual_store: StudioController, visual_twin: StudioController
) -> None:
    # a selection that is already there (a file written before) on the column a visual groups by
    visual_store.set_visual_interaction(SLICER, "V1 amount by region", "Filter")
    visual_store._cross_filters[SLICER] = ["East"]
    try:
        visual_store._set_status("")
        visual_store.toggle_cross_filter(SLICER, "East")  # clears it
        assert visual_store._cross_filters == {}
        assert visual_store.statusMessage == ""
    finally:
        visual_store._cross_filters.clear()
        visual_store.set_visual_interaction(SLICER, "V1 amount by region", "None")
    # a click on a bar filters the OTHER visuals, never the visual that was clicked
    clicked = "V4 amount by paid"
    other = "V1 amount by region"
    base_clicked, base_other = _read(visual_store, clicked), _read(visual_store, other)
    with _quiet(visual_twin):
        for controller in (visual_store, visual_twin):
            controller.set_visual_interaction(clicked, other, "Filter")
            controller.toggle_cross_filter(clicked, "TRUE")
    try:
        assert visual_store._cross_filters == {clicked: ["TRUE"]}
        assert _read(visual_store, clicked) == base_clicked == _read(visual_twin, clicked)
        assert _read(visual_store, other) != base_other
        assert _read(visual_store, other) == _read(visual_twin, other)
    finally:
        with _quiet(visual_twin):
            for controller in (visual_store, visual_twin):
                controller._cross_filters.clear()
                controller.set_visual_interaction(clicked, other, "None")


def test_a_measure_for_the_wrong_well_gets_the_ordinary_sentence_not_the_large_table_one(
    visual_pages: dict[str, Any], visual_store: StudioController
) -> None:
    visual_store._project["model"]["measures"].append({"name": RATIO[0], "expression": RATIO[1], "home_table_id": ""})
    visual_store.add_visual("bar", "M well", 0, 0, 300, 200)
    try:
        visual_store.add_field_to_well("X-axis", "__dax_measure__:Ratio")
        assert visual_store.statusMessage.startswith("Add DAX measures to a visual value well"), visual_store.statusMessage
        assert "DIVIDE" not in visual_store.statusMessage
        visual_store.add_field_to_well("Y-axis", "__dax_measure__:Ratio")  # the right well: the large-table reason
        assert "DIVIDE" in visual_store.statusMessage
        visual_store.add_field_to_well("Y-axis", "__dax_measure__:Sum Qty")
        assert _visual_of(visual_store, "M well")["fields"]["Y-axis"] == ["__dax_measure__:Sum Qty"]
    finally:
        visual_store.remove_visual(_visual_of(visual_store, "M well")["id"])
        visual_store._project["model"]["measures"] = [
            m for m in visual_store._project["model"]["measures"] if m["name"] != RATIO[0]
        ]


def test_the_controllers_loaded_candidates_reach_every_route_call(
    visual_pages: dict[str, Any], visual_store: StudioController
) -> None:
    """A project whose sources carry no `store` entry is a store project only through the loaded candidates."""
    sources = visual_store._project["data_sources"]
    saved = [dict(source) for source in sources]
    assert any("store" in source for source in saved)
    for source in sources:
        source.pop("store", None)
    try:
        assert visual_store._store_s1()
        visual_store._reset_silent_refusal_notice()
        assert _read(visual_store, "V1 amount by region")  # route_grouped
        assert _read(visual_store, "V9 filtered by region")  # route_filter_context
        assert len(visual_store.regions) == 9  # route_distinct_values
        assert visual_store.pageFilterValues(visual_store._active_model_table_id(), "region")
        assert _read(visual_store, SLICER)
        visual_store._refresh_report()
        assert len(visual_store._measure_values) == 5 and visual_store._measure_errors == {}
    finally:
        for source, original in zip(sources, saved):
            source.clear()
            source.update(original)
    assert _read(visual_store, "V1 amount by region")


ODD_HEADERS = ("id", "Reg]ion", "product", "qty", "amt", "neg", "pay", "paid")


def test_a_quote_in_the_table_name_and_a_bracket_in_a_column_name_work_everywhere(
    qapp: QApplication, tmp_path: Path
) -> None:
    regions = ["East", "West", "North"]
    rows = [[i, regions[i % 3], f"P{i % 4}", i % 7, "1.5", "1.0", "2024-01-01", "x"] for i in range(1, 801)]
    store, _ = make_store_controller(tmp_path, rows, headers=ODD_HEADERS, stem="o'brien sales")
    try:
        table = store._project["model"]["tables"][0]
        assert table["name"] == "o'brien sales" and "Reg]ion" in table["column_types"]
        tid = store._active_model_table_id()

        def by(key: Any, keep: Any = lambda row: True) -> list[dict[str, object]]:
            sums: dict[str, int] = {}
            for row in rows:
                if keep(row):
                    sums[key(row)] = sums.get(key(row), 0) + row[3]
            return [{"label": label, "value": float(sums[label])} for label in sorted(sums, key=str.casefold)]

        # the measure names the table with a quote
        assert store.create_measure("Qty", "SUM('o''brien sales'[qty])") is True, store.statusMessage
        assert store.create_measure("East Qty", "CALCULATE(SUM('o''brien sales'[qty]), 'o''brien sales'[Reg]]ion] = \"East\")")
        _build_visual(store, "bar", "By region", "Reg]ion", "Qty")  # the visual groups by the bracket column
        assert _read(store, "By region") == by(lambda r: r[1])
        _build_visual(store, "bar", "By product", "product", "Qty")
        # a report filter on the bracket column
        assert store._add_report_filter(
            table_id=tid, column="Reg]ion", operator="is_any_of", value="", multi_values=["East", "West"], report_scope=True
        ), store.statusMessage
        assert _read(store, "By product") == by(lambda r: r[2], lambda r: r[1] in ("East", "West"))
        assert _read(store, "By region") == []  # grouped by the filtered column: refused, with the column named
        assert store.statusMessage == (
            "A slicer on Reg]ion cannot be used with a visual grouped by the same column on a large table yet."
        )
        assert store._remove_filter("report", 0)
        # a slicer on the bracket column
        store.add_visual("slicer", "Slicer", 0, 0, 300, 200)
        store.add_field_to_well("Fields", "Reg]ion")
        assert [item["label"] for item in _read(store, "Slicer")] == ["East", "North", "West"]
        store.set_visual_interaction("Slicer", "By region", "None")
        store.toggle_cross_filter("Slicer", "North")
        assert store._cross_filters == {"Slicer": ["North"]}
        assert _read(store, "By product") == by(lambda r: r[2], lambda r: r[1] == "North")
        assert _read(store, "By region") == by(lambda r: r[1])  # set to None: not filtered
        store.set_visual_interaction("Slicer", "By region", "Filter")
        store._reset_silent_refusal_notice()
        assert _read(store, "By region") == []
        assert store.statusMessage == (
            "A slicer on Reg]ion cannot be used with a visual grouped by the same column on a large table yet."
        )
        # the same column written in another case in a filter and in the group-by
        from analytics_studio.store import dax_route

        assert dax_route.route_filter_context(
            store._project, [{"table_id": tid, "column": "REG]ION", "logic": "and",
                              "clauses": [{"operator": "equals", "value": "East"}]}], candidates=store._loaded_candidates,
        ) == ("'o''brien sales'[Reg]]ion] = \"East\"",)
        grouped = dax_route.route_grouped(
            store._project, "Qty", ("o'brien sales", "REG]ION"), project_store=store._project_store,
            filter_context=("'o''brien sales'[Reg]]ion] = \"East\"",), candidates=store._loaded_candidates,
        )
        assert grouped.message == (
            "A slicer on REG]ION cannot be used with a visual grouped by the same column on a large table yet."
        )
    finally:
        store._close_project_store()
