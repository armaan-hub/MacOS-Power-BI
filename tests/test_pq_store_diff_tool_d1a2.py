"""Stage D1a2: mutant-killing tests for the D1a steps (hand-checked tables, behaviour only).

Every test states its expected rows by hand. The engine must produce them (the reference), the tool must agree
(status same), and each mutant of the tool must fail the run (status not same, exit 1).
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path
from typing import Any

import pytest

from analytics_studio.file_import import parse_file
from tests.test_pq_store_diff_tool import _by_id, _engine_rows, _run_items
from tests.test_pq_store_diff_tool_d1a import _tab
from tools import pq_store_diff
from tools.pq_store_diff import evaluate_exit_policy, run_pq_step_diff_many

NBSP = " "


def _engine_error(dataset: dict[str, Any], item: dict[str, Any]) -> str:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "t.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(dataset["headers"])
            w.writerows(dataset["rows"])
        res = pq_store_diff.execute_engine_step(item, parse_file(path), None)
        assert isinstance(res, str), f"engine did not refuse: {res and len(res)}"
        return res


def _assert_hand_refusal(dataset: dict[str, Any], item: dict[str, Any], engine_text: str) -> None:
    """Hand-checked refusal: the engine raises `engine_text`; the tool refuses with the same text (status same)."""
    assert engine_text in _engine_error(dataset, item)
    data = _run_items(dataset, [item])
    row = _by_id(data, item["id"])
    assert row["status"] == "same", row
    assert row["refusal_reason"] and engine_text in row["refusal_reason"], row
    code, _ = evaluate_exit_policy(data, {"classes": [], "refused": [item["id"]]})
    assert code == 0


def _assert_hand_rows(dataset: dict[str, Any], item: dict[str, Any], expected: list[list[str | None]]) -> None:
    """Hand-checked rows: the engine returns `expected`, the tool agrees (status same, no refusal)."""
    assert _engine_rows(dataset, item) == expected
    data = _run_items(dataset, [item])
    row = _by_id(data, item["id"])
    assert row["status"] == "same" and row["refusal"] is None, row
    code, _ = evaluate_exit_policy(data, {"classes": []})
    assert code == 0


# A hand table with every kind of cell the conditional tests need (blank, NBSP-padded number, 1_000, text).
COND_TABLE = _tab(
    ["t", "n", "m"],
    [
        ["Apple", "5", "5.0"],
        ["apple", "10", "9"],
        ["", "", "q"],
        ["Banana", "2", "x"],
        ["Ban", f"{NBSP}3", "Ban"],
        ["Cherry", "1_000", "999"],
    ],
)


def _cond(clauses: list[dict[str, str]], else_value: str = "other", else_kind: str = "value") -> dict[str, Any]:
    return {"op": "conditional_column", "name": "hit", "clauses": clauses, "else_value": else_value, "else_kind": else_kind}


def _clause(column: str, op: str, value: str, kind: str, out: str = "Y", out_kind: str = "value") -> dict[str, str]:
    return {"column": column, "operator": op, "test_value": value, "test_value_kind": kind, "output": out, "output_kind": out_kind}


def _engine_result(dataset: dict[str, Any], item: dict[str, Any]) -> tuple[list[str], list[list[str | None]]]:
    """Engine (headers, rows) for a hand table with NULL cells: `dataset["nulls"]` = [[row index, column], ...]."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "t.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(dataset["headers"])
            w.writerows(dataset["rows"])
        cand = parse_file(path)
        for row_index, column in dataset.get("nulls", []):
            cand.rows[row_index][column] = None
        res = pq_store_diff.execute_engine_step(item, cand, None)
        assert not isinstance(res, str), res
        return res[0], res[1]


