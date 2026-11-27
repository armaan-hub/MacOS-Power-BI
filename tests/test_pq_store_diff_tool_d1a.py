"""Stage D1a tests for the Power Query step differential tool (tools/pq_store_diff.py).

Headers (promote/demote), transpose, unpivot, split to rows and positions,
extract text (by delimiter and between delimiters), and conditional column.
"""

from __future__ import annotations

from typing import Any

import pytest

from analytics_studio import transformations
from analytics_studio.file_import import ImportCandidate
from tests.test_pq_store_diff_tool import (
    _assert_mutant_differs_and_exits_1,
    _by_id,
    _engine_rows,
    _run_items,
)
from tools.pq_store_diff import evaluate_exit_policy, run_pq_step_diff_many

# ------------------------------------------------------------------ D1a Step Items for Hand-Checked Tests

D1A_MUTANT_ITEMS = {
    "mutant_promote_keeps_first_row": ["p_promote"],
    "mutant_demote_names_off_by_one": ["d_demote"],
    "mutant_transpose_headers_dropped": ["t_transpose"],
    "mutant_unpivot_order_per_column": ["u_unpivot"],
    "mutant_unpivot_drops_blanks": ["u_unpivot_blank"],
    "mutant_split_to_rows_loses_empty_parts": ["s_split"],
    "mutant_positions_off_by_one": ["pos_split"],
    "mutant_extract_side_swapped": ["ext_side"],
    "mutant_occurrence_off_by_one": ["ext_occ"],
    "mutant_missing_delimiter_returns_blank": ["ext_miss"],
    "mutant_between_delimiters_inclusive": ["btw_inclusive"],
    "mutant_conditional_last_clause_wins": ["cond_last"],
    "mutant_conditional_else_ignored": ["cond_else"],
}


def _tab(headers: list[str], rows: list[list[str]]) -> dict[str, Any]:
    return {"headers": headers, "rows": rows}


# ------------------------------------------------------------------ Hand-Checked Step Tests (6-10 Rows)

def test_promote_and_demote_headers_hand_checked() -> None:
    # 1. promote_headers
    t1 = _tab(["c1", "c2"], [["Name", "Age"], ["Alice", "30"], ["Bob", "25"]])
    item_p = {"id": "promote", "step": {"op": "promote_headers"}}
    clean_p = _run_items(t1, [item_p])
    assert _by_id(clean_p, "promote")["status"] == "same"
    assert _engine_rows(t1, item_p) == [["Alice", "30"], ["Bob", "25"]]
    _assert_mutant_differs_and_exits_1(
        t1, item_p, "mutant_promote_keeps_first_row", [["Alice", "30"], ["Bob", "25"]]
    )

    # 2. demote_headers
    t2 = _tab(["Dept", "Salary"], [["Eng", "100"], ["Sales", "80"]])
    item_d = {"id": "demote", "step": {"op": "demote_headers"}}
    clean_d = _run_items(t2, [item_d])
    assert _by_id(clean_d, "demote")["status"] == "same"
    assert _engine_rows(t2, item_d) == [["Dept", "Salary"], ["Eng", "100"], ["Sales", "80"]]
    _assert_mutant_differs_and_exits_1(
        t2, item_d, "mutant_demote_names_off_by_one", [["Dept", "Salary"], ["Eng", "100"], ["Sales", "80"]]
    )


def test_transpose_table_hand_checked() -> None:
    t = _tab(["A", "B", "C"], [["1", "2", "3"], ["4", "5", "6"], ["7", "8", "9"]])
    item = {"id": "transpose", "step": {"op": "transpose_table"}}
    clean = _run_items(t, [item])
    assert _by_id(clean, "transpose")["status"] == "same"
    assert _engine_rows(t, item) == [["1", "4", "7"], ["2", "5", "8"], ["3", "6", "9"]]
    _assert_mutant_differs_and_exits_1(
        t, item, "mutant_transpose_headers_dropped", [["1", "4", "7"], ["2", "5", "8"], ["3", "6", "9"]]
    )


