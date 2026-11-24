"""Unit tests for StoreJob worker."""

import os
import threading
import time
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QThreadPool
from PySide6.QtWidgets import QApplication, QProgressDialog

from analytics_studio.store.base import StoreError
from analytics_studio.store.csv_import import ImportCancelledError
from analytics_studio.store.jobs import ProgressDialogBinder, StoreJob
from analytics_studio.store.session import ProjectStore


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        core = QCoreApplication.instance()
        if core is not None:
            app = core
        else:
            app = QApplication([])
    return app


@pytest.fixture
def project_store(tmp_path):
    data_file = str(tmp_path / "test_job.npa.data")
    ps = ProjectStore.open(data_file)
    try:
        yield ps
    finally:
        ps.close()


def _drain_events(app, timeout: float = 2.0, condition=lambda: False):
    """Process Qt events until condition is True or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    app.processEvents()
    return condition()


def test_success_path_with_result(qapp, project_store):
    pool = QThreadPool()
    events = []

    def work(store, cancel_evt, progress):
        progress("working", 1, 2)
        progress("done", 2, 2)
        return {"row_count": 42}

    job = StoreJob(project_store, work, title="Success Job")
    job.signals.progress.connect(lambda msg, d, t: events.append(("progress", msg, d, t)))
    job.signals.finished.connect(lambda res: events.append(("finished", res)))
    job.signals.done.connect(lambda: events.append(("done",)))

    job.start(pool)
    assert pool.waitForDone(2000)
    _drain_events(qapp, 1.0, condition=lambda: ("done",) in events)

    assert not project_store.busy
    assert ("progress", "working", 1, 2) in events
    assert ("progress", "done", 2, 2) in events
    assert ("finished", {"row_count": 42}) in events
    assert events[-1] == ("done",)
    assert events.count(("done",)) == 1


def test_progress_signals_carry_values_in_order(qapp, project_store):
    pool = QThreadPool()
    progress_values = []

    def work(store, cancel_evt, progress):
        for i in range(1, 5):
            progress(f"step_{i}", i, 4)
        return "ok"

    job = StoreJob(project_store, work)
    job.signals.progress.connect(lambda msg, d, t: progress_values.append((msg, d, t)))

    done_flag = [False]
    job.signals.done.connect(lambda: done_flag.__setitem__(0, True))

    job.start(pool)
    assert pool.waitForDone(2000)
    _drain_events(qapp, 1.0, condition=lambda: done_flag[0])

    expected = [(f"step_{i}", i, 4) for i in range(1, 5)]
    assert progress_values == expected


def test_failure_messages(qapp, project_store):
    pool = QThreadPool()

    # 1. StoreError
    def work_store_err(store, cancel_evt, progress):
        raise StoreError("Store is corrupted")

    job1 = StoreJob(project_store, work_store_err)
    err1 = []
    job1.signals.failed.connect(lambda msg: err1.append(msg))
    job1.start(pool)
    assert pool.waitForDone(2000)
    _drain_events(qapp, 1.0, condition=lambda: len(err1) > 0)
    assert err1 == ["Store is corrupted"]
    assert not project_store.busy

    # 2. ValueError
    def work_val_err(store, cancel_evt, progress):
        raise ValueError("Invalid column count")

    job2 = StoreJob(project_store, work_val_err)
    err2 = []
    job2.signals.failed.connect(lambda msg: err2.append(msg))
    job2.start(pool)
    assert pool.waitForDone(2000)
    _drain_events(qapp, 1.0, condition=lambda: len(err2) > 0)
    assert err2 == ["Invalid column count"]
    assert not project_store.busy

    # 3. Unexpected RuntimeError
    def work_runtime_err(store, cancel_evt, progress):
        raise RuntimeError("Disk unplugged")

    job3 = StoreJob(project_store, work_runtime_err)
    err3 = []
    job3.signals.failed.connect(lambda msg: err3.append(msg))
    job3.start(pool)
    assert pool.waitForDone(2000)
    _drain_events(qapp, 1.0, condition=lambda: len(err3) > 0)
    assert err3 == ["Unexpected error: RuntimeError: Disk unplugged"]
    assert not project_store.busy


def test_cancel_mid_job(qapp, project_store):
    pool = QThreadPool()
    events = []

    def work(store, cancel_evt, progress):
        while not cancel_evt.is_set():
            time.sleep(0.01)
        raise ImportCancelledError("Canceled by user")

    job = StoreJob(project_store, work)
    job.signals.canceled.connect(lambda: events.append("canceled"))
    job.signals.done.connect(lambda: events.append("done"))

    job.start(pool)
    # Trigger cancellation
    time.sleep(0.02)
    job.cancel()

    assert pool.waitForDone(2000)
    _drain_events(qapp, 1.0, condition=lambda: "done" in events)

    assert not project_store.busy
    assert "canceled" in events
    assert events[-1] == "done"


def test_busy_store_refuses_start_and_fn_never_runs(qapp, project_store):
    pool = QThreadPool()
    fn_ran = [False]

    def work(store, cancel_evt, progress):
        fn_ran[0] = True

    # Artificially acquire job context
    with project_store.job():
        job = StoreJob(project_store, work)
        with pytest.raises(StoreError, match="The store is busy"):
            job.start(pool)

    assert not fn_ran[0]
    assert not project_store.busy


def test_store_is_busy_between_start_and_first_line_of_fn(qapp, project_store):
    pool = QThreadPool()
    started_evt = threading.Event()
    continue_evt = threading.Event()

    def work(store, cancel_evt, progress):
        started_evt.set()
        continue_evt.wait(timeout=2.0)

    job = StoreJob(project_store, work)
    job.start(pool)
    # Immediately check busy on UI thread
    assert project_store.busy

    # Wait until work runs, still busy
    assert started_evt.wait(timeout=2.0)
    assert project_store.busy

    continue_evt.set()
    assert pool.waitForDone(2000)
    assert not project_store.busy


def test_done_emitted_exactly_once_and_last(qapp, project_store):
    pool = QThreadPool()
    order = []

    def work(store, cancel_evt, progress):
        return 123

    job = StoreJob(project_store, work)
    job.signals.finished.connect(lambda res: order.append("finished"))
    job.signals.done.connect(lambda: order.append("done"))

    job.start(pool)
    assert pool.waitForDone(2000)
    _drain_events(qapp, 1.0, condition=lambda: "done" in order)

    assert order == ["finished", "done"]
    assert order.count("done") == 1


def test_busy_flag_cleared_even_when_finished_slot_raises(qapp, project_store):
    pool = QThreadPool()
    done_called = [False]

    def work(store, cancel_evt, progress):
        return "payload"

    job = StoreJob(project_store, work)

    def crashing_slot(res):
        raise ValueError("Buggy UI code in slot")

    job.signals.finished.connect(crashing_slot)
    job.signals.done.connect(lambda: done_called.__setitem__(0, True))

    job.start(pool)
    assert pool.waitForDone(2000)
    _drain_events(qapp, 1.0, condition=lambda: done_called[0])

    assert not project_store.busy
    assert done_called[0]


def test_pool_start_failure_releases_store(qapp, project_store, monkeypatch):
    pool = QThreadPool()

    def buggy_start(runnable):
        raise RuntimeError("ThreadPool exhausted")

    monkeypatch.setattr(pool, "start", buggy_start)

    job = StoreJob(project_store, lambda s, c, p: None)
    with pytest.raises(RuntimeError, match="ThreadPool exhausted"):
        job.start(pool)

    assert not project_store.busy
    # Store should be usable for next job
    with project_store.job():
        pass


def test_two_jobs_in_sequence(qapp, project_store):
    pool = QThreadPool()
    pool.setMaxThreadCount(1)

    results = []

    job1 = StoreJob(project_store, lambda s, c, p: "job1")
    job1.signals.finished.connect(lambda res: results.append(res))

    job2 = StoreJob(project_store, lambda s, c, p: "job2")
    job2.signals.finished.connect(lambda res: results.append(res))

    job1.start(pool)
    assert pool.waitForDone(2000)
    _drain_events(qapp, 1.0, condition=lambda: len(results) == 1)
    assert not project_store.busy

    job2.start(pool)
    assert pool.waitForDone(2000)
    _drain_events(qapp, 1.0, condition=lambda: len(results) == 2)
    assert not project_store.busy

    assert results == ["job1", "job2"]


def test_progress_dialog_binder(qapp, project_store):
    # If qapp is only QCoreApplication and not QApplication, use a mock dialog
    if not isinstance(qapp, QApplication):
        class MockDialog:
            def __init__(self):
                self._title = ""
                self._label = ""
                self._max = 0
                self._val = 0
                self.is_closed = False
                class _CanceledSignal:
                    def connect(self, fn):
                        self.fn = fn
                    def emit(self):
                        self.fn()
                self.canceled = _CanceledSignal()

            def setWindowTitle(self, t):
                self._title = t

            def windowTitle(self):
                return self._title

            def setLabelText(self, l):
                self._label = l

            def labelText(self):
                return self._label

            def setMaximum(self, m):
                self._max = m

            def maximum(self):
                return self._max

            def setValue(self, v):
                self._val = v

            def value(self):
                return self._val

            def close(self):
                self.is_closed = True

        dlg = MockDialog()
    else:
        dlg = QProgressDialog()

    pool = QThreadPool()
    cancelled = [False]

    def work(store, cancel_evt, progress):
        progress("Step 1", 1, 10)
        while not cancel_evt.is_set():
            time.sleep(0.01)
        cancelled[0] = True
        raise ImportCancelledError("User clicked cancel")

    job = StoreJob(project_store, work, title="My Import")
    binder = ProgressDialogBinder(job, dlg)
    assert binder is not None
    assert dlg.windowTitle() == "My Import"

    done_called = [False]
    job.signals.done.connect(lambda: done_called.__setitem__(0, True))

    job.start(pool)
    time.sleep(0.02)
    _drain_events(qapp, 0.2)
    assert dlg.labelText() == "Step 1"
    assert dlg.maximum() == 10
    assert dlg.value() == 1

    # Simulate cancel clicked
    dlg.canceled.emit()
    assert pool.waitForDone(2000)
    _drain_events(qapp, 1.0, condition=lambda: done_called[0])

    assert cancelled[0]
    assert not project_store.busy
