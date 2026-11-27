"""Engine versus DuckStore comparison and rules generator.

Stage C0c tool comparing DAX evaluation on the native engine against naive and
mapped SQL evaluation on DuckStore (CSV and Parquet paths).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import random
import sys
import tempfile
import time
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from analytics_studio import dax_dates
from analytics_studio.controller import StudioController, _format_report_number
from analytics_studio.file_import import parse_file
from analytics_studio.measures import evaluate_measures, normalize_measure
from analytics_studio.store import DuckStore, import_csv_to_store, import_parquet_to_store
from analytics_studio.store.base import StoreError
from analytics_studio.store.dax_sql import (
    PARQUET_COUNTA_REFUSAL_REASON,
    ColumnMeta,
    Refusal,
    StoreResultLayer,
    build_where_clause,
    column_decimal_meta,
    generate_mapped_sql,
    make_fold_expr,
    plan_group_by,
    plan_measure,
    refusal_matches_engine_error,
)
from analytics_studio.store.dax_whitelist import classify_filter_context, classify_measure
from analytics_studio.store.text_rules import first_spelling_expr_sql, fold_sql

# Names that moved to analytics_studio/store/dax_sql.py and stay importable from this tool
__all__ = [
    "PARQUET_COUNTA_REFUSAL_REASON",
    "Refusal",
    "StoreResultLayer",
    "build_where_clause",
    "make_fold_expr",
    "refusal_matches_engine_error",
]

# Exact numeric comparison: Decimal and int engine values (SUM, AVERAGE, counts) must match exactly (tolerance 0).
# Only a float-valued engine shape (ratio, arithmetic combos) gets a relative tolerance of 1e-15 of max(|a|, |b|).
FLOAT_REL_TOLERANCE = Decimal("1e-15")


def to_exact_decimal(val: Any) -> Decimal | None:
    """Convert a numeric scalar value to Decimal for exact comparison.

    Returns None for non-numeric values, booleans, dates, and empty/NaN markers.
    """
    if val is None or val is False or val is True:
        return None
    if isinstance(val, (dt.date, dt.datetime)):
        return None
    if dax_dates.is_date(val):
        return None
    if isinstance(val, (int, Decimal)):
        return Decimal(val)
    if isinstance(val, float):
        import math
        if math.isnan(val) or math.isinf(val):
            return None
        return Decimal(repr(val))
    if isinstance(val, str):
        if val in ("None", "BLANK", '""', "", "NaN", "nan", "Infinity", "-Infinity"):
            return None
        # String dates (e.g. "2026-06-01" or "6/1/2026") or group-by semicolon strings
        if "-" in val or "/" in val or ";" in val or ":" in val:
            return None
        try:
            return Decimal(val)
        except InvalidOperation:
            return None
    return None


def exact_values_agree(val_a: Any, val_b: Any, rel_tol: Decimal | None = None) -> bool:
    """Compare two scalar values for numeric equality; the tolerance depends on the value type of val_a.

    If either value is not a numeric scalar (or cannot be converted to Decimal), returns True
    so the formatted-text comparison handles equality.
    val_a (the engine value) of type Decimal or int: exact equality, tolerance 0.
    val_a of type float: |a - b| <= 1e-15 * max(|a|, |b|), unless rel_tol is given.
    """
    da = to_exact_decimal(val_a)
    db = to_exact_decimal(val_b)
    if da is None or db is None:
        return True
    if da == db:
        return True
    if rel_tol is None:
        rel_tol = FLOAT_REL_TOLERANCE if isinstance(val_a, float) else Decimal(0)
    if rel_tol == 0:
        return False
    diff = abs(da - db)
    max_val = max(abs(da), abs(db))
    if max_val == 0:
        return diff == 0
    return (diff / max_val) <= rel_tol


def group_values_agree(pairs_a: list[tuple[str, Any]] | None, pairs_b: list[tuple[str, Any]] | None) -> bool:
    """Compare group-by results per group key on exact values (the 2-decimal text comparison is done elsewhere).

    Keys present on one side only are left to the text comparison. The tolerance rule is the one of exact_values_agree.
    """
    if not pairs_a or not pairs_b:
        return True
    dict_b = dict(pairs_b)
    for key, val_a in pairs_a:
        if key in dict_b and not exact_values_agree(val_a, dict_b[key]):
            return False
    return True


# TRIM_CHARS_SQL (the 33 characters U+0000..U+0020) and the fold SQL come from analytics_studio.store.text_rules


def format_report_value(val: Any) -> str:
    """Format value for reporting (1:1 app representation using _format_report_number)."""
    if val is None:
        return "BLANK"
    if val == "":
        return '""'
    if isinstance(val, Refusal):
        return str(val)
    if isinstance(val, (dt.date, dt.datetime)) and not dax_dates.is_date(val):
        d_val = dt.date(val.year, val.month, val.day) if isinstance(val, dt.datetime) else val
        val = dax_dates.from_datetime(dt.datetime.combine(d_val, dt.time.min))
    if dax_dates.is_date(val):
        return _format_report_number(val)
    if isinstance(val, bool):
        return "True" if val else "False"
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float, Decimal)):
        return _format_report_number(Decimal(str(val)))
    return _format_report_number(val)


# ==============================================================================
# SECTION: DATASET GENERATOR
# ==============================================================================

def generate_dataset(
    csv_path: Path,
    parquet_path: Path,
    rows: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    """Generate seeded dataset with mixed types, blanks, edge values, duplicates, and collisions."""
    rnd = random.Random(seed)

    text_options = [
        "East",
        "east",
        "EAST",
        "West",
        "west ",
        "West\t",
        "North",
        "",
        "Ünï",
        "ünï",
        "ß",
        "SS",
        "a b",
        "A B ",
        "x",
        "x\x01",
        "X\x1f",
        "x\t",
        "x\x0b",
        "y",
    ]
    categories = ["A", "B", "C", "D", "E"]
    decimal_choices = [
        "0.1",
        "0.2",
        "0.3",
        "-2.25",
        "1234.5678",
        "-0.50",
        "3.0",
        "0.00005",
        "0.000000001",
        "123456789012345.6789",
        "1000000000000000.0",
        "1.2345678",
        "-0.87654321",
    ]
    big_choices = [
        "123456789012345678901",
        "987654321098765432109876",
        "100000000000000000000",
        "5555555555555555555555",
        "1",
        "1.0",
        "1.00",
        "+1",
    ]
    num_dups_choices = ["1", "1.0", "1.00", "+1", "-0", "0", "2", "2.5", "2.50"]

    csv_rows: list[list[str]] = []
    headers = ["id", "w", "d", "big", "t", "dt", "flag", "cat", "w_blank", "num_dups"]

    pq_id: list[str] = []
    pq_w: list[int | None] = []
    pq_d: list[float | None] = []
    pq_big: list[str] = []
    pq_t: list[str | None] = []
    pq_dt: list[dt.date | None] = []
    pq_flag: list[bool | None] = []
    pq_cat: list[str] = []
    pq_w_blank: list[str | None] = []
    pq_num_dups: list[float | None] = []

    for i in range(1, rows + 1):
        id_str = str(i)

        # Ensure boundary values exist deterministically across any row count:
        # row 1: w=100, dt=2026-06-01 (kills M15 >= vs > on numbers & dates)
        # row 2: w=200, dt=2026-06-02
        # rows 3..16: 15-digit large whole numbers (sum > 2^53, kills M4 whole SUM->DOUBLE)
        if i == 1:
            w_str, w_val = "100", 100
        elif i == 2:
            w_str, w_val = "200", 200
        elif 3 <= i <= 16:
            w_num = 900719925474099 + (i % 100)
            w_str = str(w_num)
            w_val = w_num
        elif rnd.random() < 0.10:
            w_str = ""
            w_val = None
        elif rnd.random() < 0.05:
            # 15 digits (< 16 so inferred as whole_number), sum easily exceeds 2^53 to kill M4
            w_num = 900719925474099 + (i % 100)
            w_str = str(w_num)
            w_val = w_num
        elif rnd.random() < 0.05:
            w_str = "-0"
            w_val = 0
        else:
            w_num = rnd.randint(-100, 1000)
            w_str = str(w_num)
            w_val = w_num

        # d: decimal with seed-dependent blanks, high precision, large values
        if rnd.random() < 0.10:
            d_str = ""
            d_val = None
        else:
            d_choice = decimal_choices[rnd.randint(0, len(decimal_choices) - 1)]
            d_str = d_choice
            d_val = float(d_choice)

        # big: text-typed digits
        if rnd.random() < 0.08:
            big_str = ""
        else:
            big_str = big_choices[rnd.randint(0, len(big_choices) - 1)]

        # t: mixed case, trailing spaces, control characters, non-ASCII
        if rnd.random() < 0.08:
            t_str = ""
            t_val = None
        else:
            t_choice = text_options[rnd.randint(0, len(text_options) - 1)]
            t_str = t_choice
            t_val = t_choice

        # dt: dates with seed-dependent blanks
        if i == 1:
            dt_val = dt.date(2026, 6, 1)
            dt_str = "2026-06-01"
        elif i == 2:
            dt_val = dt.date(2026, 6, 2)
            dt_str = "2026-06-02"
        elif rnd.random() < 0.10:
            dt_str = ""
            dt_val = None
        else:
            day = 1 + (rnd.randint(0, 27))
            month = 1 + (rnd.randint(0, 11))
            year = 2026
            dt_val = dt.date(year, month, day)
            dt_str = dt_val.isoformat()

        # flag: boolean with seed-dependent blanks
        if rnd.random() < 0.10:
            flag_str = ""
            flag_val = None
        elif rnd.random() < 0.50:
            flag_str = "TRUE"
            flag_val = True
        else:
            flag_str = "FALSE"
            flag_val = False

        # cat: category
        cat_str = categories[rnd.randint(0, len(categories) - 1)]

        # w_blank: all-blank column (infers as text)
        w_blank_str = ""
        w_blank_val = None

        # num_dups: numeric-typed column containing textual duplicate representations ('1', '1.0', '+1', etc.)
        num_dup_str = num_dups_choices[rnd.randint(0, len(num_dups_choices) - 1)]
        num_dup_val = float(num_dup_str)

        csv_rows.append([id_str, w_str, d_str, big_str, t_str, dt_str, flag_str, cat_str, w_blank_str, num_dup_str])

        pq_id.append(id_str)
        pq_w.append(w_val)
        pq_d.append(d_val)
        pq_big.append(big_str)
        pq_t.append(t_val)
        pq_dt.append(dt_val)
        pq_flag.append(flag_val)
        pq_cat.append(cat_str)
        pq_w_blank.append(w_blank_val)
        pq_num_dups.append(num_dup_val)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(csv_rows)

    pq_table = pa.table(
        {
            "id": pa.array(pq_id, pa.string()),
            "w": pa.array(pq_w, pa.int64()),
            "d": pa.array(pq_d, pa.float64()),
            "big": pa.array(pq_big, pa.string()),
            "t": pa.array(pq_t, pa.string()),
            "dt": pa.array(pq_dt, pa.date32()),
            "flag": pa.array(pq_flag, pa.bool_()),
            "cat": pa.array(pq_cat, pa.string()),
            "w_blank": pa.array(pq_w_blank, pa.string()),
            "num_dups": pa.array(pq_num_dups, pa.float64()),
        }
    )
    pq.write_table(pq_table, parquet_path)

    return {"headers": headers, "row_count": rows}


# ==============================================================================
# SECTION: FORMULA CATALOG
# ==============================================================================

def build_formula_catalog(headers: list[str]) -> list[dict[str, Any]]:
    """Generate deterministic formulas spanning aggregates, filters, arithmetic, and group-by."""
    catalog: list[dict[str, Any]] = []

    # 1. Base Aggregates across all columns
    aggs = [
        "SUM",
        "AVERAGE",
        "MIN",
        "MAX",
        "COUNT",
        "COUNTA",
        "COUNTROWS",
        "COUNTBLANK",
        "DISTINCTCOUNT",
        "DISTINCTCOUNTNOBLANK",
    ]

    for agg in aggs:
        if agg == "COUNTROWS":
            catalog.append({
                "id": f"{agg}_t",
                "category": "aggregate",
                "shape": agg,
                "dax": "COUNTROWS(t)",
                "agg": agg,
                "col": None,
                "filter_type": None,
            })
            continue

        for col in headers:
            catalog.append({
                "id": f"{agg}_{col}",
                "category": "aggregate",
                "shape": agg,
                "dax": f"{agg}(t[{col}])",
                "agg": agg,
                "col": col,
                "filter_type": None,
            })

    # 2. Filter variations
    filter_aggs = ["SUM", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA", "COUNTROWS", "COUNTBLANK", "DISTINCTCOUNT"]
    filter_cols = ["w", "d", "t"]

    filter_defs = [
        ("cat_eq", 't[cat] = "A"', "cat_eq"),
        ("cat_eq_other", 't[cat] = "B"', "cat_eq"),
        ("text_eq_lower", 't[t] = "east"', "text_fold"),
        ("text_eq_upper", 't[t] = "EAST"', "text_fold"),
        ("text_eq_space", 't[t] = "west "', "text_fold"),
        ("text_eq_tab", 't[t] = "west\t"', "text_fold"),
        ("text_eq_untrimmed", 't[t] = "west"', "text_fold"),
        ("text_uni_upper", 't[t] = "Ünï"', "text_ascii_only"),
        ("text_uni_lower", 't[t] = "ünï"', "text_ascii_only"),
        ("text_sharp_s", 't[t] = "ß"', "text_ascii_only"),
        ("text_ss", 't[t] = "SS"', "text_ascii_only"),
        ("w_zero", "t[w] = 0", "numeric_zero"),
        ("w_lt", "t[w] < 100", "numeric_lt"),
        ("w_lte", "t[w] <= 100", "numeric_lte"),
        ("w_gt", "t[w] > 100", "numeric_gt"),
        ("w_gte", "t[w] >= 100", "numeric_gte"),
        ("w_neq", "t[w] <> 100", "numeric_neq"),
        ("w_not", "NOT(t[w] = 100)", "numeric_not"),
        ("w_or", "t[w] = 100 || t[w] = 200", "numeric_or"),
        ("w_in", "t[w] IN {100, 200}", "numeric_in"),
        ("d_gte", "t[d] >= 0", "decimal_filter"),
        ("d_lt", "t[d] < 0", "decimal_filter"),
        ("d_neq", "t[d] <> 0", "decimal_filter"),
        ("dt_range", "t[dt] >= DATE(2026, 6, 1)", "date_range"),
        ("dt_gt", "t[dt] > DATE(2026, 6, 1)", "date_gt"),
        ("dt_lte", "t[dt] <= DATE(2026, 6, 1)", "date_lte"),
        ("dt_lt", "t[dt] < DATE(2026, 6, 1)", "date_lt"),
        ("dt_neq", "t[dt] <> DATE(2026, 6, 1)", "date_neq"),
        ("dt_in", "t[dt] IN {DATE(2026, 6, 1), DATE(2026, 7, 1)}", "date_in"),
        ("cat_in", 't[cat] IN {"A", "B"}', "is_any_of"),
        ("empty_set", 't[id] = "-999"', "empty_set"),
    ]

    for f_id, f_expr, f_cat in filter_defs:
        for agg in filter_aggs:
            target_cols = [None] if agg == "COUNTROWS" else filter_cols
            for col in target_cols:
                if agg in ("SUM", "AVERAGE") and col == "t":
                    continue
                expr = "COUNTROWS(t)" if col is None else f"{agg}(t[{col}])"
                dax = f"CALCULATE({expr}, {f_expr})"
                c_id = f"{agg}_{col or 't'}_{f_id}"
                catalog.append({
                    "id": c_id,
                    "category": f"filter_{f_cat}",
                    "shape": f"{agg}_filtered",
                    "dax": dax,
                    "agg": agg,
                    "col": col,
                    "filter_type": f_id,
                })

    # 3. Two filters in one CALCULATE & multiple columns
    catalog.append({
        "id": "COUNTROWS_t_two_filters",
        "category": "multi_filter",
        "shape": "COUNTROWS_filtered",
        "dax": "CALCULATE(COUNTROWS(t), t[w] > 5, t[w] < 15)",
        "agg": "COUNTROWS",
        "col": None,
        "filter_type": "two_filters_w",
    })
    catalog.append({
        "id": "COUNTROWS_t_filter_two_cols",
        "category": "multi_filter",
        "shape": "COUNTROWS_filtered",
        "dax": 'CALCULATE(COUNTROWS(t), t[w] > 5 && t[cat] = "A")',
        "agg": "COUNTROWS",
        "col": None,
        "filter_type": "filter_two_cols",
    })
    catalog.append({
        "id": "AVERAGE_w_all_blank_filter",
        "category": "empty_calc",
        "shape": "AVERAGE_filtered",
        "dax": "CALCULATE(AVERAGE(t[w]), t[w] = 999999)",
        "agg": "AVERAGE",
        "col": "w",
        "filter_type": "all_blank_filter",
    })

    # 4. Arithmetic combos and iterators
    arith_defs = [
        ("arith_sum_w_plus", "SUM(t[w]) + 0.1", "SUM", "w", "plus_scalar"),
        ("arith_sum_d_div_count", "SUM(t[d]) / COUNT(t[d])", "RATIO", "d", "ratio"),
        ("arith_divide_zero", "DIVIDE(SUM(t[w]), 0)", "DIVIDE", "w", "divide_zero"),
        ("arith_sum_d_plus_sum_w", "SUM(t[w]) + SUM(t[d])", "SUM", "w_d", "combo_sum"),
        ("arith_avg_minus_min", "AVERAGE(t[w]) - MIN(t[w])", "ARITH", "w", "combo_sub"),
        ("arith_sumx_divide_zero", "SUMX(t, DIVIDE(t[w], 0))", "SUMX", "w", "sumx_divide_zero"),
        ("arith_sumx_slash_zero", "SUMX(t, t[w] / 0)", "SUMX", "w", "sumx_slash_zero"),
    ]
    for a_id, a_dax, a_shape, a_col, a_type in arith_defs:
        catalog.append({
            "id": a_id,
            "category": "arithmetic",
            "shape": a_shape,
            "dax": a_dax,
            "agg": "ARITH",
            "col": a_col,
            "filter_type": a_type,
        })

    # 5. Group-by comparisons across cat, t, dt, flag
    for g_col in ["cat", "t", "dt", "flag"]:
        for agg, target in [
            ("SUM", "w"),
            ("SUM", "d"),
            ("COUNTROWS", None),
            ("DISTINCTCOUNT", "id"),
            ("DISTINCTCOUNT", "flag"),
            ("AVERAGE", "d"),
            ("MIN", "dt"),
        ]:
            c_id = f"group_by_{g_col}_{agg}_{target or 'all'}"
            catalog.append({
                "id": c_id,
                "category": "group_by",
                "shape": f"group_by_{agg}",
                "dax": f"group_by({g_col}, {agg}, {target})",
                "agg": agg,
                "col": target,
                "group_col": g_col,
                "filter_type": "group_by",
            })

    # Test formula for forced wrong value mutant testing
    catalog.append({
        "id": "forced_wrong_formula",
        "category": "test",
        "shape": "SUM",
        "dax": "SUM(t[w])",
        "agg": "SUM",
        "col": "w",
        "filter_type": None,
    })

    return catalog


# ==============================================================================
# SECTION: SQL GENERATOR & REFUSAL LOGIC
# ==============================================================================

def generate_sql(
    formula: dict[str, Any],
    table_name: str,
    column_types: dict[str, str],
    mode: str = "naive",
    is_parquet: bool = False,
    store_meta: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
) -> str | Refusal | None:
    """Generate SQL query or explicit Refusal for naive or mapped mode (the mapped part lives in dax_sql)."""
    if mode != "naive":
        return generate_mapped_sql(
            formula, table_name, column_types, is_parquet=is_parquet, store_meta=store_meta, overrides=overrides
        )
    overrides = overrides or {}
    t_q = f'"{table_name}"'
    agg = formula["agg"]
    col = formula.get("col")
    f_type = formula.get("filter_type")
    group_col = formula.get("group_col")

    # Build WHERE clause (same function the class predicates use)
    where_clause = build_where_clause(f_type, mode, is_parquet, store_meta, overrides, agg)

    # F5 / Work item G: Group-by shapes
    if group_col:
        # Group-by evaluation delegates to run_comparison for mapped mode
        return None

    # Arithmetic combos
    if f_type in ("plus_scalar", "ratio", "divide_zero", "combo_sum", "combo_sub", "sumx_divide_zero", "sumx_slash_zero"):
        if f_type == "plus_scalar":
            return f"SELECT SUM(TRY_CAST(w AS DOUBLE)) + 0.1 FROM {t_q}"
        if f_type == "ratio":
            return f"SELECT SUM(TRY_CAST(d AS DOUBLE)) / COUNT(d) FROM {t_q}"
        if f_type == "divide_zero":
            return f"SELECT SUM(TRY_CAST(w AS DOUBLE)) / 0 FROM {t_q}"
        if f_type == "sumx_divide_zero":
            return f"SELECT SUM(TRY_CAST(w AS DOUBLE) / 0) FROM {t_q}"
        if f_type == "sumx_slash_zero":
            return f"SELECT SUM(TRY_CAST(w AS DOUBLE) / 0) FROM {t_q}"
        if f_type == "combo_sum":
            return f"SELECT SUM(TRY_CAST(w AS DOUBLE)) + SUM(TRY_CAST(d AS DOUBLE)) FROM {t_q}"
        if f_type == "combo_sub":
            return f"SELECT AVG(TRY_CAST(w AS DOUBLE)) - MIN(TRY_CAST(w AS DOUBLE)) FROM {t_q}"

    # Naive mode
    if agg == "COUNTROWS":
        return f"SELECT COUNT(*) FROM {t_q} {where_clause}"
    if agg == "SUM":
        return f"SELECT SUM(TRY_CAST({col} AS DOUBLE)) FROM {t_q} {where_clause}"
    if agg == "AVERAGE":
        return f"SELECT AVG(TRY_CAST({col} AS DOUBLE)) FROM {t_q} {where_clause}"
    if agg == "MIN":
        return f"SELECT MIN({col}) FROM {t_q} {where_clause}"
    if agg == "MAX":
        return f"SELECT MAX({col}) FROM {t_q} {where_clause}"
    if agg == "COUNT":
        return f"SELECT COUNT({col}) FROM {t_q} {where_clause}"
    if agg == "COUNTA":
        return f"SELECT COUNT({col}) FROM {t_q} {where_clause}"
    if agg == "COUNTBLANK":
        return f"SELECT COUNT(*) - COUNT({col}) FROM {t_q} {where_clause}"
    if agg == "DISTINCTCOUNT":
        return f"SELECT COUNT(DISTINCT {col}) FROM {t_q} {where_clause}"
    if agg == "DISTINCTCOUNTNOBLANK":
        return f"SELECT COUNT(DISTINCT {col}) FROM {t_q} {where_clause}"
    return None



# ==============================================================================
# SECTION: PLAN MODE (Rule A+): the planner against the engine
# ==============================================================================

PLAN_FAILURE_STATUSES = ("plan-differs", "plan-sql-error", "plan-crash")


def evaluate_plan_row(
    f_item: dict[str, Any],
    engine_val: Any,
    engine_err: str | None,
    store: DuckStore,
    tables: dict[str, dict[str, str]],
    plan_meta: dict[tuple[str, str], ColumnMeta],
    overrides: dict[str, Any],
    engine_kv_exact: list[tuple[str, Any]] | None = None,
) -> dict[str, Any]:
    """Plan one catalog formula and compare it with the engine (Rule A+). Returns the plan_* result keys.

    A group-by formula goes through plan_group_by and is compared as the tool's own mapped path does: the key
    set must equal the engine's, then the key order, then every value exactly (same Python class).

    Whitelist-allowed: the plan value must equal the engine value exactly, with the same Python class and the
    same report text, else plan-differs. Whitelist-refused: plan_measure must return a Refusal, never SQL.
    """
    base: dict[str, Any] = {"plan_status": "plan-skipped", "plan_value": "None", "plan_refusal": None, "plan_allowed": False, "plan_error": None}
    if f_item.get("group_col"):
        return _evaluate_plan_group_row(f_item, engine_kv_exact, engine_err, store, tables, plan_meta, overrides, base)
    dax_expr = f_item["dax"]
    max_digits = {col: m.digits for (_, col), m in plan_meta.items()}
    try:
        decision = classify_measure(dax_expr, home_table="t", tables=tables, max_digits=max_digits)
        plan = plan_measure(
            dax_expr,
            home_table="t",
            tables=tables,
            store_tables={"t": "t_csv"},
            column_meta=plan_meta,
            overrides=overrides,
        )
    except Exception as exc:  # a planner crash is a failure, never a skip
        return {**base, "plan_status": "plan-crash", "plan_error": f"{type(exc).__name__}: {exc}"}
    base["plan_allowed"] = decision.allowed
    if isinstance(plan, Refusal):
        base["plan_refusal"] = str(plan)
        base["plan_status"] = "plan-refused" if not decision.allowed else "plan-refused-allowed"
        return base
    if not decision.allowed:
        base["plan_status"] = "plan-differs"
        base["plan_error"] = "whitelist refused but the planner returned SQL"
        return base
    try:
        plan_val = plan.execute(store)
    except StoreError as exc:
        return {**base, "plan_status": "plan-sql-error", "plan_error": str(exc)[:200]}
    except Exception as exc:
        return {**base, "plan_status": "plan-crash", "plan_error": f"{type(exc).__name__}: {exc}"}
    if isinstance(plan_val, Refusal):
        base["plan_refusal"] = str(plan_val)
        base["plan_status"] = "plan-refused-allowed"
        return base
    if overrides.get("forced_wrong_plan_value") and f_item["id"] == overrides["forced_wrong_plan_value"]:
        plan_val = Decimal("1") if plan_val is None else plan_val + Decimal("0.000001")
    base["plan_value"] = str(plan_val)
    if engine_err:
        base["plan_status"] = "plan-differs"
        base["plan_error"] = "engine raised an error but the plan returned a value"
    elif (
        type(plan_val) is type(engine_val)
        and plan_val == engine_val
        and format_report_value(plan_val) == format_report_value(engine_val)
    ):
        base["plan_status"] = "plan-same"
    else:
        base["plan_status"] = "plan-differs"
        base["plan_error"] = f"engine {format_report_value(engine_val)} ({type(engine_val).__name__}) vs plan {format_report_value(plan_val)} ({type(plan_val).__name__})"
    return base


def _evaluate_plan_group_row(
    f_item: dict[str, Any],
    engine_kv_exact: list[tuple[str, Any]] | None,
    engine_err: str | None,
    store: DuckStore,
    tables: dict[str, dict[str, str]],
    plan_meta: dict[tuple[str, str], ColumnMeta],
    overrides: dict[str, Any],
    base: dict[str, Any],
) -> dict[str, Any]:
    """plan_group_by of one catalog group-by formula against the engine's key list and per-key values."""
    agg, target, g_col = f_item["agg"], f_item.get("col"), f_item["group_col"]
    expression = "COUNTROWS(t)" if agg == "COUNTROWS" else f"{agg}(t[{target}])"
    max_digits = {col: m.digits for (_, col), m in plan_meta.items()}
    try:
        decision = classify_measure(expression, home_table="t", tables=tables, max_digits=max_digits or None)
        plan = plan_group_by(
            expression,
            group_by=("t", g_col),
            home_table="t",
            tables=tables,
            store_tables={"t": "t_csv"},
            column_meta=plan_meta,
            overrides=overrides,
        )
    except Exception as exc:
        return {**base, "plan_status": "plan-crash", "plan_error": f"{type(exc).__name__}: {exc}"}
    base["plan_allowed"] = decision.allowed
    if isinstance(plan, Refusal):
        base["plan_refusal"] = str(plan)
        base["plan_status"] = "plan-refused" if not decision.allowed else "plan-refused-allowed"
        return base
    if not decision.allowed:
        base["plan_status"] = "plan-differs"
        base["plan_error"] = "whitelist refused but the planner returned SQL"
        return base
    try:
        plan_val = plan.execute(store)
    except StoreError as exc:
        return {**base, "plan_status": "plan-sql-error", "plan_error": str(exc)[:200]}
    except Exception as exc:
        return {**base, "plan_status": "plan-crash", "plan_error": f"{type(exc).__name__}: {exc}"}
    if isinstance(plan_val, Refusal):
        base["plan_refusal"] = str(plan_val)
        base["plan_status"] = "plan-refused-allowed"
        return base
    if overrides.get("forced_wrong_plan_value") and f_item["id"] == overrides["forced_wrong_plan_value"] and plan_val:
        key0, val0 = plan_val[0]
        plan_val = [(key0, Decimal("1") if val0 is None else val0 + Decimal("0.000001")), *plan_val[1:]]
    pairs = [(format_report_value(k), v) for k, v in plan_val]
    base["plan_value"] = ";".join(f"{k}:{format_report_value(v)}" for k, v in pairs)
    if engine_err or engine_kv_exact is None:
        base["plan_status"] = "plan-differs"
        base["plan_error"] = "engine raised an error but the plan returned a value"
        return base
    plan_keys = [k for k, _ in pairs]
    engine_keys = [k for k, _ in engine_kv_exact]
    if set(plan_keys) != set(engine_keys):
        base["plan_status"] = "plan-differs"
        base["plan_error"] = f"group keys differ: engine {engine_keys[:12]} vs plan {plan_keys[:12]}"
    elif plan_keys != engine_keys:
        base["plan_status"] = "plan-differs"
        base["plan_error"] = f"group key order differs: engine {engine_keys[:12]} vs plan {plan_keys[:12]}"
    else:
        bad = next(
            (
                (k, pv, ev)
                for (k, pv), (_, ev) in zip(pairs, engine_kv_exact)
                if not (type(pv) is type(ev) and pv == ev and format_report_value(pv) == format_report_value(ev))
            ),
            None,
        )
        if bad is None:
            base["plan_status"] = "plan-same"
        else:
            base["plan_status"] = "plan-differs"
            base["plan_error"] = f"key {bad[0]}: engine {format_report_value(bad[2])} vs plan {format_report_value(bad[1])}"
    return base