def test_unpivot_columns_and_unpivot_other_hand_checked() -> None:
    t = _tab(
        ["id", "q1", "q2"],
        [["101", "10", "20"], ["102", "30", ""], ["103", "", "40"]],
    )
    # unpivot_columns
    item_u = {
        "id": "unpivot",
        "step": {"op": "unpivot_columns", "columns": ["q1", "q2"], "attribute_name": "quarter", "value_name": "sales"},
    }
    clean_u = _run_items(t, [item_u])
    assert _by_id(clean_u, "unpivot")["status"] == "same"
    expected_rows = [
        ["101", "q1", "10"], ["101", "q2", "20"],
        ["102", "q1", "30"], ["102", "q2", ""],
        ["103", "q1", ""], ["103", "q2", "40"],
    ]
    assert _engine_rows(t, item_u) == expected_rows
    _assert_mutant_differs_and_exits_1(t, item_u, "mutant_unpivot_order_per_column", expected_rows)
    _assert_mutant_differs_and_exits_1(t, item_u, "mutant_unpivot_drops_blanks", expected_rows)

    # unpivot_other_columns
    item_uo = {
        "id": "unpivot_other",
        "step": {"op": "unpivot_other_columns", "columns": ["id"], "attribute_name": "quarter", "value_name": "sales"},
    }
    clean_uo = _run_items(t, [item_uo])
    assert _by_id(clean_uo, "unpivot_other")["status"] == "same"
    assert _engine_rows(t, item_uo) == expected_rows


def test_split_column_to_rows_and_by_positions_hand_checked() -> None:
    # 1. split_column_to_rows
    t_rows = _tab(
        ["k", "v"],
        [["1", "a,b,c"], ["2", "d,,e"], ["3", ",f,"], ["4", "single"]],
    )
    item_s = {"id": "split_rows", "step": {"op": "split_column_to_rows", "column": "v", "delimiter": ","}}
    clean_s = _run_items(t_rows, [item_s])
    assert _by_id(clean_s, "split_rows")["status"] == "same"
    expected_s = [
        ["1", "a"], ["1", "b"], ["1", "c"],
        ["2", "d"], ["2", ""], ["2", "e"],
        ["3", ""], ["3", "f"], ["3", ""],
        ["4", "single"],
    ]
    assert _engine_rows(t_rows, item_s) == expected_s
    _assert_mutant_differs_and_exits_1(t_rows, item_s, "mutant_split_to_rows_loses_empty_parts", expected_s)

    # 2. split_column_by_positions
    t_pos = _tab(["id", "code"], [["1", "ABCDEF123"], ["2", "GHIJKL456"], ["3", "XY"]])
    item_p = {"id": "split_pos", "step": {"op": "split_column_by_positions", "column": "code", "positions": [0, 3, 6]}}
    clean_p = _run_items(t_pos, [item_p])
    assert _by_id(clean_p, "split_pos")["status"] == "same"
    expected_p = [
        ["1", "ABC", "DEF", "123"],
        ["2", "GHI", "JKL", "456"],
        ["3", "XY", "", ""],
    ]
    assert _engine_rows(t_pos, item_p) == expected_p
    _assert_mutant_differs_and_exits_1(t_pos, item_p, "mutant_positions_off_by_one", expected_p)


