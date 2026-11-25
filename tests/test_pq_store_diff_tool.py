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


# ------------------------------------------------------------------ D0b helpers

NBSP = " "


def _baseline() -> dict[str, Any]:
    with open(BASELINE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _statuses(data: dict[str, Any]) -> dict[str, str]:
    return {r["id"]: r["status"] for r in data["results"]}


def _by_id(data: dict[str, Any], item_id: str) -> dict[str, Any]:
    return next(r for r in data["results"] if r["id"] == item_id)


def _run_items(
    dataset: dict[str, Any],
    items: list[dict[str, Any]],
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return run_pq_step_diff(dataset=dataset, items=items, overrides=overrides)


def _engine_rows(dataset: dict[str, Any], item: dict[str, Any], second: bool = False) -> list[list[str | None]]:
    """Run one step on the real step engine for a small table (hand-check helper)."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "t.csv"
        path_2 = Path(td) / "t2.csv"
        for p, body in ((path, dataset["rows"]), (path_2, dataset.get("rows_2", []))):
            with open(p, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(dataset["headers"])
                w.writerows(body)
        res = pq_store_diff.execute_engine_step(item, parse_file(path), parse_file(path_2))
        assert not isinstance(res, str), res
        return res[1]


# 8 rows with distinct ids and names: used for the hand-checked mutant tests.
T8 = {
    "headers": ["id", "name"],
    "rows": [[str(i), n] for i, n in enumerate("abcdefgh", 1)],
    "rows_2": [[str(i), n] for i, n in enumerate("ABCD", 11)],
}
ITEM_RANGE = {"id": "range_3_2", "step": {"op": "keep_range_rows", "first_row": 3, "count": 2}}
ITEM_INDEX = {
    "id": "index_10_5",
    "step": {"op": "add_index_column", "new_name": "Idx", "start": 10, "increment": 5},
}
ITEM_ALT = {
    "id": "alt_1_1_1",
    "step": {"op": "remove_alternate_rows", "first_row_to_remove": 1, "remove_count": 1, "keep_count": 1},
}
ITEM_APPEND = {"id": "append", "step": {"op": "append"}, "second_table": "t_csv_2"}


def _assert_mutant_differs_and_exits_1(
    dataset: dict[str, Any], item: dict[str, Any], mutant: str, clean_rows: list[list[str | None]]
) -> None:
    """Clean run equals the hand-checked rows and is same; the mutant run differs and the tool exits 1."""
    assert _engine_rows(dataset, item) == clean_rows
    clean = _run_items(dataset, [item])
    assert _by_id(clean, item["id"])["status"] == "same"
    data = _run_items(dataset, [item], overrides={mutant: True})
    assert _by_id(data, item["id"])["status"] == "differs"
    code, msgs = evaluate_exit_policy(data, {"classes": []})
    assert code == 1
    assert any("unclassified differences" in m for m in msgs)


# ------------------------------------------------------------------ item 1: NULL versus ''


def test_normalize_cell_keeps_none_and_empty_apart() -> None:
    """The one cell rule: None stays None, '' stays '', numbers become text."""
    assert pq_store_diff.normalize_cell(None) is None
    assert pq_store_diff.normalize_cell("") == ""
    assert pq_store_diff.normalize_cell(5) == "5"
    assert pq_store_diff.normalize_cell(None) != pq_store_diff.normalize_cell("")


def test_step_engine_returns_empty_text_not_none_for_blank_csv_cells() -> None:
    """The rule is justified by what the engine returns: '' for blank CSV cells in every step (measured)."""
    dataset = {"headers": ["a", "b"], "rows": [["1", ""], ["", "x"], ["", ""]], "rows_2": [["", "z"]]}
    items = [i for i in pq_store_diff.build_step_catalog(dataset["headers"]) if i["id"] != "count_rows"]
    seen_blank = 0
    for item in items:
        with tempfile.TemporaryDirectory() as td:
            for name, body in (("t.csv", dataset["rows"]), ("t2.csv", dataset["rows_2"])):
                with open(Path(td) / name, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(dataset["headers"])
                    w.writerows(body)
            res = pq_store_diff.execute_engine_step(item, parse_file(Path(td) / "t.csv"), parse_file(Path(td) / "t2.csv"))
        if isinstance(res, str):
            continue
        for row in res[1]:
            assert None not in row, item["id"]
            seen_blank += sum(1 for v in row if v == "")
    assert seen_blank > 0


def test_mutant_null_for_blank_differs_and_exits_1() -> None:
    """Mutant: SQL returns NULL for a blank cell. The store holds '' so the tool must differ and exit 1."""
    dataset = {"headers": ["a", "b"], "rows": [["1", ""], ["", "x"], ["y", ""]]}
    clean = run_pq_step_diff(dataset=dataset)
    assert {r["status"] for r in clean["results"]} == {"same"}
    assert evaluate_exit_policy(clean, _baseline())[0] in (0, 1)  # refused set differs for 2 columns; not the point here

    data = run_pq_step_diff(dataset=dataset, overrides={"mutant_null_for_blank": True})
    statuses = _statuses(data)
    assert statuses["keep_columns_all"] == "differs"
    assert "None" in _by_id(data, "keep_columns_all")["diff_reason"]
    code, msgs = evaluate_exit_policy(data, {"classes": []})
    assert code == 1
    assert any("unclassified differences" in m for m in msgs)


def test_none_is_a_difference_even_without_the_mutant_hook() -> None:
    """A NULL cell from SQL against '' from the engine is flagged by the comparison itself."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "t.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["a", "b"])
            w.writerows([["1", "x"], ["", "y"]])
        store = DuckStore(str(Path(td) / "s.db"))
        import_csv_to_store(store, "t", path, {})
        eng = pq_store_diff.execute_engine_step(
            {"id": "k", "step": {"op": "keep_columns", "columns": ["a"]}}, parse_file(path)
        )
        sql_h, sql_r = pq_store_diff.execute_store_step(("SELECT NULLIF(\"a\", '') AS \"a\" FROM \"t\" ORDER BY rowid", ["a"]), store)
        assert eng[1] == [["1"], [""]]
        assert sql_r == [["1"], [None]]
        assert eng[1] != sql_r


# ------------------------------------------------------------------ item 2: data shapes and small tables


def test_generator_plants_required_shapes() -> None:
    """Duplicate rows (adjacent and not), whitespace cells (space, tab, NBSP), one whitespace-only row, blank rows."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "g.csv"
        pq_store_diff.generate_pq_dataset(path, rows=600, seed=3)
        with open(path, "r", newline="", encoding="utf-8") as f:
            body = list(csv.reader(f))[1:]
    assert len(body) == 600
    assert sum(1 for r in body if all(c == "" for c in r)) == 2  # rows 250 and 500
    ws_rows = [r for r in body if all(c != "" and c.strip() == "" for c in r)]
    assert len(ws_rows) == 1
    adjacent = sum(1 for a, b in zip(body, body[1:]) if a == b and any(a))
    assert adjacent >= 5
    seen = set()
    non_adjacent = 0
    for idx, r in enumerate(body):
        t = tuple(r)
        if t in seen and any(r) and (idx == 0 or body[idx - 1] != r):
            non_adjacent += 1
        seen.add(t)
    assert non_adjacent >= 2
    cells = {c for r in body for c in r}
    assert {" ", "\t", NBSP} <= cells


def test_catalog_works_for_one_and_two_columns() -> None:
    """build_step_catalog no longer crashes on narrow tables and keeps unique ids."""
    for headers in (["only"], ["a", "b"]):
        ids = [i["id"] for i in pq_store_diff.build_step_catalog(headers)]
        assert len(ids) == len(set(ids)) >= 30


def _assert_all_same(data: dict[str, Any]) -> None:
    bad = {k: v for k, v in _statuses(data).items() if v != "same"}
    assert not bad, bad


def test_small_table_one_column() -> None:
    """One column: 'remove the last column' is refused because of the real engine error.

    A blank line in a one-column CSV is dropped by BOTH the engine parser and the store import
    (it cannot be told from an empty line), so the table below has 2 rows, not 3.
    """
    dataset = {"headers": ["id"], "rows": [["1"], [""], ["3"]], "rows_2": [["9"]]}
    data = run_pq_step_diff(dataset=dataset)
    _assert_all_same(data)
    last = _by_id(data, "remove_column_id")
    assert last["refusal"] is not None
    assert "Cannot remove the last column from a table." in last["refusal_reason"]
    item = {"id": "rm", "step": {"op": "remove_column", "column": "id"}}
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "t.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id"])
            w.writerows(dataset["rows"])
        err = pq_store_diff.execute_engine_step(item, parse_file(path))
    assert isinstance(err, str) and "Cannot remove the last column from a table." in err
    assert _engine_rows(dataset, {"id": "c", "step": {"op": "count_rows"}}) == [["2"]]
    assert _engine_rows(dataset, {"id": "r", "step": {"op": "remove_blank_rows"}}) == [["1"], ["3"]]


def test_small_table_two_columns() -> None:
    # The all-blank row ["", ""] is dropped when the CSV is loaded, on both sides (measured).
    dataset = {"headers": ["a", "b"], "rows": [["1", "x"], ["", ""], ["2", ""]], "rows_2": [["7", "z"]]}
    data = run_pq_step_diff(dataset=dataset)
    _assert_all_same(data)
    assert _engine_rows(dataset, ITEM_APPEND) == [["1", "x"], ["2", ""], ["7", "z"]]


def test_small_table_empty_header_only() -> None:
    """Header only: every step agrees; count is 0 and the added index column exists with no rows."""
    dataset = {"headers": ["id", "name"], "rows": [], "rows_2": []}
    data = run_pq_step_diff(dataset=dataset)
    _assert_all_same(data)
    assert _engine_rows(dataset, {"id": "c", "step": {"op": "count_rows"}}) == [["0"]]
    assert _engine_rows(dataset, ITEM_INDEX) == []


def test_small_table_single_row() -> None:
    dataset = {"headers": ["id", "name"], "rows": [["1", "a"]], "rows_2": [["2", "b"]]}
    data = run_pq_step_diff(dataset=dataset)
    _assert_all_same(data)
    assert _engine_rows(dataset, ITEM_ALT) == []
    assert _engine_rows(dataset, ITEM_INDEX) == [["1", "a", "10"]]


def test_small_table_whitespace_only_cells() -> None:
    """Space, tab and NBSP cells are not blank: remove_blank_rows drops only the truly empty row."""
    rows = [[" ", ""], ["\t", "\t"], [NBSP, ""], ["", ""], ["x", "y"]]
    dataset = {"headers": ["c1", "c2"], "rows": rows, "rows_2": [[NBSP, " "]]}
    data = run_pq_step_diff(dataset=dataset)
    _assert_all_same(data)
    assert _engine_rows(dataset, {"id": "r", "step": {"op": "remove_blank_rows"}}) == [
        [" ", ""], ["\t", "\t"], [NBSP, ""], ["x", "y"],
    ]


def test_small_table_duplicate_rows() -> None:
    rows = [["1", "a"], ["1", "a"], ["1", "a"], ["2", "b"], ["1", "a"]]
    dataset = {"headers": ["id", "name"], "rows": rows, "rows_2": [["1", "a"], ["1", "a"]]}
    data = run_pq_step_diff(dataset=dataset)
    _assert_all_same(data)
    assert _engine_rows(dataset, ITEM_APPEND) == rows + [["1", "a"], ["1", "a"]]
    assert _engine_rows(dataset, ITEM_INDEX)[-1] == ["1", "a", "30"]


def test_small_table_all_blank_rows_mixed_with_data() -> None:
    rows = [["", ""], ["1", "a"], ["", ""], ["", ""], ["2", ""], ["", ""]]
    dataset = {"headers": ["id", "name"], "rows": rows, "rows_2": [["", ""], ["3", "c"]]}
    data = run_pq_step_diff(dataset=dataset)
    _assert_all_same(data)
    # All-blank rows are dropped at load on both sides, so remove_blank_rows alone changes nothing ...
    plain = {"id": "r", "step": {"op": "remove_blank_rows"}}
    assert _engine_rows(dataset, plain) == [["1", "a"], ["2", ""]]
    # ... and it only has work to do after a column selection leaves rows blank (id is blank in none, name in one).
    after_keep = {
        "id": "r2",
        "pre_step": {"op": "keep_columns", "columns": ["name"]},
        "step": {"op": "remove_blank_rows"},
    }
    assert _engine_rows(dataset, after_keep) == [["a"]]
    assert _by_id(data, "remove_blank_rows_after_keep_last_1")["status"] == "same"


# ------------------------------------------------------------------ item 3: dedicated mutants on hand-checked tables


def test_mutant_range_start_off_by_one() -> None:
    """keep_range_rows(first_row=3, count=2) on 8 rows is ids 3,4; offset + 1 gives 4,5."""
    _assert_mutant_differs_and_exits_1(T8, ITEM_RANGE, "mutant_range_start_off_by_one", [["3", "c"], ["4", "d"]])


def test_mutant_range_count_off_by_one() -> None:
    """The same range with count + 1 gives ids 3,4,5."""
    _assert_mutant_differs_and_exits_1(T8, ITEM_RANGE, "mutant_range_count_off_by_one", [["3", "c"], ["4", "d"]])


def test_mutant_index_start_off_by_one() -> None:
    """add_index_column(start=10, increment=5): first row 10; start + 1 gives 11."""
    clean = [[str(i), n, str(10 + 5 * (i - 1))] for i, n in enumerate("abcdefgh", 1)]
    _assert_mutant_differs_and_exits_1(T8, ITEM_INDEX, "mutant_index_start_off_by_one", clean)


def test_mutant_index_increment_ignored() -> None:
    """The same index with increment forced to 1 gives 10,11,12 instead of 10,15,20."""
    clean = [[str(i), n, str(10 + 5 * (i - 1))] for i, n in enumerate("abcdefgh", 1)]
    _assert_mutant_differs_and_exits_1(T8, ITEM_INDEX, "mutant_index_increment_one", clean)


def test_mutant_append_column_order() -> None:
    """Append: the second table's columns taken in reverse order put names under the id column."""
    clean = [[str(i), n] for i, n in enumerate("abcdefgh", 1)] + [[str(i), n] for i, n in enumerate("ABCD", 11)]
    _assert_mutant_differs_and_exits_1(T8, ITEM_APPEND, "mutant_append_column_order", clean)


def test_mutant_append_order_rn_then_src() -> None:
    """Append ORDER BY _rn, _src interleaves the two tables (1, 11, 2, 12, ...)."""
    clean = [[str(i), n] for i, n in enumerate("abcdefgh", 1)] + [[str(i), n] for i, n in enumerate("ABCD", 11)]
    _assert_mutant_differs_and_exits_1(T8, ITEM_APPEND, "mutant_append_order_rn_src", clean)


def test_mutant_append_order_src_only_is_not_killed_by_behaviour() -> None:
    """ORDER BY _src alone still returns each table in load order on DuckDB (measured on 8 rows).

    This is a measured limit, not a kill: the rule is not guarded by behaviour on this data.
    """
    data = _run_items(T8, [ITEM_APPEND], overrides={"mutant_append_order_src_only": True})
    assert _by_id(data, "append")["status"] == "same"


def test_mutant_append_order_src_only_killed_at_300_rows() -> None:
    """ORDER BY _src alone loses the load order inside each table once the tables are large enough
    (measured: 300 + 100 rows; not on 8 rows), and the tool exits 1."""
    clean = run_pq_step_diff(rows=300, seed=11, items=[ITEM_APPEND])
    assert _by_id(clean, "append")["status"] == "same"
    data = run_pq_step_diff(rows=300, seed=11, items=[ITEM_APPEND], overrides={"mutant_append_order_src_only": True})
    assert _by_id(data, "append")["status"] == "differs"
    assert evaluate_exit_policy(data, {"classes": []})[0] == 1


def test_mutant_alternate_rows_window_order() -> None:
    """remove_alternate_rows(1,1,1) on 8 rows keeps ids 2,4,6,8; a window over rowid DESC keeps 1,3,5,7."""
    clean = [["2", "b"], ["4", "d"], ["6", "f"], ["8", "h"]]
    _assert_mutant_differs_and_exits_1(T8, ITEM_ALT, "mutant_window_order_desc", clean)


def test_mutant_index_window_order() -> None:
    """add_index_column over a reversed window numbers the rows backwards."""
    clean = [[str(i), n, str(10 + 5 * (i - 1))] for i, n in enumerate("abcdefgh", 1)]
    _assert_mutant_differs_and_exits_1(T8, ITEM_INDEX, "mutant_window_order_desc", clean)


SLICING_OPS = ["keep_top_rows", "remove_top_rows", "keep_bottom_rows", "remove_bottom_rows", "keep_range_rows"]


def test_lint_slicing_steps_have_order_by_not_a_mutant_kill() -> None:
    """LINT on SQL text (not a mutant kill): every row-slicing SELECT contains ORDER BY.

    `mutant_no_order_by` cannot be killed by behaviour because DuckDB returns insertion order for a
    plain scan (measured at 1,000,000 rows); this lint is the only guard of that rule.
    """
    headers = ["id", "name"]
    items = [i for i in pq_store_diff.build_step_catalog(headers) if i["step"]["op"] in SLICING_OPS]
    assert {i["step"]["op"] for i in items} == set(SLICING_OPS)
    for item in items:
        sql, _ = generate_step_sql(item, headers, "t_csv", 8)
        assert "ORDER BY" in sql, item["id"]
        mutated, _ = generate_step_sql(item, headers, "t_csv", 8, overrides={"mutant_no_order_by": True})
        assert "ORDER BY" not in mutated, item["id"]


def test_lint_windows_are_explicitly_ordered() -> None:
    """LINT: no window function runs over an empty OVER (); row order is stated explicitly."""
    headers = ["id", "name"]
    for item in (ITEM_ALT, ITEM_INDEX):
        sql, _ = generate_step_sql(item, headers, "t_csv", 8)
        assert "OVER ()" not in sql
        assert "OVER (ORDER BY rowid)" in sql


# ------------------------------------------------------------------ item 4


def test_store_headers_come_from_the_cursor_description() -> None:
    """The headers of the SQL side are what the query returns, not the generator's declared list."""
    with tempfile.TemporaryDirectory() as td:
        store = DuckStore(str(Path(td) / "s.db"))
        headers, rows = pq_store_diff.execute_store_step(('SELECT 1 AS "p", 2 AS "q"', ["declared_wrong"]), store)
    assert headers == ["p", "q"]
    assert rows == [["1", "2"]]


def test_declared_header_mismatch_is_flagged_as_difference() -> None:
    """A mapping whose real column name differs from the engine's is a header difference."""
    dataset = {"headers": ["id", "name"], "rows": [["1", "a"]]}
    item = {"id": "rename", "step": {"op": "rename_column", "column": "id", "new_name": "key"}}
    clean = _run_items(dataset, [item])
    assert _by_id(clean, "rename")["status"] == "same"


def test_remove_blank_rows_is_not_vacuous_at_500_rows() -> None:
    """At 520 rows the plain step is the identity (all-blank rows are dropped at load, measured),
    and the step after a column selection removes the rows that became blank: same on both sides."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "g.csv"
        pq_store_diff.generate_pq_dataset(path, rows=520, seed=5)
        cand = parse_file(path)
        with open(path, "r", newline="", encoding="utf-8") as f:
            raw_body = list(csv.reader(f))[1:]
    assert len(raw_body) == 520
    assert sum(1 for r in raw_body if all(c == "" for c in r)) == 2  # rows 250 and 500 are in the file
    assert len(cand.rows) == 518  # and gone after the engine's parse
    data = run_pq_step_diff(rows=520, seed=5, item_filter=["remove_blank_rows", "remove_blank_rows_after_keep_last_1"])
    assert _statuses(data) == {"remove_blank_rows": "same", "remove_blank_rows_after_keep_last_1": "same"}
    last = pq_store_diff.build_step_catalog(list(cand.headers))
    item = next(i for i in last if i["id"] == "remove_blank_rows_after_keep_last_1")
    kept = pq_store_diff.execute_engine_step(item, cand)
    expected = sum(1 for r in cand.rows if r[cand.headers[-1]] != "")
    assert 0 < expected < 100 and len(kept[1]) == expected


def test_mutant_blank_counts_whitespace_kills_on_generated_300_rows() -> None:
    """Generated data holds one all-space row, so the whitespace mutant differs at 300 rows."""
    item = next(
        i for i in pq_store_diff.build_step_catalog(["id", "text_col", "num_col", "date_col", "cat_col", "blank_col"])
        if i["id"] == "remove_blank_rows_after_keep_last_1"
    )
    clean = run_pq_step_diff(rows=300, seed=9, items=[item])
    assert _by_id(clean, item["id"])["status"] == "same"
    data = run_pq_step_diff(rows=300, seed=9, items=[item], overrides={"mutant_blank_counts_whitespace": True})
    assert _by_id(data, item["id"])["status"] == "differs"
    assert evaluate_exit_policy(data, {"classes": []})[0] == 1


def test_full_catalog_at_300_rows_has_no_difference() -> None:
    """The generated shapes (whitespace, duplicates, blank rows) agree on every step at 300 rows."""
    data = run_pq_step_diff(rows=300, seed=11)
    _assert_all_same(data)
    assert evaluate_exit_policy(data, _baseline())[0] == 0
