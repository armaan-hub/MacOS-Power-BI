"""Stage D1e: pivot_column and remove/keep_rows_with_errors (Part A items 1, 2 and 4 of D1c).

Every expected row below is written by hand from the engine's rules (`_pivot_column`, the error-row branches of
`apply_transformations`, `_aggregate_group` for count rules, `_sort_rows`). The engine must produce them (the
reference), the tool must agree (status same), and each mutant of the tool must make the run differ (status
differs, exit 1). Named refusals are checked by reason text.
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path
from typing import Any

import pytest

from analytics_studio.file_import import parse_file
from tests.test_pq_store_diff_tool import _by_id, _run_items
from tests.test_pq_store_diff_tool_d1a import _tab
from tools import pq_store_diff
from tools.pq_store_diff import (
    D1E_HEADERS,
    _d1e_catalog,
    evaluate_exit_policy,
    run_pq_step_diff_many,
)

ERR_MANY = "Error: There were too many elements in the enumeration to complete the operation."


def _pivot(attr: str, value: str, agg: str) -> dict:
    return {"op": "pivot_column", "attribute_column": attr, "value_column": value, "aggregation": agg}


def _item(item_id: str, step: dict) -> dict:
    return {"id": item_id, "step": step}


def _seq(item_id: str, steps: list[dict]) -> dict:
    return {"id": item_id, "step": {"op": "sequence"}, "sequence": steps}


def _engine(dataset: dict, item: dict) -> Any:
    """The step engine's result on the dataset: (headers, rows), or the engine's error text."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "t.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(dataset["headers"])
            w.writerows(dataset["rows"])
        return pq_store_diff.execute_engine_step(item, parse_file(path), None)


def _assert_hand_rows(dataset: dict, item: dict, expected_headers: list[str], expected_rows: list[list[str | None]]) -> None:
    """The engine returns the hand-checked result, the tool agrees (status same, no refusal)."""
    result = _engine(dataset, item)
    assert result == (expected_headers, expected_rows), result
    data = _run_items(dataset, [item])
    row = _by_id(data, item["id"])
    assert row["status"] == "same" and row["refusal"] is None, row
    code, _ = evaluate_exit_policy(data, {"classes": []})
    assert code == 0


def _assert_engine_error(dataset: dict, item: dict, message: str) -> None:
    """The engine raises the hand-checked message, the tool refuses with the same engine text (status same)."""
    result = _engine(dataset, item)
    assert isinstance(result, str) and result == message, result
    data = _run_items(dataset, [item])
    row = _by_id(data, item["id"])
    assert row["status"] == "same", row


def _assert_engine_refusal(dataset: dict, item: dict, part: str) -> None:
    """The engine raises an error containing `part`; the tool refuses with that engine text (status same)."""
    result = _engine(dataset, item)
    assert isinstance(result, str) and part in result, result
    row = _by_id(_run_items(dataset, [item]), item["id"])
    assert row["status"] == "same", row


def _assert_named_refusal(dataset: dict, item: dict, reason_part: str) -> None:
    """The engine accepts the step, the tool refuses by name (a named limit, not a hidden skip)."""
    data = _run_items(dataset, [item])
    row = _by_id(data, item["id"])
    assert row["status"] == "refused", row
    assert row["refusal_reason"] and reason_part in row["refusal_reason"], row


def _assert_mutant_differs_and_exits_1(dataset: dict, item: dict, mutant: str) -> None:
    # One tool call with two override sets (clean, mutant): one database build, the same comparison as two runs.
    clean, data = run_pq_step_diff_many(0, 42, [{}, {mutant: True}], dataset=dataset, items=[item])
    assert _by_id(clean, item["id"])["status"] == "same", _by_id(clean, item["id"])
    status = _by_id(data, item["id"])["status"]
    assert status != "same", f"{mutant} survived"
    code, msgs = evaluate_exit_policy(data, {"classes": []})
    assert code == 1 and msgs, (status, msgs)


