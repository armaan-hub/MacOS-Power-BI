"""Tests of the large-table request manager (Stage C3b): `analytics_studio.store.route_requests`.

The manager only, no controller, a tiny real store. No wall-clock assertion anywhere: threads are synchronised with
Events and counters, a query that has to be stopped is the interrupt-on-demand query of tests/test_store_reader.py,
and the event-loop waits are hang guards (a fixed number of loop turns) that fail by assertion.
"""

from __future__ import annotations

import contextlib
import os
import random
import threading
import time
from pathlib import Path
from typing import Any, Callable

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, Slot
from PySide6.QtWidgets import QApplication

from analytics_studio.store import ProjectStore
from analytics_studio.store import dax_route, route_requests
from analytics_studio.store.base import StoreError
from analytics_studio.store.route_requests import (
    CALCULATING_TEXT,
    CANCELED_TEXT,
    StoreRequestManager,
    canceled_answer,
)
from tests.test_store_reader import COLUMNS, GUARD_S, Probe, make_batches, wait_or_fail

@pytest.fixture(scope="module")
def qapp() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication(["route request tests"])


def pump(predicate: Callable[[], bool], what: str) -> None:
    """Run the Qt event loop of this (the GUI) thread until predicate() holds; fail by assertion at the hang guard."""
    deadline = time.monotonic() + GUARD_S
    while not predicate() and time.monotonic() < deadline:
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        time.sleep(0.001)
    assert predicate(), f"{what} did not happen within the {GUARD_S:g} s hang guard"


class Receiver(QObject):
    """Records what the manager delivers, and on which thread the slot ran."""

    def __init__(self, manager: StoreRequestManager) -> None:
        super().__init__()
        self.finished: list[tuple[Any, Any, Any, int]] = []
        self.order: list[str] = []
        self.threads: list[int] = []
        manager.finished.connect(self.on_finished)
        manager.idle.connect(self.on_idle)

    @Slot(object, object, object, int)
    def on_finished(self, slot: Any, key: Any, answer: Any, request_id: int) -> None:
        self.finished.append((slot, key, answer, request_id))
        self.order.append("finished")
        self.threads.append(threading.get_ident())

    @Slot()
    def on_idle(self) -> None:
        self.order.append("idle")

    def answers(self) -> list[Any]:
        return [item[2] for item in self.finished]


@pytest.fixture
def ps(tmp_path: Path) -> Any:
    project_store = ProjectStore.open(str(tmp_path / "p.npa.data"))
    project_store.store.create_table_from_arrow("t", COLUMNS, make_batches())
    yield project_store
    project_store.shutdown(timeout=GUARD_S)


@pytest.fixture
def manager(qapp: QApplication, ps: Any) -> Any:
    mgr = StoreRequestManager(ps)
    yield mgr
    mgr.close(wait=True)


def idle(mgr: StoreRequestManager, what: str = "the manager to go idle") -> None:
    pump(lambda: mgr.pending() == 0, what)


def value_work(value: Any, ran: list[Any] | None = None) -> Callable[[Any, threading.Event], Any]:
    def work(reader: Any, cancel: threading.Event) -> Any:
        if ran is not None:
            ran.append(value)
        return value

    return work


