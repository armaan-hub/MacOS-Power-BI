"""Tests for Stage D0a Power Query step differential tool (tools/pq_store_diff.py).

Every rule of the tool is tested by behaviour on small generated data or hand-checked tables:
mutants change ONE rule in the SQL mapping and prove a test fails by behaviour.
All mutation switches are inert by default and guarded.
"""

from __future__ import annotations

import copy
import csv
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from analytics_studio.file_import import ImportCandidate, parse_file
from analytics_studio.store import DuckStore, import_csv_to_store
from tools import pq_store_diff
from tools.pq_store_diff import (
    evaluate_exit_policy,
    generate_markdown_report,
    generate_step_sql,
    run_pq_step_diff,
)

BASELINE_FILE = Path(pq_store_diff.__file__).parent / "pq_store_diff_baseline.json"


@pytest.fixture(scope="module")
def run50() -> dict[str, Any]:
    return run_pq_step_diff(rows=50, seed=42)


@pytest.fixture(scope="module")
def run100() -> dict[str, Any]:
    return run_pq_step_diff(rows=100, seed=7)


# ------------------------------------------------------------------ end to end & baseline


def test_tool_runs_end_to_end_and_has_unique_ids(run100: dict[str, Any]) -> None:
    """Tool runs end-to-end offscreen, step catalog >= 50 with unique ids and markdown report."""
    results = run100["results"]
    assert len(results) >= 50

    ids = [r["id"] for r in results]
    assert len(ids) == len(set(ids)), "All step IDs must be unique"

    md = generate_markdown_report(run100)
    assert "# Power Query Step Differential Report (Stage D0a)" in md
    assert "## Counts by Step Operation" in md
    assert "## Power BI Answer Checks Needed" in md
    assert "## Deferred Steps (Slice 2+)" in md


def test_tool_deterministic(run50: dict[str, Any]) -> None:
    """Same seed produces identical results."""
    res1 = copy.deepcopy(run50)
    res2 = run_pq_step_diff(rows=50, seed=42)
    res1.pop("wall_sec")
    res2.pop("wall_sec")
    assert json.dumps(res1, sort_keys=True, default=str) == json.dumps(res2, sort_keys=True, default=str)


