"""Real-app tests of the large-table background requests (Stage C3b): cards, visuals and the measure preview.

A real controller imports a small CSV through the real large-import path (800 rows for the logic tests, 40,000 and
300,000 rows for the identity and invariant tests), with `_store_async` ON. Slow or stuck answers are modelled by
patching `MeasurePlan.execute` / `GroupByPlan.execute` (see `PlanProbe`): a gate that does not react to an interrupt
(a slow answer that cannot be stopped), a query that runs until the manager interrupts its reader (a stoppable one),
and an exception. Nothing asserts elapsed time: threads are synchronised with Events, counters and Qt signals, and the
waits (`wait_store_idle`, `wait_or_fail`) are hang guards that fail by assertion.
"""

from __future__ import annotations

import os
import threading
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from analytics_studio.controller import StudioController, _format_report_number
from analytics_studio.measures import normalize_measure
from analytics_studio.store import dax_sql
from analytics_studio.store.base import StoreError
from analytics_studio.store.duck_store import DuckStore, StoreReader
from analytics_studio.store.route_requests import CALCULATING_TEXT, CANCELED_TEXT
from tests import test_controller_dax_route_app as c2
from tests.test_controller_dax_route_app import (
    CATALOG,
    ROWS,
    SLICER,
    VISUAL_MEASURES,
    VISUALS,
    _build_visual,
    _quiet,
    _read,
    import_store_controller,
    make_store_controller,
)
from tests.test_store_reader import GUARD_S, Probe, wait_or_fail

# Fixtures of the C2 app tests, used here by name (the 40,000-row CSV, its in-memory twin, the 300,000-row CSV).
visual_csv = c2.visual_csv
visual_twin = c2.visual_twin
big_csv = c2.big_csv

GUARD_MS = int(GUARD_S * 1000)
CARDS = [("Qty Sum", "SUM(t[qty])"), ("Row Count", "COUNTROWS(t)"), ("Amt Sum", "SUM(t[amt])")]
SMALL_ROWS = 800


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(["Analytics Studio dax async tests"])


def small_rows(count: int = SMALL_ROWS) -> list[list[Any]]:
    return [
        [i, "East" if i % 2 == 0 else "West", f"P{i % 3:02d}", i % 7, f"{i}.50", "-1.00", "2024-01-01", "TRUE"]
        for i in range(1, count + 1)
    ]


def text_of(value: int | Decimal) -> str:
    return _format_report_number(Decimal(value))


def qty_sum(count: int = SMALL_ROWS, parity: int | None = None) -> int:
    return sum(i % 7 for i in range(1, count + 1) if parity is None or i % 2 == parity)


def wait_store_idle(controller: StudioController, what: str = "the large-table requests to finish") -> None:
    """Run the event loop until the controller says `storeRequestsIdle` (hang guard only; the time is never asserted)."""
    manager = controller._store_requests
    if manager is not None and manager.pending() > 0:
        loop = QEventLoop()
        guard = QTimer()
        guard.setSingleShot(True)
        hit: list[int] = []
        guard.timeout.connect(lambda: (hit.append(1), loop.quit()))
        controller.storeRequestsIdle.connect(loop.quit)
        guard.start(GUARD_MS)
        loop.exec()
        guard.stop()
        controller.storeRequestsIdle.disconnect(loop.quit)
        assert not hit, f"{what}: the {GUARD_S:g} s hang guard ran out with {manager.pending()} request(s) pending"
    QApplication.processEvents()  # the coalesced stateChanged


def set_measures(controller: StudioController, items: list[tuple[str, str]] = CARDS, refresh: bool = True) -> None:
    home = controller._active_model_table_id()
    controller._project["model"]["measures"] = [normalize_measure(n, e, home_table_id=home) for n, e in items]
    if refresh:
        controller._refresh_report()


def add_region_filter(controller: StudioController, values: list[str]) -> None:
    assert controller._add_report_filter(
        table_id=controller._active_model_table_id(), column="region", operator="is_any_of", value="",
        multi_values=values, report_scope=True,
    ), controller.statusMessage


class Rule:
    def __init__(self, match: str, mode: str, times: int) -> None:
        self.match, self.mode, self.times = match, mode, times
        self.hits = 0
        self.started = threading.Event()
        self.release = threading.Event()