def plan_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    """Rule A+ counts: whitelist allowed / refused and the plan status classes."""
    counts: dict[str, int] = {
        "allowed": 0, "refused": 0, "plan-same": 0, "plan-differs": 0, "plan-refused": 0,
        "plan-refused-allowed": 0, "plan-sql-error": 0, "plan-crash": 0, "plan-skipped": 0,
    }
    for r in results:
        status = r.get("plan_status")
        if status is None:
            continue
        counts[status] = counts.get(status, 0) + 1
        if status != "plan-skipped" and status != "plan-crash":
            counts["allowed" if r.get("plan_allowed") else "refused"] += 1
    return counts


# ==============================================================================
# SECTION: RUN COMPARISON WORKFLOW
# ==============================================================================

def run_comparison(
    rows: int = 2000,
    seed: int = 42,
    perf_rows: int = 0,
    overrides: dict[str, Any] | None = None,
    formula_filter: list[str] | None = None,
    skip_naive: bool = False,
    skip_parquet: bool = False,
    skip_group_by: bool = False,
    use_plan: bool = False,
) -> dict[str, Any]:
    """Run comparison workflow across engine, CSV store, and Parquet store.

    use_plan (Rule A+): every non-group-by formula is also planned and executed through
    analytics_studio.store.dax_sql.plan_measure and compared with the engine value (tolerance 0).
    """
    overrides = overrides or {}
    temp_dir = tempfile.mkdtemp()
    t_path = Path(temp_dir)
    csv_file = t_path / "t.csv"
    pq_file = t_path / "t.parquet"
    db_file = t_path / "store.db"

    t0 = time.time()
    gen_meta = generate_dataset(csv_file, pq_file, rows=rows, seed=seed)
    headers = gen_meta["headers"]

    # 1. Setup DuckStore
    store = DuckStore(str(db_file))
    import_csv_to_store(store, "t_csv", csv_file, {})
    if not skip_parquet:
        import_parquet_to_store(store, "t_pq", pq_file, {})

    # F7: Inspect store metadata for max decimals and digits
    col_meta = column_decimal_meta(store, "t_csv", ["d", "w", "big", "num_dups"])
    decimal_scales: dict[str, int] = {col: m.scale for col, m in col_meta.items()}
    max_digits_map: dict[str, int] = {col: m.digits for col, m in col_meta.items()}

    store_meta = {"decimal_scales": decimal_scales, "max_digits": max_digits_map}
    plan_meta: dict[tuple[str, str], ColumnMeta] = {("t", col): m for col, m in col_meta.items()}

    # 2. Evaluate on Engine
    cA = StudioController()
    cA._effective_app_data_dir = lambda: str(t_path / "app_data")
    assert cA._commit_import(csv_file, parse_file(csv_file))
    ctx = cA._measure_table_context()
    aid = cA._active_model_table_id()
    tname = cA._active_model_table_name()
    cand_rows = cA._loaded_candidates[cA._active_source_id].rows
    cand_headers = cA._headers
    model_types = cA._project["model"]["tables"][0]["column_types"]

    all_formulas = build_formula_catalog(headers)
    if formula_filter:
        filter_set = set(formula_filter)
        formulas = [f for f in all_formulas if f["id"] in filter_set or f["shape"] in filter_set]
    else:
        formulas = [f for f in all_formulas if f["id"] != "forced_wrong_formula"]

    if skip_group_by:
        formulas = [f for f in formulas if not f.get("group_col")]

    # Pre-fetch engine group keys in dictionary order
    engine_group_keys: dict[str, list[str]] = {}
    if not skip_group_by:
        for g_col in ["cat", "t", "dt", "flag"]:
            try:
                tocsv_dax = f"TOCSV(VALUES({tname}[{g_col}]), 100000)"
                m_gk = normalize_measure(f"M_GK_{g_col}", tocsv_dax, home_table_id=aid)
                gk_res = evaluate_measures(
                    [m_gk],
                    cand_rows,
                    cand_headers,
                    tname,
                    measure_names=[f"M_GK_{g_col}"],
                    table_context=ctx,
                    relationships=[],
                    filter_table_ids=[],
                    active_table_id=aid,
                )[f"M_GK_{g_col}"]
                lines = gk_res.split("\n")[1:] if gk_res else []
                # Keep unique keys preserving order
                seen_k = set()
                dedup_keys = []
                for k in lines:
                    if k not in seen_k:
                        seen_k.add(k)
                        dedup_keys.append(k)
                engine_group_keys[g_col] = dedup_keys
            except Exception:
                engine_group_keys[g_col] = []

    results: list[dict[str, Any]] = []

    for f_item in formulas:
        f_id = f_item["id"]
        dax_expr = f_item["dax"]
        shape = f_item["shape"]
        g_col = f_item.get("group_col")

        # A: Engine evaluation
        engine_err = None
        engine_val = None
        engine_text = ""
        engine_kv_exact: list[tuple[str, Any]] | None = None

        if g_col:
            # F5 / Work item G: Group-by evaluation using engine key order
            try:
                g_target = f_item.get("col")
                g_agg = f_item["agg"]
                val_expr = f"COUNTROWS({tname})" if g_agg == "COUNTROWS" else f"{g_agg}({tname}[{g_target}])"
                e_keys = engine_group_keys.get(g_col, [])
                pairs: list[str] = []
                engine_kv_exact = []
                for k in e_keys:
                    if k == "":
                        filter_part = f"ISBLANK({tname}[{g_col}])" if g_col in ("dt", "flag") else f'{tname}[{g_col}] = ""'
                    elif g_col == "flag":
                        filter_part = f"{tname}[{g_col}] = {k}()"
                    elif g_col == "dt":
                        # format is m/d/yyyy
                        parts = k.split("/")
                        filter_part = f"{tname}[{g_col}] = DATE({parts[2]}, {int(parts[0])}, {int(parts[1])})"
                    else:
                        filter_part = f'{tname}[{g_col}] = "{k}"'

                    calc_dax = f"CALCULATE({val_expr}, {filter_part})"
                    m = normalize_measure("M", calc_dax, home_table_id=aid)
                    k_val = evaluate_measures(
                        [m],
                        cand_rows,
                        cand_headers,
                        tname,
                        measure_names=["M"],
                        table_context=ctx,
                        relationships=[],
                        filter_table_ids=[],
                        active_table_id=aid,
                    )["M"]
                    disp_str = format_report_value(k)
                    val_str = format_report_value(k_val)
                    pairs.append(f"{disp_str}:{val_str}")
                    engine_kv_exact.append((disp_str, k_val))

                engine_val = ";".join(pairs)
                engine_text = engine_val
            except Exception as exc:
                engine_err = str(exc)
                engine_text = f"ERR:{engine_err[:60]}"
        else:
            try:
                expr = dax_expr.replace("t[", f"{tname}[").replace("(t)", f"({tname})").replace("(t,", f"({tname},")
                m = normalize_measure("M", expr, home_table_id=aid)
                res = evaluate_measures(
                    [m],
                    cand_rows,
                    cand_headers,
                    tname,
                    measure_names=["M"],
                    table_context=ctx,
                    relationships=[],
                    filter_table_ids=[],
                    active_table_id=aid,
                )["M"]
                engine_val = res
                if overrides.get("forced_wrong_value") and f_id == "forced_wrong_formula":
                    engine_val = Decimal("10.123456")
                if overrides.get("forced_equal_value") and f_id == "forced_wrong_formula":
                    engine_val = Decimal("100000000000000.5")
                engine_text = format_report_value(engine_val)
            except Exception as exc:
                engine_err = str(exc)
                engine_text = f"ERR:{engine_err[:60]}"

        # B: Naive SQL evaluation
        naive_val = None
        naive_text = ""
        naive_err = None
        if not skip_naive:
            naive_sql_res = generate_sql(f_item, "t_csv", model_types, mode="naive")
            if naive_sql_res is None or isinstance(naive_sql_res, Refusal):
                naive_err = "NOT_SUPPORTED"
                naive_text = "ERR:NOT_SUPPORTED"
            else:
                try:
                    row_res = store.execute(naive_sql_res)
                    naive_val = row_res[0][0] if row_res else None
                    naive_text = format_report_value(naive_val)
                except Exception as exc:
                    naive_err = str(exc)
                    naive_text = f"ERR:{naive_err[:60]}"

        # C: Mapped SQL evaluation (CSV store)
        mapped_val = None
        mapped_text = ""
        mapped_err = None
        mapped_refusal = None
        mapped_kv: list[list[str]] | None = None
        mapped_kv_exact: list[tuple[str, Any]] | None = None
        mapped_status_reason: str | None = None

        if g_col:
            # Group-by mapped execution
            try:
                g_target = f_item.get("col")
                g_agg = f_item["agg"]
                d_scale = store_meta["decimal_scales"].get(g_target, 4) if g_target else 4

                if g_agg == "COUNTROWS":
                    val_expr = "COUNT(*)"
                elif g_agg == "SUM":
                    if g_target == "w":
                        if overrides.get("gb_sum_double"):
                            val_expr = "SUM(TRY_CAST(NULLIF(w, '') AS DOUBLE))"
                        else:
                            val_expr = "SUM(TRY_CAST(NULLIF(w, '') AS HUGEINT))"
                    else:
                        if overrides.get("gb_sum_double"):
                            val_expr = f"SUM(TRY_CAST(NULLIF({g_target}, '') AS DOUBLE))"
                        else:
                            val_expr = f"SUM(TRY_CAST(NULLIF({g_target}, '') AS DECIMAL(38, {d_scale})))"
                elif g_agg == "AVERAGE":
                    if overrides.get("gb_avg_float"):
                        val_expr = f"AVG(TRY_CAST(NULLIF({g_target}, '') AS DOUBLE))"
                    else:
                        avg_scale = 3 if overrides.get("gb_avg_scale_3") else d_scale
                        val_expr = f"SUM(TRY_CAST(NULLIF({g_target}, '') AS DECIMAL(38, {avg_scale}))), COUNT(TRY_CAST(NULLIF({g_target}, '') AS DECIMAL(38, {avg_scale})))"
                elif g_agg == "DISTINCTCOUNT":
                    if overrides.get("gb_distinct_no_blank_add"):
                        val_expr = f"COUNT(DISTINCT NULLIF({g_target}, ''))"
                    else:
                        val_expr = f"COUNT(DISTINCT NULLIF({g_target}, '')) + MAX(CASE WHEN COALESCE({g_target}, '') = '' THEN 1 ELSE 0 END)"
                elif g_agg == "MIN":
                    val_expr = f"MIN(TRY_CAST(NULLIF({g_target}, '') AS DATE))"

                if g_col == "cat":
                    q = f"SELECT cat as k, {val_expr}, MIN(rowid) as first_rn FROM \"t_csv\" GROUP BY cat ORDER BY first_rn"
                elif g_col == "t":
                    fold_t = fold_sql("t")
                    q = f"SELECT {first_spelling_expr_sql('t')} as k, {val_expr}, MIN(rowid) as first_rn FROM \"t_csv\" GROUP BY {fold_t} ORDER BY first_rn"
                elif g_col == "dt":
                    q = f"SELECT COALESCE(strftime(TRY_CAST(NULLIF(dt, '') AS DATE), '%-m/%-d/%Y'), '') as k, {val_expr} FROM \"t_csv\" GROUP BY TRY_CAST(NULLIF(dt, '') AS DATE) ORDER BY TRY_CAST(NULLIF(dt, '') AS DATE) NULLS FIRST"
                elif g_col == "flag":
                    q = f"SELECT (CASE WHEN UPPER(TRIM(COALESCE(flag, ''))) = 'TRUE' THEN 'TRUE' ELSE 'FALSE' END) as k, {val_expr} FROM \"t_csv\" GROUP BY 1 ORDER BY 1 ASC"

                sql_rows = store.execute(q)
                sql_keys = []
                sql_dict = {}
                for r_tuple in sql_rows:
                    k_str = str(r_tuple[0] if r_tuple[0] is not None else "")
                    sql_keys.append(k_str)
                    if g_agg == "AVERAGE":
                        if overrides.get("gb_avg_float"):
                            sql_dict[k_str] = r_tuple[1]
                        else:
                            s_part, c_part = r_tuple[1], r_tuple[2]
                            sql_dict[k_str] = StoreResultLayer.divide(s_part, c_part, overrides=overrides)
                    else:
                        sql_dict[k_str] = r_tuple[1]

                e_keys = engine_group_keys.get(g_col, [])
                if overrides.get("gb_extra_key"):
                    sql_keys.append("EXTRA_KEY")
                    sql_dict["EXTRA_KEY"] = 999
                elif overrides.get("gb_missing_key") and sql_keys:
                    dropped_k = sql_keys.pop(0)
                    sql_dict.pop(dropped_k, None)
                elif overrides.get("gb_reverse_order"):
                    sql_keys = list(reversed(sql_keys))

                if set(sql_keys) != set(e_keys):
                    mapped_err = f"Group-by keys mismatch: sql has {len(sql_keys)} keys, engine has {len(e_keys)} keys"
                    mapped_text = f"ERR:{mapped_err[:60]}"
                elif sql_keys != e_keys:
                    mapped_err = "Group-by key ordering mismatch between store and engine"
                    mapped_text = f"ERR:{mapped_err[:60]}"
                else:
                    mapped_kv = [[format_report_value(k), format_report_value(sql_dict[k])] for k in sql_keys]
                    mapped_kv_exact = [(format_report_value(k), sql_dict[k]) for k in sql_keys]
                    mapped_val = ";".join(f"{kd}:{vd}" for kd, vd in mapped_kv)
                    mapped_text = mapped_val
            except Exception as exc:
                mapped_err = str(exc)
                mapped_text = f"ERR:{mapped_err[:60]}"
        else:
            mapped_sql_res = generate_sql(
                f_item,
                "t_csv",
                model_types,
                mode="mapped",
                is_parquet=False,
                store_meta=store_meta,
                overrides=overrides,
            )

            if isinstance(mapped_sql_res, Refusal):
                mapped_refusal = mapped_sql_res
                mapped_text = str(mapped_sql_res)
            elif mapped_sql_res is None:
                mapped_refusal = Refusal("Unsupported shape")
                mapped_text = str(mapped_refusal)
            elif isinstance(mapped_sql_res, str) and mapped_sql_res.startswith("EXACT_AVERAGE:"):
                # Work item A2: Exact AVERAGE via sum / count in Python Decimal context
                _, cast_c, where_part = mapped_sql_res.split(":", 2)
                try:
                    q = f"SELECT SUM({cast_c}), COUNT({cast_c}) FROM \"t_csv\" {where_part}"
                    s_res, c_res = store.execute(q)[0]
                    mapped_val = StoreResultLayer.divide(s_res, c_res, overrides=overrides)
                    mapped_text = format_report_value(mapped_val)
                except Exception as exc:
                    mapped_err = str(exc)
                    mapped_text = f"ERR:{mapped_err[:60]}"
            elif mapped_sql_res == "COMBO_SUM":
                # Work item A3: Exact combo sums
                try:
                    s_w = store.execute('SELECT SUM(TRY_CAST(NULLIF(w, \'\') AS HUGEINT)) FROM "t_csv"')[0][0]
                    d_sc = store_meta["decimal_scales"].get("d", 4)
                    s_d = store.execute(f'SELECT SUM(TRY_CAST(NULLIF(d, \'\') AS DECIMAL(38, {d_sc}))) FROM "t_csv"')[0][0]
                    # Compute in Python Decimal / float arithmetic layer matching engine
                    f_sum = float(Decimal(str(s_w or 0))) + float(Decimal(str(s_d or 0)))
                    mapped_val = Decimal(f_sum)
                    mapped_text = format_report_value(mapped_val)
                except Exception as exc:
                    mapped_err = str(exc)
                    mapped_text = f"ERR:{mapped_err[:60]}"
            elif mapped_sql_res == "PLUS_SCALAR":
                try:
                    s_w = store.execute('SELECT SUM(TRY_CAST(NULLIF(w, \'\') AS HUGEINT)) FROM "t_csv"')[0][0]
                    f_res = float(Decimal(str(s_w or 0))) + 0.1
                    mapped_val = Decimal(f_res)
                    mapped_text = format_report_value(mapped_val)
                except Exception as exc:
                    mapped_err = str(exc)
                    mapped_text = f"ERR:{mapped_err[:60]}"
            elif mapped_sql_res == "RATIO":
                try:
                    d_sc = store_meta["decimal_scales"].get("d", 4)
                    s_d = store.execute(f'SELECT SUM(TRY_CAST(NULLIF(d, \'\') AS DECIMAL(38, {d_sc}))) FROM "t_csv"')[0][0]
                    c_d = store.execute('SELECT COUNT(NULLIF(d, \'\')) FROM "t_csv"')[0][0]
                    mapped_val = StoreResultLayer.divide_ratio(s_d, c_d, overrides=overrides)
                    mapped_text = format_report_value(mapped_val)
                except Exception as exc:
                    mapped_err = str(exc)
                    mapped_text = f"ERR:{mapped_err[:60]}"
            elif mapped_sql_res == "COMBO_SUB":
                try:
                    s_w, c_w = store.execute('SELECT SUM(TRY_CAST(NULLIF(w, \'\') AS HUGEINT)), COUNT(TRY_CAST(NULLIF(w, \'\') AS HUGEINT)) FROM "t_csv"')[0]
                    min_w = store.execute('SELECT MIN(TRY_CAST(NULLIF(w, \'\') AS HUGEINT)) FROM "t_csv"')[0][0]
                    avg_w = StoreResultLayer.divide(s_w, c_w, overrides=overrides)
                    diff_f = float(avg_w or 0) - float(Decimal(str(min_w or 0)))
                    mapped_val = Decimal(diff_f)
                    mapped_text = format_report_value(mapped_val)
                except Exception as exc:
                    mapped_err = str(exc)
                    mapped_text = f"ERR:{mapped_err[:60]}"
            else:
                try:
                    row_res = store.execute(mapped_sql_res)
                    mapped_val = row_res[0][0] if row_res else None
                    if overrides.get("forced_wrong_value") and f_id == "forced_wrong_formula":
                        mapped_val = Decimal("10.123457")
                    if overrides.get("forced_equal_value") and f_id == "forced_wrong_formula":
                        mapped_val = Decimal("100000000000000.5")
                    mapped_text = format_report_value(mapped_val)
                except Exception as exc:
                    mapped_err = str(exc)
                    mapped_text = f"ERR:{mapped_err[:60]}"

        # D: Parquet store evaluation
        pq_val = None
        pq_text = ""
        pq_err = None
        pq_refusal = None
        pq_kv: list[list[str]] | None = None
        pq_kv_exact: list[tuple[str, Any]] | None = None

        if not skip_parquet:
            if g_col:
                # Group-by on Parquet
                try:
                    g_target = f_item.get("col")
                    g_agg = f_item["agg"]
                    d_scale = store_meta["decimal_scales"].get(g_target, 4) if g_target else 4

                    if g_agg == "COUNTROWS":
                        val_expr = "COUNT(*)"
                    elif g_agg == "SUM":
                        if g_target == "w":
                            val_expr = "SUM(w)"
                        else:
                            val_expr = f"SUM(CAST(CAST(d AS VARCHAR) AS DECIMAL(38, {d_scale})))"
                    elif g_agg == "AVERAGE":
                        avg_scale = 3 if overrides.get("pq_gb_avg_scale_3") else d_scale
                        val_expr = f"SUM(CAST(CAST({g_target} AS VARCHAR) AS DECIMAL(38, {avg_scale}))), COUNT(CAST(CAST({g_target} AS VARCHAR) AS DECIMAL(38, {avg_scale})))"
                    elif g_agg == "DISTINCTCOUNT":
                        val_expr = f"COUNT(DISTINCT {g_target}) + MAX(CASE WHEN {g_target} IS NULL THEN 1 ELSE 0 END)"
                    elif g_agg == "MIN":
                        val_expr = "MIN(dt)"

                    if g_col == "cat":
                        q = f"SELECT cat as k, {val_expr} FROM \"t_pq\" GROUP BY cat"
                    elif g_col == "t":
                        fold_t = fold_sql("t")
                        q = f"SELECT {first_spelling_expr_sql('t')} as k, {val_expr} FROM \"t_pq\" GROUP BY {fold_t}"
                    elif g_col == "dt":
                        q = f"SELECT strftime(TRY_CAST(dt AS DATE), '%-m/%-d/%Y') as k, {val_expr} FROM \"t_pq\" GROUP BY TRY_CAST(dt AS DATE)"
                    elif g_col == "flag":
                        q = f"SELECT (CASE WHEN COALESCE(flag, FALSE) THEN 'TRUE' ELSE 'FALSE' END) as k, {val_expr} FROM \"t_pq\" GROUP BY 1"

                    sql_rows = store.execute(q)
                    sql_dict = {}
                    for r_tuple in sql_rows:
                        k_str = str(r_tuple[0] if r_tuple[0] is not None else "")
                        if g_agg == "AVERAGE":
                            s_part, c_part = r_tuple[1], r_tuple[2]
                            sql_dict[k_str] = StoreResultLayer.divide(s_part, c_part, overrides=overrides)
                        else:
                            sql_dict[k_str] = r_tuple[1]

                    e_keys = engine_group_keys.get(g_col, [])
                    pq_kv = [[format_report_value(k), format_report_value(sql_dict.get(k))] for k in e_keys]
                    pq_kv_exact = [(format_report_value(k), sql_dict.get(k)) for k in e_keys]
                    pq_val = ";".join(f"{kd}:{vd}" for kd, vd in pq_kv)
                    pq_text = pq_val
                except Exception as exc:
                    pq_err = str(exc)
                    pq_text = f"ERR:{pq_err[:60]}"
            else:
                pq_sql_res = generate_sql(
                    f_item,
                    "t_pq",
                    model_types,
                    mode="mapped",
                    is_parquet=True,
                    store_meta=store_meta,
                    overrides=overrides,
                )

                if isinstance(pq_sql_res, Refusal):
                    pq_refusal = pq_sql_res
                    pq_text = str(pq_sql_res)
                elif pq_sql_res is None:
                    pq_refusal = Refusal("Unsupported shape")
                    pq_text = str(pq_refusal)
                elif isinstance(pq_sql_res, str) and pq_sql_res.startswith("EXACT_AVERAGE:"):
                    _, cast_c, where_part = pq_sql_res.split(":", 2)
                    try:
                        q = f"SELECT SUM({cast_c}), COUNT({cast_c}) FROM \"t_pq\" {where_part}"
                        s_res, c_res = store.execute(q)[0]
                        pq_val = StoreResultLayer.divide(s_res, c_res, overrides=overrides)
                        pq_text = format_report_value(pq_val)
                    except Exception as exc:
                        pq_err = str(exc)
                        pq_text = f"ERR:{pq_err[:60]}"
                elif pq_sql_res == "COMBO_SUM":
                    try:
                        s_w = store.execute('SELECT SUM(w) FROM "t_pq"')[0][0]
                        d_sc = store_meta["decimal_scales"].get("d", 4)
                        s_d = store.execute(f'SELECT SUM(CAST(CAST(d AS VARCHAR) AS DECIMAL(38, {d_sc}))) FROM "t_pq"')[0][0]
                        f_sum = float(Decimal(str(s_w or 0))) + float(Decimal(str(s_d or 0)))
                        pq_val = Decimal(f_sum)
                        pq_text = format_report_value(pq_val)
                    except Exception as exc:
                        pq_err = str(exc)
                        pq_text = f"ERR:{pq_err[:60]}"
                elif pq_sql_res == "PLUS_SCALAR":
                    try:
                        s_w = store.execute('SELECT SUM(w) FROM "t_pq"')[0][0]
                        f_res = float(Decimal(str(s_w or 0))) + 0.1
                        pq_val = Decimal(f_res)
                        pq_text = format_report_value(pq_val)
                    except Exception as exc:
                        pq_err = str(exc)
                        pq_text = f"ERR:{pq_err[:60]}"
                elif pq_sql_res == "RATIO":
                    try:
                        d_sc = store_meta["decimal_scales"].get("d", 4)
                        s_d = store.execute(f'SELECT SUM(CAST(CAST(d AS VARCHAR) AS DECIMAL(38, {d_sc}))) FROM "t_pq"')[0][0]
                        c_d = store.execute('SELECT COUNT(d) FROM "t_pq"')[0][0]
                        pq_val = StoreResultLayer.divide_ratio(s_d, c_d, overrides=overrides)
                        pq_text = format_report_value(pq_val)
                    except Exception as exc:
                        pq_err = str(exc)
                        pq_text = f"ERR:{pq_err[:60]}"
                elif pq_sql_res == "COMBO_SUB":
                    try:
                        s_w, c_w = store.execute('SELECT SUM(w), COUNT(w) FROM "t_pq"')[0]
                        min_w = store.execute('SELECT MIN(w) FROM "t_pq"')[0][0]
                        avg_w = StoreResultLayer.divide(s_w, c_w, overrides=overrides)
                        diff_f = float(avg_w or 0) - float(Decimal(str(min_w or 0)))
                        pq_val = Decimal(diff_f)
                        pq_text = format_report_value(pq_val)
                    except Exception as exc:
                        pq_err = str(exc)
                        pq_text = f"ERR:{pq_err[:60]}"
                else:
                    try:
                        row_res = store.execute(pq_sql_res)
                        pq_val = row_res[0][0] if row_res else None
                        pq_text = format_report_value(pq_val)
                    except Exception as exc:
                        pq_err = str(exc)
                        pq_text = f"ERR:{pq_err[:60]}"

        # Status classification (Rules F2 & F3)
        if not skip_naive:
            if engine_err and naive_err:
                naive_status = "both-error"
            elif engine_err:
                naive_status = "engine-error"
            elif naive_err:
                naive_status = "sql-error"
            elif engine_text == naive_text:
                naive_status = "same"
            else:
                naive_status = "differs"
        else:
            naive_status = "skipped"

        if engine_err:
            if mapped_refusal is not None:
                if refusal_matches_engine_error(mapped_refusal, engine_err):
                    mapped_status = "same"
                else:
                    mapped_status = "refusal-reason-mismatch"
            elif mapped_err is not None:
                mapped_status = "sql-error"
            else:
                mapped_status = "differs"
        else:
            if mapped_err is not None:
                mapped_status = "sql-error"
            elif mapped_refusal is not None:
                mapped_status = "refused"
            elif engine_text != mapped_text:
                mapped_status = "differs"
            elif not exact_values_agree(engine_val, mapped_val) or not group_values_agree(engine_kv_exact, mapped_kv_exact):
                mapped_status = "differs"
                mapped_status_reason = "exact-value"
            else:
                mapped_status = "same"

        if skip_parquet:
            pq_vs_csv_diff = False
        elif pq_err is None and mapped_err is None:
            if pq_text != mapped_text:
                pq_vs_csv_diff = True
            elif not exact_values_agree(pq_val, mapped_val) or not group_values_agree(pq_kv_exact, mapped_kv_exact):
                pq_vs_csv_diff = True
            else:
                pq_vs_csv_diff = False
        else:
            pq_vs_csv_diff = pq_err != mapped_err

        plan_fields: dict[str, Any] = {}
        if use_plan:
            plan_fields = evaluate_plan_row(
                f_item, engine_val, engine_err, store, {"t": model_types}, plan_meta, overrides, engine_kv_exact
            )

        results.append({
            "id": f_id,
            "category": f_item["category"],
            "shape": shape,
            "dax": dax_expr,
            "engine_val": str(engine_val),
            "engine_text": engine_text,
            "engine_err": engine_err,
            "naive_val": str(naive_val),
            "naive_text": naive_text,
            "naive_err": naive_err,
            "naive_status": naive_status,
            "mapped_val": str(mapped_val),
            "mapped_text": mapped_text,
            "mapped_err": mapped_err,
            "mapped_refusal": str(mapped_refusal) if mapped_refusal else None,
            "mapped_refusal_obj": mapped_refusal,
            "mapped_kv": mapped_kv,
            "pq_kv": pq_kv,
            "engine_kv_exact": engine_kv_exact,
            "mapped_kv_exact": mapped_kv_exact,
            "pq_kv_exact": pq_kv_exact,
            "mapped_status": mapped_status,
            "mapped_status_reason": mapped_status_reason,
            "pq_val": str(pq_val),
            "pq_text": pq_text,
            "pq_err": pq_err,
            "pq_refusal": str(pq_refusal) if pq_refusal else None,
            "pq_vs_csv_diff": pq_vs_csv_diff,
            **plan_fields,
        })

    perf_metrics: dict[str, Any] = {}
    if perf_rows > 0:
        perf_metrics = run_perf_benchmark(t_path, perf_rows, use_plan=use_plan)

    # Classify mapped differences and Parquet differences by data (never by formula-id name)
    item_by_id = {f["id"]: f for f in formulas}
    pq_ctx: dict[str, Any] = {
        "store": store,
        "store_meta": store_meta,
        "overrides": overrides,
        "group_keys": engine_group_keys,
        "cols": pq.read_table(pq_file).to_pydict() if not skip_parquet else {},
    }
    for r in results:
        f_item = item_by_id[r["id"]]
        if r["mapped_status"] == "differs" and eval_distinct_numeric_predicate(r, f_item, store, store_meta, overrides):
            r["mapped_diff_class"] = "distinct_numeric_text_variants"
        else:
            r["mapped_diff_class"] = None

        if r["pq_vs_csv_diff"]:
            r["pq_diff_class"] = classify_parquet_diff(r, f_item, pq_ctx)
        else:
            r["pq_diff_class"] = None

    store.close()
    wall_sec = time.time() - t0

    return {
        "rows": rows,
        "seed": seed,
        "wall_sec": wall_sec,
        "total_formulas": len(results),
        "decimal_scales": decimal_scales,
        "results": results,
        "perf": perf_metrics,
    }


