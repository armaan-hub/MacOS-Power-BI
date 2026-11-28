"""Stage D1d tests for the Power Query step differential tool (Part D and Part E follow-ups).

Covers:
- Part D1: hand-checked rule tests for the shape mirrors: promote_all_scalars must be boolean, unpivot duplicate /
  blank / 512-column / output-name rules, split rows `_parts` / `_sub` / blank column, column strip in positions /
  extract / between. (The 667-step malformed-parameter table and the 336-step shape table are in
  test_pq_store_diff_tool_d1d_tables.py; the D1a table scaling is in test_pq_store_diff_tool_d1d_scale.py.)
- Part D2: Whitespace class (tab, newline, U+0085, U+2028, U+00A0) in numeric comparisons for conditional columns.
- Part D3: Sequence mode hand-checked tests (NULL kept as NULL in intermediate tables,
  column facts recomputed on derived tables, row counts recomputed on derived tables).
- Part E: Limits decision: the store path does not mirror the engine's import limits and the engine runs with raised
  limits (`raised_engine_limits`): 100,000 rows x 6 columns for four steps, split by each delimiter above 500,000
  cells, append above 500,000 cells and above 100,000 rows (query_engine limits), every limit constant raised and
  restored on every exit, and 100,001 rows over 10 MiB (file_import row and byte limits).
"""

from __future__ import annotations

import time
from typing import Any

from tests.test_pq_store_diff_tool import _by_id, _engine_rows, _run_items
from tests.test_pq_store_diff_tool_d1a import _tab

NEL = "\u0085"
LS = "\u2028"
NBSP = "\u00a0"


def _clause(col: str, op: str, val: str, kind: str = "value", out: str = "Y", out_kind: str = "value") -> dict[str, str]:
    return {"column": col, "operator": op, "test_value": val, "test_value_kind": kind, "output": out, "output_kind": out_kind}


def _cond(clauses: list[dict[str, str]], else_val: str = "N", else_kind: str = "value", name: str = "c") -> dict[str, Any]:
    return {"op": "conditional_column", "name": name, "clauses": clauses, "else_value": else_val, "else_kind": else_kind}


# ------------------------------------------------------------------ Part D1: Shape Probes & Survivor Killers

def test_promote_all_scalars_boolean_check_and_shape_mirror() -> None:
    """N09: promote_all_scalars must be boolean."""
    t = _tab(["a", "b"], [["1", "2"], ["3", "4"]])
    item = {"id": "p_bool", "step": {"op": "promote_headers", "promote_all_scalars": "true"}}
    res = _by_id(_run_items(t, [item]), "p_bool")
    assert res["status"] == "same"
    assert res.get("refusal") == "REFUSED: Transformation step 1 PromoteAllScalars setting must be Boolean."


def test_unpivot_column_validations_and_limits() -> None:
    """N11, N12, N13: unpivot validates columns, non-emptiness, duplicates, and 512-column limit."""
    t = _tab(["a", "b"], [["1", "2"], ["3", "4"]])

    # N11: blank / non-string column
    item_blank = {"id": "u_blank", "step": {"op": "unpivot_columns", "columns": ["a", "   "], "attribute_name": "at", "value_name": "va"}}
    res_b = _by_id(_run_items(t, [item_blank]), "u_blank")
    assert res_b["status"] == "same"
    assert res_b.get("refusal") == "REFUSED: Transformation step 1 needs one or more columns."

    # N12: duplicate column names
    item_dup = {"id": "u_dup", "step": {"op": "unpivot_columns", "columns": ["a", "a"], "attribute_name": "at", "value_name": "va"}}
    res_d = _by_id(_run_items(t, [item_dup]), "u_dup")
    assert res_d["status"] == "same"
    assert res_d.get("refusal") == "REFUSED: Transformation step 1 contains a duplicate column name."

    # N13: 512-column limit
    cols_512 = [f"c{i}" for i in range(512)]
    t_512 = _tab(cols_512, [["1"] * 512, ["2"] * 512])
    item_lim = {"id": "u_lim", "step": {"op": "unpivot_columns", "columns": ["c0"], "attribute_name": "at", "value_name": "va"}}
    res_lim = _by_id(_run_items(t_512, [item_lim]), "u_lim")
    assert res_lim["status"] == "same"
    assert "512-column" in res_lim.get("refusal", "")


