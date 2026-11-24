"""Tests for analytics_studio.store.stats (scale plan B7, finding 2.2)."""

import datetime
import decimal
import threading
import time

import pytest

from analytics_studio.file_import import ImportCancelledError
from analytics_studio.store import stats as st
from analytics_studio.store.base import StoreError
from analytics_studio.store.duck_store import DuckStore


@pytest.fixture
def store(tmp_path):
    s = DuckStore(str(tmp_path / "s.duckdb"))
    yield s
    s.close()


def _make(store, name, cols, rows=()):
    store.create_table(name, cols)
    rows = list(rows)
    if rows:
        store.append_rows(name, rows)


def _col(result, name):
    return next(c for c in result.columns if c.name == name)


# ---------- per-type measurement ----------

def test_every_stored_type_bytes_and_labels(store):
    cols = [
        ("w", "whole"), ("d", "decimal"), ("f", "fixed"), ("dt", "datetime"),
        ("t", "text"), ("b", "boolean"),
    ]
    rows = [
        (1, 1.5, decimal.Decimal("2.5"), datetime.datetime(2026, 1, 1), "x", True),
        (None, None, None, None, None, None),
        (3, 2.0, decimal.Decimal("3.0"), datetime.datetime(2026, 1, 2), "yy", False),
    ]
    _make(store, "t", cols, rows)
    labels = ["whole_number", "decimal_number", "decimal_number", "date", "text", "boolean"]
    res = st.compute_table_stats(store, "t", labels)
    assert res.rows == 3
    by = {c.name: c for c in res.columns}
    assert [c.stored_type for c in res.columns] == ["whole", "decimal", "fixed", "datetime", "text", "boolean"]
    assert by["w"].approx_bytes == 8 * 3
    assert by["d"].approx_bytes == 8 * 3
    assert by["dt"].approx_bytes == 8 * 3
    assert by["f"].approx_bytes == 16 * 3
    assert by["b"].approx_bytes == 3
    assert by["t"].approx_bytes == 1 + 2  # 'x' and 'yy', NULL contributes nothing
    assert res.approx_bytes == sum(c.approx_bytes for c in res.columns)
    assert by["w"].label == "whole_number"
    assert by["t"].empty_count == 0
    assert by["t"].max_chars == 2
    assert by["w"].max_chars == 0 and by["w"].avg_chars == 0.0


def test_null_and_empty_counts(store):
    _make(store, "t", [("s", "text"), ("n", "whole")],
          [("a", 1), (None, None), ("", 3), ("", None), ("b", 5)])
    res = st.compute_table_stats(store, "t", ["text", "whole_number"])
    s = _col(res, "s")
    n = _col(res, "n")
    assert s.rows == 5
    assert s.null_count == 1
    assert s.empty_count == 2
    assert n.null_count == 2
    assert n.empty_count == 0
    assert s.distinct_approx == 3  # 'a', '', 'b' (NULL not counted)
    assert s.avg_chars == pytest.approx((1 + 0 + 0 + 1) / 4)


def test_multibyte_lengths_use_chars_and_octets(store):
    _make(store, "t", [("s", "text")], [("é",), ("日本",), ("a",)])
    res = st.compute_table_stats(store, "t", ["text"])
    c = res.columns[0]
    assert c.max_chars == 2
    assert c.avg_chars == pytest.approx(4 / 3)
    assert c.approx_bytes == 2 + 6 + 1


def test_approx_distinct_never_above_rows(store):
    _make(store, "t", [("s", "text")], [("v%d" % (i % 7),) for i in range(50)])
    res = st.compute_table_stats(store, "t", ["text"])
    c = res.columns[0]
    assert c.distinct_approx <= c.rows == 50


def test_empty_table_no_division_no_warnings(store):
    _make(store, "t", [("s", "text"), ("n", "whole")])
    res = st.compute_table_stats(store, "t", ["text", "whole_number"])
    assert res.rows == 0 and res.approx_bytes == 0 and res.warnings == ()
    for c in res.columns:
        assert c.rows == 0 and c.null_count == 0 and c.empty_count == 0
        assert c.distinct_approx == 0 and c.max_chars == 0 and c.avg_chars == 0.0
        assert c.approx_bytes == 0 and c.warnings == ()


# ---------- label handling ----------