# ==============================================================================
# SECTION: LITERAL SWEEP (Stage C1b2): literals, filter contexts and group-by against the engine
# ==============================================================================

SWEEP_HEADERS = ["sid", "sw", "sd", "sdt", "st", "sf", "scat", "swb", "sdb", "sg", "sb", "sdt_old"]
SWEEP_COLUMN_TYPES = {
    "sid": "text", "sw": "whole_number", "sd": "decimal_number", "sdt": "date", "st": "text", "sf": "boolean",
    "scat": "text", "swb": "text", "sdb": "text", "sg": "text", "sb": "text", "sdt_old": "date",
}
# A date column with cells before 1900-01-01 (the engine shows other key text, other values, or raises): the store
# refuses every plan that reads it. The first rows hold these cells, the rest are ordinary dates and blanks.
SWEEP_OLD_DATES = ["1899-12-30", "1900-01-01", "0001-01-01", "0100-05-05"]
SWEEP_OLD_DATE_FILLER = ["", "2020-01-05", "2026-03-04", "2025-12-31"]
# The model infers text for a whole number of 16 or more digits and for a 30-digit decimal (measured with the
# controller import), so 2^63-1, -2^63 and the 30-digit decimal live in the text columns swb and sdb.
SWEEP_WHOLE = [
    "0", "-0", "1", "-1", "5", "99", "15", "6", "-5", "100", "2147483648", "-2147483649", "999999999999999",
    "-999999999999999", "900719925474099",
]
SWEEP_WHOLE_BIG = ["9223372036854775807", "-9223372036854775808", "9223372036854775808", "1234567890123456789012"]
SWEEP_DECIMAL = [
    "0", "0.0", "0.00", "-0.5", "0.5", "0.25", "12.345", "0.000001", "-0.0000005", "1.5", "-2.25", "100.123456",
    "123456789012345678.123456", "1234567890.1234567", "0.1", "0.2", "0.3", "-0.000001", "7", "-7.5", "3.14159",
]
SWEEP_DECIMAL_BIG = ["123456789012345678901234567890", "-123456789012345678901234567890.5", "0.1"]
SWEEP_DATES = [
    "1900-01-01", "1900-01-02", "9999-12-31", "2000-02-29", "2024-02-29", "2026-06-01", "2026-06-02", "2025-12-31",
    "2026-01-01", "1999-12-31",
]
NBSP_CELLS = ["\u00a0", "\u0085", "\u3000", "\u2003"]
SWEEP_TEXT = [
    "", " ", "  ", "A", "a", "A ", "A\t", "B", "b", "C", "SS", "ss", "ß", "ünï", "ÜNÏ", "it's", 'say "hi"',
    'a,b', "x y", "K", "k", *NBSP_CELLS, "A\u00a0", "\u00a0A",
]
SWEEP_CATS = ["A", "B", "C", "D", "E"]
# ASCII-only text with blanks, spaces and a tab: the column the blank and whitespace equality rows and the
# IN rows run on (the guard lets an ASCII-only column through)
SWEEP_ASCII_TEXT = ["", " ", "  ", "\t", "A", "a", "A ", "A\t", "B", "b", "a b", "x", "it's", 'say "hi"', "K", "k", "ss", "SS"]
# Group-by text column without non-ASCII whitespace: case variants, trailing space and tab, blank, a
# whitespace-only cell, non-ASCII letters and the ss / eszett pair
SWEEP_GROUP_TEXT = ["", "A", "a", "A ", "A\t", "B", "b", "ünï", "ÜNÏ", "SS", "ss", "ß", "x y", " ", "C", "c  ", 'q"r']


