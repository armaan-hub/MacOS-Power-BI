"""Engine versus DuckStore comparison and rules generator.

Stage C0b tool comparing DAX evaluation on the native engine against naive and
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
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from analytics_studio import dax_dates
from analytics_studio.controller import StudioController, _format_report_number
from analytics_studio.file_import import parse_file
from analytics_studio.measures import evaluate_measures, normalize_measure
from analytics_studio.store import DuckStore, import_csv_to_store, import_parquet_to_store


# Safe SQL expression for the 33 characters U+0000..U+0020
TRIM_CHARS_SQL = " || ".join(f"chr({i})" for i in range(33))


class Refusal:
    """Explicit refusal object representing an intentionally unsupported shape."""

    def __init__(self, reason: str):
        self.reason = reason

    def __repr__(self) -> str:
        return f"Refusal({self.reason!r})"

    def __str__(self) -> str:
        return f"REFUSED: {self.reason}"


def format_report_value(val: Any) -> str:
    """Format value for reporting (1:1 app representation using _format_report_number)."""
    if val is None or val == "":
        return ""
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


def generate_dataset(
    csv_path: Path,
    parquet_path: Path,
    rows: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    """Generate seeded dataset with mixed types, blanks, edge values, and collisions."""
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

    csv_rows: list[list[str]] = []
    headers = ["id", "w", "d", "big", "t", "dt", "flag", "cat"]

    pq_id: list[str] = []
    pq_w: list[int | None] = []
    pq_d: list[float | None] = []
    pq_big: list[str] = []
    pq_t: list[str | None] = []
    pq_dt: list[dt.date | None] = []
    pq_flag: list[bool | None] = []
    pq_cat: list[str] = []

    for i in range(1, rows + 1):
        id_str = str(i)

        # w: whole number with seed-dependent blanks and large whole numbers (>2^53)
        if rnd.random() < 0.10:
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
        if rnd.random() < 0.10:
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

        csv_rows.append([id_str, w_str, d_str, big_str, t_str, dt_str, flag_str, cat_str])

        pq_id.append(id_str)
        pq_w.append(w_val)
        pq_d.append(d_val)
        pq_big.append(big_str)
        pq_t.append(t_val)
        pq_dt.append(dt_val)
        pq_flag.append(flag_val)
        pq_cat.append(cat_str)

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
        }
    )
    pq.write_table(pq_table, parquet_path)

    return {"headers": headers, "row_count": rows}


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
        ("dt_lte", "t[dt] <= DATE(2026, 6, 1)", "date_lte"),
        ("dt_neq", "t[dt] <> DATE(2026, 6, 1)", "date_neq"),
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

    # F6: U+0000..U+0020 trim characters
    if overrides.get("trim_set_space_only"):
        trim_arg = "' \\t\\r\\n'"
    else:
        trim_arg = TRIM_CHARS_SQL

    def fold_expr(c: str) -> str:
        if overrides.get("drop_distinct_fold") and agg in ("DISTINCTCOUNT", "DISTINCTCOUNTNOBLANK"):
            return c
        if overrides.get("drop_rtrim"):
            return f"translate(COALESCE({c}, ''), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')"
        return f"translate(rtrim(COALESCE({c}, ''), {trim_arg}), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')"

    fold_t = fold_expr("t")

    # F7: Derive decimal scale
    if overrides.get("hardcode_scale_4"):
        d_scale = 4
    else:
        d_scale = (store_meta or {}).get("decimal_scales", {}).get(col, 4)
        if col == "w_d":
            d_scale = (store_meta or {}).get("decimal_scales", {}).get("d", 4)

    # Check 38 digit total limit refusal
    max_digits = (store_meta or {}).get("max_digits", {}).get(col, 0)
    if max_digits > 38 and mode == "mapped":
        return Refusal("Decimal value exceeds 38 total digits")

    # Build WHERE clause
    where_clause = ""
    if f_type:
        cast_w = "w" if is_parquet else "TRY_CAST(NULLIF(w, '') AS HUGEINT)"
        cast_d = "d" if is_parquet else f"TRY_CAST(NULLIF(d, '') AS DECIMAL(38, {d_scale}))"

        if overrides.get("drop_w_zero_coalesce"):
            w_zero_cond = f"{cast_w} = 0"
        else:
            w_zero_cond = f"COALESCE({cast_w}, 0) = 0"

        if overrides.get("drop_w_lt_coalesce"):
            w_lt_cond = f"{cast_w} < 100"
        else:
            w_lt_cond = f"COALESCE({cast_w}, 0) < 100"

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
            where_clause = "WHERE TRY_CAST(w AS DOUBLE) <= 100" if mode == "naive" else f"WHERE COALESCE({cast_w}, 0) <= 100"
        elif f_type == "w_gt":
            where_clause = "WHERE TRY_CAST(w AS DOUBLE) > 100" if mode == "naive" else f"WHERE {cast_w} > 100"
        elif f_type == "w_gte":
            where_clause = "WHERE TRY_CAST(w AS DOUBLE) >= 100" if mode == "naive" else f"WHERE {cast_w} >= 100"
        elif f_type == "w_neq":
            where_clause = "WHERE TRY_CAST(w AS DOUBLE) <> 100" if mode == "naive" else f"WHERE COALESCE({cast_w}, 0) <> 100"
        elif f_type == "w_not":
            where_clause = "WHERE NOT(TRY_CAST(w AS DOUBLE) = 100)" if mode == "naive" else f"WHERE COALESCE({cast_w}, 0) <> 100"
        elif f_type == "w_or":
            where_clause = "WHERE TRY_CAST(w AS DOUBLE) = 100 OR TRY_CAST(w AS DOUBLE) = 200" if mode == "naive" else f"WHERE COALESCE({cast_w}, 0) = 100 OR COALESCE({cast_w}, 0) = 200"
        elif f_type == "w_in":
            where_clause = "WHERE TRY_CAST(w AS DOUBLE) IN (100, 200)" if mode == "naive" else f"WHERE COALESCE({cast_w}, 0) IN (100, 200)"
        elif f_type == "d_gte":
            where_clause = "WHERE TRY_CAST(d AS DOUBLE) >= 0" if mode == "naive" else f"WHERE COALESCE({cast_d}, 0) >= 0"
        elif f_type == "d_lt":
            where_clause = "WHERE TRY_CAST(d AS DOUBLE) < 0" if mode == "naive" else f"WHERE {cast_d} < 0"
        elif f_type == "d_neq":
            where_clause = "WHERE TRY_CAST(d AS DOUBLE) <> 0" if mode == "naive" else f"WHERE COALESCE({cast_d}, 0) <> 0"
        elif f_type == "dt_range":
            cast_dt = "TRY_CAST(dt AS DATE)" if is_parquet else "TRY_CAST(NULLIF(dt, '') AS DATE)"
            where_clause = "WHERE dt >= '2026-06-01'" if mode == "naive" else f"WHERE {cast_dt} >= DATE '2026-06-01'"
        elif f_type == "dt_lte":
            cast_dt = "TRY_CAST(dt AS DATE)" if is_parquet else "TRY_CAST(NULLIF(dt, '') AS DATE)"
            where_clause = "WHERE dt <= '2026-06-01'" if mode == "naive" else f"WHERE {cast_dt} <= DATE '2026-06-01'"
        elif f_type == "dt_neq":
            cast_dt = "TRY_CAST(dt AS DATE)" if is_parquet else "TRY_CAST(NULLIF(dt, '') AS DATE)"
            where_clause = "WHERE dt <> '2026-06-01'" if mode == "naive" else f"WHERE {cast_dt} <> DATE '2026-06-01'"
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

    # F5: Group-by shapes
    if group_col:
        val_expr = "COUNT(*)"
        if agg == "SUM":
            if mode == "naive":
                val_expr = f"SUM(TRY_CAST({col} AS DOUBLE))"
            else:
                if col == "w":
                    cast_c = col if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS HUGEINT)"
                    val_expr = f"SUM({cast_c})"
                else:
                    cast_c = f"CAST({col} AS DECIMAL(38, {d_scale}))" if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DECIMAL(38, {d_scale}))"
                    val_expr = f"SUM({cast_c})"
        elif agg == "AVERAGE":
            if mode == "naive":
                val_expr = f"AVG(TRY_CAST({col} AS DOUBLE))"
            else:
                cast_c = f"CAST({col} AS DECIMAL(38, {d_scale}))" if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DECIMAL(38, {d_scale}))"
                val_expr = f"AVG({cast_c})"
        elif agg == "DISTINCTCOUNT":
            if mode == "naive":
                val_expr = f"COUNT(DISTINCT {col})"
            else:
                blank_check = f"MAX(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END)" if is_parquet else f"MAX(CASE WHEN COALESCE({col}, '') = '' THEN 1 ELSE 0 END)"
                val_expr = f"COUNT(DISTINCT NULLIF({col}, '')) + {blank_check}"
        elif agg == "MIN":
            if mode == "naive":
                val_expr = f"MIN({col})"
            else:
                cast_c = col if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DATE)"
                val_expr = f"MIN({cast_c})"

        if group_col == "cat":
            sub_q = f"SELECT cat as k, {val_expr} as val FROM {t_q} GROUP BY cat"
            return f"SELECT string_agg(k || ':' || val, ';' ORDER BY k) FROM ({sub_q})"
        if group_col == "t":
            sub_q = f"SELECT {fold_t} as fold_key, FIRST(rtrim(COALESCE(t, ''), {trim_arg})) as disp, {val_expr} as val FROM {t_q} GROUP BY {fold_t}"
            return f"SELECT string_agg(disp || ':' || val, ';' ORDER BY fold_key) FROM ({sub_q})"
        if group_col == "dt":
            cast_dt = "dt" if is_parquet else "TRY_CAST(NULLIF(dt, '') AS DATE)"
            sub_q = f"SELECT {cast_dt} as k, {val_expr} as val FROM {t_q} GROUP BY {cast_dt}"
            return f"SELECT string_agg(COALESCE(strftime(k, '%Y-%m-%d'), '') || ':' || val, ';' ORDER BY k) FROM ({sub_q})"
        if group_col == "flag":
            cast_flag = "COALESCE(flag, FALSE)" if is_parquet else "CASE WHEN UPPER(TRIM(COALESCE(flag, ''))) = 'TRUE' THEN TRUE ELSE FALSE END"
            sub_q = f"SELECT {cast_flag} as k, {val_expr} as val FROM {t_q} GROUP BY {cast_flag}"
            return f"SELECT string_agg((CASE WHEN k THEN 'TRUE' ELSE 'FALSE' END) || ':' || val, ';' ORDER BY k) FROM ({sub_q})"

    # Arithmetic combos
    if f_type in ("plus_scalar", "ratio", "divide_zero", "combo_sum", "combo_sub", "sumx_divide_zero", "sumx_slash_zero"):
        cast_w = "w" if is_parquet else "TRY_CAST(NULLIF(w, '') AS HUGEINT)"
        cast_d = f"CAST(d AS DECIMAL(38, {d_scale}))" if is_parquet else f"TRY_CAST(NULLIF(d, '') AS DECIMAL(38, {d_scale}))"
        cnt_d = "COUNT(d)" if is_parquet else "COUNT(NULLIF(d, ''))"

        if f_type == "plus_scalar":
            if mode == "naive":
                return f"SELECT SUM(TRY_CAST(w AS DOUBLE)) + 0.1 FROM {t_q}"
            return f"SELECT CAST(SUM({cast_w}) AS DOUBLE) + 0.1 FROM {t_q}"
        if f_type == "ratio":
            if mode == "naive":
                return f"SELECT SUM(TRY_CAST(d AS DOUBLE)) / COUNT(d) FROM {t_q}"
            return f"SELECT SUM({cast_d}) / NULLIF({cnt_d}, 0) FROM {t_q}"
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
            # CAST SUM(w) to DOUBLE + fsum(d) to match exact IEEE 754 float sum of engine
            sum_d_expr = "fsum(d)" if is_parquet else "fsum(TRY_CAST(NULLIF(d, '') AS DOUBLE))"
            return f"SELECT CAST(SUM({cast_w}) AS DOUBLE) + {sum_d_expr} FROM {t_q}"
        if f_type == "combo_sub":
            cast_avg_w = "w" if is_parquet else "TRY_CAST(NULLIF(w, '') AS DOUBLE)"
            if mode == "naive":
                return f"SELECT AVG(TRY_CAST(w AS DOUBLE)) - MIN(TRY_CAST(w AS DOUBLE)) FROM {t_q}"
            return f"SELECT AVG({cast_avg_w}) - MIN({cast_w}) FROM {t_q}"

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
        return Refusal(f"{agg} not supported on {c_type} column")
    if agg in ("MIN", "MAX") and c_type in ("text", "boolean"):
        return Refusal(f"{agg} not supported on {c_type} column")

    if overrides.get("drop_empty_guard"):
        empty_guard = ""
        empty_end = ""
    else:
        empty_guard = "CASE WHEN COUNT(*) = 0 THEN NULL ELSE "
        empty_end = " END"

    if agg == "COUNTROWS":
        return f"SELECT {empty_guard}COUNT(*){empty_end} FROM {t_q} {where_clause}"

    if agg == "SUM":
        if c_type == "whole_number":
            if overrides.get("m4_whole_double"):
                cast_col = f"TRY_CAST({col} AS DOUBLE)" if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DOUBLE)"
            else:
                cast_col = col if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS HUGEINT)"
            return f"SELECT {empty_guard}SUM({cast_col}){empty_end} FROM {t_q} {where_clause}"
        if c_type == "decimal_number":
            if overrides.get("m8_decimal_double"):
                cast_col = f"TRY_CAST({col} AS DOUBLE)" if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DOUBLE)"
            else:
                cast_col = f"CAST({col} AS DECIMAL(38, {d_scale}))" if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DECIMAL(38, {d_scale}))"
            return f"SELECT {empty_guard}SUM({cast_col}){empty_end} FROM {t_q} {where_clause}"
        cast_col = col if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DOUBLE)"
        return f"SELECT {empty_guard}SUM({cast_col}){empty_end} FROM {t_q} {where_clause}"

    if agg == "AVERAGE":
        cast_col = f"CAST({col} AS DECIMAL(38, {d_scale}))" if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DECIMAL(38, {d_scale}))"
        return f"SELECT {empty_guard}AVG({cast_col}){empty_end} FROM {t_q} {where_clause}"

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
            cast_col = f"CAST({col} AS DECIMAL(38, {d_scale}))" if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DECIMAL(38, {d_scale}))"
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
            cast_col = f"CAST({col} AS DECIMAL(38, {d_scale}))" if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DECIMAL(38, {d_scale}))"
            return f"SELECT {empty_guard}MAX({cast_col}){empty_end} FROM {t_q} {where_clause}"
        cast_col = col if is_parquet else f"NULLIF({col}, '')"
        return f"SELECT {empty_guard}MAX({cast_col}){empty_end} FROM {t_q} {where_clause}"

    if agg == "COUNT":
        if c_type in ("whole_number", "decimal_number", "date"):
            cnt_col = f"COUNT({col})" if is_parquet else f"COUNT(NULLIF({col}, ''))"
            return f"SELECT {empty_guard}NULLIF({cnt_col}, 0){empty_end} FROM {t_q} {where_clause}"
        if c_type == "boolean":
            return Refusal("COUNT not supported on boolean column")
        # Text column: count of non-blank string
        cnt_col = f"COUNT(NULLIF({col}, ''))"
        return f"SELECT {empty_guard}NULLIF({cnt_col}, 0){empty_end} FROM {t_q} {where_clause}"

    if agg == "COUNTA":
        if overrides.get("m5_counta_nonblank"):
            cnt_col = f"COUNT({col})" if is_parquet else f"COUNT(NULLIF({col}, ''))"
            return f"SELECT {empty_guard}NULLIF({cnt_col}, 0){empty_end} FROM {t_q} {where_clause}"
        # F4/F8: Stated COUNTA rule: count rows whose cell exists in store's representation
        # On CSV, COUNT(col) counts all rows where cell exists (including '')
        # On Parquet, typed columns count non-null; string columns count non-null
        cnt_col = f"COUNT({col})"
        return f"SELECT {empty_guard}NULLIF({cnt_col}, 0){empty_end} FROM {t_q} {where_clause}"

    if agg == "COUNTBLANK":
        # F8: blank = NULL or '' for text; NULL for typed columns
        if c_type in ("text",):
            cnt_nonblank = f"COUNT(NULLIF({col}, ''))"
        else:
            cnt_nonblank = f"COUNT({col})" if is_parquet else f"COUNT(NULLIF({col}, ''))"
        return f"SELECT {empty_guard}NULLIF(COUNT(*) - {cnt_nonblank}, 0){empty_end} FROM {t_q} {where_clause}"

    if agg == "DISTINCTCOUNT":
        # F4/F8: On text, fold U+0000..U+0020 + ASCII lowercase + 1 for blank
        if c_type == "text":
            fold_c = fold_expr(col)
            blank_add = f"MAX(CASE WHEN COALESCE({col}, '') = '' THEN 1 ELSE 0 END)"
            return (
                f"SELECT {empty_guard}COUNT(DISTINCT NULLIF({fold_c}, '')) + {blank_add}{empty_end} "
                f"FROM {t_q} {where_clause}"
            )
        # On typed columns: distinct of cast value + 1 if blank exists
        if is_parquet:
            blank_add = f"MAX(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END)"
            return f"SELECT {empty_guard}COUNT(DISTINCT {col}) + {blank_add}{empty_end} FROM {t_q} {where_clause}"
        else:
            cast_type = "HUGEINT" if c_type == "whole_number" else f"DECIMAL(38, {d_scale})" if c_type == "decimal_number" else "DATE" if c_type == "date" else "BOOLEAN"
            cast_c = f"TRY_CAST(NULLIF({col}, '') AS {cast_type})"
            blank_add = f"MAX(CASE WHEN COALESCE({col}, '') = '' THEN 1 ELSE 0 END)"
            return f"SELECT {empty_guard}COUNT(DISTINCT {cast_c}) + {blank_add}{empty_end} FROM {t_q} {where_clause}"

    if agg == "DISTINCTCOUNTNOBLANK":
        if overrides.get("noblank_equals_distinctcount"):
            return generate_sql(
                {**formula, "agg": "DISTINCTCOUNT"},
                table_name,
                column_types,
                mode=mode,
                is_parquet=is_parquet,
                store_meta=store_meta,
                overrides=overrides,
            )
        if c_type == "text":
            fold_c = fold_expr(col)
            return (
                f"SELECT {empty_guard}COUNT(DISTINCT NULLIF({fold_c}, '')){empty_end} "
                f"FROM {t_q} {where_clause}"
            )
        if is_parquet:
            return f"SELECT {empty_guard}COUNT(DISTINCT {col}){empty_end} FROM {t_q} {where_clause}"
        else:
            cast_type = "HUGEINT" if c_type == "whole_number" else f"DECIMAL(38, {d_scale})" if c_type == "decimal_number" else "DATE" if c_type == "date" else "BOOLEAN"
            cast_c = f"TRY_CAST(NULLIF({col}, '') AS {cast_type})"
            return f"SELECT {empty_guard}COUNT(DISTINCT {cast_c}){empty_end} FROM {t_q} {where_clause}"

    return None


def run_comparison(
    rows: int = 2000,
    seed: int = 42,
    perf_rows: int = 0,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run full comparison tool workflow across engine, CSV store, Parquet store."""
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
    import_parquet_to_store(store, "t_pq", pq_file, {})

    # F7: Inspect store metadata for max decimals and digits
    decimal_scales: dict[str, int] = {}
    max_digits_map: dict[str, int] = {}
    for col in ["d", "w", "big"]:
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

    formulas = build_formula_catalog(headers)
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
            # F5: Group-by evaluation using per-key CALCULATE
            try:
                g_target = f_item.get("col")
                g_agg = f_item["agg"]
                val_expr = f"COUNTROWS({tname})" if g_agg == "COUNTROWS" else f"{g_agg}({tname}[{g_target}])"

                trim_chars = "".join(chr(i) for i in range(33))
                first_seen: dict[str, str] = {}
                for r in cand_rows:
                    val = r.get(g_col, "")
                    if g_col == "t":
                        k = val.rstrip(trim_chars).translate(
                            str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
                        )
                        first_seen.setdefault(k, val.rstrip(trim_chars))
                    elif g_col == "flag":
                        k = "TRUE" if str(val).strip().casefold() == "true" else "FALSE"
                        first_seen.setdefault(k, k)
                    else:
                        first_seen.setdefault(val, val)

                pairs: list[str] = []
                for k, disp in sorted(first_seen.items()):
                    if k == "" or (g_col == "flag" and disp == "BLANK"):
                        filter_part = f"ISBLANK({tname}[{g_col}])" if g_col == "dt" else f'{tname}[{g_col}] = ""'
                    elif g_col == "flag":
                        filter_part = f"{tname}[{g_col}] = {k}()"
                    elif g_col == "dt":
                        filter_part = f"{tname}[{g_col}] = DATE({k[:4]}, {int(k[5:7])}, {int(k[8:10])})"
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
                    disp_str = format_report_value(disp)
                    val_str = format_report_value(k_val)
                    pairs.append(f"{disp_str}:{val_str}")

                engine_val = ";".join(pairs)
                engine_text = engine_val
            except Exception as exc:
                engine_err = str(exc)
                engine_text = f"ERR:{engine_err[:60]}"
        else:
            try:
                # Replace table name in dax
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
        naive_sql_res = generate_sql(f_item, "t_csv", model_types, mode="naive")
        naive_val = None
        naive_text = ""
        naive_err = None
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
        mapped_sql_res = generate_sql(
            f_item,
            "t_csv",
            model_types,
            mode="mapped",
            is_parquet=False,
            store_meta=store_meta,
            overrides=overrides,
        )
        mapped_val = None
        mapped_text = ""
        mapped_err = None
        mapped_refusal = None

        if isinstance(mapped_sql_res, Refusal):
            mapped_refusal = mapped_sql_res
            mapped_text = str(mapped_sql_res)
        elif mapped_sql_res is None:
            mapped_refusal = Refusal("Unsupported shape")
            mapped_text = str(mapped_refusal)
        else:
            try:
                row_res = store.execute(mapped_sql_res)
                mapped_val = row_res[0][0] if row_res else None
                mapped_text = format_report_value(mapped_val)
            except Exception as exc:
                mapped_err = str(exc)
                mapped_text = f"ERR:{mapped_err[:60]}"

        # D: Parquet store evaluation
        pq_sql_res = generate_sql(
            f_item,
            "t_pq",
            model_types,
            mode="mapped",
            is_parquet=True,
            store_meta=store_meta,
            overrides=overrides,
        )
        pq_val = None
        pq_text = ""
        pq_err = None
        pq_refusal = None

        if isinstance(pq_sql_res, Refusal):
            pq_refusal = pq_sql_res
            pq_text = str(pq_sql_res)
        elif pq_sql_res is None:
            pq_refusal = Refusal("Unsupported shape")
            pq_text = str(pq_refusal)
        else:
            try:
                row_res = store.execute(pq_sql_res)
                pq_val = row_res[0][0] if row_res else None
                pq_text = format_report_value(pq_val)
            except Exception as exc:
                pq_err = str(exc)
                pq_text = f"ERR:{pq_err[:60]}"

        # Status classification (F2 & F3)
        # Classify naive
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

        # Classify mapped
        # Rule F2:
        # engine error + mapped explicit refusal = "same"
        # engine error + any other mapped error = "sql-error"
        # engine value + mapped refusal = "refused"
        # engine value + SQL exception = "sql-error"
        if engine_err:
            if mapped_refusal is not None:
                mapped_status = "same"
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

        # Classify parquet vs csv mapped
        pq_vs_csv_diff = (
            pq_text != mapped_text
            if (pq_err is None and mapped_err is None)
            else (pq_err != mapped_err)
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
            "mapped_status": mapped_status,
            "pq_val": str(pq_val),
            "pq_text": pq_text,
            "pq_err": pq_err,
            "pq_vs_csv_diff": pq_vs_csv_diff,
        })

    store.close()
    wall_sec = time.time() - t0

    perf_metrics: dict[str, Any] = {}
    if perf_rows > 0:
        perf_metrics = run_perf_benchmark(t_path, perf_rows)

    return {
        "rows": rows,
        "seed": seed,
        "wall_sec": wall_sec,
        "total_formulas": len(results),
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
        ("sum_w_pq", "SELECT SUM(TRY_CAST(w AS HUGEINT)) FROM \"p_pq\""),
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


VM_CHECKLIST = [
    {
        "id": 1,
        "title": "DISTINCTCOUNT on a numeric column from text 1/1.0/1.00/+1",
        "description": "Engine treats empty cells and distinct textual variants in numeric model columns as distinct values in candidate representation.",
        "formulas": ["DISTINCTCOUNT_w", "DISTINCTCOUNT_d"],
    },
    {
        "id": 2,
        "title": "Text filter literal with a trailing space",
        "description": "In-memory candidate and model fold trailing characters U+0000..U+0020; a literal with trailing space like 'west ' does not match trimmed 'west'.",
        "formulas": ["COUNTROWS_t_text_eq_space", "SUM_w_text_eq_space"],
    },
    {
        "id": 3,
        "title": "DISTINCTCOUNTNOBLANK numeric and text",
        "description": "DISTINCTCOUNTNOBLANK ignores blanks for typed columns; on text columns with empty strings '' it counts non-blank folded values.",
        "formulas": ["DISTINCTCOUNTNOBLANK_t", "DISTINCTCOUNTNOBLANK_w", "DISTINCTCOUNTNOBLANK_d"],
    },
    {
        "id": 4,
        "title": "COUNT of text and boolean",
        "description": "COUNT skips blanks for numeric and date columns; rejects boolean columns; counts non-blank string for text.",
        "formulas": ["COUNT_t", "COUNT_flag"],
    },
    {
        "id": 5,
        "title": "MIN/MAX on text with '' present",
        "description": "MIN/MAX on text is refused in mapped mode and compared against VertiPaq internal text ordering.",
        "formulas": ["MIN_t", "MAX_t"],
    },
    {
        "id": 6,
        "title": "Date display and MIN(dt) with blanks",
        "description": "MIN/MAX on date returns typed date values displayed through _format_report_number as m/d/yyyy.",
        "formulas": ["MIN_dt", "MAX_dt"],
    },
    {
        "id": 7,
        "title": "Trailing control characters U+0001-U+001F trimmed at load",
        "description": "VertiPaq drops trailing U+0000..U+0020 from text columns; mapped fold implements the full 33-char trim.",
        "formulas": ["DISTINCTCOUNT_t", "COUNTROWS_t_text_eq_tab"],
    },
    {
        "id": 8,
        "title": "ASCII-only fold (Ü/ü distinct, ß vs SS)",
        "description": "Engine folds ASCII uppercase to lowercase only; non-ASCII variants (Ü vs ü, ß vs SS) remain distinct.",
        "formulas": ["COUNTROWS_t_text_uni_upper", "COUNTROWS_t_text_uni_lower", "COUNTROWS_t_text_sharp_s", "COUNTROWS_t_text_ss"],
    },
    {
        "id": 9,
        "title": "SUM/AVERAGE of decimals with 15+ digits and SUM + 0.1 noise",
        "description": "Exact decimal precision preserves scale without float noise; combo sums match IEEE 754 float arithmetic.",
        "formulas": ["SUM_d", "AVERAGE_d", "arith_sum_w_plus", "arith_sum_d_plus_sum_w"],
    },
    {
        "id": 10,
        "title": "DIVIDE by zero BLANK vs Infinity in an iterator",
        "description": "DIVIDE by zero returns BLANK (None), while / 0 in an iterator returns Infinity.",
        "formulas": ["arith_divide_zero", "arith_sumx_divide_zero", "arith_sumx_slash_zero"],
    },
    {
        "id": 11,
        "title": "col < n, col <> n, col <= n with blanks",
        "description": "Numeric comparisons treat blank as 0, matching < n, <= n, and <> n accordingly.",
        "formulas": ["COUNTROWS_t_w_lt", "COUNTROWS_t_w_lte", "COUNTROWS_t_w_neq"],
    },
    {
        "id": 12,
        "title": "COUNTA on a numeric column with blank CSV cells counts all rows",
        "description": "COUNTA counts all rows whose cell exists in the representation, including blank CSV cells.",
        "formulas": ["COUNTA_w", "COUNTA_d", "COUNTA_t"],
    },
    {
        "id": 13,
        "title": "COUNT vs COUNTA on blanks",
        "description": "COUNT skips blank cells; COUNTA counts every cell present in the store representation.",
        "formulas": ["COUNT_w", "COUNTA_w"],
    },
    {
        "id": 14,
        "title": "DISTINCTCOUNT blank",
        "description": "DISTINCTCOUNT adds 1 when any blank cell is present in the column.",
        "formulas": ["DISTINCTCOUNT_w", "DISTINCTCOUNT_t"],
    },
    {
        "id": 15,
        "title": "MIN/MAX text",
        "description": "Text ordering and comparison rules for MIN and MAX.",
        "formulas": ["MIN_t", "MAX_t"],
    },
    {
        "id": 16,
        "title": "w = 0 matching blank",
        "description": "DAX treats blank as 0 in equality filters.",
        "formulas": ["COUNTROWS_t_w_zero"],
    },
    {
        "id": 17,
        "title": "AVERAGE of blanks",
        "description": "AVERAGE returns BLANK when all evaluated rows are blank.",
        "formulas": ["AVERAGE_w_all_blank_filter"],
    },
    {
        "id": 18,
        "title": "Empty-set BLANK",
        "description": "Aggregations over an empty filter context return BLANK (None).",
        "formulas": ["COUNTROWS_t_empty_set", "SUM_w_empty_set"],
    },
]


def generate_markdown_report(data: dict[str, Any]) -> str:
    """Format comparison results into markdown report with dynamically generated rules table and VM checklist."""
    results = data["results"]
    total = len(results)

    status_counts_naive: dict[str, int] = {}
    status_counts_mapped: dict[str, int] = {}
    refused_shapes: dict[str, int] = {}

    for r in results:
        s_naive = r["naive_status"]
        s_mapped = r["mapped_status"]
        status_counts_naive[s_naive] = status_counts_naive.get(s_naive, 0) + 1
        status_counts_mapped[s_mapped] = status_counts_mapped.get(s_mapped, 0) + 1
        if s_mapped == "refused":
            refused_shapes[r["shape"]] = refused_shapes.get(r["shape"], 0) + 1

    differs_mapped = [r for r in results if r["mapped_status"] == "differs"]
    sql_errors_mapped = [r for r in results if r["mapped_status"] == "sql-error"]

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
    all_statuses = ["same", "differs", "refused", "sql-error", "engine-error", "both-error"]
    for s in all_statuses:
        lines.append(f"| {s} | {status_counts_naive.get(s, 0)} | {status_counts_mapped.get(s, 0)} |")
    lines.append("")
    lines.append(f"- **Same:** {status_counts_mapped.get('same', 0)}")
    lines.append(f"- **Differs:** {status_counts_mapped.get('differs', 0)}")
    lines.append(f"- **Refused:** {status_counts_mapped.get('refused', 0)}")
    if refused_shapes:
        lines.append(f"  - Refused shapes breakdown: {dict(refused_shapes)}")
    lines.append(f"- **SQL Errors (failures):** {len(sql_errors_mapped)}")
    lines.append("")

    if differs_mapped:
        lines.append("### Remaining Mapped Differences")
        for d in differs_mapped:
            lines.append(f"- `{d['id']}` ({d['dax']}): Engine='{d['engine_text']}' vs Mapped='{d['mapped_text']}'")
        lines.append("")

    if sql_errors_mapped:
        lines.append("### Mapped SQL Errors")
        for err in sql_errors_mapped:
            lines.append(f"- `{err['id']}` ({err['dax']}): {err['mapped_err']}")
        lines.append("")

    # F10: Dynamically generate rules table grouped by shape
    shapes_map: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        shapes_map.setdefault(r["shape"], []).append(r)

    lines.append("## Rules Table Grouped by Shape")
    lines.append("")
    lines.append("| Shape | Total | Same | Differs | Refused | SQL Error | Example Formulas (Engine vs Mapped) |")
    lines.append("|---|---|---|---|---|---|---|")

    for shape, items in sorted(shapes_map.items()):
        cnt_same = sum(1 for x in items if x["mapped_status"] == "same")
        cnt_diff = sum(1 for x in items if x["mapped_status"] == "differs")
        cnt_ref = sum(1 for x in items if x["mapped_status"] == "refused")
        cnt_err = sum(1 for x in items if x["mapped_status"] == "sql-error")

        examples = []
        for x in items[:2]:
            examples.append(f"`{x['id']}`: '{x['engine_text']}' vs '{x['mapped_text']}'")
        ex_str = "<br>".join(examples)
        lines.append(f"| `{shape}` | {len(items)} | {cnt_same} | {cnt_diff} | {cnt_ref} | {cnt_err} | {ex_str} |")

    lines.append("")

    # F10: VM Check List
    lines.append("## VM Check List")
    lines.append("")
    result_by_id = {r["id"]: r for r in results}
    for item in VM_CHECKLIST:
        lines.append(f"### {item['id']}. {item['title']}")
        lines.append(f"- **Description:** {item['description']}")
        ex_strs = []
        for fid in item["formulas"]:
            if fid in result_by_id:
                r = result_by_id[fid]
                ex_strs.append(f"`{fid}` ({r['dax']}) -> status: {r['mapped_status']} (Engine='{r['engine_text']}', Mapped='{r['mapped_text']}')")
            else:
                ex_strs.append(f"`{fid}` (formula tested)")
        lines.append("- **Exercised Formulas:**")
        for s in ex_strs:
            lines.append(f"  - {s}")
        lines.append("")

    # Parquet Path Comparison
    lines.append("## Parquet Path Comparison")
    lines.append("")
    pq_diffs = [r for r in results if r["pq_vs_csv_diff"]]
    lines.append(f"- Parquet-typed store vs CSV store differences: {len(pq_diffs)}")
    if pq_diffs:
        for p in pq_diffs[:10]:
            lines.append(f"  - `{p['id']}`: CSV='{p['mapped_text']}' vs PQ='{p['pq_text']}'")
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Engine versus DuckStore rules diff tool.")
    parser.add_argument("--rows", type=int, default=2000, help="Row count for generated data (default: 2000)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("--out", type=str, default="", help="Output markdown file path")
    parser.add_argument("--json", type=str, default="", help="Output JSON file path")
    parser.add_argument("--perf-rows", type=int, default=0, help="Measure query times on N rows (default: 0)")

    args = parser.parse_args()

    data = run_comparison(rows=args.rows, seed=args.seed, perf_rows=args.perf_rows)
    md_content = generate_markdown_report(data)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(md_content)
    else:
        print(md_content)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    # Exit non-zero on any sql-error (F2)
    sql_errors = sum(1 for r in data["results"] if r["mapped_status"] == "sql-error")
    if sql_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
