"""Stage D1g Power Query step tool tests: review follow-ups for pivot and error-row steps.

Every rule is tested on a hand-checked 6 to 10 row table (or small dataset) that fails
by behaviour (AssertionError) when the rule is removed.
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path
from typing import Any

import pytest

from analytics_studio.store import DuckStore
from tools import pq_store_diff
from tools.pq_store_diff import (
    generate_step_sql,
    inspect_store_columns,
    run_pq_step_diff,
)


def _tab(headers: list[str], rows: list[list[str]], rows_2: list[list[str]] | None = None) -> dict[str, Any]:
    return {"headers": headers, "rows": rows, "rows_2": rows_2 or list(reversed(rows))}


def _run_items(dataset: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    return run_pq_step_diff(rows=len(dataset["rows"]), seed=1, dataset=dataset, items=items)


# ==============================================================================
# F1: Decimal key merging in pivot_column
# ==============================================================================


def test_f1_decimal_key_merging_refused_when_text_forms_differ() -> None:
    """When key column is converted to decimal_number/number, distinct text forms with identical value are refused."""
    dataset = _tab(
        ["k", "attr", "val"],
        [
            ["1.0", "a", "10"],
            ["1.00", "b", "20"],
            ["2", "a", "30"],
            ["2.0", "b", "40"],
            ["3", "a", "50"],
            ["4", "b", "60"],
        ],
    )
    with tempfile.TemporaryDirectory() as td:
        store = DuckStore(str(Path(td) / "store.db"))
        store.create_table("t", [(h, "text") for h in dataset["headers"]])
        store.append_rows("t", dataset["rows"])
        col_meta = inspect_store_columns(store, "t", dataset["headers"])
        prev_conv = {"op": "convert_type", "column": "k", "type": "decimal_number"}
        item = {
            "id": "f1_dec",
            "step": {"op": "pivot_column", "attribute_column": "attr", "value_column": "val", "aggregation": "count_all"},
            "prev_convert": prev_conv,
        }
        res = generate_step_sql(item, dataset["headers"], "t", 6, col_meta=col_meta, store=store)
        assert isinstance(res, pq_store_diff.Refusal)
        assert "holds decimal values whose text forms differ" in res.reason


def test_f1_decimal_key_zero_variants_refused() -> None:
    """Zero variants (0, -0, 0.0) in decimal key column are refused."""
    dataset = _tab(
        ["k", "attr", "val"],
        [
            ["0", "a", "1"],
            ["-0", "b", "2"],
            ["0.0", "a", "3"],
            ["1", "b", "4"],
            ["2", "a", "5"],
            ["3", "b", "6"],
        ],
    )
    with tempfile.TemporaryDirectory() as td:
        store = DuckStore(str(Path(td) / "store.db"))
        store.create_table("t", [(h, "text") for h in dataset["headers"]])
        store.append_rows("t", dataset["rows"])
        col_meta = inspect_store_columns(store, "t", dataset["headers"])
        prev_conv = {"op": "convert_type", "column": "k", "type": "number"}
        item = {
            "id": "f1_zero",
            "step": {"op": "pivot_column", "attribute_column": "attr", "value_column": "val", "aggregation": "none"},
            "prev_convert": prev_conv,
        }
        res = generate_step_sql(item, dataset["headers"], "t", 6, col_meta=col_meta, store=store)
        assert isinstance(res, pq_store_diff.Refusal)
        assert "holds decimal values whose text forms differ" in res.reason


# ==============================================================================
# F2: Error-row column validation (strip and duplicate rejection)
# ==============================================================================


@pytest.mark.parametrize(
    "cols",
    [["a", "a"], ["a", "b", "a"], ["a", " a"]],
)
@pytest.mark.parametrize("op", ["remove_rows_with_errors", "keep_rows_with_errors"])
def test_f2_error_rows_duplicate_columns_rejected(op: str, cols: list[str]) -> None:
    """Duplicate column names (even after stripping whitespace) raise the engine duplicate refusal."""
    dataset = _tab(["a", "b"], [["1", "x"], ["2", "y"], ["3", "z"], ["4", "w"], ["5", "u"], ["6", "v"]])
    item = {"id": "f2_dup", "step": {"op": op, "columns": cols}}
    data = _run_items(dataset, [item])
    r = data["results"][0]
    assert r["status"] == "same"
    assert r["refusal"]
    assert r["refusal_reason"] == "Transformation step 1 selects an error-check column more than once."


@pytest.mark.parametrize("col_name", ["a ", " a"])
@pytest.mark.parametrize("op", ["remove_rows_with_errors", "keep_rows_with_errors"])
def test_f2_error_rows_padded_column_names_accepted(op: str, col_name: str) -> None:
    """Padded column names in error-check steps are stripped and accepted like the engine."""
    dataset = _tab(["a", "b"], [["1", "x"], ["2", "y"], ["3", "z"], ["4", "w"], ["5", "u"], ["6", "v"]])
    item = {"id": "f2_pad", "step": {"op": op, "columns": [col_name]}}
    data = _run_items(dataset, [item])
    r = data["results"][0]
    assert r["status"] == "same"
    assert not r["refusal"]


# ==============================================================================
# F3: convert_type text/any creates no error cells (and kills E13)
# ==============================================================================


@pytest.mark.parametrize("target", ["text", "any"])
def test_f3_convert_to_text_or_any_creates_no_error_cells(target: str) -> None:
    """A genuine cell 'Error: raw' remains plain text after convert_type to text or any."""
    dataset = _tab(
        ["id", "t"],
        [
            ["1", "Error: raw"],
            ["2", "ok"],
            ["3", "Error: test"],
            ["4", "normal"],
            ["5", "fine"],
            ["6", "good"],
        ],
    )
    # With target in {text, any}, remove_rows_with_errors keeps all 6 rows because 'Error: raw' is plain text
    seq = [
        {"op": "convert_type", "column": "t", "type": target},
        {"op": "remove_rows_with_errors"},
    ]
    item = {"id": "f3_text", "step": {"op": "sequence"}, "sequence": seq}
    data = _run_items(dataset, [item])
    r = data["results"][0]
    assert r["status"] == "same"
    assert not r["refusal"]


def test_f3_mutant_e13_killed_by_unmarked_column_check() -> None:
    """E13 (every column counts as marked) causes an unmarked column holding 'Error: raw' to be treated as marked instead of refused."""
    dataset = _tab(
        ["id", "other", "t"],
        [
            ["1", "10", "Error: raw"],
            ["2", "20", "ok"],
            ["3", "30", "data"],
            ["4", "40", "more"],
            ["5", "50", "row5"],
            ["6", "60", "row6"],
        ],
    )
    with tempfile.TemporaryDirectory() as td:
        store = DuckStore(str(Path(td) / "store.db"))
        store.create_table("t", [(h, "text") for h in dataset["headers"]])
        store.append_rows("t", dataset["rows"])
        col_meta = inspect_store_columns(store, "t", dataset["headers"])
        # convert_type was on 'other', NOT on 't'
        prev_conv = {"op": "convert_type", "column": "other", "type": "whole_number"}
        item = {
            "id": "e13_test",
            "step": {"op": "remove_rows_with_errors", "columns": ["t"]},
            "prev_convert": prev_conv,
        }
        res = generate_step_sql(item, dataset["headers"], "t", 6, col_meta=col_meta, store=store)
        # Without E13: 't' is not marked, holds 'Error: raw', so store refuses.
        # With E13: 't' is treated as marked, store does NOT refuse (returns SQL tuple).
        assert isinstance(res, pq_store_diff.Refusal)
        assert "starts with the engine's error prefix" in res.reason


# ==============================================================================
# F4: Typed-category conflict in pivot after unpivot
# ==============================================================================


@pytest.mark.parametrize(
    "typ,val1,val2,out_col",
    [
        ("whole_number", "1", "1", "1"),
        ("date", "2024-01-02", "2024-01-02", "2024-01-02"),
        ("boolean", "true", "TRUE", "TRUE"),
    ],
)
def test_f4_typed_category_conflict_refused_by_name(typ: str, val1: str, val2: str, out_col: str) -> None:
    """Unpivot mixing converted column and text column into attribute produces typed conflict refusal."""
    r2 = ["r2", "2", "3"] if typ == "whole_number" else (["r2", "2024-01-03", "2024-01-04"] if typ == "date" else ["r2", "false", "FALSE"])
    dataset = _tab(
        ["id", "A", "B"],
        [
            ["r1", val1, val2],
            r2,
            ["r3", val1, "val3"],
            ["r4", val1, "val5"],
            ["r5", val1, "val7"],
            ["r6", val1, "val9"],
        ],
    )
    steps = [
        {"op": "convert_type", "column": "A", "type": typ},
        {"op": "unpivot_columns", "columns": ["A", "B"], "attribute_name": "at", "value_name": "val"},
        {"op": "pivot_column", "attribute_column": "val", "value_column": "at", "aggregation": "count_all"},
    ]
    item = {"id": f"f4_conflict_{typ}", "step": {"op": "sequence"}, "sequence": steps}
    data = _run_items(dataset, [item])
    r = data["results"][0]
    assert r["status"] == "same"
    assert r["refusal"]
    expected_msg = f"Cannot pivot: distinct typed categories in 'val' produce the same output column '{out_col}'; convert the column to text first."
    assert r["refusal_reason"] == expected_msg


# ==============================================================================
# F5: Datetime attribute column formatting
# ==============================================================================


def test_f5_datetime_attribute_column_refused_by_name() -> None:
    """A datetime attribute column produces ISO 'T' formatted headers in engine; refused by name."""
    dataset = _tab(
        ["k", "dt_attr", "val"],
        [
            ["k1", "2024-01-02 03:04:05", "10"],
            ["k2", "2024-01-03 03:04:05", "20"],
            ["k3", "2024-01-04 03:04:05", "30"],
            ["k4", "2024-01-05 03:04:05", "40"],
            ["k5", "2024-01-06 03:04:05", "50"],
            ["k6", "2024-01-07 03:04:05", "60"],
        ],
    )
    with tempfile.TemporaryDirectory() as td:
        store = DuckStore(str(Path(td) / "store.db"))
        store.create_table("t", [(h, "text") for h in dataset["headers"]])
        store.append_rows("t", dataset["rows"])
        col_meta = inspect_store_columns(store, "t", dataset["headers"])
        prev_conv = {"op": "convert_type", "column": "dt_attr", "type": "datetime"}
        item = {
            "id": "f5_dt",
            "step": {"op": "pivot_column", "attribute_column": "dt_attr", "value_column": "val", "aggregation": "count_all"},
            "prev_convert": prev_conv,
        }
        res = generate_step_sql(item, dataset["headers"], "t", 6, col_meta=col_meta, store=store)
        assert isinstance(res, pq_store_diff.Refusal)
        assert res.reason == "Datetime attribute column headers use ISO 'T' formatting in the engine; SQL uses space."


# ==============================================================================
# F6: Blank key ordering (NULL and '' first-seen order)
# ==============================================================================


def test_f6_blank_key_null_first_then_empty() -> None:
    """When NULL appears before '' in the first key column, blank groups order NULL then ''."""
    dataset = {
        "headers": ["k", "attr", "val"],
        "rows": [
            ["NULL_PLANTED", "x", "1"],
            ["", "x", "2"],
            ["b", "y", "3"],
            ["a", "y", "4"],
            ["c", "x", "5"],
            ["d", "y", "6"],
        ],
        "nulls": [[0, "k"]],
    }
    item = {"id": "f6_null_first", "step": {"op": "pivot_column", "attribute_column": "attr", "value_column": "val", "aggregation": "count_all"}}
    data = _run_items(dataset, [item])
    r = data["results"][0]
    assert r["status"] == "same"
    assert not r["refusal"]


def test_f6_blank_key_empty_first_then_null() -> None:
    """When '' appears before NULL in the first key column, blank groups order '' then NULL."""
    dataset = {
        "headers": ["k", "attr", "val"],
        "rows": [
            ["", "x", "1"],
            ["NULL_PLANTED", "x", "2"],
            ["b", "y", "3"],
            ["a", "y", "4"],
            ["c", "x", "5"],
            ["d", "y", "6"],
        ],
        "nulls": [[1, "k"]],
    }
    item = {"id": "f6_empty_first", "step": {"op": "pivot_column", "attribute_column": "attr", "value_column": "val", "aggregation": "count_all"}}
    data = _run_items(dataset, [item])
    r = data["results"][0]
    assert r["status"] == "same"
    assert not r["refusal"]


# ==============================================================================
# F8: Mutant survivors
# ==============================================================================


def test_p04_key_columns_order_not_alphabetical() -> None:
    """P04 kills mutant that sorts key_headers alphabetically (e.g. ['z_key', 'b_key'] must not become ['b_key', 'z_key'])."""
    dataset = _tab(
        ["z_key", "b_key", "cat", "val"],
        [
            ["z1", "b1", "c1", "10"],
            ["z2", "b2", "c2", "20"],
            ["z3", "b3", "c1", "30"],
            ["z4", "b4", "c2", "40"],
            ["z5", "b5", "c1", "50"],
            ["z6", "b6", "c2", "60"],
        ],
    )
    item = {"id": "p04_test", "step": {"op": "pivot_column", "attribute_column": "cat", "value_column": "val", "aggregation": "count_all"}}
    with tempfile.TemporaryDirectory() as td:
        store = DuckStore(str(Path(td) / "store.db"))
        store.create_table("t", [(h, "text") for h in dataset["headers"]])
        store.append_rows("t", dataset["rows"])
        col_meta = inspect_store_columns(store, "t", dataset["headers"])
        sql_res = generate_step_sql(item, dataset["headers"], "t", 6, col_meta=col_meta, store=store)
        assert isinstance(sql_res, tuple)
        assert sql_res[1][:2] == ["z_key", "b_key"]


def test_p08_blank_attribute_null_rejected() -> None:
    """P08 kills mutant that only checks empty string and ignores NULL in attribute column."""
    dataset = {
        "headers": ["k", "cat", "val"],
        "rows": [
            ["k1", "NULL_ATTR", "1"],
            ["k2", "x", "2"],
            ["k3", "y", "3"],
            ["k4", "x", "4"],
            ["k5", "y", "5"],
            ["k6", "x", "6"],
        ],
        "nulls": [[0, "cat"]],
    }
    item = {"id": "p08_test", "step": {"op": "pivot_column", "attribute_column": "cat", "value_column": "val", "aggregation": "count_all"}}
    data = _run_items(dataset, [item])
    r = data["results"][0]
    assert r["status"] == "same"
    assert r["refusal"]
    assert "row 1 has a blank value in 'cat'" in r["refusal_reason"]


def test_p12_p13_column_limit_512_includes_keys() -> None:
    """P12 and P13 kill mutants where 512-column limit is off by one (>=) or ignores key columns."""
    # 1 key column + 512 categories = 513 total columns -> must exceed MAX_COLUMNS (512)
    categories = [f"c{i:03d}" for i in range(1, 513)]  # 512 distinct categories
    rows = [[f"k{i%3}", categories[i], "1"] for i in range(512)]
    dataset = _tab(["k", "cat", "val"], rows)
    item = {"id": "p12_13_test", "step": {"op": "pivot_column", "attribute_column": "cat", "value_column": "val", "aggregation": "count_all"}}
    data = _run_items(dataset, [item])
    r = data["results"][0]
    assert r["status"] == "same"
    assert r["refusal"]
    assert r["refusal_reason"] == "Pivoting exceeds the 512-column import limit."

    # Exactly 512 total columns (1 key + 511 categories) must SUCCEED (kills P12 where > was mutated to >=)
    cat_511 = [f"c{i:03d}" for i in range(1, 512)]
    rows_511 = [[f"k{i%3}", cat_511[i], "1"] for i in range(511)]
    item_511 = {"id": "p12_allowed", "step": {"op": "pivot_column", "attribute_column": "cat", "value_column": "val", "aggregation": "count_all"}}
    with tempfile.TemporaryDirectory() as td:
        store = DuckStore(str(Path(td) / "store.db"))
        store.create_table("t_511", [("k", "text"), ("cat", "text"), ("val", "text")])
        store.append_rows("t_511", rows_511)
        col_meta = inspect_store_columns(store, "t_511", ["k", "cat", "val"])
        res = generate_step_sql(item_511, ["k", "cat", "val"], "t_511", 511, col_meta=col_meta, store=store)
        assert isinstance(res, tuple)


def test_p21_non_ascii_key_refusal() -> None:
    """P21 kills mutant that removes the non-ASCII key refusal (Unicode case-folding differs)."""
    dataset = _tab(
        ["k", "cat", "val"],
        [
            ["ß", "x", "1"],
            ["SS", "y", "2"],
            ["İ", "x", "3"],
            ["i", "y", "4"],
            ["Σ", "x", "5"],
            ["σ", "y", "6"],
        ],
    )
    with tempfile.TemporaryDirectory() as td:
        store = DuckStore(str(Path(td) / "store.db"))
        store.create_table("t", [(h, "text") for h in dataset["headers"]])
        store.append_rows("t", dataset["rows"])
        col_meta = inspect_store_columns(store, "t", dataset["headers"])
        item = {"id": "p21_test", "step": {"op": "pivot_column", "attribute_column": "cat", "value_column": "val", "aggregation": "count_all"}}
        res = generate_step_sql(item, dataset["headers"], "t", 6, col_meta=col_meta, store=store)
        assert isinstance(res, pq_store_diff.Refusal)
        assert "Key column 'k' holds non-ASCII text; the engine case-folds with Python rules." in res.reason


def test_p29_unsafe_header_in_category_refused() -> None:
    """P29 kills mutant that removes the unsafe header check on pivot categories."""
    dataset = _tab(
        ["k", "cat", "val"],
        [
            ["k1", 'q"q', "1"],
            ["k2", "x", "2"],
            ["k3", "y", "3"],
            ["k4", "x", "4"],
            ["k5", "y", "5"],
            ["k6", "x", "6"],
        ],
    )
    with tempfile.TemporaryDirectory() as td:
        store = DuckStore(str(Path(td) / "store.db"))
        store.create_table("t", [(h, "text") for h in dataset["headers"]])
        store.append_rows("t", dataset["rows"])
        col_meta = inspect_store_columns(store, "t", dataset["headers"])
        item = {"id": "p29_test", "step": {"op": "pivot_column", "attribute_column": "cat", "value_column": "val", "aggregation": "count_all"}}
        res = generate_step_sql(item, dataset["headers"], "t", 6, col_meta=col_meta, store=store)
        assert isinstance(res, pq_store_diff.Refusal)
        assert res.reason == pq_store_diff.QUOTE_HEADER_REASON


def test_p35_boolean_attribute_refusal() -> None:
    """P35 kills mutant that removes boolean attribute refusal."""
    dataset = _tab(
        ["k", "cat", "val"],
        [
            ["k1", "true", "1"],
            ["k2", "FALSE", "2"],
            ["k3", "true", "3"],
            ["k4", "false", "4"],
            ["k5", "TRUE", "5"],
            ["k6", "FALSE", "6"],
        ],
    )
    with tempfile.TemporaryDirectory() as td:
        store = DuckStore(str(Path(td) / "store.db"))
        store.create_table("t", [(h, "text") for h in dataset["headers"]])
        store.append_rows("t", dataset["rows"])
        col_meta = inspect_store_columns(store, "t", dataset["headers"])
        prev_conv = {"op": "convert_type", "column": "cat", "type": "boolean"}
        item = {
            "id": "p35_test",
            "step": {"op": "pivot_column", "attribute_column": "cat", "value_column": "val", "aggregation": "count_all"},
            "prev_convert": prev_conv,
        }
        res = generate_step_sql(item, dataset["headers"], "t", 6, col_meta=col_meta, store=store)
        assert isinstance(res, pq_store_diff.Refusal)
        assert res.reason == "Boolean text in the attribute column is written TRUE or FALSE by the engine, not True or False."


# ==============================================================================
# Generator pin: C03 and C04
# ==============================================================================


def test_generator_pin_c03_blank_keys_present() -> None:
    """Generator pin: D1E_KEYS must contain '' so generated tables test blank key handling."""
    assert "" in pq_store_diff.D1E_KEYS
    with tempfile.TemporaryDirectory() as td:
        csv_p = Path(td) / "d1e.csv"
        found_blank = False
        for s in range(1, 11):
            pq_store_diff.generate_d1e_csv(csv_p, s, "d1e")
            with open(csv_p, newline="", encoding="utf-8") as f:
                r = list(csv.reader(f))
                if any(row[0] == "" for row in r[1:]):
                    found_blank = True
                    break
        assert found_blank, "Generated D1e tables across seeds 1..10 must include blank keys"


def test_generator_pin_c04_blank_vals_present() -> None:
    """Generator pin: D1E_VALS must contain '' so generated tables test blank value handling."""
    assert "" in pq_store_diff.D1E_VALS
    with tempfile.TemporaryDirectory() as td:
        csv_p = Path(td) / "d1e.csv"
        found_blank = False
        for s in range(1, 11):
            pq_store_diff.generate_d1e_csv(csv_p, s, "d1e")
            with open(csv_p, newline="", encoding="utf-8") as f:
                r = list(csv.reader(f))
                if any(row[2] == "" for row in r[1:]):
                    found_blank = True
                    break
        assert found_blank, "Generated D1e tables across seeds 1..10 must include blank values"