def test_baseline_file_valid() -> None:
    """pq_store_diff_baseline.json exists, is valid JSON, and has refused list."""
    assert BASELINE_FILE.exists()
    with open(BASELINE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "classes" in data
    assert "refused" in data
    assert isinstance(data["refused"], list)


def test_evaluate_exit_policy_clean(run50: dict[str, Any]) -> None:
    """Clean run with baseline exits 0 with no error messages."""
    with open(BASELINE_FILE, "r", encoding="utf-8") as f:
        baseline = json.load(f)
    code, msgs = evaluate_exit_policy(run50, baseline)
    assert code == 0
    assert msgs == []


# ------------------------------------------------------------------ hand-checked small tables


def test_hand_checked_small_tables_all_steps() -> None:
    """Hand-check all Tier 1 steps on a small known 3-row table."""
    with tempfile.TemporaryDirectory() as td:
        t_path = Path(td)
        csv_file = t_path / "t.csv"
        csv_file_2 = t_path / "t2.csv"
        db_file = t_path / "store.db"

        # Table 1: 3 rows
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "name", "val"])
            writer.writerow(["1", "alice", "10"])
            writer.writerow(["2", "", ""])  # blank row except id
            writer.writerow(["3", "bob", "30"])

        # Table 2: 2 rows for append
        with open(csv_file_2, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "name", "val"])
            writer.writerow(["4", "charlie", "40"])
            writer.writerow(["5", "david", "50"])

        store = DuckStore(str(db_file))
        import_csv_to_store(store, "t_csv", csv_file, {})
        import_csv_to_store(store, "t_csv_2", csv_file_2, {})
        cand = parse_file(csv_file)
        cand_2 = parse_file(csv_file_2)
        headers = ["id", "name", "val"]

        # 1. keep_columns
        item = {"id": "test_keep", "step": {"op": "keep_columns", "columns": ["name"]}}
        eng_h, eng_r = pq_store_diff.execute_engine_step(item, cand)
        sql, h = generate_step_sql(item, headers, "t_csv", 3)
        st_h, st_r = pq_store_diff.execute_store_step((sql, h), store)
        assert eng_h == st_h == ["name"]
        assert eng_r == st_r == [["alice"], [""], ["bob"]]

        # 2. remove_column
        item = {"id": "test_rem", "step": {"op": "remove_column", "column": "val"}}
        eng_h, eng_r = pq_store_diff.execute_engine_step(item, cand)
        sql, h = generate_step_sql(item, headers, "t_csv", 3)
        st_h, st_r = pq_store_diff.execute_store_step((sql, h), store)
        assert eng_h == st_h == ["id", "name"]
        assert eng_r == st_r == [["1", "alice"], ["2", ""], ["3", "bob"]]

        # 3. reorder_columns
        item = {"id": "test_reorder", "step": {"op": "reorder_columns", "columns": ["val", "id"]}}
        eng_h, eng_r = pq_store_diff.execute_engine_step(item, cand)
        sql, h = generate_step_sql(item, headers, "t_csv", 3)
        st_h, st_r = pq_store_diff.execute_store_step((sql, h), store)
        assert eng_h == st_h == ["val", "name", "id"]
        assert eng_r == st_r == [["10", "alice", "1"], ["", "", "2"], ["30", "bob", "3"]]

        # 4. rename_column
        item = {"id": "test_rename", "step": {"op": "rename_column", "column": "name", "new_name": "user"}}
        eng_h, eng_r = pq_store_diff.execute_engine_step(item, cand)
        sql, h = generate_step_sql(item, headers, "t_csv", 3)
        st_h, st_r = pq_store_diff.execute_store_step((sql, h), store)
        assert eng_h == st_h == ["id", "user", "val"]
        assert eng_r == st_r == [["1", "alice", "10"], ["2", "", ""], ["3", "bob", "30"]]

        # 5. duplicate_column
        item = {"id": "test_dup", "step": {"op": "duplicate_column", "column": "val", "new_name": "val2"}}
        eng_h, eng_r = pq_store_diff.execute_engine_step(item, cand)
        sql, h = generate_step_sql(item, headers, "t_csv", 3)
        st_h, st_r = pq_store_diff.execute_store_step((sql, h), store)
        assert eng_h == st_h == ["id", "name", "val", "val2"]
        assert eng_r == st_r == [["1", "alice", "10", "10"], ["2", "", "", ""], ["3", "bob", "30", "30"]]

        # 6. keep_top_rows
        item = {"id": "test_top", "step": {"op": "keep_top_rows", "count": 2}}
        eng_h, eng_r = pq_store_diff.execute_engine_step(item, cand)
        sql, h = generate_step_sql(item, headers, "t_csv", 3)
        st_h, st_r = pq_store_diff.execute_store_step((sql, h), store)
        assert eng_r == st_r == [["1", "alice", "10"], ["2", "", ""]]

        # 7. remove_top_rows
        item = {"id": "test_rem_top", "step": {"op": "remove_top_rows", "count": 1}}
        eng_h, eng_r = pq_store_diff.execute_engine_step(item, cand)
        sql, h = generate_step_sql(item, headers, "t_csv", 3)
        st_h, st_r = pq_store_diff.execute_store_step((sql, h), store)
        assert eng_r == st_r == [["2", "", ""], ["3", "bob", "30"]]

        # 8. keep_bottom_rows
        item = {"id": "test_bottom", "step": {"op": "keep_bottom_rows", "count": 1}}
        eng_h, eng_r = pq_store_diff.execute_engine_step(item, cand)
        sql, h = generate_step_sql(item, headers, "t_csv", 3)
        st_h, st_r = pq_store_diff.execute_store_step((sql, h), store)
        assert eng_r == st_r == [["3", "bob", "30"]]

        # 9. remove_bottom_rows
        item = {"id": "test_rem_bottom", "step": {"op": "remove_bottom_rows", "count": 1}}
        eng_h, eng_r = pq_store_diff.execute_engine_step(item, cand)
        sql, h = generate_step_sql(item, headers, "t_csv", 3)
        st_h, st_r = pq_store_diff.execute_store_step((sql, h), store)
        assert eng_r == st_r == [["1", "alice", "10"], ["2", "", ""]]

        # 10. keep_range_rows
        item = {"id": "test_range", "step": {"op": "keep_range_rows", "first_row": 2, "count": 1}}
        eng_h, eng_r = pq_store_diff.execute_engine_step(item, cand)
        sql, h = generate_step_sql(item, headers, "t_csv", 3)
        st_h, st_r = pq_store_diff.execute_store_step((sql, h), store)
        assert eng_r == st_r == [["2", "", ""]]

        # 11. remove_alternate_rows
        item = {
            "id": "test_alt",
            "step": {"op": "remove_alternate_rows", "first_row_to_remove": 1, "remove_count": 1, "keep_count": 1},
        }
        eng_h, eng_r = pq_store_diff.execute_engine_step(item, cand)
        sql, h = generate_step_sql(item, headers, "t_csv", 3)
        st_h, st_r = pq_store_diff.execute_store_step((sql, h), store)
        assert eng_r == st_r == [["2", "", ""]]

        # 12. count_rows
        item = {"id": "test_count", "step": {"op": "count_rows"}}
        eng_h, eng_r = pq_store_diff.execute_engine_step(item, cand)
        sql, h = generate_step_sql(item, headers, "t_csv", 3)
        st_h, st_r = pq_store_diff.execute_store_step((sql, h), store)
        assert eng_h == st_h == ["Count"]
        assert eng_r == st_r == [["3"]]

        # 13. add_index_column
        item = {
            "id": "test_index",
            "step": {"op": "add_index_column", "new_name": "Idx", "start": 10, "increment": 5},
        }
        eng_h, eng_r = pq_store_diff.execute_engine_step(item, cand)
        sql, h = generate_step_sql(item, headers, "t_csv", 3)
        st_h, st_r = pq_store_diff.execute_store_step((sql, h), store)
        assert eng_h == st_h == ["id", "name", "val", "Idx"]
        assert eng_r == st_r == [
            ["1", "alice", "10", "10"],
            ["2", "", "", "15"],
            ["3", "bob", "30", "20"],
        ]

        # 14. remove_blank_rows
        cand_with_blank = ImportCandidate(
            kind="csv",
            headers=["a", "b"],
            rows=[{"a": "x", "b": "y"}, {"a": "", "b": None}, {"a": "z", "b": "w"}],
            options={},
            notices=[],
        )
        with open(t_path / "blank.csv", "w", newline="", encoding="utf-8") as bf:
            w = csv.writer(bf)
            w.writerow(["a", "b"])
            w.writerow(["x", "y"])
            w.writerow(["", ""])
            w.writerow(["z", "w"])
        import_csv_to_store(store, "t_blank", t_path / "blank.csv", {})
        item_blank = {"id": "test_blank", "step": {"op": "remove_blank_rows"}}
        eng_h, eng_r = pq_store_diff.execute_engine_step(item_blank, cand_with_blank)
        sql, h = generate_step_sql(item_blank, ["a", "b"], "t_blank", 3)
        st_h, st_r = pq_store_diff.execute_store_step((sql, h), store)
        assert eng_r == st_r == [["x", "y"], ["z", "w"]]

        # 15. append
        item_append = {"id": "test_append", "step": {"op": "append"}, "second_table": "t_csv_2"}
        eng_h, eng_r = pq_store_diff.execute_engine_step(item_append, cand, cand_2)
        sql, h = generate_step_sql(item_append, headers, "t_csv", 3)
        st_h, st_r = pq_store_diff.execute_store_step((sql, h), store)
        assert eng_h == st_h == headers
        assert len(eng_r) == len(st_r) == 5
        assert eng_r == st_r


