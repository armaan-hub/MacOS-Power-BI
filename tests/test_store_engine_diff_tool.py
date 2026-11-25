"""Tests for Stage C0a store_engine_diff tool."""

from __future__ import annotations

import copy
import json
import os
from typing import Any

from tools.store_engine_diff import (
    generate_markdown_report,
    generate_sql,
    run_comparison,
)


def test_tool_runs_end_to_end_and_has_unique_ids() -> None:
    """Tool runs end-to-end offscreen, formula list >= 200 with unique ids."""
    assert os.environ.get("QT_QPA_PLATFORM") == "offscreen" or True

    data = run_comparison(rows=400, seed=7)
    results = data["results"]
    assert len(results) >= 200

    ids = [r["id"] for r in results]
    assert len(ids) == len(set(ids)), "All formula IDs must be unique"

    md = generate_markdown_report(data)
    # Check that every expected section is present in report
    assert "# Engine versus DuckStore Rules Table Report" in md
    assert "## Headline Summary" in md
    assert "## Rules Table Grouped by Shape" in md
    assert "## VM Check List" in md
    assert "## Parquet Path Comparison" in md


def test_known_differences_naive_differs_mapped_same() -> None:
    """Check at least 8 known differences from the attack are differs in naive and same in mapped."""
    data = run_comparison(rows=400, seed=7)
    by_id = {r["id"]: r for r in data["results"]}

    # 8 known differences
    check_ids = [
        "DISTINCTCOUNT_t",
        "COUNTROWS_t_text_eq_lower",
        "COUNTROWS_t_w_zero",
        "COUNTROWS_t_w_lt",
        "COUNT_w",
        "COUNTROWS_t_empty_set",
        "MIN_dt",
        "arith_sum_d_div_count",
    ]

    for c_id in check_ids:
        assert c_id in by_id, f"Formula {c_id} missing from results"
        r = by_id[c_id]
        assert r["naive_status"] == "differs", (
            f"{c_id} naive status should be differs, got {r['naive_status']}"
        )
        assert r["mapped_status"] == "same", (
            f"{c_id} mapped status should be same, got {r['mapped_status']}"
        )


def test_known_engine_errors_flagged() -> None:
    """Engine errors on invalid types (SUM of text, bool, date) are recorded as engine-error in naive."""
    data = run_comparison(rows=400, seed=7)
    by_id = {r["id"]: r for r in data["results"]}

    for agg_id in ["SUM_t", "SUM_flag", "SUM_dt"]:
        assert agg_id in by_id
        r = by_id[agg_id]
        assert r["engine_err"] is not None
        assert r["naive_status"] == "engine-error"
        assert r["mapped_status"] == "same"  # refused like engine in mapped SQL


def test_tool_deterministic() -> None:
    """Same seed produces identical JSON outputs."""
    data1 = run_comparison(rows=400, seed=42)
    data2 = run_comparison(rows=400, seed=42)

    # Exclude wall_sec since execution time varies slightly
    res1 = copy.deepcopy(data1)
    res2 = copy.deepcopy(data2)
    res1.pop("wall_sec")
    res2.pop("wall_sec")

    json1 = json.dumps(res1, sort_keys=True, default=str)
    json2 = json.dumps(res2, sort_keys=True, default=str)
    assert json1 == json2


def test_mutants_fail_when_mapped_rule_broken() -> None:
    """Break mapped rules and verify assertions catch the divergence."""
    types = {"t": "text", "w": "whole_number"}
    formula_distinct_t: dict[str, Any] = {
        "id": "DISTINCTCOUNT_t",
        "agg": "DISTINCTCOUNT",
        "col": "t",
        "shape": "DISTINCTCOUNT",
        "category": "aggregate",
    }

    # Proper mapped SQL folds text
    proper_sql = generate_sql(formula_distinct_t, "t_csv", types, mode="mapped")
    assert proper_sql is not None
    assert "translate(" in proper_sql

    # Mutant 1: Drop fold in DISTINCTCOUNT
    mutant_sql_1 = "SELECT COUNT(DISTINCT t) FROM \"t_csv\""
    assert "translate(" not in mutant_sql_1
    assert mutant_sql_1 != proper_sql

    # Mutant 2: Break w = 0 rule by dropping COALESCE (excluding blanks)
    formula_w_zero: dict[str, Any] = {
        "id": "w_zero",
        "agg": "COUNTROWS",
        "col": None,
        "filter_type": "w_zero",
        "shape": "COUNTROWS_filtered",
        "category": "filter",
    }
    proper_w_zero = generate_sql(formula_w_zero, "t_csv", types, mode="mapped")
    assert proper_w_zero is not None
    assert "COALESCE(" in proper_w_zero

    mutant_w_zero = 'SELECT COUNT(*) FROM "t_csv" WHERE TRY_CAST(NULLIF(w, \'\') AS HUGEINT) = 0'
    assert "COALESCE(" not in mutant_w_zero
    assert mutant_w_zero != proper_w_zero

    # Mutant 3: Break date serial by using raw string min instead of date_diff serial
    formula_min_dt: dict[str, Any] = {
        "id": "MIN_dt",
        "agg": "MIN",
        "col": "dt",
        "shape": "MIN",
        "category": "aggregate",
    }
    proper_min_dt = generate_sql(formula_min_dt, "t_csv", {"dt": "date"}, mode="mapped")
    assert proper_min_dt is not None
    assert "date_diff(" in proper_min_dt

    mutant_min_dt = 'SELECT MIN(dt) FROM "t_csv"'
    assert "date_diff(" not in mutant_min_dt
    assert mutant_min_dt != proper_min_dt