def generate_sweep_dataset(csv_file: Path, rows: int = 300, seed: int = 1) -> dict[str, Any]:
    """Seeded sweep table: edge literals planted by row number (so every row count above ~60 holds all of
    them) plus random picks and a planted share of blank cells. Column types: SWEEP_COLUMN_TYPES."""
    rnd = random.Random(seed)
    rnd_old = random.Random(seed * 7919 + 13)  # own stream: the older columns keep their values

    def pick(values: list[str], i: int, blank_share: float) -> str:
        if i <= len(values):
            return values[i - 1]  # planted: the first len(values) rows hold every special value once
        if rnd.random() < blank_share:
            return ""
        return values[rnd.randint(0, len(values) - 1)]

    out: list[list[str]] = []
    for i in range(1, rows + 1):
        w = pick(SWEEP_WHOLE, i, 0.12)
        if i > len(SWEEP_WHOLE) and w not in ("", "-0") and rnd.random() < 0.5:
            w = str(rnd.randint(-20, 120))
        out.append([
            f"s{i}",
            w,
            pick(SWEEP_DECIMAL, i, 0.12),
            pick(SWEEP_DATES, i, 0.12),
            pick(SWEEP_TEXT, i, 0.0) if i <= len(SWEEP_TEXT) else (
                "" if rnd.random() < 0.10 else SWEEP_TEXT[rnd.randint(0, len(SWEEP_TEXT) - 1)]
            ),
            "" if rnd.random() < 0.12 else rnd.choice(["TRUE", "FALSE"]),
            SWEEP_CATS[rnd.randint(0, len(SWEEP_CATS) - 1)] if rnd.random() > 0.08 else "",
            pick(SWEEP_WHOLE_BIG, i, 0.2),
            pick(SWEEP_DECIMAL_BIG, i, 0.2),
            pick(SWEEP_GROUP_TEXT, i, 0.0) if i <= len(SWEEP_GROUP_TEXT) else (
                "" if rnd.random() < 0.08 else SWEEP_GROUP_TEXT[rnd.randint(0, len(SWEEP_GROUP_TEXT) - 1)]
            ),
            SWEEP_ASCII_TEXT[(i - 1) % len(SWEEP_ASCII_TEXT)] if i <= len(SWEEP_ASCII_TEXT) else (
                SWEEP_ASCII_TEXT[rnd.randint(0, len(SWEEP_ASCII_TEXT) - 1)]
            ),
            SWEEP_OLD_DATES[i - 1] if i <= len(SWEEP_OLD_DATES) else rnd_old.choice(SWEEP_OLD_DATE_FILLER),
        ])
    with open(csv_file, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(SWEEP_HEADERS)
        writer.writerows(out)
    return {"headers": list(SWEEP_HEADERS), "row_count": rows}


def _dax_string(text: str) -> str:
    """A DAX string literal (double quotes doubled)."""
    return '"' + text.replace('"', '""') + '"'


def with_filter_context(dax: str, predicates: tuple[str, ...]) -> str:
    """The flat engine reference of a measure under a filter context: CALCULATE(<base>, <own>, <context>)."""
    if not predicates:
        return dax
    text = dax.strip()
    if text.startswith("CALCULATE(") and text.endswith(")"):
        return text[:-1] + ", " + ", ".join(predicates) + ")"
    return f"CALCULATE({text}, " + ", ".join(predicates) + ")"


SWEEP_VALUE_AGG = {
    "sw": "SUM(t[sw])", "sd": "SUM(t[sd])", "sdt": "MIN(t[sdt])", "st": "DISTINCTCOUNT(t[st])",
    "sf": "COUNTA(t[sf])", "scat": "DISTINCTCOUNT(t[scat])", "sb": "DISTINCTCOUNT(t[sb])",
}
SWEEP_WHOLE_LITERALS = ["-1", "0", "1", "5", "99", "-9223372036854775808", "9223372036854775807", "2147483648"]
SWEEP_DECIMAL_LITERALS = [
    "0", "-0.5", "0.5", "0.25", "12.345", "0.000001", "-0.0000005", "123456789012345678.123456",
    "123456789012345678901234567890.12345678",  # 38 total digits
    "1234567890123456789012345678901.12345678",  # 39 digits: refused by the whitelist
    "0.123456789012345678901234567890",  # integer digits plus scale exceed 38 with the column digits: planner
]
SWEEP_DATE_LITERALS = [
    "DATE(1900,1,1)", "DATE(1900,1,2)", "DATE(9999,12,31)", "DATE(2000,2,29)", "DATE(2024,2,29)", "DATE(2026,6,1)",
]
SWEEP_BAD_DATE_LITERALS = ["DATE(1899,12,31)", "DATE(10000,1,1)", "DATE(2023,2,29)", "DATE(2100,2,29)"]
SWEEP_TEXT_LITERALS = [
    '""', '"A"', '"a"', '"A "', '"A\t"', '"SS"', '"ss"', '"ß"', '"ünï"', '"it\'s"', '"say ""hi"""', '" "', '"  "',
    '"\t"', '" "', '"\u0085"', '"　"', '" "', '"A "',
]
SWEEP_IN_LISTS = [
    '{"A", "B"}', '{"A", ""}', '{"A", "A", "a"}', '{"ünï"}', '{"a", "b", "c"}', '{""}', '{"ss"}', '{"K"}', '{"x y"}',
]
SWEEP_GROUP_AGGS = [
    "COUNTROWS(t)", "SUM(t[sw])", "SUM(t[sd])", "AVERAGE(t[sw])", "AVERAGE(t[sd])", "MIN(t[sw])", "MAX(t[sw])",
    "MIN(t[sd])", "MAX(t[sd])", "MIN(t[sdt])", "MAX(t[sdt])", "COUNT(t[sw])", "COUNT(t[sd])", "COUNT(t[sdt])",
    "COUNTA(t[sw])", "COUNTA(t[sdt])", "COUNTA(t[st])", "COUNTA(t[sf])", "COUNTA(t[scat])", "COUNTBLANK(t[sw])",
    "COUNTBLANK(t[sd])", "COUNTBLANK(t[sdt])", "COUNTBLANK(t[st])", "COUNTBLANK(t[sf])", "COUNTBLANK(t[scat])",
    "DISTINCTCOUNT(t[st])", "DISTINCTCOUNT(t[sdt])", "DISTINCTCOUNT(t[sf])", "DISTINCTCOUNT(t[scat])",
    "DISTINCTCOUNT(t[sw])",
]
SWEEP_GROUP_COLUMNS = ["scat", "sg", "sb", "st", "sdt", "sf"]
SWEEP_GROUP_CONTEXTS: list[tuple[str, ...]] = [
    (), ("t[sw] > 5",), ("t[sdt] >= DATE(2026,1,1)",), ('t[scat] IN {"A", "B"}',),
]
# Group-by measures with their own CALCULATE filter (Stage C4a): every aggregate the group plan supports, every
# own filter on a column OTHER than the group column. The engine value of a group with no matching row is blank and
# the app drops it, the plan joins only the groups that have a matching row.
SWEEP_OWN_AGGS = [
    "COUNTROWS(t)", "SUM(t[sw])", "AVERAGE(t[sd])", "MIN(t[sdt])", "MAX(t[sdt])", "COUNT(t[sw])", "COUNTA(t[st])",
    "DISTINCTCOUNT(t[st])",
]
SWEEP_OWN_FILTERS: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = [
    ("whole_eq", ("t[sw] = 5",), ("sw",)),
    ("whole_lt", ("t[sw] < 15",), ("sw",)),
    ("whole_ge", ("t[sw] >= 0",), ("sw",)),
    ("whole_ne", ("t[sw] <> 0",), ("sw",)),
    ("decimal_ge", ("t[sd] >= 0",), ("sd",)),
    ("decimal_lt", ("t[sd] < 12.345",), ("sd",)),
    ("date_ge", ("t[sdt] >= DATE(2026,1,1)",), ("sdt",)),
    ("date_lt", ("t[sdt] < DATE(2000,2,29)",), ("sdt",)),
    ("text_eq", ('t[sb] = "A"',), ("sb",)),
    ("text_in", ('t[scat] IN {"A", "B"}',), ("scat",)),
    ("two_columns", ("t[sw] > 5", "t[sd] >= 0"), ("sw", "sd")),
    ("whole_or", ("t[sw] = 0 || t[sw] = 1",), ("sw",)),
    ("no_row", ('t[scat] = "ZZZ"',), ("scat",)),
    ("some_groups", ("t[sw] = 99",), ("sw",)),
]
# An own filter on the group column itself: DAX replaces the group filter, refused by name (REASON_GROUP_OWN_FILTER).
# NOT and || are only on the whitelist over whole-number columns, and a group column is text, date or boolean, so a
# group-column filter inside NOT or || is refused by the whitelist before the planner: the planner's own walk over
# NOT, || and IN is tested on parsed expressions (tests/test_dax_sql_c4a.py).
SWEEP_OWN_ON_GROUP: dict[str, tuple[str, ...]] = {
    "scat": ('t[scat] = "A"', 't[scat] IN {"A", "B"}'),
    "sb": ('t[sb] = "A"',),
    "sdt": ("t[sdt] >= DATE(2026,1,1)",),
    "sf": ("t[sf] = TRUE()",),
}
SWEEP_SCALAR_BASES = [
    "COUNTROWS(t)", "SUM(t[sw])", "SUM(t[sd])", "AVERAGE(t[sd])", "MIN(t[sdt])", "DISTINCTCOUNT(t[st])",
    "COUNTBLANK(t[sf])", "CALCULATE(SUM(t[sw]), t[sd] >= 0)", "CALCULATE(COUNTROWS(t), t[sw] > 5)",
]
SWEEP_SCALAR_CONTEXTS: list[tuple[str, ...]] = [
    ("t[sw] > 5",), ('t[scat] IN {"A", "B"}',), ("t[sdt] >= DATE(2026,1,1)",), ('t[st] = "A"',),
    ("t[sw] > 5", "t[sd] >= 0"), ("t[sw] = 0 || t[sw] = 1",), ('t[scat] = "ZZZ"',), ("t[sw] > 5", "t[sw] < 15"),
    ("t[sw] < 15",), ("t[sd] < 0",), ('t[scat] IN {}',), ("",), ("t[sf] = TRUE()",),
]
SWEEP_EMPTY_AGGS = [
    "COUNTROWS(t)", "SUM(t[sw])", "AVERAGE(t[sw])", "MIN(t[sw])", "MAX(t[sw])", "COUNT(t[sw])", "COUNTA(t[sw])",
    "COUNTBLANK(t[sw])", "SUM(t[sd])", "AVERAGE(t[sd])", "MIN(t[sd])", "MAX(t[sd])", "COUNT(t[sd])", "COUNTA(t[sd])",
    "COUNTBLANK(t[sd])", "MIN(t[sdt])", "MAX(t[sdt])", "COUNT(t[sdt])", "COUNTA(t[sdt])", "COUNTBLANK(t[sdt])",
    "DISTINCTCOUNT(t[sdt])", "COUNTA(t[st])", "COUNTBLANK(t[st])", "DISTINCTCOUNT(t[st])", "COUNTA(t[sf])",
    "COUNTBLANK(t[sf])", "DISTINCTCOUNT(t[sf])",
]


def _sweep_row(family: str, dax: str, ctx: tuple[str, ...] = (), group: str | None = None) -> dict[str, Any]:
    row_id = f"{family}: {dax}"
    if ctx:
        row_id += " | ctx " + " ; ".join(ctx)
    if group:
        row_id += f" | by {group}"
    return {
        "id": row_id, "category": "sweep", "shape": family, "dax": dax, "filter_context": tuple(ctx),
        "group_by": ("t", group) if group else None,
    }


def build_sweep_catalog(headers: list[str] | None = None) -> list[dict[str, Any]]:
    """Deterministic literal-sweep rows (ids are built from the content, never from a seed or a counter)."""
    rows: list[dict[str, Any]] = []

    def both(family: str, predicate_texts: list[str], value_col: str) -> None:
        preds = ", ".join(predicate_texts)
        rows.append(_sweep_row(family, f"CALCULATE(COUNTROWS(t), {preds})"))
        rows.append(_sweep_row(family, f"CALCULATE({SWEEP_VALUE_AGG[value_col]}, {preds})"))

    for col in ("sw", "sd", "sdt", "st", "sf", "scat"):  # unfiltered aggregates of every sweep column
        rows.append(_sweep_row("plain", SWEEP_VALUE_AGG[col]))
    rows.append(_sweep_row("plain", "COUNTROWS(t)"))
    for col in ("swb", "sdb"):  # text columns that hold the huge numbers: numeric aggregates are refused
        rows.append(_sweep_row("big_text", f"SUM(t[{col}])"))
        rows.append(_sweep_row("big_text", f"COUNTA(t[{col}])"))
        rows.append(_sweep_row("big_text", f"CALCULATE(COUNTROWS(t), t[{col}] > 5)"))
    for op in ("=", "<", "<=", ">", ">=", "<>"):
        for lit in SWEEP_WHOLE_LITERALS:
            both(f"whole_{op}", [f"t[sw] {op} {lit}"], "sw")
    for lit in SWEEP_WHOLE_LITERALS:
        both("whole_not", [f"NOT(t[sw] = {lit})"], "sw")
    for a, b, c in (("0", "1", "-1"), ("5", "99", "2147483648"), ("-9223372036854775808", "9223372036854775807", "0")):
        both("whole_or", [f"t[sw] = {a} || t[sw] = {b} || t[sw] = {c}"], "sw")
    for op in (">=", "<", "<>"):
        for lit in SWEEP_DECIMAL_LITERALS:
            both(f"decimal_{op}", [f"t[sd] {op} {lit}"], "sd")
    for op in (">=", ">", "<=", "<", "<>"):
        for lit in SWEEP_DATE_LITERALS:
            both(f"date_{op}", [f"t[sdt] {op} {lit}"], "sdt")
    for lit in SWEEP_BAD_DATE_LITERALS:
        for op in (">=", "<"):
            both(f"date_bad_{op}", [f"t[sdt] {op} {lit}"], "sdt")
    for lit in SWEEP_TEXT_LITERALS:
        both("text_eq", [f"t[st] = {lit}"], "st")
    for items in SWEEP_IN_LISTS:
        both("text_in", [f"t[st] IN {items}"], "st")
    for lit in SWEEP_TEXT_LITERALS:
        both("text_eq_ascii", [f"t[sb] = {lit}"], "sb")
    for items in SWEEP_IN_LISTS:
        both("text_in_ascii", [f"t[sb] IN {items}"], "sb")
        both("text_in_cat", [f"t[scat] IN {items}"], "scat")
    both("two_same_column", ["t[sw] > 5", "t[sw] < 15"], "sw")
    both("two_same_column", ["t[sd] >= 0", "t[sd] < 12.345"], "sd")
    both("two_columns", ["t[sw] > 5", "t[sd] >= 0"], "sw")
    both("two_columns", ['t[st] = "A"', "t[sw] <> 0"], "sw")
    both("two_columns", ["t[sdt] >= DATE(2000,2,29)", 't[scat] IN {"A", "B"}'], "sd")
    both("two_columns", ["t[sw] = 0", 't[scat] = "ZZZ"'], "sw")
    for agg in SWEEP_EMPTY_AGGS:
        rows.append(_sweep_row("empty", f'CALCULATE({agg}, t[scat] = "ZZZ")'))
    for base in SWEEP_SCALAR_BASES:
        for ctx in SWEEP_SCALAR_CONTEXTS:
            rows.append(_sweep_row("context", base, ctx))
    for g_col in SWEEP_GROUP_COLUMNS:
        for agg in SWEEP_GROUP_AGGS:
            for ctx in SWEEP_GROUP_CONTEXTS:
                rows.append(_sweep_row("group", agg, ctx, g_col))
    for g_col in ("sg", "sdt", "sf", "st", "sb"):  # a filter context that removes every row: empty on both sides
        for agg in ("COUNTROWS(t)", "SUM(t[sw])", "AVERAGE(t[sd])"):
            rows.append(_sweep_row("group_empty", agg, ('t[scat] = "ZZZ"',), g_col))
    rows.append(_sweep_row("group", "SUM(t[sw])", (), "sw"))  # numeric group key: refused
    for g_col in SWEEP_GROUP_COLUMNS:  # a measure with its own CALCULATE filter on ANOTHER column (Stage C4a)
        for agg in SWEEP_OWN_AGGS:
            for _name, preds, columns in SWEEP_OWN_FILTERS:
                if g_col in columns:
                    continue
                own_row = _sweep_row("group_own", f"CALCULATE({agg}, {', '.join(preds)})", (), g_col)
                own_row["own_predicates"] = tuple(preds)
                rows.append(own_row)
    for g_col, preds_list in SWEEP_OWN_ON_GROUP.items():  # the same column as the group: refused
        for pred in preds_list:
            for agg in ("COUNTROWS(t)", "SUM(t[sw])"):
                rows.append(_sweep_row("group_own_column", f"CALCULATE({agg}, {pred})", (), g_col))
    for g_col in ("scat", "sb"):  # an own filter and a slicer on different columns, and on the same column
        for own_dax, own_pred, slicer in (
            ("CALCULATE(SUM(t[sw]), t[sd] >= 0)", "t[sd] >= 0", "t[sw] > 5"),
            ("CALCULATE(COUNTROWS(t), t[sw] > 5)", "t[sw] > 5", "t[sw] < 15"),
        ):
            ctx_row = _sweep_row("group_own_context", own_dax, (slicer,), g_col)
            ctx_row["own_predicates"] = (own_pred,)
            rows.append(ctx_row)
    for old_agg in ("MIN(t[sdt_old])", "MAX(t[sdt_old])", "COUNT(t[sdt_old])", "COUNTA(t[sdt_old])"):
        rows.append(_sweep_row("date_old", old_agg))  # a date column with cells before 1900: refused by name
    rows.append(_sweep_row("date_old", "CALCULATE(COUNTROWS(t), t[sdt_old] >= DATE(2000,1,1))"))
    rows.append(_sweep_row("date_old", "CALCULATE(SUM(t[sw]), t[sdt_old] < DATE(2026,1,1))"))
    rows.append(_sweep_row("date_old", "COUNTROWS(t)", (), "sdt_old"))
    rows.append(_sweep_row("date_old", "SUM(t[sw])", (), "sdt_old"))
    rows.append(_sweep_row("date_old", "COUNTROWS(t)", (), "scat"))  # a plain group-by on another column stays same
    rows.append(_sweep_row("group", "SUM(t[sw])", ('t[scat] = "A"',), "scat"))  # same-column slicer: refused
    seen: set[str] = set()
    for row in rows:
        if row["id"] in seen:
            raise ValueError(f"duplicate sweep row id {row['id']}")
        seen.add(row["id"])
    return rows


SWEEP_STATUSES = (
    "same", "differs", "refused-whitelist", "refused-planner", "refused-guard",
    "sql-error", "crash",
)
SWEEP_FAILURE_STATUSES = ("differs", "sql-error", "crash")


def _parse_engine_keys(tocsv_text: str, row_count: Any = None) -> list[str]:
    """The distinct keys of a TOCSV(VALUES(col)) result in engine order (a blank line is the blank key).

    A header-only text is either an empty table or a table whose only key is the blank key. The text cannot tell
    them apart: pass row_count (COUNTROWS of the same filtered table, None for blank) to decide. Without
    row_count a header-only text reads as the blank key.
    """
    import io

    head, sep, rest = (tocsv_text or "").partition("\n")
    if not head:
        return []
    if sep and rest == "" and row_count is not None and (row_count == 0):
        return []
    keys: list[str] = []
    seen: set[str] = set()
    found = [record[0] if record else "" for record in csv.reader(io.StringIO(rest, newline=""))]
    if sep and (rest == "" or rest.endswith("\n")):
        found.append("")  # the csv reader drops a last blank record: the blank key shown last
    for key in found:
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def _engine_key_filter(g_col: str, g_type: str, key: str) -> str:
    """The DAX predicate that selects one engine group key."""
    if g_type == "boolean":
        return f"t[{g_col}] = {key}()"
    if key == "":
        return f"t[{g_col}] = BLANK()" if g_type == "date" else f't[{g_col}] = ""'
    if g_type == "date":
        month, day, year = key.split("/")
        return f"t[{g_col}] = DATE({year}, {int(month)}, {int(day)})"
    return f"t[{g_col}] = {_dax_string(key)}"


def _sweep_same(plan_val: Any, engine_val: Any) -> bool:
    return (
        type(plan_val) is type(engine_val)
        and plan_val == engine_val
        and format_report_value(plan_val) == format_report_value(engine_val)
    )


def _sweep_text(value: Any) -> str:
    if isinstance(value, list):
        return ";".join(f"{format_report_value(k)}:{format_report_value(v)}" for k, v in value)
    return format_report_value(value)


def run_sweep(
    rows: int = 300,
    seed: int = 1,
    overrides: dict[str, Any] | None = None,
    row_filter: Any = None,
) -> dict[str, Any]:
    """Literal sweep: every row of build_sweep_catalog against the engine, through plan_measure / plan_group_by.

    Own StudioController and DuckStore on a fresh seeded sweep table. A row is `same` (value, or key list in
    order and every value, equal to the engine's with the same Python class), or a refusal (whitelist, planner,
    guard), or a failure (differs, sql-error, crash). row_filter(row) -> bool limits the rows (tests).
    """
    overrides = overrides or {}
    temp_dir = tempfile.mkdtemp()
    t_path = Path(temp_dir)
    csv_file = t_path / "t.csv"
    t0 = time.time()
    generate_sweep_dataset(csv_file, rows=rows, seed=seed)
    store = DuckStore(str(t_path / "store.db"))
    import_csv_to_store(store, "t_csv", csv_file, {})
    col_meta = column_decimal_meta(store, "t_csv", SWEEP_HEADERS)
    plan_meta: dict[tuple[str, str], ColumnMeta] = {("t", col): m for col, m in col_meta.items()}
    controller = StudioController()
    controller._effective_app_data_dir = lambda: str(t_path / "app_data")
    assert controller._commit_import(csv_file, parse_file(csv_file))
    ctx_model = controller._measure_table_context()
    aid = controller._active_model_table_id()
    tname = controller._active_model_table_name()
    cand_rows = controller._loaded_candidates[controller._active_source_id].rows
    cand_headers = controller._headers
    model_types = controller._project["model"]["tables"][0]["column_types"]
    tables = {"t": model_types}

    def engine(dax: str) -> Any:
        measure = normalize_measure("M", dax, home_table_id=aid)
        return evaluate_measures(
            [measure], cand_rows, cand_headers, tname, measure_names=["M"], table_context=ctx_model,
            relationships=[], filter_table_ids=[], active_table_id=aid,
        )["M"]

    def engine_groups(
        dax: str, g_col: str, g_type: str, ctx: tuple[str, ...], own: tuple[str, ...] = ()
    ) -> list[tuple[str, Any]]:
        keys_dax = f"VALUES(t[{g_col}])"
        if ctx:
            keys_dax = f"CALCULATETABLE({keys_dax}, " + ", ".join(ctx) + ")"
        keys_text = engine(f"TOCSV({keys_dax}, 100000)") or ""
        head_text, line_sep, rest_text = keys_text.partition("\n")
        row_count: Any = None
        if head_text and line_sep and rest_text == "":  # empty table or blank-only key list: COUNTROWS decides
            counted = engine(with_filter_context("COUNTROWS(t)", ctx))
            row_count = 0 if counted is None else counted
        keys = _parse_engine_keys(keys_text, row_count)
        pairs: list[tuple[str, Any]] = []
        for key in keys:
            key_filter = _engine_key_filter(g_col, g_type, key)
            if own:
                # the engine shows a blank value for a group with no row under the own filter; the app drops it
                if not engine(with_filter_context("COUNTROWS(t)", (*own, key_filter, *ctx))):
                    continue
            flat = with_filter_context(dax, (key_filter, *ctx))
            pairs.append((key, engine(flat)))
        return pairs

    max_digits = {col: m.digits for (_, col), m in plan_meta.items()}
    results: list[dict[str, Any]] = []
    for item in build_sweep_catalog(SWEEP_HEADERS):
        if row_filter is not None and not row_filter(item):
            continue
        ctx = tuple(item["filter_context"])
        group = item["group_by"]
        record: dict[str, Any] = {
            "id": item["id"], "shape": item["shape"], "dax": item["dax"], "filter_context": list(ctx),
            "group_by": group[1] if group else None, "status": "crash", "engine_text": "", "plan_text": "",
            "reason": None, "error": None,
        }
        results.append(record)
        try:
            engine_err: str | None = None
            engine_val: Any = None
            try:
                if group:
                    g_type = SWEEP_COLUMN_TYPES.get(group[1], "")
                    engine_val = engine_groups(
                        item["dax"], group[1], g_type, ctx, tuple(item.get("own_predicates", ()))
                    )
                else:
                    engine_val = engine(with_filter_context(item["dax"], ctx))
            except Exception as exc:
                engine_err = str(exc)
            record["engine_text"] = f"ERR:{engine_err[:60]}" if engine_err else _sweep_text(engine_val)
            decision = classify_measure(item["dax"], home_table="t", tables=tables, max_digits=max_digits or None)
            whitelist_ok = decision.allowed
            if whitelist_ok and ctx:
                whitelist_ok = classify_filter_context(
                    ctx, home_table=decision.table or "t", tables=tables, max_digits=max_digits or None
                ).allowed
            kwargs: dict[str, Any] = dict(
                home_table="t", tables=tables, store_tables={"t": "t_csv"}, column_meta=plan_meta,
                overrides=overrides, filter_context=ctx,
            )
            plan = (
                plan_group_by(item["dax"], group_by=group, **kwargs) if group else plan_measure(item["dax"], **kwargs)
            )
            if isinstance(plan, Refusal):
                record["reason"] = str(plan)
                record["status"] = "refused-planner" if whitelist_ok else "refused-whitelist"
                continue
            if not whitelist_ok:
                record["status"] = "differs"
                record["error"] = "whitelist refused but the planner returned SQL"
                continue
            try:
                plan_val = plan.execute(store)
            except StoreError as exc:
                record["status"] = "sql-error"
                record["error"] = str(exc)[:200]
                continue
            if isinstance(plan_val, Refusal):
                record["reason"] = str(plan_val)
                record["status"] = "refused-guard"
                continue
            if overrides.get("forced_wrong_sweep_row") == item["id"]:
                if isinstance(plan_val, list):
                    plan_val = [(k, Decimal("1") if v is None else v + Decimal("0.000001")) for k, v in plan_val]
                else:
                    plan_val = Decimal("1") if plan_val is None else plan_val + Decimal("0.000001")
            record["plan_text"] = _sweep_text(plan_val)
            if engine_err:
                record["status"] = "differs"
                record["error"] = f"engine raised an error but the plan returned a value: {engine_err[:120]}"
            elif isinstance(plan_val, list):
                want = engine_val
                if [k for k, _ in plan_val] != [k for k, _ in want]:
                    record["status"] = "differs"
                    record["error"] = "group keys or key order differ: engine %r vs plan %r" % (
                        [k for k, _ in want][:12], [k for k, _ in plan_val][:12]
                    )
                elif all(_sweep_same(pv, ev) for (_, pv), (_, ev) in zip(plan_val, want)):
                    record["status"] = "same"
                else:
                    record["status"] = "differs"
                    bad = next((k, pv, ev) for (k, pv), (_, ev) in zip(plan_val, want) if not _sweep_same(pv, ev))
                    record["error"] = f"key {bad[0]!r}: engine {format_report_value(bad[2])} vs plan {format_report_value(bad[1])}"
            elif _sweep_same(plan_val, engine_val):
                record["status"] = "same"
            else:
                record["status"] = "differs"
                record["error"] = (
                    f"engine {format_report_value(engine_val)} ({type(engine_val).__name__}) "
                    f"vs plan {format_report_value(plan_val)} ({type(plan_val).__name__})"
                )
        except Exception as exc:  # a planner crash is a failure, never a skip
            record["status"] = "crash"
            record["error"] = f"{type(exc).__name__}: {exc}"
    store.close()
    counts = {status: sum(1 for r in results if r["status"] == status) for status in SWEEP_STATUSES}
    return {
        "rows": rows, "seed": seed, "wall_sec": time.time() - t0, "results": [], "sweep_results": results,
        "sweep_counts": counts, "sweep_only": True,
    }


PERF_PLAN_EXPRESSIONS = [
    ("plan_sum_w", "SUM(t[w])"),
    ("plan_distinctcount_cat_filtered", "CALCULATE(DISTINCTCOUNT(t[cat]), t[w] > 100)"),
]
# Column types of the generated dataset (generate_dataset), as the app's model reports them
PERF_COLUMN_TYPES = {
    "id": "text", "w": "whole_number", "d": "decimal_number", "big": "text", "t": "text",
    "dt": "date", "flag": "boolean", "cat": "text", "w_blank": "text", "num_dups": "decimal_number",
}


def run_perf_benchmark(base_dir: Path, n_rows: int, use_plan: bool = False) -> dict[str, Any]:
    """Measure store query times and memory on generated large CSV and Parquet.

    use_plan also times two measures through plan_measure (planning and execute, seconds in milliseconds).
    """
    import resource

    csv_perf = base_dir / f"perf_{n_rows}.csv"
    pq_perf = base_dir / f"perf_{n_rows}.parquet"
    db_perf = base_dir / f"perf_{n_rows}.db"

    t0 = time.time()
    generate_dataset(csv_perf, pq_perf, rows=n_rows, seed=99)
    st = DuckStore(str(db_perf))
    import_csv_to_store(st, "p_csv", csv_perf, {})
    import_parquet_to_store(st, "p_pq", pq_perf, {})

    queries = [
        ("count_csv", "SELECT COUNT(*) FROM \"p_csv\""),
        ("count_pq", "SELECT COUNT(*) FROM \"p_pq\""),
        ("sum_w_csv", "SELECT SUM(TRY_CAST(NULLIF(w, '') AS HUGEINT)) FROM \"p_csv\""),
        ("sum_w_pq", "SELECT SUM(w) FROM \"p_pq\""),
        ("distinct_t_csv", "SELECT COUNT(DISTINCT t) FROM \"p_csv\""),
        ("distinct_t_pq", "SELECT COUNT(DISTINCT t) FROM \"p_pq\""),
    ]

    timings = {}
    for q_name, q_sql in queries:
        t_start = time.perf_counter()
        st.execute(q_sql)
        timings[q_name] = round((time.perf_counter() - t_start) * 1000, 2)

    if use_plan:
        perf_meta = {("t", c): m for c, m in column_decimal_meta(st, "p_csv", ["d", "w", "big", "num_dups"]).items()}
        for q_name, dax in PERF_PLAN_EXPRESSIONS:
            t_start = time.perf_counter()
            plan = plan_measure(
                dax, home_table="t", tables={"t": PERF_COLUMN_TYPES}, store_tables={"t": "p_csv"}, column_meta=perf_meta
            )
            if isinstance(plan, Refusal):
                raise RuntimeError(f"perf expression refused: {plan}")
            plan.execute(st)
            timings[q_name] = round((time.perf_counter() - t_start) * 1000, 2)

    st.close()
    peak_rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024), 2)
    return {
        "rows": n_rows,
        "timings_ms": timings,
        "peak_rss_mb": peak_rss_mb,
        "setup_sec": round(time.time() - t0, 2),
    }


