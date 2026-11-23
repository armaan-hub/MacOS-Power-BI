"""DuckStore-backed table model for Data view grid preview.

Provides a replacement for CsvTableModel that queries a DuckStore table on demand while
holding only the current page (up to PREVIEW_ROW_LIMIT = 500 rows) in Python memory.

Two store shapes are supported.

* All-text store (what the CSV importer builds): every column is stored as text and
  `column_types` only labels them (whole_number, decimal_number, boolean, date,
  datetime ...). CsvTableModel parses each text cell according to its label, so this
  model uses SQL for a text column with a typed label ONLY when a cached check proves
  that every non-empty cell is in a strict canonical form on which SQL and Python agree
  (see `_canonical_sql`). Otherwise that column uses the exact Python path. Value-filter
  keys on a text store are always the raw cell strings, whatever the label says.
* Typed store (Parquet import): whole, decimal, fixed, datetime, boolean and text
  columns. SQL is used when the label fits the stored type.

If a sort or filter cannot be translated exactly, or if its SQL raises a conversion
error, the exact Python path runs instead: it streams the table in chunks, applies the
old `_sort_key` / `_matches_column_filter` rules and keeps the resulting row ids in a
temporary table. It is exact but slow on huge tables (tens of seconds on 10 million rows).

State handling: every change (sort, filters, replace_data, page change) first builds the
new row-id table under a new unique name and loads the new page. Only when all of that
worked does it switch the model state inside beginResetModel/endResetModel and then drop
the old temporary table. If anything fails the old state and the old table stay as they
were, the partial new table is dropped, `lastError` is set and `storeError` is emitted.

Threading note:
StoreTableModel is designed for use on the Qt UI thread only. DuckStore uses a
single internal connection protected by a non-blocking reentrant threading lock.
When a background import or long-running store job holds the store lock, any store
call from StoreTableModel immediately raises StoreError("The store is busy with another operation.").
StoreTableModel catches StoreError internally, records it in lastError, emits the storeError(str)
signal, keeps the previous model state, and returns neutral/cached values.

Known differences from CsvTableModel:
- -inf ordering (B15): In DuckDB SQL, floating point `-inf` on typed decimal (DOUBLE) columns
  sorts before all finite numbers in ASC order (`-inf`, `0.0`, `1.0`, `inf`), matching IEEE-754
  and standard SQL semantics. In CsvTableModel, Python's `Decimal(str(value)).is_finite()` branch
  sorts `-inf` under group `(3, 1, '-inf')` after all finite numbers `(3, 0, number)`. Store whole
  columns cannot hold infinity; decimal columns can.
- Distinct filter values above 5,000: `columnFilterValues` is exact (all values, old order,
  old labels) up to 5,000 distinct values. Above that it returns at most 2,000 matching
  values in first-appearance order (the old model would sort all matches by label first),
  `matchCount` is the number of matches capped at 100,000 (`matchCountCapped` says whether
  the cap was hit), `truncated` says more than 2,000 values match, and the type-suffix
  labels such as "(Number)" are only made unique among the returned values.
- A 'date' label on a text store shows and keys the raw cell text; only timestamp-typed
  store columns (Parquet date32) are converted to dates.
- The row total is read at replace_data time; rows appended to the table later show up
  only in sorted or filtered views and after the next replace_data.
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from copy import deepcopy
from datetime import date, datetime, time
from decimal import Decimal, DecimalException
from typing import Any, Callable

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

# Rows per chunk on the exact Python paths (tests lower these to exercise the loops).
_PY_CHUNK = 50_000
_CFV_PY_CHUNK = 50_000
# columnFilterValues limits.
_CFV_SMALL_LIMIT = 5_000
_CFV_RETURN_LIMIT = 2_000
_CFV_COUNT_CAP = 100_000
_CFV_CACHE_MAX = 64

_NULL_BLANK_OPS = {"is_null", "is_not_null", "is_blank", "is_not_blank"}
_TEXT_OPS = {
    "contains", "does_not_contain", "begins_with", "does_not_begin_with",
    "ends_with", "does_not_end_with",
}
_ORDER_OPS = {"greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"}
_ORDER_SYMBOLS = {
    "greater_than": ">", "greater_than_or_equal": ">=",
    "less_than": "<", "less_than_or_equal": "<=",
}
_NUMERIC_STORE_TYPES = {"whole", "decimal", "fixed"}
_NUMERIC_LABELS = {"whole_number", "decimal_number", "fixed_decimal", "currency", "percentage"}
# Labels CsvTableModel parses on a text cell; any other label behaves like "text".
_TEXT_STORE_TYPED_LABELS = {"whole_number", "decimal_number", "boolean", "date", "datetime"}

# Canonical text forms (full match). Strictly inside what Python parses identically.
_CANON_INT = r"^[+-]?[0-9]{1,18}$"
_CANON_DEC = r"^[+-]?[0-9]{1,18}(\.[0-9]{1,18})?$"
_CANON_BOOL = r"^(?i:true|false)$"
_DATE_PART = r"[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])"
_CANON_DATE = "^" + _DATE_PART + "$"
_CANON_TS = (
    "^" + _DATE_PART
    + r"[T ]([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]{1,6})?$"
)
_SIMPLE_NUMBER_RE = re.compile(_CANON_DEC)
_SIMPLE_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_SIMPLE_TS_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}"
    r"([T ]([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]{1,6})?)?$"
)


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


def _is_infra_error(exc: BaseException) -> bool:
    """True for errors that a retry on the Python path cannot fix (busy or closed store)."""
    message = str(exc)
    return "store is busy" in message or "Store is closed" in message


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

        # Caches keyed by (table, store change token, column and label): a table change makes the
        # old entries unreachable, so a stale answer can never be used.
        self._canonical_cache: dict[tuple[str, int, str], bool] = {}
        self._non_ascii_cache: dict[tuple[str, int, str], bool] = {}
        # (table, token, column, other-filters signature) -> cached facts about the domain.
        self._cfv_cache: dict[tuple[str, int, str, str], dict[str, Any]] = {}

    def __del__(self) -> None:
        try:
            self._cleanup_view()
        except Exception:
            pass

    def _cleanup_view(self) -> None:
        if self._active_view_name is not None:
            view_to_drop = self._active_view_name
            self._active_view_name = None
            self._drop_quiet(view_to_drop)

    def _drop_quiet(self, view_name: str | None) -> None:
        if view_name is None:
            return
        try:
            self._store.drop_view(view_name)
        except Exception:
            pass

    def _next_view_name(self) -> str:
        self._view_counter += 1
        return f"{self._view_prefix}{self._view_counter}"

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

    # ------------------------------------------------------------------
    # Atomic state change
    # ------------------------------------------------------------------

    def _snapshot(self) -> dict[str, Any]:
        return {
            "_table_name": self._table_name,
            "_table_key": self._table_key,
            "_headers": self._headers,
            "_store_columns": self._store_columns,
            "_total_rows": self._total_rows,
            "_column_types": self._column_types,
            "_sort_column": self._sort_column,
            "_sort_direction": self._sort_direction,
            "_column_filters": deepcopy(self._column_filters),
            "_sort_by_table": dict(self._sort_by_table),
            "_filters_by_table": dict(self._filters_by_table),
        }

    def _restore(self, snap: dict[str, Any]) -> None:
        for name, value in snap.items():
            setattr(self, name, value)

    def _transition(
        self,
        mutate: Callable[[], None],
        signals: tuple[Any, ...],
        cancel_event: threading.Event | None = None,
    ) -> bool:
        """Apply `mutate` (plain attribute changes and store queries, no Qt calls),
        build the new row-id table and first page, then switch to them in one reset.

        Any failure restores the old attributes, drops the partial new table and keeps
        the old table in use. StoreError is reported through storeError and returns False;
        other errors (for example a cancel) are re-raised after the restore.
        """
        ev = self._effective_cancel_event(cancel_event)
        snap = self._snapshot()
        new_view: str | None = None
        try:
            mutate()
            new_view, count = self._build_view(ev)
            rows = self._fetch_page(new_view, count, 0)
        except BaseException as exc:
            self._restore(snap)
            self._drop_quiet(new_view)
            if isinstance(exc, StoreError):
                self._handle_store_error(exc)
                return False
            raise

        old_view = self._active_view_name
        self.beginResetModel()
        try:
            self._active_view_name = new_view
            self._filtered_rows = count
            self._page_index = 0
            self._rows = rows
        finally:
            self.endResetModel()
        if old_view != new_view:
            self._drop_quiet(old_view)
        self._last_error = ""
        for sig in signals:
            sig.emit()
        return True

    # ------------------------------------------------------------------
    # Cached column facts
    # ------------------------------------------------------------------

    def _cache_key(self, column: str) -> tuple[str, int, str]:
        """Cache key: table, store change token, column and its label and stored type."""
        label = f"{self._column_types.get(column, 'text')}|{self._store_columns.get(column, 'text')}"
        return (
            self._table_name,
            self._store.table_version(self._table_name),
            f"{column}\x00{label}",
        )

    def _shape(self, column: str) -> str | None:
        """Effective label of a column for SQL decisions, or None when only Python is exact.

        Text store: the label if CsvTableModel parses it ('whole_number', 'decimal_number',
        'boolean', 'date', 'datetime'), otherwise 'text' (CsvTableModel keeps such text
        cells as text); 'time' is Python only.
        Typed store: the label must fit the stored type (a numeric label for number
        columns, 'boolean' for booleans, 'date' or 'datetime' for timestamps).
        """
        store_type = self._store_columns.get(column, "text")
        label = self._column_types.get(column, "text")
        if store_type == "text":
            if label == "time":
                return None
            return label if label in _TEXT_STORE_TYPED_LABELS else "text"
        if store_type in _NUMERIC_STORE_TYPES:
            return label if label in _NUMERIC_LABELS else None
        if store_type == "boolean":
            return "boolean" if label == "boolean" else None
        if store_type == "datetime":
            return label if label in {"date", "datetime"} else None
        return None

    def _canonical_sql(self, label: str, quoted_col: str) -> tuple[str, list[Any]] | None:
        """SQL boolean aggregate that is true when every non-blank cell is canonical."""
        if label == "whole_number":
            cond, params = f"{quoted_col} ~ ?", [_CANON_INT]
        elif label == "decimal_number":
            cond, params = f"{quoted_col} ~ ?", [_CANON_DEC]
        elif label == "boolean":
            cond, params = f"{quoted_col} ~ ?", [_CANON_BOOL]
        elif label == "date":
            cond = (
                f"({quoted_col} ~ ? AND substr({quoted_col}, 1, 4) != '0000' "
                f"AND TRY_CAST({quoted_col} AS DATE) IS NOT NULL)"
            )
            params = [_CANON_DATE]
        elif label == "datetime":
            cond = (
                f"({quoted_col} ~ ? AND substr({quoted_col}, 1, 4) != '0000' "
                f"AND TRY_CAST({quoted_col} AS TIMESTAMP) IS NOT NULL)"
            )
            params = [_CANON_TS]
        else:
            return None
        return f"bool_and({quoted_col} IS NULL OR {quoted_col} = '' OR {cond})", params

    def _check_canonical(self, column: str) -> bool:
        """True if every non-blank cell of a text-store column is canonical for its label.

        Cached per (table, store change token, column).
        """
        if not self._table_name or not self._store.has_table(self._table_name):
            return False
        cache_key = self._cache_key(column)
        if cache_key in self._canonical_cache:
            return self._canonical_cache[cache_key]

        built = self._canonical_sql(self._shape(column) or "", _quote_identifier(column))
        if built is None:
            self._canonical_cache[cache_key] = False
            return False
        agg, params = built
        sql = f"SELECT {agg} FROM {_quote_identifier(self._table_name)}"
        try:
            res = self._store.execute(sql, params)
            is_canon = bool(res[0][0]) if res and res[0][0] is not None else True
        except StoreError as exc:
            if _is_infra_error(exc):
                raise
            is_canon = False
        self._canonical_cache[cache_key] = is_canon
        return is_canon

    def _check_non_ascii(self, column: str) -> bool:
        """Check if any text value in column contains non-ASCII characters."""
        if not self._table_name or not self._store.has_table(self._table_name):
            return False
        cache_key = self._cache_key(column)
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
        except StoreError as exc:
            if _is_infra_error(exc):
                raise
            has_non_ascii = True
        self._non_ascii_cache[cache_key] = has_non_ascii
        return has_non_ascii

    # ------------------------------------------------------------------
    # Filter keys
    # ------------------------------------------------------------------

    def _decoded_text_key(self, key: str) -> tuple[str, str | None] | None:
        """Decode a value-filter key for a text-store column into ('null'|'empty'|'text', raw).

        A key is only honoured when it is exactly what the old model would build for that
        raw string; any other spelling can never match a cell, so it returns None.
        """
        dec = _decode_report_filter_value(key)
        if dec is None:
            return None
        tag, val = dec
        if tag == "null":
            return ("null", None)
        if tag == "empty":
            return ("empty", "")
        if tag == "text":
            raw = val
        elif tag == "typed" and val[0] == "text":
            raw = val[1]
        else:
            return None
        if _encode_data_view_filter_value(raw) != key:
            return None
        return ("text", raw)

    def _present_keys(
        self,
        column: str,
        requested: set[str],
        cancel_event: threading.Event | None = None,
    ) -> set[str]:
        """Return the requested value-filter keys that really occur in the column."""
        present: set[str] = set()
        if not requested or not self._table_name or not self._store.has_table(self._table_name):
            return present
        quoted_col = _quote_identifier(column)
        quoted_tbl = _quote_identifier(self._table_name)

        if self._store_columns.get(column, "text") == "text":
            raws: list[str] = []
            want_null = want_empty = False
            for key in requested:
                dec = self._decoded_text_key(key)
                if dec is None:
                    continue
                if dec[0] == "null":
                    want_null = True
                elif dec[0] == "empty":
                    want_empty = True
                else:
                    raws.append(str(dec[1]))
            for start in range(0, len(raws), 1_000):
                if cancel_event is not None and cancel_event.is_set():
                    raise ImportCancelledError("Operation canceled.")
                part = raws[start:start + 1_000]
                marks = ", ".join("?" for _ in part)
                rows = self._store.execute(
                    f"SELECT DISTINCT {quoted_col} FROM {quoted_tbl} WHERE {quoted_col} IN ({marks})",
                    part,
                )
                for (val,) in rows:
                    present.add(self._encode_filter_value(val, column))
            if want_null:
                res = self._store.execute(
                    f"SELECT count(*) FROM (SELECT 1 FROM {quoted_tbl} WHERE {quoted_col} IS NULL LIMIT 1)"
                )
                if res and res[0][0]:
                    present.add(self._encode_filter_value(None, column))
            if want_empty:
                res = self._store.execute(
                    f"SELECT count(*) FROM (SELECT 1 FROM {quoted_tbl} WHERE {quoted_col} = '' LIMIT 1)"
                )
                if res and res[0][0]:
                    present.add(self._encode_filter_value("", column))
            return present & requested

        for (val,) in self._store.execute(
            f"SELECT DISTINCT {quoted_col} FROM {quoted_tbl}"
        ):
            if cancel_event is not None and cancel_event.is_set():
                raise ImportCancelledError("Operation canceled.")
            k = self._encode_filter_value(val, column)
            if k in requested:
                present.add(k)
                if present == requested:
                    break
        return present

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

            present = self._present_keys(column, requested, cancel_event)
            rule["keys"] = sorted(present)
            if rule.get("all", True) and not present:
                self._column_filters.pop(column, None)

    def _convert_date_val(self, value: Any, column: str) -> Any:
        """Show a timestamp-typed store column labelled 'date' as a date.

        Only datetime values are converted; a text-store cell is a string and keeps its
        raw text whatever the label says.
        """
        if self._column_types.get(column) == "date" and isinstance(value, datetime):
            return value.date()
        return value

    def _encode_filter_value(self, value: Any, column: str) -> str:
        converted = self._convert_date_val(value, column)
        return _encode_data_view_filter_value(converted)

    def _filter_value_label(self, value: Any, key: str, column: str) -> str:
        converted = self._convert_date_val(value, column)
        return _data_view_filter_value_label(converted, key)

    # ------------------------------------------------------------------
    # Exact Python rules (same as CsvTableModel)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # SQL translation of filters
    # ------------------------------------------------------------------

    def _numeric_expected(self, expected: str, label: str, store_type: str) -> str | None:
        """Plain decimal text for an expected number, or None when Python must decide.

        None when the old parse would not read it as a number of this label (whole_number
        needs an integer), when it is not a plain number, or when a DOUBLE column could
        compare differently after rounding (more than 15 significant digits).
        """
        if label not in {"whole_number", "decimal_number"}:
            return None
        if not _SIMPLE_NUMBER_RE.fullmatch(expected):
            return None
        number = Decimal(expected)
        if label == "whole_number" and number != number.to_integral_value():
            return None
        if store_type == "decimal" and len(number.normalize().as_tuple().digits) > 15:
            return None
        return format(number, "f")

    def _temporal_expected(self, expected: str, label: str) -> str | None:
        """Text for CAST(? AS DATE/TIMESTAMP) when SQL and the old parse agree, else None."""
        try:
            if label == "date":
                if not _SIMPLE_DATE_RE.fullmatch(expected):
                    return None
                return date.fromisoformat(expected).isoformat()
            if label == "datetime":
                if not _SIMPLE_TS_RE.fullmatch(expected):
                    return None
                return datetime.fromisoformat(expected).isoformat(sep=" ")
        except ValueError:
            return None
        return None

    @staticmethod
    def _compare_clause(
        operator: str, quoted_col: str, target: str, param_sql: str, text_store: bool
    ) -> str:
        """Typed comparison with the old blank rules (None never matches; '' sorts after typed)."""
        if text_store:
            not_blank = f"{quoted_col} IS NOT NULL AND {quoted_col} != ''"
        else:
            not_blank = f"{quoted_col} IS NOT NULL"
        if operator == "equals":
            return f"({not_blank} AND {target} = {param_sql})"
        if operator == "not_equals":
            if text_store:
                return f"({quoted_col} IS NULL OR {quoted_col} = '' OR {target} != {param_sql})"
            return f"({quoted_col} IS NULL OR {target} != {param_sql})"
        sym = _ORDER_SYMBOLS[operator]
        if text_store and sym in (">", ">="):
            return f"({quoted_col} = '' OR ({not_blank} AND {target} {sym} {param_sql}))"
        return f"({not_blank} AND {target} {sym} {param_sql})"

    def _values_clause(
        self, column: str, rule: dict[str, Any], eff: str, store_type: str
    ) -> tuple[str | None, list[Any]]:
        keys = rule.get("keys", [])
        all_selected = rule.get("all", True)
        if not keys:
            return ("1=1" if all_selected else "1=0"), []
        quoted_col = _quote_identifier(column)
        conds: list[str] = []
        params: list[Any] = []
        has_null = False

        if store_type == "text":
            # Keys on a text store are the raw cell strings, whatever the label says.
            raws: list[str] = []
            has_empty = False
            for key in keys:
                dec = self._decoded_text_key(key)
                if dec is None:
                    continue
                if dec[0] == "null":
                    has_null = True
                elif dec[0] == "empty":
                    has_empty = True
                else:
                    raws.append(str(dec[1]))
            if raws:
                conds.append(f"{quoted_col} IN ({', '.join('?' for _ in raws)})")
                params.extend(raws)
            if has_empty:
                conds.append(f"{quoted_col} = ''")
        else:
            items: list[Any] = []
            for key in keys:
                dec = _decode_report_filter_value(key)
                if dec is None:
                    continue
                tag, val = dec
                if tag == "null":
                    has_null = True
                    continue
                if tag != "typed":
                    continue
                kind, canon, _label = val
                item = self._typed_key_item(kind, canon, key, eff, store_type)
                if item is not None:
                    items.append(item)
            for item in items:
                if store_type == "decimal":
                    conds.append(f"{quoted_col} = ?")
                elif store_type in {"whole", "fixed"}:
                    conds.append(f"{quoted_col} = CAST(? AS DECIMAL(38,18))")
                elif eff == "date":
                    conds.append(f"CAST({quoted_col} AS DATE) = CAST(? AS DATE)")
                elif eff == "datetime":
                    conds.append(f"{quoted_col} = CAST(? AS TIMESTAMP)")
                else:
                    conds.append(f"{quoted_col} = ?")
                params.append(item)
        if has_null:
            conds.append(f"{quoted_col} IS NULL")
        match_expr = f"({' OR '.join(conds)})" if conds else "1=0"
        if all_selected:
            # NULL cells must stay visible when other values are excluded.
            return f"NOT COALESCE({match_expr}, FALSE)", params
        return match_expr, params

    @staticmethod
    def _typed_key_item(
        kind: str, canon: str, key: str, eff: str, store_type: str
    ) -> Any | None:
        """SQL parameter for a typed-store key, or None when no stored value can have this key."""
        try:
            if store_type in _NUMERIC_STORE_TYPES:
                if kind != "number":
                    return None
                number = Decimal(canon)
                if _encode_data_view_filter_value(number) != key:
                    return None
                if store_type == "decimal":
                    return float(number)
                if not number.is_finite() or int(number.as_tuple().exponent) < -18:
                    return None
                return format(number, "f")
            if store_type == "boolean":
                if kind != "boolean" or canon not in {"true", "false"}:
                    return None
                return canon == "true"
            if store_type == "datetime":
                if eff == "date":
                    if kind != "date":
                        return None
                    day = date.fromisoformat(canon)
                    if _encode_data_view_filter_value(day) != key:
                        return None
                    return day.isoformat()
                if kind != "datetime":
                    return None
                stamp = datetime.fromisoformat(canon)
                if _encode_data_view_filter_value(stamp) != key:
                    return None
                return stamp.isoformat(sep=" ")
        except (ValueError, DecimalException):
            return None
        return None

    def _text_op_clause(
        self, column: str, operator: str, expected: str, eff: str, store_type: str
    ) -> tuple[str | None, list[Any]]:
        quoted_col = _quote_identifier(column)
        if not expected.isascii():
            return None, []
        if store_type == "text":
            if self._check_non_ascii(column):
                return None, []
            cell_expr = f"(CASE WHEN {quoted_col} IS NULL THEN '(null)' ELSE {quoted_col} END)"
        elif store_type == "datetime":
            if eff == "date":
                cell_expr = (
                    f"(CASE WHEN {quoted_col} IS NULL THEN '(null)' "
                    f"ELSE strftime({quoted_col}, '%Y-%m-%d') END)"
                )
            else:
                cell_expr = (
                    f"(CASE WHEN {quoted_col} IS NULL THEN '(null)' ELSE "
                    f"replace(regexp_replace(strftime({quoted_col}, '%Y-%m-%d %H:%M:%S.%f'), "
                    f"'\\.0+$', ''), ' ', 'T') END)"
                )
        else:
            cell_expr = f"(CASE WHEN {quoted_col} IS NULL THEN '(null)' ELSE {quoted_col}::VARCHAR END)"

        esc = _escape_like(expected)
        if operator in {"contains", "does_not_contain"}:
            pat = f"%{esc}%"
        elif operator in {"begins_with", "does_not_begin_with"}:
            pat = f"{esc}%"
        else:
            pat = f"%{esc}"
        cond = f"({cell_expr} LIKE ? ESCAPE ? COLLATE NOCASE)"
        if operator.startswith("does_not"):
            return f"NOT ({cond})", [pat, "\\"]
        return cond, [pat, "\\"]

    def _build_filter_sql_clause(
        self, column: str, rule: dict[str, Any]
    ) -> tuple[str | None, list[Any]]:
        """Try to translate a filter rule into SQL.

        Returns (sql_condition, params) or (None, []) if Python evaluation is required.
        """
        operator = rule["operator"]
        eff = self._shape(column)
        if eff is None:
            return None, []
        label = self._column_types.get(column, "text")
        store_type = self._store_columns.get(column, "text")
        text_store = store_type == "text"
        quoted_col = _quote_identifier(column)

        if operator == "is_null":
            return f"{quoted_col} IS NULL", []
        if operator == "is_not_null":
            return f"{quoted_col} IS NOT NULL", []
        if operator == "is_blank":
            if text_store:
                return f"({quoted_col} IS NULL OR {quoted_col} = '')", []
            return f"{quoted_col} IS NULL", []
        if operator == "is_not_blank":
            if text_store:
                return f"({quoted_col} IS NOT NULL AND {quoted_col} != '')", []
            return f"{quoted_col} IS NOT NULL", []
        if operator == "values":
            return self._values_clause(column, rule, eff, store_type)

        expected = rule.get("value", "")
        if operator in _TEXT_OPS:
            return self._text_op_clause(column, operator, expected, eff, store_type)
        if operator not in {"equals", "not_equals"} and operator not in _ORDER_OPS:
            return None, []

        if text_store and eff == "text":
            if not expected.isascii() or self._check_non_ascii(column):
                return None, []
            if operator in {"equals", "not_equals"}:
                cmp_sql = "=" if operator == "equals" else "!="
                return (
                    f"((CASE WHEN {quoted_col} IS NULL THEN '(null)' ELSE {quoted_col} END) "
                    f"{cmp_sql} ? COLLATE NOCASE)",
                    [expected],
                )
            return (
                f"({quoted_col} IS NOT NULL AND {quoted_col} {_ORDER_SYMBOLS[operator]} ? COLLATE NOCASE)",
                [expected],
            )

        if text_store and not self._check_canonical(column):
            return None, []

        # Typed comparison (typed store, or text store proven canonical).
        if eff in _NUMERIC_LABELS:
            number = self._numeric_expected(expected, label, store_type)
            if number is None:
                return None, []
            if store_type == "decimal":
                param_sql = "CAST(? AS DOUBLE)"
            else:
                param_sql = "CAST(? AS DECIMAL(38,18))"
            target = (
                f"TRY_CAST({quoted_col} AS DECIMAL(38,18))" if text_store else quoted_col
            )
            return self._compare_clause(operator, quoted_col, target, param_sql, text_store), [number]
        if eff == "boolean":
            lowered = expected.strip().casefold()
            if lowered not in {"true", "false"}:
                return None, []
            target = f"TRY_CAST({quoted_col} AS BOOLEAN)" if text_store else quoted_col
            return self._compare_clause(operator, quoted_col, target, "?", text_store), [lowered == "true"]
        if eff in {"date", "datetime"}:
            when = self._temporal_expected(expected, eff)
            if when is None:
                return None, []
            sql_type = "DATE" if eff == "date" else "TIMESTAMP"
            if text_store or eff == "date":
                target = (
                    f"TRY_CAST({quoted_col} AS {sql_type})" if text_store
                    else f"CAST({quoted_col} AS DATE)"
                )
            else:
                target = quoted_col
            return (
                self._compare_clause(operator, quoted_col, target, f"CAST(? AS {sql_type})", text_store),
                [when],
            )
        return None, []

    def _build_sort_sql_clause(self) -> str | None:
        """Return SQL ORDER BY expression for current sort column or None if Python sort needed."""
        if not self._sort_column or self._sort_column not in self._headers:
            return '"__rn" ASC'
        col = self._sort_column
        eff = self._shape(col)
        if eff is None:
            return None
        store_type = self._store_columns.get(col, "text")
        quoted_col = _quote_identifier(col)
        direction = "DESC" if self._sort_direction == "descending" else "ASC"
        null_clause = "NULLS FIRST" if direction == "ASC" else "NULLS LAST"

        if store_type == "text":
            if eff == "text":
                if self._check_non_ascii(col):
                    return None
                return f'{quoted_col} COLLATE NOCASE {direction} {null_clause}, "__rn" ASC'

            # Text store with a typed label: SQL only when every cell is canonical.
            if not self._check_canonical(col):
                return None
            if eff in _NUMERIC_LABELS:
                cast_expr = f"TRY_CAST({quoted_col} AS DECIMAL(38,18))"
            elif eff == "boolean":
                cast_expr = f"TRY_CAST({quoted_col} AS BOOLEAN)"
            elif eff == "date":
                cast_expr = f"TRY_CAST({quoted_col} AS DATE)"
            else:
                cast_expr = f"TRY_CAST({quoted_col} AS TIMESTAMP)"
            if direction == "ASC":
                return (
                    f"CASE WHEN {quoted_col} IS NULL THEN 0 ELSE 1 END ASC, "
                    f"CASE WHEN {quoted_col} = '' THEN 1 ELSE 0 END ASC, "
                    f'{cast_expr} ASC, "__rn" ASC'
                )
            return (
                f"CASE WHEN {quoted_col} IS NULL THEN 1 ELSE 0 END ASC, "
                f"CASE WHEN {quoted_col} = '' THEN 0 ELSE 1 END ASC, "
                f'{cast_expr} DESC, "__rn" ASC'
            )

        # Typed store
        if eff == "date" and store_type == "datetime":
            return f'CAST({quoted_col} AS DATE) {direction} {null_clause}, "__rn" ASC'
        return f'{quoted_col} {direction} {null_clause}, "__rn" ASC'

    # ------------------------------------------------------------------
    # Row-id table (the "view")
    # ------------------------------------------------------------------

    def _build_view(
        self, cancel_event: threading.Event | None = None
    ) -> tuple[str | None, int]:
        """Build the sorted and filtered row-id table for the current attributes.

        Returns (view name or None when the natural order is used, filtered row count).
        Never changes the active view; a failed build leaves no partial table behind.
        """
        if (
            not self._table_name
            or not self._store.has_table(self._table_name)
            or self._total_rows == 0
        ):
            return None, 0

        has_filters = bool(self._column_filters)
        has_sort = bool(self._sort_column and self._sort_column in self._headers)
        if not has_filters and not has_sort:
            return None, self._total_rows

        try:
            built = self._build_view_sql(cancel_event)
        except StoreError as exc:
            if _is_infra_error(exc):
                raise
            # A conversion error in the SQL path: the exact Python path decides instead.
            built = None
        if built is not None:
            return built
        return self._build_view_python(cancel_event)

    def _build_view_sql(
        self, cancel_event: threading.Event | None = None
    ) -> tuple[str, int] | None:
        where_clauses: list[str] = []
        where_params: list[Any] = []
        for col, rule in self._column_filters.items():
            clause, params = self._build_filter_sql_clause(col, rule)
            if clause is None:
                return None
            where_clauses.append(f"({clause})")
            where_params.extend(_norm_param(x) for x in params)

        sort_clause = self._build_sort_sql_clause()
        if sort_clause is None:
            return None

        quoted_tbl = _quote_identifier(self._table_name)
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        select_sql = f'SELECT "__rn" FROM {quoted_tbl} {where_sql} ORDER BY {sort_clause}'

        if cancel_event is not None and cancel_event.is_set():
            raise ImportCancelledError("Operation canceled.")

        view_name = self._next_view_name()
        try:
            self._store.create_view_ids(view_name, select_sql, where_params)
            cnt_row = self._store.execute(
                f"SELECT count(*) FROM {_quote_identifier(view_name)}"
            )
        except BaseException:
            self._drop_quiet(view_name)
            raise
        return view_name, (cnt_row[0][0] if cnt_row else 0)

    def _build_view_python(
        self, cancel_event: threading.Event | None = None
    ) -> tuple[str | None, int]:
        """Stream the table in chunks, apply filters and sort in Python, keep the row ids."""
        needed_cols: list[str] = []
        if self._sort_column and self._sort_column in self._headers:
            needed_cols.append(self._sort_column)
        for col in self._column_filters:
            if col not in needed_cols:
                needed_cols.append(col)

        quoted_tbl = _quote_identifier(self._table_name)
        select_cols = [_quote_identifier(c) for c in needed_cols] + ['"__rn"']
        has_sort = bool(self._sort_column and self._sort_column in self._headers)

        matching_rows: list[tuple[Any, int]] = []
        chunk_size = _PY_CHUNK
        offset = 0

        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise ImportCancelledError("Operation canceled.")
            chunk = self._store.execute(
                f'SELECT {", ".join(select_cols)} FROM {quoted_tbl} '
                f'WHERE "__rn" >= ? AND "__rn" < ? ORDER BY "__rn" ASC',
                [offset, offset + chunk_size],
            )
            if not chunk:
                break

            for r in chunk:
                rn = r[-1]
                row_dict = {needed_cols[i]: r[i] for i in range(len(needed_cols))}
                matches = True
                for col, rule in self._column_filters.items():
                    if not self._matches_column_filter(row_dict.get(col), col, rule):
                        matches = False
                        break
                if matches:
                    key = (
                        self._sort_key(row_dict.get(self._sort_column), self._sort_column)
                        if has_sort else ()
                    )
                    matching_rows.append((key, rn))

            offset += chunk_size
            if len(chunk) < chunk_size:
                break

        if cancel_event is not None and cancel_event.is_set():
            raise ImportCancelledError("Operation canceled.")

        if has_sort:
            matching_rows.sort(
                key=lambda item: item[0], reverse=self._sort_direction == "descending"
            )

        filtered_rns = [item[1] for item in matching_rows]
        view_name = self._next_view_name()
        try:
            self._store.register_arrow_ids(view_name, filtered_rns)
        except BaseException:
            self._drop_quiet(view_name)
            raise
        return view_name, len(filtered_rns)

    def _fetch_page(self, view_name: str | None, filtered_rows: int, page_index: int) -> list[dict[str, Any]]:
        """Fetch the rows of one page; never changes model state."""
        if not self._table_name or filtered_rows == 0:
            return []

        start = page_index * PREVIEW_ROW_LIMIT
        limit = PREVIEW_ROW_LIMIT

        if view_name is not None:
            quoted_tbl = _quote_identifier(self._table_name)
            quoted_view = _quote_identifier(view_name)
            col_selects = [
                f"t.{_quote_identifier(col)} AS {_quote_identifier(col)}"
                for col in self._headers
            ]
            sql = (
                f"SELECT {', '.join(col_selects)} "
                f"FROM {quoted_tbl} t "
                f'JOIN {quoted_view} v ON t."__rn" = v."__rn" '
                f"ORDER BY v.position ASC "
                f"LIMIT ? OFFSET ?"
            )
            tuples = self._store.execute(sql, [limit, start])
        else:
            tuples = self._store.read_page(
                self._table_name, start, limit, columns=self._headers
            )

        return [dict(zip(self._headers, row_tuple)) for row_tuple in tuples]

    def _materialize_state(self, cancel_event: threading.Event | None = None) -> None:
        """Rebuild the row-id table for the current attributes and switch to it.

        Plain attribute switch without a Qt reset: the caller reloads the page. The old
        table is dropped only after the new one exists; on failure nothing changes.
        """
        new_view, count = self._build_view(self._effective_cancel_event(cancel_event))
        old_view = self._active_view_name
        self._active_view_name = new_view
        self._filtered_rows = count
        if old_view != new_view:
            self._drop_quiet(old_view)

    def _load_page_rows(self) -> None:
        """Fetch rows for the current page index into self._rows."""
        self._rows = self._fetch_page(
            self._active_view_name, self._filtered_rows, self._page_index
        )

    # ------------------------------------------------------------------
    # replace_data
    # ------------------------------------------------------------------

    def replace_data(
        self,
        table_name: str,
        headers: list[str] | None = None,
        column_types: dict[str, str] | None = None,
        table_key: str | None = None,
        *,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        """Load data from a store table. Returns True on success, False on StoreError
        (the previous table, sort, filters and page stay as they were)."""
        ev = self._effective_cancel_event(cancel_event)
        if ev is not None and ev.is_set():
            raise ImportCancelledError("Operation canceled.")

        def mutate() -> None:
            new_table_name = str(table_name or "")
            new_table_key = str(table_key or "")

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
            raw_filters = deepcopy(self._filters_by_table.get(new_table_key, {}))
            new_col_filters = {
                column: rule
                for column, rule in raw_filters.items()
                if column in new_headers
            }
            if new_sort_col not in new_headers:
                new_sort_col = ""
                new_sort_dir = ""
                self._sort_by_table.pop(new_table_key, None)

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

        return self._transition(
            mutate, (self.pageChanged, self.sortChanged, self.dataReplaced), ev
        )

    # ------------------------------------------------------------------
    # Paging
    # ------------------------------------------------------------------

    def _set_page(self, page_index: int) -> bool:
        page_count = self.pageCount
        next_index = max(0, min(page_index, max(0, page_count - 1)))
        if next_index == self._page_index:
            return True

        try:
            rows = self._fetch_page(self._active_view_name, self._filtered_rows, next_index)
        except StoreError as exc:
            self._handle_store_error(exc)
            return False

        self.beginResetModel()
        try:
            self._page_index = next_index
            self._rows = rows
        finally:
            self.endResetModel()

        self._last_error = ""
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

    # ------------------------------------------------------------------
    # Sort and filters
    # ------------------------------------------------------------------

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

        def mutate() -> None:
            self._sort_column = column
            self._sort_direction = direction
            if self._table_key:
                self._sort_by_table[self._table_key] = (column, direction)

        self._transition(mutate, (self.pageChanged, self.sortChanged))

    @Property("QVariantList", notify=filterChanged)
    def activeFilterColumns(self) -> list[str]:  # noqa: N802
        return list(self._column_filters)

    @Slot(str, result=bool)
    def isColumnFiltered(self, column: str) -> bool:  # noqa: N802
        return column in self._column_filters

    @Slot(str, result="QVariantMap")
    def columnFilter(self, column: str) -> dict[str, Any]:  # noqa: N802
        return deepcopy(self._column_filters.get(column, {}))

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

        def mutate() -> None:
            self._column_filters[column] = {"operator": operator, "value": value}
            if self._table_key:
                self._filters_by_table[self._table_key] = deepcopy(self._column_filters)

        self._transition(mutate, (self.pageChanged, self.filterChanged))

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

        try:
            present = self._present_keys(
                column, set(keys), self._effective_cancel_event()
            )
        except StoreError as exc:
            self._handle_store_error(exc)
            return
        normalized = sorted(present)
        if all_selected and not normalized:
            self.clearColumnFilter(column)
            return

        def mutate() -> None:
            self._column_filters[column] = {
                "operator": "values",
                "all": bool(all_selected),
                "keys": normalized,
            }
            if self._table_key:
                self._filters_by_table[self._table_key] = deepcopy(self._column_filters)

        self._transition(mutate, (self.pageChanged, self.filterChanged))

    @Slot(str)
    def clearColumnFilter(self, column: str) -> None:  # noqa: N802
        if column not in self._column_filters:
            return

        def mutate() -> None:
            self._column_filters.pop(column, None)
            if self._table_key:
                if self._column_filters:
                    self._filters_by_table[self._table_key] = deepcopy(self._column_filters)
                else:
                    self._filters_by_table.pop(self._table_key, None)

        self._transition(mutate, (self.pageChanged, self.filterChanged))

    def clear(self) -> None:
        self._sort_by_table.clear()
        self._filters_by_table.clear()
        self.replace_data("")

    # ------------------------------------------------------------------
    # Distinct values for the filter pop-up
    # ------------------------------------------------------------------

    def _distinct_expr(self, column: str) -> str:
        """SQL expression whose distinct values correspond one to one to the old filter keys."""
        quoted_col = _quote_identifier(column)
        if (
            self._column_types.get(column) == "date"
            and self._store_columns.get(column) == "datetime"
        ):
            return f"CAST({quoted_col} AS DATE)"
        return quoted_col

    def _filters_signature(self, other_filters: dict[str, dict[str, Any]]) -> str:
        return json.dumps(
            [other_filters, sorted(self._column_types.items()), sorted(self._store_columns.items())],
            sort_keys=True,
            default=str,
        )

    def _cfv_cache_put(self, key: tuple[str, int, str, str], info: dict[str, Any]) -> None:
        if len(self._cfv_cache) >= _CFV_CACHE_MAX and key not in self._cfv_cache:
            self._cfv_cache.clear()
        self._cfv_cache[key] = info

    def _cfv_other_key(self, column: str) -> tuple[str, int, str, str]:
        other = {c: r for c, r in self._column_filters.items() if c != column}
        return (
            self._table_name,
            self._store.table_version(self._table_name),
            column,
            self._filters_signature(other),
        )

    @Slot(str, result=bool)
    def columnFilterValuesTruncated(self, column: str) -> bool:  # noqa: N802
        return bool(self._cfv_summary(column).get("truncated", False))

    @Slot(str, result=int)
    def columnFilterValueTotal(self, column: str) -> int:  # noqa: N802
        return int(self._cfv_summary(column).get("totalCount", 0))

    def _cfv_summary(self, column: str) -> dict[str, Any]:
        if column not in self._headers or not self._table_name:
            return {}
        try:
            key = self._cfv_other_key(column)
        except StoreError as exc:
            self._handle_store_error(exc)
            return {}
        info = self._cfv_cache.get(key)
        if info is not None and "summary" in info:
            return info["summary"]
        result = self.columnFilterValues(column, "")
        info = self._cfv_cache.get(key)
        if info is not None and "summary" in info:
            return info["summary"]
        return result

    def _remember_summary(self, key: tuple[str, int, str, str], result: dict[str, Any]) -> None:
        info = self._cfv_cache.setdefault(key, {})
        info["summary"] = {
            "truncated": result["truncated"],
            "totalCount": result["totalCount"],
        }
        self._cfv_cache_put(key, info)

    def _labels_for(self, raw_values: Any, column: str) -> dict[str, str]:
        distinct: dict[str, str] = {}
        for raw_value in raw_values:
            key = self._encode_filter_value(raw_value, column)
            distinct[key] = self._filter_value_label(raw_value, key, column)
        return _disambiguate_data_view_filter_labels(distinct)

    @staticmethod
    def _small_result(
        labels: dict[str, str], query: str, total: int
    ) -> dict[str, Any]:
        matched = [
            (key, label) for key, label in labels.items()
            if not query or query in label.casefold()
        ]
        matched.sort(key=lambda item: (item[1].casefold(), item[1], item[0]))
        return {
            "values": [
                {"key": key, "label": label}
                for key, label in matched[:_CFV_RETURN_LIMIT]
            ],
            "matchCount": len(matched),
            "totalCount": total,
            "truncated": len(matched) > _CFV_RETURN_LIMIT,
        }

    @Slot(str, result="QVariantMap")
    @Slot(str, str, result="QVariantMap")
    def columnFilterValues(self, column: str, search: str = "") -> dict[str, Any]:  # noqa: N802
        """Search distinct filter values in the domain after other-column filters.

        Up to 5,000 distinct values the answer is exactly the old model's. Above that see
        the module docstring.
        """
        empty_res = {"values": [], "matchCount": 0, "totalCount": 0, "truncated": False}
        if column not in self._headers or not self._table_name:
            return empty_res

        query = (search or "").strip().casefold()
        try:
            if not self._store.has_table(self._table_name):
                return empty_res
            other_filters = {
                c: r for c, r in self._column_filters.items() if c != column
            }
            key = self._cfv_other_key(column)

            where_clauses: list[str] = []
            where_params: list[Any] = []
            can_sql = True
            for c, rule in other_filters.items():
                clause, params = self._build_filter_sql_clause(c, rule)
                if clause is None:
                    can_sql = False
                    break
                where_clauses.append(f"({clause})")
                where_params.extend(_norm_param(x) for x in params)

            if can_sql:
                try:
                    result = self._cfv_sql(column, query, key, where_clauses, where_params)
                except StoreError as exc:
                    if _is_infra_error(exc):
                        raise
                    result = None
                if result is not None:
                    if not query:
                        self._remember_summary(key, result)
                    return result
            result = self._cfv_scan(column, query, other_filters)
            if not query:
                self._remember_summary(key, result)
            return result
        except StoreError as exc:
            self._handle_store_error(exc)
            return empty_res

    def _cfv_sql(
        self,
        column: str,
        query: str,
        key: tuple[str, int, str, str],
        where_clauses: list[str],
        where_params: list[Any],
    ) -> dict[str, Any]:
        quoted_tbl = _quote_identifier(self._table_name)
        dexpr = self._distinct_expr(column)
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        info = self._cfv_cache.setdefault(key, {})

        if "small" not in info:
            cnt_res = self._store.execute(
                f"SELECT count(*) FROM (SELECT DISTINCT {dexpr} FROM {quoted_tbl} {where_sql} "
                f"LIMIT {_CFV_SMALL_LIMIT + 1})",
                where_params,
            )
            info["small"] = (cnt_res[0][0] if cnt_res else 0) <= _CFV_SMALL_LIMIT
            self._cfv_cache_put(key, info)

        if info["small"]:
            if "labels" not in info:
                dist_rows = self._store.execute(
                    f'SELECT {dexpr} FROM {quoted_tbl} {where_sql} GROUP BY {dexpr} ORDER BY min("__rn")',
                    where_params,
                )
                info["labels"] = self._labels_for((r[0] for r in dist_rows), column)
                self._cfv_cache_put(key, info)
            return self._small_result(info["labels"], query, len(info["labels"]))

        return self._cfv_large(column, query, key, info, where_clauses, where_params)

    def _cfv_total_distinct(
        self, column: str, info: dict[str, Any], where_sql: str, where_params: list[Any]
    ) -> int:
        if "total" not in info:
            quoted_col = _quote_identifier(column)
            dexpr = self._distinct_expr(column)
            res = self._store.execute(
                f"SELECT count(DISTINCT {dexpr}) + "
                f"CASE WHEN bool_or({quoted_col} IS NULL) THEN 1 ELSE 0 END "
                f"FROM {_quote_identifier(self._table_name)} {where_sql}",
                where_params,
            )
            info["total"] = int(res[0][0]) if res and res[0][0] is not None else 0
        return info["total"]

    def _cfv_large(
        self,
        column: str,
        query: str,
        key: tuple[str, int, str, str],
        info: dict[str, Any],
        where_clauses: list[str],
        where_params: list[Any],
    ) -> dict[str, Any]:
        """More than 5,000 distinct values: search all of them, return up to 2,000 matches."""
        quoted_tbl = _quote_identifier(self._table_name)
        quoted_col = _quote_identifier(column)
        dexpr = self._distinct_expr(column)
        store_type = self._store_columns.get(column, "text")

        predicate = ""
        pred_params: list[Any] = []
        sql_search = False
        if query:
            sql_search = (
                store_type == "text" and query.isascii() and not self._check_non_ascii(column)
            )
            if sql_search:
                label_expr = (
                    f"(CASE WHEN {quoted_col} IS NULL THEN '(Null)' "
                    f"WHEN {quoted_col} = '' THEN '(Empty text)' ELSE {quoted_col} END)"
                )
                predicate = f"lower({label_expr}) LIKE ? ESCAPE ?"
                pred_params = [f"%{_escape_like(query)}%", "\\"]

        if not query or sql_search:
            all_where = list(where_clauses) + ([predicate] if predicate else [])
            where_sql = f"WHERE {' AND '.join(all_where)}" if all_where else ""
            rows = self._store.execute(
                f'SELECT {dexpr} AS v, min("__rn") AS m, count(*) OVER () AS c '
                f"FROM {quoted_tbl} {where_sql} GROUP BY {dexpr} ORDER BY m LIMIT {_CFV_RETURN_LIMIT}",
                list(where_params) + pred_params,
            )
            match_count = int(rows[0][2]) if rows else 0
            raw_values = [r[0] for r in rows]
            if not query:
                info["total"] = match_count
            total = self._cfv_total_distinct(
                column, info, f"WHERE {' AND '.join(where_clauses)}" if where_clauses else "",
                where_params,
            )
        else:
            raw_values, match_count, total = self._cfv_python_search(
                column, query, where_clauses, where_params
            )
            info["total"] = total
        self._cfv_cache_put(key, info)

        labels = self._labels_for(raw_values, column)
        matched = sorted(labels.items(), key=lambda item: (item[1].casefold(), item[1], item[0]))
        return {
            "values": [{"key": k, "label": label} for k, label in matched],
            "matchCount": min(match_count, _CFV_COUNT_CAP),
            "matchCountCapped": match_count > _CFV_COUNT_CAP,
            "totalCount": total,
            "truncated": match_count > _CFV_RETURN_LIMIT,
        }

    def _cfv_python_search(
        self,
        column: str,
        query: str,
        where_clauses: list[str],
        where_params: list[Any],
    ) -> tuple[list[Any], int, int]:
        """Exact search over all distinct values in chunks; returns (first matches, count, total)."""
        quoted_tbl = _quote_identifier(self._table_name)
        dexpr = self._distinct_expr(column)
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        view = self._next_view_name()
        self._store.create_view_ids(
            view,
            f'SELECT min("__rn") AS "__rn" FROM {quoted_tbl} {where_sql} '
            f'GROUP BY {dexpr} ORDER BY min("__rn")',
            where_params,
        )
        try:
            quoted_view = _quote_identifier(view)
            cnt = self._store.execute(f"SELECT count(*) FROM {quoted_view}")
            total = int(cnt[0][0]) if cnt else 0
            tdexpr = dexpr.replace(_quote_identifier(column), f"t.{_quote_identifier(column)}")
            ev = self._effective_cancel_event()
            first: list[Any] = []
            matches = 0
            offset = 0
            while offset < total and matches <= _CFV_COUNT_CAP:
                if ev is not None and ev.is_set():
                    raise ImportCancelledError("Operation canceled.")
                chunk = self._store.execute(
                    f"SELECT {tdexpr} FROM {quoted_tbl} t "
                    f'JOIN {quoted_view} v ON t."__rn" = v."__rn" '
                    f"WHERE v.position >= ? AND v.position < ? ORDER BY v.position",
                    [offset, offset + _CFV_PY_CHUNK],
                )
                if not chunk:
                    break
                for (raw_value,) in chunk:
                    k = self._encode_filter_value(raw_value, column)
                    label = self._filter_value_label(raw_value, k, column)
                    if query in label.casefold():
                        matches += 1
                        if len(first) < _CFV_RETURN_LIMIT:
                            first.append(raw_value)
                offset += _CFV_PY_CHUNK
            return first, matches, total
        finally:
            self._drop_quiet(view)

    def _cfv_scan(
        self, column: str, query: str, other_filters: dict[str, dict[str, Any]]
    ) -> dict[str, Any]:
        """Exact full scan (other filters that need Python): same as the old model."""
        distinct: dict[str, str] = {}
        offset = 0
        cols_needed = list(other_filters.keys()) + ([column] if column not in other_filters else [])
        while True:
            chunk = self._store.read_page(
                self._table_name, offset, _CFV_PY_CHUNK, columns=cols_needed
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
                    distinct[key] = self._filter_value_label(raw_value, key, column)
            offset += len(chunk)

        labels = _disambiguate_data_view_filter_labels(distinct)
        return self._small_result(labels, query, len(distinct))

    # ------------------------------------------------------------------
    # Qt model interface
    # ------------------------------------------------------------------

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
