"""DuckStore-backed table model for Data view grid preview.

Provides a 1:1 replacement for CsvTableModel that queries a DuckStore table
on demand while holding only the current page (up to PREVIEW_ROW_LIMIT = 500 rows)
in Python memory.
"""

from __future__ import annotations

import threading
import uuid
from copy import deepcopy
from datetime import date, datetime, time
from decimal import Decimal, DecimalException
from typing import Any

import pyarrow as pa
from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, Property, Signal, Slot, Qt

from analytics_studio.controller import (
    PREVIEW_ROW_LIMIT,
    _data_view_filter_value_label,
    _decode_report_filter_value,
    _disambiguate_data_view_filter_labels,
    _encode_data_view_filter_value,
    _parse_report_filter_value,
    cell_to_text,
    is_cell_error,
)
from analytics_studio.file_import import ImportCancelledError
from analytics_studio.store.duck_store import DuckStore, _quote_identifier

# Map DuckStore logical column types to application column types
_STORE_TO_APP_TYPE = {
    "whole": "whole_number",
    "decimal": "decimal_number",
    "fixed": "decimal_number",
    "datetime": "datetime",
    "text": "text",
    "boolean": "boolean",
}


def _escape_like(text: str) -> str:
    """Escape %, _, and \\ for SQL LIKE pattern."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class StoreTableModel(QAbstractTableModel):
    """Read-only table preview backed by DuckStore, showing one bounded 500-row page at a time."""

    pageChanged = Signal()
    dataReplaced = Signal()
    sortChanged = Signal()
    filterChanged = Signal()

    def __init__(self, store: DuckStore, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._store = store
        self._table_name = ""
        self._table_key = ""
        self._headers: list[str] = []
        self._column_types: dict[str, str] = {}
        self._store_columns: dict[str, str] = {}  # col_name -> store_type

        self._rows: list[dict[str, Any]] = []
        self._page_index = 0
        self._total_rows = 0
        self._filtered_rows = 0

        self._sort_by_table: dict[str, tuple[str, str]] = {}
        self._filters_by_table: dict[str, dict[str, dict[str, Any]]] = {}
        self._column_filters: dict[str, dict[str, Any]] = {}
        self._sort_column = ""
        self._sort_direction = ""

        self._active_view_name: str | None = None
        self._view_prefix = f"__stm_view_{uuid.uuid4().hex[:8]}__"
        self._view_counter = 0

    def __del__(self) -> None:
        try:
            self._cleanup_view()
        except Exception:
            pass

    def _cleanup_view(self) -> None:
        if self._active_view_name is not None:
            view_to_drop = self._active_view_name
            self._active_view_name = None
            try:
                self._store.drop_view(view_to_drop)
            except Exception:
                pass

    def replace_data(
        self,
        table_name: str,
        headers: list[str] | None = None,
        column_types: dict[str, str] | None = None,
        table_key: str | None = None,
        *,
        cancel_event: threading.Event | None = None,
    ) -> None:
        """Load data from store table."""
        if cancel_event is not None and cancel_event.is_set():
            raise ImportCancelledError("Operation canceled.")
        self.beginResetModel()
        self._cleanup_view()
        self._table_name = str(table_name or "")
        self._table_key = str(table_key or "")

        if self._table_name and self._store.has_table(self._table_name):
            col_info = self._store.columns(self._table_name)
            self._store_columns = {name: stype for name, stype in col_info}
            if headers is not None:
                self._headers = list(headers)
            else:
                self._headers = [name for name, _ in col_info]
            self._total_rows = self._store.row_count(self._table_name)
        else:
            self._store_columns = {}
            self._headers = list(headers or [])
            self._total_rows = 0

        # Derive column types with app type mapping
        self._column_types = {}
        for h in self._headers:
            stype = self._store_columns.get(h)
            if stype is not None:
                self._column_types[h] = _STORE_TO_APP_TYPE.get(stype, "text")
            else:
                self._column_types[h] = "text"
        if column_types:
            self._column_types.update(column_types)

        self._sort_column, self._sort_direction = self._sort_by_table.get(
            self._table_key, ("", "")
        )
        self._column_filters = deepcopy(
            self._filters_by_table.get(self._table_key, {})
        )
        self._column_filters = {
            column: rule
            for column, rule in self._column_filters.items()
            if column in self._headers
        }

        self._prune_stale_value_filter_keys(cancel_event=cancel_event)

        if self._table_key:
            self._filters_by_table[self._table_key] = deepcopy(self._column_filters)
        if self._sort_column not in self._headers:
            self._sort_column = ""
            self._sort_direction = ""
            self._sort_by_table.pop(self._table_key, None)

        self._page_index = 0
        self._materialize_state(cancel_event=cancel_event)
        self._load_page_rows()
        self.endResetModel()

        self.pageChanged.emit()
        self.sortChanged.emit()
        self.dataReplaced.emit()

    def _prune_stale_value_filter_keys(
        self, cancel_event: threading.Event | None = None
    ) -> None:
        if not self._table_name or not self._store.has_table(self._table_name):
            return
        for column, rule in list(self._column_filters.items()):
            if rule.get("operator") != "values":
                continue
            requested = {
                key for key in rule.get("keys", []) if isinstance(key, str)
            }
            if not requested:
                rule["keys"] = []
                if rule.get("all", True):
                    self._column_filters.pop(column, None)
                continue

            present: set[str] = set()
            # Fast check: run SELECT DISTINCT for the column
            quoted_col = _quote_identifier(column)
            quoted_tbl = _quote_identifier(self._table_name)
            try:
                dist_rows = self._store.execute(
                    f"SELECT DISTINCT {quoted_col} FROM {quoted_tbl}"
                )
                for (val,) in dist_rows:
                    if cancel_event is not None and cancel_event.is_set():
                        raise ImportCancelledError("Operation canceled.")
                    k = _encode_data_view_filter_value(val)
                    if k in requested:
                        present.add(k)
                        if present == requested:
                            break
            except Exception:
                # Fallback to streaming chunk scan
                offset = 0
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise ImportCancelledError("Operation canceled.")
                    chunk = self._store.read_page(
                        self._table_name, offset, 2_000, columns=[column]
                    )
                    if not chunk:
                        break
                    for (val,) in chunk:
                        k = _encode_data_view_filter_value(val)
                        if k in requested:
                            present.add(k)
                            if present == requested:
                                break
                    if present == requested:
                        break
                    offset += len(chunk)

            rule["keys"] = sorted(present)
            if rule.get("all", True) and not present:
                self._column_filters.pop(column, None)

    def _sort_key(self, value: Any, column: str) -> tuple[Any, ...]:
        if value is None:
            return (0, "")
        if is_cell_error(value):
            return (1, cell_to_text(value).casefold())
        column_type = self._column_types.get(column, "text")
        if isinstance(value, str):
            try:
                if column_type == "boolean":
                    lowered = value.strip().casefold()
                    if lowered in {"true", "false"}:
                        value = lowered == "true"
                else:
                    value = _parse_report_filter_value(value, column_type)
            except (ValueError, DecimalException):
                pass
        if isinstance(value, bool):
            return (2, int(value))
        if isinstance(value, (int, float, Decimal)):
            try:
                number = Decimal(str(value))
            except DecimalException:
                return (3, 1, cell_to_text(value).casefold())
            if not number.is_finite():
                return (3, 1, str(number).casefold())
            return (3, 0, number)
        if isinstance(value, datetime):
            return (4, value.isoformat())
        if isinstance(value, (date, time)):
            return (4, value.isoformat())
        if isinstance(value, str):
            return (5, value.casefold())
        return (6, cell_to_text(value).casefold())

    def _matches_column_filter(
        self, raw_value: Any, column: str, rule: dict[str, Any]
    ) -> bool:
        operator = rule["operator"]
        if operator == "values":
            keys = set(rule.get("keys", []))
            key = _encode_data_view_filter_value(raw_value)
            return key not in keys if rule.get("all", True) else key in keys
        expected = rule["value"]
        if operator == "is_null":
            return raw_value is None
        if operator == "is_not_null":
            return raw_value is not None
        if operator == "is_blank":
            return raw_value is None or raw_value == ""
        if operator == "is_not_blank":
            return raw_value is not None and raw_value != ""
        actual_text = "(null)" if raw_value is None else cell_to_text(raw_value)
        if operator in {"equals", "not_equals"}:
            column_type = self._column_types.get(column, "text")
            if column_type in {
                "whole_number", "decimal_number", "fixed_decimal", "currency",
                "percentage", "date", "datetime", "time", "boolean",
            }:
                matched = self._sort_key(raw_value, column) == self._sort_key(
                    expected, column
                )
            else:
                matched = actual_text.casefold() == expected.casefold()
            return matched if operator == "equals" else not matched
        actual = actual_text.casefold()
        needle = expected.casefold()
        if operator == "contains":
            return needle in actual
        if operator == "does_not_contain":
            return needle not in actual
        if operator == "begins_with":
            return actual.startswith(needle)
        if operator == "does_not_begin_with":
            return not actual.startswith(needle)
        if operator == "ends_with":
            return actual.endswith(needle)
        if operator == "does_not_end_with":
            return not actual.endswith(needle)
        if raw_value is None or is_cell_error(raw_value):
            return False
        actual_key = self._sort_key(raw_value, column)
        expected_key = self._sort_key(expected, column)
        if operator == "greater_than":
            return actual_key > expected_key
        if operator == "greater_than_or_equal":
            return actual_key >= expected_key
        if operator == "less_than":
            return actual_key < expected_key
        if operator == "less_than_or_equal":
            return actual_key <= expected_key
        return True

    def _build_filter_sql_clause(
        self, column: str, rule: dict[str, Any]
    ) -> tuple[str | None, list[Any]]:
        """Try to translate a filter rule into SQL.

        Returns (sql_condition, params) or (None, []) if Python evaluation is required.
        """
        operator = rule["operator"]
        col_type = self._column_types.get(column, "text")
        quoted_col = _quote_identifier(column)

        if operator == "is_null":
            return f"{quoted_col} IS NULL", []
        if operator == "is_not_null":
            return f"{quoted_col} IS NOT NULL", []
        if operator == "is_blank":
            if col_type == "text":
                return f"({quoted_col} IS NULL OR {quoted_col} = '')", []
            return f"{quoted_col} IS NULL", []
        if operator == "is_not_blank":
            if col_type == "text":
                return f"({quoted_col} IS NOT NULL AND {quoted_col} != '')", []
            return f"{quoted_col} IS NOT NULL", []

        if operator == "values":
            keys = rule.get("keys", [])
            all_selected = rule.get("all", True)
            if not keys:
                return ("1=1" if all_selected else "1=0"), []

            # Check if any key is an error key or cannot be parsed
            val_items: list[Any] = []
            has_null = False
            for k in keys:
                decoded = _decode_report_filter_value(k)
                if decoded is None:
                    return None, []
                tag, val = decoded
                if tag == "null":
                    has_null = True
                elif tag == "typed":
                    t_kind, _t_canon, t_label = val
                    if t_kind == "number":
                        try:
                            val_items.append(Decimal(t_label))
                        except Exception:
                            return None, []
                    elif t_kind == "boolean":
                        val_items.append(t_label.lower() == "true")
                    elif t_kind == "text":
                        if not t_label.isascii():
                            return None, []
                        val_items.append(t_label)
                    else:
                        return None, []
                else:
                    return None, []

            params: list[Any] = []

            if col_type == "text":
                eq_conds: list[str] = []
                for v in val_items:
                    eq_conds.append(f"{quoted_col} = ? COLLATE NOCASE")
                    params.append(v)
                if has_null:
                    eq_conds.append(f"{quoted_col} IS NULL")
                if not eq_conds:
                    match_expr = "1=0"
                else:
                    match_expr = f"({' OR '.join(eq_conds)})"
            else:
                eq_conds = []
                if val_items:
                    placeholders = ", ".join("?" for _ in val_items)
                    eq_conds.append(f"{quoted_col} IN ({placeholders})")
                    params.extend(val_items)
                if has_null:
                    eq_conds.append(f"{quoted_col} IS NULL")
                if not eq_conds:
                    match_expr = "1=0"
                else:
                    match_expr = f"({' OR '.join(eq_conds)})"

            if all_selected:
                return f"NOT ({match_expr})", params
            return match_expr, params

        expected = rule.get("value", "")

        # String search operators
        if operator in {
            "contains", "does_not_contain", "begins_with", "does_not_begin_with",
            "ends_with", "does_not_end_with",
        }:
            # CsvTableModel evaluates text operators on cell_to_text(raw_value), where None -> "(null)"
            # Check ASCII safety
            if not expected.isascii():
                return None, []
            esc = _escape_like(expected)
            if operator == "contains":
                pat = f"%{esc}%"
                return (
                    f"(CASE WHEN {quoted_col} IS NULL THEN '(null)' ELSE {quoted_col}::VARCHAR END) "
                    f"LIKE ? ESCAPE '\\' COLLATE NOCASE",
                    [pat],
                )
            if operator == "does_not_contain":
                pat = f"%{esc}%"
                return (
                    f"NOT ((CASE WHEN {quoted_col} IS NULL THEN '(null)' ELSE {quoted_col}::VARCHAR END) "
                    f"LIKE ? ESCAPE '\\' COLLATE NOCASE)",
                    [pat],
                )
            if operator == "begins_with":
                pat = f"{esc}%"
                return (
                    f"(CASE WHEN {quoted_col} IS NULL THEN '(null)' ELSE {quoted_col}::VARCHAR END) "
                    f"LIKE ? ESCAPE '\\' COLLATE NOCASE",
                    [pat],
                )
            if operator == "does_not_begin_with":
                pat = f"{esc}%"
                return (
                    f"NOT ((CASE WHEN {quoted_col} IS NULL THEN '(null)' ELSE {quoted_col}::VARCHAR END) "
                    f"LIKE ? ESCAPE '\\' COLLATE NOCASE)",
                    [pat],
                )
            if operator == "ends_with":
                pat = f"%{esc}"
                return (
                    f"(CASE WHEN {quoted_col} IS NULL THEN '(null)' ELSE {quoted_col}::VARCHAR END) "
                    f"LIKE ? ESCAPE '\\' COLLATE NOCASE",
                    [pat],
                )
            if operator == "does_not_end_with":
                pat = f"%{esc}"
                return (
                    f"NOT ((CASE WHEN {quoted_col} IS NULL THEN '(null)' ELSE {quoted_col}::VARCHAR END) "
                    f"LIKE ? ESCAPE '\\' COLLATE NOCASE)",
                    [pat],
                )

        if operator in {"equals", "not_equals"}:
            if col_type in {
                "whole_number", "decimal_number", "fixed_decimal", "currency", "percentage"
            }:
                try:
                    exp_num = Decimal(expected)
                except Exception:
                    return None, []
                if operator == "equals":
                    return f"{quoted_col} IS NOT NULL AND {quoted_col} = ?", [exp_num]
                return f"{quoted_col} IS NULL OR {quoted_col} != ?", [exp_num]
            elif col_type == "boolean":
                lowered = expected.strip().casefold()
                if lowered in {"true", "false"}:
                    exp_bool = lowered == "true"
                    if operator == "equals":
                        return f"{quoted_col} IS NOT NULL AND {quoted_col} = ?", [exp_bool]
                    return f"{quoted_col} IS NULL OR {quoted_col} != ?", [exp_bool]
                return None, []
            elif col_type in {"date", "datetime"}:
                try:
                    _parse_report_filter_value(expected, col_type)
                except Exception:
                    return None, []
                if operator == "equals":
                    return f"{quoted_col} IS NOT NULL AND {quoted_col} = ?", [expected]
                return f"{quoted_col} IS NULL OR {quoted_col} != ?", [expected]
            else:
                # Text comparison (case-insensitive)
                if not expected.isascii():
                    return None, []
                # (null) text check
                if operator == "equals":
                    return (
                        f"(CASE WHEN {quoted_col} IS NULL THEN '(null)' ELSE {quoted_col} END) = ? COLLATE NOCASE",
                        [expected],
                    )
                return (
                    f"(CASE WHEN {quoted_col} IS NULL THEN '(null)' ELSE {quoted_col} END) != ? COLLATE NOCASE",
                    [expected],
                )

        if operator in {"greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"}:
            op_sym = {
                "greater_than": ">",
                "greater_than_or_equal": ">=",
                "less_than": "<",
                "less_than_or_equal": "<=",
            }[operator]
            if col_type in {
                "whole_number", "decimal_number", "fixed_decimal", "currency", "percentage"
            }:
                try:
                    exp_num = Decimal(expected)
                except Exception:
                    return None, []
                return f"{quoted_col} IS NOT NULL AND {quoted_col} {op_sym} ?", [exp_num]
            elif col_type in {"date", "datetime"}:
                try:
                    _parse_report_filter_value(expected, col_type)
                except Exception:
                    return None, []
                return f"{quoted_col} IS NOT NULL AND {quoted_col} {op_sym} ?", [expected]
            elif col_type == "boolean":
                lowered = expected.strip().casefold()
                if lowered in {"true", "false"}:
                    exp_bool = lowered == "true"
                    return f"{quoted_col} IS NOT NULL AND {quoted_col} {op_sym} ?", [exp_bool]
                return None, []
            elif col_type == "text":
                if not expected.isascii():
                    return None, []
                return (
                    f"{quoted_col} IS NOT NULL AND {quoted_col} {op_sym} ? COLLATE NOCASE",
                    [expected],
                )

        return None, []

    def _build_sort_sql_clause(self) -> str | None:
        """Return SQL ORDER BY expression for current sort column or None if Python sort needed."""
        if not self._sort_column or self._sort_column not in self._headers:
            return '"__rn" ASC'
        col = self._sort_column
        col_type = self._column_types.get(col, "text")
        quoted_col = _quote_identifier(col)
        direction = "DESC" if self._sort_direction == "descending" else "ASC"

        # Check if non-ASCII text might need German eszett casefold order
        if col_type == "text":
            quoted_tbl = _quote_identifier(self._table_name)
            try:
                check_rows = self._store.execute(
                    f"SELECT 1 FROM {quoted_tbl} WHERE {quoted_col} IS NOT NULL AND NOT ({quoted_col} ~ '^[[:ascii:]]*$') LIMIT 1"
                )
                if check_rows:
                    return None
            except Exception:
                return None

        if direction == "ASC":
            null_clause = "NULLS FIRST"
        else:
            null_clause = "NULLS LAST"

        if col_type == "text":
            return f"{quoted_col} COLLATE NOCASE {direction} {null_clause}, \"__rn\" ASC"
        return f"{quoted_col} {direction} {null_clause}, \"__rn\" ASC"

    def _materialize_state(self, cancel_event: threading.Event | None = None) -> None:
        """Materialize sorted and filtered row IDs into a temporary table if needed."""
        self._cleanup_view()
        if not self._table_name or not self._store.has_table(self._table_name) or self._total_rows == 0:
            self._filtered_rows = 0
            return

        has_filters = bool(self._column_filters)
        has_sort = bool(self._sort_column and self._sort_column in self._headers)

        if not has_filters and not has_sort:
            self._filtered_rows = self._total_rows
            return

        # Attempt SQL translation of all active filters
        can_sql_filter = True
        where_clauses: list[str] = []
        where_params: list[Any] = []

        for col, rule in self._column_filters.items():
            clause, params = self._build_filter_sql_clause(col, rule)
            if clause is None:
                can_sql_filter = False
                break
            where_clauses.append(clause)
            where_params.extend(params)

        sort_clause = self._build_sort_sql_clause() if can_sql_filter else None

        if can_sql_filter and sort_clause is not None:
            # Full SQL path
            self._view_counter += 1
            view_name = f"{self._view_prefix}{self._view_counter}"
            quoted_tbl = _quote_identifier(self._table_name)
            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            select_sql = f"SELECT \"__rn\" FROM {quoted_tbl} {where_sql} ORDER BY {sort_clause}"

            if cancel_event is not None and cancel_event.is_set():
                raise ImportCancelledError("Operation canceled.")

            self._store.create_view_ids(view_name, select_sql, where_params)
            self._active_view_name = view_name
            quoted_view = _quote_identifier(view_name)
            cnt_row = self._store.execute(f"SELECT count(*) FROM {quoted_view}")
            self._filtered_rows = cnt_row[0][0] if cnt_row else 0
            return

        # Fallback to streaming Python evaluation in chunks
        self._materialize_state_python(cancel_event=cancel_event)

    def _materialize_state_python(
        self, cancel_event: threading.Event | None = None
    ) -> None:
        """Stream table in chunks, apply filters and sort in Python, then create temp table."""
        needed_cols: set[str] = set()
        if self._sort_column and self._sort_column in self._headers:
            needed_cols.add(self._sort_column)
        for col in self._column_filters:
            needed_cols.add(col)

        col_list = list(needed_cols)
        quoted_tbl = _quote_identifier(self._table_name)
        select_cols = [
            f"{_quote_identifier(c)} AS {_quote_identifier(c)}" for c in col_list
        ] + ['"__rn"']
        select_sql = f"SELECT {', '.join(select_cols)} FROM {quoted_tbl} ORDER BY \"__rn\" ASC"

        # Stream rows
        matching_rows: list[tuple[Any, ...]] = []
        chunk_size = 50_000
        offset = 0

        while True:
            if cancel_event is not None and cancel_event.is_set():
                self._cleanup_view()
                raise ImportCancelledError("Operation canceled.")
            chunk_sql = f"{select_sql} LIMIT {chunk_size} OFFSET {offset}"
            chunk = self._store.execute(chunk_sql)
            if not chunk:
                break

            for r in chunk:
                rn = r[-1]
                row_dict = {col_list[i]: r[i] for i in range(len(col_list))}
                # Check filters
                matches = True
                for col, rule in self._column_filters.items():
                    if not self._matches_column_filter(row_dict.get(col), col, rule):
                        matches = False
                        break
                if matches:
                    if self._sort_column and self._sort_column in self._headers:
                        key = self._sort_key(
                            row_dict.get(self._sort_column), self._sort_column
                        )
                    else:
                        key = ()
                    matching_rows.append((key, rn))

            offset += len(chunk)
            if len(chunk) < chunk_size:
                break

        if cancel_event is not None and cancel_event.is_set():
            self._cleanup_view()
            raise ImportCancelledError("Operation canceled.")

        # Sort if needed
        if self._sort_column and self._sort_column in self._headers:
            reverse = self._sort_direction == "descending"
            # Stable sort keeping original __rn order on ties
            if reverse:
                matching_rows.sort(key=lambda item: item[0], reverse=True)
            else:
                matching_rows.sort(key=lambda item: item[0])

        filtered_rns = [item[1] for item in matching_rows]
        self._filtered_rows = len(filtered_rns)

        # Create temp table with IDs
        self._view_counter += 1
        view_name = f"{self._view_prefix}{self._view_counter}"
        rn_array = pa.array(filtered_rns, type=pa.int64())
        pos_array = pa.array(range(len(filtered_rns)), type=pa.int64())
        pa_table = pa.Table.from_arrays(
            [rn_array, pos_array], names=["__rn", "position"]
        )

        batch_name = f"__stm_batch_{uuid.uuid4().hex[:8]}__"
        conn = self._store._check_open()
        conn.register(batch_name, pa_table)
        quoted_view = _quote_identifier(view_name)
        try:
            conn.execute(
                f"CREATE TEMP TABLE {quoted_view} AS SELECT * FROM {batch_name}"
            )
            self._active_view_name = view_name
        finally:
            try:
                conn.unregister(batch_name)
            except Exception:
                pass

    def _load_page_rows(self) -> None:
        """Fetch rows for current page index into self._rows."""
        if not self._table_name or not self._store.has_table(self._table_name) or self._filtered_rows == 0:
            self._rows = []
            return

        start = self._page_index * PREVIEW_ROW_LIMIT
        limit = PREVIEW_ROW_LIMIT

        quoted_tbl = _quote_identifier(self._table_name)
        select_cols = ", ".join(_quote_identifier(h) for h in self._headers)

        if self._active_view_name is not None:
            quoted_view = _quote_identifier(self._active_view_name)
            sql = (
                f"SELECT {select_cols} FROM {quoted_tbl} AS t "
                f"JOIN {quoted_view} AS v ON t.\"__rn\" = v.\"__rn\" "
                f"ORDER BY v.position ASC LIMIT ? OFFSET ?"
            )
            tuples = self._store.execute(sql, [limit, start])
        else:
            tuples = self._store.read_page(
                self._table_name, start, limit, columns=self._headers
            )

        self._rows = [
            dict(zip(self._headers, row_tuple)) for row_tuple in tuples
        ]

    def _set_page(self, page_index: int) -> None:
        page_count = self.pageCount
        next_index = max(0, min(page_index, max(0, page_count - 1)))
        if next_index == self._page_index:
            return
        self.beginResetModel()
        self._page_index = next_index
        self._load_page_rows()
        self.endResetModel()
        self.pageChanged.emit()

    @Property(int, notify=pageChanged)
    def currentPage(self) -> int:  # noqa: N802
        return self._page_index + 1 if self.pageCount else 0

    @Property(int, notify=pageChanged)
    def pageCount(self) -> int:  # noqa: N802
        return (self._filtered_rows + PREVIEW_ROW_LIMIT - 1) // PREVIEW_ROW_LIMIT

    @Property(str, notify=pageChanged)
    def pageRange(self) -> str:  # noqa: N802
        if not self._filtered_rows:
            return "No rows"
        first_row = self._page_index * PREVIEW_ROW_LIMIT + 1
        last_row = min(first_row + len(self._rows) - 1, self._filtered_rows)
        return f"Rows {first_row:,}–{last_row:,} of {self._filtered_rows:,}"

    @Property(bool, notify=pageChanged)
    def canGoPrevious(self) -> bool:  # noqa: N802
        return self._page_index > 0

    @Property(bool, notify=pageChanged)
    def canGoNext(self) -> bool:  # noqa: N802
        return self._page_index + 1 < self.pageCount

    @Slot()
    def previousPage(self) -> None:  # noqa: N802
        if self.canGoPrevious:
            self._set_page(self._page_index - 1)

    @Slot()
    def nextPage(self) -> None:  # noqa: N802
        if self.canGoNext:
            self._set_page(self._page_index + 1)

    @Property(str, notify=sortChanged)
    def sortColumn(self) -> str:  # noqa: N802
        return self._sort_column

    @Property(str, notify=sortChanged)
    def sortDirection(self) -> str:  # noqa: N802
        return self._sort_direction

    @Slot(int)
    def sortByColumn(self, column_index: int) -> None:  # noqa: N802
        if column_index < 0 or column_index >= len(self._headers):
            return
        column = self._headers[column_index]
        if column == self._sort_column:
            direction = "descending" if self._sort_direction == "ascending" else "ascending"
        else:
            direction = "ascending"
        self.beginResetModel()
        self._sort_column = column
        self._sort_direction = direction
        if self._table_key:
            self._sort_by_table[self._table_key] = (column, direction)
        self._materialize_state()
        self._page_index = 0
        self._load_page_rows()
        self.endResetModel()
        self.pageChanged.emit()
        self.sortChanged.emit()

    @Property("QVariantList", notify=filterChanged)
    def activeFilterColumns(self) -> list[str]:  # noqa: N802
        return list(self._column_filters)

    @Slot(str, result=bool)
    def isColumnFiltered(self, column: str) -> bool:  # noqa: N802
        return column in self._column_filters

    @Slot(str, result="QVariantMap")
    def columnFilter(self, column: str) -> dict[str, Any]:  # noqa: N802
        return deepcopy(self._column_filters.get(column, {}))

    @Slot(str, str, result="QVariantMap")
    def columnFilterValues(self, column: str, search: str) -> dict[str, Any]:  # noqa: N802
        """Search distinct filter values in the domain after other-column filters."""
        if column not in self._headers or not self._table_name or not self._store.has_table(self._table_name):
            return {
                "values": [], "matchCount": 0, "totalCount": 0, "truncated": False
            }

        # Check if other filters exist
        other_filters = {
            c: r for c, r in self._column_filters.items() if c != column
        }

        # If no other filters, fast SELECT DISTINCT
        if not other_filters:
            quoted_col = _quote_identifier(column)
            quoted_tbl = _quote_identifier(self._table_name)
            try:
                dist_rows = self._store.execute(
                    f"SELECT DISTINCT {quoted_col} FROM {quoted_tbl}"
                )
                distinct: dict[str, str] = {}
                for (raw_value,) in dist_rows:
                    key = _encode_data_view_filter_value(raw_value)
                    distinct[key] = _data_view_filter_value_label(raw_value, key)
                labels = _disambiguate_data_view_filter_labels(distinct)
                query = (search or "").strip().casefold()
                matched = [
                    (key, label) for key, label in labels.items()
                    if not query or query in label.casefold()
                ]
                matched.sort(key=lambda item: (item[1].casefold(), item[1], item[0]))
                return {
                    "values": [
                        {"key": key, "label": label}
                        for key, label in matched[:2_000]
                    ],
                    "matchCount": len(matched),
                    "totalCount": len(distinct),
                    "truncated": len(matched) > 2_000,
                }
            except Exception:
                pass

        # If other filters exist, check if they can be translated to SQL
        can_sql = True
        where_clauses: list[str] = []
        where_params: list[Any] = []
        for c, rule in other_filters.items():
            clause, params = self._build_filter_sql_clause(c, rule)
            if clause is None:
                can_sql = False
                break
            where_clauses.append(clause)
            where_params.extend(params)

        if can_sql:
            quoted_col = _quote_identifier(column)
            quoted_tbl = _quote_identifier(self._table_name)
            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            sql = f"SELECT DISTINCT {quoted_col} FROM {quoted_tbl} {where_sql}"
            try:
                dist_rows = self._store.execute(sql, where_params)
                distinct = {}
                for (raw_value,) in dist_rows:
                    key = _encode_data_view_filter_value(raw_value)
                    distinct[key] = _data_view_filter_value_label(raw_value, key)
                labels = _disambiguate_data_view_filter_labels(distinct)
                query = (search or "").strip().casefold()
                matched = [
                    (key, label) for key, label in labels.items()
                    if not query or query in label.casefold()
                ]
                matched.sort(key=lambda item: (item[1].casefold(), item[1], item[0]))
                return {
                    "values": [
                        {"key": key, "label": label}
                        for key, label in matched[:2_000]
                    ],
                    "matchCount": len(matched),
                    "totalCount": len(distinct),
                    "truncated": len(matched) > 2_000,
                }
            except Exception:
                pass

        # Fallback to chunk scan
        distinct = {}
        offset = 0
        cols_needed = list(other_filters.keys()) + ([column] if column not in other_filters else [])
        while True:
            chunk = self._store.read_page(
                self._table_name, offset, 50_000, columns=cols_needed
            )
            if not chunk:
                break
            for row_vals in chunk:
                row_dict = dict(zip(cols_needed, row_vals))
                matches = True
                for c, rule in other_filters.items():
                    if not self._matches_column_filter(row_dict.get(c), c, rule):
                        matches = False
                        break
                if matches:
                    raw_value = row_dict.get(column)
                    key = _encode_data_view_filter_value(raw_value)
                    if key not in distinct:
                        distinct[key] = _data_view_filter_value_label(raw_value, key)
            offset += len(chunk)

        labels = _disambiguate_data_view_filter_labels(distinct)
        query = (search or "").strip().casefold()
        matched = [
            (key, label) for key, label in labels.items()
            if not query or query in label.casefold()
        ]
        matched.sort(key=lambda item: (item[1].casefold(), item[1], item[0]))
        return {
            "values": [
                {"key": key, "label": label}
                for key, label in matched[:2_000]
            ],
            "matchCount": len(matched),
            "totalCount": len(distinct),
            "truncated": len(matched) > 2_000,
        }

    @Slot(str, str, str)
    def setColumnFilter(self, column: str, operator: str, value: str) -> None:  # noqa: N802
        supported = {
            "equals", "not_equals", "is_null", "is_not_null", "is_blank",
            "is_not_blank", "contains", "does_not_contain", "begins_with",
            "does_not_begin_with", "ends_with", "does_not_end_with",
            "greater_than", "greater_than_or_equal", "less_than",
            "less_than_or_equal",
        }
        if column not in self._headers or operator not in supported:
            return
        if len(value) > 2_000:
            return
        self.beginResetModel()
        self._column_filters[column] = {"operator": operator, "value": value}
        if self._table_key:
            self._filters_by_table[self._table_key] = deepcopy(self._column_filters)
        self._materialize_state()
        self._page_index = 0
        self._load_page_rows()
        self.endResetModel()
        self.pageChanged.emit()
        self.filterChanged.emit()

    @Slot(str, bool, "QVariantList")
    def setColumnValueFilter(
        self, column: str, all_selected: bool, keys: list[str]
    ) -> None:  # noqa: N802
        if (
            column not in self._headers
            or not isinstance(keys, list)
            or len(keys) > 100_000
            or any(not isinstance(key, str) for key in keys)
        ):
            return
        requested = set(keys)
        present: set[str] = set()
        if requested:
            quoted_col = _quote_identifier(column)
            quoted_tbl = _quote_identifier(self._table_name)
            try:
                dist_rows = self._store.execute(
                    f"SELECT DISTINCT {quoted_col} FROM {quoted_tbl}"
                )
                for (val,) in dist_rows:
                    k = _encode_data_view_filter_value(val)
                    if k in requested:
                        present.add(k)
                        if present == requested:
                            break
            except Exception:
                offset = 0
                while True:
                    chunk = self._store.read_page(
                        self._table_name, offset, 2_000, columns=[column]
                    )
                    if not chunk:
                        break
                    for (val,) in chunk:
                        k = _encode_data_view_filter_value(val)
                        if k in requested:
                            present.add(k)
                            if present == requested:
                                break
                    if present == requested:
                        break
                    offset += len(chunk)

        normalized = sorted(present)
        if all_selected and not normalized:
            self.clearColumnFilter(column)
            return
        self.beginResetModel()
        self._column_filters[column] = {
            "operator": "values",
            "all": bool(all_selected),
            "keys": normalized,
        }
        if self._table_key:
            self._filters_by_table[self._table_key] = deepcopy(self._column_filters)
        self._materialize_state()
        self._page_index = 0
        self._load_page_rows()
        self.endResetModel()
        self.pageChanged.emit()
        self.filterChanged.emit()

    @Slot(str)
    def clearColumnFilter(self, column: str) -> None:  # noqa: N802
        if column not in self._column_filters:
            return
        self.beginResetModel()
        self._column_filters.pop(column, None)
        if self._table_key:
            if self._column_filters:
                self._filters_by_table[self._table_key] = deepcopy(self._column_filters)
            else:
                self._filters_by_table.pop(self._table_key, None)
        self._materialize_state()
        self._page_index = 0
        self._load_page_rows()
        self.endResetModel()
        self.pageChanged.emit()
        self.filterChanged.emit()

    def clear(self) -> None:
        self._sort_by_table.clear()
        self._filters_by_table.clear()
        self.replace_data("")

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        if index.row() >= len(self._rows) or index.column() >= len(self._headers):
            return None
        value = self._rows[index.row()].get(self._headers[index.column()], "")
        return "(null)" if value is None else cell_to_text(value)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(self._headers):
            return self._headers[section]
        if orientation == Qt.Orientation.Vertical:
            return self._page_index * PREVIEW_ROW_LIMIT + section + 1
        return None

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802
        return {int(Qt.ItemDataRole.DisplayRole): b"display"}