# ==============================================================================
# SECTION: PREDICATE CHECKERS & CLASSIFICATION (Item 1 & Item 4)
# ==============================================================================

def eval_distinct_numeric_predicate(
    r: dict[str, Any],
    f_item: dict[str, Any],
    store: DuckStore,
    store_meta: dict[str, Any],
    overrides: dict[str, Any] | None = None,
) -> bool:
    """Verify that a mapped difference is the class distinct_numeric_text_variants.

    The class holds only when all three are true:
    1. The formula is DISTINCTCOUNT of the numeric column w or num_dups (read from the catalog entry, not the id).
    2. In the rows the mapped WHERE clause keeps, several different textual forms of the same number occur
       ('1', '1.0', '+1'); the engine counts each form, the mapped SQL counts the number once.
    3. Engine count minus mapped count equals exactly the number of surplus textual forms.
    The rows are chosen with the real mapped WHERE clause (build_where_clause), not a copy of its rules.
    """
    if f_item.get("agg") != "DISTINCTCOUNT" or f_item.get("col") not in ("w", "num_dups"):
        return False
    col = f_item["col"]
    where_clause = build_where_clause(f_item.get("filter_type"), "mapped", False, store_meta, overrides or {}, "DISTINCTCOUNT")
    try:
        extra = f"{col} IS NOT NULL AND {col} <> ''"
        q = f'SELECT {col} FROM "t_csv" {where_clause} {"AND" if where_clause else "WHERE"} {extra}'
        forms_by_number: dict[Decimal, set[str]] = {}
        for (text_val,) in store.execute(q):
            forms_by_number.setdefault(Decimal(str(text_val).strip()), set()).add(str(text_val))
    except Exception:
        return False
    surplus = sum(len(forms) - 1 for forms in forms_by_number.values())
    if surplus <= 0:
        return False
    try:
        return int(r["engine_val"]) - int(r["mapped_val"]) == surplus
    except (ValueError, TypeError):
        return False