def test_list_and_mapping_forms_agree(store):
    _make(store, "t", [("a", "text"), ("b", "whole")], [("x", 1), ("y", 2)])
    as_list = st.compute_table_stats(store, "t", ["text", "whole_number"])
    as_map = st.compute_table_stats(store, "t", {"a": "text", "b": "whole_number"})
    assert as_list == as_map


def test_missing_label_is_text(store):
    _make(store, "t", [("a", "whole"), ("b", "whole")], [(1, 2)])
    res = st.compute_table_stats(store, "t", {"a": "whole_number"})
    assert _col(res, "b").label == "text"
    res2 = st.compute_table_stats(store, "t", ["whole_number"])
    assert res2.columns[1].label == "text"


# ---------- column warnings at real constants ----------

def test_unique_text_boundary_rows_99999_vs_100000(store):
    _make(store, "small", [("s", "text")], [("u%d" % i,) for i in range(99_999)])
    assert st.compute_table_stats(store, "small", ["text"]).columns[0].warnings == ()
    _make(store, "big", [("s", "text")], [("u%d" % i,) for i in range(100_000)])
    w = st.compute_table_stats(store, "big", ["text"]).columns[0].warnings
    assert len(w) == 1
    assert w[0].startswith("Column 's' holds mostly unique text (about ")
    assert "(about 100,000 distinct values in 100,000 rows)" in w[0]
    assert w[0].endswith("Filters, grouping and visuals on it are slow and use a lot of memory.")


def test_unique_ratio_boundary_089_vs_090(monkeypatch):
    # approx_count_distinct is an estimate (about 863 for 900 real values in
    # 1000 rows), so the 0.89 vs 0.9 boundary is checked on the pure rule with
    # exact distinct counts. End-to-end wiring is covered by the 100,000-row tests.
    monkeypatch.setattr(st, "_UNIQUE_MIN_ROWS", 1_000)
    assert st._column_warnings("text", "text", "s", 1_000, 0, 0, 890, 1) == ()
    w = st._column_warnings("text", "text", "s", 1_000, 0, 0, 900, 1)
    assert w == (
        "Column 's' holds mostly unique text (about 900 distinct values in 1,000 rows). "
        "Filters, grouping and visuals on it are slow and use a lot of memory.",
    )


def test_unique_warning_needs_text_label_and_text_type(store, monkeypatch):
    monkeypatch.setattr(st, "_UNIQUE_MIN_ROWS", 10)
    _make(store, "t", [("s", "text")], [("u%d" % i,) for i in range(20)])
    res = st.compute_table_stats(store, "t", ["whole_number"])
    assert not any("mostly unique" in x for x in res.columns[0].warnings)


def test_long_text_boundary_999_vs_1000(store):
    _make(store, "t", [("s", "text")], [("a" * 999,)])
    assert st.compute_table_stats(store, "t", ["text"]).columns[0].warnings == ()
    _make(store, "u", [("s", "text")], [("a" * 1000,)])
    w = st.compute_table_stats(store, "u", ["text"]).columns[0].warnings
    assert w == ("Column 's' has cells up to 1000 characters long.",)


def test_mostly_empty_boundaries(store):
    # 1000 rows, 950 empty (NULL + '') -> 95%: warn, P = 95
    rows = [(None,)] * 500 + [("",)] * 450 + [("x",)] * 50
    _make(store, "edge", [("s", "text")], rows)
    w = st.compute_table_stats(store, "edge", ["text"]).columns[0].warnings
    assert w == ("Column 's' is almost empty (95% of cells are empty).",)
    # 949 empty of 1000 -> 94.9%: no warning
    rows = [(None,)] * 500 + [("",)] * 449 + [("x",)] * 51
    _make(store, "under", [("s", "text")], rows)
    assert st.compute_table_stats(store, "under", ["text"]).columns[0].warnings == ()


def test_mostly_empty_rows_999_vs_1000(store):
    _make(store, "t999", [("s", "text")], [(None,)] * 999)
    assert st.compute_table_stats(store, "t999", ["text"]).columns[0].warnings == ()
    _make(store, "t1000", [("s", "text")], [(None,)] * 1000)
    w = st.compute_table_stats(store, "t1000", ["text"]).columns[0].warnings
    assert w == ("Column 's' is almost empty (100% of cells are empty).",)