def test_reserved_alias_names_and_split_rows_validations() -> None:
    """N15, N17, N18, N19: reserved names _p_ord, _parts, _sub, and split-rows blank column."""
    t = _tab(["a", "b"], [["1", "2"], ["3", "4"]])

    # N15: _p_ord
    item_pord = {"id": "u_pord", "step": {"op": "unpivot_columns", "columns": ["b"], "attribute_name": "_p_ord", "value_name": "va"}}
    res_pord = _by_id(_run_items(t, [item_pord]), "u_pord")
    assert res_pord["status"] == "refused"
    assert "_p_ord" in res_pord.get("refusal", "")

    # N17: _parts
    t_parts = _tab(["a", "_parts"], [["1", "x;y"], ["2", "z"]])
    item_parts = {"id": "s_parts", "step": {"op": "split_column_to_rows", "column": "_parts", "delimiter": ";"}}
    res_parts = _by_id(_run_items(t_parts, [item_parts]), "s_parts")
    assert res_parts["status"] == "refused"
    assert "_parts" in res_parts.get("refusal", "")

    # N18: _sub
    t_sub = _tab(["a", "_sub"], [["1", "x;y"], ["2", "z"]])
    item_sub = {"id": "s_sub", "step": {"op": "split_column_to_rows", "column": "_sub", "delimiter": ";"}}
    res_sub = _by_id(_run_items(t_sub, [item_sub]), "s_sub")
    assert res_sub["status"] == "refused"
    assert "_sub" in res_sub.get("refusal", "")

    # N19: blank column in split rows
    item_s_blank = {"id": "s_blank", "step": {"op": "split_column_to_rows", "column": "   ", "delimiter": ";"}}
    res_sb = _by_id(_run_items(t, [item_s_blank]), "s_blank")
    assert res_sb["status"] == "same"
    assert "needs a column name" in res_sb.get("refusal", "")


def test_column_name_stripping_and_positions_blank_check() -> None:
    """N20, N21, N22, N44: column strip in positions, extract, between; blank check in positions."""
    t = _tab(["a", "b"], [["1;2", "x"], ["3;4", "y"]])
    t_paren = _tab(["a", "b"], [["(1)", "x"], ["(3)", "y"]])

    # N20: positions strips column name
    item_pos = {"id": "pos_strip", "step": {"op": "split_column_by_positions", "column": " a ", "positions": [0, 1]}}
    res_pos = _by_id(_run_items(t, [item_pos]), "pos_strip")
    assert res_pos["status"] == "same" and res_pos.get("refusal") is None

    # N21: extract strips column name
    item_ext = {"id": "ext_strip", "step": {"op": "extract_text_by_delimiter", "column": " a ", "delimiter": ";", "side": "before", "occurrence": 0}}
    res_ext = _by_id(_run_items(t, [item_ext]), "ext_strip")
    assert res_ext["status"] == "same" and res_ext.get("refusal") is None

    # N22: between strips column name
    item_btw = {"id": "btw_strip", "step": {"op": "extract_text_between_delimiters", "column": " a ", "start_delimiter": "(", "end_delimiter": ")", "start_occurrence": 0, "end_occurrence": 0}}
    res_btw = _by_id(_run_items(t_paren, [item_btw]), "btw_strip")
    assert res_btw["status"] == "same" and res_btw.get("refusal") is None

    # N44: positions requires non-blank column name
    item_pos_blank = {"id": "pos_blank", "step": {"op": "split_column_by_positions", "column": "   ", "positions": [0, 1]}}
    res_pb = _by_id(_run_items(t, [item_pos_blank]), "pos_blank")
    assert res_pb["status"] == "same"
    assert "needs a column name" in res_pb.get("refusal", "")


