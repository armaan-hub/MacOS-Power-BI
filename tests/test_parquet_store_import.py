"""Tests for import_parquet_to_store: streaming Parquet import into DuckStore."""

from __future__ import annotations

import datetime
from decimal import Decimal
from pathlib import Path
import threading

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from analytics_studio.file_import import (
    FileImportError,
    ImportCancelledError,
    _parse_parquet,
    default_options,
)
from analytics_studio.store import DuckStore, StoreError, import_parquet_to_store


def write_parquet(tmp_path: Path, name: str, table: pa.Table, **kwargs) -> Path:
    path = Path(tmp_path) / name
    pq.write_table(table, path, **kwargs)
    return path


def test_end_to_end_all_types_vs_old_parser(tmp_path: Path):
    d_val = datetime.date(2023, 5, 17)
    dt_val = datetime.datetime(2023, 11, 14, 22, 13, 20)
    table = pa.table(
        {
            "b": pa.array([True, False, None], type=pa.bool_()),
            "w": pa.array([123, -456, None], type=pa.int64()),
            "f32": pa.array([1.25, -2.5, None], type=pa.float32()),
            "f64": pa.array([3.1415, 0.0, None], type=pa.float64()),
            "dec": pa.array([Decimal("12.34"), Decimal("-99.50"), None], type=pa.decimal128(10, 2)),
            "d": pa.array([d_val, datetime.date(2024, 1, 1), None], type=pa.date32()),
            "ts": pa.array([dt_val, datetime.datetime(2024, 1, 1, 0, 0, 0), None], type=pa.timestamp("us")),
            "s": pa.array(["hello", "", None], type=pa.string()),
        }
    )
    path = write_parquet(tmp_path, "all_types.parquet", table)

    # Old parser check
    old_res = _parse_parquet(path, default_options("parquet"))
    assert len(old_res.rows) == 3

    db_path = tmp_path / "store.duckdb"
    with DuckStore(str(db_path)) as store:
        summary = import_parquet_to_store(store, "tbl", path)
        assert summary.row_count == 3
        assert summary.headers == ["b", "w", "f32", "f64", "dec", "d", "ts", "s"]
        assert summary.column_types == [
            "boolean",
            "whole",
            "decimal",
            "decimal",
            "fixed",
            "datetime",
            "datetime",
            "text",
        ]
        assert summary.source_arrow_types == [
            "bool",
            "int64",
            "float",
            "double",
            "decimal128(10, 2)",
            "date32[day]",
            "timestamp[us]",
            "string",
        ]
        assert summary.source_id != ""
        assert len(summary.notices) > 0

        # Read back via read_page
        rows = store.read_page("tbl", 0, 10)
        assert len(rows) == 3

        # Row 0
        r0 = rows[0]
        assert r0[0] is True
        assert r0[1] == 123
        assert r0[2] == 1.25
        assert r0[3] == 3.1415
        assert r0[4] == Decimal("12.3400")
        assert r0[5] == datetime.datetime(2023, 5, 17, 0, 0, 0)
        assert r0[6] == dt_val
        assert r0[7] == "hello"

        # Row 1
        r1 = rows[1]
        assert r1[0] is False
        assert r1[1] == -456
        assert r1[2] == -2.5
        assert r1[3] == 0.0
        assert r1[4] == Decimal("-99.5000")
        assert r1[5] == datetime.datetime(2024, 1, 1, 0, 0, 0)
        assert r1[6] == datetime.datetime(2024, 1, 1, 0, 0, 0)
        assert r1[7] == ""

        # Row 2 (nulls)
        r2 = rows[2]
        assert r2 == (None, None, None, None, None, None, None, None)


def test_multi_row_group_file_import(tmp_path: Path):
    rows = 600
    table = pa.table(
        {
            "id": pa.array(range(rows), type=pa.int64()),
            "val": pa.array([f"v_{i}" for i in range(rows)], type=pa.string()),
        }
    )
    path = write_parquet(tmp_path, "multi_rg.parquet", table, row_group_size=200)

    db_path = tmp_path / "multi_rg.duckdb"
    with DuckStore(str(db_path)) as store:
        summary = import_parquet_to_store(store, "multi_rg", path)
        assert summary.row_count == rows
        page = store.read_page("multi_rg", 0, 10)
        assert page[0] == (0, "v_0")
        page_tail = store.read_page("multi_rg", 598, 10)
        assert page_tail == [(598, "v_598"), (599, "v_599")]