# ------------------------------------------------------------------ pivot_column: hand-checked rows (6 rows)
# Keys k; attribute a (x, y, z first seen in that order); value v (one blank value in row 2).
PIV = _tab(["k", "a", "v"], [
    ["1", "x", "5"], ["2", "y", ""], ["1", "x", "7"], ["3", "x", "4"], ["2", "z", "9"], ["1", "y", "1"],
])


def test_pivot_none_hand_checked() -> None:
    # k=1, x has two members (an Expression.Error cell); the blank value of row 2 is kept as ''.
    _assert_hand_rows(PIV, _item("pv_none", _pivot("a", "v", "none")), ["k", "x", "y", "z"], [
        ["1", ERR_MANY, "1", None],
        ["2", None, "", "9"],
        ["3", "4", None, None],
    ])


def test_pivot_count_all_hand_checked() -> None:
    _assert_hand_rows(PIV, _item("pv_count_all", _pivot("a", "v", "count_all")), ["k", "x", "y", "z"], [
        ["1", "2", "1", None],
        ["2", None, "1", "1"],
        ["3", "1", None, None],
    ])


def test_pivot_count_non_blank_hand_checked() -> None:
    # The blank value of row 2 is a member for count_all and not for count_non_blank.
    _assert_hand_rows(PIV, _item("pv_cnb", _pivot("a", "v", "count_non_blank")), ["k", "x", "y", "z"], [
        ["1", "2", "1", None],
        ["2", None, "0", "1"],
        ["3", "1", None, None],
    ])


# ------------------------------------------------------------------ pivot_column: order, names, blanks (6 to 8 rows)
SORT_TEXT = _tab(["k", "a", "v"], [["b", "x", "1"], ["a", "x", "2"], ["A", "y", "3"], ["", "x", "4"]])
SORT_NUM = _tab(["k", "a", "v"], [["10", "x", "1"], ["9", "x", "2"], ["-1", "y", "3"], ["", "y", "4"]])


def test_pivot_key_order_is_case_folded_with_blank_last() -> None:
    # Text keys: 'a' before 'A' (first-seen tie), 'b', and the blank key last.
    _assert_hand_rows(SORT_TEXT, _item("pv_sort_text", _pivot("a", "v", "count_all")), ["k", "x", "y"], [
        ["a", "1", None],
        ["A", None, "1"],
        ["b", "1", None],
        ["", "1", None],
    ])


def test_pivot_key_order_is_numeric_when_every_key_parses() -> None:
    _assert_hand_rows(SORT_NUM, _item("pv_sort_num", _pivot("a", "v", "count_all")), ["k", "x", "y"], [
        ["-1", None, "1"],
        ["9", "1", None],
        ["10", "1", None],
        ["", None, "1"],
    ])


def test_pivot_empty_table_with_keys_has_no_rows() -> None:
    empty = _tab(["k", "a", "v"], [])
    _assert_hand_rows(empty, _item("pv_empty", _pivot("a", "v", "count_all")), ["k"], [])


def test_pivot_empty_table_without_keys_is_an_error() -> None:
    empty = _tab(["a", "v"], [])
    _assert_engine_error(empty, _item("pv_empty_nokey", _pivot("a", "v", "count_all")),
                         "Cannot pivot an empty table without remaining key columns.")


def test_pivot_blank_attribute_is_the_engine_error_at_its_row() -> None:
    blank = _tab(["k", "a", "v"], [["1", "x", "5"], ["2", "   ", "6"], ["3", "x", "7"]])
    _assert_engine_error(blank, _item("pv_blank", _pivot("a", "v", "none")),
                         "Cannot pivot: row 2 has a blank value in 'a'.")


def test_pivot_output_name_equal_to_key_is_an_error() -> None:
    clash = _tab(["k", "a", "v"], [["1", "k", "5"], ["2", "z", "6"]])
    _assert_engine_error(clash, _item("pv_clash", _pivot("a", "v", "count_all")),
                         "Cannot pivot: output column 'k' conflicts with an existing key column.")


def test_pivot_more_than_512_output_columns_is_an_error() -> None:
    wide = _tab(["a", "v"], [[f"c{i:03d}", "1"] for i in range(1, 514)])
    _assert_engine_error(wide, _item("pv_wide", _pivot("a", "v", "count_all")),
                         "Pivoting exceeds the 512-column import limit.")


