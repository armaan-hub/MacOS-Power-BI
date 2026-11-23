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


# ---------------------------------------------------------------------------
# Review fix 2 (N1-N4, D8a, D8b, weak tests)
# ---------------------------------------------------------------------------


def _msg_has(exc_info, *parts):
    msg = str(exc_info.value)
    for part in parts:
        assert part in msg, f"{part!r} missing from message: {msg}"


def test_rounding_is_half_up_not_half_even(tmp_path):
    D = decimal.Decimal
    with DuckStore(str(tmp_path / "rnd.npa.data")) as store:
        store.create_table("t", [("f", "fixed")])
        store.append_rows(
            "t",
            [
                (D("1.23455"),),   # half-even would give 1.2346 too; next two differ
                (D("1.23445"),),   # half-up 1.2345, half-even 1.2344
                (D("2.00005"),),   # half-up 2.0001, half-even 2.0000
                (D("-1.23455"),),
                (D("-2.00005"),),  # half-up (away from zero) -2.0001
                (D("0.00005"),),   # half-up 0.0001, half-even 0.0000
            ],
        )
        assert store.read_page("t", 0, 10) == [
            (D("1.2346"),),
            (D("1.2345"),),
            (D("2.0001"),),
            (D("-1.2346"),),
            (D("-2.0001"),),
            (D("0.0001"),),
        ]


def test_memory_limit_and_temp_directory_applied(tmp_path):
    folder = tmp_path / "cfg"
    with DuckStore(str(folder / "m.npa.data"), memory_limit="500MB") as store:
        mem, temp = store.execute(
            "SELECT current_setting('memory_limit'), current_setting('temp_directory')"
        )[0]
        # 500 MB = 476.8 MiB in DuckDB's own formatting.
        assert mem.startswith("476.8"), mem
        assert os.path.realpath(temp) == os.path.realpath(str(folder))
    with DuckStore(str(folder / "m2.npa.data"), memory_limit="1GB") as store:
        mem = store.execute("SELECT current_setting('memory_limit')")[0][0]
        assert mem.startswith("953."), mem


def test_error_messages_name_table_column_and_row(tmp_path):
    D = decimal.Decimal
    with DuckStore(str(tmp_path / "msg.npa.data")) as store:
        store.create_table(
            "tbl_x",
            [("w", "whole"), ("fx", "fixed"), ("d", "decimal"), ("tx", "text"), ("b", "boolean"), ("dt", "datetime")],
        )
        good = (1, D("1"), 1.0, "a", True, datetime.datetime(2020, 1, 1))

        def with_bad(col, val):
            row = list(good)
            row[col] = val
            return [good, good, good, tuple(row)]  # bad row index is 3

        cases = [
            (0, 2**63, "w"),                       # whole out of range
            (0, 1.5, "w"),                         # wrong type
            (1, D("1234567890123456.1"), "fx"),    # fixed out of range
            (1, 1.5, "fx"),                        # wrong type
            (1, D("1E+30"), "fx"),                 # N3
            (1, D("1E+400"), "fx"),                # N3
            (1, 10**40, "fx"),                     # N3
            (1, D("1" * 31), "fx"),                # N3
            (2, 10**400, "d"),                     # N3
            (2, D("1E+400"), "d"),                 # N3
            (3, 5, "tx"),
            (4, 1, "b"),
            (5, datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc), "dt"),
        ]
        for col, val, col_name in cases:
            with pytest.raises(StoreError) as exc_info:
                store.append_rows("tbl_x", with_bad(col, val))
            _msg_has(exc_info, "tbl_x", f"'{col_name}'", "row 3")
            assert store.row_count("tbl_x") == 0


def test_bool_rejected_separately_with_type_message(tmp_path):
    with DuckStore(str(tmp_path / "bool.npa.data")) as store:
        store.create_table("w", [("a", "whole")])
        store.create_table("b", [("a", "boolean")])
        with pytest.raises(StoreError) as exc_info:
            store.append_rows("w", [(True,)])
        _msg_has(exc_info, "expected int", "got bool")
        with pytest.raises(StoreError) as exc_info:
            store.append_rows("b", [(1,)])
        _msg_has(exc_info, "expected bool", "got int")
        assert store.row_count("w") == 0 and store.row_count("b") == 0


