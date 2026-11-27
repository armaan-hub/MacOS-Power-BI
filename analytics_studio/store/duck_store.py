"""DuckDB-backed table row store."""

import datetime
import decimal
import fcntl
import contextlib
import functools
import math
import os
import threading
import time
import uuid
from collections.abc import Sequence as _AbcSequence
from typing import Any, Callable, Iterable, Iterator, List, Optional, Sequence, Tuple, TypeVar, cast

import duckdb
import pyarrow as pa

from .base import COLUMN_TYPES, StoreBusyError, StoreError, StoreLockedError

_TYPE_MAP = {
    "whole": "BIGINT",
    "decimal": "DOUBLE",
    "fixed": "DECIMAL(19,4)",
    "datetime": "TIMESTAMP",
    "text": "VARCHAR",
    "boolean": "BOOLEAN",
}

_REVERSE_TYPE_MAP = {
    "BIGINT": "whole",
    "DOUBLE": "decimal",
    "DECIMAL(19,4)": "fixed",
    "TIMESTAMP": "datetime",
    "VARCHAR": "text",
    "BOOLEAN": "boolean",
}

_MIN_BIGINT = -9223372036854775808
_MAX_BIGINT = 9223372036854775807
_FIXED_EXP = decimal.Decimal("0.0001")
_MAX_FIXED = decimal.Decimal("999999999999999.9999")
_MIN_FIXED = -_MAX_FIXED
_FIXED_LIMIT_INT = 10**15
# Wide local context so quantize never overflows the default 28-digit context.
_FIXED_CTX = decimal.Context(prec=60)
_BATCH_NAME = "__store_batch__"
_ARROW_TARGET_TYPES = {
    "boolean": pa.bool_(),
    "whole": pa.int64(),
    "decimal": pa.float64(),
    "fixed": pa.decimal128(19, 4),
    "datetime": pa.timestamp("us"),
    "text": pa.string(),
}



def _quote_identifier(ident: str) -> str:
    """Quote SQL identifier using double quotes, doubling embedded quotes."""
    return '"' + ident.replace('"', '""') + '"'


def _ascii_lower(s: str) -> str:
    """Lowercase only ASCII A-Z characters, preserving unicode casing as DuckDB does."""
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in s)


def _validate_identifier(name: Any, kind: str = "Name") -> None:
    if not isinstance(name, str):
        raise StoreError(f"{kind} must be a string, got {type(name).__name__}.")
    if not name:
        raise StoreError(f"{kind} cannot be empty.")
    for c in name:
        code = ord(c)
        if code < 32 or code == 127:
            raise StoreError(
                f"{kind} cannot contain NUL or control characters (ord {code})."
            )


def _coerce_value(val: Any, type_name: str, table_name: str, col_name: str, row_idx: int) -> Any:
    if val is None:
        return None

    if type_name == "whole":
        if isinstance(val, bool) or not isinstance(val, int):
            raise StoreError(
                f"Invalid value for column '{col_name}' of type 'whole' in table '{table_name}' "
                f"at row {row_idx}: expected int, got {type(val).__name__} ({val!r})."
            )
        if not (_MIN_BIGINT <= val <= _MAX_BIGINT):
            raise StoreError(
                f"Value for column '{col_name}' in table '{table_name}' at row {row_idx} "
                f"exceeds BIGINT range: {val!r}."
            )
        return val

    elif type_name == "decimal":
        if isinstance(val, bool):
            raise StoreError(
                f"Invalid value for column '{col_name}' of type 'decimal' in table '{table_name}' "
                f"at row {row_idx}: expected float, int, or Decimal, got bool."
            )
        if isinstance(val, float):
            return val
        if isinstance(val, int):
            try:
                return float(val)
            except OverflowError:
                raise StoreError(
                    f"Value for column '{col_name}' in table '{table_name}' at row {row_idx} "
                    f"is too large for a decimal (DOUBLE) column: int with {val.bit_length()} bits."
                ) from None
        if isinstance(val, decimal.Decimal):
            try:
                f_val = float(val)
            except (ValueError, OverflowError) as exc:
                raise StoreError(
                    f"Invalid value for column '{col_name}' of type 'decimal' in table '{table_name}' "
                    f"at row {row_idx}: cannot convert {val!r} to a float ({exc})."
                ) from None
            if val.is_finite() and not math.isfinite(f_val):
                raise StoreError(
                    f"Value for column '{col_name}' in table '{table_name}' at row {row_idx} "
                    f"is too large for a decimal (DOUBLE) column: {val!r}."
                )
            return f_val
        raise StoreError(
            f"Invalid value for column '{col_name}' of type 'decimal' in table '{table_name}' "
            f"at row {row_idx}: expected float, int, or Decimal, got {type(val).__name__} ({val!r})."
        )

    elif type_name == "fixed":
        if isinstance(val, bool) or not isinstance(val, (decimal.Decimal, int)):
            raise StoreError(
                f"Invalid value for column '{col_name}' of type 'fixed' in table '{table_name}' "
                f"at row {row_idx}: expected Decimal or int, got {type(val).__name__} ({val!r})."
            )
        if isinstance(val, int):
            if not (-_FIXED_LIMIT_INT < val < _FIXED_LIMIT_INT):
                raise StoreError(
                    f"Value for column '{col_name}' in table '{table_name}' at row {row_idx} "
                    f"exceeds DECIMAL(19,4) range: int with {val.bit_length()} bits."
                )
            d_val = decimal.Decimal(val)
        else:
            d_val = val
            if d_val.is_nan() or d_val.is_infinite():
                raise StoreError(
                    f"Value for column '{col_name}' in table '{table_name}' at row {row_idx} "
                    f"cannot be NaN or Infinity in 'fixed' type: {val!r}."
                )
            # Check magnitude before quantize so huge values give StoreError, not InvalidOperation.
            if d_val.adjusted() > 15:
                raise StoreError(
                    f"Value for column '{col_name}' in table '{table_name}' at row {row_idx} "
                    f"exceeds DECIMAL(19,4) range: {val!r}."
                )
        rounded = d_val.quantize(_FIXED_EXP, rounding=decimal.ROUND_HALF_UP, context=_FIXED_CTX)
        if not (_MIN_FIXED <= rounded <= _MAX_FIXED):
            raise StoreError(
                f"Value for column '{col_name}' in table '{table_name}' at row {row_idx} "
                f"exceeds DECIMAL(19,4) range: {rounded!r}."
            )
        return rounded

    elif type_name == "datetime":
        if not isinstance(val, datetime.datetime):
            raise StoreError(
                f"Invalid value for column '{col_name}' of type 'datetime' in table '{table_name}' "
                f"at row {row_idx}: expected naive datetime, got {type(val).__name__} ({val!r})."
            )
        if val.tzinfo is not None:
            raise StoreError(
                f"Timezone-aware datetime rejected for column '{col_name}' in table '{table_name}' "
                f"at row {row_idx}: {val!r}."
            )
        return val

    elif type_name == "text":
        if isinstance(val, (bool, bytes)) or not isinstance(val, str):
            raise StoreError(
                f"Invalid value for column '{col_name}' of type 'text' in table '{table_name}' "
                f"at row {row_idx}: expected str, got {type(val).__name__} ({val!r})."
            )
        return val

    elif type_name == "boolean":
        if not isinstance(val, bool):
            raise StoreError(
                f"Invalid value for column '{col_name}' of type 'boolean' in table '{table_name}' "
                f"at row {row_idx}: expected bool, got {type(val).__name__} ({val!r})."
            )
        return val

    raise StoreError(f"Unknown column type '{type_name}' for column '{col_name}'.")


