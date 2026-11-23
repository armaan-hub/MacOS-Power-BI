"""Differential tests: detect_column_types on a store must equal infer_column_types on the rows."""

import random
import threading

import pytest

from analytics_studio.file_import import ImportCancelledError
from analytics_studio.store import DuckStore
from analytics_studio.store.base import StoreError
from analytics_studio.transformations import infer_column_types
from analytics_studio.store.type_detect import detect_column_types

SIZES = (50, 500, 5000)


def _store_with(tmp_path, name, headers, column_values):
    """Load an all-text table. column_values[h] is a list of str/None, one per row."""
    store = DuckStore(str(tmp_path / f"{name}.duckdb"))
    store.create_table("t", [(h, "text") for h in headers])
    count = len(column_values[headers[0]]) if headers else 0
    if count:
        store.append_rows(
            "t",
            [[column_values[h][i] for h in headers] for i in range(count)],
        )
    return store


def _expected(headers, column_values):
    count = len(column_values[headers[0]]) if headers else 0
    rows = [{h: column_values[h][i] for h in headers} for i in range(count)]
    return infer_column_types(headers, rows)


def kwargs_for_old(kwargs):
    """Only sample_size is shared with the old function; cancel/progress/cap are ours."""
    return {k: v for k, v in kwargs.items() if k == "sample_size"}


def _check(tmp_path, headers, column_values, **kwargs):
    store = _store_with(tmp_path, "check", headers, column_values)
    try:
        got = detect_column_types(store, "t", **kwargs)
    finally:
        store.close()
    count = len(column_values[headers[0]])
    rows = [{h: column_values[h][i] for h in headers} for i in range(count)]
    expected = infer_column_types(headers, rows, **kwargs_for_old(kwargs))
    assert list(got) == headers
    assert got == expected
    return got


def _cyc(values):
    return lambda n: [values[i % len(values)] for i in range(n)]


def _seq(fmt):
    return lambda n: [fmt(i) for i in range(n)]


def _at(base, pos, odd):
    """Base column with one odd value at row ``pos`` (only when the table is long enough)."""
    def build(n):
        values = base(n)
        if pos < n:
            values[pos] = odd
        return values
    return build


CASES = {
    "whole": _seq(lambda i: str(i * 7 - 100)),
    "whole_plus_sign": _cyc(["+5", "-3", "0", "12"]),
    "negative": _seq(lambda i: str(-i)),
    "negative_zero": _cyc(["-0", "7"]),
    "decimals": _cyc(["1.5", "2.25", "-0.5", "10.0"]),
    "sci_e5": _cyc(["1e5", "2.5E3", "1E-3"]),
    "dot_leading": _cyc([".5", "-.5", "0.25"]),
    "dot_trailing": _cyc(["5.", "7."]),
    "nan_inf_words": _cyc(["Infinity", "NaN", "-inf", "inf"]),
    "underscore_digits": _cyc(["1_000", "2_500"]),
    "padded_spaces": _cyc([" 12 ", "7 "]),
    "fullwidth_digits": _cyc(["１２３", "４５"]),
    "leading_zeros": _cyc(["0012", "0100"]),
    "int16_digits": _cyc(["1234567890123456", "2"]),
    "int15_digits": _cyc(["123456789012345", "99"]),
    "comma_decimal": _cyc(["1,5", "2,25"]),
    "european_thousands": _cyc(["1.234,5", "2.000,00"]),
    "dollar_sign": _cyc(["$5", "$10"]),
    "percent_sign": _cyc(["5%", "10%"]),
    "bools_case": _cyc(["true", "false", "True", "FALSE"]),
    "bool_with_yes": _cyc(["true", "yes", "false"]),
    "iso_dates": _seq(lambda i: f"2026-01-{i % 28 + 1:02d}"),
    "iso_datetime_T": _seq(lambda i: f"2026-01-01T10:{i % 60:02d}:00"),
    "iso_datetime_space": _seq(lambda i: f"2026-01-01 10:{i % 60:02d}:00"),
    "iso_datetime_Z": _seq(lambda i: f"2026-01-01T10:{i % 60:02d}:00Z"),
    "iso_datetime_offset": _seq(lambda i: f"2026-01-01T10:{i % 60:02d}:00+04:00"),
    "date_then_datetime_late": _at(_seq(lambda i: "2026-01-01"), 250, "2026-01-01T10:00:00"),
    "times_hhmm": _cyc(["10:30", "09:15"]),
    "times_digits_only": _cyc(["10", "11"]),
    "time_2400": _cyc(["24:00", "10:00"]),
    "invalid_date_month13": _cyc(["2026-13-01", "2026-02-01"]),
    "text_after_row_3000": _at(_cyc(["1", "2", "3"]), 3000, "abc"),
    "whole_then_decimal_4000": _at(_cyc(["1", "2"]), 4000, "1.5"),
    "numeric_then_leading0_4500": _at(_cyc(["1", "2"]), 4500, "0045"),
    "numeric_then_leading0_early": _at(_cyc(["1", "2"]), 10, "0045"),
    "empty_strings": _cyc([""]),
    "all_null": lambda n: [None] * n,
    "blanks_and_nulls": _cyc(["", None, "5", "7"]),
    "text_long": _cyc(["a" * 5000, "b"]),
    "unicode_text": _cyc(["Zoë", "日本語", "Ärger"]),
    "numeric_only_in_sample": lambda n: [str(i) if i < 200 else ("" if i % 2 else "x") for i in range(n)],
    "huge_exponent": _cyc(["1e400", "2"]),
    "slash_dates": _cyc(["01/02/2026", "03/04/2026"]),
    "nan_late": _at(_cyc(["1", "2"]), 300, "NaN"),
    "bool_then_text_late": _at(_cyc(["true", "false"]), 260, "maybe"),
    "time_with_letters": _cyc(["10:30pm", "11:00"]),
}