def test_n1_interrupt_mid_append_rolls_back(tmp_path):
    with DuckStore(str(tmp_path / "n1.npa.data")) as store:
        store.create_table("t", [("a", "whole")])
        store.append_rows("t", [(1,), (2,)])

        def gen(exc):
            for i in range(60_000):  # more than one 50,000 batch is flushed
                yield (i,)
            raise exc

        with pytest.raises(KeyboardInterrupt):
            store.append_rows("t", gen(KeyboardInterrupt()))
        # original exception type must pass through unchanged, store still usable
        assert store.row_count("t") == 2
        assert store.append_rows("t", [(3,), (4,)]) == 2
        assert store.execute("SELECT __rn FROM t ORDER BY __rn") == [(0,), (1,), (2,), (3,)]

        class Odd(BaseException):
            pass

        with pytest.raises(Odd):
            store.append_rows("t", gen(Odd()))
        assert store.row_count("t") == 4
        assert store.append_rows("t", [(5,)]) == 1
        assert store.execute("SELECT __rn FROM t ORDER BY __rn") == [(i,) for i in range(5)]


def test_n2_user_table_named_batch_tbl_and_reserved_names(tmp_path):
    with DuckStore(str(tmp_path / "n2.npa.data")) as store:
        store.create_table("batch_tbl", [("a", "whole")])
        assert store.append_rows("batch_tbl", [(1,), (2,)]) == 2
        assert store.read_page("batch_tbl", 0, 10) == [(1,), (2,)]
        for bad in ["__store_batch__", "__x", "__"]:
            with pytest.raises(StoreError):
                store.create_table(bad, [("a", "whole")])
        assert store.table_names() == ["batch_tbl"]


def test_n3_huge_values_raise_store_error(tmp_path):
    D = decimal.Decimal
    with DuckStore(str(tmp_path / "n3.npa.data")) as store:
        store.create_table("t", [("f", "fixed"), ("d", "decimal")])
        for bad in [D("1E+30"), D("1" * 31), 10**40, D("1E+400"), 10**400, D("999999999999999.99995")]:
            with pytest.raises(StoreError):
                store.append_rows("t", [(bad, 1.0)])
        for bad in [10**400, D("1E+400"), -(10**400)]:
            with pytest.raises(StoreError):
                store.append_rows("t", [(D("1"), bad)])
        assert store.row_count("t") == 0
        # float inf and nan, stay allowed in a decimal column
        store.append_rows("t", [(D("1"), float("inf")), (D("1"), float("nan")), (D("1"), -float("inf"))])
        rows = store.read_page("t", 0, 10)
        assert rows[0][1] == float("inf") and rows[2][1] == float("-inf")
        assert rows[1][1] != rows[1][1]
        # edge values that fit
        store.append_rows("t", [(D("999999999999999.9999"), 1e300), (10**15 - 1, 1.0)])
        assert store.read_page("t", 3, 10)[0][0] == D("999999999999999.9999")


def test_n4_row_shapes_and_generator_cause(tmp_path):
    with DuckStore(str(tmp_path / "n4.npa.data")) as store:
        store.create_table("tshape", [("a", "whole"), ("b", "text")])
        bad_rows = [{"a": 1, "b": "x"}, {1, "x"}, "ab", 5, (1,), (1, "x", 3), None, b"ab"]
        for bad in bad_rows:
            with pytest.raises(StoreError) as exc_info:
                store.append_rows("tshape", [(0, "ok"), (1, "ok"), bad])
            _msg_has(exc_info, "tshape", "Row 2")
        assert store.row_count("tshape") == 0

        original = RuntimeError("stream failure")

        def faulty():
            yield (1, "a")
            raise original

        with pytest.raises(StoreError) as exc_info:
            store.append_rows("tshape", faulty())
        assert exc_info.value.__cause__ is original
        _msg_has(exc_info, "tshape")
        assert store.row_count("tshape") == 0