_F = TypeVar("_F", bound=Callable[..., Any])


def _thread_locked(func: _F) -> _F:
    """Decorator ensuring public DuckStore methods fail loudly under concurrency."""
    @functools.wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        lock: threading.RLock = getattr(self, "_lock", None)
        if lock is not None:
            acquired = lock.acquire(blocking=False)
            if not acquired:
                raise StoreBusyError("The store is busy with another operation.")
            try:
                return func(self, *args, **kwargs)
            finally:
                lock.release()
        return func(self, *args, **kwargs)
    return cast(_F, wrapper)


def _refuse_while_read(func: _F) -> _F:
    """Decorator for the methods that change table content or the table catalog (create, drop, append, load).

    A StoreReader sees each statement as of the moment it starts, so a table that is dropped, reloaded or appended
    to between two statements of one answer would give a value that fits neither the old nor the new data. While
    a reader is open these methods raise StoreBusyError, whoever calls them. (Temporary grid views and checkpoints
    are not refused: they change nothing a reader sees.)
    """
    @functools.wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        lock = getattr(self, "_readers_lock", None)
        if lock is not None:
            with lock:
                reading = bool(self._readers)
            if reading:
                raise StoreBusyError("The store is being read; try again when the read has finished.")
        return func(self, *args, **kwargs)
    return cast(_F, wrapper)


def _validate_select(conn: duckdb.DuckDBPyConnection, sql: Any) -> None:
    """Raise StoreError unless `sql` is exactly one SELECT statement. Shared by DuckStore.execute and StoreReader.execute."""
    if not isinstance(sql, str) or not sql.strip():
        raise StoreError("Query must be a non-empty string.")

    try:
        stmts = conn.extract_statements(sql)
    except Exception as exc:
        raise StoreError(f"Invalid SQL: {exc}") from exc

    if len(stmts) != 1:
        raise StoreError(
            f"Only a single statement is allowed; found {len(stmts)} statements."
        )

    stmt = stmts[0]
    if stmt.type != duckdb.StatementType.SELECT:
        raise StoreError(
            f"Only SELECT queries are allowed; received statement type {stmt.type}."
        )


_READER_CLOSE_WAIT_S = 10.0
_READER_REINTERRUPT_S = 0.05


class StoreReader:
    """A read-only handle on a DuckStore with its OWN DuckDB connection (a cursor of the store's connection).

    Made by `DuckStore.reader()`. It runs the same single-SELECT queries as `DuckStore.execute` with the same
    checks and error text, but it never takes `DuckStore._lock`: a reader on a background thread and the data grid
    on the GUI thread (which uses the main connection) run at the same time and never see "store is busy" from
    each other. Each statement sees the data committed when it starts (measured on duckdb 1.5.5: a statement that
    is already running keeps its snapshot, the next statement sees a later commit of the main connection).

    `interrupt()` stops only this reader's own running query. `close()` is safe to call from any thread: it stops a
    running query and the cursor is closed as soon as that query has ended.
    """

    def __init__(self, owner: "DuckStore", cursor: duckdb.DuckDBPyConnection) -> None:
        self._owner = owner
        self._cursor: Optional[duckdb.DuckDBPyConnection] = cursor
        self._state = threading.Condition(threading.Lock())
        self._closed = False
        self._active = 0

    @property
    def closed(self) -> bool:
        return self._closed

    def table_version(self, name: str) -> int:
        """The owner store's change token for a table (the same stamp as DuckStore.table_version; takes no lock)."""
        return self._owner.table_version(name)

    def table_writing(self, name: str) -> bool:
        """True while an append to the table is committing (DuckStore.table_writing; takes no lock)."""
        return self._owner.table_writing(name)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> List[Tuple[Any, ...]]:
        """Run a single read query (SELECT only) and return list of tuples (same rules as DuckStore.execute)."""
        with self._state:
            cursor = self._cursor
            if self._closed or cursor is None:
                raise StoreError("Store is closed.")
            self._active += 1
        try:
            _validate_select(cursor, sql)
            try:
                return cursor.execute(sql, params).fetchall()
            except Exception as exc:
                raise StoreError(f"Query execution failed: {exc}") from exc
        finally:
            with self._state:
                self._active -= 1
                if self._active == 0:
                    if self._closed:
                        self._close_cursor_locked()
                    self._state.notify_all()

    def interrupt(self) -> None:
        """Stop the query this reader is running (and no other reader's, and not the main connection). Never raises."""
        cursor = self._cursor
        if cursor is not None:
            try:
                cursor.interrupt()
            except Exception:
                pass

    def _close_cursor_locked(self) -> None:
        cursor, self._cursor = self._cursor, None
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass

    def close(self) -> None:
        """Close the reader. Idempotent, never raises. A running query is interrupted and the cursor is closed
        when it ends (waiting at most `_READER_CLOSE_WAIT_S`, then left to the thread that runs the query)."""
        with self._state:
            self._closed = True
        self._owner._forget_reader(self)
        deadline = time.monotonic() + _READER_CLOSE_WAIT_S
        with self._state:
            while self._active > 0:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                self.interrupt()
                self._state.wait(min(_READER_REINTERRUPT_S, remaining))
            self._close_cursor_locked()

    def __enter__(self) -> "StoreReader":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


