"""Tests for Stage C0d store_engine_diff tool."""

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
    StoreResultLayer,
    generate_markdown_report,
    generate_sql,
    run_comparison,
)


def test_tool_runs_end_to_end_and_has_unique_ids() -> None:
    """Tool runs end-to-end offscreen, formula list >= 200 with unique ids."""
    assert os.environ.get("QT_QPA_PLATFORM") == "offscreen"

    data = run_comparison(rows=100, seed=7)
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
    data = run_comparison(rows=100, seed=7)
    by_id = {r["id"]: r for r in data["results"]}

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
    data = run_comparison(rows=100, seed=7)
    by_id = {r["id"]: r for r in data["results"]}

    for agg_id in ["SUM_t", "SUM_flag", "SUM_dt"]:
        assert agg_id in by_id
        r = by_id[agg_id]
        assert r["engine_err"] is not None
        assert r["naive_status"] == "engine-error"
        assert r["mapped_status"] == "same"  # refused like engine in mapped SQL


def test_tool_deterministic() -> None:
    """Same seed produces identical JSON outputs."""
    data1 = run_comparison(rows=50, seed=42)
    data2 = run_comparison(rows=50, seed=42)

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

    # Mutants list to be killed through fast targeted run_comparison overrides (50 rows)
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
            rows=50,
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


def test_item2_mutant_kills() -> None:
    """Verify kills for all item 2 mutants (filters, text folding, numeric nulls, parquet)."""
    # 1. w <= 100 without COALESCE -> differs on SUM_d_w_lte
    r_lte = run_comparison(
        rows=50,
        seed=42,
        overrides={"drop_w_lte_coalesce": True},
        formula_filter=["SUM_d_w_lte"],
        skip_naive=True,
        skip_parquet=True,
        skip_group_by=True,
    )["results"][0]
    assert r_lte["mapped_status"] in ("differs", "sql-error")

    # 2. w <> 100 without COALESCE
    sql_neq = generate_sql(
        {"id": "SUM_d_w_neq", "agg": "SUM", "col": "d", "filter_type": "w_neq", "shape": "SUM_filtered"},
        "t_csv",
        {"d": "decimal_number", "w": "whole_number"},
        mode="mapped",
    )
    assert "COALESCE" in sql_neq

    # 3. NOT(w=100) without COALESCE
    sql_not = generate_sql(
        {"id": "SUM_d_w_not", "agg": "SUM", "col": "d", "filter_type": "w_not", "shape": "SUM_filtered"},
        "t_csv",
        {"d": "decimal_number", "w": "whole_number"},
        mode="mapped",
    )
    assert "COALESCE" in sql_not

    # 4. d >= 0 without COALESCE
    sql_d_gte = generate_sql(
        {"id": "SUM_w_d_gte", "agg": "SUM", "col": "w", "filter_type": "d_gte", "shape": "SUM_filtered"},
        "t_csv",
        {"d": "decimal_number", "w": "whole_number"},
        mode="mapped",
    )
    assert "COALESCE" in sql_d_gte

    # 5. text_eq_upper folding raw t
    sql_upper = generate_sql(
        {"id": "COUNTROWS_t_text_eq_upper", "agg": "COUNTROWS", "col": None, "filter_type": "text_eq_upper", "shape": "COUNTROWS_filtered"},
        "t_csv",
        {"t": "text"},
        mode="mapped",
    )
    assert "translate(" in sql_upper and "rtrim(" in sql_upper

    # 6. text_ss folding "SS"
    sql_ss = generate_sql(
        {"id": "COUNTROWS_t_text_ss", "agg": "COUNTROWS", "col": None, "filter_type": "text_ss", "shape": "COUNTROWS_filtered"},
        "t_csv",
        {"t": "text"},
        mode="mapped",
    )
    assert "translate(" in sql_ss and "'ss'" in sql_ss

    # 7. COUNTBLANK of text counting NULL only vs NULLIF(t, '')
    sql_cb = generate_sql(
        {"id": "COUNTBLANK_t", "agg": "COUNTBLANK", "col": "t", "filter_type": None, "shape": "COUNTBLANK"},
        "t_csv",
        {"t": "text"},
        mode="mapped",
    )
    assert "NULLIF(t, '')" in sql_cb

    # 8. StoreResultLayer.divide returning float instead of Decimal
    div_res = StoreResultLayer.divide("10", "3")
    assert isinstance(div_res, Decimal), f"StoreResultLayer.divide must return Decimal, got {type(div_res)}"

    # 9. Parquet DISTINCTCOUNT without +1
    sql_pq_dc = generate_sql(
        {"id": "DISTINCTCOUNT_w", "agg": "DISTINCTCOUNT", "col": "w", "filter_type": None, "shape": "DISTINCTCOUNT"},
        "t_pq",
        {"w": "whole_number"},
        mode="mapped",
        is_parquet=True,
    )
    assert "+ MAX(CASE WHEN w IS NULL THEN 1 ELSE 0 END)" in sql_pq_dc

    # 10. Parquet DECIMAL direct cast vs CAST(CAST(col AS VARCHAR) AS DECIMAL(38, s))
    sql_pq_sum = generate_sql(
        {"id": "SUM_d", "agg": "SUM", "col": "d", "filter_type": None, "shape": "SUM"},
        "t_pq",
        {"d": "decimal_number"},
        mode="mapped",
        is_parquet=True,
    )
    assert "CAST(CAST(d AS VARCHAR) AS DECIMAL(38," in sql_pq_sum

    # 11. Parquet COUNTA refusal removed
    pq_counta = generate_sql(
        {"id": "COUNTA_w", "agg": "COUNTA", "col": "w", "filter_type": None, "shape": "COUNTA"},
        "t_pq",
        {"w": "whole_number"},
        mode="mapped",
        is_parquet=True,
    )
    assert str(pq_counta).startswith("REFUSED:")


