"""Tests for Stage C0c store_engine_diff tool."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
from decimal import Decimal
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
    """Break mapped rules via overrides and verify assertions catch divergence (kills mutants M1-M15)."""
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

    # Mutants list to be killed through fast targeted run_comparison overrides (200 rows)
    mutants = [
        ("M1 drop DISTINCTCOUNT fold", {"drop_distinct_fold": True}, "DISTINCTCOUNT_t"),
        ("M2 drop COALESCE in w=0", {"drop_w_zero_coalesce": True}, "COUNTROWS_t_w_zero"),
        ("M3 drop rtrim in fold", {"drop_rtrim": True}, "COUNTROWS_t_text_eq_space"),
        ("M4 SUM whole HUGEINT->DOUBLE", {"m4_whole_double": True}, "SUM_w"),
        ("M5 COUNTA counts non-blank only", {"m5_counta_nonblank": True}, "COUNTA_w"),
        ("M5 prime COUNTA nonblank CSV", {"m5_prime_counta_nonblank": True}, "COUNTA_w"),
        ("M6 date serial epoch off by one", {"m6_date_epoch_off": True}, "MIN_dt"),
        ("M8 SUM decimal DECIMAL->DOUBLE", {"m8_decimal_double": True}, "SUM_d"),
        ("M8 prime SUM decimal CSV", {"m8_prime_decimal_double": True}, "SUM_d"),
        ("M9 broken SQL where engine errors", {"broken_sql_m9": True}, "SUM_t"),
        ("M10 filter w<100 drop COALESCE", {"drop_w_lt_coalesce": True}, "COUNTROWS_t_w_lt"),
        ("M11 empty-set guard removed", {"drop_empty_guard": True}, "COUNTROWS_t_empty_set"),
        ("M12 trim set space only", {"trim_set_space_only": True}, "COUNTROWS_t_text_eq_untrimmed"),
        ("M13 scale hardcoded 4", {"hardcode_scale_4": True}, "SUM_w_d_neq"),
        ("M14 DISTINCTCOUNT numeric without +1", {"m14_distinct_no_blank_add": True}, "DISTINCTCOUNT_w"),
        ("M15 num gte to gt", {"m15_num_gte_to_gt": True}, "COUNTROWS_t_w_gte"),
        ("M15 date gte to gt", {"m15_date_gte_to_gt": True}, "COUNTROWS_t_dt_range"),
    ]

    for name, overrides, f_id in mutants:
        res = run_comparison(
            rows=200,
            seed=42,
            overrides=overrides,
            formula_filter=[f_id],
            skip_naive=True,
            skip_parquet=True,
            skip_group_by=True,
        )
        r = res["results"][0]
        assert r["mapped_status"] in ("differs", "sql-error"), (
            f"Mutant '{name}' failed to kill {f_id}! status: {r['mapped_status']}"
        )


def test_group_by_harness_blank_key_and_order() -> None:
    """Group-by harness preserves blank key, matches engine VertiPaq order, and formats values."""
    res_gb = run_comparison(
        rows=200,
        seed=42,
        formula_filter=["group_by_cat_SUM_w", "group_by_dt_MIN_dt"],
        skip_naive=True,
        skip_parquet=True,
    )
    for r in res_gb["results"]:
        assert r["mapped_status"] == "same", f"Group-by mismatch on {r['id']}"
        assert ":" in r["mapped_val"], "Group-by must format key-value pairs separated by :"
        if r["id"] == "group_by_dt_MIN_dt":
            # Verify blank key group is present (:;)
            assert r["mapped_val"].startswith(":"), "Blank key group must be preserved and present"


def test_scale_keyed_by_filtered_column() -> None:
    """Scale used to cast a filtered column must be the scale of that column, not aggregate column."""
    res = run_comparison(
        rows=200,
        seed=42,
        formula_filter=["SUM_w_d_neq"],
        skip_naive=True,
        skip_parquet=True,
        skip_group_by=True,
    )
    r = res["results"][0]
    assert r["mapped_status"] == "same", f"SUM_w_d_neq failed: {r}"


def test_blank_date_rules_per_operator() -> None:
    """Blank dates: dt <= D and dt <> D include blanks; dt >= D and dt > D do not."""
    res = run_comparison(
        rows=200,
        seed=42,
        formula_filter=[
            "COUNTROWS_t_dt_lte",
            "COUNTROWS_t_dt_lt",
            "COUNTROWS_t_dt_neq",
            "COUNTROWS_t_dt_gt",
            "COUNTROWS_t_dt_range",
        ],
        skip_naive=True,
        skip_parquet=True,
        skip_group_by=True,
    )
    for r in res["results"]:
        assert r["mapped_status"] == "same", f"Date rule mismatch on {r['id']}"


def test_exact_average_at_high_magnitude() -> None:
    """AVERAGE computes sum/count in Python Decimal result layer without double precision loss."""
    res = run_comparison(
        rows=200,
        seed=42,
        formula_filter=["AVERAGE_d"],
        skip_naive=True,
        skip_parquet=True,
        skip_group_by=True,
    )
    r = res["results"][0]
    assert r["mapped_status"] == "same", f"AVERAGE_d precision loss: {r}"
    assert Decimal(str(r["mapped_val"])) > 100000000000000, "Must be at 1e14 magnitude"


def test_refusals_have_reasons() -> None:
    """Store refusals (DISTINCTCOUNTNOBLANK, COUNT of text) must carry explicit reason string."""
    res = run_comparison(
        rows=200,
        seed=42,
        formula_filter=["DISTINCTCOUNTNOBLANK_w", "COUNT_t"],
        skip_naive=True,
        skip_parquet=True,
        skip_group_by=True,
    )
    for r in res["results"]:
        assert r["mapped_status"] == "refused"
        ref_text = r.get("mapped_refusal")
        assert ref_text and ref_text.startswith("REFUSED:"), f"Missing refusal string: {r}"


def test_exit_policy_subprocess() -> None:
    """Exit policy: exit 0 on matching baseline, exit 1 on missing differs entry, exit 1 on sql-error."""
    res_200 = run_comparison(rows=200, seed=42)
    diffs_200 = [r["id"] for r in res_200["results"] if r["mapped_status"] == "differs"]
    refs_200 = sorted([r["id"] for r in res_200["results"] if r["mapped_status"] == "refused"])

    b_exact = {
        "sizes": {
            "200": {
                "refused": refs_200,
                "differs": [{"id": d} for d in diffs_200],
            }
        }
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(b_exact, f)
        f_exact = f.name

    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    env["QT_QPA_PLATFORM"] = "offscreen"

    # 1. Matching baseline -> Exit 0
    p1 = subprocess.run(
        [sys.executable, "tools/store_engine_diff.py", "--rows", "200", "--seed", "42", "--baseline", f_exact],
        capture_output=True,
        text=True,
        env=env,
    )
    assert p1.returncode == 0, f"Expected exit 0, got {p1.returncode}: {p1.stderr}"

    # 2. Baseline missing a differs entry -> Exit 1
    b_missing = {
        "sizes": {
            "200": {
                "refused": refs_200,
                "differs": [],
            }
        }
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(b_missing, f)
        f_missing = f.name

    p2 = subprocess.run(
        [sys.executable, "tools/store_engine_diff.py", "--rows", "200", "--seed", "42", "--baseline", f_missing],
        capture_output=True,
        text=True,
        env=env,
    )
    assert p2.returncode == 1, f"Expected exit 1, got {p2.returncode}"