def _assert_null_hand_rows(dataset: dict[str, Any], item: dict[str, Any], expected: list[list[str | None]]) -> None:
    headers, rows = _engine_result(dataset, item)
    assert rows == expected, rows
    data = run_pq_step_diff_many(0, 0, [{}], items=[item], dataset=dataset)[0]
    row = _by_id(data, item["id"])
    assert row["status"] == "same" and row["refusal"] is None, row


def test_null_cell_split_to_rows_keeps_one_row() -> None:
    t = {**_tab(["k", "v"], [["1", "a|b"], ["2", "c"]]), "nulls": [[0, "v"]]}
    item = {"id": "nsr", "step": {"op": "split_column_to_rows", "column": "v", "delimiter": "|"}}
    _assert_null_hand_rows(t, item, [["1", None], ["2", "c"]])


def test_null_pivot_cell_is_not_unpivoted() -> None:
    t = {**_tab(["k", "v", "w"], [["1", "a", "x"], ["2", "b", "y"]]), "nulls": [[0, "v"]]}
    item = {"id": "nun", "step": {"op": "unpivot_columns", "columns": ["v"], "attribute_name": "attr", "value_name": "val"}}
    _assert_null_hand_rows(t, item, [["2", "y", "v", "b"]])


def test_null_left_cell_not_equals_is_true() -> None:
    t = {**_tab(["t", "m"], [["a", "x"], ["b", "y"]]), "nulls": [[0, "t"]]}
    item = {"id": "nne", "step": _cond([_clause("t", "not_equals", "a", "value")])}
    # a NULL is not equal to "a", so the not-equals test is true for it
    _assert_null_hand_rows(t, item, [[None, "x", "Y"], ["b", "y", "Y"]])


def test_null_cell_column_compare_follows_the_engine() -> None:
    """Column kind: a NULL on one side is not equal (so not-equals is true); NULL against NULL is equal."""
    t = {**_tab(["t", "m"], [["a", "x"], ["b", "y"], ["c", "z"]]), "nulls": [[0, "t"], [1, "m"]]}
    item = {"id": "ncc", "step": _cond([_clause("t", "not_equals", "m", "column")])}
    _assert_null_hand_rows(t, item, [[None, "x", "Y"], ["b", None, "Y"], ["c", "z", "Y"]])
    item_eq = {"id": "nce", "step": _cond([_clause("t", "equals", "m", "column")])}
    _assert_null_hand_rows(t, item_eq, [[None, "x", "other"], ["b", None, "other"], ["c", "z", "other"]])
    both = {**_tab(["t", "m"], [["a", "x"], ["b", "y"]]), "nulls": [[0, "t"], [0, "m"]]}
    item_both = {"id": "nb", "step": _cond([_clause("t", "equals", "m", "column")])}
    _assert_null_hand_rows(both, item_both, [[None, None, "Y"], ["b", "y", "other"]])


def test_null_left_cell_equals_null_matches() -> None:
    t = {**_tab(["t", "m"], [["a", "x"], ["b", "y"]]), "nulls": [[0, "t"]]}
    item = {"id": "nen", "step": _cond([_clause("t", "equals", "", "null")])}
    # the NULL is the left cell of row 1: equals null matches it; "b" is not null
    _assert_null_hand_rows(t, item, [[None, "x", "Y"], ["b", "y", "other"]])


def test_promote_refuses_a_name_with_a_nul_by_name() -> None:
    """The engine keeps the NUL name; the store path refuses it by name (the reason is the store's, not the engine's)."""
    t = _tab(["h1", "h2"], [["a\x00b", "q"], ["1", "2"]])
    item = {"id": "pnul", "step": {"op": "promote_headers"}}
    headers, _rows = _engine_result(t, item)
    assert headers == ["a\x00b", "q"]
    data = _run_items(t, [item])
    row = _by_id(data, "pnul")
    assert row["status"] == "refused" and "header name contains a NUL" in row["refusal_reason"], row


