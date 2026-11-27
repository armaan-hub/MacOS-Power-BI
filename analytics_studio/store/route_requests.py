"""Background requests for the large-table DAX route (Stage C3b).

One worker thread runs one request at a time. A request is a plain function `work(reader, cancel)` that the
controller builds on the GUI thread; the task opens a read lease, runs the function on that lease's own reader and
hands the answer back through a Qt signal, so the GUI thread is the only place where results are applied.

A request belongs to a SLOT (what is being calculated, for example ("card", "Total")) and has a KEY (everything that
decides the answer). A slot has at most one live request: submitting a new one cancels the older one. The manager
emits `finished` only for the newest request of a slot, on the GUI thread; an answer of a superseded request is
dropped here and never reaches the controller.

The manager's dictionaries are touched on the GUI thread only. A task's own state is under its lock.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Hashable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from analytics_studio.measure_tasks import create_measure_thread_pool

from . import dax_route
from .base import StoreBusyError, StoreError

logger = logging.getLogger(__name__)

# One worker thread keeps cancel and ordering simple (whether two would be faster is not measured).
WORKER_THREADS = 1
_CLOSE_WAIT_FIRST_MS = 2000
_CLOSE_WAIT_SECOND_MS = 5000

# The sentences of the states a card or a visual shows while it has no value. Refusals, timeouts and busy keep the
# route's own sentences (dax_route.FRAGMENTS, DEADLINE/BUSY_MESSAGE, "took longer than 30 seconds").
CALCULATING_TEXT = "Calculating..."
CANCELED_TEXT = "Canceled. Change a filter or press Refresh to calculate again."
PREVIEW_SLOT = ("preview",)


def _slot_label(slot: Hashable) -> str:
    if isinstance(slot, tuple) and len(slot) > 1:
        return str(slot[1])
    if isinstance(slot, tuple) and slot:
        return str(slot[0])
    return str(slot)


def canceled_answer() -> Any:
    return dax_route.RouteRefusal(dax_route.CANCELED_MESSAGE, dax_route.CANCELED_REASON, dax_route.CODE_CANCELED)


class StoreRouteTask(QRunnable):
    """One request on the pool thread: lease, work, answer, release. Emits exactly once."""

    def __init__(
        self,
        manager: "StoreRequestManager",
        request_id: int,
        slot: Hashable,
        key: Hashable,
        work: Callable[[Any, threading.Event], Any],
        project_store: Any,
    ) -> None:
        super().__init__()
        self.setAutoDelete(False)  # the manager may tryTake() it: Python owns it
        self.request_id = request_id
        self.slot = slot
        self.key = key
        self.cancel_event = threading.Event()
        self._manager = manager
        self._work = work
        self._project_store = project_store
        self._lock = threading.Lock()
        self._reader: Any = None
        self._emitted = False

    def cancel(self) -> None:
        """Stop this request: the event first, then the reader's running query (if the lease is already open)."""
        self.cancel_event.set()
        with self._lock:
            reader = self._reader
        if reader is not None:
            try:
                reader.interrupt()
            except Exception:  # an interrupt must never raise into the caller
                pass

    def _publish_reader(self, reader: Any) -> None:
        with self._lock:
            self._reader = reader
        if reader is not None and self.cancel_event.is_set():
            # cancel() ran between the lease and this line: it saw no reader, so interrupt here.
            try:
                reader.interrupt()
            except Exception:
                pass

    def emit_once(self, answer: Any) -> None:
        with self._lock:
            if self._emitted:
                return
            self._emitted = True
        try:
            self._manager._done.emit(self.request_id, self.slot, self.key, answer)
        except RuntimeError:  # the manager was deleted: nobody is waiting for the answer
            logger.debug("route request %s finished after its manager was deleted", self.request_id)

    def run(self) -> None:
        name = _slot_label(self.slot)
        answer: Any
        try:
            answer = self._run()
        except BaseException as exc:  # nothing may escape a pool thread
            if self.cancel_event.is_set():
                answer = canceled_answer()
            else:
                answer = dax_route.RouteRefusal(
                    f"{name} could not be computed ({type(exc).__name__}).", repr(exc), dax_route.CODE_PLAN
                )
        if self.cancel_event.is_set() and not _is_refusal(answer):
            answer = canceled_answer()  # a canceled task never emits a value
        self.emit_once(answer)

    def _run(self) -> Any:
        if self.cancel_event.is_set():
            return canceled_answer()  # no lease is taken
        entered = False
        try:
            with self._project_store.read_lease() as reader:
                entered = True
                self._publish_reader(reader)
                try:
                    if self.cancel_event.is_set():
                        return canceled_answer()
                    return self._work(reader, self.cancel_event)
                finally:
                    with self._lock:
                        self._reader = None
        except StoreBusyError:
            if entered:
                raise
            return dax_route.RouteRefusal(dax_route.BUSY_MESSAGE, "store busy", dax_route.CODE_BUSY)
        except StoreError as exc:
            if entered:
                raise
            return dax_route.RouteRefusal(
                f"{_slot_label(self.slot)} cannot be computed: the large table is closed.", str(exc), dax_route.CODE_CLOSED
            )


def _is_refusal(answer: Any) -> bool:
    return isinstance(answer, dax_route.RouteRefusal)


