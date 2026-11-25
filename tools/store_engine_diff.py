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


# The one Parquet refusal that the Parquet difference class parquet_counta_refusal accepts
PARQUET_COUNTA_REFUSAL_REASON = "COUNTA on Parquet typed columns differs from CSV store"

# Safe SQL expression for the 33 characters U+0000..U+0020
TRIM_CHARS_SQL = " || ".join(f"chr({i})" for i in range(33))


class Refusal:
    """Explicit refusal object representing an intentionally unsupported shape."""

    def __init__(self, reason: str, expected_error: str | None = None):
        self.reason = reason
        self.expected_error = expected_error

    def __repr__(self) -> str:
        return f"Refusal({self.reason!r}, expected_error={self.expected_error!r})"

    def __str__(self) -> str:
        return f"REFUSED: {self.reason}"


def refusal_matches_engine_error(refusal: Refusal, engine_err: str) -> bool:
    """A refusal that stands for an engine error must name that error: no expected text, or text not in the error, fails."""
    return bool(refusal.expected_error) and refusal.expected_error in engine_err


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
# SECTION: RESULT LAYER (Aggregates from SQL, Arithmetic via Decimal layer)
# ==============================================================================

class StoreResultLayer:
    """Prototypes the app's execution layer: aggregate leaves from SQL, exact Decimal arithmetic."""

    @staticmethod
    def divide(sum_val: Any, cnt_val: Any) -> Decimal | None:
        if sum_val is None or cnt_val is None or cnt_val == 0:
            return None
        return Decimal(str(sum_val)) / Decimal(str(cnt_val))

    @staticmethod
    def divide_ratio(sum_val: Any, cnt_val: Any) -> Decimal | None:
        if sum_val is None or cnt_val is None or cnt_val == 0:
            return None
        # In DAX, binary `/` between measures evaluates in IEEE 754 float
        f_val = float(sum_val) / float(cnt_val)
        return Decimal(str(f_val))

    @staticmethod
    def add(a: Any, b: Any) -> Decimal | None:
        if a is None and b is None:
            return None
        dec_a = Decimal(0) if a is None else Decimal(str(a))
        dec_b = Decimal(0) if b is None else Decimal(str(b))
        return dec_a + dec_b

    @staticmethod
    def subtract(a: Any, b: Any) -> Decimal | None:
        if a is None and b is None:
            return None
        dec_a = Decimal(0) if a is None else Decimal(str(a))
        dec_b = Decimal(0) if b is None else Decimal(str(b))
        return dec_a - dec_b


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

    return catalog


# ==============================================================================
# SECTION: SQL GENERATOR & REFUSAL LOGIC
# ==============================================================================

def make_fold_expr(c: str, agg: str | None, overrides: dict[str, Any]) -> str:
    """SQL fold for text comparison: rtrim U+0000..U+0020 then ASCII-only lowercase."""
    if overrides.get("drop_distinct_fold") and agg in ("DISTINCTCOUNT", "DISTINCTCOUNTNOBLANK"):
        return c
    if overrides.get("trim_set_space_only"):
        trim_arg = "' \\t\\r\\n'"
    else:
        trim_arg = TRIM_CHARS_SQL
    if overrides.get("drop_rtrim"):
        return f"translate(COALESCE({c}, ''), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')"
    return f"translate(rtrim(COALESCE({c}, ''), {trim_arg}), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')"


