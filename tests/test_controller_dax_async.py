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
from analytics_studio.store.route_requests import CALCULATING_TEXT, CANCELED_TEXT, JOB_RUNNING_TEXT
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

# Fixture of the C2 app tests, used here by name (the 300,000-row CSV).
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
# l: identity with the in-memory engine, and random sequences of user actions: async against sync
# ---------------------------------------------------------------------------------------------------
WORLD_ROWS = 600
FUZZ_SEEDS = list(range(20261127, 20261127 + 40))  # 40 sequences of 10 actions, a fixed list


class World:
    """One built world per module: A (store, async), B (store, sync reader path), C (the same rows in memory), the same
    measures and the same 8 visuals plus a region slicer on all three. `reset` puts all of it back exactly as built."""

    def __init__(self, a: StudioController, b: StudioController, c: StudioController) -> None:
        self.a, self.b, self.c = a, b, c
        self.titles = [item[0] for item in VISUALS] + [SLICER]
        self.saved = [c2._capture_visual_state(ctl) for ctl in (a, b, c)]

    def reset(self) -> None:
        for ctl, state in zip((self.a, self.b, self.c), self.saved):
            c2._restore_visual_state(ctl, state)
            ctl._reset_silent_refusal_notice()
        self.a._store_async, self.b._store_async = True, False
        self.a._refresh_report()
        self.b._refresh_report()
        wait_store_idle(self.a)


@pytest.fixture(scope="module")
def built_world(qapp: QApplication, tmp_path_factory: pytest.TempPathFactory) -> Any:
    from unittest.mock import patch

    from PySide6.QtWidgets import QMessageBox

    from analytics_studio.file_import import parse_file

    base = tmp_path_factory.mktemp("async_world")
    csv_path = c2.generate_visual_csv(base / "sales.csv", rows=WORLD_ROWS)
    dirs = [base / name for name in ("a", "b", "c")]
    for directory in dirs:
        directory.mkdir()
    a, _ = import_store_controller(csv_path, dirs[0], async_mode=True)
    b, _ = import_store_controller(csv_path, dirs[1], async_mode=False)
    c = StudioController()
    c._effective_app_data_dir = lambda: str(dirs[2])  # type: ignore[method-assign]
    errors: list[str] = []
    with patch.object(QMessageBox, "critical", lambda *args: errors.append(str(args[2]))):
        assert c._commit_import(csv_path, parse_file(csv_path)), errors
    for ctl in (a, b):
        for name, expression in VISUAL_MEASURES:
            assert ctl.create_measure(name, expression) is True, ctl.statusMessage
    home = c._active_model_table_id()
    c._project["model"]["measures"] = [normalize_measure(n, e, home_table_id=home) for n, e in VISUAL_MEASURES]
    with _quiet(c):
        for ctl in (a, b, c):
            for title, vtype, column, measure in VISUALS:
                _build_visual(ctl, vtype, title, column, measure)
            ctl.add_visual("slicer", SLICER, 0, 0, 300, 200)
            ctl.add_field_to_well("Fields", "region")
            for title, *_ in VISUALS:
                if title != "V8 sliced by product":
                    ctl.set_visual_interaction(SLICER, title, "None")
    world = World(a, b, c)
    yield world
    a._close_project_store()
    b._close_project_store()


@pytest.fixture
def world(built_world: World, lifted_budgets: None) -> Any:
    """The shared world with every test's changes undone before and after; the synchronous side runs with lifted budgets."""
    built_world.reset()
    yield built_world
    built_world.reset()


lifted_budgets = c2.lifted_budgets


def read_async(controller: StudioController, title: str) -> list[dict[str, object]]:
    controller._report_filter_context_cache.clear()
    first = controller.visualSeries(title)
    wait_store_idle(controller)
    return controller.visualSeries(title) if not first else first


def settle(controller: StudioController, titles: list[str]) -> None:
    """Ask for every visual until nothing is pending any more (a request answered after another one started is asked
    again), with a bounded number of rounds."""
    for _ in range(12):
        for title in titles:
            controller.visualSeries(title)
        wait_store_idle(controller)
        manager = controller._store_requests
        if (manager is None or manager.pending() == 0) and not any(
            status == "pending" for _key, status, _payload in controller._store_state.values()
        ):
            return
    raise AssertionError("the large-table requests did not settle within 12 rounds")


