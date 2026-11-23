"""DuckStore-backed table model for Data view grid preview.

Provides a 1:1 replacement for CsvTableModel that queries a DuckStore table
on demand while holding only the current page (up to PREVIEW_ROW_LIMIT = 500 rows)
in Python memory.

Threading note:
StoreTableModel is designed for use on the Qt UI thread only. DuckStore uses a
single internal connection protected by a non-blocking reentrant threading lock.
When a background import or long-running store job holds the store lock, any store
call from StoreTableModel immediately raises StoreError("The store is busy with another operation.").
StoreTableModel catches StoreError internally, records it in lastError, emits the storeError(str)
signal, preserves all previous model state without breaking Qt beginResetModel/endResetModel
guarantees, and returns neutral/cached values.

Known differences from CsvTableModel:
- -inf ordering (B15): In DuckDB SQL, floating point `-inf` on typed decimal (DOUBLE) columns
  sorts before all finite numbers in ASC order (`-inf`, `0.0`, `1.0`, `inf`), matching IEEE-754
  and standard SQL semantics. In CsvTableModel, Python's `Decimal(str(value)).is_finite()` branch
  sorts `-inf` under group `(3, 1, '-inf')` after all finite numbers `(3, 0, number)`. Store whole
  columns cannot hold infinity; decimal columns can.
"""

from __future__ import annotations

import threading
import uuid
from copy import deepcopy
from datetime import date, datetime, time
from decimal import Decimal, DecimalException
from typing import Any

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
from analytics_studio.store.base import StoreError
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


def _norm_param(x: Any) -> Any:
    """Normalise Decimal parameters with exponents into exact string representations.
    
    Prevents Decimal('1E+2') from being bound incorrectly as 1.00.
    """
    if isinstance(x, Decimal):
        return format(x, "f")
    return x