def test_mostly_empty_rounds_half_up(store, monkeypatch):
    monkeypatch.setattr(st, "_EMPTY_PERCENT", 1)
    # 125 empty of 1000 rows is 12.5%, which rounds half up to 13%
    _make(store, "t", [("s", "text")], [(None,)] * 125 + [("x",)] * 875)
    w = st.compute_table_stats(store, "t", ["text"]).columns[0].warnings
    assert w == ("Column 's' is almost empty (13% of cells are empty).",)


# ---------- table warnings ----------

def _wide(store, name, n):
    cols = [("c%d" % i, "whole") for i in range(n)]
    _make(store, name, cols, [tuple(range(n))])


def test_wide_table_boundary_100_vs_101(store):
    _wide(store, "w100", 100)
    assert st.compute_table_stats(store, "w100", ["whole_number"] * 100).warnings == ()
    _wide(store, "w101", 101)
    res = st.compute_table_stats(store, "w101", ["whole_number"] * 101)
    assert res.warnings == (
        "The table has 101 columns. Wide tables use much more memory; keep only the columns you need.",
    )


def test_513_columns_allowed_and_warned(store):
    _wide(store, "w513", 513)
    res = st.compute_table_stats(store, "w513", ["whole_number"] * 513)
    assert len(res.columns) == 513
    assert res.warnings[0].startswith("The table has 513 columns.")


def test_size_warning_monkeypatched(store, monkeypatch):
    _make(store, "t", [("a", "whole")], [(1,), (2,), (3,)])
    assert st.compute_table_stats(store, "t", ["whole_number"]).warnings == ()
    monkeypatch.setattr(st, "_LARGE_TABLE_BYTES", 24)
    res = st.compute_table_stats(store, "t", ["whole_number"])
    assert res.approx_bytes == 24
    assert res.warnings == (
        "The table needs about 0.0 GB in the store. Importing it again with fewer columns is faster.",
    )


# ---------- hostile names ----------

def test_hostile_column_names(store):
    names = ['a"b', "x; DROP TABLE t", "Ünï"]
    _make(store, "t", [(n, "text") for n in names], [("1", "2", "3")])
    res = st.compute_table_stats(store, "t", ["text"] * 3)
    assert [c.name for c in res.columns] == names
    assert all(c.rows == 1 and c.distinct_approx == 1 for c in res.columns)
    assert store.has_table("t")


def test_hostile_table_name_quoted(store):
    _make(store, 'we"ird', [("a", "text")], [("q",)])
    res = st.compute_table_stats(store, 'we"ird', ["text"])
    assert res.rows == 1


# ---------- cancel, progress, errors ----------

def test_cancel_before_first_column(store):
    _make(store, "t", [("a", "text"), ("b", "text")], [("x", "y")])
    ev = threading.Event()
    ev.set()
    calls = []
    with pytest.raises(ImportCancelledError):
        st.compute_table_stats(store, "t", ["text", "text"], cancel_event=ev,
                               progress=calls.append)
    assert calls == []


def test_cancel_between_columns(store):
    _make(store, "t", [("a", "text"), ("b", "text"), ("c", "text")], [("x", "y", "z")])
    ev = threading.Event()
    calls = []

    def progress(msg):
        calls.append(msg)
        ev.set()

    with pytest.raises(ImportCancelledError):
        st.compute_table_stats(store, "t", ["text"] * 3, cancel_event=ev, progress=progress)
    assert calls == ["Measuring column 1 of 3: a"]


def test_progress_messages(store):
    _make(store, "t", [("a", "text"), ("b", "whole")], [("x", 1)])
    calls = []
    st.compute_table_stats(store, "t", ["text", "whole_number"], progress=calls.append)
    assert calls == ["Measuring column 1 of 2: a", "Measuring column 2 of 2: b"]


def test_unknown_table_store_error_passes_through(store):
    with pytest.raises(StoreError):
        st.compute_table_stats(store, "nope", ["text"])


def test_column_warnings_stay_plain_text(store):
    _make(store, "t", [("a", "text")], [("x",)])
    res = st.compute_table_stats(store, "t", ["text"])
    assert isinstance(res.columns[0].warnings, tuple)
    assert isinstance(res.warnings, tuple)


# ---------- size of a real run ----------

def test_half_million_unique_rows_fast(store):
    n = 500_000
    _make(store, "big", [("s", "text")], [("row-%d" % i,) for i in range(n)])
    t0 = time.perf_counter()
    res = st.compute_table_stats(store, "big", ["text"])
    elapsed = time.perf_counter() - t0
    assert elapsed < 10, elapsed
    c = res.columns[0]
    assert c.rows == n
    assert c.distinct_approx <= n
    assert any("mostly unique text" in w for w in c.warnings)