def test_d8a_bad_column_specs_raise_store_error(tmp_path):
    with DuckStore(str(tmp_path / "d8a.npa.data")) as store:
        bad_specs = [
            [("a", ["whole"])],      # unhashable type name
            [("a", 5)],              # non-str type name
            [("a", None)],
            [(5, "whole")],          # non-str column name
            [None],                  # non-tuple spec
            ["ab"],
            [5],
            [("a",)],
            [("a", "whole", "x")],
            [("a", {"whole"})],
        ]
        for spec in bad_specs:
            with pytest.raises(StoreError):
                store.create_table("zz", spec)
        assert not store.has_table("zz")


def test_d8b_limit_zero_still_validates_columns(tmp_path):
    with DuckStore(str(tmp_path / "d8b.npa.data")) as store:
        store.create_table("t", [("a", "whole")])
        store.append_rows("t", [(1,)])
        with pytest.raises(StoreError):
            store.read_page("t", 0, 0, columns=["nope"])
        with pytest.raises(StoreError):
            store.read_page("t", 0, 0, columns="a")
        assert store.read_page("t", 0, 0, columns=["A"]) == []


def test_read_page_follows_rn_after_failed_batch_and_three_calls(tmp_path):
    with DuckStore(str(tmp_path / "ord3.npa.data")) as store:
        store.create_table("t", [("a", "whole")])
        data = [(i,) for i in range(30)]
        store.append_rows("t", data[:10])
        with pytest.raises(StoreError):
            store.append_rows("t", [(100,), ("bad",)])
        store.append_rows("t", data[10:25])
        store.append_rows("t", data[25:])
        assert store.execute("SELECT __rn FROM t") != []
        assert sorted(r[0] for r in store.execute("SELECT __rn FROM t")) == list(range(30))
        pages = []
        for off in range(0, 30, 7):
            pages.extend(store.read_page("t", off, 7))
        assert pages == data


def test_b2a_create_table_from_arrow_success(tmp_path):
    import pyarrow as pa
    with DuckStore(str(tmp_path / "b2a_store.duckdb")) as store:
        batch1 = pa.record_batch([
            pa.array(["r0c0", "r1c0"], pa.string()),
            pa.array(["r0c1", "r1c1"], pa.string()),
        ], names=["col0", "col1"])
        batch2 = pa.record_batch([
            pa.array(["r2c0"], pa.string()),
            pa.array(["r2c1"], pa.string()),
        ], names=["col0", "col1"])

        rows_added = store.create_table_from_arrow(
            "tbl",
            [("col0", "text"), ("col1", "text")],
            [batch1, batch2],
        )
        assert rows_added == 3
        assert store.row_count("tbl") == 3
        assert store.columns("tbl") == [("col0", "text"), ("col1", "text")]

        # Read page
        page = store.read_page("tbl", 0, 10)
        assert page == [
            ("r0c0", "r0c1"),
            ("r1c0", "r1c1"),
            ("r2c0", "r2c1"),
        ]

        # Verify __rn
        rn_vals = store.execute('SELECT "__rn" FROM "tbl" ORDER BY "__rn"')
        assert [r[0] for r in rn_vals] == [0, 1, 2]


def test_b2a_create_table_from_arrow_type_must_be_known(tmp_path):
    import pyarrow as pa
    with DuckStore(str(tmp_path / "b2a_bad_type.duckdb")) as store:
        batch = pa.record_batch([
            pa.array(["val"], pa.string()),
        ], names=["col0"])
        with pytest.raises(StoreError, match="Unknown column type"):
            store.create_table_from_arrow(
                "tbl",
                [("col0", "nonexistent_type")],
                [batch],
            )
        assert not store.has_table("tbl")


def test_b2a_create_table_from_arrow_reserved_name(tmp_path):
    import pyarrow as pa
    with DuckStore(str(tmp_path / "b2a_res_tbl.duckdb")) as store:
        batch = pa.record_batch([pa.array(["val"], pa.string())], names=["col0"])
        with pytest.raises(StoreError, match="reserved"):
            store.create_table_from_arrow(
                "__internal",
                [("col0", "text")],
                [batch],
            )