IDENTIFIER_HEADERS = [
    "id", "Customer ID", "ZIP", "code", "ProductKey", "Order No", "Reference",
    "phone", "trn", "serial", "item_number", "invoice ref", "orderKey", "stock code",
]
NUMERIC_DATA = {
    "digits": _cyc(["12", "0034", "7"]),
    "plain": _cyc(["42", "43", "44"]),
    "long": _cyc(["1234567890123456", "9"]),
}


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("case", sorted(CASES))
def test_case_matches_old_function(tmp_path, case, size):
    values = CASES[case](size)
    _check(tmp_path, ["value"], {"value": values})


@pytest.mark.parametrize("size", [1, 2, 0])
@pytest.mark.parametrize("case", ["whole", "decimals", "bools_case", "iso_dates", "empty_strings"])
def test_tiny_tables(tmp_path, case, size):
    values = CASES[case](size) if size else []
    if size == 0:
        store = DuckStore(str(tmp_path / "empty.duckdb"))
        store.create_table("t", [("value", "text")])
        try:
            assert detect_column_types(store, "t") == infer_column_types(["value"], [])
        finally:
            store.close()
        return
    _check(tmp_path, ["value"], {"value": values})


@pytest.mark.parametrize("size", SIZES)
@pytest.mark.parametrize("header", IDENTIFIER_HEADERS)
@pytest.mark.parametrize("data", sorted(NUMERIC_DATA))
def test_identifier_headers_with_numeric_data(tmp_path, header, data, size):
    _check(tmp_path, [header], {header: NUMERIC_DATA[data](size)})


@pytest.mark.parametrize("size", SIZES)
def test_suffix_headers_and_decimal_control(tmp_path, size):
    headers = ["unit price", "amount", "account number", "rebate ref", "barcode", "Price"]
    cols = {
        "unit price": _cyc(["1.5", "2"])(size),
        "amount": _cyc(["3", "4"])(size),
        "account number": _cyc(["3", "4"])(size),
        "rebate ref": _cyc(["3.5", "4"])(size),
        "barcode": _cyc(["1", "2"])(size),
        "Price": _cyc(["10", "20"])(size),
    }
    _check(tmp_path, headers, cols)


@pytest.mark.parametrize("size", SIZES)
def test_all_cases_side_by_side(tmp_path, size):
    headers = list(CASES)
    cols = {h: CASES[h](size) for h in headers}
    _check(tmp_path, headers, cols)


@pytest.mark.parametrize("sample_size", [1, 10, 200])
def test_non_default_sample_size_matches(tmp_path, sample_size):
    headers = list(CASES)
    cols = {h: CASES[h](500) for h in headers}
    _check(tmp_path, headers, cols, sample_size=sample_size)


# ---- Monotone shortcut, random pools, many columns -----------------------

_POOLS = {
    "whole": ["0", "1", "-5", "+7", "123"],
    "decimal": ["1.5", "2", "-0.25", ".5", "1e5"],
    "leading0": ["0012", "7"],
    "long": ["1234567890123456"],
    "bool": ["true", "false", "TRUE"],
    "bool_mixed": ["yes", "no"],
    "date": ["2026-01-02", "2026-03-04"],
    "datetime": ["2026-01-02T10:00:00", "2026-01-02 10:00", "2026-01-02T10:00:00Z", "2026-01-02T10:00:00+04:00"],
    "time": ["10:30", "10", "24:00", "09:15:00"],
    "text": ["abc", "Zoë", "x y"],
    "invalid": ["2026-13-01", "1,5", "$5", "5%", "NaN", "Infinity", " 12 ", "１２"],
}
_ODD = ["abc", "2026-13-01", "1,5", "NaN", "0045", "true", "10:30pm", "2026-01-02T10:00:00Z", "1.5", "x"]
_HEADER_HINTS = ["amount", "price", "name", "note", "code", "id", "ref", "qty"]