def test_extract_text_by_delimiter_and_between_delimiters_hand_checked() -> None:
    t = _tab(
        ["id", "text"],
        [["1", "apple-banana-cherry"], ["2", "cat-dog-fox"], ["3", "red-green-blue"]],
    )
    # extract_text_by_delimiter before
    item_b = {
        "id": "ext_before",
        "step": {"op": "extract_text_by_delimiter", "column": "text", "delimiter": "-", "side": "before", "occurrence": 0},
    }
    assert _engine_rows(t, item_b) == [["1", "apple"], ["2", "cat"], ["3", "red"]]
    _assert_mutant_differs_and_exits_1(t, item_b, "mutant_extract_side_swapped", [["1", "apple"], ["2", "cat"], ["3", "red"]])

    # extract_text_by_delimiter after
    item_a = {
        "id": "ext_after",
        "step": {"op": "extract_text_by_delimiter", "column": "text", "delimiter": "-", "side": "after", "occurrence": 0},
    }
    assert _engine_rows(t, item_a) == [["1", "banana-cherry"], ["2", "dog-fox"], ["3", "green-blue"]]
    _assert_mutant_differs_and_exits_1(t, item_a, "mutant_occurrence_off_by_one", [["1", "banana-cherry"], ["2", "dog-fox"], ["3", "green-blue"]])

    # missing delimiter causes named refusal in clean, but mutant returns blank
    t_miss = _tab(["id", "text"], [["1", "nodash"], ["2", "has-dash"]])
    item_miss = {
        "id": "ext_miss",
        "step": {"op": "extract_text_by_delimiter", "column": "text", "delimiter": "-", "side": "before", "occurrence": 0},
    }
    clean_miss = _run_items(t_miss, [item_miss])
    assert _by_id(clean_miss, "ext_miss")["status"] == "same"
    assert _by_id(clean_miss, "ext_miss")["refusal"] is not None
    mut_miss = _run_items(t_miss, [item_miss], overrides={"mutant_missing_delimiter_returns_blank": True})
    assert _by_id(mut_miss, "ext_miss")["status"] == "differs"
    code, _ = evaluate_exit_policy(mut_miss, {"classes": []})
    assert code == 1

    # extract_text_between_delimiters
    t_between = _tab(
        ["id", "tag"],
        [["1", "<start>data1<end>"], ["2", "<start>data2<end>"], ["3", "<start><end>"]],
    )
    item_btw = {
        "id": "btw",
        "step": {
            "op": "extract_text_between_delimiters",
            "column": "tag",
            "start_delimiter": "<start>",
            "end_delimiter": "<end>",
            "start_occurrence": 0,
            "end_occurrence": 0,
        },
    }
    expected_btw = [["1", "data1"], ["2", "data2"], ["3", ""]]
    assert _engine_rows(t_between, item_btw) == expected_btw
    _assert_mutant_differs_and_exits_1(t_between, item_btw, "mutant_between_delimiters_inclusive", expected_btw)


def test_conditional_column_hand_checked() -> None:
    t = _tab(
        ["id", "score", "grade"],
        [
            ["1", "95", "A"],
            ["2", "85", "B"],
            ["3", "75", "C"],
            ["4", "60", "D"],
            ["5", "40", "F"],
        ],
    )
    # 1. Multiple clauses + first match wins
    item_c = {
        "id": "cond",
        "step": {
            "op": "conditional_column",
            "name": "status",
            "clauses": [
                {"column": "grade", "operator": "equals", "test_value": "A", "test_value_kind": "value", "output": "Excellent", "output_kind": "value"},
                {"column": "grade", "operator": "equals", "test_value": "A", "test_value_kind": "value", "output": "Shadowed", "output_kind": "value"},
                {"column": "grade", "operator": "equals", "test_value": "B", "test_value_kind": "value", "output": "Good", "output_kind": "value"},
                {"column": "grade", "operator": "equals", "test_value": "C", "test_value_kind": "value", "output": "Pass", "output_kind": "value"},
            ],
            "else_value": "Fail",
            "else_kind": "value",
        },
    }
    expected_c = [
        ["1", "95", "A", "Excellent"],
        ["2", "85", "B", "Good"],
        ["3", "75", "C", "Pass"],
        ["4", "60", "D", "Fail"],
        ["5", "40", "F", "Fail"],
    ]
    assert _engine_rows(t, item_c) == expected_c
    _assert_mutant_differs_and_exits_1(t, item_c, "mutant_conditional_last_clause_wins", expected_c)

    # 2. Else value verification
    item_else = {
        "id": "cond_else",
        "step": {
            "op": "conditional_column",
            "name": "tag",
            "clauses": [
                {"column": "grade", "operator": "equals", "test_value": "Z", "test_value_kind": "value", "output": "Zero", "output_kind": "value"},
            ],
            "else_value": "STANDARD",
            "else_kind": "value",
        },
    }
    expected_else = [
        ["1", "95", "A", "STANDARD"],
        ["2", "85", "B", "STANDARD"],
        ["3", "75", "C", "STANDARD"],
        ["4", "60", "D", "STANDARD"],
        ["5", "40", "F", "STANDARD"],
    ]
    assert _engine_rows(t, item_else) == expected_else
    _assert_mutant_differs_and_exits_1(t, item_else, "mutant_conditional_else_ignored", expected_else)