class DuckStore:
    """DuckDB implementation of Store interface.

    Notes on locking:
    An exclusive advisory lock is held via fcntl.flock on '<path>.lock'.
    A stale '.lock' file is left behind on disk on purpose; the lock is held on the
    open file descriptor and automatically released when the file is closed or the process terminates.

    threads parameter is optional; None preserves DuckDB's default thread count.
    """

    def __init__(
        self,
        path: str,
        memory_limit: str = "2GB",
        threads: Optional[int] = None,
        temp_directory: Optional[str] = None,
    ) -> None:
        if not isinstance(path, str) or not path.strip():
            raise StoreError("Store path must be a non-empty string.")

        real_target = os.path.realpath(path)
        self.path = real_target
        self.lock_path = real_target + ".lock"
        self._lock_fd: Optional[int] = None
        self._lock = threading.RLock()
        self._conn: Optional[duckdb.DuckDBPyConnection] = None
        # In-memory change counters per table (lower-cased name); never persisted.
        self._versions: dict[str, int] = {}
        self._writing: dict[str, int] = {}  # tables with an append between its last insert and the end of its bumps
        # True while append_rows or create_table_from_arrow holds an open transaction.
        self._txn_open = False
        # Open StoreReaders. A plain set under its own small lock (never `_lock`), so any thread can interrupt them.
        self._readers_lock = threading.Lock()
        self._readers: set[StoreReader] = set()
        self._readers_closing = False

        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        except OSError as exc:
            raise StoreError(f"Failed to create directory for store '{self.path}': {exc}") from exc

        self._acquire_lock()
        self._init_conn(
            memory_limit=memory_limit,
            threads=threads,
            temp_directory=temp_directory,
        )

    def _acquire_lock(self) -> None:
        try:
            self._lock_fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o666)
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            if self._lock_fd is not None:
                try:
                    os.close(self._lock_fd)
                except OSError:
                    pass
                self._lock_fd = None
            raise StoreLockedError(
                f"Store at '{self.path}' is already locked by another process or instance."
            ) from exc
        except OSError as exc:
            if self._lock_fd is not None:
                try:
                    os.close(self._lock_fd)
                except OSError:
                    pass
                self._lock_fd = None
            raise StoreError(f"Failed to acquire lock file at '{self.lock_path}': {exc}") from exc

    def _init_conn(
        self,
        memory_limit: str = "2GB",
        threads: Optional[int] = None,
        temp_directory: Optional[str] = None,
    ) -> None:
        spill_target = os.path.realpath(temp_directory) if temp_directory is not None else os.path.dirname(self.path)
        try:
            os.makedirs(spill_target, exist_ok=True)
        except OSError as exc:
            raise StoreError(f"Failed to create temp directory '{spill_target}': {exc}") from exc

        config: dict[str, Any] = {
            "enable_external_access": False,
            "memory_limit": memory_limit,
            "temp_directory": spill_target,
        }
        if threads is not None:
            config["threads"] = threads

        try:
            self._conn = duckdb.connect(self.path, config=config)
        except Exception as exc:
            self.close()
            raise StoreError(f"Failed to open DuckDB store at '{self.path}': {exc}") from exc

    def interrupt(self) -> None:
        """Stop the query that another thread is running on the MAIN connection of this store. Takes NO store lock.

        It does not stop a query that runs on a `StoreReader` (a reader has its own connection): use
        `StoreReader.interrupt()` for one reader or `interrupt_all_readers()` for all of them.

        The running query holds `_lock` (see `_thread_locked`: a second caller gets StoreBusyError at once, it
        never waits), so taking the lock here would fail exactly when interrupt is needed. DuckDB's own
        connection.interrupt() is safe to call from another thread, and does nothing on an idle connection.
        """
        conn = self._conn
        if conn is not None:
            try:
                conn.interrupt()
            except Exception:
                pass

    def reader(self) -> StoreReader:
        """A new `StoreReader` (its own connection) for read queries on another thread. Takes NO store lock.

        Raises StoreError when the store is closed and StoreBusyError while an append or a table creation holds
        an open transaction on the main connection. Close the reader (or use it as a context manager) when done.
        """
        with self._readers_lock:
            conn = self._conn
            if conn is None or self._readers_closing:
                raise StoreError("Store is closed.")
            if self._txn_open:
                raise StoreBusyError("The store is busy with another operation.")
            try:
                cursor = conn.cursor()
            except Exception as exc:
                raise StoreError(f"Could not open a reader: {exc}") from exc
            reader = StoreReader(self, cursor)
            self._readers.add(reader)
            return reader

    def _forget_reader(self, reader: StoreReader) -> None:
        with self._readers_lock:
            self._readers.discard(reader)

    def interrupt_all_readers(self) -> None:
        """Stop the query of every open reader. Takes NO store lock; safe from any thread and when none is open."""
        with self._readers_lock:
            readers = list(self._readers)
        for reader in readers:
            reader.interrupt()

    @_thread_locked
    def close(self) -> None:
        """Close the store: every reader is interrupted and closed first (a reader gives up waiting after 10 s).

        `_conn.close()` itself blocks until a query that cannot be interrupted has ended.
        """
        # Every reader first: a cursor query keeps running after its main connection is closed (measured on
        # duckdb 1.5.5, it ended 15.9 s later with "No open result set"), so each one is interrupted and has
        # ended before `_conn` closes.
        lock = getattr(self, "_readers_lock", None)
        if lock is not None:
            with lock:
                self._readers_closing = True
                readers = list(self._readers)
            self.interrupt_all_readers()
            for reader in readers:
                reader.close()
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def __enter__(self) -> "DuckStore":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def _bump_version(self, name: str) -> None:
        key = _ascii_lower(name)
        self._versions[key] = self._versions.get(key, 0) + 1

    def _set_writing(self, name: str, on: bool) -> None:
        key = _ascii_lower(name)
        count = self._writing.get(key, 0) + (1 if on else -1)
        if count > 0:
            self._writing[key] = count
        else:
            self._writing.pop(key, None)

    @contextlib.contextmanager
    def _flagged(self, name: str) -> Iterator[None]:
        """Flag the table as being written for the body (cleared on any exit, an error included)."""
        self._set_writing(name, True)
        try:
            yield
        finally:
            self._set_writing(name, False)

    def table_writing(self, name: str) -> bool:
        """True while a change to this table is committing (append_rows, create_table, drop_table, create_table_from_arrow):
        from just before its COMMIT (or DDL statement) until its token bumps are done.

        Like table_version it takes no lock. A reader that compares table_version before and after several statements
        also refuses when this is True at its start: rows may become visible between two statements while the token
        has not yet moved.
        """
        return isinstance(name, str) and self._writing.get(_ascii_lower(name), 0) > 0

    def table_version(self, name: str) -> int:
        """Return an in-memory change token for a table.

        The token goes up by one after every successful create_table,
        drop_table and create_table_from_arrow for that table name, and by two for
        every successful append_rows (once just before its COMMIT, once after; a failed
        COMMIT may leave the first one). It starts at 0 for
        a name this store object has never changed, it is never saved to disk, and it
        does not take the store lock, so it can be read while an import runs.
        Models use it to know that cached facts about a table are out of date.
        """
        if not isinstance(name, str):
            return 0
        return self._versions.get(_ascii_lower(name), 0)

    def _check_open(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            raise StoreError("Store is closed.")
        return self._conn

    def _get_raw_tables(self, conn: duckdb.DuckDBPyConnection) -> List[str]:
        try:
            rows = conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' ORDER BY table_name"
            ).fetchall()
            return [r[0] for r in rows]
        except Exception as exc:
            raise StoreError(f"Failed to query table names: {exc}") from exc

    def _resolve_table_name(self, name: Any, conn: duckdb.DuckDBPyConnection) -> str:
        _validate_identifier(name, kind="Table name")
        all_tables = self._get_raw_tables(conn)
        for t in all_tables:
            if t == name:
                return t
        lower_name = _ascii_lower(name)
        for t in all_tables:
            if _ascii_lower(t) == lower_name:
                return t
        raise StoreError(f"Table '{name}' does not exist.")

    @_thread_locked
    def resolve_table_name(self, name: str) -> str:
        """Resolve a table name using ASCII-only case insensitivity."""
        conn = self._check_open()
        return self._resolve_table_name(name, conn)

    @_thread_locked
    @_refuse_while_read
    def create_table(self, name: str, columns: Sequence[Tuple[str, str]]) -> None:
        conn = self._check_open()
        _validate_identifier(name, kind="Table name")
        if name.startswith("__"):
            raise StoreError(f"Table name '{name}' is reserved: names starting with '__' are internal.")

        if isinstance(columns, str) or not hasattr(columns, "__iter__"):
            raise StoreError("Columns must be a sequence of (name, type) pairs, not string.")

        cols_list = list(columns)
        if len(cols_list) == 0:
            raise StoreError(f"Cannot create table '{name}' with zero columns.")

        # Check existing tables case-insensitively
        all_tables = self._get_raw_tables(conn)
        target_lower = _ascii_lower(name)
        for t in all_tables:
            if _ascii_lower(t) == target_lower:
                raise StoreError(f"Table '{name}' already exists (matches '{t}').")

        seen_ci: set[str] = set()
        col_defs: list[str] = []

        for col in cols_list:
            if not isinstance(col, (tuple, list)) or len(col) != 2:
                raise StoreError(f"Invalid column specification: {col!r}")
            col_name, type_name = col
            _validate_identifier(col_name, kind="Column name")

            col_ci = _ascii_lower(col_name)
            if col_ci == "__rn":
                raise StoreError("Column name '__rn' is reserved for hidden row index.")
            if col_ci in seen_ci:
                raise StoreError(f"Duplicate column name: '{col_name}'")
            seen_ci.add(col_ci)

            if not isinstance(type_name, str) or type_name not in _TYPE_MAP:
                raise StoreError(
                    f"Unknown column type {type_name!r}. Must be one of {COLUMN_TYPES}."
                )

            sql_type = _TYPE_MAP[type_name]
            col_defs.append(f"{_quote_identifier(col_name)} {sql_type}")

        col_defs.append('"__rn" BIGINT')
        quoted_name = _quote_identifier(name)
        create_sql = f"CREATE TABLE {quoted_name} ({', '.join(col_defs)})"
        with self._flagged(name):  # flagged from just before the statement until the bump is done (see table_writing)
            try:
                conn.execute(create_sql)
            except Exception as exc:
                raise StoreError(f"Failed to create table '{name}': {exc}") from exc
            self._bump_version(name)

    @_thread_locked
    def has_table(self, name: str) -> bool:
        conn = self._check_open()
        if not isinstance(name, str) or not name:
            return False
        all_tables = self._get_raw_tables(conn)
        target_lower = _ascii_lower(name)
        return any(_ascii_lower(t) == target_lower for t in all_tables)

    @_thread_locked
    def table_names(self) -> List[str]:
        conn = self._check_open()
        return self._get_raw_tables(conn)

    @_thread_locked
    def columns(self, name: str) -> List[Tuple[str, str]]:
        conn = self._check_open()
        resolved_name = self._resolve_table_name(name, conn)

        try:
            rows = conn.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = ? "
                "ORDER BY ordinal_position",
                [resolved_name],
            ).fetchall()
        except Exception as exc:
            raise StoreError(f"Failed to query columns for '{resolved_name}': {exc}") from exc

        result: list[Tuple[str, str]] = []
        for col_name, data_type in rows:
            if _ascii_lower(col_name) == "__rn":
                continue
            dt_upper = data_type.upper()
            logical_type = _REVERSE_TYPE_MAP.get(dt_upper)
            if logical_type is None:
                raise StoreError(
                    f"Unknown stored column type '{data_type}' for column '{col_name}' in table '{resolved_name}'."
                )
            result.append((col_name, logical_type))
        return result

    @_thread_locked
    def row_count(self, name: str) -> int:
        conn = self._check_open()
        resolved_name = self._resolve_table_name(name, conn)
        quoted_name = _quote_identifier(resolved_name)
        try:
            row = conn.execute(f"SELECT COUNT(*) FROM {quoted_name}").fetchone()
            return row[0] if row else 0
        except Exception as exc:
            raise StoreError(f"Failed to get row count for '{resolved_name}': {exc}") from exc

    @_thread_locked
    @_refuse_while_read
    def drop_table(self, name: str) -> None:
        conn = self._check_open()
        resolved_name = self._resolve_table_name(name, conn)
        quoted_name = _quote_identifier(resolved_name)
        with self._flagged(resolved_name):
            try:
                conn.execute(f"DROP TABLE {quoted_name}")
            except Exception as exc:
                raise StoreError(f"Failed to drop table '{resolved_name}': {exc}") from exc
            self._bump_version(resolved_name)

    @_thread_locked
    @_refuse_while_read
    def append_rows(self, name: str, rows: Iterable[Sequence[Any]]) -> int:
        """Append rows in one transaction; return the number of rows added.

        Values are strict: whole takes int only, fixed takes Decimal or int, datetime
        takes naive datetime only. numpy integers and floats, pandas Timestamps and
        timezone-aware datetimes are rejected on purpose; the importer (B2/B3) must
        convert them to plain Python int, float, Decimal and naive datetime first.
        Any failure, including KeyboardInterrupt, rolls the whole append back.
        """
        conn = self._check_open()
        resolved_name = self._resolve_table_name(name, conn)

        col_info = self.columns(resolved_name)
        expected_cols = len(col_info)
        current_rn = self.row_count(resolved_name)
        quoted_tbl = _quote_identifier(resolved_name)

        pa_fields = []
        for c_name, t_name in col_info:
            if t_name == "whole":
                pa_fields.append((c_name, pa.int64()))
            elif t_name == "decimal":
                pa_fields.append((c_name, pa.float64()))
            elif t_name == "fixed":
                pa_fields.append((c_name, pa.decimal128(19, 4)))
            elif t_name == "datetime":
                pa_fields.append((c_name, pa.timestamp("us")))
            elif t_name == "text":
                pa_fields.append((c_name, pa.string()))
            elif t_name == "boolean":
                pa_fields.append((c_name, pa.bool_()))
            else:
                raise StoreError(f"Unsupported column type: {t_name}")
        pa_fields.append(("__rn", pa.int64()))
        pa_schema = pa.schema(pa_fields)

        batch_size = 50_000
        current_batch: list[Tuple[Any, ...]] = []
        total_appended = 0
        overall_row_idx = 0

        try:
            conn.execute("BEGIN TRANSACTION")
        except Exception as exc:
            raise StoreError(f"Failed to begin transaction: {exc}") from exc

        self._txn_open = True
        writing = False
        try:
            for row in rows:
                if isinstance(row, (str, bytes, bytearray)) or not isinstance(row, _AbcSequence):
                    raise StoreError(
                        f"Row {overall_row_idx} for table '{resolved_name}' must be a tuple or list of values, "
                        f"got {type(row).__name__}."
                    )
                if len(row) != expected_cols:
                    raise StoreError(
                        f"Row {overall_row_idx} has {len(row)} values, but table '{resolved_name}' expects {expected_cols}."
                    )
                coerced_row = []
                for idx, (c_name, t_name) in enumerate(col_info):
                    coerced_row.append(
                        _coerce_value(row[idx], t_name, resolved_name, c_name, overall_row_idx)
                    )
                current_batch.append(tuple(coerced_row))
                overall_row_idx += 1

                if len(current_batch) >= batch_size:
                    self._insert_batch(
                        conn, quoted_tbl, current_batch, col_info, pa_schema, current_rn
                    )
                    total_appended += len(current_batch)
                    current_rn += len(current_batch)
                    current_batch = []

            if current_batch:
                self._insert_batch(
                    conn, quoted_tbl, current_batch, col_info, pa_schema, current_rn
                )
                total_appended += len(current_batch)
                current_rn += len(current_batch)
                current_batch = []

            # From here to the end of the call the table is "being written": the rows become visible at the COMMIT and
            # the token goes up before it and after it, but no single token read can tell a reader that the rows
            # landed between two of its statements (a lagging second bump). A reader that finds the flag set at the
            # start of its statements, or a changed token at the end, refuses (see table_writing).
            self._set_writing(resolved_name, True)
            writing = True
            self._bump_version(resolved_name)
            conn.execute("COMMIT")
            self._txn_open = False
        except BaseException as exc:
            # BaseException on purpose: an interrupt must not leave the transaction open.
            self._txn_open = False
            if writing:
                self._set_writing(resolved_name, False)
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            if isinstance(exc, StoreError) or not isinstance(exc, Exception):
                raise
            raise StoreError(
                f"Failed to append rows to '{resolved_name}' at row {overall_row_idx}: {exc}"
            ) from exc

        try:
            self._bump_version(resolved_name)
        finally:
            self._set_writing(resolved_name, False)
        return total_appended

    def _insert_batch(
        self,
        conn: duckdb.DuckDBPyConnection,
        quoted_tbl: str,
        batch: list[Tuple[Any, ...]],
        col_info: list[Tuple[str, str]],
        pa_schema: Any,
        start_rn: int,
    ) -> None:
        batch_len = len(batch)
        if batch_len == 0:
            return

        cols_dict: dict[str, list[Any]] = {}
        for idx, (c_name, _) in enumerate(col_info):
            cols_dict[c_name] = [row[idx] for row in batch]
        cols_dict["__rn"] = list(range(start_rn, start_rn + batch_len))

        try:
            batch_table = pa.Table.from_pydict(cols_dict, schema=pa_schema)
            conn.register(_BATCH_NAME, batch_table)
            conn.execute(f"INSERT INTO {quoted_tbl} SELECT * FROM {_BATCH_NAME}")
        except Exception as exc:
            raise StoreError(f"Failed to insert batch: {exc}") from exc
        finally:
            try:
                conn.unregister(_BATCH_NAME)
            except Exception:
                pass

    @_thread_locked
    def read_page(
        self,
        name: str,
        offset: int,
        limit: int,
        columns: Optional[Sequence[str]] = None,
    ) -> List[Tuple[Any, ...]]:
        conn = self._check_open()
        resolved_name = self._resolve_table_name(name, conn)

        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise StoreError(f"Offset must be a non-negative integer, got {offset!r}.")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise StoreError(f"Limit must be a non-negative integer, got {limit!r}.")

        all_cols = self.columns(resolved_name)
        col_lookup: dict[str, str] = {}
        for c_name, _ in all_cols:
            col_lookup[_ascii_lower(c_name)] = c_name

        if columns is None:
            selected_cols = [c[0] for c in all_cols]
        else:
            if isinstance(columns, str) or not hasattr(columns, "__iter__"):
                raise StoreError("Columns parameter must be a sequence of column names, not a string.")
            selected_cols = []
            seen_ci: set[str] = set()
            for c in columns:
                if not isinstance(c, str):
                    raise StoreError(f"Column name must be a string, got {type(c).__name__}.")
                c_ci = _ascii_lower(c)
                if c_ci in seen_ci:
                    raise StoreError(f"Duplicate column '{c}' in read_page request.")
                seen_ci.add(c_ci)
                if c_ci not in col_lookup:
                    raise StoreError(f"Column '{c}' does not exist in table '{resolved_name}'.")
                selected_cols.append(col_lookup[c_ci])

        if limit == 0 or not selected_cols:
            return []

        selected_sql = ", ".join(_quote_identifier(c) for c in selected_cols)
        quoted_tbl = _quote_identifier(resolved_name)
        sql = (
            f"SELECT {selected_sql} FROM {quoted_tbl} "
            f"WHERE \"__rn\" >= ? AND \"__rn\" < ? ORDER BY \"__rn\" ASC"
        )
        try:
            return conn.execute(sql, [offset, offset + limit]).fetchall()
        except Exception as exc:
            raise StoreError(f"Failed to read page from '{resolved_name}': {exc}") from exc

    @_thread_locked
    def execute(self, sql: str, params: Sequence[Any] = ()) -> List[Tuple[Any, ...]]:
        """Run a single read query (SELECT only) and return list of tuples.

        Note: When running 'SELECT *', the returned tuples will also include the hidden
        '__rn' column as the last element.

        Only SQL generated by the engine may be passed in; user-typed SQL must never reach it,
        because files inside the store's own folder stay readable through DuckDB's external-access rule.
        """
        conn = self._check_open()
        _validate_select(conn, sql)

        try:
            return conn.execute(sql, params).fetchall()
        except Exception as exc:
            raise StoreError(f"Query execution failed: {exc}") from exc

    @_thread_locked
    def iter_rows(
        self,
        sql: str,
        params: Sequence[Any] = (),
        chunk_size: int = 50_000,
    ) -> Iterator[List[Tuple[Any, ...]]]:
        """Validate one SELECT query now and return a generator that yields rows in chunks.

        Validation (non-empty string, one statement, SELECT only) runs eagerly, when
        iter_rows(...) is called, so a bad query raises at the call and not at the first
        next(). The lock only guards this validation and the creation of the generator:
        iterating is NOT locked, so callers must iterate inside session.call (or another
        owner of the store) and must not let another thread use the store meanwhile.
        The generator closes its cursor in finally, also when it is closed early.
        """
        conn = self._check_open()
        if not isinstance(sql, str) or not sql.strip():
            raise StoreError("Query must be a non-empty string.")

        try:
            stmts = conn.extract_statements(sql)
        except Exception as exc:
            raise StoreError(f"Invalid SQL: {exc}") from exc

        if len(stmts) != 1:
            raise StoreError(
                f"Only a single statement is allowed; found {len(stmts)} statements."
            )

        stmt = stmts[0]
        if stmt.type != duckdb.StatementType.SELECT:
            raise StoreError(
                f"Only SELECT queries are allowed; received statement type {stmt.type}."
            )

        return self._iter_rows_chunks(conn, sql, params, chunk_size)

    def _iter_rows_chunks(
        self,
        conn: Any,
        sql: str,
        params: Sequence[Any],
        chunk_size: int,
    ) -> Iterator[List[Tuple[Any, ...]]]:
        """Generator behind iter_rows; not locked (see iter_rows)."""
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params)
            while True:
                chunk = cursor.fetchmany(chunk_size)
                if not chunk:
                    break
                yield chunk
        except Exception as exc:
            raise StoreError(f"Query execution failed: {exc}") from exc
        finally:
            try:
                cursor.close()
            except Exception:
                pass

    @_thread_locked
    def checkpoint(self) -> None:
        """Execute a checkpoint to flush the write-ahead log to disk.

        Must be called before copying or moving the database file to ensure all
        committed data is persisted in the main file rather than left in the WAL.
        """
        conn = self._check_open()
        if self._txn_open:
            raise StoreError("Cannot checkpoint while a transaction is open.")
        try:
            conn.execute("CHECKPOINT")
        except Exception as exc:
            raise StoreError(f"Checkpoint failed: {exc}") from exc

    @_thread_locked
    def create_view_ids(
        self,
        name: str,
        select_sql: str,
        params: Sequence[Any] = (),
    ) -> None:
        """Create a temporary table containing ordered __rn values for model views.

        `name` must begin with '__stm_'.
        `select_sql` must be a single SELECT statement returning at least `__rn`.
        A positional column `position` is computed via `(ROW_NUMBER() OVER ()) - 1`.
        """
        conn = self._check_open()
        _validate_identifier(name, kind="View name")
        if not name.startswith("__stm_"):
            raise StoreError(
                f"View name '{name}' must start with reserved prefix '__stm_'."
            )

        # Refuse names that already exist as a table or temp table
        all_raw = self._get_raw_tables(conn)
        target_lower = _ascii_lower(name)
        if any(_ascii_lower(t) == target_lower for t in all_raw):
            raise StoreError(f"Table '{name}' already exists.")

        try:
            temp_tables = conn.execute(
                "SELECT table_name FROM duckdb_tables() WHERE temporary"
            ).fetchall()
            temp_names = [r[0] for r in temp_tables]
            if any(_ascii_lower(t) == target_lower for t in temp_names):
                raise StoreError(f"Temporary table '{name}' already exists.")
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(f"Failed to check existing temp tables: {exc}") from exc

        if not isinstance(select_sql, str) or not select_sql.strip():
            raise StoreError("Query must be a non-empty string.")

        try:
            stmts = conn.extract_statements(select_sql)
        except Exception as exc:
            raise StoreError(f"Invalid SQL: {exc}") from exc

        if len(stmts) != 1:
            raise StoreError(
                f"Only a single statement is allowed; found {len(stmts)} statements."
            )

        stmt = stmts[0]
        if stmt.type != duckdb.StatementType.SELECT:
            raise StoreError(
                f"Only SELECT queries are allowed; received statement type {stmt.type}."
            )

        quoted_name = _quote_identifier(name)
        create_sql = (
            f"CREATE TEMP TABLE {quoted_name} AS "
            f"SELECT \"__rn\", (ROW_NUMBER() OVER ()) - 1 AS position "
            f"FROM ({select_sql})"
        )
        try:
            conn.execute(create_sql, params)
        except Exception as exc:
            raise StoreError(f"Failed to create view ids '{name}': {exc}") from exc

    @_thread_locked
    def register_arrow_ids(
        self,
        name: str,
        rns: Sequence[int],
    ) -> None:
        """Create a temporary view table from an explicit sequence of __rn row ids.

        `name` must start with '__stm_'.
        """
        conn = self._check_open()
        _validate_identifier(name, kind="View name")
        if not name.startswith("__stm_"):
            raise StoreError(
                f"View name '{name}' must start with reserved prefix '__stm_'."
            )

        all_raw = self._get_raw_tables(conn)
        target_lower = _ascii_lower(name)
        if any(_ascii_lower(t) == target_lower for t in all_raw):
            raise StoreError(f"Table '{name}' already exists.")

        try:
            temp_tables = conn.execute(
                "SELECT table_name FROM duckdb_tables() WHERE temporary"
            ).fetchall()
            temp_names = [r[0] for r in temp_tables]
            if any(_ascii_lower(t) == target_lower for t in temp_names):
                raise StoreError(f"Temporary table '{name}' already exists.")
        except StoreError:
            raise
        except Exception as exc:
            raise StoreError(f"Failed to check existing temp tables: {exc}") from exc

        quoted_name = _quote_identifier(name)
        batch_name = f"__stm_batch_{uuid.uuid4().hex[:8]}__"
        rn_array = pa.array(rns, type=pa.int64())
        pos_array = pa.array(range(len(rns)), type=pa.int64())
        pa_table = pa.Table.from_arrays(
            [rn_array, pos_array], names=["__rn", "position"]
        )

        conn.register(batch_name, pa_table)
        try:
            conn.execute(
                f"CREATE TEMP TABLE {quoted_name} AS SELECT * FROM {batch_name}"
            )
        except Exception as exc:
            raise StoreError(f"Failed to register view ids '{name}': {exc}") from exc
        finally:
            try:
                conn.unregister(batch_name)
            except Exception:
                pass

    @_thread_locked
    def drop_view(self, name: str) -> None:
        """Drop a temporary view table. Refuses non-__stm_ names and non-temporary tables."""
        conn = self._check_open()
        _validate_identifier(name, kind="View name")
        if not name.startswith("__stm_"):
            raise StoreError(
                f"View name '{name}' must start with reserved prefix '__stm_'."
            )

        # Check if the table exists as a non-temporary table
        all_raw = self._get_raw_tables(conn)
        target_lower = _ascii_lower(name)
        if any(_ascii_lower(t) == target_lower for t in all_raw):
            raise StoreError(f"Refusing to drop non-temporary table '{name}'.")

        # Verify that it is indeed a temporary table (or does not exist)
        try:
            temp_rows = conn.execute(
                "SELECT table_name FROM duckdb_tables() WHERE temporary AND table_name = ?",
                [name],
            ).fetchall()
            if not temp_rows:
                # Does not exist as a temporary table
                return
        except Exception as exc:
            raise StoreError(f"Failed to inspect temporary tables: {exc}") from exc

        quoted_name = _quote_identifier(name)
        try:
            conn.execute(f"DROP TABLE {quoted_name}")
        except Exception as exc:
            raise StoreError(f"Failed to drop view '{name}': {exc}") from exc

    @_thread_locked
    @_refuse_while_read
    def create_table_from_arrow(
        self,
        name: str,
        columns: Sequence[Tuple[str, str]],
        batches: Iterable[pa.RecordBatch],
        *,
        cancel_event: Optional[Any] = None,
        progress: Optional[Any] = None,
        max_rows: Optional[int] = None,
        progress_label: Optional[str] = "CSV",
    ) -> int:
        """Create a table with typed columns and stream Arrow record batches in one transaction.

        Accepts all six store types with exact Arrow types:
        - boolean: pa.bool_()
        - whole: pa.int64()
        - decimal: pa.float64()
        - fixed: pa.decimal128(19, 4)
        - datetime: pa.timestamp("us")
        - text: pa.string() ONLY (large_string is refused)

        The batch schema must match the declared column names and exact types.
        Schema-level metadata is accepted and ignored. Field nullable flags are
        not restricted (pyarrow writes nullable fields by default, so both nullable
        and non-nullable fields are accepted).

        The store has one connection and is not thread-safe: an import running on a
        worker thread owns the store until it returns.
        Any exception, row limit overflow, or cancel_event trigger rolls back the
        transaction cleanly so that no partial table is left in the store.
        Returns the total number of rows inserted.
        """
        conn = self._check_open()
        _validate_identifier(name, kind="Table name")
        if name.startswith("__"):
            raise StoreError(f"Table name '{name}' is reserved: names starting with '__' are internal.")

        if isinstance(columns, str) or not hasattr(columns, "__iter__"):
            raise StoreError("Columns must be a sequence of (name, type) pairs, not string.")

        cols_list = list(columns)
        if len(cols_list) == 0:
            raise StoreError(f"Cannot create table '{name}' with zero columns.")

        # Check existing tables case-insensitively
        all_tables = self._get_raw_tables(conn)
        target_lower = _ascii_lower(name)
        for t in all_tables:
            if _ascii_lower(t) == target_lower:
                raise StoreError(f"Table '{name}' already exists (matches '{t}').")

        seen_ci: set[str] = set()
        col_names: list[str] = []
        col_defs: list[str] = []

        for col in cols_list:
            if not isinstance(col, (tuple, list)) or len(col) != 2:
                raise StoreError(f"Invalid column specification: {col!r}")
            col_name, type_name = col
            _validate_identifier(col_name, kind="Column name")

            col_ci = _ascii_lower(col_name)
            if col_ci == "__rn":
                raise StoreError("Column name '__rn' is reserved for hidden row index.")
            if col_ci in seen_ci:
                raise StoreError(f"Duplicate column name: '{col_name}'")
            seen_ci.add(col_ci)

            if not isinstance(type_name, str) or type_name not in _TYPE_MAP:
                raise StoreError(
                    f"Unknown column type {type_name!r}. Must be one of {COLUMN_TYPES}."
                )

            sql_type = _TYPE_MAP[type_name]
            col_names.append(col_name)
            col_defs.append(f"{_quote_identifier(col_name)} {sql_type}")

        col_defs.append('"__rn" BIGINT')
        quoted_name = _quote_identifier(name)
        create_sql = f"CREATE TABLE {quoted_name} ({', '.join(col_defs)})"

        table_created = False
        try:
            conn.execute("BEGIN TRANSACTION")
            self._txn_open = True
            conn.execute(create_sql)
            table_created = True

            total_rows = 0
            for batch in batches:
                if cancel_event is not None and cancel_event.is_set():
                    from analytics_studio.file_import import ImportCancelledError
                    raise ImportCancelledError("Import canceled.")

                if not isinstance(batch, pa.RecordBatch):
                    raise StoreError(f"Expected pa.RecordBatch, got {type(batch).__name__}.")

                if batch.schema.names != col_names:
                    raise StoreError(
                        f"Batch column names {batch.schema.names} do not match table columns {col_names}."
                    )
                for idx_field, field in enumerate(batch.schema):
                    expected_store_type = cols_list[idx_field][1]
                    expected_arrow_type = _ARROW_TARGET_TYPES[expected_store_type]
                    if expected_store_type == "text" and not field.type.equals(pa.string()):
                        raise StoreError(
                            f"Batch column '{field.name}' has non-string type {field.type}."
                        )
                    if field.type != expected_arrow_type:
                        raise StoreError(
                            f"Batch column '{field.name}' has type {field.type}, expected {expected_arrow_type}."
                        )

                batch_len = batch.num_rows
                if max_rows is not None and total_rows + batch_len > max_rows:
                    from analytics_studio.file_import import FileImportError
                    raise FileImportError(f"The file exceeds the {max_rows:,}-row import limit.")

                rn_array = pa.array(range(total_rows, total_rows + batch_len), type=pa.int64())
                table_batch = pa.Table.from_batches([batch]).append_column("__rn", rn_array)
                conn.register(_BATCH_NAME, table_batch)
                try:
                    conn.execute(f"INSERT INTO {quoted_name} SELECT * FROM {_BATCH_NAME}")
                finally:
                    conn.unregister(_BATCH_NAME)

                total_rows += batch_len
                if progress is not None and progress_label is not None:
                    progress(f"Imported {total_rows:,} {progress_label} rows...")

            # Defensive post-insert check on timestamps/dates if datetime columns exist
            dt_cols = [c_name for c_name, t_name in cols_list if t_name == "datetime"]
            if dt_cols:
                conds = [
                    f'(isinf({_quote_identifier(c)}) OR year({_quote_identifier(c)}) NOT BETWEEN 1 AND 9999)'
                    for c in dt_cols
                ]
                check_sql = f"SELECT count(*) FROM {quoted_name} WHERE {' OR '.join(conds)}"
                bad_count = conn.execute(check_sql).fetchone()
                if bad_count and bad_count[0] > 0:
                    raise StoreError("Store contains datetime values outside year 1 to 9999 or non-finite timestamps.")

            with self._flagged(name):  # flagged from just before the COMMIT until the bump is done
                conn.execute("COMMIT")
                self._txn_open = False
                self._bump_version(name)
            return total_rows
        except BaseException as exc:
            self._txn_open = False
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            if table_created:
                try:
                    conn.execute(f"DROP TABLE IF EXISTS {quoted_name}")
                except Exception:
                    pass
            if cancel_event is not None and cancel_event.is_set():
                from analytics_studio.file_import import ImportCancelledError
                raise ImportCancelledError("Import canceled.") from exc
            if isinstance(exc, (StoreError, KeyboardInterrupt)):
                raise
            # ImportCancelledError and FileImportError should propagate directly
            from analytics_studio.file_import import FileImportError, ImportCancelledError
            if isinstance(exc, (FileImportError, ImportCancelledError)):
                raise
            raise StoreError(f"Failed to create table '{name}' from Arrow batches: {exc}") from exc

