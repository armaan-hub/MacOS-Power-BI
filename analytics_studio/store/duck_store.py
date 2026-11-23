"""DuckDB-backed table row store."""

import datetime
import decimal
import fcntl
import os
from typing import Any, Iterable, List, Optional, Sequence, Tuple

import duckdb

try:
    import pyarrow as pa
except ImportError:
    pa = None

from .base import COLUMN_TYPES, Store, StoreError, StoreLockedError

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
    "TIMESTAMP WITH TIME ZONE": "datetime",
    "VARCHAR": "text",
    "BOOLEAN": "boolean",
}


def _quote_identifier(ident: str) -> str:
    """Quote SQL identifier using double quotes, doubling embedded quotes."""
    return '"' + ident.replace('"', '""') + '"'


def _coerce_value(val: Any, type_name: str) -> Any:
    if val is None:
        return None
    if type_name == "whole":
        return int(val)
    elif type_name == "decimal":
        return float(val)
    elif type_name == "fixed":
        if isinstance(val, decimal.Decimal):
            return val
        return decimal.Decimal(str(val))
    elif type_name == "datetime":
        if isinstance(val, datetime.datetime):
            return val
        if isinstance(val, datetime.date):
            return datetime.datetime(val.year, val.month, val.day)
        return datetime.datetime.fromisoformat(str(val))
    elif type_name == "text":
        return str(val)
    elif type_name == "boolean":
        return bool(val)
    return val