def test_pivot_names_differing_only_by_case_are_a_named_refusal() -> None:
    # The engine keeps 'red' and 'RED' as two columns; DuckDB cannot hold both, so the tool refuses by name.
    cased = _tab(["k", "a", "v"], [["1", "red", "5"], ["1", "RED", "6"]])
    _assert_named_refusal(cased, _item("pv_case", _pivot("a", "v", "count_all")), "differ only by letter case")


def test_pivot_decimal_aggregations_are_named_refusals() -> None:
    for agg in ("sum", "average", "median", "min", "max"):
        _assert_named_refusal(PIV, _item(f"pv_{agg}", _pivot("a", "v", agg)), f"pivot aggregation {agg!r}")


def test_pivot_padded_names_are_trimmed_like_the_engine() -> None:
    padded = _pivot(" a ", " v ", " count_all ")
    _assert_hand_rows(PIV, _item("pv_padded", padded), ["k", "x", "y", "z"], [
        ["1", "2", "1", None],
        ["2", None, "1", "1"],
        ["3", "1", None, None],
    ])


def test_pivot_error_text_in_the_attribute_after_convert_type_is_the_engine_error() -> None:
    # convert_type to boolean makes every cell of 'a' an error cell; the pivot reports row 1.
    item = _seq("pv_seq_attr_error", [
        {"op": "convert_type", "column": "a", "type": "boolean"}, _pivot("a", "v", "count_all"),
    ])
    _assert_engine_error(PIV, item, "Cannot pivot: row 1 of 'a' contains an error.")


def test_pivot_error_text_in_the_key_after_convert_type_is_the_engine_error() -> None:
    keyed = _tab(["key", "a", "v"], [["p", "x", "5"], ["q", "y", "6"]])
    item = _seq("pv_seq_key_error", [
        {"op": "convert_type", "column": "key", "type": "whole_number"}, _pivot("a", "v", "count_all"),
    ])
    _assert_engine_error(keyed, item, "Cannot pivot: row 1 of key column 'key' contains an error.")


def test_pivot_text_that_looks_like_an_error_cell_is_a_named_refusal() -> None:
    raw = _tab(["k", "a", "v"], [["1", "Error: raw", "5"], ["2", "y", "6"]])
    _assert_named_refusal(raw, _item("pv_raw_prefix", _pivot("a", "v", "none")), "error prefix")


def test_pivot_shape_refusals_name_the_engine_text() -> None:
    _assert_engine_refusal(PIV, _item("pv_same", _pivot("a", "a", "none")), "must use different attribute and value columns.")
    _assert_engine_refusal(PIV, _item("pv_agg", _pivot("a", "v", "bogus")), "has an unsupported pivot aggregation.")
    _assert_engine_refusal(PIV, _item("pv_miss", _pivot("zz", "v", "none")), "Column 'zz' does not exist.")
    _assert_engine_refusal(PIV, _item("pv_blank_field", _pivot("a", "v", "   ")),
                           "needs an attribute, value, and aggregation choice.")


# ------------------------------------------------------------------ remove and keep rows with errors (6 to 8 rows)
# convert_type to decimal makes row 2 ('x') and row 4 ('') error cells; the other rows are numbers.
ERR_TABLE = _tab(["n", "k"], [["1", "a"], ["x", "b"], ["2", "c"], ["", "d"], ["3.5", "e"]])


def _decimal_error(text: str, row: int) -> str:
    return f"Error: Cannot convert value '{text}' in row {row} of column 'n' to decimal_number."


CONVERTED = [
    ["1", "a"], [_decimal_error("x", 2), "b"], ["2", "c"], [_decimal_error("", 4), "d"], ["3.5", "e"],
]


def test_convert_then_remove_rows_with_errors_hand_checked() -> None:
    item = _seq("rm_seq", [{"op": "convert_type", "column": "n", "type": "decimal_number"},
                           {"op": "remove_rows_with_errors"}])
    _assert_hand_rows(ERR_TABLE, item, ["n", "k"], [["1", "a"], ["2", "c"], ["3.5", "e"]])