def _sig_digits(text: Any) -> int:
    """Count significant digits of a printed number (sign, commas, point and leading zeros ignored)."""
    return len("".join(ch for ch in str(text) if ch.isdigit()).lstrip("0"))


def _pq_decimal(v: float, scale: int) -> Decimal:
    """A Parquet DOUBLE cell as the store reads it: its shortest text form held at the column scale."""
    return Decimal(repr(v)).quantize(Decimal(1).scaleb(-scale))


def _fold_text(v: str | None) -> str:
    """Python mirror of the store fold: rtrim U+0000..U+0020, then ASCII-only lowercase."""
    stripped = (v or "").rstrip("".join(chr(i) for i in range(33)))
    return "".join(chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in stripped)


def _group_label(g_col: str, v: Any) -> str:
    """Group key of one Parquet cell in the label form the engine keys use."""
    if g_col == "t":
        return _fold_text(v)
    if g_col == "dt":
        return "" if v is None else f"{v.month}/{v.day}/{v.year}"
    if g_col == "flag":
        return "TRUE" if v else "FALSE"
    return str(v)


def _pq_group_expected(f_item: dict[str, Any], ctx: dict[str, Any]) -> list[tuple[str, Decimal | None]]:
    """Expected Parquet exact group values of SUM or AVERAGE of d, from the DOUBLE-rounded Parquet cells."""
    g_col = f_item["group_col"]
    scale = ctx["store_meta"]["decimal_scales"].get("d", 4)
    cols = ctx["cols"]
    sums: dict[str, Decimal] = {}
    counts: dict[str, int] = {}
    with localcontext() as lc:
        lc.prec = 80
        for gv, dv in zip(cols[g_col], cols["d"]):
            if dv is None:
                continue
            label = _group_label(g_col, gv)
            sums[label] = sums.get(label, Decimal(0)) + _pq_decimal(dv, scale)
            counts[label] = counts.get(label, 0) + 1
    pairs: list[tuple[str, Decimal | None]] = []
    for key in ctx["group_keys"].get(g_col, []):
        label = _fold_text(key) if g_col == "t" else key
        if f_item["agg"] == "SUM":
            val: Decimal | None = sums.get(label)
        else:
            val = StoreResultLayer.divide(sums.get(label), counts.get(label))
        pairs.append((format_report_value(key), val))
    return pairs