class _RnListingStore:
    """Wraps a store whose columns() also lists the hidden __rn column."""

    def __init__(self, inner):
        self._inner = inner

    def columns(self, table):
        return self._inner.columns(table) + [("__rn", "whole")]

    def row_count(self, table):
        return self._inner.row_count(table)

    def execute(self, sql, params=()):
        return self._inner.execute(sql, params)


def test_hidden_rn_column_is_skipped(store):
    _make(store, "t", [("a", "text")], [("x",)])
    res = st.compute_table_stats(_RnListingStore(store), "t", ["text"])
    assert [c.name for c in res.columns] == ["a"]


# ---------------- Review Finding Repro Tests (Failing First) ----------------

def test_s1_text_column_uses_exact_count_distinct(store, monkeypatch):
    """S1: text column uses exact count(DISTINCT) so distinct_approx matches exact, and approx_count_distinct not in SQL."""
    # Build 5000 rows where exactly 4500 are distinct
    rows = [(f"val_{i}",) for i in range(4500)] + [(f"val_{i % 4500}",) for i in range(500)]
    _make(store, "t_s1", [("txt", "text")], rows)

    executed_sqls = []
    orig_execute = store.execute
    def spy_execute(sql, params=()):
        executed_sqls.append(sql)
        return orig_execute(sql, params)
    monkeypatch.setattr(store, "execute", spy_execute)

    res = st.compute_table_stats(store, "t_s1", ["text"])
    col = res.columns[0]
    assert col.distinct_approx == 4500

    # Ensure SQL contains count(DISTINCT "txt") and NOT approx_count_distinct
    assert any('count(DISTINCT "txt")' in sql for sql in executed_sqls)
    assert not any('approx_count_distinct' in sql for sql in executed_sqls)


def test_s1_non_text_column_keeps_approx_count_distinct(store, monkeypatch):
    """S1: non-text columns keep approx_count_distinct."""
    _make(store, "t_num", [("num", "whole")], [(1,), (2,)])
    executed_sqls = []
    orig_execute = store.execute
    def spy_execute(sql, params=()):
        executed_sqls.append(sql)
        return orig_execute(sql, params)
    monkeypatch.setattr(store, "execute", spy_execute)

    res = st.compute_table_stats(store, "t_num", ["whole_number"])
    assert res.rows == 2
    assert any('approx_count_distinct' in sql for sql in executed_sqls)
    assert not any('count(DISTINCT' in sql for sql in executed_sqls)


def test_s2_zero_rows_no_table_warnings_even_with_101_columns(store):
    """S2: 0-row table must produce no table-level warnings even with 101 columns."""
    _make(store, "wide_0", [(f"c{i}", "text") for i in range(101)])
    res = st.compute_table_stats(store, "wide_0", ["text"] * 101)
    assert res.rows == 0
    assert len(res.columns) == 101
    assert res.warnings == ()