def test_async_results_equal_the_in_memory_engine(world: World) -> None:
    store, twin = world.a, world.c
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
    twin._project["model"]["measures"] = [normalize_measure(n, e, home_table_id=twin_home) for n, e in VISUAL_MEASURES]
    results: list[tuple[str, bool, int]] = []
    with _quiet(twin):
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


def run_sequence(world: World, seed: int) -> None:
    """Ten random user actions on the async controller A and the synchronous controller B (same rows, same report),
    then a refresh and a settle: cards and every visual must be identical. Even seeds use the interactive entry points
    (the ones QML calls: they refresh through `_refresh_report_async`)."""
    import random

    from analytics_studio.controller import _encode_report_filter_value

    a, b = world.a, world.b
    interactive = seed % 2 == 0
    rnd = random.Random(seed)
    regions = [r for r in a.regions if r != "All regions"]
    products = [f"P{i:03d}" for i in range(0, 200, 7)]
    tids = {id(a): a._active_model_table_id(), id(b): b._active_model_table_id()}

    def both(fn: Any) -> None:
        for ctl in (a, b):
            fn(ctl, interactive and ctl is a)

    kinds = (
        ["region"] * 3 + ["cross"] * 2
        + ["pagef", "pagef_rm", "reportf", "reportf_rm", "visf", "visf_rm", "measure_edit", "measure_add", "measure_rm"]
        + ["page", "page_back"] + ["read"] * 3 + ["reads", "pump", "pump", "cancel_recalc"]
    )
    sequence = [rnd.choice(kinds) for _ in range(10)]
    for kind in sequence:
        if kind == "region":
            region = rnd.choice([*regions, "All regions"])
            both(lambda c, fast: (c.setRegionFilterInteractive if fast else c.setRegionFilter)(region))
        elif kind == "cross":
            label = rnd.choice(regions)
            both(lambda c, fast: c.toggle_cross_filter(SLICER, label))
        elif kind == "pagef":
            values = [_encode_report_filter_value(v) for v in rnd.sample(products, 3)]
            both(lambda c, fast: c._add_report_filter(
                table_id=tids[id(c)], column="product", operator="is_any_of", value="", multi_values=values,
                async_refresh=fast))
        elif kind == "pagef_rm":
            both(lambda c, fast: c._remove_filter("page", 0, async_refresh=fast))
        elif kind == "reportf":
            values = [_encode_report_filter_value(v) for v in rnd.sample(regions, 2)]
            both(lambda c, fast: c._add_report_filter(
                table_id=tids[id(c)], column="region", operator="is_any_of", value="", multi_values=values,
                report_scope=True, async_refresh=fast))
        elif kind == "reportf_rm":
            both(lambda c, fast: c._remove_filter("report", 0, async_refresh=fast))
        elif kind == "visf":
            title, product = rnd.choice([v[0] for v in VISUALS]), rnd.choice(products)
            both(lambda c, fast: c.addVisualFilter(title, tids[id(c)], "product", product))
        elif kind == "visf_rm":
            title = rnd.choice([v[0] for v in VISUALS])

            def drop_visual_filter(c: StudioController, fast: bool) -> None:
                c._selected_visual = title
                c._remove_filter("visual", 0)

            both(drop_visual_filter)
        elif kind == "measure_edit":
            expression = rnd.choice(["SUM(sales[amount])", "SUM(sales[qty])", "COUNTROWS(sales)"])
            both(lambda c, fast: c.update_measure("Sum Amount", "Sum Amount", expression))
        elif kind == "measure_add":
            both(lambda c, fast: c.create_measure("Extra", "SUM(sales[qty])"))
        elif kind == "measure_rm":
            both(lambda c, fast: c.remove_measure("Extra"))
        elif kind == "page":
            def add_page(c: StudioController, fast: bool) -> None:
                if len(c._project["report"]["pages"]) < 2:
                    c.add_page()
                c.setActivePage(1)

            both(add_page)
        elif kind == "page_back":
            both(lambda c, fast: c.setActivePage(0))
        elif kind == "read":
            a.visualSeries(rnd.choice(world.titles))
        elif kind == "reads":
            for title in world.titles:
                a.visualSeries(title)
        elif kind == "pump":
            for _ in range(rnd.randint(1, 4)):
                QApplication.processEvents()
        elif kind == "cancel_recalc":
            a.cancelStoreCalculations()
            QApplication.processEvents()
            a.recalculateStore()
    both(lambda c, fast: c.setActivePage(0))
    a._refresh_report()
    b._refresh_report()
    settle(a, world.titles)
    where = f"seed {seed}, actions {sequence}"
    assert a._measure_values == b._measure_values and a._measure_errors == b._measure_errors, where
    assert not any("Calculating" in text for text in [*a._measure_values.values(), *a._measure_errors.values()]), where
    for title in world.titles:
        got, want = a.visualSeries(title), b.visualSeries(title)
        assert got == want, f"{where}: visual {title}"
        assert a.visualErrorMessage(title) != CALCULATING_TEXT, f"{where}: visual {title} is stuck calculating"