class DuckStore:
    """DuckDB implementation of Store interface."""

    def __init__(self, path: str, memory_limit: str = "2GB", threads: Optional[int] = None) -> None:
        self.path = os.path.abspath(path)
        self.lock_path = self.path + ".lock"
        self._lock_fd: Optional[int] = None
        self._conn: Optional[duckdb.DuckDBPyConnection] = None

        os.makedirs(os.path.dirname(self.path), exist_ok=True)

        self._acquire_lock()
        self._init_conn(memory_limit=memory_limit, threads=threads)

    def _acquire_lock(self) -> None:
        try:
            self._lock_fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o666)
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            if self._lock_fd is not None:
                try:
                    os.close(self._lock_fd)
                except OSError:
                    pass
                self._lock_fd = None
            raise StoreLockedError(
                f"Store at '{self.path}' is already locked by another process or instance."
            ) from exc

    def _init_conn(self, memory_limit: str = "2GB", threads: Optional[int] = None) -> None:
        config: dict[str, Any] = {
            "memory_limit": memory_limit,
            "temp_directory": os.path.dirname(self.path),
        }
        if threads is not None:
            config["threads"] = threads

        try:
            self._conn = duckdb.connect(self.path, config=config)
        except Exception:
            self.close()
            raise

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

    def __enter__(self) -> "DuckStore":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def _check_open(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            raise StoreError("Store is closed.")
        return self._conn

    def create_table(self, name: str, columns: Sequence[Tuple[str, str]]) -> None:
        conn = self._check_open()

        if self.has_table(name):
            raise StoreError(f"Table '{name}' already exists.")

        seen_cols: set[str] = set()
        col_defs: list[str] = []

        for col_name, type_name in columns:
            if not isinstance(col_name, str) or not col_name:
                raise StoreError(f"Invalid column name: {col_name!r}")
            if col_name == "__rn":
                raise StoreError("Column name '__rn' is reserved for hidden row index.")
            if col_name in seen_cols:
                raise StoreError(f"Duplicate column name: '{col_name}'")
            seen_cols.add(col_name)

            if type_name not in _TYPE_MAP:
                raise StoreError(
                    f"Unknown column type '{type_name}'. Must be one of {COLUMN_TYPES}."
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
        rows = conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = ?",
            [name],
        ).fetchall()
        return len(rows) > 0

    def table_names(self) -> List[str]:
        conn = self._check_open()
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() ORDER BY table_name"
        ).fetchall()
        return [r[0] for r in rows]

    def columns(self, name: str) -> List[Tuple[str, str]]:
        conn = self._check_open()
        if not self.has_table(name):
            raise StoreError(f"Table '{name}' does not exist.")

        rows = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ? "
            "ORDER BY ordinal_position",
            [name],
        ).fetchall()

        result: list[Tuple[str, str]] = []
        for col_name, data_type in rows:
            if col_name == "__rn":
                continue
            dt_upper = data_type.upper()
            logical_type = _REVERSE_TYPE_MAP.get(dt_upper)
            if logical_type is None:
                if "DECIMAL" in dt_upper:
                    logical_type = "fixed"
                elif "INT" in dt_upper:
                    logical_type = "whole"
                elif "DOUBLE" in dt_upper or "FLOAT" in dt_upper:
                    logical_type = "decimal"
                elif "TIMESTAMP" in dt_upper:
                    logical_type = "datetime"
                elif "BOOL" in dt_upper:
                    logical_type = "boolean"
                else:
                    logical_type = "text"
            result.append((col_name, logical_type))
        return result

    def row_count(self, name: str) -> int:
        conn = self._check_open()
        if not self.has_table(name):
            raise StoreError(f"Table '{name}' does not exist.")
        quoted_name = _quote_identifier(name)
        row = conn.execute(f"SELECT COUNT(*) FROM {quoted_name}").fetchone()
        return row[0] if row else 0

    def drop_table(self, name: str) -> None:
        conn = self._check_open()
        if not self.has_table(name):
            raise StoreError(f"Table '{name}' does not exist.")
        quoted_name = _quote_identifier(name)
        try:
            conn.execute(f"DROP TABLE {quoted_name}")
        except Exception as exc:
            raise StoreError(f"Failed to drop table '{name}': {exc}") from exc

    def append_rows(self, name: str, rows: Iterable[Sequence[Any]]) -> int:
        conn = self._check_open()
        if not self.has_table(name):
            raise StoreError(f"Table '{name}' does not exist.")

        col_info = self.columns(name)
        expected_cols = len(col_info)
        current_rn = self.row_count(name)
        quoted_tbl = _quote_identifier(name)

        pa_schema = None
        if pa is not None:
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
                    pa_fields.append((c_name, pa.string()))
            pa_fields.append(("__rn", pa.int64()))
            pa_schema = pa.schema(pa_fields)

        batch_size = 50_000
        current_batch: list[Tuple[Any, ...]] = []
        total_appended = 0

        conn.execute("BEGIN TRANSACTION")
        try:
            for row in rows:
                if len(row) != expected_cols:
                    raise StoreError(
                        f"Row has {len(row)} values, but table '{name}' expects {expected_cols}."
                    )
                current_batch.append(tuple(row))
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
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise

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

        if pa is not None and pa_schema is not None:
            try:
                cols_dict: dict[str, list[Any]] = {}
                for idx, (c_name, t_name) in enumerate(col_info):
                    cols_dict[c_name] = [
                        _coerce_value(row[idx], t_name) for row in batch
                    ]
                cols_dict["__rn"] = list(range(start_rn, start_rn + batch_len))
                batch_table = pa.Table.from_pydict(cols_dict, schema=pa_schema)
                conn.execute(f"INSERT INTO {quoted_tbl} SELECT * FROM batch_table")
                return
            except Exception:
                # If PyArrow path fails, fall back to executemany
                pass

        num_cols = len(col_info) + 1  # includes __rn
        placeholders = ", ".join(["?"] * num_cols)
        insert_sql = f"INSERT INTO {quoted_tbl} VALUES ({placeholders})"
        rows_with_rn = [
            tuple(r) + (start_rn + offset,) for offset, r in enumerate(batch)
        ]
        conn.executemany(insert_sql, rows_with_rn)

    def read_page(
        self,
        name: str,
        offset: int,
        limit: int,
        columns: Optional[Sequence[str]] = None,
    ) -> List[Tuple[Any, ...]]:
        conn = self._check_open()
        if not self.has_table(name):
            raise StoreError(f"Table '{name}' does not exist.")

        if columns is None:
            available_cols = [c[0] for c in self.columns(name)]
            selected = ", ".join(_quote_identifier(c) for c in available_cols)
        else:
            if not columns:
                return []
            existing = {c[0] for c in self.columns(name)}
            for c in columns:
                if c not in existing:
                    raise StoreError(f"Column '{c}' does not exist in table '{name}'.")
            selected = ", ".join(_quote_identifier(c) for c in columns)

        quoted_tbl = _quote_identifier(name)
        sql = (
            f"SELECT {selected} FROM {quoted_tbl} "
            f"ORDER BY \"__rn\" ASC LIMIT ? OFFSET ?"
        )
        return conn.execute(sql, [limit, offset]).fetchall()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> List[Tuple[Any, ...]]:
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