def _pq_scalar_expected(f_item: dict[str, Any], ctx: dict[str, Any]) -> Decimal | None:
    """Expected Parquet value of a scalar over d, from the DOUBLE-rounded Parquet cells of the rows kept by the filter."""
    store_meta = ctx["store_meta"]
    scale = store_meta["decimal_scales"].get("d", 4)
    where_clause = build_where_clause(f_item.get("filter_type"), "mapped", False, store_meta, ctx["overrides"], f_item["agg"])
    ids = [int(row[0]) for row in ctx["store"].execute(f'SELECT CAST(id AS BIGINT) FROM "t_csv" {where_clause}')]
    d_cells = [ctx["cols"]["d"][i - 1] for i in ids]
    cells = [_pq_decimal(v, scale) for v in d_cells if v is not None]
    with localcontext() as lc:
        lc.prec = 80
        total = sum(cells, Decimal(0)) if cells else None
    f_type = f_item.get("filter_type")
    if f_type == "combo_sum":
        w_total = sum(v for v in ctx["cols"]["w"] if v is not None)
        return Decimal(float(Decimal(str(w_total))) + float(Decimal(str(total or 0))))
    if f_type == "ratio":
        return StoreResultLayer.divide_ratio(total, len(cells))
    agg = f_item["agg"]
    if agg == "SUM":
        return total
    if agg == "AVERAGE":
        return StoreResultLayer.divide(total, len(cells))
    if agg == "MIN":
        return min(cells) if cells else None
    return max(cells) if cells else None


def classify_parquet_diff(r: dict[str, Any], f_item: dict[str, Any], ctx: dict[str, Any]) -> str | None:
    """Classify a Parquet versus CSV difference into a named class by its data, or return None.

    parquet_counta_refusal: the Parquet result is exactly the COUNTA refusal and the CSV store answered with a value.
    parquet_source_precision: a SUM, AVERAGE, MIN, MAX or arithmetic over the decimal column d where the CSV exact
    value has more than 15 significant digits and the Parquet value equals the exact result computed here from the
    DOUBLE-rounded Parquet cells (not from the SQL under test).
    """
    agg = f_item["agg"]
    if agg == "COUNTA":
        counta_refusal = f"REFUSED: {PARQUET_COUNTA_REFUSAL_REASON}"
        if r["pq_refusal"] == counta_refusal and r["mapped_refusal"] is None and r["mapped_err"] is None:
            return "parquet_counta_refusal"
        return None
    if r["pq_err"] is not None or r["pq_refusal"] is not None or r["mapped_err"] is not None or r["mapped_refusal"] is not None:
        return None

    if f_item.get("group_col"):
        mapped_exact = r.get("mapped_kv_exact")
        pq_exact = r.get("pq_kv_exact")
        if f_item.get("col") != "d" or agg not in ("SUM", "AVERAGE") or not mapped_exact or not pq_exact:
            return None
        expected = _pq_group_expected(f_item, ctx)
        if len(expected) != len(pq_exact) or len(mapped_exact) != len(pq_exact):
            return None
        for (exp_key, exp_val), (pq_key, pq_val) in zip(expected, pq_exact):
            if exp_key != pq_key or to_exact_decimal(pq_val) != exp_val:
                return None
        differing = [m for m, p in zip(mapped_exact, pq_exact) if to_exact_decimal(m[1]) != to_exact_decimal(p[1])]
        if differing and all(_sig_digits(format(to_exact_decimal(m[1]) or Decimal(0), "f")) > 15 for m in differing):
            return "parquet_source_precision"
        return None

    over_d = f_item.get("col") == "d" and agg in ("SUM", "AVERAGE", "MIN", "MAX")
    if not over_d and f_item.get("filter_type") not in ("combo_sum", "ratio"):
        return None
    if _sig_digits(r["mapped_val"]) <= 15:
        return None
    try:
        parquet_value = None if r["pq_val"] == "None" else Decimal(r["pq_val"])
    except InvalidOperation:
        return None
    if parquet_value == _pq_scalar_expected(f_item, ctx):
        return "parquet_source_precision"
    return None


VM_CHECKLIST = [
    {
        "id": 1,
        "title": "DISTINCTCOUNT on a numeric column with duplicates 1/1.0/1.00/+1",
        "formulas": ["DISTINCTCOUNT_num_dups", "DISTINCTCOUNT_w", "DISTINCTCOUNT_d"],
    },
    {
        "id": 2,
        "title": "Text filter literal with a trailing space",
        "formulas": ["COUNTROWS_t_text_eq_space", "SUM_w_text_eq_space"],
    },
    {
        "id": 3,
        "title": "DISTINCTCOUNTNOBLANK refused on store",
        "formulas": ["DISTINCTCOUNTNOBLANK_t", "DISTINCTCOUNTNOBLANK_w", "DISTINCTCOUNTNOBLANK_d"],
    },
    {
        "id": 4,
        "title": "COUNT of text and boolean refused on store",
        "formulas": ["COUNT_t", "COUNT_flag"],
    },
    {
        "id": 5,
        "title": "MIN/MAX on text refused on store",
        "formulas": ["MIN_t", "MAX_t"],
    },
    {
        "id": 6,
        "title": "Date display and MIN(dt) with blanks",
        "formulas": ["MIN_dt", "MAX_dt"],
    },
    {
        "id": 7,
        "title": "Trailing control characters U+0001-U+001F trimmed at load",
        "formulas": ["DISTINCTCOUNT_t", "COUNTROWS_t_text_eq_tab"],
    },
    {
        "id": 8,
        "title": "ASCII-only fold (Ü/ü distinct, ß vs SS)",
        "formulas": ["COUNTROWS_t_text_uni_upper", "COUNTROWS_t_text_uni_lower", "COUNTROWS_t_text_sharp_s", "COUNTROWS_t_text_ss"],
    },
    {
        "id": 9,
        "title": "AVERAGE precision at 1e14 magnitude",
        "formulas": ["AVERAGE_d", "AVERAGE_w", "AVERAGE_d_cat_eq"],
    },
    {
        "id": 10,
        "title": "SUM(w) + SUM(d) exactness and arithmetic iterators",
        "formulas": ["arith_sum_d_plus_sum_w", "arith_sum_w_plus", "arith_sum_d_div_count", "arith_avg_minus_min"],
    },
    {
        "id": 11,
        "title": "DIVIDE by zero BLANK vs Infinity in an iterator",
        "formulas": ["arith_divide_zero", "arith_sumx_divide_zero", "arith_sumx_slash_zero"],
    },
    {
        "id": 12,
        "title": "Numeric comparisons treat blank as 0 (< n, <= n, <> n, = 0)",
        "formulas": ["COUNTROWS_t_w_lt", "COUNTROWS_t_w_lte", "COUNTROWS_t_w_zero", "COUNTROWS_t_w_neq"],
    },
    {
        "id": 13,
        "title": "COUNTA on a numeric column with blank CSV cells counts all rows",
        "formulas": ["COUNTA_w", "COUNTA_d", "COUNTA_t"],
    },
    {
        "id": 14,
        "title": "COUNT vs COUNTA on blanks",
        "formulas": ["COUNT_w", "COUNTA_w"],
    },
    {
        "id": 15,
        "title": "DISTINCTCOUNT blank (+1 when blank exists)",
        "formulas": ["DISTINCTCOUNT_w", "DISTINCTCOUNT_t"],
    },
    {
        "id": 16,
        "title": "Empty-set BLANK and AVERAGE of blanks",
        "formulas": ["COUNTROWS_t_empty_set", "SUM_w_empty_set", "AVERAGE_w_all_blank_filter"],
    },
    {
        "id": 17,
        "title": "Date comparisons with blank date: dt <= D and dt <> D include blank",
        "formulas": ["COUNTROWS_t_dt_lte", "COUNTROWS_t_dt_lt", "COUNTROWS_t_dt_neq", "COUNTROWS_t_dt_range", "COUNTROWS_t_dt_gt"],
    },
    {
        "id": 18,
        "title": "IN and && filters on numeric and date columns (engine error, refused on store)",
        "formulas": ["COUNTROWS_t_w_in", "COUNTROWS_t_filter_two_cols", "COUNTROWS_t_dt_in"],
    },
    {
        "id": 19,
        "title": "Group-by blank key preservation and VertiPaq dictionary ordering",
        "formulas": ["group_by_cat_SUM_w", "group_by_t_COUNTROWS_all", "group_by_dt_MIN_dt", "group_by_flag_SUM_w"],
    },
    {
        "id": 20,
        "title": "All-blank numeric column (model type text, refused on store)",
        "formulas": ["SUM_w_blank", "AVERAGE_w_blank"],
    },
    {
        "id": 21,
        "title": "DISTINCTCOUNT of 1, 1.0, +1, -0 and 0 in a numeric column: one value or several?",
        "formulas": ["DISTINCTCOUNT_num_dups", "DISTINCTCOUNT_w"],
    },
    {
        "id": 22,
        "title": "IN filter on a date column with blank cells raises engine error (refused on store)",
        "formulas": ["COUNTROWS_t_dt_in"],
    },
    {
        "id": 23,
        "title": "Parquet DOUBLE sums at 1e14 magnitude reflect floating-point rounding vs CSV DECIMAL",
        "formulas": ["SUM_d", "AVERAGE_d"],
    },
]


def generate_sweep_markdown(data: dict[str, Any]) -> str:
    """The "Literal sweep" section: counts per status, the refusal reasons and every failure."""
    sweep = data["sweep_results"]
    lines = ["## Literal sweep", ""]
    lines.append(f"- Rows: {len(sweep)} (table rows {data.get('rows')}, seed {data.get('seed')})")
    for status in SWEEP_STATUSES:
        lines.append(f"- {status}: {sum(1 for r in sweep if r['status'] == status)}")
    reasons: dict[str, int] = {}
    for r in sweep:
        if r["status"].startswith("refused"):
            reasons[str(r.get("reason"))] = reasons.get(str(r.get("reason")), 0) + 1
    if reasons:
        lines.append("")
        lines.append("### Refusal reasons")
        lines.append("")
        for reason, n in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"- {n} x {reason}")
    failures = [r for r in sweep if r["status"] in SWEEP_FAILURE_STATUSES]
    if failures:
        lines.append("")
        lines.append("### Failures")
        lines.append("")
        for r in failures:
            lines.append(f"- `{r['id']}`: {r['status']}: {r.get('error')}")
    lines.append("")
    return "\n".join(lines)


