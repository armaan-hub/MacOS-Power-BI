"""Parquet source reader for the DuckDB store (Stage B2, Parquet step 1).

``plan_parquet`` inspects a flat Parquet file and decides the normalised
headers, the store column types and the declared row count.  ``iter_parquet_batches``
streams the same file as Arrow record batches that are already in the exact
Arrow types the store inserts:

=====================  ====================  ======================================
store type             Arrow type yielded    source Arrow types
=====================  ====================  ======================================
``boolean``            ``bool_()``           boolean
``whole``              ``int64()``           int8..int64, uint8..uint64 (<= 2**63-1)
``decimal``            ``float64()``         float16/32/64 (finite only)
``fixed``              ``decimal128(19, 4)`` decimal (precision-scale <= 15, scale <= 4)
``datetime``           ``timestamp("us")``   date32/64, timestamp w/o tz (yr 1..9999)
``text``               ``string()``          string, large_string, null, dictionary
=====================  ====================  ======================================

Type mapping details and design limits:
- ``null`` type source columns map to ``text`` (containing all nulls).
- ``fixed`` columns require ``scale <= 4`` and ``precision - scale <= 15``. Decimals
  with scale > 4 or integer digits > 15 are refused on purpose: the store has one
  fixed type DECIMAL(19,4); this is a known design limit (the old in-memory importer
  accepted wider decimals).
- ``uint64`` values above ``2**63 - 1`` are refused.
- Sub-microsecond ``timestamp[ns]`` values that cannot be converted without loss or
  overflow are refused.
- Dates and timestamps outside years 1 to 9999 are refused.
- Row groups: files with more than 100,000 row groups are refused (inherited from
  the old importer).
- Time-of-day (time32/time64) and timezone-aware timestamps are refused.

Limits, messages and refusals are shared with the old importer by importing
them from ``analytics_studio.file_import`` (imported, never copied).  The
store path drops the old 100,000-row and 500,000-cell limits (the caller
applies its own ``max_rows``), and - because it streams one batch at a time
instead of holding every row in memory - it replaces the old total
uncompressed-size budget with a per-row-group budget of at most
``max_row_group_bytes`` (default 1 GiB).  Every other old check is kept.  All
value conversion happens inside Arrow (``pyarrow.compute`` / ``cast``) - never
in a Python loop over rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any, Callable, Iterator, Mapping, Optional

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from analytics_studio.file_import import (
    FileImportError,
    ImportCancelledError,
    MAX_CELLS,
    MAX_COLUMNS,
    MAX_DATA_ROWS,
    MAX_SOURCE_BYTES,
    _check_column_limit,
    _normalize_headers,
    normalize_options,
)

_MAX_INT64 = 2**63 - 1

# Store type -> the Arrow type the store inserts without per-value Python work.
_TARGET_TYPES: dict[str, pa.DataType] = {
    "boolean": pa.bool_(),
    "whole": pa.int64(),
    "decimal": pa.float64(),
    "fixed": pa.decimal128(19, 4),
    "datetime": pa.timestamp("us"),
    "text": pa.string(),
}

# Source types the old parser accepts before its own finer checks.
_SUPPORTED_SOURCE_TYPES = (
    pa.types.is_null,
    pa.types.is_boolean,
    pa.types.is_integer,
    pa.types.is_floating,
    pa.types.is_decimal,
    pa.types.is_string,
    pa.types.is_large_string,
    pa.types.is_date,
    pa.types.is_time,
    pa.types.is_timestamp,
)

_FIXED_SCALE_LIMIT = 4
_FIXED_INTEGER_DIGITS = 15

# Date and timestamp bounds corresponding to Python datetime range (year 1 to 9999)
_DATE32_MIN = -719162
_DATE32_MAX = 2932896
_DATE64_MIN = -62135596800000
_DATE64_MAX = 253402300799999
_TS_BOUNDS = {
    "s": (-62135596800, 253402300799),
    "ms": (-62135596800000, 253402300799999),
    "us": (-62135596800000000, 253402300799999999),
    "ns": (-62135596800000000000, 253402300799999999000),
}


@dataclass
class ParquetPlan:
    """Headers, store types and declared rows for one Parquet file."""

    headers: list[str]
    column_types: list[str]
    row_count: int
    notices: list[str]


def _check_cancel(cancel_event: Optional[threading.Event]) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ImportCancelledError("Import canceled.")


def _store_type_for(source_type: pa.DataType, header: str) -> Optional[str]:
    """Map one source Arrow type to a store type, or None if unsupported."""
    if (
        pa.types.is_null(source_type)
        or pa.types.is_string(source_type)
        or pa.types.is_large_string(source_type)
    ):
        return "text"
    if pa.types.is_boolean(source_type):
        return "boolean"
    if pa.types.is_integer(source_type):
        return "whole"
    if pa.types.is_floating(source_type):
        return "decimal"
    if pa.types.is_decimal(source_type):
        precision = source_type.precision
        scale = source_type.scale
        if scale <= _FIXED_SCALE_LIMIT and (precision - scale) <= _FIXED_INTEGER_DIGITS:
            return "fixed"
        raise FileImportError(
            f"Parquet decimal column {header!r} (decimal({precision},{scale})) "
            "does not fit the 4-decimal fixed type"
        )
    if pa.types.is_date(source_type):
        return "datetime"
    if pa.types.is_timestamp(source_type):
        if source_type.tz is not None:
            raise FileImportError(
                f"Parquet column {header!r} has a time zone; remove the time zone "
                "before importing"
            )
        return "datetime"
    if pa.types.is_time(source_type):
        raise FileImportError(
            f"Parquet column {header!r} has a time-of-day type that the large-table "
            "store does not support yet"
        )
    return None


def _unsupported_type_message(header: str, source_type: pa.DataType) -> str:
    return (
        f"Parquet column {header!r} has unsupported type {source_type}. "
        "Supported columns must contain scalar values; nested and binary types "
        "are not supported."
    )


def plan_parquet(
    path: str | Path,
    options: Mapping[str, Any] | None = None,
    *,
    cancel_event: threading.Event | None = None,
    max_row_group_bytes: int = 1_073_741_824,
) -> ParquetPlan:
    """Validate a Parquet file and decide its headers, store types and rows.

    ``max_row_group_bytes`` caps one row group's uncompressed size: the store
    import reads a row group at a time, so a single oversized group is the only
    size that matters here (the old importer's whole-file budget does not).
    """
    source_path = Path(path)
    normalize_options("parquet", options)
    parquet_file = None
    try:
        parquet_file = pq.ParquetFile(
            source_path,
            thrift_string_size_limit=MAX_SOURCE_BYTES,
            thrift_container_size_limit=MAX_CELLS,
        )
        metadata = parquet_file.metadata
        if metadata is None:
            raise FileImportError(f"{source_path.name} has no readable Parquet metadata.")

        declared_rows = int(metadata.num_rows)
        if declared_rows < 0:
            raise FileImportError(f"{source_path.name} has invalid Parquet row metadata.")
        if metadata.num_row_groups > MAX_DATA_ROWS:
            raise FileImportError(
                f"{source_path.name} contains more than {MAX_DATA_ROWS:,} Parquet row groups."
            )

        schema = parquet_file.schema_arrow
        raw_headers = list(schema.names)
        _check_column_limit(len(raw_headers))
        if not raw_headers:
            raise FileImportError("Parquet import requires at least one column.")
        headers = _normalize_headers(raw_headers, len(raw_headers))

        # One row group at a time, so only a single oversized group is refused.
        # (The old whole-file uncompressed budget and converted-text budget are
        # memory guards for the in-memory importer and do not apply here.)
        for group_index in range(metadata.num_row_groups):
            _check_cancel(cancel_event)
            group_bytes = int(metadata.row_group(group_index).total_byte_size)
            if group_bytes < 0:
                raise FileImportError(
                    f"{source_path.name} has invalid Parquet row-group metadata."
                )
            if group_bytes > max_row_group_bytes:
                raise FileImportError(
                    f"{source_path.name} has a Parquet row group larger than "
                    f"{max_row_group_bytes // (1024 * 1024)} MiB; the store import "
                    "reads one row group at a time."
                )

        column_types: list[str] = []
        for index, field in enumerate(schema):
            source_type = field.type
            decision_type = (
                source_type.value_type if pa.types.is_dictionary(source_type) else source_type
            )
            if not any(is_type(decision_type) for is_type in _SUPPORTED_SOURCE_TYPES):
                raise FileImportError(_unsupported_type_message(headers[index], source_type))
            store_type = _store_type_for(decision_type, headers[index])
            if store_type is None:
                raise FileImportError(_unsupported_type_message(headers[index], source_type))
            column_types.append(store_type)

        notices = [
            "Parquet scalar values are converted to the store's column types; "
            "nested, binary, time-zone and time-of-day values are not supported."
        ]
        return ParquetPlan(
            headers=headers,
            column_types=column_types,
            row_count=declared_rows,
            notices=notices,
        )
    except FileImportError:
        raise
    except Exception as exc:
        raise FileImportError(
            f"Could not read {source_path.name} as Parquet: {exc}"
        ) from exc
    finally:
        if parquet_file is not None:
            parquet_file.close()


def _cast(array: pa.Array, target: pa.DataType, header: str) -> pa.Array:
    try:
        return pc.cast(array, target, safe=True)
    except (pa.ArrowException, OverflowError, ValueError) as exc:
        raise FileImportError(
            f"Parquet column {header!r} cannot be converted to the {target} type: {exc}"
        ) from exc


def _check_uint64_range(array: pa.Array, header: str, row_offset: int) -> None:
    """Refuse uint64 values above the signed 64-bit maximum, one batch at a time."""
    highest = pc.max(array).as_py()
    if highest is None or highest <= _MAX_INT64:
        return
    offenders = pc.indices_nonzero(
        pc.greater(array, pa.scalar(_MAX_INT64, pa.uint64()))
    )
    row_number = row_offset + int(offenders[0].as_py()) + 1
    raise FileImportError(
        f"Parquet column {header!r} contains a value above {_MAX_INT64} "
        f"at row {row_number:,}."
    )


def _check_finite(array: pa.Array, header: str) -> None:
    """Refuse NaN and infinity with the old importer's message."""
    bad = pc.fill_null(pc.or_(pc.is_nan(array), pc.is_inf(array)), False)
    if pc.any(bad).as_py():
        raise FileImportError(
            f"Parquet column {header!r} contains a non-finite number."
        )


def _check_datetime_range(array: pa.Array, header: str, row_offset: int) -> None:
    """Refuse dates and timestamps outside years 1 to 9999."""
    src_type = array.type
    if pa.types.is_date32(src_type):
        min_bound, max_bound = _DATE32_MIN, _DATE32_MAX
        int_arr = array.cast(pa.int32())
    elif pa.types.is_date64(src_type):
        min_bound, max_bound = _DATE64_MIN, _DATE64_MAX
        int_arr = array.cast(pa.int64())
    elif pa.types.is_timestamp(src_type):
        bounds = _TS_BOUNDS.get(src_type.unit)
        if bounds is None:
            return
        min_bound, max_bound = bounds
        int_arr = array.cast(pa.int64())
    else:
        return

    stats = pc.min_max(int_arr).as_py()
    cur_min = stats["min"]
    cur_max = stats["max"]
    if cur_min is None:
        return
    if cur_min < min_bound or cur_max > max_bound:
        bad = pc.fill_null(
            pc.or_(pc.less(int_arr, min_bound), pc.greater(int_arr, max_bound)),
            False,
        )
        offenders = pc.indices_nonzero(bad)
        row_number = row_offset + int(offenders[0].as_py()) + 1
        raise FileImportError(
            f"Parquet column {header!r} contains a date/timestamp outside years 1 to 9999 "
            f"at row {row_number:,}."
        )


def _convert_column(
    array: pa.Array,
    store_type: str,
    header: str,
    row_offset: int,
) -> pa.Array:
    """Convert one source column to its store Arrow type (no Python value loops)."""
    if pa.types.is_dictionary(array.type):
        array = array.dictionary_decode()
    target = _TARGET_TYPES[store_type]
    if store_type == "whole" and pa.types.is_uint64(array.type):
        _check_uint64_range(array, header, row_offset)
    if store_type == "datetime":
        _check_datetime_range(array, header, row_offset)
    if array.type != target:
        if store_type == "datetime" and pa.types.is_timestamp(array.type):
            try:
                array = pc.cast(array, target, safe=True)
            except (pa.ArrowException, OverflowError, ValueError) as exc:
                raise FileImportError(
                    f"Parquet column {header!r} has a timestamp value that does not "
                    "fit microsecond precision."
                ) from exc
        else:
            array = _cast(array, target, header)
    if store_type == "decimal":
        _check_finite(array, header)
    return array


def iter_parquet_batches(
    path: str | Path,
    plan: ParquetPlan,
    *,
    cancel_event: threading.Event | None = None,
    progress: Optional[Callable[[str], None]] = None,
    batch_size: int = 50_000,
) -> Iterator[pa.RecordBatch]:
    """Yield the file as Arrow batches typed for the store, then check the total."""
    source_path = Path(path)
    headers = list(plan.headers)
    column_types = list(plan.column_types)
    if len(headers) != len(column_types):
        raise FileImportError("The Parquet plan has mismatched headers and column types.")
    # A plan can be built by hand, so hold it to the shared column budget too.
    if len(headers) > MAX_COLUMNS:
        raise FileImportError(f"The file exceeds the {MAX_COLUMNS}-column import limit.")
    parquet_file = None
    try:
        parquet_file = pq.ParquetFile(
            source_path,
            thrift_string_size_limit=MAX_SOURCE_BYTES,
            thrift_container_size_limit=MAX_CELLS,
        )
        yielded = 0
        for batch in parquet_file.iter_batches(batch_size=batch_size, use_threads=False):
            _check_cancel(cancel_event)
            if batch.num_columns != len(headers):
                raise FileImportError(
                    f"{source_path.name} has inconsistent Parquet batch columns."
                )
            arrays = [
                _convert_column(
                    batch.column(index), column_types[index], headers[index], yielded
                )
                for index in range(len(headers))
            ]
            record = pa.RecordBatch.from_arrays(arrays, names=headers)
            yielded += record.num_rows
            if progress is not None:
                progress(f"Read {yielded:,} Parquet rows…")
            yield record
        if yielded != int(plan.row_count):
            raise FileImportError(
                f"{source_path.name} declares {int(plan.row_count):,} rows "
                f"but yielded {yielded:,}."
            )
    except FileImportError:
        raise
    except Exception as exc:
        raise FileImportError(
            f"Could not read {source_path.name} as Parquet: {exc}"
        ) from exc
    finally:
        if parquet_file is not None:
            parquet_file.close()
