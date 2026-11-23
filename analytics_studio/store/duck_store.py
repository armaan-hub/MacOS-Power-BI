"""DuckDB-backed table row store."""

import datetime
import decimal
import fcntl
import math
import os
from collections.abc import Sequence as _AbcSequence
from typing import Any, Iterable, List, Optional, Sequence, Tuple

import duckdb
import pyarrow as pa

from .base import COLUMN_TYPES, StoreError, StoreLockedError

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


class DuckStore:
    """DuckDB implementation of Store interface.

    Notes on locking:
    An exclusive advisory lock is held via fcntl.flock on '<path>.lock'.
    A stale '.lock' file is left behind on disk on purpose; the lock is held on the
    open file descriptor and automatically released when the file is closed or the process terminates.

    threads parameter is optional; None preserves DuckDB's default thread count.
    """

    def __init__(self, path: str, memory_limit: str = "2GB", threads: Optional[int] = None) -> None:
        if not isinstance(path, str) or not path.strip():
            raise StoreError("Store path must be a non-empty string.")

        real_target = os.path.realpath(path)
        self.path = real_target
        self.lock_path = real_target + ".lock"
        self._lock_fd: Optional[int] = None
        self._conn: Optional[duckdb.DuckDBPyConnection] = None

        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        except OSError as exc:
            raise StoreError(f"Failed to create directory for store '{self.path}': {exc}") from exc

        self._acquire_lock()
        self._init_conn(memory_limit=memory_limit, threads=threads)

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

    def _init_conn(self, memory_limit: str = "2GB", threads: Optional[int] = None) -> None:
        config: dict[str, Any] = {
            "enable_external_access": False,
            "memory_limit": memory_limit,
            "temp_directory": os.path.dirname(self.path),
        }
        if threads is not None:
            config["threads"] = threads

        try:
            self._conn = duckdb.connect(self.path, config=config)
        except Exception as exc:
            self.close()
            raise StoreError(f"Failed to open DuckDB store at '{self.path}': {exc}") from exc

    def close(self) -> None:
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

    def _check_open(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            raise StoreError("Store is closed.")
        return self._conn

    def _get_raw_tables(self, conn: duckdb.DuckDBPyConnection) -> List[str]:
        try:
            rows = conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() ORDER BY table_name"
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
        try:
            conn.execute(create_sql)
        except Exception as exc:
            raise StoreError(f"Failed to create table '{name}': {exc}") from exc

    def has_table(self, name: str) -> bool:
        conn = self._check_open()
        if not isinstance(name, str) or not name:
            return False
        all_tables = self._get_raw_tables(conn)
        target_lower = _ascii_lower(name)
        return any(_ascii_lower(t) == target_lower for t in all_tables)

    def table_names(self) -> List[str]:
        conn = self._check_open()
        return self._get_raw_tables(conn)

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

    def row_count(self, name: str) -> int:
        conn = self._check_open()
        resolved_name = self._resolve_table_name(name, conn)
        quoted_name = _quote_identifier(resolved_name)
        try:
            row = conn.execute(f"SELECT COUNT(*) FROM {quoted_name}").fetchone()
            return row[0] if row else 0
        except Exception as exc:
            raise StoreError(f"Failed to get row count for '{resolved_name}': {exc}") from exc

    def drop_table(self, name: str) -> None:
        conn = self._check_open()
        resolved_name = self._resolve_table_name(name, conn)
        quoted_name = _quote_identifier(resolved_name)
        try:
            conn.execute(f"DROP TABLE {quoted_name}")
        except Exception as exc:
            raise StoreError(f"Failed to drop table '{resolved_name}': {exc}") from exc

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

            conn.execute("COMMIT")
        except BaseException as exc:
            # BaseException on purpose: an interrupt must not leave the transaction open.
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            if isinstance(exc, StoreError) or not isinstance(exc, Exception):
                raise
            raise StoreError(
                f"Failed to append rows to '{resolved_name}' at row {overall_row_idx}: {exc}"
            ) from exc

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
            f"ORDER BY \"__rn\" ASC LIMIT ? OFFSET ?"
        )
        try:
            return conn.execute(sql, [limit, offset]).fetchall()
        except Exception as exc:
            raise StoreError(f"Failed to read page from '{resolved_name}': {exc}") from exc

    def execute(self, sql: str, params: Sequence[Any] = ()) -> List[Tuple[Any, ...]]:
        """Run a single read query (SELECT only) and return list of tuples.

        Note: When running 'SELECT *', the returned tuples will also include the hidden
        '__rn' column as the last element.

        Only SQL generated by the engine may be passed in; user-typed SQL must never reach it,
        because files inside the store's own folder stay readable through DuckDB's external-access rule.
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

        try:
            return conn.execute(sql, params).fetchall()
        except Exception as exc:
            raise StoreError(f"Query execution failed: {exc}") from exc

    def create_table_from_arrow(
        self,
        name: str,
        columns: Sequence[Tuple[str, str]],
        batches: Iterable[pa.RecordBatch],
        *,
        cancel_event: Optional[Any] = None,
        progress: Optional[Any] = None,
        max_rows: Optional[int] = None,
    ) -> int:
        """Create a table with text columns and stream Arrow record batches in one transaction.

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

            if type_name != "text":
                raise StoreError(f"create_table_from_arrow requires 'text' columns, got {type_name!r}.")

            sql_type = _TYPE_MAP[type_name]
            col_names.append(col_name)
            col_defs.append(f"{_quote_identifier(col_name)} {sql_type}")

        col_defs.append('"__rn" BIGINT')
        quoted_name = _quote_identifier(name)
        create_sql = f"CREATE TABLE {quoted_name} ({', '.join(col_defs)})"

        table_created = False
        try:
            conn.execute("BEGIN TRANSACTION")
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
                for field in batch.schema:
                    if not (pa.types.is_string(field.type) or pa.types.is_large_string(field.type)):
                        raise StoreError(
                            f"Batch column '{field.name}' has non-string type {field.type}."
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
                if progress is not None:
                    progress(f"Imported {total_rows:,} CSV rows...")

            conn.execute("COMMIT")
            return total_rows
        except BaseException as exc:
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

    def add_column(self, name: str, column_name: str, type_name: str) -> None:
        """Add a new column to an existing table.

        Follows standard identifier validation, case policies, and type rules.
        """
        conn = self._check_open()
        resolved_name = self._resolve_table_name(name, conn)
        _validate_identifier(column_name, kind="Column name")

        col_ci = _ascii_lower(column_name)
        if col_ci == "__rn":
            raise StoreError("Column name '__rn' is reserved for hidden row index.")

        existing = self.columns(resolved_name)
        for existing_col, _ in existing:
            if _ascii_lower(existing_col) == col_ci:
                raise StoreError(f"Column '{column_name}' already exists in table '{resolved_name}'.")

        if not isinstance(type_name, str) or type_name not in _TYPE_MAP:
            raise StoreError(f"Unknown column type '{type_name}'. Must be one of {COLUMN_TYPES}.")

        sql_type = _TYPE_MAP[type_name]
        quoted_tbl = _quote_identifier(resolved_name)
        quoted_col = _quote_identifier(column_name)
        default_clause = "DEFAULT ''" if type_name == "text" else "DEFAULT NULL"
        alter_sql = f"ALTER TABLE {quoted_tbl} ADD COLUMN {quoted_col} {sql_type} {default_clause}"
        try:
            conn.execute(alter_sql)
        except Exception as exc:
            raise StoreError(f"Failed to add column '{column_name}' to table '{resolved_name}': {exc}") from exc