def test_convert_then_keep_rows_with_errors_hand_checked() -> None:
    item = _seq("keep_seq", [{"op": "convert_type", "column": "n", "type": "decimal_number"},
                             {"op": "keep_rows_with_errors"}])
    _assert_hand_rows(ERR_TABLE, item, ["n", "k"], [[_decimal_error("x", 2), "b"], [_decimal_error("", 4), "d"]])


def test_convert_then_remove_with_columns_checks_only_the_listed_column() -> None:
    item = _seq("rm_cols_seq", [{"op": "convert_type", "column": "n", "type": "decimal_number"},
                                {"op": "remove_rows_with_errors", "columns": ["n"]}])
    _assert_hand_rows(ERR_TABLE, item, ["n", "k"], [["1", "a"], ["2", "c"], ["3.5", "e"]])


def test_remove_with_empty_column_list_keeps_every_row() -> None:
    item = _seq("rm_empty_seq", [{"op": "convert_type", "column": "n", "type": "decimal_number"},
                                 {"op": "remove_rows_with_errors", "columns": []}])
    _assert_hand_rows(ERR_TABLE, item, ["n", "k"], CONVERTED)


def test_keep_with_empty_column_list_keeps_no_row() -> None:
    item = _seq("keep_empty_seq", [{"op": "convert_type", "column": "n", "type": "decimal_number"},
                                   {"op": "keep_rows_with_errors", "columns": []}])
    _assert_hand_rows(ERR_TABLE, item, ["n", "k"], [])


def test_raw_text_without_convert_has_no_error_rows() -> None:
    raw = _tab(["n", "k"], [["x", "a"], ["", "b"]])
    _assert_hand_rows(raw, _item("rm_raw", {"op": "remove_rows_with_errors"}), ["n", "k"], [["x", "a"], ["", "b"]])
    _assert_hand_rows(raw, _item("keep_raw", {"op": "keep_rows_with_errors"}), ["n", "k"], [])


def test_null_cell_after_convert_is_kept_by_remove_and_dropped_by_keep() -> None:
    # Row 2 of 'n' is a NULL cell (the dataset seam writes it); convert_type keeps a NULL as NULL, which is no error.
    nulled = {**ERR_TABLE, "nulls": [[1, "n"]]}
    remove = _seq("rm_null", [{"op": "convert_type", "column": "n", "type": "decimal_number"},
                              {"op": "remove_rows_with_errors"}])
    keep = _seq("keep_null", [{"op": "convert_type", "column": "n", "type": "decimal_number"},
                              {"op": "keep_rows_with_errors"}])
    for item in (remove, keep):
        row = _by_id(_run_items(nulled, [item]), item["id"])
        assert row["status"] == "same", row


def test_error_rows_refusals_by_name() -> None:
    _assert_engine_error(ERR_TABLE, _item("rm_missing", {"op": "remove_rows_with_errors", "columns": ["zz"]}),
                         "Error-check column 'zz' does not exist.")
    _assert_engine_refusal(ERR_TABLE, _item("keep_not_list", {"op": "keep_rows_with_errors", "columns": "n"}),
                           "needs a list of error-check column names.")
    _assert_engine_refusal(ERR_TABLE, _item("rm_extra", {"op": "remove_rows_with_errors", "culture": "en-US"}),
                           "has missing or unsupported fields.")
    raw = _tab(["n", "k"], [["Error: raw", "a"]])
    _assert_named_refusal(raw, _item("rm_prefix", {"op": "remove_rows_with_errors"}), "error prefix")


def test_pivot_then_remove_rows_with_errors_is_a_named_refusal() -> None:
    # The pivot's 'none' text for a repeated pair starts with the error prefix: the store cannot tell it from an error.
    item = _seq("pv_then_rm", [_pivot("a", "v", "none"), {"op": "remove_rows_with_errors"}])
    _assert_named_refusal(PIV, item, "error prefix")


