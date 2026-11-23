"""Tests for DuckDB table row store (analytics_studio.store)."""

import datetime
import decimal
import gc
import os
import subprocess
import sys
import time
import pytest

from analytics_studio.store import (
    COLUMN_TYPES,
    DuckStore,
    StoreError,
    StoreLockedError,
)


def test_column_types_constant():
    assert set(COLUMN_TYPES) == {"whole", "decimal", "fixed", "datetime", "text", "boolean"}


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

        # Row 1 exact assertions
        assert read_rows[0][0] == 2**62
        assert read_rows[0][1] == 1.23456789e-10
        assert read_rows[0][2] == decimal.Decimal("1234567890.1234")
        assert read_rows[0][3] == datetime.datetime(2026, 11, 23, 11, 30, 45)
        assert read_rows[0][4] == "Hello, 世界! 🚀"
        assert read_rows[0][5] is True

        # Row 2 exact assertions
        assert read_rows[1][0] == -(2**62)
        assert read_rows[1][1] == -9.87654321e15
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


def test_strict_value_rejections_decision1(tmp_path):
    db_path = str(tmp_path / "strict.npa.data")
    with DuckStore(db_path) as store:
        for t_name in COLUMN_TYPES:
            store.create_table(t_name, [("val", t_name)])

        # whole: int only, fits BIGINT
        bad_whole = [1.7, True, False, 2**63, -2**63 - 1, "12", float("nan"), float("inf")]
        for val in bad_whole:
            with pytest.raises(StoreError):
                store.append_rows("whole", [(val,)])
            assert store.row_count("whole") == 0

        # decimal: int, float, Decimal, not bool, not str
        bad_decimal = [True, False, "1.5", "abc", 10**400]
        for val in bad_decimal:
            with pytest.raises(StoreError):
                store.append_rows("decimal", [(val,)])
            assert store.row_count("decimal") == 0

        # fixed: Decimal or int, round half away from zero to 4 places, fits DECIMAL(19,4), not float, not bool, not str, no NaN
        bad_fixed = [1.1, 0.1 + 0.2, True, False, "1.5", decimal.Decimal("1234567890123456.1"), decimal.Decimal("NaN"), decimal.Decimal("Infinity")]
        for val in bad_fixed:
            with pytest.raises(StoreError):
                store.append_rows("fixed", [(val,)])
            assert store.row_count("fixed") == 0

        # fixed rounding behavior test
        store.append_rows("fixed", [(decimal.Decimal("1.23456"),), (decimal.Decimal("1.23455"),), (decimal.Decimal("-1.23455"),), (5,)])
        res = store.read_page("fixed", 0, 10)
        assert res == [(decimal.Decimal("1.2346"),), (decimal.Decimal("1.2346"),), (decimal.Decimal("-1.2346"),), (decimal.Decimal("5.0000"),)]

        # datetime: naive datetime only
        aware_dt = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
        bad_dt = [aware_dt, datetime.date(2026, 1, 1), "2026-01-01 00:00:00", 123456789]
        for val in bad_dt:
            with pytest.raises(StoreError):
                store.append_rows("datetime", [(val,)])
            assert store.row_count("datetime") == 0

        # text: str only
        bad_text = [b"bytes", True, False, 123, 4.5]
        for val in bad_text:
            with pytest.raises(StoreError):
                store.append_rows("text", [(val,)])
            assert store.row_count("text") == 0

        # boolean: bool only
        bad_bool = [0, 1, 2, "False", "True", "", 0.0]
        for val in bad_bool:
            with pytest.raises(StoreError):
                store.append_rows("boolean", [(val,)])
            assert store.row_count("boolean") == 0


def test_bad_row_rollback_and_rn_contiguity(tmp_path):
    db_path = str(tmp_path / "rollback.npa.data")
    with DuckStore(db_path) as store:
        store.create_table("t", [("a", "whole"), ("b", "text")])

        # 120,000 rows with bad row at 70,000
        rows = [(i, f"str_{i}") for i in range(120_000)]
        rows[70_000] = (1.5, "bad_float_in_whole")

        with pytest.raises(StoreError) as exc_info:
            store.append_rows("t", rows)
        assert "column 'a'" in str(exc_info.value)
        assert store.row_count("t") == 0

        # Next valid append starts at __rn = 0 and is contiguous
        store.append_rows("t", [(10, "first"), (20, "second")])
        assert store.row_count("t") == 2
        assert store.execute("SELECT min(__rn), max(__rn), count(*) FROM t") == [(0, 1, 2)]

        # Attempt another invalid batch, row_count must remain 2
        bad_batch = [(30, "third"), ("invalid", "fourth")]
        with pytest.raises(StoreError):
            store.append_rows("t", bad_batch)
        assert store.row_count("t") == 2

        # Subsequent valid append continues __rn
        store.append_rows("t", [(30, "third"), (40, "fourth")])
        assert store.row_count("t") == 4
        assert store.execute("SELECT min(__rn), max(__rn), count(*) FROM t") == [(0, 3, 4)]