def test_promote_with_a_null_first_cell_names_it_column_one() -> None:
    t = {**_tab(["h1", "h2"], [["x", "b"], ["1", "2"]]), "nulls": [[0, "h1"]]}
    item = {"id": "pnull", "step": {"op": "promote_headers"}}
    headers, rows = _engine_result(t, item)
    assert headers == ["Column 1", "b"] and rows == [["1", "2"]]
    data = run_pq_step_diff_many(0, 0, [{}], items=[item], dataset=t)[0]
    assert _by_id(data, "pnull")["status"] == "same"


def _assert_named_refusal(dataset: dict[str, Any], item: dict[str, Any], text: str) -> None:
    """The engine runs the step; the store path refuses it by name (a named limit of the mapping)."""
    headers, _rows = _engine_result(dataset, item)
    assert headers, "the engine should run this step"
    row = _by_id(_run_items(dataset, [item]), item["id"])
    assert row["status"] == "refused" and text in row["refusal_reason"], row


def test_store_alias_names_are_refused_by_name() -> None:
    t = _tab(["k", "_part"], [["1", "a|b"]])
    item = {"id": "alias_part", "step": {"op": "split_column_to_rows", "column": "k", "delimiter": "|"}}
    _assert_named_refusal(t, item, "clashes with an alias the store path uses")
    t2 = _tab(["k", "v"], [["1", "a"]])
    item2 = {"id": "alias_rn", "step": {"op": "unpivot_columns", "columns": ["v"], "attribute_name": "__rn", "value_name": "val"}}
    _assert_named_refusal(t2, item2, "clashes with a name the store path uses")


def test_positions_refuse_more_than_500000_cells() -> None:
    """100,000 rows of one column (the importer's row limit) split into 6 columns: 600,000 cells."""
    big = _tab(["t"], [[str(i)] for i in range(100000)])
    item = {"id": "bigpos", "step": {"op": "split_column_by_positions", "column": "t", "positions": [0, 1, 2, 3, 4, 5]}}
    _assert_hand_refusal(big, item, "Splitting 't' exceeds the 500,000-cell import limit.")


def test_conditional_refuses_when_the_new_column_exceeds_500000_cells() -> None:
    """100,000 rows of five columns (500,000 cells, the import limit) plus one conditional column."""
    big = _tab(["a", "b", "c", "d", "e"], [["x", "y", "z", "w", str(i)] for i in range(100000)])
    item = {"id": "bigcond", "step": _cond([_clause("a", "equals", "x", "value")])}
    _assert_hand_refusal(big, item, "Adding a conditional column exceeds the 500,000-cell limit.")


def test_sequence_transpose_then_promote_with_a_null_cell() -> None:
    """A NULL cell carried through a transpose into the promoted header row: the engine and the store agree."""
    t = {**_tab(["h1", "h2"], [["x", "b"], ["1", "2"]]), "nulls": [[0, "h1"]]}
    item = {"id": "seq_null", "step": {"op": "sequence"}, "sequence": [{"op": "transpose_table"}, {"op": "promote_headers"}]}
    headers, rows = _engine_result(t, item)
    assert headers == ["Column 1", "1"] and rows == [["b", "2"]], (headers, rows)
    data = run_pq_step_diff_many(0, 0, [{}], items=[item], dataset=t)[0]
    assert _by_id(data, "seq_null")["status"] == "same", _by_id(data, "seq_null")


# ------------------------------------------------------------------ transpose (512 vs 513 column limit)

def test_transpose_512_rows_is_allowed_and_513_is_refused() -> None:
    t512 = _tab(["n"], [[str(i)] for i in range(512)])
    item = {"id": "tr512", "step": {"op": "transpose_table"}}
    assert _engine_rows(t512, item) == [[str(i) for i in range(512)]]
    assert _by_id(_run_items(t512, [item]), "tr512")["status"] == "same"
    t513 = _tab(["n"], [[str(i)] for i in range(513)])
    item513 = {"id": "tr513", "step": {"op": "transpose_table"}}
    _assert_hand_refusal(t513, item513, "Transposing exceeds the 512-column import limit.")