# ------------------------------------------------------------------ Part D2: Whitespace Class

def test_whitespace_class_padded_numeric_comparisons() -> None:
    """N06, N07: numeric comparisons trim all Python whitespace: tab, newline, U+0085, U+2028, U+00A0."""
    # Column n has cells with tab, newline, NEL, LS, and plain spaces
    H = ["n", "ref"]
    R = [
        ["\t3", "4"],
        ["10", "10"],
        ["2\n", "1"],
        [f"{LS}5", "6"],
        [f"{NEL}7", "7"],
        ["5", f"{NBSP}8"],
    ]
    t = _tab(H, R)

    # N06: Left numeric expression with diverse whitespace
    step_n06 = _cond([_clause("n", "less_than", "6")])
    item_n06 = {"id": "n06_ws", "step": step_n06}
    res_n06 = _by_id(_run_items(t, [item_n06]), "n06_ws")
    assert res_n06["status"] == "same" and res_n06.get("refusal") is None
    expected_rows_n06 = [
        ["\t3", "4", "Y"],
        ["10", "10", "N"],
        ["2\n", "1", "Y"],
        [f"{LS}5", "6", "Y"],
        [f"{NEL}7", "7", "N"],
        ["5", f"{NBSP}8", "Y"],
    ]
    assert _engine_rows(t, item_n06) == expected_rows_n06

    # N07: Right column numeric comparison with diverse whitespace
    H_n07 = ["n", "ref"]
    R_n07 = [
        ["10", "\t3"],
        ["1", "10"],
        ["5", "2\n"],
        ["6", f"{LS}5"],
        ["8", f"{NEL}7"],
        ["4", f"{NBSP}5"],
    ]
    t_n07 = _tab(H_n07, R_n07)
    step_n07 = _cond([_clause("n", "less_than", "ref", kind="column")])
    item_n07 = {"id": "n07_ws", "step": step_n07}
    res_n07 = _by_id(_run_items(t_n07, [item_n07]), "n07_ws")
    assert res_n07["status"] == "same" and res_n07.get("refusal") is None
    expected_rows_n07 = [
        ["10", "\t3", "N"],
        ["1", "10", "Y"],
        ["5", "2\n", "N"],
        ["6", f"{LS}5", "N"],
        ["8", f"{NEL}7", "N"],
        ["4", f"{NBSP}5", "Y"],
    ]
    assert _engine_rows(t_n07, item_n07) == expected_rows_n07


# ------------------------------------------------------------------ Part D3: Sequence Mode

def test_sequence_mode_null_kept_as_null_in_intermediate_table() -> None:
    """N32: NULL kept as NULL (not converted to empty string '') across sequence steps."""
    H = ["a", "b", "c"]
    R = [["1", "x", "y"], ["2", "p", "q"], ["3", "r", "s"]]
    seq = [
        {"op": "transpose_table"},
        {"op": "unpivot_other_columns", "columns": ["Column1"], "attribute_name": "at", "value_name": "va"},
    ]
    t = {**_tab(H, R), "nulls": [[0, "b"], [2, "c"]]}
    item = {"id": "seq_null", "step": {"op": "sequence"}, "sequence": seq}
    res = _by_id(_run_items(t, [item]), "seq_null")
    assert res["status"] == "same" and res.get("refusal") is None