def test_b2a_create_table_from_arrow_duplicate_columns(tmp_path):
    import pyarrow as pa
    with DuckStore(str(tmp_path / "b2a_dup_cols.duckdb")) as store:
        batch = pa.record_batch([
            pa.array(["v1"], pa.string()),
            pa.array(["v2"], pa.string()),
        ], names=["Col", "col"])
        with pytest.raises(StoreError, match="Duplicate column name"):
            store.create_table_from_arrow(
                "tbl",
                [("Col", "text"), ("col", "text")],
                [batch],
            )


def test_b2a_create_table_from_arrow_non_string_batch(tmp_path):
    import pyarrow as pa
    with DuckStore(str(tmp_path / "b2a_non_string.duckdb")) as store:
        batch = pa.record_batch([
            pa.array([123], pa.int64()),
        ], names=["col0"])
        with pytest.raises(StoreError, match="non-string type"):
            store.create_table_from_arrow(
                "tbl",
                [("col0", "text")],
                [batch],
            )


def test_b2a_create_table_from_arrow_batch_names_mismatch(tmp_path):
    import pyarrow as pa
    with DuckStore(str(tmp_path / "b2a_mismatch.duckdb")) as store:
        batch = pa.record_batch([
            pa.array(["v"], pa.string()),
        ], names=["other_name"])
        with pytest.raises(StoreError, match="do not match"):
            store.create_table_from_arrow(
                "tbl",
                [("col0", "text")],
                [batch],
            )


def test_b2a_create_table_from_arrow_cancel_checked_between_batches(tmp_path):
    import threading
    import pyarrow as pa
    from analytics_studio.file_import import ImportCancelledError

    ev = threading.Event()
    batch = pa.record_batch([pa.array(["v"], pa.string())], names=["c0"])

    def dummy_batches():
        yield batch
        ev.set()  # Cancel triggered after first batch
        yield batch

    with DuckStore(str(tmp_path / "b2a_cancel.duckdb")) as store:
        with pytest.raises(ImportCancelledError):
            store.create_table_from_arrow(
                "tbl",
                [("c0", "text")],
                dummy_batches(),
                cancel_event=ev,
            )
        assert not store.has_table("tbl")


def test_b2a_create_table_from_arrow_max_rows_boundary(tmp_path):
    import pyarrow as pa
    from analytics_studio.file_import import FileImportError

    with DuckStore(str(tmp_path / "b2a_max_rows.duckdb")) as store:
        batch1 = pa.record_batch([pa.array(["a", "b"], pa.string())], names=["c0"])
        batch2 = pa.record_batch([pa.array(["c"], pa.string())], names=["c0"])

        # Exactly max_rows rows (3) -> OK
        store.create_table_from_arrow("t_exact", [("c0", "text")], [batch1, batch2], max_rows=3)
        assert store.row_count("t_exact") == 3

        # max_rows=2 with 3 rows -> raises and rolls back
        with pytest.raises(FileImportError, match="import limit"):
            store.create_table_from_arrow("t_over", [("c0", "text")], [batch1, batch2], max_rows=2)
        assert not store.has_table("t_over")


def test_b2a_create_table_from_arrow_progress_called(tmp_path):
    import pyarrow as pa

    calls = []
    with DuckStore(str(tmp_path / "b2a_prog.duckdb")) as store:
        batch = pa.record_batch([pa.array(["a"], pa.string())], names=["c0"])
        store.create_table_from_arrow(
            "tbl",
            [("c0", "text")],
            [batch],
            progress=calls.append,
        )
        assert len(calls) == 1
        assert "Imported 1 CSV rows" in calls[0]


def test_b2a_create_table_from_arrow_rollback_on_error(tmp_path):
    import pyarrow as pa
    with DuckStore(str(tmp_path / "b2a_rollback.duckdb")) as store:
        batch1 = pa.record_batch([
            pa.array(["a", "b"], pa.string()),
        ], names=["c1"])
        # batch2 schema mismatch
        batch2 = pa.record_batch([
            pa.array(["c"], pa.string()),
        ], names=["mismatched"])

        with pytest.raises(StoreError, match="do not match"):
            store.create_table_from_arrow(
                "t_fail",
                [("c1", "text")],
                [batch1, batch2],
            )

        # Table should be cleanly rolled back and not exist
        assert not store.has_table("t_fail")
        assert "t_fail" not in store.table_names()