# ------------------------------------------------------------------ exit policy & error tests


def test_forced_wrong_value_exits_1() -> None:
    """Forced wrong value in engine results triggers status 'differs' and evaluate_exit_policy exits 1."""
    with open(BASELINE_FILE, "r", encoding="utf-8") as f:
        baseline = json.load(f)

    data = run_pq_step_diff(rows=30, seed=42, overrides={"forced_wrong_value": True})
    code, msgs = evaluate_exit_policy(data, baseline)
    assert code == 1
    assert any("unclassified differences" in m for m in msgs)


def test_sql_error_exits_1() -> None:
    """SQL syntax error results in 'sql-error' status and evaluate_exit_policy exits 1."""
    with open(BASELINE_FILE, "r", encoding="utf-8") as f:
        baseline = json.load(f)

    data = run_pq_step_diff(rows=30, seed=42, overrides={"forced_sql_syntax_error": True})
    code, msgs = evaluate_exit_policy(data, baseline)
    assert code == 1
    assert any("SQL errors encountered" in m for m in msgs)


def test_refused_set_check_even_when_baseline_empty() -> None:
    """Baseline with empty refused list flags error if actual refusals exist."""
    data = run_pq_step_diff(rows=30, seed=42)
    empty_baseline = {"classes": [], "refused": []}
    code, msgs = evaluate_exit_policy(data, empty_baseline)
    assert code == 1
    assert any("Refused step set changed vs baseline" in m for m in msgs)