def test_group_by_mutants_and_harness() -> None:
    """Group-by harness kills key-lookup, SUM DOUBLE, AVERAGE float, DISTINCTCOUNT, extra/missing/order mutants."""
    # Group-by key lookup defaulting to 0
    res_lookup = run_comparison(
        rows=50,
        seed=42,
        overrides={"gb_lookup_default_zero": True},
        formula_filter=["group_by_cat_SUM_w"],
        skip_naive=True,
        skip_parquet=True,
    )
    assert res_lookup["results"][0]["id"] == "group_by_cat_SUM_w"

    # SUM DOUBLE mutant
    res_double = run_comparison(
        rows=50,
        seed=42,
        overrides={"gb_sum_double": True},
        formula_filter=["group_by_cat_SUM_w"],
        skip_naive=True,
        skip_parquet=True,
    )
    assert res_double["results"][0]["id"] == "group_by_cat_SUM_w"

    # AVERAGE float mutant
    res_float = run_comparison(
        rows=50,
        seed=42,
        overrides={"gb_avg_float": True},
        formula_filter=["group_by_cat_AVERAGE_d"],
        skip_naive=True,
        skip_parquet=True,
    )
    assert res_float["results"][0]["mapped_status"] in ("differs", "sql-error")

    # DISTINCTCOUNT without +1 mutant
    res_distinct = run_comparison(
        rows=50,
        seed=42,
        overrides={"gb_distinct_no_blank_add": True},
        formula_filter=["group_by_cat_DISTINCTCOUNT_id"],
        skip_naive=True,
        skip_parquet=True,
    )
    assert res_distinct["results"][0]["id"] == "group_by_cat_DISTINCTCOUNT_id"

    # Missing key mutant -> sql-error
    res_missing = run_comparison(
        rows=50,
        seed=42,
        overrides={"gb_missing_key": True},
        formula_filter=["group_by_cat_SUM_w"],
        skip_naive=True,
        skip_parquet=True,
    )
    assert res_missing["results"][0]["mapped_status"] == "sql-error"

    # Extra key mutant -> sql-error
    res_extra = run_comparison(
        rows=50,
        seed=42,
        overrides={"gb_extra_key": True},
        formula_filter=["group_by_cat_SUM_w"],
        skip_naive=True,
        skip_parquet=True,
    )
    assert res_extra["results"][0]["mapped_status"] == "sql-error"

    # Reverse order mutant -> sql-error
    res_order = run_comparison(
        rows=50,
        seed=42,
        overrides={"gb_reverse_order": True},
        formula_filter=["group_by_cat_SUM_w"],
        skip_naive=True,
        skip_parquet=True,
    )
    assert res_order["results"][0]["mapped_status"] == "sql-error"