@pytest.mark.parametrize("chunk", range(4))
def test_random_action_sequences_give_the_same_answers_async_and_sync(world: World, chunk: int) -> None:
    for seed in FUZZ_SEEDS[chunk * 10:(chunk + 1) * 10]:
        run_sequence(world, seed)
        world.reset()


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
# F1: a store job (import, reload, save) while requests are in flight
# ---------------------------------------------------------------------------------------------------
def test_a_store_job_replaces_calculating_by_one_plain_sentence_and_the_end_of_the_job_recalculates(
    app: StudioController, probe: PlanProbe
) -> None:
    title = make_bar(app)
    wait_store_idle(app)
    gate = probe.stoppable("qty")  # inside its query until the interrupt of the job stops it
    app._refresh_report()
    wait_or_fail(gate.started, "a card inside its query")
    assert app.visualSeries(title) == []
    assert app.storeCalculating == len(CARDS) + 1
    done: list[str] = []
    app._preview_measure_expression_async("Draft", "SUM(t[qty])", done.append)
    app._cancel_store_requests_for_job()  # what an import, a reload and a save-as do first
    for name, _ in CARDS:
        assert app._measure_errors[name] == JOB_RUNNING_TEXT, "the card must say what is going on"
        assert name not in app._measure_values
        assert app._kpis.get(name) != CALCULATING_TEXT
    assert [m["value"] for m in app.modelMeasures] == ["—"] * len(CARDS)
    assert app.visualErrorMessage(title) == JOB_RUNNING_TEXT and app.visualSeries(title) == []
    assert done == [JOB_RUNNING_TEXT] and app._preview_busy_request_id is None, "the open preview is told too"
    assert app.storeCalculating == 0, "nothing is calculating for the user: no bar, no Cancel"
    assert app.storeCanRecalculate is False
    wait_store_idle(app)  # the forgotten answers arrive and are swallowed
    assert app._measure_errors[CARDS[0][0]] == JOB_RUNNING_TEXT and app.storeCalculating == 0
    app._refresh_store_after_job()  # the `done` signal of the job
    assert [app._measure_values.get(name) for name, _ in CARDS[:2]] == [CALCULATING_TEXT] * 2
    wait_store_idle(app)
    assert app._measure_values["Qty Sum"] == text_of(qty_sum()) and app._measure_errors == {}
    assert len(app.visualSeries(title)) == 0
    wait_store_idle(app)
    assert len(app.visualSeries(title)) == 2


# ---------------------------------------------------------------------------------------------------
# F2: state that changes under a request in flight, without any refresh (every part of the key)
# ---------------------------------------------------------------------------------------------------
def drift_and_compare_with_sync(app: StudioController, probe: PlanProbe, mutate: Any) -> tuple[Any, Any, int]:
    """A card is inside its query; the project changes under it with no refresh; the answer arrives. Returns what the
    async path shows, what the synchronous path shows for the same state, and how many results were dropped."""
    gate = probe.gate("qty")
    app._refresh_report()
    wait_or_fail(gate.started, "a card inside its query")
    dropped0 = app._store_dropped
    mutate(app)
    gate.release.set()
    wait_store_idle(app)
    shown = (dict(app._measure_values), dict(app._measure_errors))
    dropped = app._store_dropped - dropped0
    app._store_async = False
    try:
        app._refresh_report()
        expected = (dict(app._measure_values), dict(app._measure_errors))
    finally:
        app._store_async = True
    return shown, expected, dropped