# ------------------------------------------------------------------ mutants (tool level, each by behaviour)
PIVOT_MUTANTS = [
    ("mutant_pivot_no_attr_error_check", _seq("m_attr", [{"op": "convert_type", "column": "a", "type": "boolean"},
                                                          _pivot("a", "v", "count_all")]), PIV),
    ("mutant_pivot_no_blank_check", _pivot("a", "v", "count_all"),
     _tab(["k", "a", "v"], [["1", "x", "5"], ["2", "", "6"]])),
    ("mutant_pivot_no_collision_check", _pivot("a", "v", "count_all"),
     _tab(["k", "a", "v"], [["1", "k", "5"], ["2", "z", "6"]])),
    ("mutant_pivot_order_first_seen", _pivot("a", "v", "count_all"), SORT_TEXT),
    ("mutant_pivot_sort_case_sensitive", _pivot("a", "v", "count_all"), SORT_TEXT),
    ("mutant_pivot_blank_key_first", _pivot("a", "v", "count_all"), SORT_TEXT),
    ("mutant_pivot_none_first_member", _pivot("a", "v", "none"), PIV),
    ("mutant_pivot_count_non_blank_counts_blank", _pivot("a", "v", "count_non_blank"), PIV),
    ("mutant_pivot_missing_is_zero", _pivot("a", "v", "count_all"), PIV),
    ("mutant_pivot_columns_alpha", _pivot("a", "v", "count_all"),
     _tab(["k", "a", "v"], [["1", "z", "5"], ["1", "b", "6"]])),
]


@pytest.mark.parametrize("mutant,step,dataset", PIVOT_MUTANTS, ids=[m[0] for m in PIVOT_MUTANTS])
def test_pivot_mutant_differs_and_exits_1(mutant: str, step: dict, dataset: dict) -> None:
    item = step if "sequence" in step else _item("m", step)
    _assert_mutant_differs_and_exits_1(dataset, item, mutant)


ERROR_MUTANTS = [
    ("mutant_error_rows_missing_skipped", {"op": "remove_rows_with_errors", "columns": ["zz"]}, ERR_TABLE),
    ("mutant_error_rows_first_column_only", {"op": "remove_rows_with_errors", "columns": ["n", "k"]},
     _tab(["n", "k"], [["1", "p"], ["2", "q"], ["3", "r"]])),
    ("mutant_error_rows_empty_list_inverted", {"op": "remove_rows_with_errors", "columns": []}, ERR_TABLE),
]


@pytest.mark.parametrize("mutant,step,dataset", ERROR_MUTANTS, ids=[m[0] for m in ERROR_MUTANTS])
def test_error_rows_mutant_differs_and_exits_1(mutant: str, step: dict, dataset: dict) -> None:
    # convert 'k' (the second listed column): its error cells are the only error cells, so only a check of every column catches it
    converted = "k" if mutant == "mutant_error_rows_first_column_only" else "n"
    seq = _seq("m_err", [{"op": "convert_type", "column": converted, "type": "decimal_number"}, step])
    _assert_mutant_differs_and_exits_1(dataset, seq, mutant)


def test_error_rows_keep_empty_list_inverted_differs() -> None:
    seq = _seq("m_keep_empty", [{"op": "convert_type", "column": "n", "type": "decimal_number"},
                                {"op": "keep_rows_with_errors", "columns": []}])
    _assert_mutant_differs_and_exits_1(ERR_TABLE, seq, "mutant_error_rows_empty_list_inverted")


# ------------------------------------------------------------------ catalog shape: every D1e item runs (no sql-error)
def test_d1e_catalog_runs_without_sql_errors_on_small_tables() -> None:
    data = pq_store_diff.run_pq_step_diff(rows=40, seed=3, items=_d1e_catalog())
    statuses = {r["status"] for r in data["results"]}
    assert statuses <= {"same", "refused"}, statuses
    assert all(r["status"] == "same" or r["refusal_reason"] for r in data["results"])
    assert len(data["results"]) == len(_d1e_catalog())


def test_d1e_headers_are_the_generated_table_columns() -> None:
    assert D1E_HEADERS == ["e_key", "e_cat", "e_val", "e_txt"]