# ------------------------------------------------------------------ Probes (Unicode, Combining, Astral, CJK, Regex)

def test_unicode_astral_cjk_and_metacharacter_probes() -> None:
    probes = [
        ("combining_marks", ["id", "text"], [["1", "e\u0301cole"], ["2", "cafe\u0301"]]),
        ("astral_emoji", ["id", "text"], [["1", "😀😁😂"], ["2", "🚀🛸🌟"]]),
        ("cjk", ["id", "text"], [["1", "你好世界"], ["2", "こんにちは"]]),
        ("whitespace_delims", ["id", "text"], [["1", "a\tb\u00a0c"], ["2", "x\ty\u00a0z"]]),
        ("regex_chars", ["id", "text"], [["1", "a.b+c*d?e"], ["2", "x[0-9]y(z)"]]),
    ]
    for name, headers, rows in probes:
        ds = _tab(headers, rows)
        items = [
            {"id": f"{name}_pos", "step": {"op": "split_column_by_positions", "column": "text", "positions": [0, 1, 2]}},
            {"id": f"{name}_split_rows", "step": {"op": "split_column_to_rows", "column": "text", "delimiter": "\t" if "\t" in rows[0][1] else "." if "." in rows[0][1] else " "}},
            {"id": f"{name}_unpivot", "step": {"op": "unpivot_columns", "columns": ["text"], "attribute_name": "attr", "value_name": "val"}},
            {"id": f"{name}_transpose", "step": {"op": "transpose_table"}},
            {"id": f"{name}_promote", "step": {"op": "promote_headers"}},
            {"id": f"{name}_demote", "step": {"op": "demote_headers"}},
        ]
        res = _run_items(ds, items)
        for item in items:
            row = _by_id(res, item["id"])
            assert row["status"] == "same", f"Probe {name} failed on {item['id']}: {row}"


# ------------------------------------------------------------------ Edge Case Parameter Sets