def first_table(controller: StudioController) -> dict[str, Any]:
    return controller._project["model"]["tables"][0]


def test_a_table_renamed_under_a_running_card_never_shows_the_old_value(app: StudioController, probe: PlanProbe) -> None:
    shown, expected, dropped = drift_and_compare_with_sync(app, probe, lambda c: first_table(c).__setitem__("name", "t2"))
    assert dropped >= 1 and shown == expected
    assert shown[0].get("Qty Sum") != text_of(qty_sum()) and "Qty Sum" in shown[1]


def test_a_column_renamed_under_a_running_card_never_shows_the_old_value(app: StudioController, probe: PlanProbe) -> None:
    def rename(c: StudioController) -> None:
        types = first_table(c)["column_types"]
        types["qty2"] = types.pop("qty")

    shown, expected, dropped = drift_and_compare_with_sync(app, probe, rename)
    assert dropped >= 1 and shown == expected
    assert shown[0].get("Qty Sum") != text_of(qty_sum()) and "Qty Sum" in shown[1]


def test_a_column_type_changed_under_a_running_card_never_shows_the_old_value(app: StudioController, probe: PlanProbe) -> None:
    shown, expected, dropped = drift_and_compare_with_sync(
        app, probe, lambda c: first_table(c)["column_types"].__setitem__("qty", "text")
    )
    assert dropped >= 1 and shown == expected
    assert shown[0].get("Qty Sum") != text_of(qty_sum()) and "Qty Sum" in shown[1]


def test_a_measure_edited_under_a_running_card_never_shows_the_old_value(app: StudioController, probe: PlanProbe) -> None:
    shown, expected, dropped = drift_and_compare_with_sync(
        app, probe, lambda c: c._project["model"]["measures"][0].__setitem__("expression", "COUNTROWS(t)")
    )
    assert dropped >= 1 and shown == expected and shown[0]["Qty Sum"] != text_of(qty_sum())