def build_where_clause(
    f_type: str | None,
    mode: str,
    is_parquet: bool,
    store_meta: dict[str, Any] | None,
    overrides: dict[str, Any] | None,
    agg: str | None = None,
) -> str:
    """Build the WHERE clause of one filter shape; the single source used by the mapped SQL and the class predicates."""
    overrides = overrides or {}
    fold_t = make_fold_expr("t", agg, overrides)

    # Filtered decimal column scale (C1): the scale of column d itself, never the aggregated column
    filter_d_scale = 4 if overrides.get("hardcode_scale_4") else (store_meta or {}).get("decimal_scales", {}).get("d", 4)

    where_clause = ""
    if f_type:
        cast_w = "w" if is_parquet else "TRY_CAST(NULLIF(w, '') AS HUGEINT)"
        cast_d_filter = (
            f"CAST(d AS DECIMAL(38, {filter_d_scale}))"
            if is_parquet
            else f"TRY_CAST(NULLIF(d, '') AS DECIMAL(38, {filter_d_scale}))"
        )
        cast_dt = "TRY_CAST(dt AS DATE)" if is_parquet else "TRY_CAST(NULLIF(dt, '') AS DATE)"

        if overrides.get("drop_w_zero_coalesce"):
            w_zero_cond = f"{cast_w} = 0"
        else:
            w_zero_cond = f"COALESCE({cast_w}, 0) = 0"

        if overrides.get("drop_w_lt_coalesce"):
            w_lt_cond = f"{cast_w} < 100"
        else:
            w_lt_cond = f"COALESCE({cast_w}, 0) < 100"

        if overrides.get("drop_w_lte_coalesce"):
            w_lte_cond = f"{cast_w} <= 100"
        else:
            w_lte_cond = f"COALESCE({cast_w}, 0) <= 100"

        if overrides.get("drop_w_neq_coalesce"):
            w_neq_cond = f"{cast_w} <> 100"
        else:
            w_neq_cond = f"COALESCE({cast_w}, 0) <> 100"

        if overrides.get("drop_d_gte_coalesce"):
            d_gte_cond = f"{cast_d_filter} >= 0"
        else:
            d_gte_cond = f"COALESCE({cast_d_filter}, 0) >= 0"

        if f_type == "cat_eq":
            where_clause = "WHERE cat = 'A'"
        elif f_type == "cat_eq_other":
            where_clause = "WHERE cat = 'B'"
        elif f_type == "text_eq_lower":
            where_clause = "WHERE t = 'east'" if mode == "naive" else f"WHERE {fold_t} = 'east'"
        elif f_type == "text_eq_upper":
            where_clause = "WHERE t = 'EAST'" if mode == "naive" else f"WHERE {fold_t} = 'east'"
        elif f_type == "text_eq_space":
            if overrides.get("hardcode_text_space_false"):
                where_clause = "WHERE 1 = 0"
            else:
                where_clause = "WHERE t = 'west '" if mode == "naive" else f"WHERE {fold_t} = 'west '"
        elif f_type == "text_eq_tab":
            where_clause = "WHERE t = 'west\t'" if mode == "naive" else f"WHERE {fold_t} = 'west\t'"
        elif f_type == "text_eq_untrimmed":
            where_clause = "WHERE t = 'west'" if mode == "naive" else f"WHERE {fold_t} = 'west'"
        elif f_type == "text_uni_upper":
            where_clause = "WHERE t = 'Ünï'" if mode == "naive" else f"WHERE {fold_t} = 'Ünï'"
        elif f_type == "text_uni_lower":
            where_clause = "WHERE t = 'ünï'" if mode == "naive" else f"WHERE {fold_t} = 'ünï'"
        elif f_type == "text_sharp_s":
            where_clause = "WHERE t = 'ß'" if mode == "naive" else f"WHERE {fold_t} = 'ß'"
        elif f_type == "text_ss":
            where_clause = "WHERE t = 'SS'" if mode == "naive" else f"WHERE {fold_t} = 'ss'"
        elif f_type == "w_zero":
            where_clause = "WHERE TRY_CAST(w AS DOUBLE) = 0" if mode == "naive" else f"WHERE {w_zero_cond}"
        elif f_type == "w_lt":
            where_clause = "WHERE TRY_CAST(w AS DOUBLE) < 100" if mode == "naive" else f"WHERE {w_lt_cond}"
        elif f_type == "w_lte":
            where_clause = "WHERE TRY_CAST(w AS DOUBLE) <= 100" if mode == "naive" else f"WHERE {w_lte_cond}"
        elif f_type == "w_gt":
            where_clause = "WHERE TRY_CAST(w AS DOUBLE) > 100" if mode == "naive" else f"WHERE {cast_w} > 100"
        elif f_type == "w_gte":
            if overrides.get("m15_num_gte_to_gt"):
                where_clause = "WHERE TRY_CAST(w AS DOUBLE) >= 100" if mode == "naive" else f"WHERE {cast_w} > 100"
            else:
                where_clause = "WHERE TRY_CAST(w AS DOUBLE) >= 100" if mode == "naive" else f"WHERE {cast_w} >= 100"
        elif f_type == "w_neq":
            where_clause = "WHERE TRY_CAST(w AS DOUBLE) <> 100" if mode == "naive" else f"WHERE {w_neq_cond}"
        elif f_type == "w_not":
            where_clause = "WHERE NOT(TRY_CAST(w AS DOUBLE) = 100)" if mode == "naive" else f"WHERE {w_neq_cond}"
        elif f_type == "w_or":
            where_clause = "WHERE TRY_CAST(w AS DOUBLE) = 100 OR TRY_CAST(w AS DOUBLE) = 200" if mode == "naive" else f"WHERE COALESCE({cast_w}, 0) = 100 OR COALESCE({cast_w}, 0) = 200"
        elif f_type == "w_in":
            where_clause = "WHERE TRY_CAST(w AS DOUBLE) IN (100, 200)" if mode == "naive" else f"WHERE COALESCE({cast_w}, 0) IN (100, 200)"
        elif f_type == "d_gte":
            where_clause = "WHERE TRY_CAST(d AS DOUBLE) >= 0" if mode == "naive" else f"WHERE {d_gte_cond}"
        elif f_type == "d_lt":
            where_clause = "WHERE TRY_CAST(d AS DOUBLE) < 0" if mode == "naive" else f"WHERE {cast_d_filter} < 0"
        elif f_type == "d_neq":
            where_clause = "WHERE TRY_CAST(d AS DOUBLE) <> 0" if mode == "naive" else f"WHERE COALESCE({cast_d_filter}, 0) <> 0"
        elif f_type == "dt_range":
            if overrides.get("m15_date_gte_to_gt"):
                where_clause = "WHERE dt >= '2026-06-01'" if mode == "naive" else f"WHERE {cast_dt} > DATE '2026-06-01'"
            else:
                where_clause = "WHERE dt >= '2026-06-01'" if mode == "naive" else f"WHERE {cast_dt} >= DATE '2026-06-01'"
        elif f_type == "dt_gt":
            where_clause = "WHERE dt > '2026-06-01'" if mode == "naive" else f"WHERE {cast_dt} > DATE '2026-06-01'"
        elif f_type == "dt_lte":
            # Item A1: dt <= D includes blank dates (epoch DATE '1899-12-30')
            where_clause = "WHERE dt <= '2026-06-01'" if mode == "naive" else f"WHERE COALESCE({cast_dt}, DATE '1899-12-30') <= DATE '2026-06-01'"
        elif f_type == "dt_lt":
            # Item A1: dt < D includes blank dates (epoch DATE '1899-12-30')
            where_clause = "WHERE dt < '2026-06-01'" if mode == "naive" else f"WHERE COALESCE({cast_dt}, DATE '1899-12-30') < DATE '2026-06-01'"
        elif f_type == "dt_neq":
            # Item A1: dt <> D includes blank dates (epoch DATE '1899-12-30')
            where_clause = "WHERE dt <> '2026-06-01'" if mode == "naive" else f"WHERE COALESCE({cast_dt}, DATE '1899-12-30') <> DATE '2026-06-01'"
        elif f_type == "dt_in":
            where_clause = "WHERE dt IN ('2026-06-01', '2026-07-01')"
        elif f_type == "cat_in":
            where_clause = "WHERE cat IN ('A', 'B')"
        elif f_type == "empty_set":
            where_clause = "WHERE id = '-999'"
        elif f_type == "two_filters_w":
            where_clause = f"WHERE {cast_w} > 5 AND {cast_w} < 15"
        elif f_type == "filter_two_cols":
            where_clause = f"WHERE {cast_w} > 5 AND cat = 'A'"
        elif f_type == "all_blank_filter":
            where_clause = f"WHERE {cast_w} = 999999"

    return where_clause