# ------------------------------------------------------------------ unpivot

UNPIVOT_TABLE = _tab(["k", "p", "q"], [["1", "a", "b"], ["2", "c", "d"]])


def test_unpivot_pivots_in_table_order_not_listed_order() -> None:
    item = {"id": "uo", "step": {"op": "unpivot_columns", "columns": ["q", "p"], "attribute_name": "attr", "value_name": "val"}}
    expected = [["1", "p", "a"], ["1", "q", "b"], ["2", "p", "c"], ["2", "q", "d"]]
    assert _engine_rows(UNPIVOT_TABLE, item) == expected
    _assert_hand_rows(UNPIVOT_TABLE, item, expected)


def test_unpivot_other_columns_refuses_when_every_column_is_kept() -> None:
    item = {"id": "uall", "step": {"op": "unpivot_other_columns", "columns": ["k", "p", "q"], "attribute_name": "attr", "value_name": "val"}}
    _assert_hand_refusal(UNPIVOT_TABLE, item, "Select at least one column to unpivot.")


def test_unpivot_refuses_an_output_name_that_is_kept() -> None:
    item = {"id": "uclash", "step": {"op": "unpivot_columns", "columns": ["p"], "attribute_name": "k", "value_name": "val"}}
    _assert_hand_refusal(UNPIVOT_TABLE, item, "Cannot unpivot: output column 'k' already exists.")


def test_transpose_refuses_a_table_with_no_data_rows() -> None:
    t0 = _tab(["a", "b"], [])
    item = {"id": "tr0", "step": {"op": "transpose_table"}}
    _assert_hand_refusal(t0, item, "Cannot transpose a table with no data rows.")


def test_unpivot_output_names_are_stripped() -> None:
    t = _tab(["k", "p"], [["1", "a"], ["2", "b"]])
    item = {"id": "un", "step": {"op": "unpivot_columns", "columns": ["p"], "attribute_name": " attr ", "value_name": " val "}}
    expected = [["1", "p", "a"], ["2", "p", "b"]]
    assert _engine_rows(t, item) == expected
    _assert_hand_rows(t, item, expected)


def test_unpivot_refuses_duplicate_listed_columns_and_missing_names() -> None:
    item = {"id": "udup", "step": {"op": "unpivot_columns", "columns": ["p", "p"], "attribute_name": "a", "value_name": "v"}}
    _assert_hand_refusal(UNPIVOT_TABLE, item, "contains a duplicate column name.")


# ------------------------------------------------------------------ split to rows

def test_split_to_rows_blanks_other_columns_is_caught() -> None:
    t = _tab(["k", "v", "w"], [["1", "a|b", "x"], ["2", "c", "y"]])
    item = {"id": "sr", "step": {"op": "split_column_to_rows", "column": "v", "delimiter": "|"}}
    expected = [["1", "a", "x"], ["1", "b", "x"], ["2", "c", "y"]]
    assert _engine_rows(t, item) == expected
    _assert_hand_rows(t, item, expected)


def test_split_to_rows_refuses_empty_delimiter() -> None:
    t = _tab(["k", "v"], [["1", "a"]])
    item = {"id": "sre", "step": {"op": "split_column_to_rows", "column": "v", "delimiter": ""}}
    _assert_hand_refusal(t, item, "needs a non-empty delimiter.")


# ------------------------------------------------------------------ split by positions

POS_TABLE = _tab(["k", "t"], [["1", "abcdef"], ["2", "xy"]])


def test_positions_must_start_at_zero() -> None:
    item = {"id": "p1", "step": {"op": "split_column_by_positions", "column": "t", "positions": [1, 4]}}
    _assert_hand_refusal(POS_TABLE, item, "positions must start at 0.")


