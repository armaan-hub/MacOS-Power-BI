"""Tests for Stage C3a: DuckStore.reader() / StoreReader, ProjectStore read leases and cancel hooks.

No Qt and no wall-clock assertion anywhere. Threads are synchronised with Events, Conditions and a counter that a
query itself raises (`Probe`); `join(timeout)` / `Event.wait(timeout)` are hang guards only, their elapsed time is
never asserted.
"""

from __future__ import annotations

import itertools
import random
import threading
from pathlib import Path
from typing import Any, Callable

import pyarrow as pa
import pytest

try:  # duckdb 1.5 names the module sqltypes; older releases called it typing
    from duckdb.sqltypes import BIGINT, BOOLEAN
except ImportError:  # pragma: no cover
    from duckdb.typing import BIGINT, BOOLEAN  # type: ignore[no-redef]

from analytics_studio.store import DuckStore, ProjectStore
from analytics_studio.store.base import StoreBusyError, StoreError
from analytics_studio.store.duck_store import StoreReader

GUARD_S = 10.0  # hang guard only: a wrong implementation fails by assertion after this long
COLUMNS = [("id", "whole"), ("grp", "text"), ("val", "decimal")]
ROWS = 5000

# Never ends by itself (about 10 s or more on duckdb 1.5.5); the probe filter raises a counter once per chunk,
# so a test can wait until the query is really running and prove that it still runs. SQL functions live in the
# database catalog, so every Probe / Gate has its own function name.
_LONG_QUERY = "SELECT sum(hash(a)) FROM range(3000000000) r(a) WHERE {name}(a)"
_names = itertools.count(1)
PROBE_CAP_CHUNKS = 40_000  # about 4 s of scanning here; a test interrupts after a handful of chunks


def make_batches(rows: int = ROWS, seed: int = 11) -> list[pa.RecordBatch]:
    rnd = random.Random(seed)
    schema = pa.schema([("id", pa.int64()), ("grp", pa.string()), ("val", pa.float64())])
    return [pa.record_batch(
        [
            pa.array(list(range(1, rows + 1)), pa.int64()),
            pa.array([rnd.choice(["a", "b", "c", "d", None]) for _ in range(rows)], pa.string()),
            pa.array([None if rnd.random() < 0.05 else round(rnd.uniform(-100, 100), 2) for _ in range(rows)], pa.float64()),
        ],
        schema=schema,
    )]


def join_or_fail(thread: threading.Thread, what: str = "thread") -> None:
    """Join with the hang guard and fail with a message (an assertion, not a hang) when it did not end."""
    thread.join(GUARD_S)
    assert not thread.is_alive(), f"{what} did not end within the {GUARD_S:g} s hang guard"


def wait_or_fail(event: threading.Event, what: str) -> None:
    assert event.wait(GUARD_S), f"{what} did not happen within the {GUARD_S:g} s hang guard"


@pytest.fixture
def store(tmp_path: Path) -> Any:
    s = DuckStore(str(tmp_path / "r.db"))
    s.create_table_from_arrow("t", COLUMNS, make_batches())
    yield s
    s.close()


@pytest.fixture
def ps(tmp_path: Path) -> Any:
    p = ProjectStore.open(str(tmp_path / "p.npa.data"))
    p.store.create_table_from_arrow("t", COLUMNS, make_batches())
    yield p
    p.shutdown(timeout=GUARD_S)


class Probe:
    """Counts the chunks a LONG_QUERY has scanned and lets a test wait for more of them."""

    def __init__(self) -> None:
        self.calls = 0
        self.name = f"probe_{next(_names)}"
        self.query = _LONG_QUERY.format(name=self.name)
        self._cond = threading.Condition()

    def _fn(self, arr: Any) -> Any:
        with self._cond:
            self.calls += 1
            self._cond.notify_all()
            over = self.calls > PROBE_CAP_CHUNKS
        if over:  # a wrong implementation that never interrupts must not leave a query of minutes behind
            raise RuntimeError("the probe query ran past its cap of scanned chunks")
        return pa.array([True] * len(arr))

    def install(self, reader: StoreReader) -> "Probe":
        reader._cursor.create_function(self.name, self._fn, [BIGINT], BOOLEAN, type="arrow")
        return self

    def wait_running(self, more: int = 1) -> None:
        """Wait until at least `more` further chunks were scanned: the query runs now, and still runs after this."""
        with self._cond:
            target = self.calls + more
            assert self._cond.wait_for(lambda: self.calls >= target, timeout=GUARD_S), "the long query never ran"