def test_b2b_create_table_from_arrow_all_types_round_trip(tmp_path):
    import datetime
    from decimal import Decimal
    import pyarrow as pa
    with DuckStore(str(tmp_path / "b2b_all_types.duckdb")) as store:
        cols = [
            ("c_bool", "boolean"),
            ("c_whole", "whole"),
            ("c_dec", "decimal"),
            ("c_fix", "fixed"),
            ("c_dt", "datetime"),
            ("c_txt", "text"),
        ]
        dt_val = datetime.datetime(2023, 11, 14, 22, 13, 20)
        dt_us = int(dt_val.timestamp() * 1_000_000)
        batch = pa.record_batch([
            pa.array([True, False, None], type=pa.bool_()),
            pa.array([42, -999, None], type=pa.int64()),
            pa.array([3.1415, -0.001, None], type=pa.float64()),
            pa.array([Decimal("12.3456"), Decimal("-99.0000"), None], type=pa.decimal128(19, 4)),
            pa.array([dt_val, datetime.datetime(2024, 1, 1, 0, 0, 0), None], type=pa.timestamp("us")),
            pa.array(["hello", "", None], type=pa.string()),
        ], names=[c[0] for c in cols])

        inserted = store.create_table_from_arrow("all_types", cols, [batch])
        assert inserted == 3
        assert store.row_count("all_types") == 3

        page = store.read_page("all_types", 0, 10)
        assert len(page) == 3
        # Row 0
        r0 = page[0]
        assert r0[0] is True
        assert r0[1] == 42
        assert abs(r0[2] - 3.1415) < 1e-9
        assert r0[3] == Decimal("12.3456")
        assert r0[4] == dt_val
        assert r0[5] == "hello"

        # Row 1
        r1 = page[1]
        assert r1[0] is False
        assert r1[1] == -999
        assert abs(r1[2] - (-0.001)) < 1e-9
        assert r1[3] == Decimal("-99.0000")
        assert r1[4] == datetime.datetime(2024, 1, 1, 0, 0, 0)
        assert r1[5] == ""

        # Row 2 (all nulls)
        r2 = page[2]
        assert r2 == (None, None, None, None, None, None)


def test_b2b_create_table_from_arrow_wrong_arrow_type_refused(tmp_path):
    import pyarrow as pa
    with DuckStore(str(tmp_path / "b2b_wrong_type.duckdb")) as store:
        # Expected whole (int64), provided int32
        batch = pa.record_batch([
            pa.array([1, 2], type=pa.int32()),
        ], names=["w"])
        with pytest.raises(StoreError, match="expected int64"):
            store.create_table_from_arrow("tbl_wrong", [("w", "whole")], [batch])
        assert not store.has_table("tbl_wrong")


def test_b2b_create_table_from_arrow_wrong_field_name_order(tmp_path):
    import pyarrow as pa
    with DuckStore(str(tmp_path / "b2b_wrong_order.duckdb")) as store:
        cols = [("a", "text"), ("b", "whole")]
        # Reversed column order in batch
        batch = pa.record_batch([
            pa.array([1, 2], type=pa.int64()),
            pa.array(["x", "y"], type=pa.string()),
        ], names=["b", "a"])
        with pytest.raises(StoreError, match="do not match"):
            store.create_table_from_arrow("tbl_order", cols, [batch])
        assert not store.has_table("tbl_order")


def test_b2b_create_table_from_arrow_extra_column_refused(tmp_path):
    import pyarrow as pa
    with DuckStore(str(tmp_path / "b2b_extra_col.duckdb")) as store:
        cols = [("a", "text")]
        batch = pa.record_batch([
            pa.array(["x"], type=pa.string()),
            pa.array([1], type=pa.int64()),
        ], names=["a", "b"])
        with pytest.raises(StoreError, match="do not match"):
            store.create_table_from_arrow("tbl_extra", cols, [batch])
        assert not store.has_table("tbl_extra")