def test_sequence_mode_column_facts_recomputed_on_derived_table() -> None:
    """N30: column facts are recomputed on derived table (e.g. dirty numeric column becomes clean)."""
    H = ["n", "m"]
    R = [["m", "n"], ["1", "1e30"], ["2", "٣"], ["3", "7"], ["4", "0.1234567890123456789"]]
    seq = [
        {"op": "promote_headers"},
        _cond([_clause("n", "greater_than", "5")]),
    ]
    t = _tab(H, R)
    item = {"id": "seq_facts", "step": {"op": "sequence"}, "sequence": seq}
    res = _by_id(_run_items(t, [item]), "seq_facts")
    assert res["status"] == "refused"
    assert "holds numeric text SQL does not read" in res.get("refusal", "")


def test_sequence_mode_row_count_recomputed_on_derived_table() -> None:
    """N31: total rows recomputed on derived table after split_column_to_rows expands row count."""
    H = ["id", "k"]
    R = [["1", "a;b"], ["2", "c"], ["3", "d"], ["4", "e"], ["5", "f"]]
    # 5 rows expanded to 6 rows, then transposed (must have 6 columns Column1..Column6)
    seq = [
        {"op": "split_column_to_rows", "column": "k", "delimiter": ";"},
        {"op": "transpose_table"},
    ]
    t = _tab(H, R)
    item = {"id": "seq_rows", "step": {"op": "sequence"}, "sequence": seq}
    res = _by_id(_run_items(t, [item]), "seq_rows")
    assert res["status"] == "same" and res.get("refusal") is None
    assert _engine_rows(t, item) == [["1", "1", "2", "3", "4", "5"], ["a", "b", "c", "d", "e", "f"]]


# ------------------------------------------------------------------ Part E: Limits Decision

def test_raised_limits_exceed_500000_cells() -> None:
    """Part E: 100,000 rows x 6 columns (600,000 cells) runs with raised limits and matches engine."""
    N = 100_000
    H = ["id", "k", "a", "b", "c", "d"]
    rows = [[str(i), "x;y;z", "1", "2", "3", "4"] for i in range(N)]

    steps = {
        "unpivot": {"op": "unpivot_columns", "columns": ["a", "b"], "attribute_name": "at", "value_name": "val"},
        "split_rows": {"op": "split_column_to_rows", "column": "k", "delimiter": ";"},
        "positions": {"op": "split_column_by_positions", "column": "id", "positions": [0, 1]},
        "conditional": _cond([_clause("a", "equals", "1")], name="new_c", else_val="no"),
    }

    t = _tab(H, rows)
    for name, st in steps.items():
        t0 = time.time()
        res = _by_id(_run_items(t, [{"id": name, "step": st}]), name)
        dt = time.time() - t0
        print(f"Timing for {name:12s} (600k cells): {dt:.2f}s")
        assert res["status"] == "same", f"{name} failed: {res}"
        assert res.get("refusal") is None, f"{name} was refused: {res.get('refusal')}"


def test_each_delimiter_split_above_500000_cells_is_same() -> None:
    """Part E: the store path does not mirror the engine's cell limit for split_column_by_each_delimiter.

    100,000 rows x 3 columns, each k cell "a;b;c;d" split by ";" gives 5 output columns of 100,000 rows
    (600,000 cells, over the 500,000-cell import limit): the store result must equal the engine result run with raised limits.
    """
    N = 100_000
    rows = [[str(i), "a;b;c;d", "z"] for i in range(N)]
    t = _tab(["id", "k", "z"], rows)
    item = {"id": "each", "step": {"op": "split_column_by_each_delimiter", "column": "k", "delimiter": ";"}}
    res = _by_id(_run_items(t, [item]), "each")
    assert res["status"] == "same", res
    assert res.get("refusal") is None, res.get("refusal")
    assert N * (3 - 1 + 4) > 500_000


def test_append_above_500000_cells_is_same() -> None:
    """Part E: append_candidates (query_engine) limits are raised too: 90,000 + 100 rows x 6 columns is 540,600 cells."""
    first = [[str(i), "x", "y", "1", "2", "3"] for i in range(90_000)]
    second = [[str(i), "x", "y", "1", "2", "3"] for i in range(100)]
    t = {"headers": list("abcdef"), "rows": first, "rows_2": second}
    res = _by_id(_run_items(t, [{"id": "ap", "step": {"op": "append"}}]), "ap")
    assert res["status"] == "same", res
    assert res.get("refusal") is None, res.get("refusal")
    assert (90_000 + 100) * 6 > 500_000