def test_the_key_changes_with_the_physical_table_name_alone(app: StudioController, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(DuckStore, "table_version", lambda self, name: 3)  # the versions cannot tell the tables apart
    base = card_key(app)
    candidate = app._active_store_candidate
    physical = candidate.store_table
    candidate.store_table = physical + "_g2"
    try:
        assert card_key(app) != base
    finally:
        candidate.store_table = physical
    assert card_key(app) == base


def test_a_filter_added_under_a_running_visual_is_never_shown_as_the_old_series(
    app: StudioController, probe: PlanProbe
) -> None:
    import copy

    title = make_bar(app)
    wait_store_idle(app)
    assert app._add_report_filter(
        table_id=app._active_model_table_id(), column="product", operator="is_any_of", value="",
        multi_values=["P01"], report_scope=True,
    ), app.statusMessage
    saved_filter = copy.deepcopy(app._project["report"]["filters"][0])
    assert app._remove_filter("report", 0)
    wait_store_idle(app)
    unfiltered = read_visual_when_ready(app, title)
    gate = probe.gate("GROUP BY")
    app._refresh_report()
    wait_store_idle(app)
    assert app.visualSeries(title) == []
    wait_or_fail(gate.started, "the visual inside its query")
    dropped0 = app._store_dropped
    app._project["report"]["filters"].append(saved_filter)  # no refresh: only the key can tell
    gate.release.set()
    wait_store_idle(app)
    assert app._store_dropped > dropped0
    shown = read_visual_when_ready(app, title)
    app._store_async = False
    try:
        expected = app.visualSeries(title)
    finally:
        app._store_async = True
    assert shown == expected and shown != unfiltered


def test_a_model_change_under_a_running_preview_asks_again(app: StudioController, probe: PlanProbe) -> None:
    gate = probe.gate("qty")
    done: list[str] = []
    app._preview_measure_expression_async("Draft", "SUM(t[qty])", done.append)
    wait_or_fail(gate.started, "the preview inside its query")
    home = app._active_model_table_id()
    app._project["model"]["measures"].append(normalize_measure("Zed", "COUNTROWS(t)", home_table_id=home))  # no refresh
    gate.release.set()
    wait_store_idle(app)
    assert probe.count(match="qty") == 2, "the answer for the old model is dropped and the preview runs again"
    assert done == [text_of(qty_sum())] and app._preview_busy_request_id is None


def test_a_rebind_changes_the_identity_and_an_answer_queued_before_it_is_dropped(
    app: StudioController, probe: PlanProbe, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(DuckStore, "table_version", lambda self, name: 5)  # the identity alone must tell the stores apart
    project_store = app._project_store
    before_key, before_ident = card_key(app), app._store_ident()
    finished0 = len(probe.finished)
    app._refresh_report()
    for _ in range(10_000):  # the worker answers; nothing is delivered because this thread runs no event loop
        if len(probe.finished) >= finished0 + len(CARDS) and lease_count(app) == 0:
            break
        time.sleep(0.001)
    assert len(probe.finished) >= finished0 + len(CARDS) and lease_count(app) == 0, "the worker did not finish"
    project_store.checkpoint()
    copy_path = tmp_path / "copy.npa.data"
    project_store.copy_to(str(copy_path))
    project_store.rebind(str(copy_path), delete_old=False)  # another DuckStore under the same session object
    assert app._store_ident() != before_ident and card_key(app) != before_key
    dropped0, applied0 = app._store_dropped, app._store_applied
    wait_store_idle(app)  # the three answers from before the rebind arrive now
    assert app._store_dropped - dropped0 == len(CARDS), "answers computed on the old store must be dropped"
    assert app._store_applied - applied0 == len(CARDS), "and asked again on the new one"
    assert app._measure_values["Qty Sum"] == text_of(qty_sum()) and lease_count(app) == 0


def test_save_as_bumps_the_store_identity(
    app: StudioController, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_dialogs(monkeypatch)
    bumps: list[int] = []
    original = StudioController._bump_store_identity
    monkeypatch.setattr(StudioController, "_bump_store_identity", lambda self: (bumps.append(1), original(self))[1])
    assert app._save_to(tmp_path / "saved2.npa") is True, app.statusMessage
    assert bumps, "the session moved to another data file: the identity must change at once"
    wait_store_idle(app)


# ---------------------------------------------------------------------------------------------------
# F3: card tiles, timeouts, the preview id, the interactive refresh, threads
# ---------------------------------------------------------------------------------------------------
def test_a_card_result_writes_the_kpi_tile_too(app: StudioController) -> None:
    for name, _ in CARDS:
        assert app._kpis[name] == app._measure_values[name] != CALCULATING_TEXT
    assert app._kpis["Qty Sum"] == text_of(qty_sum())


def test_a_timeout_offers_calculate_again_and_stops_sticking_once_the_cause_is_gone(
    app: StudioController, probe: PlanProbe, monkeypatch: pytest.MonkeyPatch
) -> None:
    from analytics_studio.store import dax_route

    monkeypatch.setattr(dax_route, "BACKGROUND_BUDGET_S", 0.3)  # the stoppable query never ends by itself
    stuck = probe.stoppable("qty")
    app._refresh_report()
    wait_store_idle(app)
    assert len(probe.interrupted) == 1
    assert "took longer than 0.3 seconds" in app._measure_errors["Qty Sum"]
    assert app._measure_values["Row Count"] == text_of(SMALL_ROWS), "the other cards are fine"
    assert app.storeCanRecalculate is True, "Calculate again is offered after a timeout"
    calls0 = probe.count()
    for _ in range(3):  # the timeout sticks per key: a read starts nothing
        app.modelMeasures
        app.visualSeries("nothing")
    wait_store_idle(app)
    assert probe.count() == calls0 and "took longer" in app._measure_errors["Qty Sum"]
    assert stuck.hits == 1
    app.recalculateStore()  # the cause is gone (the rule was used once)
    wait_store_idle(app)
    assert app._measure_values["Qty Sum"] == text_of(qty_sum()) and app._measure_errors == {}
    assert app.storeCanRecalculate is False


def test_a_canceled_visual_of_another_page_does_not_keep_the_banner(app: StudioController, probe: PlanProbe) -> None:
    first_page = app._active_page_id
    app.add_page()
    second_page = next(p["id"] for p in app._project["report"]["pages"] if p["id"] != first_page)
    app._active_page_id = first_page
    title = make_bar(app)
    wait_store_idle(app)
    gate = probe.gate("GROUP BY")
    assert app.visualSeries(title) == []
    wait_or_fail(gate.started, "the visual inside its query")
    app.cancelStoreCalculations()
    gate.release.set()
    wait_store_idle(app)
    assert app.visualErrorMessage(title) == CANCELED_TEXT
    assert app.storeCanRecalculate is True
    app._active_page_id = second_page  # the visual is not on screen now (no refresh: its state is still there)
    assert app.storeCanRecalculate is False
    app._active_page_id = first_page
    assert app.storeCanRecalculate is True
    app.recalculateStore()
    assert app.storeCanRecalculate is False
    assert app.visualSeries(title) == []
    wait_store_idle(app)
    assert len(app.visualSeries(title)) == 2


def test_the_canceled_sentence_names_the_button(app: StudioController) -> None:
    from pathlib import Path as _Path

    qml = (_Path(__file__).resolve().parents[1] / "analytics_studio" / "qml" / "Main.qml").read_text(encoding="utf-8")
    assert 'text: "Calculate again"' in qml and CANCELED_TEXT.endswith("press Calculate again.")


@pytest.mark.parametrize("entry", ["region", "report filter", "cross filter"])
def test_the_interactive_refresh_stops_the_running_visual_request_and_clears_results(
    app: StudioController, probe: PlanProbe, entry: str
) -> None:
    """QML refreshes through `_refresh_report_async`: it must reset the requests like `_refresh_report` does."""
    title = make_bar(app, "V1 qty by product", "product")
    app.add_visual("slicer", "Region slicer", 0, 0, 300, 200)
    app.add_field_to_well("Fields", "region")
    wait_store_idle(app)
    stuck = probe.stoppable("GROUP BY")
    assert app.visualSeries(title) == []
    wait_or_fail(stuck.started, "the visual inside its query")
    if entry == "region":
        app.setRegionFilterInteractive("East")
    elif entry == "report filter":
        assert app._add_report_filter(
            table_id=app._active_model_table_id(), column="region", operator="is_any_of", value="",
            multi_values=["East"], report_scope=True, async_refresh=True,
        ), app.statusMessage
    else:
        app.toggle_cross_filter("Region slicer", "East")
    # nothing read the visual again: only the refresh itself can have stopped its query
    for _ in range(int(GUARD_S / 0.001)):
        if probe.interrupted:
            break
        QApplication.processEvents()
        time.sleep(0.001)
    assert len(probe.interrupted) == 1, "the refresh must stop the visual query"
    assert not any(slot[0] == "visual" for slot in app._store_state), "results of the old state are not kept"
    wait_store_idle(app)
    assert app._measure_values["Qty Sum"] == text_of(qty_sum(parity=0)), "the cards follow the filter"


def test_a_preview_answer_for_a_superseded_request_id_is_not_delivered_and_the_preview_restarts(
    app: StudioController, probe: PlanProbe
) -> None:
    gate = probe.gate("qty")
    done: list[str] = []
    app._preview_measure_expression_async("Draft", "SUM(t[qty])", done.append)
    wait_or_fail(gate.started, "the preview inside its query")
    gate.release.set()
    for _ in range(10_000):  # the answer is on its way to this thread, not delivered yet
        if probe.finished and lease_count(app) == 0:
            break
        time.sleep(0.001)
    app._cancel_and_wait_preview()  # an engine call: the id moves on and the job restarts after the call
    wait_store_idle(app)
    for _ in range(50):
        QApplication.processEvents()
        if probe.count(match="qty") >= 2:
            break
    wait_store_idle(app)
    assert probe.count(match="qty") == 2, "the preview must run again after the engine call"
    assert done == [text_of(qty_sum())], done


class ThreadCheckedDict(dict):
    """A dict that records every write made from a thread other than the GUI thread."""

    def __init__(self, name: str, violations: list[tuple[str, str, str]], gui: int, *args: Any) -> None:
        super().__init__(*args)
        self._name, self._violations, self._gui = name, violations, gui

    def _check(self, op: str) -> None:
        if threading.get_ident() != self._gui:
            self._violations.append((self._name, op, threading.current_thread().name))

    def __setitem__(self, key: Any, value: Any) -> None:
        self._check("set")
        super().__setitem__(key, value)

    def __delitem__(self, key: Any) -> None:
        self._check("del")
        super().__delitem__(key)

    def pop(self, *args: Any) -> Any:
        self._check("pop")
        return super().pop(*args)

    def clear(self) -> None:
        self._check("clear")
        super().clear()

    def update(self, *args: Any, **kwargs: Any) -> None:
        self._check("update")
        super().update(*args, **kwargs)

    def setdefault(self, *args: Any) -> Any:
        self._check("setdefault")
        return super().setdefault(*args)



def test_no_controller_state_is_written_off_the_gui_thread_and_the_compute_functions_run_on_the_worker(
    app: StudioController, probe: PlanProbe, monkeypatch: pytest.MonkeyPatch
) -> None:
    gui = threading.get_ident()
    violations: list[tuple[str, str, str]] = []
    tracked = ("_measure_values", "_kpis", "_measure_errors", "_store_state", "_store_preview_params")
    original_setattr = StudioController.__setattr__

    def tracking_setattr(self: Any, name: str, value: Any) -> None:
        if threading.get_ident() != gui:
            violations.append(("attribute", name, threading.current_thread().name))
        if name in tracked and isinstance(value, dict) and not isinstance(value, ThreadCheckedDict):
            value = ThreadCheckedDict(name, violations, gui, value)
        original_setattr(self, name, value)

    monkeypatch.setattr(StudioController, "__setattr__", tracking_setattr)
    for name in tracked:
        setattr(app, name, getattr(app, name) or {})
    gui_only = (
        "_store_ordered_rows", "_store_visual_spec", "_store_slot_key", "_store_snapshot", "_apply_store_result",
        "_apply_store_card", "_apply_store_visual", "_store_filter_context", "_notice_silent_message", "_set_status",
        "_refresh_report", "_store_key_base", "_store_closure", "_on_store_result", "_store_after_drop",
    )

    def guard(name: str) -> None:
        method = getattr(StudioController, name)

        def checked(*args: Any, **kwargs: Any) -> Any:
            if threading.get_ident() != gui:
                violations.append(("method", name, threading.current_thread().name))
            return method(*args, **kwargs)

        monkeypatch.setattr(StudioController, name, checked)

    for name in gui_only:
        guard(name)
    ran: list[tuple[str, bool]] = []

    def watch(name: str) -> None:
        function = getattr(StudioController, name)

        def computing(*args: Any, **kwargs: Any) -> Any:
            ran.append((name, threading.get_ident() != gui))
            return function(*args, **kwargs)

        monkeypatch.setattr(StudioController, name, staticmethod(computing))

    for name in ("_store_card_compute", "_store_visual_compute", "_store_preview_compute"):
        watch(name)
    emits_off_thread: list[int] = []
    app.stateChanged.connect(lambda: emits_off_thread.append(0) if threading.get_ident() != gui else None)

    make_bar(app, "V1 qty by region")
    make_bar(app, "V2 qty by product", "product")
    wait_store_idle(app)
    violations.clear()
    ran.clear()
    for step in range(3):
        app._refresh_report()
        for title in ("V1 qty by region", "V2 qty by product"):
            app.visualSeries(title)
        wait_store_idle(app)
        for title in ("V1 qty by region", "V2 qty by product"):
            app.visualSeries(title)
        app.setRegionFilter(["East", "West", "All regions"][step])
        wait_store_idle(app)
    done: list[str] = []
    app._preview_measure_expression_async("Draft", "SUM(t[qty])", done.append)
    wait_store_idle(app)
    assert app.create_measure("Extra", "SUM(t[qty])") is True
    wait_store_idle(app)
    assert app.remove_measure("Extra") is True
    wait_store_idle(app)
    assert violations == [], f"controller state written off the GUI thread: {violations[:5]}"
    assert emits_off_thread == [], "stateChanged emitted off the GUI thread"
    kinds = {name for name, _ in ran}
    assert kinds == {"_store_card_compute", "_store_visual_compute", "_store_preview_compute"}, kinds
    assert all(on_worker for _name, on_worker in ran), "a compute function ran on the GUI thread"
    assert done == [text_of(qty_sum())], done


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