def _random_column(rng, size):
    """One column: first 200 rows drawn from one pool mix, the rest from another, odd value past 200."""
    names = list(_POOLS)
    if rng.random() < 0.5:
        # Half the columns come from clean families so non-text types are exercised too.
        clean = ["whole", "decimal", "leading0", "long", "bool", "date", "datetime", "time"]
        names = clean
    first_pools = rng.sample(names, rng.randint(1, 3))
    later_pools = rng.sample(names, rng.randint(1, 3))
    split = rng.choice([min(200, size), size])
    values = []
    for i in range(size):
        pools = first_pools if i < split else later_pools
        if rng.random() < 0.05:
            values.append(rng.choice(["", None]))
        else:
            values.append(rng.choice(_POOLS[rng.choice(pools)]))
    if size > 201 and rng.random() < 0.4:
        values[rng.randint(200, size - 1)] = rng.choice(_ODD)
    return values


@pytest.mark.parametrize("size", SIZES)
def test_random_fuzz_300_columns(tmp_path, size):
    rng = random.Random(20261123 + size)
    headers = [f"{rng.choice(_HEADER_HINTS)} {i}" for i in range(300)]
    cols = {h: _random_column(rng, size) for h in headers}
    store = _store_with(tmp_path, "fuzz", headers, cols)
    try:
        got = detect_column_types(store, "t")
    finally:
        store.close()
    rows_all = [{h: cols[h][i] for h in headers} for i in range(size)]
    expected = infer_column_types(headers, rows_all)
    assert list(got) == headers
    mismatches = [h for h in headers if got[h] != expected[h]]
    assert mismatches == []
    for h in headers:
        first = [{h: cols[h][i]} for i in range(min(200, size))]
        if infer_column_types([h], first)[h] == "text":
            assert got[h] == "text", h


def test_monotone_text_shortcut_on_random_columns(tmp_path):
    rng = random.Random(7)
    checked = 0
    for trial in range(40):
        size = rng.choice([250, 600])
        headers = [f"v{trial}_{i}" for i in range(20)]
        cols = {h: _random_column(rng, size) for h in headers}
        for h in headers:
            sample_result = infer_column_types([h], [{h: v} for v in cols[h][:200]])[h]
            if sample_result == "text":
                full = infer_column_types([h], [{h: v} for v in cols[h]])[h]
                assert full == "text", h
                checked += 1
    assert checked > 100


# ---- Behaviour, errors, cancel, progress ---------------------------------

def test_progress_reports_each_column(tmp_path):
    headers = ["a", "b", "c"]
    cols = {"a": CASES["whole"](300), "b": CASES["decimals"](300), "c": CASES["iso_dates"](300)}
    messages = []
    got = _check(tmp_path, headers, cols, progress=messages.append)
    assert got == {"a": "whole_number", "b": "decimal_number", "c": "date"}
    assert messages == [f"Detected types for column {i} of 3..." for i in (1, 2, 3)]


def test_cancel_after_first_column(tmp_path):
    headers = ["a", "b", "c"]
    cols = {h: CASES["whole"](300) for h in headers}
    store = _store_with(tmp_path, "cancel", headers, cols)
    event = threading.Event()
    try:
        with pytest.raises(ImportCancelledError):
            detect_column_types(
                store, "t", cancel_event=event, progress=lambda _msg: event.set()
            )
    finally:
        store.close()


def test_max_distinct_values_raises(tmp_path):
    # Numeric sample, then 300 distinct non-numeric values after row 200.
    values = [str(i) for i in range(200)] + [f"w{i}" for i in range(300)]
    store = _store_with(tmp_path, "cap", ["big"], {"big": values})
    try:
        with pytest.raises(ValueError, match="Column 'big' has more than 100 distinct values"):
            detect_column_types(store, "t", max_distinct_values=100)
        # Same data under the default cap is fine and matches the old function.
        assert detect_column_types(store, "t") == _expected(["big"], {"big": values})
    finally:
        store.close()


def test_unknown_table_raises(tmp_path):
    store = _store_with(tmp_path, "unknown", ["a"], {"a": ["1"]})
    try:
        with pytest.raises(StoreError):
            detect_column_types(store, "missing")
    finally:
        store.close()


def test_non_text_column_raises(tmp_path):
    store = DuckStore(str(tmp_path / "typed.duckdb"))
    store.create_table("t", [("a", "text"), ("n", "whole")])
    try:
        with pytest.raises(StoreError, match="not 'text'"):
            detect_column_types(store, "t")
    finally:
        store.close()