class StoreRequestManager(QObject):
    """Runs route requests on one worker thread and delivers the newest answer of each slot on the GUI thread.

    Create it on the GUI thread. `finished(slot, key, answer, request_id)` is emitted on the GUI thread; `idle()` is
    emitted on the GUI thread, after the last `finished`, when no request is queued or running any more.
    """

    finished = Signal(object, object, object, int)
    idle = Signal()
    _done = Signal(int, object, object, object)  # pool thread -> GUI thread

    def __init__(self, project_store: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._project_store = project_store
        self._pool: QThreadPool = create_measure_thread_pool()
        self._pool.setMaxThreadCount(WORKER_THREADS)
        self._tasks: dict[int, StoreRouteTask] = {}  # request id -> task, every request not yet delivered
        self._by_slot: dict[Hashable, int] = {}  # slot -> id of its live request
        self._next_id = 0
        self._closed = False
        self._hook_registered = False
        self._done.connect(self._on_done)
        self._register_hook()

    # -- hooks -----------------------------------------------------------------------------------------------
    def _register_hook(self) -> None:
        if self._hook_registered or self._project_store is None:
            return
        add = getattr(self._project_store, "add_cancel_hook", None)
        if add is not None:
            add(self._cancel_all_hook)
            self._hook_registered = True

    def _cancel_all_hook(self) -> None:
        """Called by ProjectStore.shutdown() / request_cancel_readers() from any thread: stop what is running now.

        Only task state is touched (no manager dictionary): the GUI thread owns those.
        """
        for task in list(self._tasks.values()):
            task.cancel()

    # -- state ------------------------------------------------------------------------------------------------
    @property
    def project_store(self) -> Any:
        return self._project_store

    def pending(self) -> int:
        """Requests queued or running whose answer has not been delivered yet."""
        return len(self._tasks)

    def has(self, slot: Hashable) -> bool:
        return slot in self._by_slot

    # -- submit and cancel --------------------------------------------------------------------------------------
    def submit(self, slot: Hashable, key: Hashable, work: Callable[[Any, threading.Event], Any]) -> int:
        """Queue `work(reader, cancel)` for `slot`; cancels the older request of that slot. Returns the request id."""
        if self._closed:
            raise StoreError("The request manager is closed.")
        self._register_hook()
        older = self._by_slot.get(slot)
        if older is not None:
            self._cancel_task(older, deliver=False)
        self._next_id += 1
        request_id = self._next_id
        task = StoreRouteTask(self, request_id, slot, key, work, self._project_store)
        self._tasks[request_id] = task
        self._by_slot[slot] = request_id
        self._pool.start(task)
        return request_id

    def _cancel_task(self, request_id: int, *, deliver: bool) -> None:
        """Cancel one request. A queued one is taken out of the pool and ends at once; a running one is interrupted.

        With deliver=False the slot forgets the request, so its answer is swallowed when it arrives.
        """
        task = self._tasks.get(request_id)
        if task is None:
            return
        slot = task.slot
        if not deliver and self._by_slot.get(slot) == request_id:
            del self._by_slot[slot]
        if self._pool.tryTake(task):
            # It never started: no lease, no query. Finish it here.
            task.cancel_event.set()
            task.emit_once(canceled_answer())
            return
        task.cancel()

    def cancel(self, slot: Hashable, *, deliver: bool = True) -> None:
        """Cancel the live request of a slot. Its "canceled" answer is delivered unless deliver is False."""
        request_id = self._by_slot.get(slot)
        if request_id is not None:
            self._cancel_task(request_id, deliver=deliver)

    def cancel_all(self, wait: bool = False, *, deliver: bool = True, keep: tuple[Hashable, ...] = ()) -> None:
        """Cancel every request: running ones are interrupted, queued ones never run.

        deliver=True reports each as canceled; deliver=False forgets them (for a data change: the controller recomputes).
        Requests of the slots in `keep` are left alone. With wait=True the call returns when the worker thread is
        free (the leases are released); wait with `keep` slots would wait for those too, so do not combine them.
        """
        for request_id, task in list(self._tasks.items()):
            if task.slot in keep:
                continue
            self._cancel_task(request_id, deliver=deliver)
        if wait:
            self._wait_for_pool()

    def _wait_for_pool(self) -> None:
        if not self._pool.waitForDone(_CLOSE_WAIT_FIRST_MS):
            for task in list(self._tasks.values()):
                task.cancel()
            self._pool.waitForDone(_CLOSE_WAIT_SECOND_MS)

    def close(self, wait: bool = True) -> None:
        """Cancel everything, wait for the worker and stop delivering. Idempotent."""
        if self._closed:
            return
        self._closed = True
        for request_id in list(self._tasks):
            self._cancel_task(request_id, deliver=False)
        if self._hook_registered:
            remove = getattr(self._project_store, "remove_cancel_hook", None)
            if remove is not None:
                remove(self._cancel_all_hook)
            self._hook_registered = False
        if wait:
            self._wait_for_pool()
        self._tasks.clear()
        self._by_slot.clear()

    # -- delivery (GUI thread) --------------------------------------------------------------------------------
    @Slot(int, object, object, object)
    def _on_done(self, request_id: int, slot: Any, key: Any, answer: Any) -> None:
        task = self._tasks.pop(request_id, None)
        if task is None or self._closed:
            return  # closed or cleared: nobody waits for it
        live = self._by_slot.get(slot) == request_id
        if live:
            del self._by_slot[slot]
            try:
                self.finished.emit(slot, key, answer, request_id)
            except Exception:  # a receiver must never break the manager
                logger.exception("A route request receiver raised")
        if not self._tasks:
            self.idle.emit()