def test_zero_row_file(tmp_path: Path):
    table = pa.table(
        {
            "id": pa.array([], type=pa.int64()),
            "name": pa.array([], type=pa.string()),
        }
    )
    path = write_parquet(tmp_path, "zero.parquet", table)

    db_path = tmp_path / "zero.duckdb"
    with DuckStore(str(db_path)) as store:
        summary = import_parquet_to_store(store, "zero_tbl", path)
        assert summary.row_count == 0
        assert store.columns("zero_tbl") == [("id", "whole"), ("name", "text")]
        assert store.read_page("zero_tbl", 0, 10) == []


def test_cancel_at_batch_2_leaves_no_table(tmp_path: Path):
    table = pa.table({"a": pa.array(range(500), type=pa.int64())})
    path = write_parquet(tmp_path, "cancel.parquet", table)

    ev = threading.Event()
    batch_count = [0]

    def on_progress(_msg):
        if "Read" in _msg:
            batch_count[0] += 1
            if batch_count[0] == 2:
                ev.set()

    db_path = tmp_path / "cancel.duckdb"
    with DuckStore(str(db_path)) as store:
        with pytest.raises(ImportCancelledError):
            import_parquet_to_store(
                store,
                "t_cancel",
                path,
                cancel_event=ev,
                progress=on_progress,
                batch_size=100,
            )
        assert not store.has_table("t_cancel")


def test_max_rows_refusal_before_reading_and_exact_boundary(tmp_path: Path):
    table = pa.table({"a": pa.array(range(10), type=pa.int64())})
    path = write_parquet(tmp_path, "max_rows.parquet", table)

    db_path = tmp_path / "max_rows.duckdb"
    with DuckStore(str(db_path)) as store:
        # Refused before reading when declared rows > max_rows
        with pytest.raises(FileImportError, match="exceeds the 9-row import limit"):
            import_parquet_to_store(store, "t1", path, max_rows=9)
        assert not store.has_table("t1")

        # Exact boundary: 10 rows with max_rows=10 succeeds
        summary = import_parquet_to_store(store, "t2", path, max_rows=10)
        assert summary.row_count == 10
        assert store.has_table("t2")


def test_progress_called_per_batch(tmp_path: Path):
    table = pa.table({"a": pa.array(range(300), type=pa.int64())})
    path = write_parquet(tmp_path, "prog.parquet", table)

    progress_calls = []
    db_path = tmp_path / "prog.duckdb"
    with DuckStore(str(db_path)) as store:
        import_parquet_to_store(store, "t_prog", path, progress=progress_calls.append, batch_size=100)
        # progress called by iter_parquet_batches and by store for each of the 3 batches
        read_calls = [c for c in progress_calls if "Read" in c]
        assert len(read_calls) == 3


