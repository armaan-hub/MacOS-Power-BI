"""Column type detection for all-text DuckStore tables (Stage B3a).

``detect_column_types`` returns exactly what the old
``analytics_studio.transformations.infer_column_types(headers, rows)`` returns
for the same rows, without loading the whole table into Python.

Why this is exact. Every whole-column condition in the old function is either
"all values satisfy X" (ISO date/datetime/time parsing, numeric parsing,
whole-number check, boolean check, conversion-error count == 0) or "any value
is Y" (long-integer / leading-zero identifier check). Those conditions depend
only on the SET of non-blank values. The candidate type is chosen from the
sample (first ``sample_size`` rows) only, plus the date-to-datetime upgrade
that is again an "all values" test.

Monotone shortcut. If the candidate computed from the sample alone is
"text", the full column is "text" too. Every sample-only condition that can
reject a type is an "all" test over a subset of the full column, so it still
fails on the full column; every "any" test that can force text (identifier
patterns) only becomes more likely to fire on the full column. Checked by the
differential suite in test_type_detect.py.

Distinct shortcut. Otherwise the candidate is re-checked against the full
column. The old function only needs the set of non-blank values, so we feed
``first + distinct``. The sample rows stay first, so the sample is unchanged.
Duplicates of sample values among the distinct values do not change any "all"
or "any" test, and ``count == 0`` is also a set property.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from analytics_studio.file_import import ImportCancelledError
from analytics_studio.store.base import StoreError
from analytics_studio.transformations import infer_column_types

_DISTINCT_CHUNK = 100_000


def _quote(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _resolve_table(store: Any, table: str) -> str:
    names = store.table_names()
    if table in names:
        return table
    lowered = table.casefold()
    for name in names:
        if name.casefold() == lowered:
            return name
    raise StoreError(f"Table '{table}' does not exist.")


def _check_cancel(cancel_event: Optional[threading.Event]) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ImportCancelledError("Import canceled.")


def detect_column_types(
    store: Any,
    table: str,
    *,
    sample_size: int = 200,
    cancel_event: Optional[threading.Event] = None,
    progress: Optional[Callable[[str], None]] = None,
    max_distinct_values: int = 5_000_000,
) -> dict[str, str]:
    """Return {column: model type} for an all-text store table.

    Result equals ``infer_column_types(headers, rows, sample_size=sample_size)``
    for the same rows. Column order follows the table.
    """
    if not isinstance(sample_size, int) or isinstance(sample_size, bool) or sample_size < 1:
        raise ValueError("A type-detection sample must contain at least one row.")
    stored_name = _resolve_table(store, table)
    columns = store.columns(stored_name)
    for name, type_name in columns:
        if type_name != "text":
            raise StoreError(
                f"Column '{name}' in table '{stored_name}' has type '{type_name}', "
                "not 'text'; detect_column_types needs an all-text table."
            )
    quoted_table = _quote(stored_name)
    total = len(columns)
    result: dict[str, str] = {}
    for index, (header, _) in enumerate(columns, 1):
        _check_cancel(cancel_event)
        quoted = _quote(header)
        first_rows = store.execute(
            f'SELECT {quoted} FROM {quoted_table} ORDER BY "__rn" LIMIT ?',
            [sample_size],
        )
        first = [row[0] for row in first_rows]
        # Blank cells (NULL or '') are passed exactly as stored; the old function filters them.
        decided = infer_column_types(
            [header], [{header: value} for value in first], sample_size=sample_size
        )[header]
        if decided == "text" or len(first) < sample_size:
            # Text is final (monotone argument above). If fewer rows than the
            # sample exist, ``first`` is the whole column and is already exact.
            result[header] = decided
            if progress is not None:
                progress(f"Detected types for column {index} of {total}...")
            continue

        distinct: list[Any] = []
        cap = max_distinct_values + 1
        distinct_rows = store.execute(
            f"SELECT DISTINCT {quoted} FROM {quoted_table} "
            f"WHERE {quoted} IS NOT NULL AND {quoted} <> '' LIMIT ?",
            [cap],
        )
        # Values from the store, one chunk at a time, so a cancel is seen between chunks.
        for start in range(0, len(distinct_rows), _DISTINCT_CHUNK):
            _check_cancel(cancel_event)
            distinct.extend(row[0] for row in distinct_rows[start:start + _DISTINCT_CHUNK])
        if len(distinct) > max_distinct_values:
            raise ValueError(
                f"Column '{header}' has more than {max_distinct_values} distinct values; "
                "type detection on this column is not supported yet"
            )
        del distinct_rows
        full_rows = [{header: value} for value in first]
        full_rows.extend({header: value} for value in distinct)
        result[header] = infer_column_types(
            [header], full_rows, sample_size=sample_size
        )[header]
        if progress is not None:
            progress(f"Detected types for column {index} of {total}...")
    return result