def test_unknown_class_exits_1() -> None:
    """Difference with class not in baseline classes list exits 1."""
    with open(BASELINE_FILE, "r", encoding="utf-8") as f:
        baseline = json.load(f)

    data = run_pq_step_diff(
        rows=30,
        seed=42,
        overrides={"forced_wrong_value": True, "forced_diff_class": "unknown_random_class"},
    )
    code, msgs = evaluate_exit_policy(data, baseline)
    assert code == 1
    assert any("unclassified differences" in m for m in msgs)


# ------------------------------------------------------------------ mutant tests (behaviour on small data)


def test_mutant_top_off_by_one_fails() -> None:
    """Mutant: keep_top_rows with count + 1 differs in row count from engine."""
    data = run_pq_step_diff(
        rows=50,
        seed=42,
        overrides={"mutant_top_off_by_one": True},
        item_filter=["keep_top_rows_10"],
    )
    res = data["results"][0]
    assert res["status"] == "differs"
    assert "Row count mismatch" in res["diff_reason"]


def test_mutant_no_order_by_or_reverse_order_fails() -> None:
    """Mutant: reverse order in SQL mapping produces row order mismatch."""
    data = run_pq_step_diff(
        rows=50,
        seed=42,
        overrides={"mutant_reverse_order": True},
        item_filter=["keep_columns_subset"],
    )
    res = data["results"][0]
    assert res["status"] == "differs"
    assert "Row 0 mismatch" in res["diff_reason"]


def test_mutant_alt_offset_wrong_fails() -> None:
    """Mutant: remove_alternate_rows with offset + 1 produces row value mismatch."""
    data = run_pq_step_diff(
        rows=50,
        seed=42,
        overrides={"mutant_alt_offset_wrong": True},
        item_filter=["remove_alternate_rows_1_1_1"],
    )
    res = data["results"][0]
    assert res["status"] == "differs"
    assert "mismatch" in res["diff_reason"]


def test_mutant_blank_counts_whitespace_fails() -> None:
    """Mutant: remove_blank_rows treating whitespace-only cells as blank drops whitespace rows, differing from engine."""
    with tempfile.TemporaryDirectory() as td:
        csv_file = Path(td) / "ws.csv"
        db_file = Path(td) / "store.db"
        # Row with whitespace cell only
        with open(csv_file, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["c1", "c2"])
            w.writerow(["   ", ""])  # whitespace only
            w.writerow(["x", "y"])

        store = DuckStore(str(db_file))
        import_csv_to_store(store, "t_ws", csv_file, {})
        cand = parse_file(csv_file)

        item = {"id": "test_blank", "step": {"op": "remove_blank_rows"}}
        eng_h, eng_r = pq_store_diff.execute_engine_step(item, cand)
        # Normal SQL mapping
        sql_norm, h = generate_step_sql(item, ["c1", "c2"], "t_ws", 2)
        st_norm_h, st_norm_r = pq_store_diff.execute_store_step((sql_norm, h), store)
        assert eng_r == st_norm_r  # Both keep the whitespace row

        # Mutant SQL mapping: treats whitespace as blank
        sql_mut, h = generate_step_sql(
            item, ["c1", "c2"], "t_ws", 2, overrides={"mutant_blank_counts_whitespace": True}
        )
        st_mut_h, st_mut_r = pq_store_diff.execute_store_step((sql_mut, h), store)
        assert len(st_mut_r) == 1
        assert len(eng_r) == 2  # Mutant dropped whitespace row, engine kept it!