def test_positions_must_be_strictly_increasing() -> None:
    item = {"id": "p2", "step": {"op": "split_column_by_positions", "column": "t", "positions": [0, 3, 3]}}
    _assert_hand_refusal(POS_TABLE, item, "positions must be in strictly increasing order.")


def test_positions_upper_bound_is_83886080() -> None:
    item = {"id": "p3", "step": {"op": "split_column_by_positions", "column": "t", "positions": [0, 83886081]}}
    _assert_hand_refusal(POS_TABLE, item, "positions must be whole numbers from 0 to 83,886,080.")


def test_positions_refuse_a_boolean_position() -> None:
    item = {"id": "p4", "step": {"op": "split_column_by_positions", "column": "t", "positions": [0, True]}}
    _assert_hand_refusal(POS_TABLE, item, "positions must be whole numbers from 0 to 83,886,080.")


def test_positions_split_characters_and_keep_short_cells() -> None:
    item = {"id": "p5", "step": {"op": "split_column_by_positions", "column": "t", "positions": [0, 2, 4]}}
    expected = [["1", "ab", "cd", "ef"], ["2", "xy", "", ""]]
    t = _tab(["k", "t"], [["1", "abcdef"], ["2", "xy"]])
    assert _engine_rows(t, item) == [["1", "ab", "cd", "ef"], ["2", "xy", "", ""]]
    _assert_hand_rows(t, item, expected)


# ------------------------------------------------------------------ extract text by delimiter

EXTRACT_TABLE = _tab(["k", "v"], [["1", "a;b"], ["2", ""], ["3", "c;d;e"]])


def test_extract_keeps_an_empty_cell_as_blank() -> None:
    item = {"id": "ex", "step": {"op": "extract_text_by_delimiter", "column": "v", "delimiter": ";", "side": "before", "occurrence": 0}}
    expected = [["1", "a"], ["2", ""], ["3", "c"]]
    assert _engine_rows(EXTRACT_TABLE, item) == expected
    _assert_hand_rows(EXTRACT_TABLE, item, expected)


def test_extract_occurrence_bound_is_100000() -> None:
    item = {"id": "exo", "step": {"op": "extract_text_by_delimiter", "column": "v", "delimiter": ";", "side": "before", "occurrence": 100001}}
    _assert_hand_refusal(EXTRACT_TABLE, item, "needs a zero-based delimiter occurrence from 0 to 100,000.")


def test_extract_side_must_be_before_or_after() -> None:
    item = {"id": "exs", "step": {"op": "extract_text_by_delimiter", "column": "v", "delimiter": ";", "side": "middle", "occurrence": 0}}
    _assert_hand_refusal(EXTRACT_TABLE, item, "must extract text before or after the delimiter.")


# ------------------------------------------------------------------ extract between delimiters

BETWEEN_TABLE = _tab(["v"], [["a(b)c(d)"]])


def test_between_start_occurrence_is_used() -> None:
    item = {"id": "bs", "step": {"op": "extract_text_between_delimiters", "column": "v", "start_delimiter": "(", "end_delimiter": ")", "start_occurrence": 1, "end_occurrence": 0}}
    expected = [["d"]]
    assert _engine_rows(BETWEEN_TABLE, item) == expected
    _assert_hand_rows(BETWEEN_TABLE, item, expected)


def test_between_end_occurrence_is_used() -> None:
    t = _tab(["v"], [["(a)b)c"]])
    item = {"id": "be", "step": {"op": "extract_text_between_delimiters", "column": "v", "start_delimiter": "(", "end_delimiter": ")", "start_occurrence": 0, "end_occurrence": 1}}
    expected = [["a)b"]]
    assert _engine_rows(t, item) == expected
    _assert_hand_rows(t, item, expected)