def generate_markdown_report(data: dict[str, Any]) -> str:
    """Format comparison results into markdown report with dynamically generated rules table and VM checklist."""
    results = data["results"]
    total = len(results)

    status_counts_naive: dict[str, int] = {}
    status_counts_mapped: dict[str, int] = {}
    refused_shapes: dict[str, int] = {}
    refused_reasons: dict[str, int] = {}

    for r in results:
        s_naive = r["naive_status"]
        s_mapped = r["mapped_status"]
        status_counts_naive[s_naive] = status_counts_naive.get(s_naive, 0) + 1
        status_counts_mapped[s_mapped] = status_counts_mapped.get(s_mapped, 0) + 1
        if r.get("mapped_refusal"):
            refused_shapes[r["shape"]] = refused_shapes.get(r["shape"], 0) + 1
            reason = str(r["mapped_refusal"])
            refused_reasons[reason] = refused_reasons.get(reason, 0) + 1

    differs_mapped = [r for r in results if r["mapped_status"] == "differs"]
    sql_errors_mapped = [r for r in results if r["mapped_status"] == "sql-error"]
    refusal_mismatches = [r for r in results if r["mapped_status"] == "refusal-reason-mismatch"]

    lines: list[str] = []
    lines.append("# Engine versus DuckStore Rules Table Report")
    lines.append("")
    lines.append(f"- **Evaluated rows:** {data['rows']}")
    lines.append(f"- **Seed:** {data['seed']}")
    lines.append(f"- **Total formulas:** {total}")
    lines.append(f"- **Execution wall time:** {data['wall_sec']:.2f} s")
    lines.append("")
    lines.append("## Headline Summary")
    lines.append("")
    lines.append("| Status | Naive SQL | Mapped SQL |")
    lines.append("|---|---|---|")
    # Headline refused count = every formula that carries an explicit Refusal; the breakdowns below sum to it
    total_refusals = sum(refused_reasons.values())
    refused_with_engine_value = status_counts_mapped.get("refused", 0)
    matching_error_refusals = total_refusals - refused_with_engine_value
    headline_mapped_same = status_counts_mapped.get("same", 0) - matching_error_refusals

    all_statuses = ["same", "differs", "refused", "sql-error", "refusal-reason-mismatch", "engine-error", "both-error"]
    for s in all_statuses:
        if s == "refused":
            m_cnt = total_refusals
        elif s == "same":
            m_cnt = headline_mapped_same
        else:
            m_cnt = status_counts_mapped.get(s, 0)
        lines.append(f"| {s} | {status_counts_naive.get(s, 0)} | {m_cnt} |")
    lines.append("")
    lines.append(f"- **Same:** {status_counts_mapped.get('same', 0)}")
    lines.append(f"- **Differs:** {status_counts_mapped.get('differs', 0)}")
    lines.append(
        f"- **Refused:** {total_refusals} "
        f"({refused_with_engine_value} where the engine returns a value and the store refuses, "
        f"{matching_error_refusals} where the engine raises an error and the refusal text matches it)"
    )
    if refused_shapes:
        lines.append(f"  - Refused shapes breakdown: {dict(sorted(refused_shapes.items()))}")
        lines.append("  - Refused by reason:")
        for reason, count in sorted(refused_reasons.items()):
            lines.append(f"    - {reason}: {count}")
    lines.append(f"- **SQL Errors (failures):** {len(sql_errors_mapped)}")
    if refusal_mismatches:
        lines.append(f"- **Refusal Reason Mismatches (failures):** {len(refusal_mismatches)}")
    lines.append("")

    if differs_mapped:
        lines.append("### Remaining Mapped Differences")
        for d in differs_mapped:
            e_disp = "(blank)" if d["engine_text"] == "" else d["engine_text"]
            m_disp = "(blank)" if d["mapped_text"] == "" else d["mapped_text"]
            reason_note = f" [Reason: {d['mapped_status_reason']}]" if d.get("mapped_status_reason") else ""
            cls_note = f" [Class: {d.get('mapped_diff_class')}]" if d.get('mapped_diff_class') else " [UNCLASSIFIED]"
            lines.append(f"- `{d['id']}` ({d['dax']}): Engine='{e_disp}' vs Mapped='{m_disp}'{reason_note}{cls_note}")
        lines.append("")

    if sql_errors_mapped:
        lines.append("### Mapped SQL Errors")
        for err in sql_errors_mapped:
            lines.append(f"- `{err['id']}` ({err['dax']}): {err['mapped_err']}")
        lines.append("")

    if refusal_mismatches:
        lines.append("### Refusal Reason Mismatches")
        for r_m in refusal_mismatches:
            lines.append(f"- `{r_m['id']}` ({r_m['dax']}): expected '{r_m['mapped_refusal_obj'].expected_error}' in engine err '{r_m['engine_err']}'")
        lines.append("")

    # Dynamically generate rules table grouped by shape with one data-derived rule sentence per shape
    shapes_map: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        shapes_map.setdefault(r["shape"], []).append(r)

    lines.append("## Rules Table Grouped by Shape")
    lines.append("")
    lines.append("| Shape | Total | Same | Differs | Refused | SQL Error | Data-Derived Engine Rule |")
    lines.append("|---|---|---|---|---|---|---|")

    rule_sentences = {
        "SUM": "Sums numeric columns exactly using HUGEINT or DECIMAL(38,s); refuses non-numeric columns.",
        "AVERAGE": "Computes exact sum divided by count in Python Decimal context; returns BLANK if all cells are blank.",
        "MIN": "Returns minimum numeric value or date formatted as m/d/yyyy; refuses text columns.",
        "MAX": "Returns maximum numeric value or date formatted as m/d/yyyy; refuses text columns.",
        "COUNT": "Counts non-blank numeric and date cells; refuses boolean and text columns on store.",
        "COUNTA": "Counts all cells present in store representation on CSV (including empty string); refused on Parquet.",
        "COUNTROWS": "Counts rows matching filter context; returns BLANK when filter context matches 0 rows.",
        "COUNTBLANK": "Counts cells where value is blank or empty string; returns BLANK when count is 0.",
        "DISTINCTCOUNT": (
            "Text: distinct values after ASCII folding. Numeric columns: the engine counts distinct textual forms of "
            "the cells ('1', '1.0', '+1' are three values) while the mapped store counts distinct numbers (one value). "
            "Blank counts as one more value when any blank cell exists."
        ),
        "DISTINCTCOUNTNOBLANK": "Refused on store because engine counts empty string as a distinct value.",
        "SUM_filtered": "Evaluates SUM under filter predicate with decimal scales keyed by filtered column.",
        "AVERAGE_filtered": "Evaluates exact sum/count under filter predicate; returns BLANK on empty filter sets.",
        "MIN_filtered": "Evaluates MIN under filter predicate; returns BLANK on empty filter sets.",
        "MAX_filtered": "Evaluates MAX under filter predicate; returns BLANK on empty filter sets.",
        "COUNT_filtered": "Evaluates COUNT of numeric/date columns under filter predicate; returns BLANK on empty sets.",
        "COUNTA_filtered": "Evaluates COUNTA under filter predicate; returns BLANK on empty sets.",
        "COUNTROWS_filtered": "Counts rows matching compound or single filter predicates; blank date is matched by <=, <, <>.",
        "COUNTBLANK_filtered": "Counts blanks under filter predicate; returns BLANK on empty sets.",
        "DISTINCTCOUNT_filtered": (
            "Counts distinct values under a filter predicate with the same textual-form rule for numeric columns "
            "(engine counts forms, mapped counts numbers); returns BLANK on empty sets."
        ),
        "group_by_SUM": "Aggregates SUM grouped by column, matching VertiPaq dictionary key order and formatting each group value.",
        "group_by_AVERAGE": "Aggregates AVERAGE grouped by column, dividing sum by count exactly in Decimal result layer.",
        "group_by_MIN": "Aggregates MIN grouped by column, returning formatted dates or values per group.",
        "group_by_COUNTROWS": "Counts rows per group, preserving blank key group and VertiPaq order.",
        "group_by_DISTINCTCOUNT": "Counts distinct keys per group, preserving blank key group and VertiPaq order.",
        "RATIO": "Evaluates quotient of two aggregate leaves in Python Decimal result layer.",
        "DIVIDE": "Evaluates safe division, returning BLANK on division by zero.",
        "ARITH": "Evaluates arithmetic difference of two aggregate leaves in Python Decimal result layer.",
        "SUMX": "Evaluates row iterator arithmetic, returning Infinity on division by zero.",
    }

    for shape, items in sorted(shapes_map.items()):
        cnt_same = sum(1 for x in items if x["mapped_status"] == "same")
        cnt_diff = sum(1 for x in items if x["mapped_status"] == "differs")
        cnt_ref = sum(1 for x in items if x["mapped_status"] == "refused")
        cnt_err = sum(1 for x in items if x["mapped_status"] == "sql-error")
        rule_desc = rule_sentences.get(shape, "Evaluates DAX expression against DuckStore representation.")

        lines.append(f"| `{shape}` | {len(items)} | {cnt_same} | {cnt_diff} | {cnt_ref} | {cnt_err} | {rule_desc} |")

    lines.append("")

    # Data-derived VM Check List
    lines.append("## VM Check List")
    lines.append("")
    result_by_id = {r["id"]: r for r in results}
    for item in VM_CHECKLIST:
        lines.append(f"### {item['id']}. {item['title']}")
        lines.append("- **Exercised Formulas (Data-Derived):**")
        for fid in item["formulas"]:
            if fid in result_by_id:
                r = result_by_id[fid]
                e_disp = "(blank)" if r["engine_text"] == "" else r["engine_text"]
                m_disp = "(blank)" if r["mapped_text"] == "" else r["mapped_text"]
                lines.append(f"  - `{fid}` (`{r['dax']}`) -> status: **{r['mapped_status']}** (Engine='{e_disp}', Mapped='{m_disp}')")
            else:
                lines.append(f"  - `{fid}` (not in active catalog)")
        lines.append("")

    # Parquet Path Comparison
    lines.append("## Parquet Path Comparison")
    lines.append("")
    pq_diffs = [r for r in results if r["pq_vs_csv_diff"]]
    lines.append(f"- Parquet-typed store vs CSV store differences: {len(pq_diffs)}")
    pq_classes: dict[str, int] = {}
    for p in pq_diffs:
        c_name = p.get("pq_diff_class") or "unclassified"
        pq_classes[c_name] = pq_classes.get(c_name, 0) + 1
    lines.append(f"- Parquet differences by class: {dict(pq_classes)}")
    if pq_diffs:
        lines.append("- Sample differences:")
        for p in pq_diffs[:10]:
            lines.append(f"  - `{p['id']}` [{p.get('pq_diff_class')}]: CSV='{p['mapped_text']}' vs PQ='{p['pq_text']}'")
    lines.append("")

    if any("plan_status" in r for r in results):
        counts = plan_counts(results)
        lines.append("## Plan (Rule A+)")
        lines.append("")
        lines.append(f"- Whitelist allowed: {counts['allowed']}")
        lines.append(f"- Whitelist refused: {counts['refused']}")
        lines.append(f"- Plan same as engine: {counts['plan-same']}")
        lines.append(f"- Plan differs: {counts['plan-differs']}")
        lines.append(f"- Plan refused where the whitelist refused: {counts['plan-refused']}")
        lines.append(f"- Plan refused where the whitelist allowed: {counts['plan-refused-allowed']}")
        lines.append(f"- Plan SQL errors: {counts['plan-sql-error']}")
        lines.append(f"- Plan crashes: {counts['plan-crash']}")
        lines.append(f"- Skipped (group-by): {counts['plan-skipped']}")
        for r in results:
            if r.get("plan_status") in PLAN_FAILURE_STATUSES:
                lines.append(f"  - `{r['id']}` ({r['dax']}): {r['plan_status']}: {r.get('plan_error')}")
        lines.append("")

    if data.get("perf"):
        lines.append("## Performance Benchmarks")
        lines.append("")
        perf = data["perf"]
        lines.append(f"- **Benchmark rows:** {perf['rows']:,}")
        lines.append(f"- **Peak RSS:** {perf['peak_rss_mb']} MB")
        lines.append("- **Query Timings (ms):**")
        for q_name, ms in perf["timings_ms"].items():
            lines.append(f"  - `{q_name}`: {ms:.2f} ms")
        lines.append("")

    return "\n".join(lines)


# ==============================================================================
# SECTION: EXIT POLICY, MAIN CLI & BASELINE
# ==============================================================================

def evaluate_sweep_policy(sweep_results: list[dict[str, Any]], baseline: dict[str, Any]) -> tuple[int, list[str]]:
    """Exit policy of the literal sweep: any difference, SQL error or crash exits 1, and the set of refused rows
    (whitelist, planner or guard) must equal the baseline list `sweep_refused` (row ids are built from content,
    never from a seed)."""
    failures = [r for r in sweep_results if r["status"] in SWEEP_FAILURE_STATUSES]
    if failures:
        by_status = {st: sum(1 for r in failures if r["status"] == st) for st in SWEEP_FAILURE_STATUSES}
        first = [f"{r['id']}: {r.get('error')}" for r in failures[:5]]
        return 1, [f"FAILURE: sweep failures {by_status}: {first}"]
    expected = set(baseline.get("sweep_refused", []))
    actual = {r["id"] for r in sweep_results if r["status"].startswith("refused")}
    if actual != expected:
        changed = sorted(actual.symmetric_difference(expected))
        return 1, [f"FAILURE: sweep refused set changed vs baseline ({len(changed)} rows): {changed[:5]}"]
    return 0, []


def evaluate_exit_policy(data: dict[str, Any], baseline: dict[str, Any]) -> tuple[int, list[str]]:
    """Exit policy of the tool: returns (exit code, failure messages).

    Exit 1 on: any mapped SQL error, any refusal whose reason does not match the engine error, any mapped difference
    without a class listed in the baseline, any Parquet difference without a class listed in the baseline, and (when
    the baseline has a "refused" list, even an empty one) any change of the set of refused formulas.
    """
    results = data["results"]

    if "sweep_results" in data:
        sweep_code, sweep_messages = evaluate_sweep_policy(data["sweep_results"], baseline)
        if sweep_code or data.get("sweep_only"):
            return sweep_code, sweep_messages

    plan_refusals_allowed = set(baseline.get("plan_refusals_allowed", []))
    plan_failures = [
        r["id"] for r in results
        if r.get("plan_status") in PLAN_FAILURE_STATUSES
        or (r.get("plan_status") == "plan-refused-allowed" and r["id"] not in plan_refusals_allowed)
    ]
    if plan_failures:
        by_class = {c: sum(1 for r in results if r.get("plan_status") == c) for c in PLAN_FAILURE_STATUSES}
        by_class["plan-refused-allowed"] = sum(
            1 for r in results if r.get("plan_status") == "plan-refused-allowed" and r["id"] not in plan_refusals_allowed
        )
        return 1, [f"FAILURE: plan (Rule A+) failures {by_class}: {plan_failures}"]

    sql_errors = sum(1 for r in results if r["mapped_status"] == "sql-error")
    if sql_errors > 0:
        return 1, [f"FAILURE: {sql_errors} SQL errors encountered."]

    refusal_mismatches = sum(1 for r in results if r["mapped_status"] == "refusal-reason-mismatch")
    if refusal_mismatches > 0:
        return 1, [f"FAILURE: {refusal_mismatches} refusal reason mismatches encountered."]

    expected_classes = set(baseline.get("classes", []))
    expected_refusals = baseline.get("refused")
    if expected_refusals is None and "refused" in baseline.get("sizes", {}).get(str(data["rows"]), {}):
        expected_refusals = baseline["sizes"][str(data["rows"])]["refused"]

    unclassified_diffs = [
        r["id"] for r in results
        if r["mapped_status"] == "differs" and r.get("mapped_diff_class") not in expected_classes
    ]
    if unclassified_diffs:
        return 1, [f"FAILURE: {len(unclassified_diffs)} un-baselined differences: {unclassified_diffs}"]

    unclassified_pq = [
        r["id"] for r in results
        if r["pq_vs_csv_diff"] and r.get("pq_diff_class") not in expected_classes
    ]
    if unclassified_pq:
        return 1, [f"FAILURE: {len(unclassified_pq)} unclassified Parquet differences: {unclassified_pq}"]

    if expected_refusals is not None:
        actual_refusals = {r["id"] for r in results if r.get("mapped_refusal")}
        if actual_refusals != set(expected_refusals):
            diff_ref = actual_refusals.symmetric_difference(set(expected_refusals))
            return 1, [f"FAILURE: Refused formula set changed vs baseline: {diff_ref}"]
    return 0, []


def main() -> None:
    parser = argparse.ArgumentParser(description="Engine versus DuckStore rules diff tool.")
    parser.add_argument(
        "--rows", type=int, default=None, help="Row count for generated data (default: 2000, 300 with --sweep)"
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("--out", type=str, default="", help="Output markdown file path")
    parser.add_argument("--json", type=str, default="", help="Output JSON file path")
    parser.add_argument("--perf-rows", type=int, default=0, help="Measure query times on N rows (default: 0)")
    parser.add_argument("--baseline", type=str, default="", help="Path to baseline JSON file")
    parser.add_argument("--plan", action="store_true", help="Also evaluate every formula through plan_measure (Rule A+)")
    parser.add_argument(
        "--sweep", action="store_true", help="Run the literal sweep (plan_measure / plan_group_by) instead of the catalog run"
    )

    args = parser.parse_args()

    try:
        if args.sweep:
            data = run_sweep(rows=args.rows or 300, seed=args.seed)
        else:
            data = run_comparison(rows=args.rows or 2000, seed=args.seed, perf_rows=args.perf_rows, use_plan=args.plan)
    except Exception as exc:
        print(f"TOOL CRASH: {exc}", file=sys.stderr)
        sys.exit(2)

    md_content = generate_sweep_markdown(data) if data.get("sweep_only") else generate_markdown_report(data)
    if not data.get("sweep_only") and "sweep_results" in data:
        md_content += "\n" + generate_sweep_markdown(data)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md_content)
    else:
        print(md_content)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    baseline_path = Path(args.baseline) if args.baseline else Path(__file__).parent / "store_engine_diff_baseline.json"
    try:
        with open(baseline_path, "r", encoding="utf-8") as bf:
            baseline_data = json.load(bf)
    except (OSError, ValueError) as exc:
        print(f"FAILURE: Error reading baseline {baseline_path.name}: {exc}", file=sys.stderr)
        sys.exit(1)

    code, messages = evaluate_exit_policy(data, baseline_data)
    if args.sweep:
        print("Sweep counts: " + ", ".join(f"{k}={v}" for k, v in data["sweep_counts"].items()), file=sys.stderr)
    elif args.plan:
        counts = plan_counts(data["results"])
        print("Plan (Rule A+) counts: " + ", ".join(f"{k}={v}" for k, v in counts.items()), file=sys.stderr)
    for message in messages:
        print(message, file=sys.stderr)
    sys.exit(code)


if __name__ == "__main__":
    main()