def generate_sql(
    formula: dict[str, Any],
    table_name: str,
    column_types: dict[str, str],
    mode: str = "naive",
    is_parquet: bool = False,
    store_meta: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
) -> str | Refusal | None:
    """Generate SQL query or explicit Refusal for naive or mapped mode."""
    overrides = overrides or {}
    t_q = f'"{table_name}"'
    agg = formula["agg"]
    col = formula.get("col")
    f_type = formula.get("filter_type")
    group_col = formula.get("group_col")
    c_type = column_types.get(col, "text") if col else None

    # Refusal B1: numeric IN / && filters with blank cells error on old engine
    if f_type in ("w_in", "filter_two_cols") and mode == "mapped":
        return Refusal(
            "Engine bug: numeric IN or && filter with blank cells raises type error",
            expected_error="Cannot convert value '' of type Text to type Number.",
        )
    if f_type == "dt_in" and mode == "mapped":
        return Refusal(
            "Engine bug: date IN filter with blank cells raises type error",
            expected_error="Cannot convert value '46174' of type Text to type Date.",
        )

    # Refusal D2: COUNT of a text column
    if agg == "COUNT" and c_type == "text" and mode == "mapped":
        return Refusal("COUNT not supported on text column", expected_error="type error")

    # Refusal D1: DISTINCTCOUNTNOBLANK on store
    if agg == "DISTINCTCOUNTNOBLANK" and mode == "mapped":
        if overrides.get("noblank_equals_distinctcount"):
            pass
        else:
            return Refusal("DISTINCTCOUNTNOBLANK not supported on store")
    if col == "w_blank" and agg in ("SUM", "AVERAGE") and mode == "mapped":
        return Refusal(
            f"{agg} not supported on text column",
            expected_error=f"The function {agg} cannot work with values of type String.",
        )

    # Refusal: Parquet COUNTA
    if agg == "COUNTA" and is_parquet and mode == "mapped" and not overrides.get("pq_counta_no_refusal"):
        return Refusal(PARQUET_COUNTA_REFUSAL_REASON)

    # Aggregated column scale (the filtered column scale is handled in build_where_clause)
    agg_d_scale = 4 if overrides.get("hardcode_scale_4") else (store_meta or {}).get("decimal_scales", {}).get(col, 4)
    if col == "w_d":
        agg_d_scale = 4 if overrides.get("hardcode_scale_4") else (store_meta or {}).get("decimal_scales", {}).get("d", 4)

    # Check 38 digit total limit refusal
    max_digits = (store_meta or {}).get("max_digits", {}).get(col, 0)
    if max_digits > 38 and mode == "mapped":
        return Refusal("Decimal value exceeds 38 total digits")

    # Build WHERE clause (same function the class predicates use)
    where_clause = build_where_clause(f_type, mode, is_parquet, store_meta, overrides, agg)

    # F5 / Work item G: Group-by shapes
    if group_col:
        # Group-by evaluation delegates to run_comparison for mapped mode
        return None

    # Arithmetic combos
    if f_type in ("plus_scalar", "ratio", "divide_zero", "combo_sum", "combo_sub", "sumx_divide_zero", "sumx_slash_zero"):
        cast_w = "w" if is_parquet else "TRY_CAST(NULLIF(w, '') AS HUGEINT)"

        if f_type == "plus_scalar":
            if mode == "naive":
                return f"SELECT SUM(TRY_CAST(w AS DOUBLE)) + 0.1 FROM {t_q}"
            return "PLUS_SCALAR"
        if f_type == "ratio":
            if mode == "naive":
                return f"SELECT SUM(TRY_CAST(d AS DOUBLE)) / COUNT(d) FROM {t_q}"
            return "RATIO"
        if f_type == "divide_zero":
            if mode == "naive":
                return f"SELECT SUM(TRY_CAST(w AS DOUBLE)) / 0 FROM {t_q}"
            return "SELECT NULL"
        if f_type == "sumx_divide_zero":
            if mode == "naive":
                return f"SELECT SUM(TRY_CAST(w AS DOUBLE) / 0) FROM {t_q}"
            return "SELECT NULL"
        if f_type == "sumx_slash_zero":
            if mode == "naive":
                return f"SELECT SUM(TRY_CAST(w AS DOUBLE) / 0) FROM {t_q}"
            return f"SELECT SUM(CAST({cast_w} AS DOUBLE) / 0.0) FROM {t_q}"
        if f_type == "combo_sum":
            if mode == "naive":
                return f"SELECT SUM(TRY_CAST(w AS DOUBLE)) + SUM(TRY_CAST(d AS DOUBLE)) FROM {t_q}"
            # Work item A3 / Result layer: return special token so run_comparison executes exact leaf sums
            return "COMBO_SUM"
        if f_type == "combo_sub":
            if mode == "naive":
                return f"SELECT AVG(TRY_CAST(w AS DOUBLE)) - MIN(TRY_CAST(w AS DOUBLE)) FROM {t_q}"
            return "COMBO_SUB"

    # Naive mode
    if mode == "naive":
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

    # Mapped mode Refusal checks
    if overrides.get("broken_sql_m9"):
        if agg in ("SUM", "AVERAGE") and c_type in ("text", "boolean", "date"):
            return "SELECT BROKEN SYNTAX"

    if agg in ("SUM", "AVERAGE") and c_type in ("text", "boolean", "date"):
        if col in ("id", "big", "w_blank"):
            expected = f"The function {agg} cannot work with values of type String."
        else:
            expected = f"Column '{col}' contains a non-numeric value"
        return Refusal(f"{agg} not supported on {c_type} column", expected_error=expected)
    if agg in ("MIN", "MAX") and c_type in ("text", "boolean"):
        expected = f"Column '{col}' contains a non-numeric value" if c_type == "boolean" else None
        return Refusal(f"{agg} not supported on {c_type} column", expected_error=expected)

    if overrides.get("drop_empty_guard"):
        empty_guard = ""
        empty_end = ""
    else:
        empty_guard = "CASE WHEN COUNT(*) = 0 THEN NULL ELSE "
        empty_end = " END"

    def pq_dec(c: str, scale: int) -> str:
        """Parquet DOUBLE to exact DECIMAL via its shortest text form (the cast the store uses)."""
        if overrides.get("pq_decimal_direct_cast"):
            return f"CAST({c} AS DECIMAL(38, {scale}))"
        return f"CAST(CAST({c} AS VARCHAR) AS DECIMAL(38, {scale}))"

    if agg == "COUNTROWS":
        return f"SELECT {empty_guard}COUNT(*){empty_end} FROM {t_q} {where_clause}"

    if agg == "SUM":
        if c_type == "whole_number":
            if overrides.get("m4_whole_double"):
                cast_col = f"TRY_CAST({col} AS DOUBLE)" if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DOUBLE)"
            else:
                cast_col = col if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS HUGEINT)"
                if is_parquet and overrides.get("pq_sum_plus_one"):
                    cast_col = f"({col} + 1)"
            return f"SELECT {empty_guard}SUM({cast_col}){empty_end} FROM {t_q} {where_clause}"
        if c_type == "decimal_number":
            if overrides.get("m8_decimal_double") or (not is_parquet and overrides.get("m8_prime_decimal_double")):
                cast_col = f"TRY_CAST({col} AS DOUBLE)" if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DOUBLE)"
            else:
                cast_col = (
                    pq_dec(col, agg_d_scale)
                    if is_parquet
                    else f"TRY_CAST(NULLIF({col}, '') AS DECIMAL(38, {agg_d_scale}))"
                )
            return f"SELECT {empty_guard}SUM({cast_col}){empty_end} FROM {t_q} {where_clause}"
        cast_col = col if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DOUBLE)"
        return f"SELECT {empty_guard}SUM({cast_col}){empty_end} FROM {t_q} {where_clause}"

    if agg == "AVERAGE":
        # Work item A2: Return special token so run_comparison executes exact sum and count
        if c_type == "whole_number":
            cast_c = col if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS HUGEINT)"
        else:
            cast_c = (
                pq_dec(col, 0 if overrides.get("pq_avg_scale0") else agg_d_scale)
                if is_parquet
                else f"TRY_CAST(NULLIF({col}, '') AS DECIMAL(38, {agg_d_scale}))"
            )
        return f"EXACT_AVERAGE:{cast_c}:{where_clause}"

    if agg == "MIN":
        if c_type == "date":
            cast_col = f"TRY_CAST({col} AS DATE)" if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DATE)"
            if overrides.get("m6_date_epoch_off"):
                epoch = "DATE '1899-12-31'"
                return f"SELECT {empty_guard}date_diff('day', {epoch}, MIN({cast_col})){empty_end} FROM {t_q} {where_clause}"
            return f"SELECT {empty_guard}MIN({cast_col}){empty_end} FROM {t_q} {where_clause}"
        if c_type == "whole_number":
            cast_col = col if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS HUGEINT)"
            return f"SELECT {empty_guard}MIN({cast_col}){empty_end} FROM {t_q} {where_clause}"
        if c_type == "decimal_number":
            cast_col = (
                pq_dec(col, agg_d_scale)
                if is_parquet
                else f"TRY_CAST(NULLIF({col}, '') AS DECIMAL(38, {agg_d_scale}))"
            )
            return f"SELECT {empty_guard}MIN({cast_col}){empty_end} FROM {t_q} {where_clause}"
        cast_col = col if is_parquet else f"NULLIF({col}, '')"
        return f"SELECT {empty_guard}MIN({cast_col}){empty_end} FROM {t_q} {where_clause}"

    if agg == "MAX":
        if c_type == "date":
            cast_col = f"TRY_CAST({col} AS DATE)" if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DATE)"
            if overrides.get("m6_date_epoch_off"):
                epoch = "DATE '1899-12-31'"
                return f"SELECT {empty_guard}date_diff('day', {epoch}, MAX({cast_col})){empty_end} FROM {t_q} {where_clause}"
            return f"SELECT {empty_guard}MAX({cast_col}){empty_end} FROM {t_q} {where_clause}"
        if c_type == "whole_number":
            cast_col = col if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS HUGEINT)"
            return f"SELECT {empty_guard}MAX({cast_col}){empty_end} FROM {t_q} {where_clause}"
        if c_type == "decimal_number":
            cast_col = (
                pq_dec(col, agg_d_scale)
                if is_parquet
                else f"TRY_CAST(NULLIF({col}, '') AS DECIMAL(38, {agg_d_scale}))"
            )
            return f"SELECT {empty_guard}MAX({cast_col}){empty_end} FROM {t_q} {where_clause}"
        cast_col = col if is_parquet else f"NULLIF({col}, '')"
        return f"SELECT {empty_guard}MAX({cast_col}){empty_end} FROM {t_q} {where_clause}"

    if agg == "COUNT":
        if c_type in ("whole_number", "decimal_number", "date"):
            cnt_col = f"COUNT({col})" if is_parquet else f"COUNT(NULLIF({col}, ''))"
            return f"SELECT {empty_guard}NULLIF({cnt_col}, 0){empty_end} FROM {t_q} {where_clause}"
        if c_type == "boolean":
            return Refusal(
                "COUNT not supported on boolean column",
                expected_error=f"Column '{col}' contains a non-numeric value",
            )
        # Text column: refused on mapped mode above
        cnt_col = f"COUNT(NULLIF({col}, ''))"
        return f"SELECT {empty_guard}NULLIF({cnt_col}, 0){empty_end} FROM {t_q} {where_clause}"

    if agg == "COUNTA":
        if overrides.get("m5_counta_nonblank") or (not is_parquet and overrides.get("m5_prime_counta_nonblank")):
            cnt_col = f"COUNT({col})" if is_parquet else f"COUNT(NULLIF({col}, ''))"
            return f"SELECT {empty_guard}NULLIF({cnt_col}, 0){empty_end} FROM {t_q} {where_clause}"
        cnt_col = f"COUNT({col})"
        return f"SELECT {empty_guard}NULLIF({cnt_col}, 0){empty_end} FROM {t_q} {where_clause}"

    if agg == "COUNTBLANK":
        if c_type in ("text",):
            cnt_nonblank = f"COUNT(NULLIF({col}, ''))"
        else:
            cnt_nonblank = f"COUNT({col})" if is_parquet else f"COUNT(NULLIF({col}, ''))"
        return f"SELECT {empty_guard}NULLIF(COUNT(*) - {cnt_nonblank}, 0){empty_end} FROM {t_q} {where_clause}"

    if agg == "DISTINCTCOUNT":
        if c_type == "text":
            fold_c = make_fold_expr(col, agg, overrides)
            blank_add = f"MAX(CASE WHEN COALESCE({col}, '') = '' THEN 1 ELSE 0 END)"
            return (
                f"SELECT {empty_guard}COUNT(DISTINCT NULLIF({fold_c}, '')) + {blank_add}{empty_end} "
                f"FROM {t_q} {where_clause}"
            )
        if is_parquet:
            if overrides.get("pq_distinct_no_blank_add"):
                return f"SELECT {empty_guard}COUNT(DISTINCT {col}){empty_end} FROM {t_q} {where_clause}"
            blank_add = f"MAX(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END)"
            return f"SELECT {empty_guard}COUNT(DISTINCT {col}) + {blank_add}{empty_end} FROM {t_q} {where_clause}"
        else:
            cast_type = "HUGEINT" if c_type == "whole_number" else f"DECIMAL(38, {agg_d_scale})" if c_type == "decimal_number" else "DATE" if c_type == "date" else "BOOLEAN"
            cast_c = f"TRY_CAST(NULLIF({col}, '') AS {cast_type})"
            if overrides.get("m14_distinct_no_blank_add"):
                return f"SELECT {empty_guard}COUNT(DISTINCT {cast_c}){empty_end} FROM {t_q} {where_clause}"
            blank_add = f"MAX(CASE WHEN COALESCE({col}, '') = '' THEN 1 ELSE 0 END)"
            return f"SELECT {empty_guard}COUNT(DISTINCT {cast_c}) + {blank_add}{empty_end} FROM {t_q} {where_clause}"

    return None


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
) -> dict[str, Any]:
    """Run comparison workflow across engine, CSV store, and Parquet store."""
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
    decimal_scales: dict[str, int] = {}
    max_digits_map: dict[str, int] = {}
    for col in ["d", "w", "big", "num_dups"]:
        try:
            scale_res = store.execute(
                f"SELECT COALESCE(MAX(CASE WHEN strpos({col}, '.') > 0 "
                f"THEN length(regexp_extract({col}, '\\.([0-9]+)', 1)) ELSE 0 END), 0) FROM \"t_csv\""
            )
            decimal_scales[col] = max(4, int(scale_res[0][0])) if scale_res else 4
            digits_res = store.execute(
                f"SELECT COALESCE(MAX(length(regexp_replace({col}, '[^0-9]', '', 'g'))), 0) FROM \"t_csv\""
            )
            max_digits_map[col] = int(digits_res[0][0]) if digits_res else 0
        except Exception:
            decimal_scales[col] = 4
            max_digits_map[col] = 0

    store_meta = {"decimal_scales": decimal_scales, "max_digits": max_digits_map}

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
        formulas = all_formulas

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

        if g_col:
            # F5 / Work item G: Group-by evaluation using engine key order
            try:
                g_target = f_item.get("col")
                g_agg = f_item["agg"]
                val_expr = f"COUNTROWS({tname})" if g_agg == "COUNTROWS" else f"{g_agg}({tname}[{g_target}])"
                e_keys = engine_group_keys.get(g_col, [])
                pairs: list[str] = []
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
                engine_text = format_report_value(res)
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
                        val_expr = f"SUM(TRY_CAST(NULLIF({g_target}, '') AS DECIMAL(38, {d_scale}))), COUNT(TRY_CAST(NULLIF({g_target}, '') AS DECIMAL(38, {d_scale})))"
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
                    fold_t = f"translate(rtrim(COALESCE(t, ''), {TRIM_CHARS_SQL}), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')"
                    q = f"SELECT arg_min(rtrim(COALESCE(t, ''), {TRIM_CHARS_SQL}), rowid) as k, {val_expr}, MIN(rowid) as first_rn FROM \"t_csv\" GROUP BY {fold_t} ORDER BY first_rn"
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
                            sql_dict[k_str] = StoreResultLayer.divide(s_part, c_part)
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
                    mapped_val = StoreResultLayer.divide(s_res, c_res)
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
                    mapped_val = StoreResultLayer.divide_ratio(s_d, c_d)
                    mapped_text = format_report_value(mapped_val)
                except Exception as exc:
                    mapped_err = str(exc)
                    mapped_text = f"ERR:{mapped_err[:60]}"
            elif mapped_sql_res == "COMBO_SUB":
                try:
                    s_w, c_w = store.execute('SELECT SUM(TRY_CAST(NULLIF(w, \'\') AS HUGEINT)), COUNT(TRY_CAST(NULLIF(w, \'\') AS HUGEINT)) FROM "t_csv"')[0]
                    min_w = store.execute('SELECT MIN(TRY_CAST(NULLIF(w, \'\') AS HUGEINT)) FROM "t_csv"')[0][0]
                    avg_w = StoreResultLayer.divide(s_w, c_w)
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
                        val_expr = f"SUM(CAST(CAST({g_target} AS VARCHAR) AS DECIMAL(38, {d_scale}))), COUNT(CAST(CAST({g_target} AS VARCHAR) AS DECIMAL(38, {d_scale})))"
                    elif g_agg == "DISTINCTCOUNT":
                        val_expr = f"COUNT(DISTINCT {g_target}) + MAX(CASE WHEN {g_target} IS NULL THEN 1 ELSE 0 END)"
                    elif g_agg == "MIN":
                        val_expr = "MIN(dt)"

                    if g_col == "cat":
                        q = f"SELECT cat as k, {val_expr} FROM \"t_pq\" GROUP BY cat"
                    elif g_col == "t":
                        fold_t = f"translate(rtrim(COALESCE(t, ''), {TRIM_CHARS_SQL}), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')"
                        q = f"SELECT FIRST(rtrim(COALESCE(t, ''), {TRIM_CHARS_SQL})) as k, {val_expr} FROM \"t_pq\" GROUP BY {fold_t}"
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
                            sql_dict[k_str] = StoreResultLayer.divide(s_part, c_part)
                        else:
                            sql_dict[k_str] = r_tuple[1]

                    e_keys = engine_group_keys.get(g_col, [])
                    pq_kv = [[format_report_value(k), format_report_value(sql_dict.get(k))] for k in e_keys]
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
                        pq_val = StoreResultLayer.divide(s_res, c_res)
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
                        pq_val = StoreResultLayer.divide_ratio(s_d, c_d)
                        pq_text = format_report_value(pq_val)
                    except Exception as exc:
                        pq_err = str(exc)
                        pq_text = f"ERR:{pq_err[:60]}"
                elif pq_sql_res == "COMBO_SUB":
                    try:
                        s_w, c_w = store.execute('SELECT SUM(w), COUNT(w) FROM "t_pq"')[0]
                        min_w = store.execute('SELECT MIN(w) FROM "t_pq"')[0][0]
                        avg_w = StoreResultLayer.divide(s_w, c_w)
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
            elif engine_text == mapped_text:
                mapped_status = "same"
            else:
                mapped_status = "differs"

        if skip_parquet:
            pq_vs_csv_diff = False
        elif pq_err is None and mapped_err is None:
            pq_vs_csv_diff = pq_text != mapped_text
        else:
            pq_vs_csv_diff = pq_err != mapped_err

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
            "mapped_status": mapped_status,
            "pq_val": str(pq_val),
            "pq_text": pq_text,
            "pq_err": pq_err,
            "pq_refusal": str(pq_refusal) if pq_refusal else None,
            "pq_vs_csv_diff": pq_vs_csv_diff,
        })

    perf_metrics: dict[str, Any] = {}
    if perf_rows > 0:
        perf_metrics = run_perf_benchmark(t_path, perf_rows)

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