def test_between_refuses_a_missing_end_delimiter() -> None:
    t = _tab(["v"], [["(x"]])
    item = {"id": "bme", "step": {"op": "extract_text_between_delimiters", "column": "v", "start_delimiter": "(", "end_delimiter": ")", "start_occurrence": 0, "end_occurrence": 0}}
    _assert_hand_refusal(t, item, "Could not find end delimiter occurrence 0 after start delimiter occurrence 0 in row 1 of column 'v'.")
    _assert_hand_refusal(t, item, "Could not find end delimiter occurrence 0 after start delimiter occurrence 0 in row 1 of column 'v'.")


def test_between_refuses_a_missing_start_delimiter() -> None:
    t = _tab(["v"], [["abc"]])
    item = {"id": "bms", "step": {"op": "extract_text_between_delimiters", "column": "v", "start_delimiter": "(", "end_delimiter": ")", "start_occurrence": 0, "end_occurrence": 0}}
    _assert_hand_refusal(t, item, "Could not find start delimiter occurrence 0 in row 1 of column 'v'.")


# ------------------------------------------------------------------ conditional column (hand table COND_TABLE)

def test_conditional_contains_is_not_begins_with() -> None:
    item = {"id": "cc", "step": _cond([_clause("t", "contains", "an", "value")])}
    expected = [
        ["Apple", "5", "5.0", "other"], ["apple", "10", "9", "other"], ["", "", "q", "other"],
        ["Banana", "2", "x", "Y"], ["Ban", f"{NBSP}3", "Ban", "Y"], ["Cherry", "1_000", "999", "other"],
    ]
    assert _engine_rows(COND_TABLE, item) == expected
    _assert_hand_rows(COND_TABLE, item, expected)


def test_conditional_begins_with_is_not_ends_with() -> None:
    item = {"id": "cb", "step": _cond([_clause("t", "begins_with", "Ban", "value")])}
    expected = [
        ["Apple", "5", "5.0", "other"], ["apple", "10", "9", "other"], ["", "", "q", "other"],
        ["Banana", "2", "x", "Y"], ["Ban", f"{NBSP}3", "Ban", "Y"], ["Cherry", "1_000", "999", "other"],
    ]
    assert _engine_rows(COND_TABLE, item) == expected
    _assert_hand_rows(COND_TABLE, item, expected)


def test_conditional_greater_or_equal_includes_the_threshold() -> None:
    item = {"id": "cge", "step": _cond([_clause("n", "greater_than_or_equal", "5", "value")])}
    expected = [
        ["Apple", "5", "5.0", "Y"], ["apple", "10", "9", "Y"], ["", "", "q", "other"],
        ["Banana", "2", "x", "other"], ["Ban", f"{NBSP}3", "Ban", "other"], ["Cherry", "1_000", "999", "Y"],
    ]
    assert _engine_rows(COND_TABLE, item) == expected
    _assert_hand_rows(COND_TABLE, item, expected)


def test_conditional_numeric_compare_strips_padding() -> None:
    # NBSP-padded "3" (Python strips it, a SQL trim of spaces alone does not)
    item = {"id": "cnt", "step": _cond([_clause("n", "greater_than", "2", "value")])}
    expected = [
        ["Apple", "5", "5.0", "Y"], ["apple", "10", "9", "Y"], ["", "", "q", "other"],
        ["Banana", "2", "x", "other"], ["Ban", f"{NBSP}3", "Ban", "Y"], ["Cherry", "1_000", "999", "Y"],
    ]
    assert _engine_rows(COND_TABLE, item) == expected
    _assert_hand_rows(COND_TABLE, item, expected)


def test_conditional_numeric_compare_drops_underscores() -> None:
    item = {"id": "cu", "step": _cond([_clause("n", "greater_than", "500", "value")])}
    expected = [
        ["Apple", "5", "5.0", "other"], ["apple", "10", "9", "other"], ["", "", "q", "other"],
        ["Banana", "2", "x", "other"], ["Ban", f"{NBSP}3", "Ban", "other"], ["Cherry", "1_000", "999", "Y"],
    ]
    assert _engine_rows(COND_TABLE, item) == expected
    _assert_hand_rows(COND_TABLE, item, expected)