def test_generator_and_shape_inputs(tmp_path):
    db_path = str(tmp_path / "shapes.npa.data")
    with DuckStore(db_path) as store:
        store.create_table("t", [("a", "whole"), ("b", "text")])

        # Empty iterable and generator
        assert store.append_rows("t", []) == 0
        assert store.append_rows("t", iter(())) == 0
        assert store.row_count("t") == 0

        # Generator input
        gen = ((i, f"g_{i}") for i in range(5))
        assert store.append_rows("t", gen) == 5
        assert store.row_count("t") == 5

        # Short tuple
        with pytest.raises(StoreError):
            store.append_rows("t", [(1,)])

        # Extra long tuple
        with pytest.raises(StoreError):
            store.append_rows("t", [(1, "b", "c")])

        # Row as non-sequence
        with pytest.raises(StoreError):
            store.append_rows("t", [123])

        # Generator that raises midway
        def faulty_gen():
            for i in range(10):
                yield (i, "ok")
            raise RuntimeError("stream failure")

        with pytest.raises(StoreError):
            store.append_rows("t", faulty_gen())
        # Table remains intact at 5 rows
        assert store.row_count("t") == 5


def test_order_preserved_single_and_multiple_calls(tmp_path):
    db_path = str(tmp_path / "order.npa.data")
    total_rows = 120_000
    rows_data = [(i, f"val_{i}") for i in range(total_rows)]

    # 1. Single call of 120,000 rows
    with DuckStore(db_path) as store:
        store.create_table("items_single", [("num", "whole"), ("txt", "text")])
        added = store.append_rows("items_single", rows_data)
        assert added == total_rows
        assert store.row_count("items_single") == total_rows
        assert store.execute("SELECT MIN(__rn), MAX(__rn), COUNT(__rn) FROM items_single") == [(0, total_rows - 1, total_rows)]

        reconstructed = []
        page_size = 40_000
        for offset in range(0, total_rows, page_size):
            reconstructed.extend(store.read_page("items_single", offset, page_size))
        assert reconstructed == rows_data

    # 2. Three calls across batches
    db_path2 = str(tmp_path / "order_multi.npa.data")
    with DuckStore(db_path2) as store:
        store.create_table("items_multi", [("num", "whole"), ("txt", "text")])
        store.append_rows("items_multi", rows_data[:40_000])
        store.append_rows("items_multi", rows_data[40_000:90_000])
        store.append_rows("items_multi", rows_data[90_000:])
        assert store.row_count("items_multi") == total_rows
        assert store.execute("SELECT MIN(__rn), MAX(__rn), COUNT(__rn) FROM items_multi") == [(0, total_rows - 1, total_rows)]

        reconstructed2 = []
        for offset in range(0, total_rows, page_size):
            reconstructed2.extend(store.read_page("items_multi", offset, page_size))
        assert reconstructed2 == rows_data


def test_process_lock_symlink_del_and_readonly(tmp_path):
    db_path = str(tmp_path / "lk.npa.data")

    # Second process test via subprocess
    store1 = DuckStore(db_path)
    child_code = f"""
import sys; sys.path.insert(0, '{os.getcwd()}')
from analytics_studio.store import DuckStore, StoreLockedError
try:
    DuckStore({db_path!r})
    print('OPENED')
except StoreLockedError:
    print('LOCKED')
"""
    proc = subprocess.run([sys.executable, "-c", child_code], capture_output=True, text=True)
    assert proc.stdout.strip() == "LOCKED"

    # Close store1 -> second process can open
    store1.close()
    proc = subprocess.run([sys.executable, "-c", child_code], capture_output=True, text=True)
    assert proc.stdout.strip() == "OPENED"

    # Exception inside with block releases lock
    try:
        with DuckStore(db_path):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    proc = subprocess.run([sys.executable, "-c", child_code], capture_output=True, text=True)
    assert proc.stdout.strip() == "OPENED"

    # Symlink to same path is locked
    sym_path = str(tmp_path / "sym_lk.npa.data")
    os.symlink(db_path, sym_path)
    store2 = DuckStore(db_path)
    with pytest.raises(StoreLockedError):
        DuckStore(sym_path)
    store2.close()

    # del and gc.collect() releases lock
    store3 = DuckStore(db_path)
    del store3
    gc.collect()
    store4 = DuckStore(db_path)
    store4.close()

    # Readonly folder raises StoreError (not StoreLockedError)
    ro_dir = tmp_path / "ro_dir"
    ro_dir.mkdir()
    ro_dir.chmod(0o500)
    try:
        with pytest.raises(StoreError) as exc_info:
            DuckStore(str(ro_dir / "db.npa.data"))
        assert not isinstance(exc_info.value, StoreLockedError)
        assert "already locked" not in str(exc_info.value)
    finally:
        ro_dir.chmod(0o700)