def run_perf_benchmark(base_dir: Path, n_rows: int) -> dict[str, Any]:
    """Measure store query times and memory on generated large CSV and Parquet."""
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


def _pq_group_expected(r: dict[str, Any], f_item: dict[str, Any], ctx: dict[str, Any]) -> str | None:
    """Expected Parquet text of a group-by SUM or AVERAGE of d, from the DOUBLE-rounded Parquet cells."""
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
    pairs = []
    for key in ctx["group_keys"].get(g_col, []):
        label = _fold_text(key) if g_col == "t" else key
        if f_item["agg"] == "SUM":
            val: Decimal | None = sums.get(label)
        else:
            val = StoreResultLayer.divide(sums.get(label), counts.get(label))
        pairs.append(f"{format_report_value(key)}:{format_report_value(val)}")
    return ";".join(pairs)


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
        if f_item.get("col") != "d" or agg not in ("SUM", "AVERAGE") or not r.get("mapped_kv") or not r.get("pq_kv"):
            return None
        if _pq_group_expected(r, f_item, ctx) != r["pq_text"]:
            return None
        differing = [m for m, p in zip(r["mapped_kv"], r["pq_kv"]) if m != p]
        if differing and all(_sig_digits(m[1]) > 15 for m in differing):
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
    all_statuses = ["same", "differs", "refused", "sql-error", "refusal-reason-mismatch", "engine-error", "both-error"]
    for s in all_statuses:
        lines.append(f"| {s} | {status_counts_naive.get(s, 0)} | {status_counts_mapped.get(s, 0)} |")
    lines.append("")
    lines.append(f"- **Same:** {status_counts_mapped.get('same', 0)}")
    lines.append(f"- **Differs:** {status_counts_mapped.get('differs', 0)}")
    # Headline refused count = every formula that carries an explicit Refusal; the breakdowns below sum to it
    total_refusals = sum(refused_reasons.values())
    refused_with_engine_value = status_counts_mapped.get("refused", 0)
    lines.append(
        f"- **Refused:** {total_refusals} "
        f"({refused_with_engine_value} where the engine returns a value and the store refuses, "
        f"{total_refusals - refused_with_engine_value} where the engine raises an error and the refusal text matches it)"
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
            cls_note = f" [Class: {d.get('mapped_diff_class')}]" if d.get('mapped_diff_class') else " [UNCLASSIFIED]"
            lines.append(f"- `{d['id']}` ({d['dax']}): Engine='{e_disp}' vs Mapped='{m_disp}'{cls_note}")
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

def evaluate_exit_policy(data: dict[str, Any], baseline: dict[str, Any]) -> tuple[int, list[str]]:
    """Exit policy of the tool: returns (exit code, failure messages).

    Exit 1 on: any mapped SQL error, any refusal whose reason does not match the engine error, any mapped difference
    without a class listed in the baseline, any Parquet difference without a class listed in the baseline, and (when
    the baseline has a "refused" list, even an empty one) any change of the set of refused formulas.
    """
    results = data["results"]

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
    parser.add_argument("--rows", type=int, default=2000, help="Row count for generated data (default: 2000)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("--out", type=str, default="", help="Output markdown file path")
    parser.add_argument("--json", type=str, default="", help="Output JSON file path")
    parser.add_argument("--perf-rows", type=int, default=0, help="Measure query times on N rows (default: 0)")
    parser.add_argument("--baseline", type=str, default="", help="Path to baseline JSON file")

    args = parser.parse_args()

    try:
        data = run_comparison(rows=args.rows, seed=args.seed, perf_rows=args.perf_rows)
    except Exception as exc:
        print(f"TOOL CRASH: {exc}", file=sys.stderr)
        sys.exit(2)

    md_content = generate_markdown_report(data)

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
    for message in messages:
        print(message, file=sys.stderr)
    sys.exit(code)


if __name__ == "__main__":
    main()
