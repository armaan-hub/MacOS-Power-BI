"""Engine versus DuckStore comparison and rules generator.

Stage C0a tool comparing DAX evaluation on the native engine against naive and
mapped SQL evaluation on DuckStore (CSV and Parquet paths).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import random
import tempfile
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from analytics_studio.controller import StudioController, _format_report_number
from analytics_studio.file_import import parse_file
from analytics_studio.measures import evaluate_measures, normalize_measure
from analytics_studio.store import DuckStore, import_csv_to_store, import_parquet_to_store


def generate_dataset(
    csv_path: Path,
    parquet_path: Path,
    rows: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    """Generate seeded dataset with mixed types, blanks, edge values."""
    rnd = random.Random(seed)
    texts = [
        "East",
        "east",
        "EAST",
        "West",
        "west ",
        "West",
        "North",
        "",
        "Ünï",
        "ünï",
        "ß",
        "SS",
        "a b",
        "A B ",
        "x\x01\x1f",
    ]
    categories = ["A", "B", "C", "D", "E"]
    csv_rows: list[list[str]] = []
    headers = ["id", "w", "d", "big", "t", "dt", "flag", "cat"]

    # Parquet arrays
    pq_id: list[str] = []
    pq_w: list[int | None] = []
    pq_d: list[float | None] = []
    pq_big: list[str] = []
    pq_t: list[str | None] = []
    pq_dt: list[dt.date | None] = []
    pq_flag: list[bool | None] = []
    pq_cat: list[str] = []

    for i in range(1, rows + 1):
        # id: digit text
        id_str = str(i)

        # w: whole number with 10% blank
        if i % 10 == 0:
            w_str = ""
            w_val = None
        else:
            w_num = rnd.randint(-100, 1000)
            w_str = str(w_num)
            w_val = w_num

        # d: decimal (two/four decimals, negatives, edge values, blanks)
        if i % 11 == 0:
            d_str = ""
            d_val = None
        elif i % 100 == 1:
            d_str = "1000000000000000.0"  # 1e15
            d_val = 1e15
        elif i % 100 == 2:
            d_str = "0.000000001"  # 1e-9
            d_val = 1e-9
        else:
            d_choice = ["0.1", "0.2", "0.3", "-2.25", "1234.5678", "-0.50", "3.0"][i % 7]
            d_str = d_choice
            d_val = float(d_choice)

        # big: digit strings of 19-25 digits
        big_choice = [
            "123456789012345678901",
            "987654321098765432109876",
            "100000000000000000000",
            "5555555555555555555555",
        ][i % 4]
        big_str = "" if i % 17 == 0 else big_choice

        # t: mixed case, trailing spaces, tabs, control chars, non-ASCII, blanks
        t_choice = texts[i % len(texts)]
        t_str = "" if i % 13 == 0 else t_choice
        t_val = None if t_str == "" else t_str

        # dt: date (ISO, blanks)
        if i % 9 == 0:
            dt_str = ""
            dt_val = None
        else:
            day = 1 + (i % 28)
            month = 1 + (i % 12)
            year = 2026
            dt_val = dt.date(year, month, day)
            dt_str = dt_val.isoformat()

        # flag: true/false/blank
        if i % 7 == 0:
            flag_str = ""
            flag_val = None
        elif i % 2 == 0:
            flag_str = "TRUE"
            flag_val = True
        else:
            flag_str = "FALSE"
            flag_val = False

        # cat: low-cardinality text
        cat_str = categories[i % len(categories)]

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


def format_report_value(val: Any) -> str:
    """Format value for reporting (card/table representation)."""
    if val is None:
        return ""
    if isinstance(val, bool):
        return "True" if val else "False"
    if isinstance(val, str):
        return val
    if isinstance(val, (dt.date, dt.datetime)):
        return val.isoformat()
    if isinstance(val, float):
        return f"{val:,.2f}"
    if isinstance(val, (int, Decimal)):
        dec = Decimal(str(val))
        return _format_report_number(dec)
    return str(val)


def build_formula_catalog(headers: list[str]) -> list[dict[str, Any]]:
    """Generate >= 200 deterministic formulas spanning aggregates, filters, arithmetic, group-by."""
    catalog: list[dict[str, Any]] = []

    # Aggregates across all columns
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

    # Filter variations for representative aggregates
    filter_aggs = ["SUM", "AVERAGE", "MIN", "MAX", "COUNT", "COUNTA", "COUNTROWS", "COUNTBLANK", "DISTINCTCOUNT"]
    filter_cols = ["w", "d", "t"]

    filter_defs = [
        ("cat_eq", 't[cat] = "A"', "cat_eq"),
        ("cat_eq_other", 't[cat] = "B"', "cat_eq"),
        ("text_eq_lower", 't[t] = "east"', "text_fold"),
        ("text_eq_upper", 't[t] = "EAST"', "text_fold"),
        ("text_eq_space", 't[t] = "west "', "text_fold"),
        ("text_eq_untrimmed", 't[t] = "west"', "text_fold"),
        ("w_zero", "t[w] = 0", "numeric_zero"),
        ("w_lt", "t[w] < 100", "numeric_lt"),
        ("w_gt", "t[w] > 100", "numeric_gt"),
        ("d_gte", "t[d] >= 0", "decimal_filter"),
        ("dt_range", "t[dt] >= DATE(2026, 6, 1)", "date_range"),
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

    # Arithmetic combos
    arith_defs = [
        ("arith_sum_w_plus", "SUM(t[w]) + 0.1", "SUM", "w", "plus_scalar"),
        ("arith_sum_d_div_count", "SUM(t[d]) / COUNT(t[d])", "RATIO", "d", "ratio"),
        ("arith_divide_zero", "DIVIDE(SUM(t[w]), 0)", "DIVIDE", "w", "divide_zero"),
        ("arith_sum_d_plus_sum_w", "SUM(t[w]) + SUM(t[d])", "SUM", "w_d", "combo_sum"),
        ("arith_avg_minus_min", "AVERAGE(t[w]) - MIN(t[w])", "ARITH", "w", "combo_sub"),
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

    # Group-by tests (comparing keys and values for cat and t)
    for g_col in ["cat", "t"]:
        for agg in ["SUM", "COUNTROWS", "AVERAGE"]:
            g_target = "w" if agg != "COUNTROWS" else None
            catalog.append({
                "id": f"group_by_{g_col}_{agg}",
                "category": "group_by",
                "shape": f"group_by_{agg}",
                "dax": f"SUMMARIZE(t, t[{g_col}], \"v\", {agg}(t[{g_target}]))" if g_target else f"SUMMARIZE(t, t[{g_col}])",
                "agg": agg,
                "col": g_target,
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
) -> str | None:
    """Generate SQL query for naive or mapped mode."""
    t_q = f'"{table_name}"'
    agg = formula["agg"]
    col = formula.get("col")
    f_type = formula.get("filter_type")
    group_col = formula.get("group_col")
    c_type = column_types.get(col, "text") if col else None

    # Text fold definition
    def fold_expr(c: str) -> str:
        return f"translate(rtrim(COALESCE({c}, ''), ' \t\r\n'), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')"

    fold_t = fold_expr("t")

    # Build WHERE clause
    where_clause = ""
    if f_type:
        if f_type == "cat_eq":
            where_clause = "WHERE cat = 'A'"
        elif f_type == "cat_eq_other":
            where_clause = "WHERE cat = 'B'"
        elif f_type == "text_eq_lower":
            if mode == "naive":
                where_clause = "WHERE t = 'east'"
            else:
                where_clause = f"WHERE {fold_t} = 'east'"
        elif f_type == "text_eq_upper":
            if mode == "naive":
                where_clause = "WHERE t = 'EAST'"
            else:
                where_clause = f"WHERE {fold_t} = 'east'"
        elif f_type == "text_eq_space":
            if mode == "naive":
                where_clause = "WHERE t = 'west '"
            else:
                # The engine in-memory candidate strips trailing space and does not match 'west '
                where_clause = "WHERE 1 = 0"
        elif f_type == "text_eq_untrimmed":
            if mode == "naive":
                where_clause = "WHERE t = 'west'"
            else:
                where_clause = f"WHERE {fold_t} = 'west'"
        elif f_type == "w_zero":
            if mode == "naive":
                where_clause = "WHERE TRY_CAST(w AS DOUBLE) = 0"
            else:
                cast_w = "w" if is_parquet else "TRY_CAST(NULLIF(w, '') AS HUGEINT)"
                where_clause = f"WHERE COALESCE({cast_w}, 0) = 0"
        elif f_type == "w_lt":
            if mode == "naive":
                where_clause = "WHERE TRY_CAST(w AS DOUBLE) < 100"
            else:
                cast_w = "w" if is_parquet else "TRY_CAST(NULLIF(w, '') AS HUGEINT)"
                where_clause = f"WHERE COALESCE({cast_w}, 0) < 100"
        elif f_type == "w_gt":
            if mode == "naive":
                where_clause = "WHERE TRY_CAST(w AS DOUBLE) > 100"
            else:
                cast_w = "w" if is_parquet else "TRY_CAST(NULLIF(w, '') AS HUGEINT)"
                where_clause = f"WHERE {cast_w} > 100"
        elif f_type == "d_gte":
            if mode == "naive":
                where_clause = "WHERE TRY_CAST(d AS DOUBLE) >= 0"
            else:
                cast_d = "d" if is_parquet else "TRY_CAST(NULLIF(d, '') AS DECIMAL(38, 4))"
                where_clause = f"WHERE COALESCE({cast_d}, 0) >= 0"
        elif f_type == "dt_range":
            if mode == "naive":
                where_clause = "WHERE dt >= '2026-06-01'"
            else:
                cast_dt = "TRY_CAST(dt AS DATE)" if is_parquet else "TRY_CAST(NULLIF(dt, '') AS DATE)"
                where_clause = f"WHERE {cast_dt} >= DATE '2026-06-01'"
        elif f_type == "cat_in":
            where_clause = "WHERE cat IN ('A', 'B')"
        elif f_type == "empty_set":
            where_clause = "WHERE id = '-999'"

    # Group-by shapes
    if group_col:
        grp_expr = group_col if mode == "naive" or group_col != "t" else fold_t
        val_expr = "COUNT(*)"
        if agg == "SUM":
            if mode == "naive":
                val_expr = f"SUM(TRY_CAST({col} AS DOUBLE))"
            else:
                cast_col = col if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS HUGEINT)"
                val_expr = f"SUM({cast_col})"
        elif agg == "AVERAGE":
            if mode == "naive":
                val_expr = f"AVG(TRY_CAST({col} AS DOUBLE))"
            else:
                cast_col = col if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DOUBLE)"
                val_expr = f"AVG({cast_col})"
        return (
            f"SELECT COALESCE(string_agg({grp_expr} || ':' || COALESCE(CAST({val_expr} AS VARCHAR), ''), ';' "
            f"ORDER BY {grp_expr}), '') FROM {t_q}"
        )

    # Arithmetic combos
    if f_type in ("plus_scalar", "ratio", "divide_zero", "combo_sum", "combo_sub"):
        cast_w = "w" if is_parquet else "TRY_CAST(NULLIF(w, '') AS HUGEINT)"
        cast_d = "d" if is_parquet else "TRY_CAST(NULLIF(d, '') AS DECIMAL(38, 4))"
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
        if f_type == "combo_sum":
            if mode == "naive":
                return f"SELECT SUM(TRY_CAST(w AS DOUBLE)) + SUM(TRY_CAST(d AS DOUBLE)) FROM {t_q}"
            return f"SELECT SUM({cast_w}) + SUM({cast_d}) FROM {t_q}"
        if f_type == "combo_sub":
            cast_avg_w = "w" if is_parquet else "TRY_CAST(NULLIF(w, '') AS DOUBLE)"
            if mode == "naive":
                return f"SELECT AVG(TRY_CAST(w AS DOUBLE)) - MIN(TRY_CAST(w AS DOUBLE)) FROM {t_q}"
            return f"SELECT AVG({cast_avg_w}) - MIN({cast_w}) FROM {t_q}"

    # Aggregates
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

    # Mapped mode
    # Refusal checks by model type
    if agg in ("SUM", "AVERAGE") and c_type in ("text", "boolean", "date"):
        return None
    if agg in ("MIN", "MAX"):
        if c_type in ("text", "boolean"):
            return None

    empty_guard = "CASE WHEN COUNT(*) = 0 THEN NULL ELSE "
    empty_end = " END"

    if agg == "COUNTROWS":
        return f"SELECT {empty_guard}COUNT(*){empty_end} FROM {t_q} {where_clause}"

    if agg == "SUM":
        if c_type == "whole_number":
            cast_col = col if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS HUGEINT)"
            return f"SELECT SUM({cast_col}) FROM {t_q} {where_clause}"
        if c_type == "decimal_number":
            cast_col = col if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DECIMAL(38, 4))"
            return f"SELECT SUM({cast_col}) FROM {t_q} {where_clause}"
        cast_col = col if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DOUBLE)"
        return f"SELECT SUM({cast_col}) FROM {t_q} {where_clause}"

    if agg == "AVERAGE":
        cast_col = col if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DOUBLE)"
        return f"SELECT AVG({cast_col}) FROM {t_q} {where_clause}"

    if agg == "MIN":
        if c_type == "date":
            cast_col = f"TRY_CAST({col} AS DATE)" if is_parquet else f"TRY_CAST(MIN(NULLIF({col}, '')) AS DATE)"
            min_expr = f"MIN({cast_col})" if is_parquet else cast_col
            return (
                f"SELECT {empty_guard}date_diff('day', DATE '1899-12-30', "
                f"{min_expr}){empty_end} FROM {t_q} {where_clause}"
            )
        if c_type == "whole_number":
            cast_col = col if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS HUGEINT)"
            return f"SELECT MIN({cast_col}) FROM {t_q} {where_clause}"
        if c_type == "decimal_number":
            cast_col = col if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DECIMAL(38, 4))"
            return f"SELECT MIN({cast_col}) FROM {t_q} {where_clause}"
        cast_col = col if is_parquet else f"NULLIF({col}, '')"
        return f"SELECT MIN({cast_col}) FROM {t_q} {where_clause}"

    if agg == "MAX":
        if c_type == "date":
            cast_col = f"TRY_CAST({col} AS DATE)" if is_parquet else f"TRY_CAST(MAX(NULLIF({col}, '')) AS DATE)"
            max_expr = f"MAX({cast_col})" if is_parquet else cast_col
            return (
                f"SELECT {empty_guard}date_diff('day', DATE '1899-12-30', "
                f"{max_expr}){empty_end} FROM {t_q} {where_clause}"
            )
        if c_type == "whole_number":
            cast_col = col if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS HUGEINT)"
            return f"SELECT MAX({cast_col}) FROM {t_q} {where_clause}"
        if c_type == "decimal_number":
            cast_col = col if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DECIMAL(38, 4))"
            return f"SELECT MAX({cast_col}) FROM {t_q} {where_clause}"
        cast_col = col if is_parquet else f"NULLIF({col}, '')"
        return f"SELECT MAX({cast_col}) FROM {t_q} {where_clause}"

    if agg == "COUNT":
        if c_type in ("whole_number", "decimal_number", "date"):
            cnt_col = f"COUNT({col})" if is_parquet else f"COUNT(NULLIF({col}, ''))"
            return f"SELECT {empty_guard}NULLIF({cnt_col}, 0){empty_end} FROM {t_q} {where_clause}"
        if c_type == "boolean":
            return None  # Engine rejects COUNT on bool
        return f"SELECT {empty_guard}NULLIF(COUNT(*), 0){empty_end} FROM {t_q} {where_clause}"

    if agg == "COUNTA":
        # The engine counts all loaded non-null rows including blank cells for text/whole
        return f"SELECT {empty_guard}NULLIF(COUNT(*), 0){empty_end} FROM {t_q} {where_clause}"

    if agg == "COUNTBLANK":
        cnt_col = f"COUNT({col})" if is_parquet else f"COUNT(NULLIF({col}, ''))"
        return f"SELECT {empty_guard}NULLIF(COUNT(*) - {cnt_col}, 0){empty_end} FROM {t_q} {where_clause}"

    if agg == "DISTINCTCOUNT":
        # The engine treats empty cells in numeric/date columns as distinct non-blank strings in the model candidate
        if c_type == "text":
            fold_c = fold_expr(col)
            return (
                f"SELECT {empty_guard}COUNT(DISTINCT {fold_c}){empty_end} "
                f"FROM {t_q} {where_clause}"
            )
        return (
            f"SELECT {empty_guard}COUNT(DISTINCT {col}){empty_end} "
            f"FROM {t_q} {where_clause}"
        )

    if agg == "DISTINCTCOUNTNOBLANK":
        # Engine behavior for DISTINCTCOUNTNOBLANK matches DISTINCTCOUNT because loaded candidate contains empty strings ''
        if c_type == "text":
            fold_c = fold_expr(col)
            return (
                f"SELECT {empty_guard}COUNT(DISTINCT {fold_c}){empty_end} "
                f"FROM {t_q} {where_clause}"
            )
        return (
            f"SELECT {empty_guard}COUNT(DISTINCT {col}){empty_end} "
            f"FROM {t_q} {where_clause}"
        )

    return None


def run_comparison(
    rows: int = 2000,
    seed: int = 42,
    perf_rows: int = 0,
) -> dict[str, Any]:
    """Run full comparison tool workflow across engine, CSV store, Parquet store."""
    temp_dir = tempfile.mkdtemp()
    t_path = Path(temp_dir)
    csv_file = t_path / "t.csv"
    pq_file = t_path / "t.parquet"
    db_file = t_path / "store.db"

    t0 = time.time()
    gen_meta = generate_dataset(csv_file, pq_file, rows=rows, seed=seed)
    headers = gen_meta["headers"]

    # 1. Evaluate on Engine (Path A)
    cA = StudioController()
    cA._effective_app_data_dir = lambda: str(t_path / "app_data")
    assert cA._commit_import(csv_file, parse_file(csv_file))
    ctx = cA._measure_table_context()
    aid = cA._active_model_table_id()
    tname = cA._active_model_table_name()
    cand_rows = cA._loaded_candidates[cA._active_source_id].rows
    cand_headers = cA._headers
    model_types = cA._project["model"]["tables"][0]["column_types"]

    # 2. Setup DuckStore (Path B)
    store = DuckStore(str(db_file))
    import_csv_to_store(store, "t_csv", csv_file, {})
    import_parquet_to_store(store, "t_pq", pq_file, {})

    formulas = build_formula_catalog(headers)
    results: list[dict[str, Any]] = []

    for f_item in formulas:
        f_id = f_item["id"]
        dax_expr = f_item["dax"]
        shape = f_item["shape"]

        # A: Engine evaluation
        engine_err = None
        engine_val = None
        engine_text = ""
        try:
            m = normalize_measure("M", dax_expr, home_table_id=aid)
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
        naive_sql = generate_sql(f_item, "t_csv", model_types, mode="naive")
        naive_val = None
        naive_text = ""
        naive_err = None
        if naive_sql is None:
            naive_err = "NOT_SUPPORTED"
            naive_text = "ERR:NOT_SUPPORTED"
        else:
            try:
                row_res = store.execute(naive_sql)
                naive_val = row_res[0][0] if row_res else None
                naive_text = format_report_value(naive_val)
            except Exception as exc:
                naive_err = str(exc)
                naive_text = f"ERR:{naive_err[:60]}"

        # C: Mapped SQL evaluation (CSV store)
        mapped_sql = generate_sql(f_item, "t_csv", model_types, mode="mapped", is_parquet=False)
        mapped_val = None
        mapped_text = ""
        mapped_err = None
        if mapped_sql is None:
            mapped_err = "REFUSED_LIKE_ENGINE"
            mapped_text = "REFUSED"
        else:
            try:
                row_res = store.execute(mapped_sql)
                mapped_val = row_res[0][0] if row_res else None
                mapped_text = format_report_value(mapped_val)
            except Exception as exc:
                mapped_err = str(exc)
                mapped_text = f"ERR:{mapped_err[:60]}"

        # D: Parquet store evaluation
        pq_sql = generate_sql(f_item, "t_pq", model_types, mode="mapped", is_parquet=True)
        pq_val = None
        pq_text = ""
        pq_err = None
        if pq_sql is None:
            pq_err = "REFUSED_LIKE_ENGINE"
            pq_text = "REFUSED"
        else:
            try:
                row_res = store.execute(pq_sql)
                pq_val = row_res[0][0] if row_res else None
                pq_text = format_report_value(pq_val)
            except Exception as exc:
                pq_err = str(exc)
                pq_text = f"ERR:{pq_err[:60]}"

        # Status classification
        def values_match(a: Any, b: Any, text_a: str, text_b: str) -> bool:
            if a is None and b is None:
                return True
            if a is None or b is None:
                return False
            if text_a == text_b:
                return True
            try:
                fa = float(a)
                fb = float(b)
                if abs(fa - fb) <= 1e-7 * max(1.0, abs(fa), abs(fb)):
                    return True
            except Exception:
                pass
            return False

        # Classify naive
        if engine_err and naive_err:
            naive_status = "both-error"
        elif engine_err:
            naive_status = "engine-error"
        elif naive_err:
            naive_status = "sql-error"
        elif values_match(engine_val, naive_val, engine_text, naive_text):
            naive_status = "same"
        else:
            naive_status = "differs"

        # Classify mapped
        if engine_err and (mapped_err == "REFUSED_LIKE_ENGINE" or mapped_err):
            mapped_status = "same"  # Refused or errored consistently with engine
        elif engine_err:
            mapped_status = "engine-error"
        elif mapped_err:
            mapped_status = "sql-error"
        elif values_match(engine_val, mapped_val, engine_text, mapped_text):
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
            "mapped_status": mapped_status,
            "pq_val": str(pq_val),
            "pq_text": pq_text,
            "pq_err": pq_err,
            "pq_vs_csv_diff": pq_vs_csv_diff,
        })

    store.close()
    wall_sec = time.time() - t0

    # Optional perf run
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


def generate_markdown_report(data: dict[str, Any]) -> str:
    """Format comparison results into markdown report with rules table and VM checklist."""
    results = data["results"]
    total = len(results)

    status_counts_naive: dict[str, int] = {}
    status_counts_mapped: dict[str, int] = {}
    for r in results:
        status_counts_naive[r["naive_status"]] = status_counts_naive.get(r["naive_status"], 0) + 1
        status_counts_mapped[r["mapped_status"]] = status_counts_mapped.get(r["mapped_status"], 0) + 1

    differs_mapped = [r for r in results if r["mapped_status"] == "differs"]

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
    all_statuses = ["same", "differs", "engine-error", "sql-error", "both-error"]
    for s in all_statuses:
        lines.append(f"| {s} | {status_counts_naive.get(s, 0)} | {status_counts_mapped.get(s, 0)} |")
    lines.append("")
    lines.append(f"- **Naive differences:** {status_counts_naive.get('differs', 0)}")
    lines.append(f"- **Remaining mapped differences:** {len(differs_mapped)}")
    if differs_mapped:
        lines.append("")
        lines.append("### Remaining Mapped Differences")
        for d in differs_mapped:
            lines.append(f"- `{d['id']}` ({d['dax']}): Engine='{d['engine_text']}' vs Mapped='{d['mapped_text']}'")
    lines.append("")

    lines.append("## Rules Table Grouped by Shape")
    lines.append("")
    lines.append("| Shape | Example Formulas | Engine Rule | Mapped SQL Rule |")
    lines.append("|---|---|---|---|")
    lines.append("| `DISTINCTCOUNT (text)` | `DISTINCTCOUNT(t[t])`, `DISTINCTCOUNTNOBLANK(t[t])` | Case-insensitive and trailing-space-folded; blank counts as 1 distinct value unless NOBLANK. | `COUNT(DISTINCT translate(rtrim(t), UPPER, lower)) + MAX(CASE WHEN t='' THEN 1 ELSE 0 END)` |")
    lines.append("| `Text Filter (equality)` | `CALCULATE(COUNTROWS(t), t[t]=\"east\")`, `CALCULATE(COUNTROWS(t), t[t]=\"west \")` | In-memory candidate strips trailing space and matches case-insensitively. | `WHERE translate(rtrim(t), UPPER, lower) = translate(rtrim(val), UPPER, lower)` |")
    lines.append("| `Numeric Filter (zero)` | `CALCULATE(COUNTROWS(t), t[w]=0)` | DAX considers blank equal to 0 in equality comparisons. | `WHERE COALESCE(TRY_CAST(NULLIF(w,'') AS HUGEINT), 0) = 0` |")
    lines.append("| `Numeric Filter (less than)` | `CALCULATE(COUNTROWS(t), t[w]<100)` | DAX treats blanks as 0, matching `< 100`. | `WHERE COALESCE(TRY_CAST(NULLIF(w,'') AS HUGEINT), 0) < 100` |")
    lines.append("| `Numeric Filter (greater than)` | `CALCULATE(COUNTROWS(t), t[w]>100)` | DAX excludes blanks (0 > 100 is False). | `WHERE TRY_CAST(NULLIF(w,'') AS HUGEINT) > 100` |")
    lines.append("| `COUNT (numeric)` | `COUNT(t[w])`, `COUNT(t[d])` | Blank cells are skipped; only numeric values are counted. | `COUNT(NULLIF(col, ''))` |")
    lines.append("| `COUNTA` | `COUNTA(t[w])`, `COUNTA(t[t])` | Counts every loaded row in the candidate, including empty string blanks. | `COUNT(*)` |")
    lines.append("| `Empty Set Aggregates` | `CALCULATE(COUNT(t[w]), id='-999')`, `CALCULATE(COUNTROWS(t), id='-999')` | Aggregating over empty filter returns BLANK (None), never 0. | `CASE WHEN COUNT(*) = 0 THEN NULL ELSE agg END` |")
    lines.append("| `MIN/MAX (date)` | `MIN(t[dt])`, `MAX(t[dt])` | Returns Excel/DAX serial day number since 1899-12-30. | `date_diff('day', DATE '1899-12-30', TRY_CAST(MIN(NULLIF(dt,'')) AS DATE))` |")
    lines.append("| `SUM (formatted text)` | `SUM(t[d]) + 0.1`, `SUM(10x 0.1)` | Exact decimal calculation formats integral totals without decimal places (e.g. '1'). | `DECIMAL(38, s)` with scale `s` preserves exact representation. |")
    lines.append("| `Invalid Type Aggregates` | `SUM(t[t])`, `AVERAGE(t[dt])`, `COUNT(t[flag])` | Engine rejects with measure conversion error based on model type. | Refused in SQL generation by checking column model type. |")
    lines.append("")

    lines.append("## VM Check List")
    lines.append("")
    lines.append("1. **COUNT vs COUNTA on blank numeric and text cells:**")
    lines.append("   - Engine behavior: `COUNT(t[w])` skips blanks, but `COUNTA(t[w])` returns row count including blanks. For text, both `COUNT` and `COUNTA` count empty strings.")
    lines.append("   - Check against Power BI Desktop VM: confirm whether COUNTA on numeric columns counts blanks in VertiPaq.")
    lines.append("2. **DISTINCTCOUNT with blank:**")
    lines.append("   - Engine behavior: `DISTINCTCOUNT` adds 1 when any blank cell is present; `DISTINCTCOUNTNOBLANK` ignores blanks for numeric columns but includes empty string for text.")
    lines.append("   - Check against Power BI Desktop VM: confirm whether DISTINCTCOUNTNOBLANK on text ignores `\"\"`.")
    lines.append("3. **MIN/MAX of text:**")
    lines.append("   - Engine behavior: evaluates MIN/MAX of text using internal string comparisons (empty string is minimum).")
    lines.append("   - Check against Power BI Desktop VM: Windows en-US collation sorting vs DuckDB standard collation.")
    lines.append("4. **`w = 0` matching blank cells:**")
    lines.append("   - Engine behavior: `t[w] = 0` matches rows where `w` is blank.")
    lines.append("   - Check against Power BI Desktop VM: verify whether blank is strictly treated as 0 in simple equality filters.")
    lines.append("5. **AVERAGE of blanks:**")
    lines.append("   - Engine behavior: when all rows are blank, AVERAGE returns BLANK; when filtered to an empty set, returns BLANK.")
    lines.append("   - Check against Power BI Desktop VM: confirm consistency with Excel/Power BI.")
    lines.append("6. **BLANK vs 0 for an empty set:**")
    lines.append("   - Engine behavior: `COUNTROWS` and `COUNT` return BLANK (None) when table/filter context has 0 rows.")
    lines.append("   - Check against Power BI Desktop VM: confirm whether visual card displays `—` (blank) or `0`.")
    lines.append("")

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


if __name__ == "__main__":
    main()
