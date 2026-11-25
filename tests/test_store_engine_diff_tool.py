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
    assert os.environ.get("QT_QPA_PLATFORM") == "offscreen"

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
    """Break mapped rules via overrides and verify assertions catch divergence (kills mutants)."""
    base_data = run_comparison(rows=400, seed=42)
    base_counts: dict[str, int] = {}
    for r in base_data["results"]:
        st = r["mapped_status"]
        base_counts[st] = base_counts.get(st, 0) + 1

    # Verify text_eq_space generates real fold comparison rather than hardcoded 1 = 0 fudge
    formula_space: dict[str, Any] = {
        "id": "text_eq_space",
        "agg": "COUNTROWS",
        "col": None,
        "filter_type": "text_eq_space",
        "shape": "COUNTROWS_filtered",
    }
    proper_space = generate_sql(formula_space, "t_csv", {"t": "text"}, mode="mapped")
    assert proper_space is not None
    assert "translate(" in proper_space
    assert "WHERE 1 = 0" not in proper_space

    # Mutants list to be killed through run_comparison overrides
    mutants = [
        ("M1 drop DISTINCTCOUNT fold", {"drop_distinct_fold": True}),
        ("M2 drop COALESCE in w=0", {"drop_w_zero_coalesce": True}),
        ("M3 drop rtrim in fold", {"drop_rtrim": True}),
        ("M4 SUM whole HUGEINT->DOUBLE", {"m4_whole_double": True}),
        ("M5 COUNTA counts non-blank only", {"m5_counta_nonblank": True}),
        ("M6 date serial epoch off by one", {"m6_date_epoch_off": True}),
        ("M8 SUM decimal DECIMAL->DOUBLE", {"m8_decimal_double": True}),
        ("M9 broken SQL where engine errors", {"broken_sql_m9": True}),
        ("M10 filter w<100 drop COALESCE", {"drop_w_lt_coalesce": True}),
        ("M11 empty-set guard removed", {"drop_empty_guard": True}),
        ("trim set space only", {"trim_set_space_only": True}),
        ("scale hardcoded 4", {"hardcode_scale_4": True}),
        ("NOBLANK = DISTINCTCOUNT", {"noblank_equals_distinctcount": True}),
    ]

    for name, overrides in mutants:
        mut_data = run_comparison(rows=400, seed=42, overrides=overrides)
        mut_counts: dict[str, int] = {}
        for r in mut_data["results"]:
            st = r["mapped_status"]
            mut_counts[st] = mut_counts.get(st, 0) + 1
        assert mut_counts != base_counts, f"Mutant '{name}' was not killed by assertions!"