def test_s3_size_warning_divisor_1024_not_1000(store, monkeypatch):
    """S3: size warning must use 1024**3 divisor and say 'GB'."""
    # Pick byte count where 1024**3 and 1000**3 format differently:
    # 2.5 * 1024**3 = 2,684,354,560 bytes.
    # 2684354560 / 1024**3 = 2.5 GB.
    # 2684354560 / 1000**3 = 2.684... = 2.7 GB.
    b = int(2.5 * 1024**3)
    _make(store, "t_size", [("a", "whole")], [(1,)])
    monkeypatch.setattr(st, "_LARGE_TABLE_BYTES", 100)
    monkeypatch.setattr(st, "_EIGHT_BYTE_LABELS", ())
    # Create a table whose sum(approx_bytes) is b
    class FakeStore:
        def columns(self, t): return [("c", "fixed")]
        def row_count(self, t): return b // 16
        def execute(self, sql, params=()): return [(0, 0, 1, 0, 0.0, 0)]
    monkeypatch.setattr(st, "_FIXED_BYTES", 16)
    res = st.compute_table_stats(FakeStore(), "fake", ["fixed"])
    assert res.approx_bytes == (b // 16) * 16
    expected_gb = ((b // 16) * 16) / (1024**3)
    wrong_gb = ((b // 16) * 16) / (1000**3)
    assert f"{expected_gb:.1f} GB" != f"{wrong_gb:.1f} GB"
    assert any(f"{expected_gb:.1f} GB" in w for w in res.warnings)


def test_s4_text_byte_size_uses_strlen_not_octet_length_encode(store, monkeypatch):
    """S4: Text byte size uses strlen instead of octet_length(encode())."""
    _make(store, "t_s4", [("s", "text")], [("é",), ("日本",), ("a\x00b",)])
    executed_sqls = []
    orig_execute = store.execute
    def spy_execute(sql, params=()):
        executed_sqls.append(sql)
        return orig_execute(sql, params)
    monkeypatch.setattr(store, "execute", spy_execute)

    res = st.compute_table_stats(store, "t_s4", ["text"])
    col = res.columns[0]
    # "é": 2 bytes, "日本": 6 bytes, "a\x00b": 3 bytes -> total = 11
    assert col.approx_bytes == 11
    assert any('strlen("s")' in sql for sql in executed_sqls)
    assert not any('octet_length' in sql for sql in executed_sqls)
    assert not any('encode' in sql for sql in executed_sqls)


def test_s5_unique_warning_requires_both_label_and_stored_type_text(store, monkeypatch):
    """S5: unique-text warning needs BOTH label 'text' and stored_type 'text'."""
    monkeypatch.setattr(st, "_UNIQUE_MIN_ROWS", 10)
    # Case 1: stored_type text, but label whole_number
    _make(store, "t_u1", [("c", "text")], [(f"v{i}",) for i in range(20)])
    res1 = st.compute_table_stats(store, "t_u1", ["whole_number"])
    assert not any("mostly unique text" in w for w in res1.columns[0].warnings)

    # Case 2: label text, but stored_type whole
    _make(store, "t_u2", [("c", "whole")], [(i,) for i in range(20)])
    res2 = st.compute_table_stats(store, "t_u2", ["text"])
    assert not any("mostly unique text" in w for w in res2.columns[0].warnings)


def test_s5_long_text_warning_requires_stored_type_text(store, monkeypatch):
    """S5: long text warning needs stored_type text."""
    monkeypatch.setattr(st, "_LONG_TEXT_CHARS", 5)
    _make(store, "t_lt", [("c", "whole")], [(1000000,)])
    res = st.compute_table_stats(store, "t_lt", ["text"])
    assert not any("characters long" in w for w in res.columns[0].warnings)


def test_s5_non_text_columns_report_empty_count_zero(store):
    """S5: non-text columns report empty_count 0 even if stored type is text-like/fallback."""
    _make(store, "t_emp", [("n", "whole")], [(1,), (None,)])
    res = st.compute_table_stats(store, "t_emp", ["whole_number"])
    assert res.columns[0].empty_count == 0



# ---------------- Round 3 (distinct clamp, exact-count gate) ----------------

def test_r3_non_text_distinct_clamped_to_rows(store, monkeypatch):
    _make(store, "t_cl", [("n", "whole")], [(1,), (2,)])
    orig = store.execute

    def spy(sql, params=()):
        rows = orig(sql, params)
        if "approx_count_distinct" in sql:
            null_count, empty_count, _distinct, *rest = rows[0]
            return [(null_count, empty_count, 999_999, *rest)]
        return rows

    monkeypatch.setattr(store, "execute", spy)
    res = st.compute_table_stats(store, "t_cl", ["whole_number"])
    assert res.rows == 2
    assert res.columns[0].distinct_approx == 2


def test_r3_exact_count_needs_text_label_and_text_stored_type(store, monkeypatch):
    _make(store, "t_x", [("a", "text"), ("b", "whole"), ("c", "text")],
          [("p", 1, "u"), ("q", 2, "v")])
    sqls = []
    orig = store.execute

    def spy(sql, params=()):
        sqls.append(sql)
        return orig(sql, params)

    monkeypatch.setattr(store, "execute", spy)
    st.compute_table_stats(store, "t_x", ["decimal_number", "text", "text"])
    by_col = {}
    for q in ("a", "b", "c"):
        by_col[q] = next(s for s in sqls if f'"{q}"' in s)
    assert "approx_count_distinct" in by_col["a"] and "count(DISTINCT" not in by_col["a"]  # text stored, number label
    assert "approx_count_distinct" in by_col["b"] and "count(DISTINCT" not in by_col["b"]  # number stored, text label
    assert 'count(DISTINCT "c")' in by_col["c"] and "approx_count_distinct" not in by_col["c"]
