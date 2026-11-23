"""Tests for DuckDB table row store (analytics_studio.store)."""

import datetime
import decimal
import time
import pytest

from analytics_studio.store import (
    COLUMN_TYPES,
    DuckStore,
    StoreError,
    StoreLockedError,
)


def test_round_trip_types(tmp_path):
    db_path = str(tmp_path / "test.npa.data")
    with DuckStore(db_path) as store:
        columns = [
            ("col_whole", "whole"),
            ("col_decimal", "decimal"),
            ("col_fixed", "fixed"),
            ("col_datetime", "datetime"),
            ("col_text", "text"),
            ("col_boolean", "boolean"),
        ]
        store.create_table("data_types", columns)

        row1 = (
            2**62,
            1.23456789e-10,
            decimal.Decimal("1234567890.1234"),
            datetime.datetime(2026, 11, 23, 11, 30, 45),
            "Hello, 世界! 🚀",
            True,
        )
        row2 = (
            -(2**62),
            -9.87654321e15,
            decimal.Decimal("-9876543210.9876"),
            datetime.datetime(1999, 12, 31, 23, 59, 59),
            "",
            False,
        )
        row3 = (None, None, None, None, None, None)

        added = store.append_rows("data_types", [row1, row2, row3])
        assert added == 3
        assert store.row_count("data_types") == 3

        read_rows = store.read_page("data_types", 0, 10)
        assert len(read_rows) == 3

        # Row 1
        assert read_rows[0][0] == 2**62
        assert abs(read_rows[0][1] - 1.23456789e-10) < 1e-18
        assert read_rows[0][2] == decimal.Decimal("1234567890.1234")
        assert read_rows[0][3] == datetime.datetime(2026, 11, 23, 11, 30, 45)
        assert read_rows[0][4] == "Hello, 世界! 🚀"
        assert read_rows[0][5] is True

        # Row 2
        assert read_rows[1][0] == -(2**62)
        assert abs(read_rows[1][1] - (-9.87654321e15)) < 1e5
        assert read_rows[1][2] == decimal.Decimal("-9876543210.9876")
        assert read_rows[1][3] == datetime.datetime(1999, 12, 31, 23, 59, 59)
        assert read_rows[1][4] == ""
        assert read_rows[1][5] is False

        # Row 3 (all None)
        assert read_rows[2] == (None, None, None, None, None, None)

        # Distinguish empty string vs None
        assert read_rows[1][4] == ""
        assert read_rows[2][4] is None
        assert read_rows[1][4] != read_rows[2][4]


def test_order_preserved_over_multiple_batches(tmp_path):
    db_path = str(tmp_path / "batches.npa.data")
    total_rows = 120_000
    rows_data = [(i, f"val_{i}") for i in range(total_rows)]

    with DuckStore(db_path) as store:
        store.create_table("items", [("num", "whole"), ("txt", "text")])

        # Append in chunks to simulate multiple appends across batches
        added = store.append_rows("items", rows_data[:70_000])
        assert added == 70_000
        added = store.append_rows("items", rows_data[70_000:])
        assert added == 50_000
        assert store.row_count("items") == total_rows

        # Verify __rn order via direct execute query
        rn_check = store.execute("SELECT MIN(__rn), MAX(__rn), COUNT(__rn) FROM items")
        assert rn_check == [(0, total_rows - 1, total_rows)]

        # Read in pages of 40,000 and verify concatenated list matches original
        page_size = 40_000
        reconstructed = []
        for offset in range(0, total_rows, page_size):
            page = store.read_page("items", offset, page_size)
            reconstructed.extend(page)

        assert len(reconstructed) == total_rows
        assert reconstructed == rows_data


def test_persistence_and_locking(tmp_path):
    db_path = str(tmp_path / "locked.npa.data")

    # Open store 1
    store1 = DuckStore(db_path)
    store1.create_table("t", [("x", "whole")])
    store1.append_rows("t", [(1,), (2,), (3,)])

    # Second store concurrently on same path should raise StoreLockedError
    with pytest.raises(StoreLockedError) as exc_info:
        DuckStore(db_path)
    assert "already locked" in str(exc_info.value)

    # Close store 1
    store1.close()

    # Now reopening succeeds and data persists
    with DuckStore(db_path) as store2:
        assert store2.has_table("t")
        assert store2.row_count("t") == 3
        assert store2.read_page("t", 0, 10) == [(1,), (2,), (3,)]


def test_bad_names_and_types_and_escaping(tmp_path):
    db_path = str(tmp_path / "errors.npa.data")
    with DuckStore(db_path) as store:
        # Invalid type
        with pytest.raises(StoreError):
            store.create_table("t1", [("a", "invalid_type")])

        # Reserved column name __rn
        with pytest.raises(StoreError):
            store.create_table("t2", [("__rn", "whole")])

        # Duplicate column name
        with pytest.raises(StoreError):
            store.create_table("t3", [("a", "whole"), ("a", "text")])

        # Valid create with tricky identifiers (quotes, spaces, unicode)
        special_tbl = 'my "special" table'
        special_col = 'my "col" 1'
        store.create_table(special_tbl, [(special_col, "text")])
        assert store.has_table(special_tbl)
        assert store.columns(special_tbl) == [(special_col, "text")]

        # Duplicate table name
        with pytest.raises(StoreError):
            store.create_table(special_tbl, [("other", "whole")])

        # Append and read from tricky table
        store.append_rows(special_tbl, [('quote: "',)])
        res = store.read_page(special_tbl, 0, 10)
        assert res == [('quote: "',)]

        # Drop table
        store.drop_table(special_tbl)
        assert not store.has_table(special_tbl)
        with pytest.raises(StoreError):
            store.drop_table(special_tbl)


def test_execute_statement_restrictions(tmp_path):
    db_path = str(tmp_path / "sql.npa.data")
    with DuckStore(db_path) as store:
        store.create_table("test_table", [("id", "whole")])
        store.append_rows("test_table", [(10,), (20,)])

        # Valid SELECT
        rows = store.execute("SELECT id FROM test_table WHERE id > ? ORDER BY id", [10])
        assert rows == [(20,)]

        # Multiple statements disallowed
        with pytest.raises(StoreError):
            store.execute("SELECT 1; SELECT 2")

        # DROP TABLE disallowed
        with pytest.raises(StoreError):
            store.execute("DROP TABLE test_table")

        # INSERT disallowed
        with pytest.raises(StoreError):
            store.execute("INSERT INTO test_table VALUES (30, 2)")

        # Table is intact
        assert store.row_count("test_table") == 2


def test_speed_300k_rows(tmp_path):
    db_path = str(tmp_path / "speed.npa.data")
    n_rows = 300_000
    rows_data = [
        (i, f"str_{i}", float(i) * 0.1, i % 2 == 0, decimal.Decimal("123.4567"))
        for i in range(n_rows)
    ]

    with DuckStore(db_path) as store:
        cols = [
            ("c1", "whole"),
            ("c2", "text"),
            ("c3", "decimal"),
            ("c4", "boolean"),
            ("c5", "fixed"),
        ]
        store.create_table("bench", cols)

        t0 = time.perf_counter()
        added = store.append_rows("bench", rows_data)
        elapsed = time.perf_counter() - t0

        print(f"\n[BENCHMARK] Appended {n_rows} rows x 5 columns in {elapsed:.3f} s")
        assert added == n_rows
        assert elapsed < 10.0, f"Append took {elapsed:.3f} s, which exceeds 10 s limit"
        assert store.row_count("bench") == n_rows
