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
                    def disconnect(self, fn=None):
                        self.fn = None
                    def emit(self):
                        if self.fn:
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


# ---------------- Review Finding Repro Tests (Failing First) ----------------

def test_quality_a_busy_is_false_inside_finished_handler(qapp, project_store):
    """(a) assert project_store.busy is False INSIDE a connected finished handler (release-before-done)."""
    pool = QThreadPool()
    busy_in_finished = []
    job = StoreJob(project_store, lambda s, e, p: 123)
    job.signals.finished.connect(lambda res: busy_in_finished.append(project_store.busy))
    done = []
    job.signals.done.connect(lambda: done.append(True))
    job.start(pool)
    assert pool.waitForDone(3000)
    _drain_events(qapp, 1.0, condition=lambda: bool(done))
    assert busy_in_finished == [False]


def test_quality_b_cancel_flag_set_and_store_error_emits_canceled(qapp, project_store):
    """(b) cancel flag set + StoreError raised -> canceled (not failed), assert it."""
    pool = QThreadPool()
    def work(s, e, p):
        while not e.is_set():
            time.sleep(0.005)
        raise StoreError("disk full while cancelling")

    job = StoreJob(project_store, work)
    canceled = []
    failed = []
    job.signals.canceled.connect(lambda: canceled.append(True))
    job.signals.failed.connect(failed.append)

    job.start(pool)
    time.sleep(0.05)
    job.cancel()
    assert pool.waitForDone(3000)
    _drain_events(qapp, 1.0, condition=lambda: bool(canceled))
    assert canceled == [True]
    assert failed == []


def test_quality_c_traceback_is_logged_for_unexpected_error(qapp, project_store, caplog):
    """(c) the traceback is logged for an unexpected error (use caplog)."""
    import logging
    pool = QThreadPool()
    def work(s, e, p):
        raise TypeError("completely unexpected error")

    job = StoreJob(project_store, work, title="MyJob")
    done = []
    job.signals.done.connect(lambda: done.append(True))

    with caplog.at_level(logging.ERROR, logger="analytics_studio.store.jobs"):
        job.start(pool)
        assert pool.waitForDone(3000)
        _drain_events(qapp, 1.0, condition=lambda: bool(done))

    assert any("Unexpected error in StoreJob 'MyJob'" in record.message for record in caplog.records)
    assert any(record.exc_info is not None for record in caplog.records)


def test_quality_d_raising_finished_handler_does_not_stop_done_and_busy_false(qapp, project_store):
    """(d) a raising finished handler does not stop done (assert done count == 1) and busy False."""
    pool = QThreadPool()
    job = StoreJob(project_store, lambda s, e, p: 99)
    def bad_slot(val):
        raise ValueError("slot blew up")
    job.signals.finished.connect(bad_slot)
    done_count = []
    job.signals.done.connect(lambda: done_count.append(1))

    job.start(pool)
    assert pool.waitForDone(3000)
    _drain_events(qapp, 1.0, condition=lambda: len(done_count) == 1)
    assert len(done_count) == 1
    assert not project_store.busy


def test_quality_e_binder_closes_on_done_and_total_zero_branch(qapp, project_store):
    """(e) binder closes on done (assert dialog not visible / closed) and total=0 branch (maximum 0, busy indicator)."""
    pool = QThreadPool()
    dlg = QProgressDialog() if isinstance(qapp, QApplication) else None
    if dlg is None:
        pytest.skip("Requires QApplication")

    progress_received = [False]
    def work(s, e, p):
        p("working unknown total", 5, 0)
        time.sleep(0.1)
        return "done"

    job = StoreJob(project_store, work, title="Indeterminate")
    binder = ProgressDialogBinder(job, dlg)
    assert binder is not None
    job.signals.progress.connect(lambda m, d, t: progress_received.__setitem__(0, True))
    dlg.show()
    assert dlg.isVisible()

    done = []
    job.signals.done.connect(lambda: done.append(True))

    job.start(pool)
    _drain_events(qapp, 1.0, condition=lambda: progress_received[0])
    assert dlg.maximum() == 0
    assert dlg.value() == 0

    assert pool.waitForDone(3000)
    _drain_events(qapp, 2.0, condition=lambda: not dlg.isVisible())
    assert not dlg.isVisible()


def test_quality_f_pool_start_failure_exit_explicitly_called(qapp, project_store, monkeypatch):
    """(f) pool.start failure test must fail if the explicit cm.__exit__ is removed:
    hold a reference to the context manager generator so refcount cannot save it."""
    pool = QThreadPool()
    def buggy_start(runnable):
        raise RuntimeError("ThreadPool exhausted")
    monkeypatch.setattr(pool, "start", buggy_start)

    exit_calls = []
    orig_job = project_store.job

    class JobCmWrapper:
        def __init__(self, inner_cm):
            self.inner_cm = inner_cm
        def __enter__(self):
            return self.inner_cm.__enter__()
        def __exit__(self, exc_type, exc_val, tb):
            exit_calls.append(True)
            return self.inner_cm.__exit__(exc_type, exc_val, tb)

    # Keep a reference alive in test scope so garbage collection cannot trigger __exit__
    cm_refs = []
    def patched_job():
        cm = JobCmWrapper(orig_job())
        cm_refs.append(cm)
        return cm

    monkeypatch.setattr(project_store, "job", patched_job)

    job = StoreJob(project_store, lambda s, c, p: None)
    with pytest.raises(RuntimeError, match="ThreadPool exhausted"):
        job.start(pool)

    assert exit_calls == [True]
    assert not project_store.busy