def test_case_policy_and_names(tmp_path):
    db_path = str(tmp_path / "case.npa.data")
    with DuckStore(db_path) as store:
        # Table name case-insensitivity
        store.create_table("t", [("w", "whole"), ("select", "text")])
        assert store.has_table("t")
        assert store.has_table("T")
        assert not store.has_table("other")

        # Duplicate table under ASCII case
        with pytest.raises(StoreError):
            store.create_table("T", [("a", "whole")])

        # Append using upper-case table name
        store.append_rows("T", [(1, "hello")])
        assert store.row_count("T") == 1
        assert store.row_count("t") == 1

        # Columns lookup with case-insensitivity
        assert store.columns("T") == [("w", "whole"), ("select", "text")]

        # read_page resolving column name "W" to "w"
        assert store.read_page("T", 0, 10, columns=["W"]) == [(1,)]

        # Unicode case preserved (DuckDB is ASCII-only case insensitive)
        store.create_table("Ünï", [("a", "whole")])
        assert store.has_table("Ünï")
        assert not store.has_table("ünï")
        store.create_table("ünï", [("a", "whole")])
        assert store.has_table("ünï")

        # Tricky identifiers: spaces, quotes, SQL keywords
        special = 'my "tbl" select 日本'
        store.create_table(special, [('col "1"', "whole")])
        assert store.has_table(special)
        store.append_rows(special, [(42,)])
        assert store.read_page(special, 0, 10) == [(42,)]

        # Invalid names: empty, NUL, control chars, non-str
        for bad_nm in ["", None, 123, "a\x00b", "a\nb", "a\rb", "a\tb"]:
            with pytest.raises(StoreError):
                store.create_table(bad_nm, [("a", "whole")])
            with pytest.raises(StoreError):
                store.create_table("valid_name", [(bad_nm, "whole")])


def test_read_page_options(tmp_path):
    db_path = str(tmp_path / "read_page.npa.data")
    with DuckStore(db_path) as store:
        store.create_table("t", [("a", "whole"), ("b", "text")])
        store.append_rows("t", [(i, f"s_{i}") for i in range(10)])

        # Offset past end -> empty list
        assert store.read_page("t", 100, 5) == []

        # Limit 0 -> empty list
        assert store.read_page("t", 0, 0) == []

        # Negative offset or limit -> StoreError
        with pytest.raises(StoreError):
            store.read_page("t", -1, 5)
        with pytest.raises(StoreError):
            store.read_page("t", 0, -1)

        # None or bool offset/limit -> StoreError
        with pytest.raises(StoreError):
            store.read_page("t", None, 5)
        with pytest.raises(StoreError):
            store.read_page("t", True, 5)
        with pytest.raises(StoreError):
            store.read_page("t", 0, False)

        # Columns reorder
        rows = store.read_page("t", 0, 2, columns=["b", "a"])
        assert rows == [("s_0", 0), ("s_1", 1)]

        # Duplicate columns in read_page
        with pytest.raises(StoreError):
            store.read_page("t", 0, 2, columns=["a", "A"])

        # Columns as bare string -> StoreError
        with pytest.raises(StoreError):
            store.read_page("t", 0, 2, columns="ab")

        # Unknown column -> StoreError
        with pytest.raises(StoreError):
            store.read_page("t", 0, 2, columns=["nonexistent"])


def test_external_access_disabled_and_corrupt_file(tmp_path):
    db_path = str(tmp_path / "ext.npa.data")
    with DuckStore(db_path) as store:
        store.create_table("t", [("a", "whole")])
        store.append_rows("t", [(1,)])

        # read_csv / read_text / glob must raise StoreError
        with pytest.raises(StoreError):
            store.execute("SELECT * FROM read_csv('/etc/hosts')")
        with pytest.raises(StoreError):
            store.execute("SELECT * FROM read_text('/etc/hosts')")
        with pytest.raises(StoreError):
            store.execute("SELECT * FROM glob('/etc/*')")

    # Corrupt file on open raises StoreError
    corrupt_path = str(tmp_path / "corrupt.npa.data")
    with open(corrupt_path, "wb") as f:
        f.write(b"not a valid duckdb file content" * 100)

    with pytest.raises(StoreError):
        DuckStore(corrupt_path)


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

        # Verify SELECT * exposes __rn as last column
        res = store.execute("SELECT * FROM test_table WHERE id = 10")
        assert res == [(10, 0)]


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
        assert elapsed < 3.0, f"Append took {elapsed:.3f} s, which exceeds 3 s limit"
        assert store.row_count("bench") == n_rows