def test_conditional_numeric_compare_reads_underscore_groups_like_the_engine() -> None:
    """Python's Decimal reads '1__000' as 1000 and DuckDB rejects it: only the underscore removal agrees."""
    t = _tab(["n"], [["1__000"], ["1_0.0_1"], ["7"]])
    item = {"id": "cug", "step": _cond([_clause("n", "greater_than", "500", "value")])}
    expected = [["1__000", "Y"], ["1_0.0_1", "other"], ["7", "other"]]
    assert _engine_rows(t, item) == expected
    _assert_hand_rows(t, item, expected)


def test_conditional_else_column_reads_the_column() -> None:
    item = {"id": "cec", "step": _cond([_clause("t", "equals", "zzz", "value")], else_value="m", else_kind="column")}
    expected = [["Apple", "5", "5.0", "5.0"], ["apple", "10", "9", "9"], ["", "", "q", "q"],
                ["Banana", "2", "x", "x"], ["Ban", f"{NBSP}3", "Ban", "Ban"], ["Cherry", "1_000", "999", "999"]]
    assert _engine_rows(COND_TABLE, item) == expected
    _assert_hand_rows(COND_TABLE, item, expected)


def test_conditional_output_column_reads_the_column() -> None:
    item = {"id": "coc", "step": _cond([_clause("t", "equals", "Apple", "value", out="m", out_kind="column")])}
    expected = [["Apple", "5", "5.0", "5.0"], ["apple", "10", "9", "other"], ["", "", "q", "other"],
                ["Banana", "2", "x", "other"], ["Ban", f"{NBSP}3", "Ban", "other"], ["Cherry", "1_000", "999", "other"]]
    assert _engine_rows(COND_TABLE, item) == expected
    _assert_hand_rows(COND_TABLE, item, expected)


def test_conditional_null_equals_matches_only_nulls() -> None:
    # CSV blanks are '' (not NULL), so nothing matches a null test on this table.
    item = {"id": "cne", "step": _cond([_clause("t", "equals", "", "null")])}
    expected = [[*row, "other"] for row in COND_TABLE["rows"]]
    assert _engine_rows(COND_TABLE, item) == expected
    _assert_hand_rows(COND_TABLE, item, expected)


def test_conditional_column_equals_is_case_sensitive() -> None:
    t = _tab(["a", "b"], [["Apple", "apple"], ["x", "x"], ["y", "Y"]])
    item = {"id": "cce", "step": _cond([_clause("a", "equals", "b", "column")])}
    expected = [["Apple", "apple", "other"], ["x", "x", "Y"], ["y", "Y", "other"]]
    assert _engine_rows(t, item) == expected
    _assert_hand_rows(t, item, expected)


def test_conditional_column_numeric_compare_is_numeric() -> None:
    t = _tab(["n", "m"], [["10", "9"], ["2", "10"], ["", "x"]])
    item = {"id": "ccn", "step": _cond([_clause("n", "greater_than", "m", "column")])}
    expected = [["10", "9", "Y"], ["2", "10", "other"], ["", "x", "other"]]
    assert _engine_rows(t, item) == expected
    _assert_hand_rows(t, item, expected)


def test_conditional_clause_cap_is_64_and_65_is_refused() -> None:
    clauses64 = [_clause("t", "equals", f"v{i}", "value") for i in range(64)]
    item64 = {"id": "c64", "step": _cond(clauses64)}
    assert _by_id(_run_items(COND_TABLE, [item64]), "c64")["status"] == "same"
    clauses65 = [_clause("t", "equals", f"v{i}", "value") for i in range(65)]
    item65 = {"id": "c65", "step": _cond(clauses65)}
    _assert_hand_refusal(COND_TABLE, item65, "A conditional column may contain at most 64 clauses.")