def test_edge_case_parameters_and_errors() -> None:
    cases = [
        # Empty table
        ("empty_promote", _tab(["a", "b"], []), {"id": "x", "step": {"op": "promote_headers"}}),
        ("empty_demote", _tab(["a", "b"], []), {"id": "x", "step": {"op": "demote_headers"}}),
        ("empty_transpose", _tab(["a", "b"], []), {"id": "x", "step": {"op": "transpose_table"}}),
        ("empty_unpivot", _tab(["a", "b"], []), {"id": "x", "step": {"op": "unpivot_columns", "columns": ["b"], "attribute_name": "attr", "value_name": "val"}}),
        ("empty_split_rows", _tab(["a", "b"], []), {"id": "x", "step": {"op": "split_column_to_rows", "column": "a", "delimiter": ","}}),
        ("empty_pos", _tab(["a", "b"], []), {"id": "x", "step": {"op": "split_column_by_positions", "column": "a", "positions": [0, 1]}}),
        ("empty_cond", _tab(["a", "b"], []), {"id": "x", "step": {"op": "conditional_column", "name": "c", "clauses": [{"column": "a", "operator": "equals", "test_value": "x", "test_value_kind": "value", "output": "1", "output_kind": "value"}], "else_value": "0", "else_kind": "value"}}),
        # One row
        ("one_row_promote", _tab(["a", "b"], [["x", "y"]]), {"id": "x", "step": {"op": "promote_headers"}}),
        ("one_row_transpose", _tab(["a", "b"], [["x", "y"]]), {"id": "x", "step": {"op": "transpose_table"}}),
        # One column
        ("one_col_unpivot", _tab(["a"], [["x"], ["y"]]), {"id": "x", "step": {"op": "unpivot_columns", "columns": ["a"], "attribute_name": "attr", "value_name": "val"}}),
        ("one_col_transpose", _tab(["a"], [["x"], ["y"]]), {"id": "x", "step": {"op": "transpose_table"}}),
        # All blank cells
        ("all_blank_unpivot", _tab(["a", "b"], [["", ""], ["", ""]]), {"id": "x", "step": {"op": "unpivot_columns", "columns": ["b"], "attribute_name": "attr", "value_name": "val"}}),
        ("all_blank_split_rows", _tab(["a", "b"], [["", ""], ["", ""]]), {"id": "x", "step": {"op": "split_column_to_rows", "column": "a", "delimiter": ","}}),
        # Missing column
        ("missing_col_unpivot", _tab(["a", "b"], [["1", "2"]]), {"id": "x", "step": {"op": "unpivot_columns", "columns": ["missing"], "attribute_name": "attr", "value_name": "val"}}),
        ("missing_col_split_rows", _tab(["a", "b"], [["1", "2"]]), {"id": "x", "step": {"op": "split_column_to_rows", "column": "missing", "delimiter": ","}}),
        ("missing_col_pos", _tab(["a", "b"], [["1", "2"]]), {"id": "x", "step": {"op": "split_column_by_positions", "column": "missing", "positions": [0, 1]}}),
        ("missing_col_cond", _tab(["a", "b"], [["1", "2"]]), {"id": "x", "step": {"op": "conditional_column", "name": "c", "clauses": [{"column": "missing", "operator": "equals", "test_value": "x", "test_value_kind": "value", "output": "1", "output_kind": "value"}], "else_value": "0", "else_kind": "value"}}),
        # Clashing new names
        ("clash_unpivot_attr", _tab(["a", "b"], [["1", "2"]]), {"id": "x", "step": {"op": "unpivot_columns", "columns": ["b"], "attribute_name": "a", "value_name": "val"}}),
        ("clash_unpivot_val", _tab(["a", "b"], [["1", "2"]]), {"id": "x", "step": {"op": "unpivot_columns", "columns": ["b"], "attribute_name": "attr", "value_name": "a"}}),
        ("clash_pos", _tab(["a", "a.1"], [["123", "2"]]), {"id": "x", "step": {"op": "split_column_by_positions", "column": "a", "positions": [0, 1]}}),
        ("clash_cond", _tab(["a", "b"], [["1", "2"]]), {"id": "x", "step": {"op": "conditional_column", "name": "a", "clauses": [{"column": "b", "operator": "equals", "test_value": "x", "test_value_kind": "value", "output": "1", "output_kind": "value"}], "else_value": "0", "else_kind": "value"}}),
    ]
    for name, table, item in cases:
        res = _by_id(_run_items(table, [item]), "x")
        assert res["status"] == "same", f"Failed on {name}: {res}"


# ------------------------------------------------------------------ Chained Structural Steps

def test_structural_step_chain_split_then_unpivot() -> None:
    cand = ImportCandidate(
        kind="csv",
        headers=["id", "s"],
        rows=[{"id": "1", "s": "a|b"}, {"id": "2", "s": "c|d"}],
        options={},
        notices=[],
    )
    step1 = {"op": "split_column_to_rows", "column": "s", "delimiter": "|"}
    res1 = transformations.apply_transformations(cand, [step1])

    table2 = _tab(res1.headers, [[r[h] for h in res1.headers] for r in res1.rows])
    item2 = {"id": "u", "step": {"op": "unpivot_columns", "columns": ["s"], "attribute_name": "attr", "value_name": "val"}}
    res2 = _run_items(table2, [item2])
    row = _by_id(res2, "u")
    assert row["status"] == "same" and row["refusal"] is None