class Gate:
    """A SQL function `gate(x)` that blocks (ignoring interrupts) until `release` is set."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.name = f"gate_{next(_names)}"

    def _fn(self, x: int) -> int:
        self.started.set()
        if not self.release.wait(GUARD_S):
            self.release.set()  # a test that failed before releasing the gate must not hold every later row for 10 s
        return x

    def install(self, reader: StoreReader) -> "Gate":
        reader._cursor.create_function(self.name, self._fn, [BIGINT], BIGINT)
        return self


class Runner:
    """Runs one reader query on its own thread; keeps the result or the exception."""

    def __init__(self, reader: StoreReader, sql: str) -> None:
        self.result: Any = None
        self.error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, args=(reader, sql), daemon=True)
        self._thread.start()

    def _run(self, reader: StoreReader, sql: str) -> None:
        try:
            self.result = reader.execute(sql)
        except BaseException as exc:  # noqa: BLE001 - the test reads it
            self.error = exc

    def finished(self) -> bool:
        return not self._thread.is_alive()

    def join(self) -> None:
        self._thread.join(GUARD_S)
        assert not self._thread.is_alive(), "the query did not end"


def interrupt_until_done(runner: Runner, interrupt: Callable[[], None]) -> None:
    """An interrupt that lands before the query starts is lost, so send it again until the thread has ended."""
    for _ in range(int(GUARD_S / 0.05)):
        interrupt()
        runner._thread.join(0.05)
        if runner.finished():
            return
    raise AssertionError("the query did not end")


# ---------------------------------------------------------------------------------------------------------
# Item 1 / 2: reader on DuckStore
# ---------------------------------------------------------------------------------------------------------
def test_two_readers_and_main_connection_query_at_the_same_time(store: DuckStore) -> None:
    a, b = store.reader(), store.reader()
    gate_a, gate_b = Gate().install(a), Gate().install(b)
    run_a = Runner(a, f"SELECT sum({gate_a.name}(id)) FROM t")
    run_b = Runner(b, f"SELECT sum({gate_b.name}(id)) FROM t")
    try:
        assert gate_a.started.wait(GUARD_S) and gate_b.started.wait(GUARD_S)
        # Both readers are inside a query now. The main connection (the data grid) answers; a third reader too.
        assert store.execute("SELECT count(*) FROM t") == [(ROWS,)]
        assert len(store.read_page("t", 0, 10)) == 10
        with store.reader() as c:
            assert c.execute("SELECT count(*) FROM t") == [(ROWS,)]
        assert not run_a.finished() and not run_b.finished()
    finally:
        gate_a.release.set()
        gate_b.release.set()
    run_a.join()
    run_b.join()
    assert run_a.error is None and run_b.error is None
    expected = store.execute("SELECT sum(id) FROM t")
    assert run_a.result == expected and run_b.result == expected
    a.close()
    b.close()


def test_reader_never_takes_the_store_lock(store: DuckStore) -> None:
    with store.reader() as reader:
        results: list[Any] = []
        errors: list[BaseException] = []

        def work() -> None:
            try:
                results.append(reader.execute("SELECT count(*) FROM t"))
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        with store._lock:  # the main connection is "busy": a store call from another thread is refused at once
            worker = threading.Thread(target=work)
            worker.start()
            join_or_fail(worker, "worker")
            assert not worker.is_alive()
            assert errors == [] and results == [[(ROWS,)]]
            blocked: list[BaseException] = []

            def main_call() -> None:
                try:
                    store.execute("SELECT 1")
                except BaseException as exc:  # noqa: BLE001
                    blocked.append(exc)

            other = threading.Thread(target=main_call)
            other.start()
            join_or_fail(other, "other")
            assert len(blocked) == 1 and isinstance(blocked[0], StoreBusyError)


def test_interrupt_stops_only_that_reader(store: DuckStore) -> None:
    a, b = store.reader(), store.reader()
    pa_, pb = Probe().install(a), Probe().install(b)
    run_a, run_b = Runner(a, pa_.query), Runner(b, pb.query)
    pa_.wait_running()
    pb.wait_running()
    interrupt_until_done(run_a, a.interrupt)
    assert isinstance(run_a.error, StoreError) and "interrupt" in str(run_a.error).casefold()
    pb.wait_running(3)  # reader B was not touched: it scanned three more chunks after A had ended
    assert not run_b.finished() and run_b.error is None
    interrupt_until_done(run_b, b.interrupt)
    assert isinstance(run_b.error, StoreError) and "interrupt" in str(run_b.error).casefold()
    a.close()
    b.close()


def test_other_interrupts_do_not_stop_a_reader_but_interrupt_all_readers_does(store: DuckStore) -> None:
    a, b = store.reader(), store.reader()
    probe = Probe().install(a)
    run_a = Runner(a, probe.query)
    probe.wait_running()
    for _ in range(5):
        b.interrupt()  # an idle other reader
        store.interrupt()  # the main connection only
    probe.wait_running(5)
    assert not run_a.finished() and run_a.error is None  # still scanning after all of them
    interrupt_until_done(run_a, store.interrupt_all_readers)
    assert isinstance(run_a.error, StoreError) and "interrupt" in str(run_a.error).casefold()
    a.close()
    b.close()


def test_reader_answers_a_normal_query_after_an_interrupt(store: DuckStore) -> None:
    with store.reader() as reader:
        probe = Probe().install(reader)
        run = Runner(reader, probe.query)
        probe.wait_running()
        interrupt_until_done(run, reader.interrupt)
        assert run.error is not None
        assert reader.execute("SELECT 41 + 1") == [(42,)]
        assert reader.execute("SELECT count(*) FROM t") == [(ROWS,)]
        reader.interrupt()  # idle: harms nothing
        assert reader.execute("SELECT 7") == [(7,)]


def test_reader_interrupt_is_safe_idle_and_after_close(store: DuckStore) -> None:
    reader = store.reader()
    reader.interrupt()
    assert reader.execute("SELECT 1") == [(1,)]
    reader.close()
    reader.interrupt()  # never raises on a closed reader
    reader.close()  # idempotent
    assert reader.closed
    with pytest.raises(StoreError, match="closed"):
        reader.execute("SELECT 1")


def test_store_close_interrupts_a_running_reader_and_joins(tmp_path: Path) -> None:
    store = DuckStore(str(tmp_path / "c.db"))
    store.create_table_from_arrow("t", COLUMNS, make_batches(100))
    reader = store.reader()
    probe = Probe().install(reader)
    run = Runner(reader, probe.query)
    probe.wait_running()
    store.close()  # interrupts the reader first, closes it, then the main connection
    run.join()
    assert isinstance(run.error, StoreError), run.error
    assert "interrupt" in str(run.error).casefold()
    assert reader.closed
    with pytest.raises(StoreError, match="closed"):
        store.reader()
    with pytest.raises(StoreError, match="closed"):
        reader.execute("SELECT 1")


def test_store_close_closes_idle_readers(tmp_path: Path) -> None:
    store = DuckStore(str(tmp_path / "c2.db"))
    first, second = store.reader(), store.reader()
    store.close()
    assert first.closed and second.closed
    assert store._readers == set()


def test_closing_a_reader_forgets_it(store: DuckStore) -> None:
    reader = store.reader()
    assert reader in store._readers
    reader.close()
    assert reader not in store._readers
    with store.reader() as other:
        assert other in store._readers
    assert store._readers == set()


def test_reader_refused_while_a_transaction_is_open(tmp_path: Path) -> None:
    store = DuckStore(str(tmp_path / "x.db"))
    try:
        store.create_table_from_arrow("t", COLUMNS, make_batches(10))
        seen: list[BaseException | None] = []

        def probing_rows() -> Any:
            yield (1, "a", 1.0)
            try:
                store.reader()
                seen.append(None)
            except BaseException as exc:  # noqa: BLE001
                seen.append(exc)
            yield (2, "b", 2.0)

        assert store.append_rows("t", probing_rows()) == 2
        assert len(seen) == 1 and isinstance(seen[0], StoreBusyError), seen
        assert store._txn_open is False
        store.reader().close()  # the transaction is over: a reader is allowed again

        arrow_seen: list[BaseException | None] = []

        def probing_batches() -> Any:
            try:
                store.reader()
                arrow_seen.append(None)
            except BaseException as exc:  # noqa: BLE001
                arrow_seen.append(exc)
            yield from make_batches(5)

        store.create_table_from_arrow("u", COLUMNS, probing_batches())
        assert len(arrow_seen) == 1 and isinstance(arrow_seen[0], StoreBusyError), arrow_seen
        with store.reader() as reader:
            assert reader.execute("SELECT count(*) FROM u") == [(5,)]
    finally:
        store.close()


@pytest.mark.parametrize("sql", [
    "INSERT INTO t VALUES (1, 'x', 1.0, 1)",
    "DROP TABLE t",
    "SELECT 1; SELECT 2",
    "",
    "   ",
    "SELEKT nonsense",
    "CREATE TABLE z (a INT)",
])
def test_reader_refuses_what_store_execute_refuses_with_the_same_text(store: DuckStore, sql: str) -> None:
    with pytest.raises(StoreError) as main_error:
        store.execute(sql)
    with store.reader() as reader:
        with pytest.raises(StoreError) as reader_error:
            reader.execute(sql)
    assert str(reader_error.value) == str(main_error.value)
    assert store.execute("SELECT count(*) FROM t") == [(ROWS,)]  # nothing ran


def test_reader_wraps_a_query_error_like_the_store(store: DuckStore) -> None:
    sql = "SELECT nosuchcolumn FROM t"
    with pytest.raises(StoreError) as main_error:
        store.execute(sql)
    with store.reader() as reader:
        with pytest.raises(StoreError) as reader_error:
            reader.execute(sql)
    assert str(reader_error.value) == str(main_error.value)
    assert str(reader_error.value).startswith("Query execution failed: ")


def test_reader_results_equal_store_results_for_generated_selects(store: DuckStore) -> None:
    rnd = random.Random(5)
    aggregates = ["count(*)", "count(val)", "sum(val)", "min(id)", "max(val)", "avg(val)", "count(DISTINCT grp)"]
    filters = ["", "WHERE id > 2500", "WHERE grp = 'a'", "WHERE val < 0", "WHERE grp IN ('b', 'c') AND id % 3 = 0",
               "WHERE val IS NULL", "WHERE grp IS NULL OR id < 100"]
    queries: list[str] = []
    for _ in range(10):
        queries.append(f"SELECT {rnd.choice(aggregates)}, {rnd.choice(aggregates)} FROM t {rnd.choice(filters)}")
    for _ in range(10):
        queries.append(
            f"SELECT grp, {rnd.choice(aggregates)} FROM t {rnd.choice(filters)} GROUP BY grp ORDER BY grp NULLS FIRST"
        )
    assert len(queries) == 20
    with store.reader() as reader:
        for sql in queries:
            assert reader.execute(sql) == store.execute(sql), sql
        assert reader.execute("SELECT id FROM t WHERE id = ?", [77]) == store.execute("SELECT id FROM t WHERE id = ?", [77])


def test_append_after_reader_opened_is_not_seen_by_a_running_statement_but_by_the_next(store: DuckStore) -> None:
    """Measured on duckdb 1.5.5: a statement keeps the snapshot it started with; the next statement of the same
    reader sees what the main connection committed meanwhile (the same as the main connection today)."""
    reader = store.reader()
    gate = Gate().install(reader)
    run = Runner(reader, f"SELECT count(*) FROM t WHERE {gate.name}(id) > 0")
    try:
        assert gate.started.wait(GUARD_S)
        # The store refuses append_rows while a reader is open (see test_table_changes_are_refused_while_a_reader_is_open),
        # so the duckdb fact is measured with a raw commit on the main connection.
        store._conn.execute("INSERT INTO t VALUES (?, 'z', 1.0, ?)", [ROWS + 1, ROWS + 1])
        assert store.execute("SELECT count(*) FROM t") == [(ROWS + 1,)]
    finally:
        gate.release.set()
    run.join()
    assert run.error is None
    assert run.result == [(ROWS,)]  # the running statement did not see the new row
    assert reader.execute("SELECT count(*) FROM t") == [(ROWS + 1,)]  # the next statement does
    reader.close()


def test_drop_on_the_main_connection_while_a_reader_reads_lets_the_read_finish(store: DuckStore) -> None:
    reader = store.reader()
    gate = Gate().install(reader)
    run = Runner(reader, f"SELECT count(*) FROM t WHERE {gate.name}(id) > 0")
    try:
        assert gate.started.wait(GUARD_S)
        store._conn.execute("DROP TABLE t")  # raw: drop_table is refused while a reader is open
    finally:
        gate.release.set()
    run.join()
    assert run.error is None and run.result == [(ROWS,)]
    with pytest.raises(StoreError):
        reader.execute("SELECT count(*) FROM t")  # the table is gone for the next statement
    reader.close()


# ---------------------------------------------------------------------------------------------------------
# Item 3: ProjectStore read leases, cancel hooks, shutdown
# ---------------------------------------------------------------------------------------------------------
def test_lease_gives_a_working_reader_and_leaves_counts_at_zero(ps: ProjectStore) -> None:
    with ps.read_lease() as reader:
        assert ps._readers == 1
        assert ps.busy is False  # a lease never sets the busy flag
        assert reader.execute("SELECT count(*) FROM t") == [(ROWS,)]
        assert ps.store.execute("SELECT count(*) FROM t") == [(ROWS,)]  # the data grid still works
    assert ps._readers == 0 and reader.closed and ps.store._readers == set()


def test_lease_does_not_clear_the_cancel_event(ps: ProjectStore) -> None:
    ps.request_cancel()
    with ps.read_lease():
        assert ps.cancel_event.is_set()
    assert ps.cancel_event.is_set()


def test_job_is_refused_while_a_lease_is_open_and_the_lease_while_a_job_runs(ps: ProjectStore) -> None:
    with ps.read_lease():
        with pytest.raises(StoreBusyError):
            with ps.job():
                pass
        with pytest.raises(StoreBusyError):
            with ps._exclusive():
                pass
        assert ps.busy is False
    assert ps._readers == 0
    with ps.job():
        with pytest.raises(StoreBusyError):
            with ps.read_lease():
                pass
        assert ps._readers == 0
    assert ps.busy is False
    with ps.read_lease():  # both orders are usable again
        pass
    with ps.job():
        pass


def test_exclusive_operations_are_refused_while_a_lease_is_open(ps: ProjectStore, tmp_path: Path) -> None:
    with ps.read_lease():
        with pytest.raises(StoreBusyError):
            ps.drop_unreferenced(set())
        with pytest.raises(StoreBusyError):
            ps.validate_table("t", ["id", "grp", "val"], ["whole", "text", "decimal"], ROWS)
        with pytest.raises(StoreBusyError):
            ps.copy_to(str(tmp_path / "copy.npa.data"))
        with pytest.raises(StoreBusyError):
            ps.rebind(str(tmp_path / "other.npa.data"), delete_old=False)
        with pytest.raises(StoreBusyError):
            ps.close()
        assert ps.closed is False
    assert ps._readers == 0
    assert ps.drop_unreferenced({"t"}) == []


def test_two_leases_at_once_are_allowed(ps: ProjectStore) -> None:
    with ps.read_lease() as first:
        with ps.read_lease() as second:
            assert ps._readers == 2 and first is not second
            assert first.execute("SELECT 1") == [(1,)] and second.execute("SELECT 2") == [(2,)]
        assert ps._readers == 1 and second.closed and not first.closed
        assert first.execute("SELECT 3") == [(3,)]
    assert ps._readers == 0


def test_lease_counts_return_to_zero_after_an_exception_inside(ps: ProjectStore) -> None:
    with pytest.raises(RuntimeError, match="inside"):
        with ps.read_lease() as reader:
            raise RuntimeError("inside")
    assert ps._readers == 0 and reader.closed and ps.store._readers == set()
    with ps.job():  # an exclusive operation is possible again
        pass
    with pytest.raises(StoreError):
        with ps.read_lease() as reader2:
            reader2.execute("SELECT nosuchcolumn FROM t")
    assert ps._readers == 0 and reader2.closed


def test_lease_refused_when_closed_or_shutting_down(tmp_path: Path) -> None:
    closed = ProjectStore.open(str(tmp_path / "a.npa.data"))
    closed.close()
    with pytest.raises(StoreError, match="The store is closed."):
        with closed.read_lease():
            pass
    assert closed._readers == 0

    other = ProjectStore.open(str(tmp_path / "b.npa.data"))
    try:
        other._shutting_down = True
        with pytest.raises(StoreError, match="The store is shutting down."):
            with other.read_lease():
                pass
        assert other._readers == 0
    finally:
        other._shutting_down = False
        other.shutdown(timeout=GUARD_S)


def test_lease_refused_while_the_store_has_an_open_transaction(ps: ProjectStore) -> None:
    ps.store._txn_open = True
    try:
        with pytest.raises(StoreBusyError):
            with ps.read_lease():
                pass
    finally:
        ps.store._txn_open = False
    assert ps._readers == 0


def test_shutdown_with_a_lease_held_interrupts_the_query_waits_and_returns_true(tmp_path: Path) -> None:
    ps = ProjectStore.open(str(tmp_path / "s.npa.data"))
    ps.store.create_table_from_arrow("t", COLUMNS, make_batches(100))
    leased = threading.Event()
    done = threading.Event()
    outcome: dict[str, Any] = {}

    def holder() -> None:
        try:
            with ps.read_lease() as reader:
                probe = Probe().install(reader)
                leased.set()
                try:
                    reader.execute(probe.query)
                except StoreError as exc:
                    outcome["error"] = exc
                outcome["probe_calls"] = probe.calls
        finally:
            done.set()

    thread = threading.Thread(target=holder, daemon=True)
    thread.start()
    assert leased.wait(GUARD_S)
    # Wait until the long query really runs: poll the lease count (set) and a probe through the store's reader set.
    reader = next(iter(ps.store._readers))
    with reader._state:
        assert reader._state.wait_for(lambda: reader._active == 1, timeout=GUARD_S)
    assert ps.shutdown(timeout=GUARD_S) is True
    assert done.wait(GUARD_S)
    join_or_fail(thread, "thread")
    assert "interrupt" in str(outcome["error"]).casefold()
    assert ps.closed and ps._readers == 0


def test_shutdown_timeout_with_a_gate_that_ignores_interrupts_returns_false_and_store_stays_usable(
    ps: ProjectStore,
) -> None:
    gate_ready = threading.Event()
    gate_holder: dict[str, Gate] = {}
    finished = threading.Event()

    def holder() -> None:
        with ps.read_lease() as reader:
            gate = Gate().install(reader)
            gate_holder["gate"] = gate
            gate_ready.set()
            try:
                reader.execute(f"SELECT sum({gate.name}(id)) FROM t")
            except StoreError:
                pass
        finished.set()

    thread = threading.Thread(target=holder, daemon=True)
    thread.start()
    assert gate_ready.wait(GUARD_S)
    gate = gate_holder["gate"]
    assert gate.started.wait(GUARD_S)
    assert ps.shutdown(timeout=0.2) is False
    assert ps.closed is False and ps._shutting_down is False
    assert ps._readers == 1
    assert ps.store.execute("SELECT count(*) FROM t") == [(ROWS,)]  # the store stays usable
    gate.release.set()
    assert finished.wait(GUARD_S)
    join_or_fail(thread, "thread")
    assert ps._readers == 0
    assert ps.shutdown(timeout=GUARD_S) is True
    assert ps.closed


def test_shutdown_still_waits_for_a_job_as_before(ps: ProjectStore) -> None:
    started = threading.Event()
    release = threading.Event()

    def job() -> None:
        with ps.job() as cancel:
            started.set()
            release.wait(GUARD_S)
            assert cancel.is_set()  # shutdown asked the job to cancel

    thread = threading.Thread(target=job, daemon=True)
    thread.start()
    assert started.wait(GUARD_S)
    assert ps.shutdown(timeout=0.2) is False
    release.set()
    join_or_fail(thread, "thread")
    assert ps.shutdown(timeout=GUARD_S) is True


def test_close_raises_busy_while_a_lease_is_held_and_works_after(ps: ProjectStore) -> None:
    with ps.read_lease():
        with pytest.raises(StoreBusyError):
            ps.close()
        assert ps.closed is False
    ps.close()
    assert ps.closed


def test_cancel_hooks_are_called_once_per_request_and_a_raising_hook_does_not_stop_the_others(
    ps: ProjectStore,
) -> None:
    calls: list[str] = []

    def first() -> None:
        calls.append("first")

    def broken() -> None:
        calls.append("broken")
        raise RuntimeError("hook failure")

    def last() -> None:
        calls.append("last")

    for hook in (first, broken, last):
        ps.add_cancel_hook(hook)
    ps.request_cancel_readers()
    assert calls == ["first", "broken", "last"]
    ps.request_cancel_readers()
    assert calls == ["first", "broken", "last"] * 2
    ps.remove_cancel_hook(broken)
    ps.remove_cancel_hook(broken)  # a hook that is not registered is ignored
    calls.clear()
    ps.request_cancel_readers()
    assert calls == ["first", "last"]


def test_cancel_hooks_run_outside_the_store_lock(ps: ProjectStore) -> None:
    states: list[bool] = []

    def hook() -> None:
        acquired = ps._lock.acquire(blocking=False)
        states.append(acquired)
        if acquired:
            ps._lock.release()

    ps.add_cancel_hook(hook)
    ps.request_cancel_readers()
    assert states == [True]


def test_request_cancel_readers_interrupts_a_lease_and_leaves_the_job_cancel_event_alone(tmp_path: Path) -> None:
    ps = ProjectStore.open(str(tmp_path / "q.npa.data"))
    try:
        ps.store.create_table_from_arrow("t", COLUMNS, make_batches(50))
        with ps.read_lease() as reader:
            probe = Probe().install(reader)
            run = Runner(reader, probe.query)
            probe.wait_running()
            interrupt_until_done(run, ps.request_cancel_readers)
            assert isinstance(run.error, StoreError) and "interrupt" in str(run.error).casefold()
            assert ps.cancel_event.is_set() is False
            assert reader.execute("SELECT 1") == [(1,)]
    finally:
        ps.shutdown(timeout=GUARD_S)


def test_shutdown_calls_the_cancel_hooks(ps: ProjectStore) -> None:
    calls: list[int] = []
    ps.add_cancel_hook(lambda: calls.append(1))
    assert ps.shutdown(timeout=GUARD_S) is True
    assert calls == [1]


# ---------------------------------------------------------------------------------------------------------
# F2: table changes are refused at the DuckStore layer while a reader is open
# ---------------------------------------------------------------------------------------------------------
def _do_create(store: DuckStore) -> None:
    store.create_table("fresh", [("a", "whole")])


def _do_drop(store: DuckStore) -> None:
    store.drop_table("t")


def _do_append(store: DuckStore) -> None:
    store.append_rows("t", [(ROWS + 1, "z", 1.0)])


def _do_arrow(store: DuckStore) -> None:
    store.create_table_from_arrow("fresh2", COLUMNS, make_batches(5))


GUARDED = [("create_table", _do_create), ("drop_table", _do_drop), ("append_rows", _do_append),
           ("create_table_from_arrow", _do_arrow)]


@pytest.mark.parametrize("name,change", GUARDED, ids=[g[0] for g in GUARDED])
def test_table_changes_are_refused_while_a_reader_is_open_and_allowed_after(
    store: DuckStore, name: str, change: Callable[[DuckStore], None]
) -> None:
    names_before = sorted(store.table_names())
    version_before = store.table_version("t")
    reader = store.reader()
    with pytest.raises(StoreBusyError, match="being read"):
        change(store)
    assert sorted(store.table_names()) == names_before and store.table_version("t") == version_before
    assert store.execute("SELECT count(*) FROM t") == [(ROWS,)]  # nothing changed
    assert reader.execute("SELECT count(*) FROM t") == [(ROWS,)]
    reader.close()
    change(store)  # allowed once the reader is closed
    assert sorted(store.table_names()) != names_before or store.table_version("t") != version_before


@pytest.mark.parametrize("name,change", GUARDED, ids=[g[0] for g in GUARDED])
def test_table_changes_without_a_reader_are_unchanged(store: DuckStore, name: str, change: Callable[[DuckStore], None]) -> None:
    with store.reader():  # a reader that came and went leaves no trace
        pass
    change(store)


def test_the_grid_views_and_checkpoint_are_still_allowed_while_a_reader_is_open(store: DuckStore) -> None:
    with store.reader() as reader:
        store.create_view_ids("__stm_v_reader", 'SELECT "__rn" FROM "t" ORDER BY "id" DESC')
        assert store.execute('SELECT count(*) FROM "__stm_v_reader"') == [(ROWS,)]
        store.drop_view("__stm_v_reader")
        store.checkpoint()  # measured harmless: the reader answers before and after it
        assert reader.execute("SELECT count(*) FROM t") == [(ROWS,)]


def test_call_cannot_change_a_table_under_a_lease(ps: ProjectStore) -> None:
    """ProjectStore.call() hands the raw DuckStore to its function: the guard sits one layer lower."""
    with ps.read_lease() as reader:
        with pytest.raises(StoreBusyError):
            ps.call(lambda s: s.drop_table("t"))
        with pytest.raises(StoreBusyError):
            ps.call(lambda s: s.append_rows("t", [(1, "a", 1.0)]))
        with pytest.raises(StoreBusyError):
            ps.store.drop_table("t")
        assert reader.execute("SELECT count(*) FROM t") == [(ROWS,)]
    ps.call(lambda s: s.drop_table("t"))
    assert ps.store.has_table("t") is False


# ---------------------------------------------------------------------------------------------------------
# F3: pins for rules the first review found unpinned
# ---------------------------------------------------------------------------------------------------------
def spy_interrupts(reader: StoreReader) -> threading.Event:
    """An event that is set the first time `reader.interrupt()` is called."""
    seen = threading.Event()
    real = reader.interrupt

    def spy() -> None:
        seen.set()
        real()

    reader.interrupt = spy  # type: ignore[method-assign]
    return seen


def test_closing_one_reader_does_not_interrupt_another_that_is_running(store: DuckStore) -> None:
    a, b = store.reader(), store.reader()
    gate_a, gate_b = Gate().install(a), Gate().install(b)
    run_a = Runner(a, f"SELECT sum({gate_a.name}(id)) FROM t")
    run_b = Runner(b, f"SELECT sum({gate_b.name}(id)) FROM t")
    wait_or_fail(gate_a.started, "query A start")
    wait_or_fail(gate_b.started, "query B start")
    a_interrupted = spy_interrupts(a)
    closer = threading.Thread(target=a.close, daemon=True)
    closer.start()
    try:
        wait_or_fail(a_interrupted, "the interrupt of reader A by its own close")
    finally:
        gate_a.release.set()
    join_or_fail(closer, "A.close()")
    gate_b.release.set()
    run_a.join()
    run_b.join()
    assert isinstance(run_a.error, StoreError) and "interrupt" in str(run_a.error).casefold()
    assert run_b.error is None and run_b.result == store.execute("SELECT sum(id) FROM t")  # B was left alone
    b.close()


def test_interrupt_all_readers_interrupts_every_reader(store: DuckStore) -> None:
    readers = [store.reader() for _ in range(3)]
    gates = [Gate().install(r) for r in readers]
    runs = [Runner(r, f"SELECT sum({g.name}(id)) FROM t") for r, g in zip(readers, gates)]
    for index, gate in enumerate(gates):
        wait_or_fail(gate.started, f"query {index} start")
    store.interrupt_all_readers()  # once: every query is inside its gate now, so none of the three can miss it
    for gate in gates:
        gate.release.set()
    for run in runs:
        run.join()
    assert [isinstance(run.error, StoreError) and "interrupt" in str(run.error).casefold() for run in runs] == [True] * 3
    for reader in readers:
        reader.close()


def test_shutdown_stops_a_query_that_starts_after_its_first_interrupt(tmp_path: Path) -> None:
    """An interrupt that lands before a query starts is lost; shutdown sends it again until the lease ends."""
    ps = ProjectStore.open(str(tmp_path / "late.npa.data"))
    ps.store.create_table_from_arrow("t", COLUMNS, make_batches(50))
    first_interrupt_done = threading.Event()
    go = threading.Event()
    leased = threading.Event()
    outcome: dict[str, Any] = {}

    def holder() -> None:
        with ps.read_lease() as reader:
            probe = Probe().install(reader)
            leased.set()
            go.wait(GUARD_S)
            try:
                reader.execute(probe.query)
            except StoreError as exc:
                outcome["error"] = exc

    ps.add_cancel_hook(first_interrupt_done.set)  # called by shutdown right after its first interrupt
    holder_thread = threading.Thread(target=holder, daemon=True)
    holder_thread.start()
    wait_or_fail(leased, "the lease")
    shutter, box = run_in_thread_result(lambda: ps.shutdown(timeout=GUARD_S))
    try:
        wait_or_fail(first_interrupt_done, "the first interrupt of shutdown")
        go.set()  # only now does the long query start: the first interrupt is already lost
        join_or_fail(shutter, "shutdown")
        assert box.get("result") is True, box
    finally:
        go.set()
        for _ in range(int(GUARD_S / 0.05)):  # cleanup if shutdown did not stop the query
            if not holder_thread.is_alive():
                break
            ps.request_cancel_readers()
            holder_thread.join(0.05)
    join_or_fail(holder_thread, "the lease holder")
    assert "interrupt" in str(outcome["error"]).casefold()
    assert ps.closed


def run_in_thread_result(fn: Callable[[], Any]) -> tuple[threading.Thread, dict[str, Any]]:
    box: dict[str, Any] = {}

    def work() -> None:
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    return thread, box


def test_reader_cursor_is_closed_on_lease_exit_and_on_store_close(tmp_path: Path) -> None:
    ps = ProjectStore.open(str(tmp_path / "cur.npa.data"))
    ps.store.create_table_from_arrow("t", COLUMNS, make_batches(20))
    with ps.read_lease() as reader:
        cursor = reader._cursor
        assert cursor.execute("SELECT 1").fetchall() == [(1,)]
    assert reader._cursor is None
    with pytest.raises(Exception):
        cursor.execute("SELECT 1")  # the cursor itself is closed, not only marked
    leftover = ps.store.reader()
    leftover_cursor = leftover._cursor
    ps.store.close()  # the store closes the readers that are still open
    assert leftover.closed and leftover._cursor is None
    with pytest.raises(Exception):
        leftover_cursor.execute("SELECT 1")
    assert ps.shutdown(timeout=GUARD_S) is True


def test_reader_close_gives_up_waiting_and_the_cursor_closes_when_its_query_ends(
    store: DuckStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from analytics_studio.store import duck_store

    monkeypatch.setattr(duck_store, "_READER_CLOSE_WAIT_S", 0.2)
    reader = store.reader()
    cursor = reader._cursor
    gate = Gate().install(reader)
    run = Runner(reader, f"SELECT sum({gate.name}(id)) FROM t")
    wait_or_fail(gate.started, "the query")
    reader.close()  # gives up after the short wait: the query ignores interrupts while it sits in the gate
    assert reader.closed and reader._cursor is not None  # the cursor is still in use by the running query
    gate.release.set()
    run.join()
    assert isinstance(run.error, StoreError) and "interrupt" in str(run.error).casefold()
    assert reader._cursor is None  # the thread that ran the query closed it
    with pytest.raises(Exception):
        cursor.execute("SELECT 1")


def test_reader_close_interrupts_the_running_query_and_waits_for_it(store: DuckStore) -> None:
    reader = store.reader()
    gate = Gate().install(reader)
    run = Runner(reader, f"SELECT sum({gate.name}(id)) FROM t")
    wait_or_fail(gate.started, "the query")
    interrupted = spy_interrupts(reader)
    closer = threading.Thread(target=reader.close, daemon=True)
    closer.start()
    try:
        wait_or_fail(interrupted, "the interrupt by close()")
        assert closer.is_alive()  # close() waits for the query: it is still sitting in the gate
        assert reader._cursor is not None
    finally:
        gate.release.set()
    join_or_fail(closer, "close()")
    assert reader._cursor is None  # closed only after the query had ended
    run.join()
    assert isinstance(run.error, StoreError) and "interrupt" in str(run.error).casefold()


def test_a_reader_is_refused_while_the_store_is_closing(tmp_path: Path) -> None:
    store = DuckStore(str(tmp_path / "closing.db"))
    store.create_table_from_arrow("t", COLUMNS, make_batches(20))
    reader = store.reader()
    gate = Gate().install(reader)
    run = Runner(reader, f"SELECT sum({gate.name}(id)) FROM t")
    wait_or_fail(gate.started, "the query")
    interrupted = spy_interrupts(reader)
    closer = threading.Thread(target=store.close, daemon=True)
    closer.start()
    try:
        wait_or_fail(interrupted, "the interrupt by store.close()")  # close() is inside, waiting for the reader
        with pytest.raises(StoreError, match="closed"):
            store.reader()
    finally:
        gate.release.set()
    join_or_fail(closer, "store.close()")
    run.join()
    assert store._readers == set()


# --- the budget (dax_route) ----------------------------------------------------------------------------
def test_budget_cancel_waits_for_an_interrupt_in_flight_and_nothing_arrives_after_it() -> None:
    from analytics_studio.store import dax_route

    entered, release = threading.Event(), threading.Event()
    calls: list[int] = []

    def slow_interrupt() -> None:
        calls.append(1)
        entered.set()
        release.wait(GUARD_S)

    budget = dax_route._Budget(slow_interrupt, 0.0)
    budget.start()
    wait_or_fail(entered, "the first interrupt")
    returned = threading.Event()
    canceller = threading.Thread(target=lambda: (budget.cancel(), returned.set()), daemon=True)
    canceller.start()
    assert not returned.wait(0.3)  # cancel() must not return while an interrupt is still running
    release.set()
    wait_or_fail(returned, "cancel() returning")
    join_or_fail(canceller, "canceller")
    seen = len(calls)
    join_or_fail(budget._thread, "the budget watcher")  # type: ignore[arg-type]
    assert len(calls) == seen  # no interrupt arrives after cancel() returned


def test_budget_does_not_fire_after_cancel_even_when_the_watcher_was_already_deciding() -> None:
    from analytics_studio.store import dax_route

    class SlowCancel:
        """A cancel event that is 'set', but whose first is_set() call is held until released."""

        def __init__(self) -> None:
            self.entered, self.release, self.first = threading.Event(), threading.Event(), True

        def is_set(self) -> bool:
            if self.first:
                self.first = False
                self.entered.set()
                self.release.wait(GUARD_S)
            return True

        def wait(self, timeout: float | None = None) -> bool:
            return True

    fired: list[int] = []
    cancel = SlowCancel()
    budget = dax_route._Budget(lambda: fired.append(1), 3600.0, cancel)  # type: ignore[arg-type]
    budget.start()
    wait_or_fail(cancel.entered, "the watcher reading the cancel event")
    budget.cancel()  # the watcher has seen "canceled" but has not fired yet
    cancel.release.set()
    join_or_fail(budget._thread, "the budget watcher")  # type: ignore[arg-type]
    assert fired == [] and not budget.canceled.is_set()