@pytest.mark.parametrize("op", ["equals", "not_equals", "contains", "does_not_contain", "begins_with", "does_not_begin_with",
                                "ends_with", "does_not_end_with", "greater_than", "greater_than_or_equal", "less_than",
                                "less_than_or_equal"])
@pytest.mark.parametrize("kind", ["value", "column", "null"])
def test_conditional_every_operator_with_every_kind_agrees_with_engine(op: str, kind: str) -> None:
    """All twelve operators with each comparison kind (literal, column, null) on the hand table: same as the engine."""
    numeric = op in {"greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"}
    column = "n" if numeric else "t"
    value = {"value": "2" if numeric else "an", "column": "m", "null": ""}[kind]
    item = {"id": f"m_{op}_{kind}", "step": _cond([_clause(column, op, value, kind)])}
    row = _by_id(_run_items(COND_TABLE, [item]), item["id"])
    assert row["status"] == "same", row


def test_conditional_blank_cells_and_column_compare_with_blanks() -> None:
    item = {"id": "cbl", "step": _cond([_clause("n", "less_than", "m", "column")])}
    t = _tab(["n", "m"], [["", "k"], ["3", ""], ["", "4"]])
    # blank cells are text: "" < "k" and "" < "4" are true; "3" < "" is false
    expected = [["", "k", "Y"], ["3", "", "other"], ["", "4", "Y"]]
    assert _engine_rows(t, item) == expected
    assert _by_id(_run_items(t, [item]), "cbl")["status"] == "same"


# ------------------------------------------------------------------ mutants at tool level (generated D1a tables)

D1A_TOOL_MUTANTS = [
    ("mutant_transpose_headers_dropped", "d1a_transpose_table"),
    ("mutant_extract_side_swapped", "ext_side"),
    ("mutant_occurrence_off_by_one", "ext_occ"),
    ("mutant_between_delimiters_inclusive", "btw_inclusive"),
]
D1A_TOOL_ITEMS = [
    {"id": "d1a_transpose_table", "step": {"op": "transpose_table"}, "table": "d1a", "d1a": True},
    {"id": "ext_side", "step": {"op": "extract_text_by_delimiter", "column": "d_paren", "delimiter": "(", "side": "before", "occurrence": 0}, "table": "d1a", "d1a": True},
    {"id": "ext_occ", "step": {"op": "extract_text_by_delimiter", "column": "d_delim", "delimiter": ";", "side": "before", "occurrence": 0}, "table": "d1a", "d1a": True},
    {"id": "btw_inclusive", "step": {"op": "extract_text_between_delimiters", "column": "d_paren", "start_delimiter": "(", "end_delimiter": ")", "start_occurrence": 0, "end_occurrence": 0}, "table": "d1a", "d1a": True},
]


@pytest.mark.parametrize("rows,seed", [(50, 42), (400, 1), (2000, 7)])
def test_d1a_tool_level_mutants_exit_1_on_generated_tables(rows: int, seed: int) -> None:
    clean_run, *mutant_runs = run_pq_step_diff_many(
        rows, seed, [{}] + [{m: True} for m, _ in D1A_TOOL_MUTANTS], items=D1A_TOOL_ITEMS
    )
    refusals = [r["id"] for r in clean_run["results"] if r["refusal"]]
    code, _ = evaluate_exit_policy(clean_run, {"classes": [], "refused": refusals})
    assert code == 0, f"clean D1a run failed at {rows}/{seed}"
    for (mutant, item_id), data in zip(D1A_TOOL_MUTANTS, mutant_runs):
        code, _ = evaluate_exit_policy(data, {"classes": [], "refused": refusals})
        assert code == 1, f"{mutant} did not exit 1 at {rows}/{seed}"
        assert _by_id(data, item_id)["status"] != "same", f"{mutant} not caught on {item_id} at {rows}/{seed}"