def test_quality_g_binder_bounded_loop_event_pumping(qapp, project_store):
    """(g) the binder test waits with a bounded loop on a condition (up to 5 s) instead of fixed sleep."""
    dlg = QProgressDialog() if isinstance(qapp, QApplication) else None
    if dlg is None:
        pytest.skip("Requires QApplication")

    pool = QThreadPool()
    job = StoreJob(project_store, lambda s, e, p: 123, title="Pump")
    binder = ProgressDialogBinder(job, dlg)
    assert binder is not None
    dlg.show()

    done = [False]
    job.signals.done.connect(lambda: done.__setitem__(0, True))

    job.start(pool)
    assert pool.waitForDone(3000)
    assert _drain_events(qapp, 5.0, condition=lambda: done[0] and not dlg.isVisible())


def test_quality_h_chained_second_job_from_finished_completes(qapp, project_store):
    """(h) chained second job from finished completes, in a plain (no binder) test."""
    pool = QThreadPool()
    results = []
    j1 = StoreJob(project_store, lambda s, e, p: "res1")

    def on_j1_finished(v):
        results.append(v)
        j2 = StoreJob(project_store, lambda s, e, p: "res2")
        j2.signals.finished.connect(results.append)
        j2.start(pool)

    j1.signals.finished.connect(on_j1_finished)
    j1.start(pool)

    _drain_events(qapp, 5.0, condition=lambda: len(results) == 2)
    assert pool.waitForDone(3000)
    assert results == ["res1", "res2"]
    assert not project_store.busy


def test_j1_binder_close_does_not_set_cancel_event(qapp, project_store):
    """J1: closing dialog on done must not leave project_store.cancel_event set."""
    pool = QThreadPool()
    dlg = QProgressDialog() if isinstance(qapp, QApplication) else None
    if dlg is None:
        pytest.skip("Requires QApplication")

    job = StoreJob(project_store, lambda s, e, p: 42, title="J1")
    binder = ProgressDialogBinder(job, dlg)
    assert binder is not None
    done_called = [False]
    job.signals.done.connect(lambda: done_called.__setitem__(0, True))

    job.start(pool)
    assert pool.waitForDone(3000)
    _drain_events(qapp, 2.0, condition=lambda: done_called[0])

    assert not project_store.cancel_event.is_set()


def test_j1b_chained_job_from_finished_slot_with_binder_not_cancelled(qapp, project_store):
    """J1b: Job 2 started from job 1's finished slot (with binders on both) completes without seeing cancel."""
    pool = QThreadPool()
    if not isinstance(qapp, QApplication):
        pytest.skip("Requires QApplication")

    dlg1 = QProgressDialog()
    dlg2 = QProgressDialog()

    j1 = StoreJob(project_store, lambda s, e, p: 1, title="J1")
    binder1 = ProgressDialogBinder(j1, dlg1)
    assert binder1 is not None
    res2 = []
    j2_holder = []

    def on_finished(val):
        def work2(s, e, p):
            time.sleep(0.05)
            return "cancelled" if e.is_set() else "ok"
        j2 = StoreJob(project_store, work2, title="J2")
        binder2 = ProgressDialogBinder(j2, dlg2)
        assert binder2 is not None
        j2.signals.finished.connect(res2.append)
        j2_holder.append(j2)
        j2.start(pool)

    j1.signals.finished.connect(on_finished)
    j1.start(pool)

    _drain_events(qapp, 5.0, condition=lambda: len(res2) == 1)
    assert pool.waitForDone(3000)
    assert res2 == ["ok"]
    assert not project_store.cancel_event.is_set()


def test_j2_release_if_not_started_when_pool_cleared(qapp, project_store):
    """J2: release_if_not_started releases store when job was queued in pool and dropped by pool.clear()."""
    pool = QThreadPool()
    pool.setMaxThreadCount(1)
    gate = threading.Event()

    blocker = StoreJob(project_store, lambda s, e, p: gate.wait(2))
    blocker.start(pool)

    # project_store is busy with blocker. Create a second project store to queue a job
    import tempfile, os
    tmp = tempfile.mkdtemp()
    ps2 = ProjectStore.open(os.path.join(tmp, "b.npa.data"))
    try:
        jq = StoreJob(ps2, lambda s, e, p: 1)
        jq.start(pool)
        assert ps2.busy

        # Clear pool before jq runs
        pool.clear()
        jq.release_if_not_started()
        assert not ps2.busy

        gate.set()
        assert pool.waitForDone(3000)
        # Calling after run or release does nothing
        jq.release_if_not_started()
        assert not ps2.busy
    finally:
        gate.set()
        ps2.close()


def test_j4_base_exception_keyboard_interrupt_system_exit(qapp, project_store):
    """J4: KeyboardInterrupt and SystemExit emit failed('The job was interrupted.') and do not crash pool."""
    pool = QThreadPool()

    for exc in (KeyboardInterrupt(), SystemExit(1)):
        failed_msgs = []
        dones = []
        def work_fail(s, e, p, ex=exc):
            raise ex

        job = StoreJob(project_store, work_fail)
        job.signals.failed.connect(failed_msgs.append)
        job.signals.done.connect(lambda: dones.append(1))

        job.start(pool)
        assert pool.waitForDone(3000)
        _drain_events(qapp, 2.0, condition=lambda: bool(dones))

        assert failed_msgs == ["The job was interrupted."]
        assert dones == [1]
        assert not project_store.busy