def _escape_like(text: str) -> str:
    r"""Escape %, _, and \ for SQL LIKE pattern."""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class StoreTableModel(QAbstractTableModel):
    """Read-only table preview backed by DuckStore, showing one bounded 500-row page at a time."""

    pageChanged = Signal()
    dataReplaced = Signal()
    sortChanged = Signal()
    filterChanged = Signal()
    storeError = Signal(str)

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

        self._last_error: str = ""
        self._cancel_event: threading.Event | None = None

        # Caches for canonical column format and non-ascii checks: (table_name, col) -> bool
        self._canonical_cache: dict[tuple[str, str], bool] = {}
        self._non_ascii_cache: dict[tuple[str, str], bool] = {}

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

    @Property(str, notify=storeError)
    def lastError(self) -> str:  # noqa: N802
        return self._last_error

    @Property(QObject)
    def cancelEvent(self) -> Any:  # noqa: N802
        return self._cancel_event

    @cancelEvent.setter
    def cancelEvent(self, ev: Any) -> None:  # noqa: N802
        self._cancel_event = ev

    def _effective_cancel_event(
        self, cancel_event: threading.Event | None = None
    ) -> threading.Event | None:
        return cancel_event if cancel_event is not None else self._cancel_event

    def _handle_store_error(self, exc: Exception) -> None:
        err_msg = str(exc)
        self._last_error = err_msg
        self.storeError.emit(err_msg)

    def _check_canonical(self, column: str) -> bool:
        """Check if all non-blank values in a text-store column conform to canonical SQL format."""
        if not self._table_name or not self._store.has_table(self._table_name):
            return False
        cache_key = (self._table_name, column)
        if cache_key in self._canonical_cache:
            return self._canonical_cache[cache_key]

        app_type = self._column_types.get(column, "text")
        quoted_col = _quote_identifier(column)
        quoted_tbl = _quote_identifier(self._table_name)

        if app_type in {"whole_number", "decimal_number", "fixed_decimal", "currency", "percentage"}:
            sql = (
                f"SELECT bool_and({quoted_col} IS NULL OR {quoted_col} = '' OR "
                f"{quoted_col} ~ '^[+-]?[0-9]{{1,18}}(\\.[0-9]{{1,18}})?$') "
                f"FROM {quoted_tbl}"
            )
        elif app_type == "boolean":
            sql = (
                f"SELECT bool_and({quoted_col} IS NULL OR {quoted_col} = '' OR "
                f"{quoted_col} ~ '^(?i:true|false)$') "
                f"FROM {quoted_tbl}"
            )
        elif app_type == "date":
            sql = (
                f"SELECT bool_and({quoted_col} IS NULL OR {quoted_col} = '' OR "
                f"{quoted_col} ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$') "
                f"FROM {quoted_tbl}"
            )
        elif app_type == "datetime":
            sql = (
                f"SELECT bool_and({quoted_col} IS NULL OR {quoted_col} = '' OR "
                f"{quoted_col} ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}[T ][0-9]{{2}}:[0-9]{{2}}:[0-9]{{2}}(\\.[0-9]{{1,6}})?$') "
                f"FROM {quoted_tbl}"
            )
        else:
            self._canonical_cache[cache_key] = False
            return False

        try:
            res = self._store.execute(sql)
            is_canon = bool(res[0][0]) if res and res[0][0] is not None else True
        except Exception:
            is_canon = False
        self._canonical_cache[cache_key] = is_canon
        return is_canon

    def _check_non_ascii(self, column: str) -> bool:
        """Check if any text value in column contains non-ASCII characters."""
        if not self._table_name or not self._store.has_table(self._table_name):
            return False
        cache_key = (self._table_name, column)
        if cache_key in self._non_ascii_cache:
            return self._non_ascii_cache[cache_key]

        quoted_col = _quote_identifier(column)
        quoted_tbl = _quote_identifier(self._table_name)
        sql = (
            f"SELECT bool_or({quoted_col} IS NOT NULL AND NOT ({quoted_col} ~ '^[[:ascii:]]*$')) "
            f"FROM {quoted_tbl}"
        )
        try:
            res = self._store.execute(sql)
            has_non_ascii = bool(res[0][0]) if res and res[0][0] is not None else False
        except Exception:
            has_non_ascii = True
        self._non_ascii_cache[cache_key] = has_non_ascii
        return has_non_ascii

    def replace_data(
        self,
        table_name: str,
        headers: list[str] | None = None,
        column_types: dict[str, str] | None = None,
        table_key: str | None = None,
        *,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        """Load data from store table. Returns True on success, False on StoreError."""
        ev = self._effective_cancel_event(cancel_event)
        if ev is not None and ev.is_set():
            raise ImportCancelledError("Operation canceled.")

        # Invalidate caches
        self._canonical_cache.clear()
        self._non_ascii_cache.clear()

        # Compute new state before resetting model
        new_table_name = str(table_name or "")
        new_table_key = str(table_key or "")

        try:
            if new_table_name and self._store.has_table(new_table_name):
                col_info = self._store.columns(new_table_name)
                new_store_columns = {name: stype for name, stype in col_info}
                if headers is not None:
                    new_headers = list(headers)
                else:
                    new_headers = [name for name, _ in col_info]
                new_total_rows = self._store.row_count(new_table_name)
            else:
                new_store_columns = {}
                new_headers = list(headers or [])
                new_total_rows = 0

            # Derive column types with app type mapping
            new_col_types = {}
            for h in new_headers:
                stype = new_store_columns.get(h)
                if stype is not None:
                    new_col_types[h] = _STORE_TO_APP_TYPE.get(stype, "text")
                else:
                    new_col_types[h] = "text"
            if column_types:
                new_col_types.update(column_types)

            new_sort_col, new_sort_dir = self._sort_by_table.get(
                new_table_key, ("", "")
            )
            raw_filters = deepcopy(
                self._filters_by_table.get(new_table_key, {})
            )
            new_col_filters = {
                column: rule
                for column, rule in raw_filters.items()
                if column in new_headers
            }

            if new_sort_col not in new_headers:
                new_sort_col = ""
                new_sort_dir = ""
                self._sort_by_table.pop(new_table_key, None)

        except StoreError as exc:
            self._handle_store_error(exc)
            return False

        # Safely wrap Qt reset model
        self.beginResetModel()
        try:
            self._cleanup_view()
            self._table_name = new_table_name
            self._table_key = new_table_key
            self._headers = new_headers
            self._store_columns = new_store_columns
            self._total_rows = new_total_rows
            self._column_types = new_col_types
            self._sort_column = new_sort_col
            self._sort_direction = new_sort_dir
            self._column_filters = new_col_filters

            self._prune_stale_value_filter_keys(cancel_event=ev)

            if self._table_key:
                self._filters_by_table[self._table_key] = deepcopy(self._column_filters)

            self._page_index = 0
            self._materialize_state(cancel_event=ev)
            self._load_page_rows()
        except StoreError as exc:
            self._handle_store_error(exc)
        finally:
            self.endResetModel()

        self.pageChanged.emit()
        self.sortChanged.emit()
        self.dataReplaced.emit()
        return True

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
            quoted_col = _quote_identifier(column)
            quoted_tbl = _quote_identifier(self._table_name)
            try:
                dist_rows = self._store.execute(
                    f"SELECT DISTINCT {quoted_col} FROM {quoted_tbl}"
                )
                for (val,) in dist_rows:
                    if cancel_event is not None and cancel_event.is_set():
                        raise ImportCancelledError("Operation canceled.")
                    k = self._encode_filter_value(val, column)
                    if k in requested:
                        present.add(k)
                        if present == requested:
                            break
            except Exception:
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
                        k = self._encode_filter_value(val, column)
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

    def _convert_date_val(self, value: Any, column: str) -> Any:
        if self._column_types.get(column) == "date":
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, str):
                try:
                    return date.fromisoformat(value)
                except Exception:
                    pass
        return value

    def _encode_filter_value(self, value: Any, column: str) -> str:
        converted = self._convert_date_val(value, column)
        return _encode_data_view_filter_value(converted)

    def _filter_value_label(self, value: Any, key: str, column: str) -> str:
        converted = self._convert_date_val(value, column)
        return _data_view_filter_value_label(converted, key)

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
            if column_type == "date":
                return (4, value.date().isoformat())
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
            key = self._encode_filter_value(raw_value, column)
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

        actual_cell_val = self._convert_date_val(raw_value, column)
        actual_text = "(null)" if raw_value is None else cell_to_text(actual_cell_val)
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
        store_type = self._store_columns.get(column, "text")
        quoted_col = _quote_identifier(column)

        # Check if text-store column requires canonical verification
        if store_type == "text" and col_type != "text":
            if not self._check_canonical(column):
                return None, []

        # Check non-ASCII text for casefolded operators
        if col_type == "text":
            if self._check_non_ascii(column):
                if operator not in {"is_null", "is_not_null", "is_blank", "is_not_blank"}:
                    return None, []

        if operator == "is_null":
            return f"{quoted_col} IS NULL", []
        if operator == "is_not_null":
            return f"{quoted_col} IS NOT NULL", []
        if operator == "is_blank":
            if col_type == "text" or store_type == "text":
                return f"({quoted_col} IS NULL OR {quoted_col} = '')", []
            return f"{quoted_col} IS NULL", []
        if operator == "is_not_blank":
            if col_type == "text" or store_type == "text":
                return f"({quoted_col} IS NOT NULL AND {quoted_col} != '')", []
            return f"{quoted_col} IS NOT NULL", []

        if operator == "values":
            keys = rule.get("keys", [])
            all_selected = rule.get("all", True)
            if not keys:
                return ("1=1" if all_selected else "1=0"), []

            val_items: list[Any] = []
            has_null = False
            has_empty = False
            for k in keys:
                decoded = _decode_report_filter_value(k)
                if decoded is None:
                    return None, []
                tag, val = decoded
                if tag == "null":
                    has_null = True
                elif tag == "empty":
                    has_empty = True
                elif tag == "typed":
                    t_kind, _t_canon, t_label = val
                    if t_kind == "number":
                        try:
                            # Verify if label has non-canonical representations
                            d = Decimal(t_label)
                            val_items.append(format(d, "f"))
                        except Exception:
                            return None, []
                    elif t_kind == "boolean":
                        val_items.append(t_label.lower() == "true")
                    elif t_kind == "date":
                        val_items.append(t_label)
                    elif t_kind == "datetime":
                        val_items.append(t_label)
                    elif t_kind == "text":
                        val_items.append(t_label)
                    else:
                        return None, []
                else:
                    return None, []

            params: list[Any] = []

            if col_type == "text":
                eq_conds: list[str] = []
                for v in val_items:
                    eq_conds.append(f"{quoted_col} = ?")
                    params.append(v)
                if has_null:
                    eq_conds.append(f"{quoted_col} IS NULL")
                if has_empty:
                    eq_conds.append(f"{quoted_col} = ''")
                if not eq_conds:
                    match_expr = "1=0"
                else:
                    match_expr = f"({' OR '.join(eq_conds)})"
            elif store_type == "text":
                # Text store with non-text label (canonical proven)
                eq_conds = []
                for v in val_items:
                    if col_type in {"whole_number", "decimal_number", "fixed_decimal", "currency", "percentage"}:
                        eq_conds.append(f"(CASE WHEN {quoted_col} IS NOT NULL AND {quoted_col} != '' THEN CAST({quoted_col} AS DECIMAL(38,18)) END = CAST(? AS DECIMAL(38,18)))")
                        params.append(v)
                    elif col_type == "boolean":
                        eq_conds.append(f"(CASE WHEN {quoted_col} IS NOT NULL AND {quoted_col} != '' THEN CAST({quoted_col} AS BOOLEAN) END = ?)")
                        params.append(v)
                    elif col_type == "date":
                        eq_conds.append(f"(CASE WHEN {quoted_col} IS NOT NULL AND {quoted_col} != '' THEN CAST({quoted_col} AS DATE) END = CAST(? AS DATE))")
                        params.append(v)
                    elif col_type == "datetime":
                        eq_conds.append(f"(CASE WHEN {quoted_col} IS NOT NULL AND {quoted_col} != '' THEN CAST({quoted_col} AS TIMESTAMP) END = CAST(? AS TIMESTAMP))")
                        params.append(v)
                if has_null:
                    eq_conds.append(f"{quoted_col} IS NULL")
                if has_empty:
                    eq_conds.append(f"{quoted_col} = ''")
                if not eq_conds:
                    match_expr = "1=0"
                else:
                    match_expr = f"({' OR '.join(eq_conds)})"
            else:
                # Typed store
                eq_conds = []
                for v in val_items:
                    if store_type == "decimal":
                        eq_conds.append(f"{quoted_col} = ?")
                        params.append(float(v))
                    elif col_type in {"whole_number", "decimal_number", "fixed_decimal", "currency", "percentage"}:
                        eq_conds.append(f"{quoted_col} = CAST(? AS DECIMAL(38,18))")
                        params.append(v)
                    elif col_type == "date" and store_type == "datetime":
                        eq_conds.append(f"CAST({quoted_col} AS DATE) = CAST(? AS DATE)")
                        params.append(v)
                    else:
                        eq_conds.append(f"{quoted_col} = ?")
                        params.append(v)
                if has_null:
                    eq_conds.append(f"{quoted_col} IS NULL")
                if not eq_conds:
                    match_expr = "1=0"
                else:
                    match_expr = f"({' OR '.join(eq_conds)})"

            if all_selected:
                return f"NOT COALESCE({match_expr}, FALSE)", params
            return match_expr, params

        expected = rule.get("value", "")

        # String search operators
        if operator in {
            "contains", "does_not_contain", "begins_with", "does_not_begin_with",
            "ends_with", "does_not_end_with",
        }:
            if not expected.isascii():
                return None, []
            esc = _escape_like(expected)
            if operator == "contains":
                pat = f"%{esc}%"
                is_neg = False
            elif operator == "does_not_contain":
                pat = f"%{esc}%"
                is_neg = True
            elif operator == "begins_with":
                pat = f"{esc}%"
                is_neg = False
            elif operator == "does_not_begin_with":
                pat = f"{esc}%"
                is_neg = True
            elif operator == "ends_with":
                pat = f"%{esc}"
                is_neg = False
            else:  # does_not_end_with
                pat = f"%{esc}"
                is_neg = True

            # Determine text expression representing the cell
            if col_type == "date":
                # Formats as YYYY-MM-DD
                if store_type == "datetime":
                    cell_expr = f"(CASE WHEN {quoted_col} IS NULL THEN '(null)' ELSE strftime({quoted_col}, '%Y-%m-%d') END)"
                else:
                    cell_expr = f"(CASE WHEN {quoted_col} IS NULL THEN '(null)' ELSE {quoted_col}::VARCHAR END)"
            elif col_type == "datetime":
                if store_type == "datetime":
                    cell_expr = (
                        f"(CASE WHEN {quoted_col} IS NULL THEN '(null)' ELSE "
                        f"replace(regexp_replace(strftime({quoted_col}, '%Y-%m-%d %H:%M:%S.%f'), '\\.0+$', ''), ' ', 'T') END)"
                    )
                else:
                    cell_expr = f"(CASE WHEN {quoted_col} IS NULL THEN '(null)' ELSE {quoted_col}::VARCHAR END)"
            else:
                cell_expr = f"(CASE WHEN {quoted_col} IS NULL THEN '(null)' ELSE {quoted_col}::VARCHAR END)"

            cond = f"({cell_expr} LIKE ? ESCAPE ? COLLATE NOCASE)"
            if is_neg:
                return f"NOT ({cond})", [pat, "\\"]
            return cond, [pat, "\\"]

        if operator in {"equals", "not_equals"}:
            if col_type in {
                "whole_number", "decimal_number", "fixed_decimal", "currency", "percentage"
            }:
                try:
                    exp_num = Decimal(expected)
                    # Exponents or special notations go to Python path
                    if "e" in expected.lower() or "_" in expected or " " in expected:
                        return None, []
                except Exception:
                    return None, []
                norm_exp = format(exp_num, "f")
                if store_type == "text":
                    target_expr = f"CAST({quoted_col} AS DECIMAL(38,18))"
                    null_guard = f"{quoted_col} IS NOT NULL AND {quoted_col} != ''"
                    if operator == "equals":
                        return f"({null_guard} AND {target_expr} = CAST(? AS DECIMAL(38,18)))", [norm_exp]
                    return f"({quoted_col} IS NULL OR {quoted_col} = '' OR {target_expr} != CAST(? AS DECIMAL(38,18)))", [norm_exp]
                else:
                    target_expr = quoted_col
                    null_guard = f"{quoted_col} IS NOT NULL"
                    if operator == "equals":
                        return f"({null_guard} AND {target_expr} = CAST(? AS DECIMAL(38,18)))", [norm_exp]
                    return f"({quoted_col} IS NULL OR {target_expr} != CAST(? AS DECIMAL(38,18)))", [norm_exp]

            elif col_type == "boolean":
                lowered = expected.strip().casefold()
                if lowered in {"true", "false"}:
                    exp_bool = lowered == "true"
                    if store_type == "text":
                        target_expr = f"CAST({quoted_col} AS BOOLEAN)"
                        null_guard = f"{quoted_col} IS NOT NULL AND {quoted_col} != ''"
                    else:
                        target_expr = quoted_col
                        null_guard = f"{quoted_col} IS NOT NULL"
                    if store_type == "text":
                        if operator == "equals":
                            return f"({null_guard} AND {target_expr} = ?)", [exp_bool]
                        return f"({quoted_col} IS NULL OR {quoted_col} = '' OR {target_expr} != ?)", [exp_bool]
                    else:
                        if operator == "equals":
                            return f"({null_guard} AND {target_expr} = ?)", [exp_bool]
                        return f"({quoted_col} IS NULL OR {target_expr} != ?)", [exp_bool]
                return None, []

            elif col_type in {"date", "datetime"}:
                try:
                    _parse_report_filter_value(expected, col_type)
                except Exception:
                    return None, []
                if store_type == "text":
                    if col_type == "date":
                        target_expr = f"CAST({quoted_col} AS DATE)"
                    else:
                        target_expr = f"CAST({quoted_col} AS TIMESTAMP)"
                    null_guard = f"{quoted_col} IS NOT NULL AND {quoted_col} != ''"
                else:
                    if col_type == "date" and store_type == "datetime":
                        target_expr = f"CAST({quoted_col} AS DATE)"
                    else:
                        target_expr = quoted_col
                    null_guard = f"{quoted_col} IS NOT NULL"

                cast_type = "DATE" if col_type == "date" else "TIMESTAMP"
                if store_type == "text":
                    if operator == "equals":
                        return f"({null_guard} AND {target_expr} = CAST(? AS {cast_type}))", [expected]
                    return f"({quoted_col} IS NULL OR {quoted_col} = '' OR {target_expr} != CAST(? AS {cast_type}))", [expected]
                else:
                    if operator == "equals":
                        return f"({null_guard} AND {target_expr} = CAST(? AS {cast_type}))", [expected]
                    return f"({quoted_col} IS NULL OR {target_expr} != CAST(? AS {cast_type}))", [expected]

            else:
                # Text comparison (case-insensitive)
                if not expected.isascii():
                    return None, []
                if operator == "equals":
                    return (
                        f"((CASE WHEN {quoted_col} IS NULL THEN '(null)' ELSE {quoted_col} END) = ? COLLATE NOCASE)",
                        [expected],
                    )
                return (
                    f"((CASE WHEN {quoted_col} IS NULL THEN '(null)' ELSE {quoted_col} END) != ? COLLATE NOCASE)",
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
                    if "e" in expected.lower() or "_" in expected or " " in expected:
                        return None, []
                except Exception:
                    return None, []
                norm_exp = format(exp_num, "f")
                if store_type == "text":
                    target_expr = f"CAST({quoted_col} AS DECIMAL(38,18))"
                    null_guard = f"{quoted_col} IS NOT NULL AND {quoted_col} != ''"
                    if op_sym in (">", ">="):
                        return f"({quoted_col} = '' OR ({null_guard} AND {target_expr} {op_sym} CAST(? AS DECIMAL(38,18))))", [norm_exp]
                    else:
                        return f"({null_guard} AND {target_expr} {op_sym} CAST(? AS DECIMAL(38,18)))", [norm_exp]
                else:
                    target_expr = quoted_col
                    null_guard = f"{quoted_col} IS NOT NULL"
                    return f"({null_guard} AND {target_expr} {op_sym} CAST(? AS DECIMAL(38,18)))", [norm_exp]

            elif col_type in {"date", "datetime"}:
                try:
                    _parse_report_filter_value(expected, col_type)
                except Exception:
                    return None, []
                if store_type == "text":
                    if col_type == "date":
                        target_expr = f"CAST({quoted_col} AS DATE)"
                    else:
                        target_expr = f"CAST({quoted_col} AS TIMESTAMP)"
                    null_guard = f"{quoted_col} IS NOT NULL AND {quoted_col} != ''"
                else:
                    if col_type == "date" and store_type == "datetime":
                        target_expr = f"CAST({quoted_col} AS DATE)"
                    else:
                        target_expr = quoted_col
                    null_guard = f"{quoted_col} IS NOT NULL"

                cast_type = "DATE" if col_type == "date" else "TIMESTAMP"
                if store_type == "text" and op_sym in (">", ">="):
                    return f"({quoted_col} = '' OR ({null_guard} AND {target_expr} {op_sym} CAST(? AS {cast_type})))", [expected]
                return f"({null_guard} AND {target_expr} {op_sym} CAST(? AS {cast_type}))", [expected]

            elif col_type == "boolean":
                lowered = expected.strip().casefold()
                if lowered in {"true", "false"}:
                    exp_bool = lowered == "true"
                    if store_type == "text":
                        target_expr = f"CAST({quoted_col} AS BOOLEAN)"
                        null_guard = f"{quoted_col} IS NOT NULL AND {quoted_col} != ''"
                    else:
                        target_expr = quoted_col
                        null_guard = f"{quoted_col} IS NOT NULL"
                    if store_type == "text" and op_sym in (">", ">="):
                        return f"({quoted_col} = '' OR ({null_guard} AND {target_expr} {op_sym} ?))", [exp_bool]
                    return f"({null_guard} AND {target_expr} {op_sym} ?)", [exp_bool]
                return None, []

            elif col_type == "text":
                if not expected.isascii():
                    return None, []
                return (
                    f"({quoted_col} IS NOT NULL AND {quoted_col} {op_sym} ? COLLATE NOCASE)",
                    [expected],
                )

        return None, []

    def _build_sort_sql_clause(self) -> str | None:
        """Return SQL ORDER BY expression for current sort column or None if Python sort needed."""
        if not self._sort_column or self._sort_column not in self._headers:
            return '\"__rn\" ASC'
        col = self._sort_column
        col_type = self._column_types.get(col, "text")
        store_type = self._store_columns.get(col, "text")
        quoted_col = _quote_identifier(col)
        direction = "DESC" if self._sort_direction == "descending" else "ASC"

        # Check non-ASCII text
        if col_type == "text":
            if self._check_non_ascii(col):
                return None
            null_clause = "NULLS FIRST" if direction == "ASC" else "NULLS LAST"
            return f"{quoted_col} COLLATE NOCASE {direction} {null_clause}, \"__rn\" ASC"

        if store_type == "text":
            # Must be canonical to use SQL path
            if not self._check_canonical(col):
                return None

            if col_type in {"whole_number", "decimal_number", "fixed_decimal", "currency", "percentage"}:
                cast_expr = f"CASE WHEN {quoted_col} IS NOT NULL AND {quoted_col} != '' THEN CAST({quoted_col} AS DECIMAL(38,18)) ELSE NULL END"
            elif col_type == "boolean":
                cast_expr = f"CASE WHEN {quoted_col} IS NOT NULL AND {quoted_col} != '' THEN CAST({quoted_col} AS BOOLEAN) ELSE NULL END"
            elif col_type == "date":
                cast_expr = f"CASE WHEN {quoted_col} IS NOT NULL AND {quoted_col} != '' THEN CAST({quoted_col} AS DATE) ELSE NULL END"
            elif col_type == "datetime":
                cast_expr = f"CASE WHEN {quoted_col} IS NOT NULL AND {quoted_col} != '' THEN CAST({quoted_col} AS TIMESTAMP) ELSE NULL END"
            else:
                cast_expr = quoted_col

            if direction == "ASC":
                return (
                    f"CASE WHEN {quoted_col} IS NULL THEN 0 ELSE 1 END ASC, "
                    f"CASE WHEN {quoted_col} = '' THEN 1 ELSE 0 END ASC, "
                    f"{cast_expr} ASC, \"__rn\" ASC"
                )
            else:
                return (
                    f"CASE WHEN {quoted_col} IS NULL THEN 1 ELSE 0 END ASC, "
                    f"CASE WHEN {quoted_col} = '' THEN 0 ELSE 1 END ASC, "
                    f"{cast_expr} DESC, \"__rn\" ASC"
                )

        # Typed store
        null_clause = "NULLS FIRST" if direction == "ASC" else "NULLS LAST"
        if col_type == "date" and store_type == "datetime":
            return f"CAST({quoted_col} AS DATE) {direction} {null_clause}, \"__rn\" ASC"
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

        can_sql_filter = True
        where_clauses: list[str] = []
        where_params: list[Any] = []

        for col, rule in self._column_filters.items():
            clause, params = self._build_filter_sql_clause(col, rule)
            if clause is None:
                can_sql_filter = False
                break
            where_clauses.append(f"({clause})")
            where_params.extend(_norm_param(x) for x in params)

        sort_clause = self._build_sort_sql_clause() if can_sql_filter else None

        if can_sql_filter and sort_clause is not None:
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
        ] + ['\"__rn\"']
        select_sql = f"SELECT {', '.join(select_cols)} FROM {quoted_tbl} ORDER BY \"__rn\" ASC"

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

        if self._sort_column and self._sort_column in self._headers:
            reverse = self._sort_direction == "descending"
            if reverse:
                matching_rows.sort(key=lambda item: item[0], reverse=True)
            else:
                matching_rows.sort(key=lambda item: item[0])

        filtered_rns = [item[1] for item in matching_rows]
        self._filtered_rows = len(filtered_rns)

        self._view_counter += 1
        view_name = f"{self._view_prefix}{self._view_counter}"
        self._store.register_arrow_ids(view_name, filtered_rns)
        self._active_view_name = view_name

    def _load_page_rows(self) -> None:
        """Fetch rows for current page index into self._rows."""
        if not self._table_name or not self._store.has_table(self._table_name) or self._filtered_rows == 0:
            self._rows = []
            return

        start = self._page_index * PREVIEW_ROW_LIMIT
        limit = PREVIEW_ROW_LIMIT

        if self._active_view_name is not None:
            quoted_tbl = _quote_identifier(self._table_name)
            quoted_view = _quote_identifier(self._active_view_name)
            col_selects = [
                f"t.{_quote_identifier(col)} AS {_quote_identifier(col)}"
                for col in self._headers
            ]
            sql = (
                f"SELECT {', '.join(col_selects)} "
                f"FROM {quoted_tbl} t "
                f"JOIN {quoted_view} v ON t.\"__rn\" = v.\"__rn\" "
                f"ORDER BY v.position ASC "
                f"LIMIT ? OFFSET ?"
            )
            tuples = self._store.execute(sql, [limit, start])
        else:
            tuples = self._store.read_page(
                self._table_name, start, limit, columns=self._headers
            )

        self._rows = [
            dict(zip(self._headers, row_tuple)) for row_tuple in tuples
        ]

    def _set_page(self, page_index: int) -> bool:
        page_count = self.pageCount
        next_index = max(0, min(page_index, max(0, page_count - 1)))
        if next_index == self._page_index:
            return True

        old_index = self._page_index
        old_rows = self._rows
        self.beginResetModel()
        try:
            self._page_index = next_index
            self._load_page_rows()
        except StoreError as exc:
            self._page_index = old_index
            self._rows = old_rows
            self._handle_store_error(exc)
            return False
        finally:
            self.endResetModel()

        self.pageChanged.emit()
        return True

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

        # Save previous state in case of StoreError
        old_sort_col = self._sort_column
        old_sort_dir = self._sort_direction
        old_page_index = self._page_index
        old_rows = self._rows
        old_filtered = self._filtered_rows
        old_active_view = self._active_view_name

        self.beginResetModel()
        try:
            self._sort_column = column
            self._sort_direction = direction
            if self._table_key:
                self._sort_by_table[self._table_key] = (column, direction)
            self._materialize_state(cancel_event=self._effective_cancel_event())
            self._page_index = 0
            self._load_page_rows()
        except StoreError as exc:
            self._sort_column = old_sort_col
            self._sort_direction = old_sort_dir
            self._page_index = old_page_index
            self._rows = old_rows
            self._filtered_rows = old_filtered
            self._active_view_name = old_active_view
            if self._table_key:
                if old_sort_col:
                    self._sort_by_table[self._table_key] = (old_sort_col, old_sort_dir)
                else:
                    self._sort_by_table.pop(self._table_key, None)
            self._handle_store_error(exc)
            return
        finally:
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

    @Slot(str, result=bool)
    def columnFilterValuesTruncated(self, column: str) -> bool:  # noqa: N802
        cf = self.columnFilterValues(column, "")
        return bool(cf.get("truncated", False))

    @Slot(str, result=int)
    def columnFilterValueTotal(self, column: str) -> int:  # noqa: N802
        cf = self.columnFilterValues(column, "")
        return int(cf.get("totalCount", 0))

    @Slot(str, result="QVariantMap")
    @Slot(str, str, result="QVariantMap")
    def columnFilterValues(self, column: str, search: str = "") -> dict[str, Any]:  # noqa: N802
        """Search distinct filter values in the domain after other-column filters."""
        empty_res = {"values": [], "matchCount": 0, "totalCount": 0, "truncated": False}
        if column not in self._headers or not self._table_name:
            return empty_res

        try:
            if not self._store.has_table(self._table_name):
                return empty_res
        except StoreError as exc:
            self._handle_store_error(exc)
            return empty_res

        other_filters = {
            c: r for c, r in self._column_filters.items() if c != column
        }

        # Check if other filters can be translated to SQL
        can_sql = True
        where_clauses: list[str] = []
        where_params: list[Any] = []
        for c, rule in other_filters.items():
            clause, params = self._build_filter_sql_clause(c, rule)
            if clause is None:
                can_sql = False
                break
            where_clauses.append(f"({clause})")
            where_params.extend(_norm_param(x) for x in params)

        if can_sql:
            quoted_col = _quote_identifier(column)
            quoted_tbl = _quote_identifier(self._table_name)
            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            try:
                cnt_sql = (
                    f"SELECT count(*) FROM (SELECT DISTINCT {quoted_col} FROM {quoted_tbl} {where_sql} LIMIT 5001)"
                )
                cnt_res = self._store.execute(cnt_sql, where_params)
                distinct_sample_count = cnt_res[0][0] if cnt_res else 0

                if distinct_sample_count <= 5_000:
                    # Full domain
                    dist_rows = self._store.execute(
                        f"SELECT {quoted_col} FROM {quoted_tbl} {where_sql} GROUP BY {quoted_col} ORDER BY min(\"__rn\")",
                        where_params,
                    )
                    distinct: dict[str, str] = {}
                    for (raw_value,) in dist_rows:
                        key = self._encode_filter_value(raw_value, column)
                        distinct[key] = self._filter_value_label(raw_value, key, column)
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
                else:
                    # Capped fast path: query top 2,000 distinct in first-appearance order
                    dist_rows = self._store.execute(
                        f"SELECT {quoted_col} FROM {quoted_tbl} {where_sql} GROUP BY {quoted_col} ORDER BY min(\"__rn\") LIMIT 2000",
                        where_params,
                    )
                    distinct = {}
                    for (raw_value,) in dist_rows:
                        key = self._encode_filter_value(raw_value, column)
                        distinct[key] = self._filter_value_label(raw_value, key, column)
                    labels = _disambiguate_data_view_filter_labels(distinct)
                    query = (search or "").strip().casefold()
                    matched = [
                        (key, label) for key, label in labels.items()
                        if not query or query in label.casefold()
                    ]
                    matched.sort(key=lambda item: (item[1].casefold(), item[1], item[0]))

                    # Query total distinct count
                    tot_res = self._store.execute(
                        f"SELECT count(DISTINCT {quoted_col}) FROM {quoted_tbl} {where_sql}",
                        where_params,
                    )
                    total_count = tot_res[0][0] if tot_res else 5001
                    return {
                        "values": [
                            {"key": key, "label": label}
                            for key, label in matched
                        ],
                        "matchCount": total_count,
                        "totalCount": total_count,
                        "truncated": True,
                    }
            except StoreError as exc:
                self._handle_store_error(exc)
                return empty_res
            except Exception:
                pass

        # Fallback to chunk scan
        distinct = {}
        offset = 0
        cols_needed = list(other_filters.keys()) + ([column] if column not in other_filters else [])
        try:
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
                        key = self._encode_filter_value(raw_value, column)
                        if key not in distinct:
                            distinct[key] = self._filter_value_label(raw_value, key, column)
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
        except StoreError as exc:
            self._handle_store_error(exc)
            return empty_res

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

        old_filters = deepcopy(self._column_filters)
        old_page_index = self._page_index
        old_rows = self._rows
        old_filtered = self._filtered_rows
        old_active_view = self._active_view_name

        self.beginResetModel()
        try:
            self._column_filters[column] = {"operator": operator, "value": value}
            if self._table_key:
                self._filters_by_table[self._table_key] = deepcopy(self._column_filters)
            self._materialize_state(cancel_event=self._effective_cancel_event())
            self._page_index = 0
            self._load_page_rows()
        except StoreError as exc:
            self._column_filters = old_filters
            self._page_index = old_page_index
            self._rows = old_rows
            self._filtered_rows = old_filtered
            self._active_view_name = old_active_view
            if self._table_key:
                self._filters_by_table[self._table_key] = deepcopy(old_filters)
            self._handle_store_error(exc)
            return
        finally:
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
            return False

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
                    k = self._encode_filter_value(val, column)
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
                        k = self._encode_filter_value(val, column)
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

        old_filters = deepcopy(self._column_filters)
        old_page_index = self._page_index
        old_rows = self._rows
        old_filtered = self._filtered_rows
        old_active_view = self._active_view_name

        self.beginResetModel()
        try:
            self._column_filters[column] = {
                "operator": "values",
                "all": bool(all_selected),
                "keys": normalized,
            }
            if self._table_key:
                self._filters_by_table[self._table_key] = deepcopy(self._column_filters)
            self._materialize_state(cancel_event=self._effective_cancel_event())
            self._page_index = 0
            self._load_page_rows()
        except StoreError as exc:
            self._column_filters = old_filters
            self._page_index = old_page_index
            self._rows = old_rows
            self._filtered_rows = old_filtered
            self._active_view_name = old_active_view
            if self._table_key:
                self._filters_by_table[self._table_key] = deepcopy(old_filters)
            self._handle_store_error(exc)
            return
        finally:
            self.endResetModel()

        self.pageChanged.emit()
        self.filterChanged.emit()

    @Slot(str)
    def clearColumnFilter(self, column: str) -> None:  # noqa: N802
        if column not in self._column_filters:
            return

        old_filters = deepcopy(self._column_filters)
        old_page_index = self._page_index
        old_rows = self._rows
        old_filtered = self._filtered_rows
        old_active_view = self._active_view_name

        self.beginResetModel()
        try:
            self._column_filters.pop(column, None)
            if self._table_key:
                if self._column_filters:
                    self._filters_by_table[self._table_key] = deepcopy(self._column_filters)
                else:
                    self._filters_by_table.pop(self._table_key, None)
            self._materialize_state(cancel_event=self._effective_cancel_event())
            self._page_index = 0
            self._load_page_rows()
        except StoreError as exc:
            self._column_filters = old_filters
            self._page_index = old_page_index
            self._rows = old_rows
            self._filtered_rows = old_filtered
            self._active_view_name = old_active_view
            if self._table_key:
                self._filters_by_table[self._table_key] = deepcopy(old_filters)
            self._handle_store_error(exc)
            return
        finally:
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
        header = self._headers[index.column()]
        value = self._rows[index.row()].get(header, "")
        if value is None:
            return "(null)"
        converted = self._convert_date_val(value, header)
        return cell_to_text(converted)

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