class PlanProbe:
    """Patches the two plan classes: counts every execute, and gates, stops or breaks the ones a rule selects."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.lock = threading.Lock()
        self.calls: list[dict[str, Any]] = []
        self.finished: list[str] = []
        self.interrupted: list[str] = []
        self.rules: list[Rule] = []
        for cls in (dax_sql.MeasurePlan, dax_sql.GroupByPlan):
            monkeypatch.setattr(cls, "execute", self._wrap(cls.__name__, cls.execute))

    def gate(self, match: str, times: int = 1) -> Rule:
        """The first `times` plans whose SQL contains `match` wait for rule.release; an interrupt does not stop them."""
        return self._add(Rule(match, "gate", times))

    def stoppable(self, match: str, times: int = 1) -> Rule:
        """The first `times` such plans run a query that only ends when its reader is interrupted."""
        return self._add(Rule(match, "stoppable", times))

    def raising(self, match: str, times: int = 1_000) -> Rule:
        return self._add(Rule(match, "raise", times))

    def _add(self, rule: Rule) -> Rule:
        self.rules.append(rule)
        return rule

    def release_all(self) -> None:
        for rule in self.rules:
            rule.release.set()

    def count(self, kind: str | None = None, match: str = "") -> int:
        with self.lock:
            return sum(1 for call in self.calls if (kind is None or call["kind"] == kind) and match in call["sql"])

    def _wrap(self, kind: str, original: Any) -> Any:
        probe = self

        def execute(plan: Any, store: Any) -> Any:
            with probe.lock:
                probe.calls.append({
                    "kind": kind, "sql": plan.sql, "thread": threading.get_ident(), "on_reader": isinstance(store, StoreReader),
                })
                rule = next((r for r in probe.rules if r.match in plan.sql and r.hits < r.times), None)
                if rule is not None:
                    rule.hits += 1
            if rule is not None:
                rule.started.set()
                if rule.mode == "gate":
                    if not rule.release.wait(GUARD_S):
                        rule.release.set()  # a test that failed before releasing must not hold the worker for ever
                elif rule.mode == "stoppable":
                    scan = Probe().install(store)
                    try:
                        store.execute(scan.query)
                    except StoreError as exc:
                        if "interrupt" in str(exc).casefold():
                            with probe.lock:
                                probe.interrupted.append(plan.sql)
                        raise
                elif rule.mode == "raise":
                    raise RuntimeError("boom")
            result = original(plan, store)
            with probe.lock:
                probe.finished.append(plan.sql)
            return result

        return execute


@pytest.fixture
def app(qapp: QApplication, tmp_path: Path) -> Any:
    controller, project_store = make_store_controller(tmp_path, small_rows(), async_mode=True)
    set_measures(controller)
    wait_store_idle(controller)
    assert controller._measure_values["Qty Sum"] == text_of(qty_sum())
    yield controller
    controller._close_project_store()


@pytest.fixture
def probe(app: StudioController, monkeypatch: pytest.MonkeyPatch) -> Any:
    plan_probe = PlanProbe(monkeypatch)
    yield plan_probe
    plan_probe.release_all()  # first, so the teardown of `app` never waits for a gate


def no_dialogs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """A modal box would hang a test that fails; make it an assertion failure instead and record what was asked."""
    from PySide6.QtWidgets import QMessageBox

    asked: list[str] = []

    def refuse(*args: Any, **kwargs: Any) -> Any:
        asked.append(" ".join(str(a) for a in args[1:3]))
        raise AssertionError(f"a modal dialog was opened: {asked[-1]}")

    for name in ("critical", "question", "warning", "information"):
        monkeypatch.setattr(QMessageBox, name, refuse)
    return asked


def lease_count(controller: StudioController) -> int:
    return controller._project_store._readers if controller._project_store is not None else 0


# ---------------------------------------------------------------------------------------------------
# a-h: ordering, cancel and shutdown
# ---------------------------------------------------------------------------------------------------
def test_stale_answer_never_overwrites_a_newer_one(app: StudioController, probe: PlanProbe) -> None:
    gate = probe.gate("qty")
    applied0 = app._store_applied
    app._refresh_report()  # A: the Qty Sum card is inside its query, the others wait behind it
    wait_or_fail(gate.started, "card A inside its query")
    add_region_filter(app, ["East"])  # B: the key of every card changes
    gate.release.set()  # A's slow answer now arrives; it is for the old filter
    wait_store_idle(app)
    assert app._measure_values["Qty Sum"] == text_of(qty_sum(parity=0)), "the East value must be shown, not A's"
    assert app._measure_values["Row Count"] == text_of(SMALL_ROWS // 2)
    assert app._store_applied - applied0 == len(CARDS), "only B's answers are applied"
    assert probe.count(match="qty") == 2, "A ran once, B once"
    assert lease_count(app) == 0


def test_a_result_for_an_old_key_is_dropped_by_the_key_check(app: StudioController, probe: PlanProbe) -> None:
    """The manager forgets a superseded request, so this proves the controller's own recheck: the result is delivered
    for slot and key as they were, the state changed without a refresh in between, and the answer is not shown."""
    gate = probe.gate("qty")
    app._refresh_report()
    wait_or_fail(gate.started, "card A inside its query")
    # Change what the card depends on WITHOUT any refresh or request (a mutation site that forgot to refresh).
    app._project["model"]["measures"][0]["expression"] = "SUM(t[qty]) + 1000"
    dropped0, applied0 = app._store_dropped, app._store_applied
    gate.release.set()
    wait_store_idle(app)
    assert app._store_dropped - dropped0 >= 1
    assert app._store_applied - applied0 == len(CARDS) - 1 + 1  # the other cards, then the card asked again for its new key
    # SUM(t[qty]) + 1000 is not a whitelisted shape: whatever the card shows, it is never the old value
    assert app._measure_values.get("Qty Sum") != text_of(qty_sum())


def test_cancel_on_filter_change_stops_the_old_query(app: StudioController, probe: PlanProbe) -> None:
    stuck = probe.stoppable("qty")
    applied0 = app._store_applied
    app._refresh_report()
    wait_or_fail(stuck.started, "card A inside its query")
    add_region_filter(app, ["East"])
    wait_store_idle(app)
    assert len(probe.interrupted) == 1, "the old query must end by interrupt"
    assert probe.count(match="qty") == 2 and len(probe.finished) == probe.count() - 1, "A never finished normally"
    assert app._store_applied - applied0 == len(CARDS), "only B is applied"
    assert app._measure_values["Qty Sum"] == text_of(qty_sum(parity=0))
    assert lease_count(app) == 0


def test_close_project_while_a_query_runs(app: StudioController, probe: PlanProbe) -> None:
    stuck = probe.stoppable("qty")
    project_store = app._project_store
    app._refresh_report()
    wait_or_fail(stuck.started, "a query inside the store")
    applied0 = app._store_applied
    assert app.shutdown_store() is True
    assert project_store.closed and app._project_store is None
    QApplication.processEvents()
    assert app._store_applied == applied0, "no result may be applied after the store closed"
    assert len(probe.interrupted) == 1
    assert project_store._readers == 0
    assert app._store_requests is None


def test_closing_the_project_store_stops_the_manager_first(app: StudioController, probe: PlanProbe) -> None:
    stuck = probe.stoppable("qty")
    project_store = app._project_store
    manager_before = app._store_requests
    app._refresh_report()
    wait_or_fail(stuck.started, "a query inside the store")
    applied0 = app._store_applied
    app._close_project_store()
    assert app._project_store is None and project_store.closed and project_store._readers == 0
    assert app._store_requests is None and manager_before.pending() == 0 and app._store_state == {}
    QApplication.processEvents()
    assert app._store_applied == applied0 and len(probe.interrupted) == 1


def test_shutdown_with_a_gated_query_returns_false_and_store_stays_usable(
    app: StudioController, probe: PlanProbe
) -> None:
    gate = probe.gate("qty")
    project_store = app._project_store
    app._refresh_report()
    wait_or_fail(gate.started, "card inside its query")
    assert app.shutdown_store(timeout=0.2) is False, "a query that cannot be stopped keeps the store open"
    assert not project_store.closed and app._project_store is project_store
    gate.release.set()
    wait_store_idle(app)
    assert app._measure_values["Qty Sum"] == text_of(qty_sum()), "the controller still answers"
    assert app.shutdown_store(timeout=GUARD_S) is True
    assert project_store.closed and project_store._readers == 0


def test_reload_while_a_query_runs(
    app: StudioController, probe: PlanProbe, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_dialogs(monkeypatch)
    stuck = probe.stoppable("qty")
    app._refresh_report()
    wait_or_fail(stuck.started, "card inside its query")
    new_rows = small_rows(900)
    path = tmp_path / "t.csv"
    import csv

    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("id", "region", "product", "qty", "amt", "neg", "pay", "paid"))
        writer.writerows(new_rows)
    from tests.test_controller_store_reload import _wait_for_job

    assert app.reloadLargeTable() is True, app.statusMessage
    assert len(probe.interrupted) == 1, "the request is canceled first"
    assert "busy" not in app.statusMessage
    _wait_for_job(app)
    wait_store_idle(app)
    assert app._measure_values["Row Count"] == text_of(900)
    assert app._measure_values["Qty Sum"] == text_of(qty_sum(900))
    assert lease_count(app) == 0


def test_two_overlapping_refreshes(app: StudioController, probe: PlanProbe) -> None:
    gate = probe.gate("qty")
    applied0 = app._store_applied
    app._refresh_report()
    wait_or_fail(gate.started, "first refresh: a card inside its query")
    app._refresh_report()
    gate.release.set()
    wait_store_idle(app)
    # the one already running (first refresh) plus every measure of the second refresh
    assert probe.count() == 1 + len(CARDS)
    assert app._store_applied - applied0 == len(CARDS), "only the second refresh is applied"
    assert app._measure_values["Qty Sum"] == text_of(qty_sum())
    assert app._measure_errors == {}


def test_exception_in_the_worker_is_a_refusal(app: StudioController, probe: PlanProbe) -> None:
    probe.raising("amt")
    names_before = [str(m["name"]) for m in app._project["model"]["measures"]]
    app._refresh_report()
    wait_store_idle(app)
    assert app._measure_errors["Amt Sum"] == "Amt Sum could not be computed (RuntimeError)."
    assert "Amt Sum" not in app._measure_values
    assert app._measure_values["Qty Sum"] == text_of(qty_sum()) and app._measure_values["Row Count"] == text_of(SMALL_ROWS)
    assert [str(m["name"]) for m in app._project["model"]["measures"]] == names_before
    assert app.create_measure("Another", "COUNTROWS(t)") is True, app.statusMessage
    wait_store_idle(app)
    assert app._measure_values["Another"] == text_of(SMALL_ROWS)
    assert lease_count(app) == 0


def test_pending_requests_are_dropped_at_shutdown(app: StudioController, probe: PlanProbe) -> None:
    set_measures(app, [*CARDS, ("Max Qty", "MAX(t[qty])")], refresh=False)
    stuck = probe.stoppable("qty")
    app._refresh_report()
    wait_or_fail(stuck.started, "the first card inside its query")
    assert app._store_requests.pending() == 4
    assert app.shutdown_store() is True
    assert probe.count() == 1, "the three queued requests never ran"
    assert app._store_requests is None and app._project_store is None


# ---------------------------------------------------------------------------------------------------
# i-k: the grid, texts and the getter
# ---------------------------------------------------------------------------------------------------
def test_grid_reads_while_a_route_query_runs(app: StudioController, probe: PlanProbe) -> None:
    gate = probe.gate("qty")
    app._refresh_report()
    wait_or_fail(gate.started, "a route query inside its reader")
    store = app._project_store.store
    table = app._active_store_candidate.store_table
    page = store.read_page(table, 0, 3)  # the main connection: no StoreBusyError
    assert len(page) == 3 and page[0][1] in ("East", "West")
    model = app.dataModel
    assert model._set_page(0) is True
    assert model.data(model.index(0, 1)) in ("East", "West")
    gate.release.set()
    wait_store_idle(app)


def test_calculating_text_and_cancel(app: StudioController, probe: PlanProbe) -> None:
    gate = probe.gate("qty")
    app._refresh_report()
    wait_or_fail(gate.started, "a card inside its query")
    for name, _ in CARDS:
        assert app._measure_values[name] == CALCULATING_TEXT and app._kpis[name] == CALCULATING_TEXT
    assert app.storeCalculating == len(CARDS)
    assert [m["value"] for m in app.modelMeasures] == [CALCULATING_TEXT] * len(CARDS)
    app.cancelStoreCalculations()
    gate.release.set()
    wait_store_idle(app)
    assert app.storeCalculating == 0
    for name, _ in CARDS:
        assert app._measure_errors[name] == CANCELED_TEXT and name not in app._measure_values
    assert app.storeCanRecalculate is True
    calls0 = probe.count()
    for _ in range(5):  # a later read never starts a request by itself
        app.visualSeries("nothing")
        app.visualErrorMessage("nothing")
        app.modelMeasures
    wait_store_idle(app)
    assert probe.count() == calls0 and app.storeCalculating == 0
    app.recalculateStore()
    assert app.storeCalculating == len(CARDS)
    wait_store_idle(app)
    assert app._measure_values["Qty Sum"] == text_of(qty_sum()) and app._measure_errors == {}
    assert app.storeCanRecalculate is False
    assert probe.count() == calls0 + len(CARDS)


def make_bar(app: StudioController, title: str = "V1 qty by region", column: str = "region") -> str:
    _build_visual(app, "bar", title, column, "Qty Sum")
    return title


def read_visual_when_ready(app: StudioController, title: str, **kwargs: Any) -> list[dict[str, object]]:
    first = app.visualSeries(title)
    wait_store_idle(app)
    return app.visualSeries(title) if not first else first


def test_a_visual_getter_does_not_loop(app: StudioController, probe: PlanProbe) -> None:
    title = make_bar(app)
    wait_store_idle(app)
    grouped0 = probe.count("GroupByPlan")
    for _ in range(50):
        assert app.visualSeries(title) == []  # while pending: nothing, and no new request
    assert app.visualErrorMessage(title) == CALCULATING_TEXT
    wait_store_idle(app)
    for _ in range(50):
        series = app.visualSeries(title)
    assert probe.count("GroupByPlan") - grouped0 == 1, "one request for one key, whatever the number of reads"
    assert [item["label"] for item in series] == ["East", "West"]
    assert series[0]["value"] == float(qty_sum(parity=0)) and series[1]["value"] == float(qty_sum(parity=1))
    assert app.visualErrorMessage(title) == ""


def test_a_visual_shows_calculating_then_its_series_and_follows_a_filter(app: StudioController, probe: PlanProbe) -> None:
    title = make_bar(app)
    wait_store_idle(app)
    gate = probe.gate("GROUP BY")
    assert app.visualSeries(title) == []
    wait_or_fail(gate.started, "the visual inside its query")
    assert app.visualErrorMessage(title) == CALCULATING_TEXT
    assert app.storeCalculating == 1
    app.cancelStoreCalculations()
    gate.release.set()
    wait_store_idle(app)
    assert app.visualSeries(title) == [] and app.visualErrorMessage(title) == CANCELED_TEXT
    app.recalculateStore()
    assert app.visualSeries(title) == []
    wait_store_idle(app)
    assert len(app.visualSeries(title)) == 2
    unfiltered = app.visualSeries(title)
    assert app._add_report_filter(
        table_id=app._active_model_table_id(), column="product", operator="is_any_of", value="",
        multi_values=["P01"], report_scope=True,
    ), app.statusMessage
    assert app.visualSeries(title) == [], "a changed filter is a new key: the old series is not shown"
    wait_store_idle(app)
    filtered = app.visualSeries(title)
    assert [item["label"] for item in filtered] == ["East", "West"] and filtered != unfiltered
    assert filtered[0]["value"] == float(sum(i % 7 for i in range(1, SMALL_ROWS + 1) if i % 2 == 0 and i % 3 == 1))


# ---------------------------------------------------------------------------------------------------
# l: identity with the in-memory engine
# ---------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def async_visual_store(qapp: QApplication, visual_csv: Path, tmp_path_factory: pytest.TempPathFactory) -> Any:
    controller, _ = import_store_controller(visual_csv, tmp_path_factory.mktemp("async_visual_store"), async_mode=True)
    yield controller
    controller._close_project_store()


def read_async(controller: StudioController, title: str) -> list[dict[str, object]]:
    controller._report_filter_context_cache.clear()
    first = controller.visualSeries(title)
    wait_store_idle(controller)
    return controller.visualSeries(title) if not first else first


def test_async_results_equal_the_sync_results(
    async_visual_store: StudioController, visual_twin: StudioController
) -> None:
    store, twin = async_visual_store, visual_twin
    # cards: the 34 measures of the C2 catalog against the in-memory engine
    set_measures(store, [*CATALOG], refresh=True)
    wait_store_idle(store)
    twin_home = twin._active_model_table_id()
    twin._project["model"]["measures"] = [normalize_measure(n, e, home_table_id=twin_home) for n, e in CATALOG]
    twin._refresh_report()
    differences = [
        (name, store._measure_values.get(name), twin._measure_values.get(name))
        for name, _ in CATALOG if store._measure_values.get(name) != twin._measure_values.get(name)
    ]
    assert store._measure_errors == {} and not differences, differences
    print(f"[measured] {len(CATALOG) - len(differences)} of {len(CATALOG)} async card texts identical to the in-memory engine")
    # visuals: the 8 comparable ones and the slicer
    set_measures(store, VISUAL_MEASURES)
    wait_store_idle(store)
    twin._project["model"]["measures"] = [
        normalize_measure(n, e, home_table_id=twin_home) for n, e in VISUAL_MEASURES
    ]
    with _quiet(twin):
        for title, vtype, column, measure in VISUALS:
            _build_visual(store, vtype, title, column, measure)
            _build_visual(twin, vtype, title, column, measure)
        for controller in (store, twin):
            controller.add_visual("slicer", SLICER, 0, 0, 300, 200)
            controller.add_field_to_well("Fields", "region")
            for title, *_ in VISUALS:
                if title != "V8 sliced by product":
                    controller.set_visual_interaction(SLICER, title, "None")
        results: list[tuple[str, bool, int]] = []
        for title, *_ in VISUALS[:5]:
            got, want = read_async(store, title), _read(twin, title)
            results.append((title, got == want and bool(got), len(got)))
        for label in ("East", "West"):
            store.toggle_cross_filter(SLICER, label)
            twin.toggle_cross_filter(SLICER, label)
        got, want = read_async(store, "V8 sliced by product"), _read(twin, "V8 sliced by product")
        results.append(("V8 sliced by product", got == want and bool(got), len(got)))
        for label in ("East", "West"):
            store.toggle_cross_filter(SLICER, label)
            twin.toggle_cross_filter(SLICER, label)
        for controller in (store, twin):
            assert controller._add_report_filter(
                table_id=controller._active_model_table_id(), column="is_paid", operator="equals", value="TRUE",
                report_scope=True,
            )
        got, want = read_async(store, "V9 filtered by region"), _read(twin, "V9 filtered by region")
        results.append(("V9 filtered by region", got == want and bool(got), len(got)))
        for controller in (store, twin):
            assert controller._remove_filter("report", 0)
        got, want = read_async(store, SLICER), _read(twin, SLICER)
        results.append((SLICER, got == want and bool(got), len(got)))
    print(f"[measured] {sum(1 for _, ok, _n in results if ok)} of {len(results)} async visuals identical to the in-memory twin")
    assert all(ok for _, ok, _ in results), results
    assert len(results) == 8
    # cards follow a report filter like the in-memory twin; the synchronous lists (regions, page-filter values) too
    plain = [name for name, _ in VISUAL_MEASURES if name != "North Amount"]
    unfiltered = dict(store._measure_values)
    for controller in (store, twin):
        assert controller._add_report_filter(
            table_id=controller._active_model_table_id(), column="is_paid", operator="equals", value="TRUE",
            report_scope=True,
        )
    wait_store_idle(store)
    assert store._measure_values != unfiltered, "the filter reached the cards"
    assert {n: store._measure_values.get(n) for n in plain} == {n: twin._measure_values.get(n) for n in plain}
    for controller in (store, twin):
        assert controller._remove_filter("report", 0)
    wait_store_idle(store)
    assert store._measure_values == unfiltered
    assert store.regions == twin.regions and len(store.regions) == 9
    for column in ("region", "product", "is_paid"):
        store_id, twin_id = store._active_model_table_id(), twin._active_model_table_id()
        assert store.pageFilterValues(store_id, column) == twin.pageFilterValues(twin_id, column), column


# ---------------------------------------------------------------------------------------------------
# m, n, o: what stays synchronous, the invariant, a job
# ---------------------------------------------------------------------------------------------------
def test_validation_preview_and_lists_stay_synchronous_and_use_readers(
    app: StudioController, probe: PlanProbe
) -> None:
    gate = probe.gate("qty")
    app._refresh_report()
    wait_or_fail(gate.started, "a card inside its query")
    # nothing below may wait for the gated card, and nothing may say the store is busy
    assert app.create_measure("Sync Count", "COUNTROWS(t)") is True, app.statusMessage
    assert not gate.release.is_set(), "the call returned while the card was still inside its query"
    assert app.regions == ["All regions", "East", "West"]
    table_id = app._active_model_table_id()
    labels = [item["label"] for item in app.pageFilterValues(table_id, "region")]
    assert labels == ["East", "West"]
    assert [item["label"] for item in app.searchPageFilterValues(table_id, "region", "ea")] == ["East"]
    assert app.create_measure("Bad", "CALCULATE(SUM(t[qty]), ALL(t))") is False
    assert "busy" not in app.statusMessage.casefold()
    gate.release.set()
    wait_store_idle(app)
    assert app._measure_values["Sync Count"] == text_of(SMALL_ROWS)


def test_no_route_query_on_the_gui_thread_or_main_connection(
    app: StudioController, probe: PlanProbe, monkeypatch: pytest.MonkeyPatch
) -> None:
    gui = threading.get_ident()
    main_calls: list[tuple[str, int]] = []
    reader_threads: list[int] = []
    lock = threading.Lock()
    original_execute, original_read_page, original_reader_execute = DuckStore.execute, DuckStore.read_page, StoreReader.execute

    def main_execute(self: Any, sql: str, params: Any = ()) -> Any:
        with lock:
            main_calls.append((sql[:60], threading.get_ident()))
        return original_execute(self, sql, params)

    def main_read_page(self: Any, *args: Any, **kwargs: Any) -> Any:
        with lock:
            main_calls.append(("read_page", threading.get_ident()))
        return original_read_page(self, *args, **kwargs)

    def reader_execute(self: Any, sql: str, params: Any = ()) -> Any:
        with lock:
            reader_threads.append(threading.get_ident())
        return original_reader_execute(self, sql, params)

    title = make_bar(app)  # building a visual validates its measure on the window thread (allowed): not recorded
    wait_store_idle(app)
    probe.calls.clear()
    monkeypatch.setattr(DuckStore, "execute", main_execute)
    monkeypatch.setattr(DuckStore, "read_page", main_read_page)
    monkeypatch.setattr(StoreReader, "execute", reader_execute)
    app._refresh_report()
    app.visualSeries(title)
    done: list[str] = []
    app._preview_measure_expression_async("Draft", "SUM(t[qty])", done.append)
    wait_store_idle(app)
    app.visualSeries(title)
    assert done == [text_of(qty_sum())], done
    assert main_calls == [], f"a route query ran on the main connection: {main_calls}"
    assert reader_threads, "the route ran no query at all"
    assert gui not in reader_threads, "a route query ran on the GUI thread"
    assert probe.calls and all(call["on_reader"] and call["thread"] != gui for call in probe.calls)


def test_a_save_waits_for_nothing_and_the_cards_recompute_after_it(
    app: StudioController, probe: PlanProbe, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_dialogs(monkeypatch)
    stuck = probe.stoppable("qty")
    app._refresh_report()
    wait_or_fail(stuck.started, "a card inside its query")
    target = tmp_path / "saved.npa"
    ident = app._store_ident()
    assert app._save_to(target) is True, app.statusMessage
    assert app._store_ident() != ident, "Save As moved the session to another data file: another store identity"
    assert "busy" not in app.statusMessage.casefold()
    assert len(probe.interrupted) == 1, "the request was canceled first"
    wait_store_idle(app)
    assert app._measure_values["Qty Sum"] == text_of(qty_sum()), "the cards recompute after the job"
    assert lease_count(app) == 0


def test_a_busy_refusal_recovers_by_itself_when_the_job_ends(app: StudioController) -> None:
    with app._project_store.job():
        app._refresh_report()
        wait_store_idle(app)
        for name, _ in CARDS:
            assert "busy" in app._measure_errors[name] and name not in app._measure_values
    app._on_large_import_done()  # what the `done` signal of a store job does
    wait_store_idle(app)
    assert app._measure_values["Qty Sum"] == text_of(qty_sum()) and app._measure_errors == {}


# ---------------------------------------------------------------------------------------------------
# the preview
# ---------------------------------------------------------------------------------------------------
def test_preview_answers_through_the_manager_and_only_the_newest_calls_back(app: StudioController, probe: PlanProbe) -> None:
    gate = probe.gate("qty")
    first, second = [], []
    app._preview_measure_expression_async("Draft", "SUM(t[qty])", first.append)
    wait_or_fail(gate.started, "the first preview inside its query")
    app._preview_measure_expression_async("Draft", "COUNTROWS(t)", second.append)
    gate.release.set()
    wait_store_idle(app)
    assert first == [] and second == [text_of(SMALL_ROWS)]
    assert app._preview_busy_request_id is None


def test_cancel_preview_cancels_the_store_slot(app: StudioController, probe: PlanProbe) -> None:
    stuck = probe.stoppable("qty")
    done: list[str] = []
    app._preview_measure_expression_async("Draft", "SUM(t[qty])", done.append)
    wait_or_fail(stuck.started, "the preview inside its query")
    app.cancelPreview()
    wait_store_idle(app)
    assert len(probe.interrupted) == 1, "cancelPreview must stop the query"
    assert done == [] and app._preview_busy_request_id is None
    assert lease_count(app) == 0


def test_a_preview_refusal_is_its_sentence(app: StudioController) -> None:
    done: list[str] = []
    app._preview_measure_expression_async("Draft", "CALCULATE(SUM(t[qty]), ALL(t))", done.append)
    wait_store_idle(app)
    assert len(done) == 1 and "cannot be computed on a large table" in done[0], done


# ---------------------------------------------------------------------------------------------------
# keys (item 2)
# ---------------------------------------------------------------------------------------------------
def card_key(app: StudioController, name: str = "Qty Sum") -> Any:
    return app._store_slot_key("card", name)


def test_the_key_changes_for_each_input_and_only_then(app: StudioController) -> None:
    tid = app._active_model_table_id()
    base = card_key(app)
    assert card_key(app) == base, "pure: the same state gives the same key"
    measures = app._project["model"]["measures"]
    # an unrelated measure does not change it; the measure itself does
    row_count = next(m for m in measures if m["name"] == "Row Count")
    qty = next(m for m in measures if m["name"] == "Qty Sum")
    old = row_count["expression"]
    row_count["expression"] = "COUNTROWS(t) + 1"
    assert card_key(app) == base
    assert card_key(app, "Row Count") != app._store_slot_key("card", "Amt Sum")
    row_count["expression"] = old
    old = qty["expression"]
    qty["expression"] = "SUM(t[qty]) + 1"
    assert card_key(app) != base
    qty["expression"] = old
    assert card_key(app) == base
    # a measure the card uses through another measure
    measures.append(normalize_measure("Alias", "[Qty Sum]", home_table_id=tid))
    alias_key = card_key(app, "Alias")
    qty["expression"] = "SUM(t[amt])"
    assert card_key(app, "Alias") != alias_key, "the key holds the closure of measures the card uses"
    qty["expression"] = old
    measures.pop()
    # a filter
    add_region_filter(app, ["East"])
    filtered = card_key(app)
    assert filtered != base
    assert app._remove_filter("report", 0)
    assert card_key(app) == base
    # a selection of a slicer that filters a visual (a bar by product: a slicer on the bar's own column is refused)
    make_bar(app, "V1 qty by region", "product")
    app.add_visual("slicer", "Region slicer", 0, 0, 300, 200)
    app.add_field_to_well("Fields", "region")
    before_selection = card_key(app)
    app.toggle_cross_filter("Region slicer", "East")
    assert card_key(app) != before_selection
    app.toggle_cross_filter("Region slicer", "East")
    assert card_key(app) == before_selection
    # a visual: its fields, its filter and its measure
    visual = next(v for v in app._active_page()["visuals"] if v["title"] == "V1 qty by region")
    vkey = app._store_slot_key("visual", "V1 qty by region")
    visual["fields"]["X-axis"] = ["region"]
    assert app._store_slot_key("visual", "V1 qty by region") != vkey
    visual["fields"]["X-axis"] = ["product"]
    assert app._store_slot_key("visual", "V1 qty by region") == vkey
    qty = next(m for m in app._project["model"]["measures"] if m["name"] == "Qty Sum")  # the project dict was replaced
    qty["expression"] = "SUM(t[amt])"
    assert app._store_slot_key("visual", "V1 qty by region") != vkey
    qty["expression"] = old
    assert app._store_slot_key("visual", "V1 qty by region") == vkey


def test_the_key_changes_with_the_table_version_the_physical_table_and_the_store_identity(
    app: StudioController, tmp_path: Path
) -> None:
    base = card_key(app)
    candidate = app._active_store_candidate
    store = app._project_store.store
    # append: the table version goes up
    assert store.append_rows(candidate.store_table, [("9001", "East", "P01", "3", "1.50", "-1.00", "2024-01-01", "TRUE")]) == 1
    after_append = card_key(app)
    assert after_append != base
    # reload: another physical table
    physical = candidate.store_table
    candidate.store_table = physical + "_g2"
    try:
        assert card_key(app) != after_append
    finally:
        candidate.store_table = physical
    assert card_key(app) == after_append
    # close and reopen: the store identity
    ident = app._store_ident()
    assert app._store_ident() == ident
    app._bump_store_identity()
    assert card_key(app) != after_append
    from analytics_studio.store.session import ProjectStore

    other = ProjectStore.open(str(tmp_path / "other.npa.data"))
    original = app._project_store
    try:
        app._project_store = other
        assert app._store_ident() != ident, "another project store is another identity"
    finally:
        app._project_store = original
        other.shutdown(timeout=GUARD_S)
    assert app._store_ident() != ident


def test_results_are_cleared_by_every_refresh(app: StudioController, probe: PlanProbe) -> None:
    assert any(slot[0] == "card" for slot in app._store_state)
    gate = probe.gate("qty")
    app._refresh_report()
    wait_or_fail(gate.started, "a card inside its query")
    assert all(state[1] == "pending" for slot, state in app._store_state.items() if slot[0] == "card")
    gate.release.set()
    wait_store_idle(app)
    assert all(state[1] == "done" for slot, state in app._store_state.items() if slot[0] == "card")
    app._refresh_report_async()
    assert all(state[1] == "pending" for slot, state in app._store_state.items() if slot[0] == "card")
    wait_store_idle(app)


def test_state_changed_is_coalesced_to_one_emit_per_turn(app: StudioController) -> None:
    emitted: list[int] = []
    app.stateChanged.connect(lambda: emitted.append(1))
    QApplication.processEvents()
    emitted.clear()
    for _ in range(10):
        app._schedule_store_state_emit()
    QApplication.processEvents()
    assert emitted == [1]


def test_a_result_the_slot_cannot_apply_never_kills_the_qt_slot(app: StudioController, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("bug while applying")

    monkeypatch.setattr(StudioController, "_apply_store_card", broken)
    app._refresh_report()
    wait_store_idle(app)  # the Qt slot swallowed the exception: the manager still went idle
    assert app.storeCalculating == 0
    for name, _ in CARDS:  # a lost result never leaves "Calculating..." on the card
        assert app._measure_values.get(name) != CALCULATING_TEXT and app._kpis.get(name) != CALCULATING_TEXT
        assert app._measure_errors[name] == "This result could not be shown."
    monkeypatch.undo()
    app._refresh_report()
    wait_store_idle(app)
    assert app._measure_values["Qty Sum"] == text_of(qty_sum())


# ---------------------------------------------------------------------------------------------------
# projects that are not S1 never create a manager
# ---------------------------------------------------------------------------------------------------
def test_a_mixed_model_keeps_the_old_refusals_and_creates_no_manager(qapp: QApplication, tmp_path: Path) -> None:
    controller, project_store = make_store_controller(tmp_path, small_rows(), async_mode=True)
    try:
        controller._project["model"]["tables"].append(
            {"id": "ordinary", "source_id": "ordinary", "name": "Small", "column_types": {"a": "text"}}
        )
        controller._reset_silent_refusal_notice()
        controller._refresh_report()
        assert controller._store_requests is None and controller._measure_values == {}
        assert controller.create_measure("Another", "COUNTROWS(t)") is False
        assert controller._large_data_refusal("DAX measures") in controller.statusMessage
        assert controller.visualSeries("anything") == [] and controller.storeCalculating == 0
        assert controller._store_requests is None
    finally:
        controller._close_project_store()


def test_a_relationship_keeps_the_old_refusal_and_creates_no_manager(qapp: QApplication, tmp_path: Path) -> None:
    controller, project_store = make_store_controller(tmp_path, small_rows(), async_mode=True)
    try:
        controller._project["model"]["relationships"] = [{"id": "r"}]
        controller._reset_silent_refusal_notice()
        controller._refresh_report()
        assert controller._store_requests is None and controller._measure_values == {}
        assert controller.create_measure("Qty Sum", "SUM(t[qty])") is False
        assert controller._store_requests is None
    finally:
        controller._close_project_store()


def test_an_ordinary_project_has_no_manager_and_no_requests(qapp: QApplication) -> None:
    controller = StudioController()
    assert controller._store_requests is None and controller.storeCalculating == 0
    assert controller.storeCanRecalculate is False
    controller.cancelStoreCalculations()
    controller.recalculateStore()
    assert controller._store_requests is None
    assert controller.shutdown_store() is True


def test_a_refresh_cancels_the_running_visual_request_and_asks_for_it_again(app: StudioController, probe: PlanProbe) -> None:
    title = make_bar(app)
    wait_store_idle(app)
    grouped0 = probe.count("GroupByPlan")
    stuck = probe.stoppable("GROUP BY")
    assert app.visualSeries(title) == []
    wait_or_fail(stuck.started, "the visual inside its query")
    app._refresh_report()  # a new state: the old visual query must stop, and must not delay the cards
    wait_store_idle(app)
    assert len(probe.interrupted) == 1, "the refresh must stop the visual query"
    assert app._measure_values["Qty Sum"] == text_of(qty_sum())
    assert not any(slot[0] == "visual" for slot in app._store_state), "results of the old state are not kept"
    assert app.visualSeries(title) == []  # asked again, not served from an old result
    wait_store_idle(app)
    assert len(app.visualSeries(title)) == 2
    assert probe.count("GroupByPlan") - grouped0 == 2


def test_a_finished_visual_is_asked_again_after_a_refresh(app: StudioController, probe: PlanProbe) -> None:
    title = make_bar(app)
    wait_store_idle(app)
    app.visualSeries(title)
    wait_store_idle(app)
    assert len(app.visualSeries(title)) == 2
    grouped = probe.count("GroupByPlan")
    app._refresh_report()
    assert app.visualSeries(title) == [], "the result of the old state is not shown after a refresh"
    wait_store_idle(app)
    assert probe.count("GroupByPlan") == grouped + 1 and len(app.visualSeries(title)) == 2


def test_a_getter_that_starts_a_request_tells_qml_through_state_changed(app: StudioController, probe: PlanProbe) -> None:
    title = make_bar(app)
    wait_store_idle(app)
    gate = probe.gate("GROUP BY")
    emitted: list[int] = []
    app.stateChanged.connect(lambda: emitted.append(app.storeCalculating))
    QApplication.processEvents()
    emitted.clear()
    assert app.visualSeries(title) == []  # what a QML binding does: it starts the request, it must not emit by itself
    assert emitted == []
    wait_or_fail(gate.started, "the visual inside its query")
    QApplication.processEvents()
    assert emitted and emitted[0] == 1, "the bar must learn that a calculation started"
    gate.release.set()
    wait_store_idle(app)


# ---------------------------------------------------------------------------------------------------
# 300,000 rows: the report refresh does not touch the store on the GUI thread
# ---------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def async_big_store(qapp: QApplication, big_csv: Path, tmp_path_factory: pytest.TempPathFactory) -> Any:
    controller, _ = import_store_controller(big_csv, tmp_path_factory.mktemp("async_big_store"), async_mode=True)
    yield controller
    controller._close_project_store()


def test_ten_visuals_and_ten_cards_at_300k_touch_no_store_on_the_gui_thread(
    async_big_store: StudioController, monkeypatch: pytest.MonkeyPatch
) -> None:
    from uuid import uuid4

    controller = async_big_store
    gui = threading.get_ident()
    reader_threads: list[int] = []
    main_calls: list[Any] = []
    original_reader, original_main = StoreReader.execute, DuckStore.execute

    def reader_execute(self: Any, sql: str, params: Any = ()) -> Any:
        reader_threads.append(threading.get_ident())
        return original_reader(self, sql, params)

    def main_execute(self: Any, sql: str, params: Any = ()) -> Any:
        main_calls.append(sql[:60])
        return original_main(self, sql, params)

    names = ["Total Amount", "Row Count", "Max Amount", "Avg Amount"]
    catalog = dict(CATALOG)
    cards = [(name, catalog[name]) for name in names] + [(n, e) for n, e in CATALOG if n not in names][:6]
    set_measures(controller, cards, refresh=False)
    page = controller._active_page()
    saved_visuals = list(page.get("visuals", []))
    specs = [("bar", "region", 0), ("column", "product", 1), ("line", "order_date", 2), ("pie", "is_paid", 0),
             ("bar", "region", 3), ("bar", "product", 0), ("column", "region", 1), ("bar", "is_paid", 2),
             ("line", "order_date", 3), ("pie", "region", 0)]
    try:
        for index, (vtype, column, which) in enumerate(specs):
            page.setdefault("visuals", []).append({
                "id": str(uuid4()), "type": vtype, "title": f"T{index}", "x": 0, "y": 0, "width": 300, "height": 200,
                "fields": {"X-axis": [column], "Y-axis": [f"__dax_measure__:{names[which]}"]},
            })
        monkeypatch.setattr(StoreReader, "execute", reader_execute)
        monkeypatch.setattr(DuckStore, "execute", main_execute)
        started = time.monotonic()
        controller._refresh_report()
        refresh_s = time.monotonic() - started
        assert all(controller._measure_values[name] == CALCULATING_TEXT for name, _ in cards)
        assert reader_threads == [] or gui not in reader_threads
        started = time.monotonic()
        first = [controller.visualSeries(f"T{i}") for i in range(10)]
        visuals_s = time.monotonic() - started
        assert first == [[]] * 10
        wait_store_idle(controller)
        assert gui not in reader_threads and reader_threads, "route queries ran only on the request thread"
        assert main_calls == [], main_calls
        series = [controller.visualSeries(f"T{i}") for i in range(10)]
        assert all(series), [len(s) for s in series]
        assert controller._measure_errors == {}
        print(f"[measured] GUI thread at {ROWS:,} rows, background requests: _refresh_report() returned in {refresh_s:.3f} s "
              f"(10 cards 'Calculating...'), 10 visual getters in {visuals_s:.3f} s; keys per visual {[len(s) for s in series]}")
    finally:
        monkeypatch.undo()
        page["visuals"] = saved_visuals
        controller._project["model"]["measures"] = []
        controller._refresh_report()
        wait_store_idle(controller)


# ---------------------------------------------------------------------------------------------------
# the sweep: S1 project, async visuals, every property and every slot, no engine call
# ---------------------------------------------------------------------------------------------------
def test_s1_sweep_makes_no_engine_call(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests import test_controller_store_sweep as sweep

    from PySide6.QtWidgets import QDialog

    sweep._block_dialogs(monkeypatch)
    controller, project_store = make_store_controller(tmp_path, small_rows(), async_mode=True)

    def no_modal(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("A modal dialog was opened in the sweep.")

    monkeypatch.setattr(QDialog, "exec", no_modal)  # a modal dialog would hang the sweep until the alarm
    monkeypatch.setattr(StudioController, "_run_store_summary_dialog", lambda self, candidate: None)
    engine_calls: list[int] = []

    def counting_engine(*args: Any, **kwargs: Any) -> Any:
        engine_calls.append(1)
        return {}

    monkeypatch.setattr("analytics_studio.controller.evaluate_measures", counting_engine)
    try:
        set_measures(controller)
        wait_store_idle(controller)
        titles: list[str] = []
        tid = controller._active_model_table_id()
        for index, (vtype, fields) in enumerate([
            ("bar", {"X-axis": [(tid, "region")], "Y-axis": ["__dax_measure__:Qty Sum"]}),
            ("column", {"X-axis": [(tid, "product")], "Y-axis": ["__dax_measure__:Row Count"]}),
            ("line", {"X-axis": [(tid, "region")], "Y-axis": ["__dax_measure__:Qty Sum"]}),
            ("slicer", {"Fields": [(tid, "region")]}),
            ("card", {"Fields": ["__dax_measure__:Qty Sum"]}),
            ("gauge", {"Value": ["__dax_measure__:Qty Sum"]}),
            ("table", {"Fields": ["region", "__dax_measure__:Qty Sum"]}),
            ("matrix", {"Rows": [(tid, "region")], "Values": ["__dax_measure__:Qty Sum"]}),
            ("kpi", {"Indicator": ["__dax_measure__:Qty Sum"], "Trend axis": [(tid, "region")]}),
            ("scatter", {"X-axis": [(tid, "region")], "Y-axis": ["__dax_measure__:Qty Sum"]}),
            ("lineClusteredColumn", {"X-axis": [(tid, "region")], "Column Y-axis": ["__dax_measure__:Qty Sum"], "Line Y-axis": ["__dax_measure__:Row Count"]}),
        ]):
            title = f"Sw{index}"
            controller._active_page()["visuals"].append(
                {"id": f"sw_{index}", "title": title, "type": vtype, "table_id": tid, "fields": fields}
            )
            titles.append(title)
        reads = 0
        for name in sweep.SWEEP_PROPERTIES:
            try:
                getattr(controller, name)
            except Exception:  # noqa: BLE001 - the sweep counts engine calls, not exceptions
                pass
            reads += 1
        slot_calls = 0
        for name in sweep.SWEEP_SLOTS + list(sweep.EXTRA_CALLABLES):
            if not hasattr(controller, name):
                continue
            fn = getattr(controller, name)
            for args in sweep._call_sets(controller, name, titles):
                try:
                    fn(*args)
                except Exception:  # noqa: BLE001
                    pass
                slot_calls += 1
            QApplication.processEvents()
        wait_store_idle(controller)
        print(f"[measured] sweep of an S1 project in async mode: {reads} property reads, {slot_calls} slot calls, "
              f"{len(engine_calls)} engine calls")
        assert len(engine_calls) == 0, f"{len(engine_calls)} call(s) of the in-memory engine"
        assert reads == len(sweep.SWEEP_PROPERTIES) >= 60 and slot_calls >= len(sweep.SWEEP_SLOTS) >= 130
    finally:
        monkeypatch.undo()
        controller._close_project_store()


# ---------------------------------------------------------------------------------------------------
# the QML bar (offscreen: the real Main.qml with this controller)
# ---------------------------------------------------------------------------------------------------
def test_the_calculating_bar_follows_the_controller_in_the_real_qml(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pathlib import Path as _Path

    from PySide6.QtCore import QObject, QUrl
    from PySide6.QtQml import QQmlComponent, QQmlEngine
    from PySide6.QtQuickControls2 import QQuickStyle

    controller, project_store = make_store_controller(tmp_path, small_rows(), async_mode=True)
    set_measures(controller)
    wait_store_idle(controller)
    plan_probe = PlanProbe(monkeypatch)
    QQuickStyle.setStyle("Basic")
    engine = QQmlEngine()
    component = QQmlComponent(engine)
    qml = _Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml"
    component.loadUrl(QUrl.fromLocalFile(str(qml)))
    assert not component.isError(), "\n".join(error.toString() for error in component.errors())
    window = component.createWithInitialProperties({"studioController": controller})
    assert window is not None, "\n".join(error.toString() for error in component.errors())
    try:
        controller.setCurrentView("Report")
        QApplication.processEvents()
        bar = window.findChild(QObject, "storeCalculatingBar")
        cancel = window.findChild(QObject, "storeCancelButton")
        again = window.findChild(QObject, "storeCalculateAgainButton")
        assert bar is not None and cancel is not None and again is not None
        assert bar.property("visible") is False, "nothing is calculating"
        gate = plan_probe.gate("qty")
        controller._refresh_report()
        controller.stateChanged.emit()
        wait_or_fail(gate.started, "a card inside its query")
        QApplication.processEvents()
        assert controller.storeCalculating == len(CARDS)
        assert bar.property("visible") is True and cancel.property("visible") is True
        assert again.property("visible") is False
        cancel.metaObject().invokeMethod(cancel, "clicked")  # the Button signal: the QML handler calls the slot
        QApplication.processEvents()
        gate.release.set()
        wait_store_idle(controller)
        QApplication.processEvents()
        assert controller.storeCalculating == 0 and controller.storeCanRecalculate is True
        assert bar.property("visible") is True, "the bar stays to offer Calculate again"
        assert cancel.property("visible") is False and again.property("visible") is True
        controller.recalculateStore()
        wait_store_idle(controller)
        QApplication.processEvents()
        assert bar.property("visible") is False
        assert controller._measure_values["Qty Sum"] == text_of(qty_sum())
    finally:
        plan_probe.release_all()
        window.deleteLater()
        engine.deleteLater()
        QApplication.processEvents()
        controller._close_project_store()