def test_rollback_on_corrupt_file_leaves_no_table(tmp_path: Path):
    table = pa.table({"a": pa.array(range(500), type=pa.int64())})
    valid_path = write_parquet(tmp_path, "valid.parquet", table, row_group_size=100)

    # Create truncated file
    data = valid_path.read_bytes()
    corrupt_path = tmp_path / "corrupt.parquet"
    corrupt_path.write_bytes(data[: len(data) // 2])

    db_path = tmp_path / "corrupt.duckdb"
    with DuckStore(str(db_path)) as store:
        with pytest.raises(FileImportError, match="Could not read .* as Parquet"):
            import_parquet_to_store(store, "t_corrupt", corrupt_path)
        assert not store.has_table("t_corrupt")


def test_duplicate_table_name_raises_store_error(tmp_path: Path):
    table = pa.table({"a": pa.array([1, 2], type=pa.int64())})
    path = write_parquet(tmp_path, "dup.parquet", table)

    db_path = tmp_path / "dup.duckdb"
    with DuckStore(str(db_path)) as store:
        import_parquet_to_store(store, "t_exist", path)
        with pytest.raises(StoreError, match="already exists"):
            import_parquet_to_store(store, "t_exist", path)
        # Case insensitive duplicate
        with pytest.raises(StoreError, match="already exists"):
            import_parquet_to_store(store, "T_EXIST", path)


def test_header_refusals_case_duplicate_control_char_and_rn(tmp_path: Path):
    db_path = tmp_path / "header_errs.duckdb"
    with DuckStore(str(db_path)) as store:
        # Case duplicate
        t_case = pa.table({
            "Col": pa.array([1]),
            "col": pa.array([2]),
        })
        p_case = write_parquet(tmp_path, "case.parquet", t_case)
        with pytest.raises(FileImportError, match="cannot be used by the large-file store"):
            import_parquet_to_store(store, "t_case", p_case)
        assert not store.has_table("t_case")

        # Control character
        t_ctrl = pa.table({
            "col\n1": pa.array([1]),
        })
        p_ctrl = write_parquet(tmp_path, "ctrl.parquet", t_ctrl)
        with pytest.raises(FileImportError, match="cannot be used by the large-file store"):
            import_parquet_to_store(store, "t_ctrl", p_ctrl)
        assert not store.has_table("t_ctrl")

        # __rn leading double underscore
        t_rn = pa.table({
            "__rn": pa.array([1]),
        })
        p_rn = write_parquet(tmp_path, "rn.parquet", t_rn)
        with pytest.raises(FileImportError, match="cannot be used by the large-file store"):
            import_parquet_to_store(store, "t_rn", p_rn)
        assert not store.has_table("t_rn")


def test_unsupported_columns_refused_with_old_message(tmp_path: Path):
    # Nested struct
    t_nested = pa.table({
        "st": pa.array([{"x": 1}]),
    })
    p_nested = write_parquet(tmp_path, "nested.parquet", t_nested)
    db_path = tmp_path / "nested.duckdb"
    with DuckStore(str(db_path)) as store:
        with pytest.raises(FileImportError, match="Supported columns must contain scalar values; nested and binary types are not supported"):
            import_parquet_to_store(store, "t_nested", p_nested)
        assert not store.has_table("t_nested")


def test_type_mapping_refusals_time_tz_decimal_uint64(tmp_path: Path):
    db_path = tmp_path / "type_refusals.duckdb"
    with DuckStore(str(db_path)) as store:
        # Time of day
        t_time = pa.table({"tm": pa.array([datetime.time(12, 0, 0)], type=pa.time64("us"))})
        p_time = write_parquet(tmp_path, "time.parquet", t_time)
        with pytest.raises(FileImportError, match="time-of-day type that the large-table store does not support"):
            import_parquet_to_store(store, "t_time", p_time)
        assert not store.has_table("t_time")

        # Time zone
        t_tz = pa.table({"tz": pa.array([datetime.datetime(2023, 1, 1, 0, 0, 0)], type=pa.timestamp("us", tz="UTC"))})
        p_tz = write_parquet(tmp_path, "tz.parquet", t_tz)
        with pytest.raises(FileImportError, match="has a time zone; remove the time zone"):
            import_parquet_to_store(store, "t_tz", p_tz)
        assert not store.has_table("t_tz")

        # Decimal wider than 4 places scale
        t_dec = pa.table({"d": pa.array([Decimal("1.23456")], type=pa.decimal128(10, 5))})
        p_dec = write_parquet(tmp_path, "dec.parquet", t_dec)
        with pytest.raises(FileImportError, match="does not fit the 4-decimal fixed type"):
            import_parquet_to_store(store, "t_dec", p_dec)
        assert not store.has_table("t_dec")

        # uint64 > 2**63 - 1
        t_uint = pa.table({"u": pa.array([2**63 + 10], type=pa.uint64())})
        p_uint = write_parquet(tmp_path, "uint.parquet", t_uint)
        with pytest.raises(FileImportError, match="contains a value above 9223372036854775807"):
            import_parquet_to_store(store, "t_uint", p_uint)
        assert not store.has_table("t_uint")


def test_read_table_back_without_type_detect(tmp_path: Path):
    """Parquet tables are already typed; read_page returns typed values directly."""
    table = pa.table({
        "id": pa.array([1, 2], type=pa.int64()),
        "name": pa.array(["a", "b"], type=pa.string()),
    })
    path = write_parquet(tmp_path, "typed.parquet", table)

    db_path = tmp_path / "typed.duckdb"
    with DuckStore(str(db_path)) as store:
        summary = import_parquet_to_store(store, "typed_tbl", path)
        assert summary.column_types == ["whole", "text"]
        cols = store.columns("typed_tbl")
        assert cols == [("id", "whole"), ("name", "text")]
        rows = store.read_page("typed_tbl", 0, 10)
        assert rows == [(1, "a"), (2, "b")]