# ------------------------------------------------------------------ Mutants on Generated Data (50/42, 400/1, 2000/7)

@pytest.mark.parametrize("rows,seed", [(50, 42), (400, 1), (2000, 7)])
def test_d1a_mutants_exit_1_on_generated_data_and_clean_run_exits_0(rows: int, seed: int) -> None:
    test_items = [
        {"id": "p_promote", "step": {"op": "promote_headers"}},
        {"id": "d_demote", "step": {"op": "demote_headers"}},
        {"id": "u_unpivot", "step": {"op": "unpivot_columns", "columns": ["cat_col", "grp_key"], "attribute_name": "attr", "value_name": "val"}},
        {"id": "s_split", "step": {"op": "split_column_to_rows", "column": "split_col", "delimiter": "|"}},
        {"id": "pos_split", "step": {"op": "split_column_by_positions", "column": "text_col", "positions": [0, 2, 4]}},
        {"id": "ext_miss", "step": {"op": "extract_text_by_delimiter", "column": "split_col", "delimiter": "|", "side": "before", "occurrence": 0}},
        {"id": "cond_last", "step": {
            "op": "conditional_column",
            "name": "cond_last_col",
            "clauses": [
                {"column": "cat_col", "operator": "equals", "test_value": "A", "test_value_kind": "value", "output": "A1", "output_kind": "value"},
                {"column": "cat_col", "operator": "equals", "test_value": "A", "test_value_kind": "value", "output": "A2", "output_kind": "value"},
            ],
            "else_value": "other",
            "else_kind": "value",
        }},
        {"id": "cond_else", "step": {
            "op": "conditional_column",
            "name": "cond_else_col",
            "clauses": [
                {"column": "cat_col", "operator": "equals", "test_value": "NONEXISTENT_VAL", "test_value_kind": "value", "output": "A1", "output_kind": "value"},
            ],
            "else_value": "FALLBACK",
            "else_kind": "value",
        }},
    ]
    ids = [item["id"] for item in test_items]
    active_mutants = {
        "mutant_promote_keeps_first_row": ["p_promote"],
        "mutant_demote_names_off_by_one": ["d_demote"],
        "mutant_unpivot_order_per_column": ["u_unpivot"],
        "mutant_unpivot_drops_blanks": ["u_unpivot"],
        "mutant_split_to_rows_loses_empty_parts": ["s_split"],
        "mutant_positions_off_by_one": ["pos_split"],
        "mutant_missing_delimiter_returns_blank": ["ext_miss"],
        "mutant_conditional_last_clause_wins": ["cond_last"],
        "mutant_conditional_else_ignored": ["cond_else"],
    }
    mutant_list = list(active_mutants)
    all_runs = run_pq_step_diff_many(
        rows, seed, [{}] + [{m: True} for m in mutant_list], item_filter=ids, items=test_items
    )
    clean_run = all_runs[0]
    refusals = [r["id"] for r in clean_run["results"] if r["refusal"]]
    baseline = {"classes": [], "refused": refusals}
    code, _ = evaluate_exit_policy(clean_run, baseline)
    assert code == 0, f"Clean run failed at {rows}/{seed}"

    for mutant, mut_data in zip(mutant_list, all_runs[1:]):
        code, _ = evaluate_exit_policy(mut_data, baseline)
        assert code == 1, f"Mutant {mutant} did not exit 1 at {rows}/{seed}"
        killed = [r["id"] for r in mut_data["results"] if r["status"] == "differs"]
        assert set(killed) & set(active_mutants[mutant]), f"Mutant {mutant} killed unexpected: {killed}"