def test_append_above_100000_rows_is_same() -> None:
    """Part E: the engine's append row limit (query_engine.MAX_DATA_ROWS, 100,000) is raised too: 100,000 + 100 rows x 2 columns."""
    first = [[str(i), "x"] for i in range(100_000)]
    second = [[str(i), "y"] for i in range(100)]
    t = {"headers": ["a", "b"], "rows": first, "rows_2": second}
    res = _by_id(_run_items(t, [{"id": "ap_rows", "step": {"op": "append"}}]), "ap_rows")
    assert res["status"] == "same", res
    assert res.get("refusal") is None, res.get("refusal")


def _limit_constants() -> dict[str, int]:
    from analytics_studio import file_import, query_engine, transformations

    return {
        f"{mod.__name__}.{name}": getattr(mod, name)
        for mod in (file_import, transformations, query_engine)
        for name in ("MAX_CELLS", "MAX_DATA_ROWS", "MAX_SOURCE_BYTES")
        if hasattr(mod, name)
    }


def test_raised_engine_limits_raises_every_copy_and_restores_all_on_every_exit() -> None:
    """Part E: all limit constants are raised inside the context and restored after normal exit, error and KeyboardInterrupt."""
    import pytest

    from analytics_studio import query_engine
    from tools.pq_store_diff import raised_engine_limits

    before = _limit_constants()
    assert before["analytics_studio.query_engine.MAX_CELLS"] == 500_000
    with raised_engine_limits():
        inside = _limit_constants()
        assert inside["analytics_studio.query_engine.MAX_CELLS"] == 100_000_000
        assert inside["analytics_studio.query_engine.MAX_DATA_ROWS"] == 1_000_000
        assert query_engine.MAX_CELLS == 100_000_000
        assert all(inside[k] > before[k] for k in before), (before, inside)
    assert _limit_constants() == before
    with pytest.raises(RuntimeError):
        with raised_engine_limits():
            raise RuntimeError("boom")
    assert _limit_constants() == before
    with pytest.raises(KeyboardInterrupt):
        with raised_engine_limits():
            raise KeyboardInterrupt
    assert _limit_constants() == before
    with raised_engine_limits():
        with raised_engine_limits():
            pass
        assert query_engine.MAX_CELLS == 100_000_000
    assert _limit_constants() == before


def test_import_limits_crossed_by_100001_rows_and_over_10_mib() -> None:
    """Part E: 100,001 rows of about 130 bytes cross file_import.MAX_DATA_ROWS (100,000) and MAX_SOURCE_BYTES (10 MiB)."""
    from analytics_studio import file_import

    pad = "x" * 120
    rows = [[str(i), pad] for i in range(100_001)]
    csv_bytes = sum(len(a) + len(b) + 2 for a, b in rows)
    assert len(rows) > file_import.MAX_DATA_ROWS
    assert csv_bytes > file_import.MAX_SOURCE_BYTES
    t = _tab(["id", "pad"], rows)
    item = {"id": "top", "step": {"op": "keep_top_rows", "count": 3}}
    try:
        data = _run_items(t, [item])
    except Exception as exc:  # an import limit not raised makes the tool itself crash
        raise AssertionError(f"the tool crashed on 100,001 rows: {exc!r}") from exc
    res = _by_id(data, "top")
    assert res["status"] == "same", res
    assert res.get("refusal") is None, res.get("refusal")
    from tools.pq_store_diff import raised_engine_limits

    with raised_engine_limits():
        assert _engine_rows(t, item) == [["0", pad], ["1", pad], ["2", pad]]