class Blocker:
    """A request that holds the worker thread until released (it does not react to cancel: a slow answer)."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.saw_cancel = False

    def work(self, reader: Any, cancel: threading.Event) -> Any:
        self.started.set()
        if not self.release.wait(GUARD_S):
            self.release.set()
        self.saw_cancel = cancel.is_set()
        return "blocked-value"


def stoppable_work(started: threading.Event, outcome: list[str]) -> Callable[[Any, threading.Event], Any]:
    """The interrupt-on-demand query: runs until the manager interrupts the reader."""

    def work(reader: Any, cancel: threading.Event) -> Any:
        probe = Probe().install(reader)
        started.set()
        try:
            reader.execute(probe.query)
        except StoreError as exc:
            outcome.append("interrupted" if "interrupt" in str(exc).casefold() else f"failed: {exc}")
            raise
        outcome.append("finished normally")
        return "long-value"

    return work


def lease_count(ps: Any) -> int:
    return ps._readers  # the number of read leases open: every path must bring it back to 0


def test_a_request_gives_its_value_once_and_the_lease_is_released(manager: StoreRequestManager, ps: Any) -> None:
    receiver = Receiver(manager)
    request_id = manager.submit(("card", "A"), "key-a", value_work(42))
    assert manager.pending() == 1 and manager.has(("card", "A"))
    idle(manager)
    assert len(receiver.finished) == 1
    slot, key, answer, delivered_id = receiver.finished[0]
    assert (slot, key, answer, delivered_id) == (("card", "A"), "key-a", 42, request_id)
    assert not manager.has(("card", "A"))
    assert lease_count(ps) == 0


def test_receiver_runs_on_the_gui_thread_and_work_does_not(manager: StoreRequestManager) -> None:
    receiver = Receiver(manager)
    work_threads: list[int] = []

    def work(reader: Any, cancel: threading.Event) -> Any:
        work_threads.append(threading.get_ident())
        return "x"

    manager.submit(("card", "A"), "k", work)
    idle(manager)
    gui = threading.get_ident()
    assert receiver.threads == [gui], "the finished slot must run on the GUI thread"
    assert work_threads and work_threads[0] != gui, "work must run on the pool thread"


def test_idle_comes_after_the_last_finished_and_finished_once_per_request(manager: StoreRequestManager) -> None:
    receiver = Receiver(manager)
    for index in range(5):
        manager.submit(("card", f"M{index}"), f"k{index}", value_work(index))
    pump(lambda: "idle" in receiver.order, "the idle signal")
    assert receiver.order == ["finished"] * 5 + ["idle"], receiver.order
    assert sorted(item[0] for item in receiver.finished) == [("card", f"M{i}") for i in range(5)]


def test_a_newer_request_for_the_slot_cancels_the_older_and_only_the_newest_is_emitted(
    manager: StoreRequestManager, ps: Any
) -> None:
    receiver = Receiver(manager)
    started, outcome = threading.Event(), []
    slot = ("visual", "V", "Y-axis", False)
    manager.submit(slot, "old", stoppable_work(started, outcome))
    wait_or_fail(started, "the old query")
    manager.submit(slot, "new", value_work("fresh"))
    idle(manager)
    assert outcome == ["interrupted"], "the old query must be stopped, not run to its end"
    assert [(item[0], item[1], item[2]) for item in receiver.finished] == [(slot, "new", "fresh")]
    assert lease_count(ps) == 0


def test_a_queued_request_is_taken_out_when_its_slot_is_superseded(manager: StoreRequestManager) -> None:
    receiver = Receiver(manager)
    blocker = Blocker()
    ran: list[Any] = []
    manager.submit(("card", "first"), "k", blocker.work)
    wait_or_fail(blocker.started, "the blocking request")
    manager.submit(("card", "second"), "old", value_work("old", ran))
    manager.submit(("card", "second"), "new", value_work("new", ran))
    blocker.release.set()
    idle(manager)
    assert ran == ["new"], "the superseded queued request must never run"
    assert [item[2] for item in receiver.finished if item[0] == ("card", "second")] == ["new"]


def test_cancel_all_with_one_running_and_three_queued(manager: StoreRequestManager, ps: Any) -> None:
    receiver = Receiver(manager)
    started, outcome, ran = threading.Event(), [], []
    manager.submit(("card", "running"), "k", stoppable_work(started, outcome))
    wait_or_fail(started, "the running query")
    for index in range(3):
        manager.submit(("card", f"queued{index}"), "k", value_work(index, ran))
    assert manager.pending() == 4
    manager.cancel_all()
    idle(manager)
    assert ran == [], "a queued request must never run after cancel_all"
    assert outcome == ["interrupted"]
    assert len(receiver.finished) == 4
    assert all(isinstance(answer, dax_route.RouteRefusal) and answer.code == dax_route.CODE_CANCELED
               for answer in receiver.answers())
    assert lease_count(ps) == 0


def test_queued_requests_are_canceled_at_once_and_not_when_the_worker_frees_up(manager: StoreRequestManager) -> None:
    receiver = Receiver(manager)
    blocker = Blocker()
    ran: list[Any] = []
    manager.submit(("card", "blocker"), "k", blocker.work)
    wait_or_fail(blocker.started, "the blocking request")
    for index in range(3):
        manager.submit(("card", f"queued{index}"), "k", value_work(index, ran))
    manager.cancel_all()
    # The worker is still inside the blocking request; the three queued ones are already reported as canceled.
    assert sorted(item[0] for item in receiver.finished) == [("card", f"queued{i}") for i in range(3)]
    assert all(answer.code == dax_route.CODE_CANCELED for answer in receiver.answers())
    assert manager.pending() == 1 and not blocker.release.is_set()
    blocker.release.set()
    idle(manager)
    assert ran == [] and len(receiver.finished) == 4


def test_cancel_all_without_delivery_forgets_the_requests(manager: StoreRequestManager, ps: Any) -> None:
    receiver = Receiver(manager)
    started, outcome, ran = threading.Event(), [], []
    manager.submit(("card", "running"), "k", stoppable_work(started, outcome))
    wait_or_fail(started, "the running query")
    manager.submit(("card", "queued"), "k", value_work(1, ran))
    manager.cancel_all(wait=True, deliver=False)
    assert lease_count(ps) == 0 and ran == []
    idle(manager)
    assert receiver.finished == [], "nothing may be delivered for a request that was forgotten"
    assert not manager.has(("card", "running")) and not manager.has(("card", "queued"))


def test_cancel_all_can_keep_a_slot(manager: StoreRequestManager) -> None:
    receiver = Receiver(manager)
    blocker = Blocker()
    ran: list[Any] = []
    manager.submit(("card", "blocker"), "k", blocker.work)
    wait_or_fail(blocker.started, "the blocking request")
    manager.submit(("preview",), "k", value_work("kept", ran))
    manager.submit(("card", "other"), "k", value_work("dropped", ran))
    manager.cancel_all(deliver=False, keep=(("preview",), ("card", "blocker")))
    blocker.release.set()
    idle(manager)
    assert ran == ["kept"]
    assert sorted(str(item[0]) for item in receiver.finished) == sorted([str(("card", "blocker")), str(("preview",))])


def test_cancel_of_one_slot_delivers_canceled(manager: StoreRequestManager, ps: Any) -> None:
    receiver = Receiver(manager)
    started, outcome = threading.Event(), []
    manager.submit(("card", "A"), "k", stoppable_work(started, outcome))
    wait_or_fail(started, "the query")
    manager.cancel(("card", "A"))
    idle(manager)
    assert outcome == ["interrupted"]
    assert len(receiver.finished) == 1 and receiver.finished[0][2].code == dax_route.CODE_CANCELED
    assert lease_count(ps) == 0


def test_a_task_whose_work_raises_gives_a_refusal_and_the_manager_keeps_working(
    manager: StoreRequestManager, ps: Any
) -> None:
    receiver = Receiver(manager)

    def broken(reader: Any, cancel: threading.Event) -> Any:
        raise RuntimeError("boom")

    manager.submit(("card", "Bad"), "k1", broken)
    manager.submit(("card", "Good"), "k2", value_work("ok"))
    idle(manager)
    by_slot = {item[0]: item[2] for item in receiver.finished}
    bad = by_slot[("card", "Bad")]
    assert isinstance(bad, dax_route.RouteRefusal) and bad.code == dax_route.CODE_PLAN
    assert bad.message == "Bad could not be computed (RuntimeError)."
    assert by_slot[("card", "Good")] == "ok"
    assert lease_count(ps) == 0


def test_a_request_canceled_before_it_starts_takes_no_lease(
    manager: StoreRequestManager, ps: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    receiver = Receiver(manager)
    leases: list[int] = []
    original = ps.read_lease

    def counting_lease() -> Any:
        leases.append(1)
        return original()

    monkeypatch.setattr(ps, "read_lease", counting_lease)
    blocker = Blocker()
    ran: list[Any] = []
    manager.submit(("card", "blocker"), "k", blocker.work)
    wait_or_fail(blocker.started, "the blocking request")
    manager.submit(("card", "late"), "k", value_work("late", ran))
    # What ProjectStore.shutdown() does: the cancel hook sets every cancel event; the queued task is still in the pool.
    manager._cancel_all_hook()
    blocker.release.set()
    idle(manager)
    assert ran == [], "work must not run for a request canceled before it starts"
    assert sum(leases) == 1, "only the blocking request may have taken a lease"
    late = [item[2] for item in receiver.finished if item[0] == ("card", "late")]
    assert len(late) == 1 and late[0].code == dax_route.CODE_CANCELED


def test_a_canceled_task_never_emits_a_value(manager: StoreRequestManager) -> None:
    receiver = Receiver(manager)
    blocker = Blocker()
    manager.submit(("card", "A"), "k", blocker.work)
    wait_or_fail(blocker.started, "the blocking request")
    manager.cancel(("card", "A"))
    blocker.release.set()  # the work ignores the cancel and returns a value
    idle(manager)
    assert blocker.saw_cancel
    assert len(receiver.finished) == 1
    answer = receiver.finished[0][2]
    assert isinstance(answer, dax_route.RouteRefusal) and answer.code == dax_route.CODE_CANCELED


def test_a_busy_store_gives_a_busy_refusal_and_no_lease(manager: StoreRequestManager, ps: Any) -> None:
    receiver = Receiver(manager)
    with ps.job():
        manager.submit(("card", "A"), "k", value_work("never"))
        idle(manager)
    assert receiver.answers()[0].code == dax_route.CODE_BUSY
    assert receiver.answers()[0].message == dax_route.BUSY_MESSAGE
    assert lease_count(ps) == 0
    manager.submit(("card", "A"), "k2", value_work("now"))
    idle(manager)
    assert receiver.answers()[-1] == "now"


def test_a_closed_store_gives_a_closed_refusal(qapp: QApplication, tmp_path: Path) -> None:
    project_store = ProjectStore.open(str(tmp_path / "c.npa.data"))
    mgr = StoreRequestManager(project_store)
    receiver = Receiver(mgr)
    try:
        assert project_store.shutdown(timeout=GUARD_S)
        mgr.submit(("card", "A"), "k", value_work("never"))
        idle(mgr)
        assert receiver.answers()[0].code == dax_route.CODE_CLOSED
        assert "closed" in receiver.answers()[0].message
    finally:
        mgr.close(wait=True)


def test_close_stops_a_running_query_and_is_idempotent(qapp: QApplication, ps: Any) -> None:
    mgr = StoreRequestManager(ps)
    receiver = Receiver(mgr)
    started, outcome, ran = threading.Event(), [], []
    mgr.submit(("card", "running"), "k", stoppable_work(started, outcome))
    wait_or_fail(started, "the running query")
    mgr.submit(("card", "queued"), "k", value_work(1, ran))
    mgr.close(wait=True)
    assert outcome == ["interrupted"] and ran == []
    assert lease_count(ps) == 0 and mgr.pending() == 0
    mgr.close(wait=True)  # idempotent
    mgr.close(wait=False)
    QCoreApplication.processEvents()
    assert receiver.finished == [], "a closed manager delivers nothing"
    with pytest.raises(StoreError):
        mgr.submit(("card", "again"), "k", value_work(2))


def test_the_cancel_hook_is_registered_and_removed(qapp: QApplication, ps: Any) -> None:
    mgr = StoreRequestManager(ps)
    assert mgr._cancel_all_hook in ps._cancel_hooks
    mgr.close(wait=True)
    assert mgr._cancel_all_hook not in ps._cancel_hooks


def test_store_shutdown_stops_the_requests_through_the_hook(qapp: QApplication, ps: Any) -> None:
    mgr = StoreRequestManager(ps)
    Receiver(mgr)
    started, outcome = threading.Event(), []
    mgr.submit(("card", "running"), "k", stoppable_work(started, outcome))
    wait_or_fail(started, "the running query")
    assert ps.shutdown(timeout=GUARD_S) is True
    assert outcome == ["interrupted"]
    mgr.close(wait=True)


def test_lease_count_returns_to_zero_after_a_random_mix_of_paths(manager: StoreRequestManager, ps: Any) -> None:
    receiver = Receiver(manager)
    rnd = random.Random(20261127)
    submitted = 0
    for round_no in range(60):
        slot = ("card", f"M{rnd.randrange(6)}")
        choice = rnd.choice(["value", "raise", "cancel", "supersede"])

        def work(reader: Any, cancel: threading.Event, choice: str = choice) -> Any:
            if choice == "raise":
                raise ValueError("x")
            return reader.execute("SELECT count(*) FROM t")[0][0]

        manager.submit(slot, f"k{round_no}", work)
        submitted += 1
        if choice == "cancel":
            manager.cancel(slot)
        elif choice == "supersede":
            manager.submit(slot, f"s{round_no}", value_work("s"))
    idle(manager)
    assert lease_count(ps) == 0 and manager.pending() == 0
    assert len({(item[0], item[3]) for item in receiver.finished}) == len(receiver.finished), "one answer per request"
    # Whatever happened, a plain request still works afterwards.
    receiver.finished.clear()
    manager.submit(("card", "after"), "k", lambda reader, cancel: reader.execute("SELECT count(*) FROM t")[0][0])
    idle(manager)
    assert receiver.answers() == [5000]


def test_the_sentences_of_the_user_visible_states_are_plain() -> None:
    assert CALCULATING_TEXT == "Calculating..."
    assert CANCELED_TEXT == "Canceled. Change a filter or press Calculate again."
    assert canceled_answer().code == dax_route.CODE_CANCELED
    # the timeout and busy sentences come from the route: the timeout names its 30 seconds
    timeout = dax_route._timeout("Total", dax_route.BACKGROUND_BUDGET_S)
    assert "30 seconds" in timeout.message and timeout.code == dax_route.CODE_TIMEOUT
    assert dax_route.BUSY_MESSAGE.endswith("try again when it finishes.")


def test_a_cancel_that_lands_before_the_reader_is_published_still_interrupts_it(
    qapp: QApplication, ps: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """cancel() sees no reader before the task publishes it; the task must interrupt the reader itself then."""
    mgr = StoreRequestManager(ps)
    receiver = Receiver(mgr)
    interrupts: list[int] = []
    ran: list[Any] = []
    real_lease = ps.read_lease

    class CountingReader:
        def __init__(self, reader: Any) -> None:
            self._reader = reader

        def interrupt(self) -> None:
            interrupts.append(1)
            self._reader.interrupt()

        def __getattr__(self, name: str) -> Any:
            return getattr(self._reader, name)

    @contextlib.contextmanager
    def lease() -> Any:
        with real_lease() as reader:
            mgr._cancel_all_hook()  # the cancel lands now: the lease is open, the reader is not published yet
            yield CountingReader(reader)

    monkeypatch.setattr(ps, "read_lease", lease)
    try:
        mgr.submit(("card", "A"), "k", value_work("never", ran))
        idle(mgr)
        assert interrupts == [1], "the late cancel must interrupt the reader that was just published"
        assert ran == [] and receiver.answers()[0].code == dax_route.CODE_CANCELED
        assert lease_count(ps) == 0
    finally:
        mgr.close(wait=True)


def test_close_waits_a_second_time_for_a_query_that_ignores_the_interrupt(
    qapp: QApplication, ps: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(route_requests, "_CLOSE_WAIT_FIRST_MS", 1)  # the first wait gives up at once
    mgr = StoreRequestManager(ps)
    blocker = Blocker()
    mgr.submit(("card", "A"), "k", blocker.work)
    wait_or_fail(blocker.started, "the blocking request")
    timer = threading.Timer(0.3, blocker.release.set)  # frees the query while close() is in its second wait
    timer.start()
    try:
        mgr.close(wait=True)
        assert lease_count(ps) == 0, "close(wait=True) returned while the query still held its lease"
    finally:
        blocker.release.set()
        timer.cancel()