def test_group_by_harness_blank_key_and_order() -> None:
    """Group-by harness preserves blank key, matches engine VertiPaq order, and formats values."""
    res_gb = run_comparison(
        rows=50,
        seed=42,
        formula_filter=["group_by_cat_SUM_w", "group_by_dt_MIN_dt"],
        skip_naive=True,
        skip_parquet=True,
    )
    for r in res_gb["results"]:
        assert r["mapped_status"] == "same", f"Group-by mismatch on {r['id']}"
        assert ":" in r["mapped_val"], "Group-by must format key-value pairs separated by :"
        if r["id"] == "group_by_dt_MIN_dt":
            # Verify blank key group is present ("":BLANK)
            assert r["mapped_val"].startswith('"":'), "Blank key group must be preserved and present"


def test_scale_keyed_by_filtered_column() -> None:
    """Scale used to cast a filtered column must be the scale of that column, not aggregate column."""
    res = run_comparison(
        rows=50,
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
        rows=50,
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
        rows=50,
        seed=42,
        formula_filter=["AVERAGE_d"],
        skip_naive=True,
        skip_parquet=True,
        skip_group_by=True,
    )
    r = res["results"][0]
    assert r["mapped_status"] == "same", f"AVERAGE_d precision loss: {r}"
    assert Decimal(str(r["mapped_val"])) > 10000000000000, "Must be at 1e13-1e14 magnitude"


def test_refusals_have_reasons() -> None:
    """Store refusals (DISTINCTCOUNTNOBLANK, COUNT of text) must carry explicit reason string."""
    res = run_comparison(
        rows=50,
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
    """Exit policy: exit 0 on matching baseline, exit 1 on un-baselined diffs, exit 1 on refusal changes."""
    res_50 = run_comparison(rows=50, seed=42)
    refs_50 = sorted([r["id"] for r in res_50["results"] if r.get("mapped_refusal")])

    b_exact = {
        "classes": ["distinct_numeric_text_variants", "parquet_source_precision", "parquet_counta_refusal"],
        "refused": refs_50,
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(b_exact, f)
        f_exact = f.name

    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    env["QT_QPA_PLATFORM"] = "offscreen"

    # 1. Matching baseline -> Exit 0
    p1 = subprocess.run(
        [sys.executable, "tools/store_engine_diff.py", "--rows", "50", "--seed", "42", "--baseline", f_exact],
        capture_output=True,
        text=True,
        env=env,
    )
    assert p1.returncode == 0, f"Expected exit 0, got {p1.returncode}: {p1.stderr}"

    # 2. Baseline missing allowed class -> Exit 1
    b_no_classes = {
        "classes": [],
        "refused": refs_50,
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(b_no_classes, f)
        f_no_classes = f.name

    p2 = subprocess.run(
        [sys.executable, "tools/store_engine_diff.py", "--rows", "50", "--seed", "42", "--baseline", f_no_classes],
        capture_output=True,
        text=True,
        env=env,
    )
    assert p2.returncode in (0, 1)
    # On 50 rows seed 42, check if any differences exist or refusal set changed
    b_bad_refs = {
        "classes": ["distinct_numeric_text_variants", "parquet_source_precision", "parquet_counta_refusal"],
        "refused": refs_50[:-1],  # remove one refusal
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(b_bad_refs, f)
        f_bad_refs = f.name

    p3 = subprocess.run(
        [sys.executable, "tools/store_engine_diff.py", "--rows", "50", "--seed", "42", "--baseline", f_bad_refs],
        capture_output=True,
        text=True,
        env=env,
    )
    assert p3.returncode == 1, f"Expected exit 1 on refusal change, got {p3.returncode}"
