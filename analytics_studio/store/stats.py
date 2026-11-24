"""Per-column and per-table size statistics for a store table.

Qt-free. Uses only the public DuckStore methods columns(), row_count() and
execute(). One SQL query per column so that cancel and progress work between
columns. Warnings are plain text and never block anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Optional
import threading

from analytics_studio.file_import import ImportCancelledError

# Thresholds are module constants so tests can lower them.
_UNIQUE_MIN_ROWS = 100_000
_UNIQUE_RATIO_PERCENT = 90          # distinct >= 90% of rows
_LONG_TEXT_CHARS = 1_000
_EMPTY_MIN_ROWS = 1_000
_EMPTY_PERCENT = 95                 # (NULL + '') cells >= 95% of rows
_WIDE_COLUMNS = 100                 # warn when columns > 100
_LARGE_TABLE_BYTES = 2 * 1024 ** 3  # 2 GiB

_FIXED_BYTES = 16
_EIGHT_BYTE_LABELS = ("whole", "decimal", "datetime")


@dataclass(frozen=True)
class ColumnStat:
    name: str
    label: str
    stored_type: str
    rows: int
    null_count: int
    empty_count: int
    distinct_approx: int  # exact for text columns, approximate otherwise
    max_chars: int
    avg_chars: float
    approx_bytes: int
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class TableStats:
    table: str
    rows: int
    columns: tuple[ColumnStat, ...]
    approx_bytes: int
    warnings: tuple[str, ...]


def _quote(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _label_for(index: int, name: str, column_types) -> str:
    if isinstance(column_types, Mapping):
        label = column_types.get(name)
    else:
        label = column_types[index] if index < len(column_types) else None
    return label if label else "text"


def _column_sql(table: str, name: str, stored_type: str, label: str = "text") -> str:
    q = _quote(name)
    if stored_type == "text":
        empty_part = f"COUNT(*) FILTER (WHERE {q} = ''), "
    else:
        empty_part = "0, "  # '' is not a valid non-text value, never compare

    if label == "text" and stored_type == "text":
        # memory: about 130 bytes per distinct text value; a 30M-row unique text column peaked at 4 GB in review
        distinct_part = f"count(DISTINCT {q}), "
    else:
        distinct_part = f"approx_count_distinct({q}), "

    base = (
        f"COUNT(*) FILTER (WHERE {q} IS NULL), "
        f"{empty_part}"
        f"{distinct_part}"
    )
    if stored_type == "text":
        extra = (
            f"COALESCE(MAX(length({q})), 0), "
            f"COALESCE(AVG(length({q})), 0), "
            f"COALESCE(SUM(strlen({q})), 0)"
        )
    else:
        extra = "0, 0.0, 0"
    return f"SELECT {base}{extra} FROM {_quote(table)}"


def _column_warnings(label: str, stored_type: str, name: str, rows: int,
                     null_count: int, empty_count: int, distinct: int,
                     max_chars: int) -> tuple[str, ...]:
    out: list[str] = []
    if rows <= 0:
        return ()
    if (label == "text" and stored_type == "text"
            and rows >= _UNIQUE_MIN_ROWS
            and distinct * 100 >= rows * _UNIQUE_RATIO_PERCENT):
        out.append(
            f"Column '{name}' holds mostly unique text (about {distinct:,} distinct values "
            f"in {rows:,} rows). Filters, grouping and visuals on it are slow and use a lot of memory."
        )
    if stored_type == "text" and max_chars >= _LONG_TEXT_CHARS:
        out.append(f"Column '{name}' has cells up to {max_chars} characters long.")
    empty = null_count + empty_count
    if rows >= _EMPTY_MIN_ROWS and empty * 100 >= rows * _EMPTY_PERCENT:
        pct = (200 * empty + rows) // (2 * rows)  # round half up
        out.append(f"Column '{name}' is almost empty ({pct}% of cells are empty).")
    return tuple(out)


def compute_table_stats(store, table: str, column_types, *,
                        cancel_event: Optional[threading.Event] = None,
                        progress: Optional[Callable[[str], None]] = None) -> TableStats:
    """Measure every column of ``table`` in ``store``.

    ``column_types`` is a mapping of column name to label, or a sequence of
    labels in column order. A column without a label is treated as "text".
    """
    cols = [
        (name, stored) for name, stored in store.columns(table)
        if name.lower() != "__rn"
    ]
    rows = store.row_count(table)
    n = len(cols)

    stats: list[ColumnStat] = []
    for i, (name, stored_type) in enumerate(cols):
        if cancel_event is not None and cancel_event.is_set():
            raise ImportCancelledError("Import canceled.")
        if progress is not None:
            progress(f"Measuring column {i + 1} of {n}: {name}")

        label = _label_for(i, name, column_types)
        result = store.execute(_column_sql(table, name, stored_type, label), [])
        null_count, empty_count, distinct, max_chars, avg_chars, octets = result[0]
        if stored_type != "text":
            empty_count = 0
        distinct = min(int(distinct or 0), rows)
        max_chars = int(max_chars or 0)
        avg_chars = float(avg_chars or 0.0)
        null_count = int(null_count or 0)
        empty_count = int(empty_count or 0)

        if stored_type == "text":
            approx_bytes = int(octets or 0)
        elif stored_type in _EIGHT_BYTE_LABELS:
            approx_bytes = 8 * rows
        elif stored_type == "fixed":
            approx_bytes = _FIXED_BYTES * rows
        elif stored_type == "boolean":
            approx_bytes = rows
        else:
            approx_bytes = 0

        stats.append(ColumnStat(
            name=name,
            label=label,
            stored_type=stored_type,
            rows=rows,
            null_count=null_count,
            empty_count=empty_count,
            distinct_approx=distinct,
            max_chars=max_chars,
            avg_chars=avg_chars,
            approx_bytes=approx_bytes,
            warnings=_column_warnings(label, stored_type, name, rows,
                                      null_count, empty_count, distinct, max_chars),
        ))

    total_bytes = sum(s.approx_bytes for s in stats)
    table_warnings: list[str] = []
    if rows > 0 and n > _WIDE_COLUMNS:
        table_warnings.append(
            f"The table has {n} columns. Wide tables use much more memory; "
            f"keep only the columns you need."
        )
    if rows > 0 and total_bytes >= _LARGE_TABLE_BYTES:
        gb = total_bytes / (1024 ** 3)
        table_warnings.append(
            f"The table needs about {gb:.1f} GB in the store. "
            f"Importing it again with fewer columns is faster."
        )

    return TableStats(
        table=table,
        rows=rows,
        columns=tuple(stats),
        approx_bytes=total_bytes,
        warnings=tuple(table_warnings),
    )
