"""DAX to DuckDB SQL for the store (Stage C1b1).

Turns a measure expression that the whitelist (dax_whitelist.classify_measure) allows into one SELECT on the
store table and converts the SQL result into the SAME Python value the engine returns. The default answer is
REFUSE: a wrong value here is a silent wrong answer, so every rule is proved against the real engine by the rules
tool (tools/store_engine_diff.py, run_comparison with use_plan=True).

The first part of this module holds the code moved without a logic change from the rules tool (Refusal, the
result layer, the fold expression, the legacy WHERE clauses, the mapped SQL builder and the store metadata).
The second part is the planner (plan_measure).

A plan is a snapshot: it keeps the decimal scale and digit counts read from the store when it was built (and
re-reads them on every execute). After a reload or `append_rows` that changes those, `execute` returns a
Refusal ("plan is stale; rebuild it"): REBUILD the plan after any reload or append. Guards (non-ASCII text,
unreadable dates, stale decimal metadata) run as cheap queries on every execute and are never cached.
"""

from __future__ import annotations

import datetime as _dt
import string
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping

from analytics_studio import dax_dates
from analytics_studio.measures import MeasureError, parse_expression
from analytics_studio.store.dax_whitelist import (
    MAX_PREDICATES,
    REASON_CAP_PREDICATES,
    _canonical_type,
    REASON_IN_FOLD_EQ_MIX,
    _collect_references,
    _in_item_folds_differently,
    classify_filter_context,
    classify_measure,
    in_mix_reason,
)
from analytics_studio.store.text_rules import TRIM_CHARS_SQL, first_spelling_expr_sql, first_spelling_sql, fold_sql, trim_sql


# The one Parquet refusal that the Parquet difference class parquet_counta_refusal accepts
PARQUET_COUNTA_REFUSAL_REASON = "COUNTA on Parquet typed columns differs from CSV store"


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


# ==============================================================================
# SECTION: RESULT LAYER (Aggregates from SQL, Arithmetic via Decimal layer)
# ==============================================================================

class StoreResultLayer:
    """Prototypes the app's execution layer: aggregate leaves from SQL, exact Decimal arithmetic."""

    @staticmethod
    def divide(sum_val: Any, cnt_val: Any, overrides: dict[str, Any] | None = None) -> Decimal | None:
        if sum_val is None or cnt_val is None or cnt_val == 0:
            return None
        overrides = overrides or {}
        res = Decimal(str(sum_val)) / Decimal(str(cnt_val))
        if overrides.get("trunc_div_4"):
            return res.quantize(Decimal("0.0001"))
        return res

    @staticmethod
    def divide_ratio(sum_val: Any, cnt_val: Any, overrides: dict[str, Any] | None = None) -> Decimal | None:
        if sum_val is None or cnt_val is None or cnt_val == 0:
            return None
        overrides = overrides or {}
        # In DAX, binary `/` between measures evaluates in IEEE 754 float
        f_val = float(sum_val) / float(cnt_val)
        # Exact binary value of the float: the engine prints the full binary tail, not the shortest repr
        res = Decimal(f_val)
        if overrides.get("trunc_div_4"):
            return res.quantize(Decimal("0.0001"))
        return res

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
    if trim_arg == TRIM_CHARS_SQL:
        return fold_sql(c)
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


def _pq_dec(c: str, scale: int, overrides: dict[str, Any]) -> str:
    """Parquet DOUBLE to exact DECIMAL via its shortest text form (the cast the store uses)."""
    if overrides.get("pq_decimal_direct_cast"):
        return f"CAST({c} AS DECIMAL(38, {scale}))"
    return f"CAST(CAST({c} AS VARCHAR) AS DECIMAL(38, {scale}))"


def average_cast_sql(col: str, c_type: str | None, scale: int, is_parquet: bool, overrides: dict[str, Any]) -> str:
    """The exact cast an AVERAGE sums and counts (the legacy EXACT_AVERAGE leaf)."""
    if overrides.get("csv_avg_scale_3") and not is_parquet:
        cast_c = f"TRY_CAST(NULLIF({col}, '') AS DECIMAL(38, 3))"
    elif c_type == "whole_number":
        cast_c = col if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS HUGEINT)"
    else:
        cast_c = (
            _pq_dec(col, 0 if overrides.get("pq_avg_scale0") else (3 if overrides.get("pq_avg_scale3") else scale), overrides)
            if is_parquet
            else f"TRY_CAST(NULLIF({col}, '') AS DECIMAL(38, {scale}))"
        )
    return cast_c


def aggregate_sql(
    agg: str,
    col: str | None,
    c_type: str | None,
    where_clause: str,
    scale: int,
    *,
    t_q: str,
    is_parquet: bool = False,
    overrides: dict[str, Any] | None = None,
) -> str | Refusal | None:
    """SQL of one aggregate leaf over a quoted table t_q with a ready WHERE clause.

    Shared by the legacy mapped builder (generate_mapped_sql) and the planner (plan_measure). `scale` is the
    decimal scale of the aggregated column. AVERAGE returns the legacy token "EXACT_AVERAGE:<cast>:<where>".
    """
    overrides = overrides or {}
    if overrides.get("drop_empty_guard"):
        empty_guard = ""
        empty_end = ""
    else:
        empty_guard = "CASE WHEN COUNT(*) = 0 THEN NULL ELSE "
        empty_end = " END"

    def pq_dec(c: str, scale: int) -> str:
        """Parquet DOUBLE to exact DECIMAL via its shortest text form (the cast the store uses)."""
        return _pq_dec(c, scale, overrides)

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
                    pq_dec(col, scale)
                    if is_parquet
                    else f"TRY_CAST(NULLIF({col}, '') AS DECIMAL(38, {scale}))"
                )
            return f"SELECT {empty_guard}SUM({cast_col}){empty_end} FROM {t_q} {where_clause}"
        cast_col = col if is_parquet else f"TRY_CAST(NULLIF({col}, '') AS DOUBLE)"
        return f"SELECT {empty_guard}SUM({cast_col}){empty_end} FROM {t_q} {where_clause}"


    if agg == "AVERAGE":
        # Work item A2: Return special token so run_comparison executes exact sum and count
        cast_c = average_cast_sql(col, c_type, scale, is_parquet, overrides)
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
                pq_dec(col, scale)
                if is_parquet
                else f"TRY_CAST(NULLIF({col}, '') AS DECIMAL(38, {scale}))"
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
                pq_dec(col, scale)
                if is_parquet
                else f"TRY_CAST(NULLIF({col}, '') AS DECIMAL(38, {scale}))"
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
            cnt_nonblank = f"COUNT(NULLIF({trim_sql(col)}, ''))"
        else:
            cnt_nonblank = f"COUNT({col})" if is_parquet else f"COUNT(NULLIF({col}, ''))"
        return f"SELECT {empty_guard}NULLIF(COUNT(*) - {cnt_nonblank}, 0){empty_end} FROM {t_q} {where_clause}"

    if agg == "DISTINCTCOUNT":
        if c_type == "text":
            fold_c = make_fold_expr(col, agg, overrides)
            blank_add = f"MAX(CASE WHEN {trim_sql(col)} = '' THEN 1 ELSE 0 END)"
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
            cast_type = "HUGEINT" if c_type == "whole_number" else f"DECIMAL(38, {scale})" if c_type == "decimal_number" else "DATE" if c_type == "date" else "BOOLEAN"
            cast_c = f"TRY_CAST(NULLIF({col}, '') AS {cast_type})"
            if overrides.get("m14_distinct_no_blank_add"):
                return f"SELECT {empty_guard}COUNT(DISTINCT {cast_c}){empty_end} FROM {t_q} {where_clause}"
            blank_add = f"MAX(CASE WHEN COALESCE({col}, '') = '' THEN 1 ELSE 0 END)"
            return f"SELECT {empty_guard}COUNT(DISTINCT {cast_c}) + {blank_add}{empty_end} FROM {t_q} {where_clause}"

    return None


def generate_mapped_sql(
    formula: dict[str, Any],
    table_name: str,
    column_types: dict[str, str],
    is_parquet: bool = False,
    store_meta: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
) -> str | Refusal | None:
    """Legacy mapped SQL, token or explicit Refusal of one catalog formula (the mapped part of generate_sql)."""
    overrides = overrides or {}
    mode = "mapped"
    t_q = f'"{table_name}"'
    agg = formula["agg"]
    col = formula.get("col")
    f_type = formula.get("filter_type")
    group_col = formula.get("group_col")
    c_type = column_types.get(col, "text") if col else None

    # Refusal B1: numeric IN / && filters with blank cells error on old engine
    if f_type in ("w_in", "filter_two_cols"):
        return Refusal(
            "Engine bug: numeric IN or && filter with blank cells raises type error",
            expected_error="Cannot convert value '' of type Text to type Number.",
        )
    if f_type == "dt_in":
        return Refusal(
            "Engine bug: date IN filter with blank cells raises type error",
            expected_error="Cannot convert value '46174' of type Text to type Date.",
        )

    # Refusal D2: COUNT of a text column
    if agg == "COUNT" and c_type == "text":
        return Refusal("COUNT not supported on text column", expected_error="type error")

    # Refusal D1: DISTINCTCOUNTNOBLANK on store
    if agg == "DISTINCTCOUNTNOBLANK":
        if overrides.get("noblank_equals_distinctcount"):
            pass
        else:
            return Refusal("DISTINCTCOUNTNOBLANK not supported on store")
    if col == "w_blank" and agg in ("SUM", "AVERAGE"):
        return Refusal(
            f"{agg} not supported on text column",
            expected_error=f"The function {agg} cannot work with values of type String.",
        )

    # Refusal: Parquet COUNTA
    if agg == "COUNTA" and is_parquet and not overrides.get("pq_counta_no_refusal"):
        return Refusal(PARQUET_COUNTA_REFUSAL_REASON)

    # Aggregated column scale (the filtered column scale is handled in build_where_clause)
    agg_d_scale = 4 if overrides.get("hardcode_scale_4") else (store_meta or {}).get("decimal_scales", {}).get(col, 4)
    if col == "w_d":
        agg_d_scale = 4 if overrides.get("hardcode_scale_4") else (store_meta or {}).get("decimal_scales", {}).get("d", 4)

    # Check 38 digit total limit refusal
    max_digits = (store_meta or {}).get("max_digits", {}).get(col, 0)
    if max_digits > 38:
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
            return "PLUS_SCALAR"
        if f_type == "ratio":
            return "RATIO"
        if f_type == "divide_zero":
            return "SELECT NULL"
        if f_type == "sumx_divide_zero":
            return "SELECT NULL"
        if f_type == "sumx_slash_zero":
            return f"SELECT SUM(CAST({cast_w} AS DOUBLE) / 0.0) FROM {t_q}"
        if f_type == "combo_sum":
            # Work item A3 / Result layer: return special token so run_comparison executes exact leaf sums
            return "COMBO_SUM"
        if f_type == "combo_sub":
            return "COMBO_SUB"

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

    return aggregate_sql(
        agg, col, c_type, where_clause, agg_d_scale, t_q=t_q, is_parquet=is_parquet, overrides=overrides
    )


@dataclass(frozen=True)
class ColumnMeta:
    """Decimal scale and max digit count of one store column (filled by column_decimal_meta)."""

    scale: int
    digits: int


def column_decimal_meta(store: Any, table: str, columns: list[str]) -> dict[str, ColumnMeta]:
    """Decimal scale (at least 4) and max digit count per column of a physical store table.

    Column and table names are quoted. A column whose metadata query fails is left OUT of the result (never
    given a made-up scale): plan_measure then refuses a decimal use of it with "no decimal metadata".
    """
    meta: dict[str, ColumnMeta] = {}
    t_q = quote_identifier(table)
    for col in columns:
        c_q = quote_identifier(col)
        try:
            scale_res = store.execute(
                f"SELECT COALESCE(MAX(CASE WHEN strpos({c_q}, '.') > 0 "
                f"THEN length(regexp_extract({c_q}, '\\.([0-9]+)', 1)) ELSE 0 END), 0) FROM {t_q}"
            )
            digits_res = store.execute(
                f"SELECT COALESCE(MAX(length(regexp_replace({c_q}, '[^0-9]', '', 'g'))), 0) FROM {t_q}"
            )
            scale = max(4, int(scale_res[0][0])) if scale_res else 4
            digits = int(digits_res[0][0]) if digits_res else 0
        except Exception:
            continue
        meta[col] = ColumnMeta(scale, digits)
    return meta


# ==============================================================================
# SECTION: PLANNER (Stage C1b1): an allowed expression becomes one SELECT and one Python value
# ==============================================================================

PARQUET_PLAN_REASON = "Parquet plan is not on the store path yet"
REASON_IN_NON_ASCII_COLUMN = (
    "the IN, blank-literal or equality-beside-IN column holds non-ASCII text; the engine folds and trims it differently"
)
REASON_DATE_UNREADABLE = "date column holds text the store cannot read the way the engine does"
REASON_PLAN_STALE = "plan is stale; rebuild it"
REASON_DECIMAL_LITERAL_FIT = "literal does not fit the column's decimal precision"
MAX_DECIMAL_TOTAL = 38

# The store's own load-order column. The physical rowid is the load order only on a fresh import: after a
# re-sort or a derived table it is not, so any "first seen" order must use "__rn".
STORE_ORDER_COLUMN = '"__rn"'

# DAX comparison operator to SQL operator. Only these six exist; an operator not in the table is refused.
_SQL_OPERATORS: dict[str, str] = {"=": "=", "<>": "<>", "<": "<", "<=": "<=", ">": ">", ">=": ">="}
_OR_JOIN = " OR "
_AND_JOIN = " AND "
_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)


def in_column_has_non_ascii(store: Any, guard: tuple[str, str]) -> bool:
    """Does any cell of the (physical table, column) hold a non-ASCII character? One cheap query, never cached."""
    t_q, c_q = quote_identifier(guard[0]), quote_identifier(guard[1])
    rows = store.execute(f"SELECT EXISTS (SELECT 1 FROM {t_q} WHERE strlen({c_q}) <> length({c_q}))")
    return bool(rows and rows[0][0])


def run_plan_guards(
    store: Any,
    *,
    in_guards: tuple[tuple[str, str], ...] = (),
    date_guards: tuple[tuple[str, str], ...] = (),
    decimal_stamps: tuple[tuple[str, str, int, int], ...] = (),
) -> Refusal | None:
    """The cheap per-execute guard queries shared by every plan kind: a Refusal on the first failure, else None.

    Never cached: the store can change between two executes of one plan.
    """
    for physical, column, scale, digits in decimal_stamps:
        now = column_decimal_meta(store, physical, [column]).get(column)
        if now is None or now.scale != scale or now.digits != digits:
            return Refusal(REASON_PLAN_STALE)
    for guard in in_guards:
        if in_column_has_non_ascii(store, guard):
            return Refusal(REASON_IN_NON_ASCII_COLUMN)
    for physical, column in date_guards:
        t_q, c_q = quote_identifier(physical), quote_identifier(column)
        rows = store.execute(
            f"SELECT EXISTS (SELECT 1 FROM {t_q} WHERE {c_q} IS NOT NULL AND trim({c_q}) <> '' "
            f"AND TRY_CAST({c_q} AS DATE) IS NULL)"
        )
        if rows and rows[0][0]:
            return Refusal(REASON_DATE_UNREADABLE)
    return None


@dataclass(frozen=True)
class MeasurePlan:
    """One SELECT on the store and the rule that turns its result into the engine's Python value.

    kind is "scalar" (the first cell is the value) or "average" (the SELECT returns SUM and COUNT and the value
    is their exact quotient). value_type is "number" (Decimal) or "date" (DaxDateTime).
    """

    kind: str
    sql: str
    table: str
    shape: str
    value_type: str = "number"
    overrides: Mapping[str, Any] | None = field(default=None, compare=False, repr=False)
    in_guards: tuple[tuple[str, str], ...] = ()
    date_guards: tuple[tuple[str, str], ...] = ()
    decimal_stamps: tuple[tuple[str, str, int, int], ...] = ()

    def _in_column_has_non_ascii(self, store: Any, guard: tuple[str, str]) -> bool:
        """One cheap query per (table, column) on EVERY execute: does any cell hold a non-ASCII character?

        Never cached: the store can gain a non-ASCII cell between two executes of one plan.
        """
        return in_column_has_non_ascii(store, guard)

    def execute(self, store: Any) -> Decimal | dax_dates.DaxDateTime | Refusal | None:
        """Run the SELECT through the store's public read call and return the engine's value.

        A plan with a text IN (on its IN column AND on every text-equality column of the same plan), or a text
        equality with an empty or whitespace-only literal, first checks that column for non-ASCII cells on every
        execute (the engine casefolds and trims those differently from the store's ASCII-only rules). A date
        column the plan reads must hold only text the store can cast; a decimal column must still have the scale
        and digits the plan was built with. If a guard fails the answer is a Refusal and the aggregate query is
        not run.
        """
        refused = run_plan_guards(store, decimal_stamps=self.decimal_stamps)
        if refused is not None:
            return refused
        for guard in self.in_guards:
            if self._in_column_has_non_ascii(store, guard):
                return Refusal(REASON_IN_NON_ASCII_COLUMN)
        refused = run_plan_guards(store, date_guards=self.date_guards)
        if refused is not None:
            return refused
        rows = store.execute(self.sql)
        if self.kind == "average":
            sum_val, count_val = rows[0] if rows else (None, None)
            return StoreResultLayer.divide(sum_val, count_val, overrides=dict(self.overrides or {}))
        cell = rows[0][0] if rows else None
        return convert_result(cell, self.value_type)


def to_decimal(value: Any) -> Decimal:
    """An SQL integer or Decimal as an exact Decimal. A float is a bug, never converted."""
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError(f"unexpected SQL result type {type(value).__name__}")
    if isinstance(value, (int, Decimal)):
        return Decimal(value)
    raise TypeError(f"unexpected SQL result type {type(value).__name__}")


def to_dax_date(value: Any) -> dax_dates.DaxDateTime:
    """An SQL date as the DaxDateTime the engine returns for a date column."""
    if isinstance(value, _dt.datetime) or not isinstance(value, _dt.date):
        raise TypeError(f"unexpected SQL result type {type(value).__name__}")
    return dax_dates.from_datetime(_dt.datetime.combine(value, _dt.time.min))


def convert_result(cell: Any, value_type: str) -> Decimal | dax_dates.DaxDateTime | None:
    """One SQL result cell as the engine's value: SQL NULL is None (BLANK)."""
    if cell is None:
        return None
    if value_type == "date":
        return to_dax_date(cell)
    return to_decimal(cell)


def quote_identifier(name: str) -> str:
    """A column or table name as a double-quoted SQL identifier."""
    return '"' + name.replace('"', '""') + '"'


def _fold_literal(text: str) -> str:
    """A text literal as the engine compares it: ASCII A-Z lower-cased, never trimmed."""
    return text.translate(_ASCII_LOWER)


def _sql_string(text: str) -> str:
    """A SQL string literal; a single quote is doubled."""
    return "'" + text.replace("'", "''") + "'"


def text_predicate_sql(col: str, op: str, literal: str) -> str:
    """Text comparison: the folded cell against the literal with only A-Z lower-cased."""
    return f"{fold_sql(col)} {_SQL_OPERATORS[op]} {_sql_string(_fold_literal(literal))}"


def text_in_sql(col: str, items: list[str]) -> str:
    """Text IN: the folded cell against the lower-cased literals."""
    listed = ", ".join(_sql_string(_fold_literal(item)) for item in items)
    return f"{fold_sql(col)} IN ({listed})"


def _whole_cell(col: str) -> str:
    return f"COALESCE(TRY_CAST(NULLIF({col}, '') AS HUGEINT), 0)"


def whole_predicate_sql(col: str, op: str, literal: int) -> str:
    """Whole number comparison: a blank cell counts as 0."""
    return f"{_whole_cell(col)} {_SQL_OPERATORS[op]} {int(literal)}"


def whole_not_predicate_sql(col: str, literal: int) -> str:
    """NOT over a whole-number equality: the blank cell is 0 first, then the comparison is negated."""
    return f"NOT ({whole_predicate_sql(col, '=', literal)})"


def whole_or_sql(col: str, literals: list[int]) -> str:
    """A || chain of whole-number equalities on one column."""
    return "(" + _OR_JOIN.join(whole_predicate_sql(col, "=", lit) for lit in literals) + ")"


def decimal_predicate_sql(col: str, op: str, literal: Decimal, scale: int) -> str:
    """Decimal comparison at scale `scale`: a blank cell counts as 0."""
    cell = f"COALESCE(TRY_CAST(NULLIF({col}, '') AS DECIMAL(38, {scale})), 0)"
    return f"{cell} {_SQL_OPERATORS[op]} CAST({format(literal, 'f')} AS DECIMAL(38, {scale}))"


def date_predicate_sql(col: str, op: str, day: _dt.date) -> str:
    """Date comparison: a blank cell counts as DATE '1899-12-30'."""
    cell = f"COALESCE(TRY_CAST(NULLIF({col}, '') AS DATE), DATE '1899-12-30')"
    return f"{cell} {_SQL_OPERATORS[op]} DATE '{day.isoformat()}'"


def first_spelling_query(store_table: str, column: str) -> str:
    """first_spelling_sql ordered by the store's own "__rn" (not the physical rowid)."""
    return first_spelling_sql(quote_identifier(store_table), quote_identifier(column), rowid=STORE_ORDER_COLUMN)


def _number_literal(node: Any) -> Decimal | None:
    """Exact signed value of a number literal or a unary minus over one."""
    sign = 1
    if isinstance(node, tuple) and node and node[0] == "unary" and node[1] == "-":
        sign = -1
        node = node[2]
    if isinstance(node, tuple) and len(node) > 2 and node[0] == "number" and isinstance(node[1], Decimal):
        return -node[1] if sign < 0 else node[1]
    return None


def _date_literal(node: Any) -> _dt.date | None:
    """The date of a DATE(y, m, d) literal, else None."""
    if not (isinstance(node, tuple) and len(node) == 3 and node[0] == "call" and node[1] == "DATE"):
        return None
    try:
        year, month, day = (int(a[2]) for a in node[2])
        return _dt.date(year, month, day)
    except (TypeError, ValueError, IndexError):
        return None


@dataclass(frozen=True)
class _Resolved:
    table: str
    column: str
    col_type: str


class _Planner:
    """Everything one plan_measure call needs: the case-folded names, metadata and hooks."""

    def __init__(
        self,
        home_table: str,
        tables: Mapping[str, Mapping[str, str]],
        column_meta: Mapping[tuple[str, str], ColumnMeta],
        overrides: Mapping[str, Any],
    ) -> None:
        self.home = home_table.casefold()
        self.tables = {t.casefold(): (t, {c.casefold(): (c, ty) for c, ty in cols.items()}) for t, cols in tables.items()}
        self.meta = {(t.casefold(), c.casefold()): m for (t, c), m in column_meta.items()}
        self.overrides = dict(overrides)
        self.in_columns: list[tuple[str, str]] = []
        self.eq_columns: list[tuple[str, str]] = []
        self.date_columns: list[tuple[str, str]] = []
        self.decimal_columns: list[tuple[str, str, ColumnMeta]] = []
        self.has_in = False

    def resolve(self, ref: Any) -> _Resolved | Refusal:
        if not (isinstance(ref, tuple) and len(ref) == 3 and ref[0] == "reference"):
            return Refusal("not a column reference")
        table_fold = (ref[1] or "").casefold() or self.home
        entry = self.tables.get(table_fold)
        if entry is None:
            return Refusal(f"unknown table '{ref[1]}'")
        table_name, columns = entry
        found = columns.get(ref[2].casefold())
        if found is None:
            return Refusal(f"unknown column '{ref[2]}'")
        canonical, reason = _canonical_type(found[1])
        if canonical is None:
            return Refusal(reason or "unknown column type")
        return _Resolved(table_name, found[0], canonical)

    def meta_for(self, resolved: _Resolved) -> ColumnMeta | None:
        return self.meta.get((resolved.table.casefold(), resolved.column.casefold()))

    def predicate(self, node: Any) -> str | Refusal:
        """SQL of one admitted predicate node; any other shape is refused."""
        if not (isinstance(node, tuple) and node):
            return Refusal("unsupported predicate")
        kind = node[0]
        if kind == "comparison":
            return self._comparison(node)
        if kind == "in":
            return self._in(node)
        if kind == "call" and node[1] == "NOT" and len(node[2]) == 1:
            leaf = self._whole_equality(node[2][0])
            if isinstance(leaf, Refusal):
                return leaf
            return whole_not_predicate_sql(quote_identifier(leaf[0].column), leaf[1])
        if kind == "logical" and node[1] == "||":
            leaves: list[Any] = []
            stack: list[Any] = [node]
            while stack:
                current = stack.pop()
                if isinstance(current, tuple) and current and current[0] == "logical" and current[1] == "||":
                    stack.append(current[3])
                    stack.append(current[2])
                else:
                    leaves.append(current)
            columns: set[str] = set()
            literals: list[int] = []
            column = ""
            for leaf_node in leaves:
                leaf = self._whole_equality(leaf_node)
                if isinstance(leaf, Refusal):
                    return leaf
                columns.add(f"{leaf[0].table.casefold()}\0{leaf[0].column.casefold()}")
                column = leaf[0].column
                literals.append(leaf[1])
            if len(columns) != 1:
                return Refusal("all operands of || must be on the same column")
            return whole_or_sql(quote_identifier(column), literals)
        return Refusal("unsupported predicate")

    def _whole_equality(self, node: Any) -> tuple[_Resolved, int] | Refusal:
        if not (isinstance(node, tuple) and node and node[0] == "comparison" and node[1] == "="):
            return Refusal("unsupported predicate")
        resolved = self.resolve(node[2])
        if isinstance(resolved, Refusal):
            return resolved
        value = _number_literal(node[3])
        if resolved.col_type != "whole_number" or value is None or value != value.to_integral_value():
            return Refusal("unsupported predicate")
        return resolved, int(value)

    def _comparison(self, node: tuple[Any, ...]) -> str | Refusal:
        op = node[1]
        if op not in _SQL_OPERATORS:
            return Refusal(f"operator {op} is not supported")
        resolved = self.resolve(node[2])
        if isinstance(resolved, Refusal):
            return resolved
        col = quote_identifier(resolved.column)
        right = node[3]
        if resolved.col_type == "text":
            if op != "=" or not (isinstance(right, tuple) and right and right[0] == "string"):
                return Refusal("unsupported text predicate")
            refused = self._text_checked(right[1], lambda: text_predicate_sql(col, op, right[1]))
            if isinstance(refused, str):
                self.eq_columns.append((resolved.table, resolved.column))
                if right[1].strip() == "":
                    self.in_columns.append((resolved.table, resolved.column))
            return refused
        if resolved.col_type == "whole_number":
            value = _number_literal(right)
            if value is None or value != value.to_integral_value():
                return Refusal("unsupported whole-number predicate")
            return whole_predicate_sql(col, op, int(value))
        if resolved.col_type == "decimal_number":
            value = _number_literal(right)
            meta = self.meta_for(resolved)
            if value is None:
                return Refusal("unsupported decimal predicate")
            if meta is None:
                return Refusal(f"no decimal metadata for column '{resolved.column}'")
            literal_scale = max(0, -int(value.as_tuple().exponent)) if isinstance(value.as_tuple().exponent, int) else 0
            scale = max(meta.scale, literal_scale)
            literal_int_digits = len(str(int(abs(value)))) if abs(value) >= 1 else 0
            if max(literal_int_digits, meta.digits) + scale > MAX_DECIMAL_TOTAL:
                return Refusal(REASON_DECIMAL_LITERAL_FIT)
            self.decimal_columns.append((resolved.table, resolved.column, meta))
            return decimal_predicate_sql(col, op, value, scale)
        if resolved.col_type == "date":
            day = _date_literal(right)
            if day is None:
                return Refusal("unsupported date predicate")
            self.date_columns.append((resolved.table, resolved.column))
            return date_predicate_sql(col, op, day)
        return Refusal(f"predicate on a {resolved.col_type} column is not supported")

    def _in(self, node: tuple[Any, ...]) -> str | Refusal:
        resolved = self.resolve(node[1])
        if isinstance(resolved, Refusal):
            return resolved
        ctor = node[2]
        if resolved.col_type != "text" or not (isinstance(ctor, tuple) and ctor and ctor[0] == "tableconstructor"):
            return Refusal("unsupported IN predicate")
        items: list[str] = []
        for item in ctor[1]:
            if not (isinstance(item, tuple) and item and item[0] == "string"):
                return Refusal("unsupported IN predicate")
            items.append(item[1])
        if not items:
            return Refusal("unsupported IN predicate")
        refused = self._text_checked(items, lambda: "")
        if isinstance(refused, Refusal):
            return refused
        self.in_columns.append((resolved.table, resolved.column))
        self.has_in = True
        return text_in_sql(quote_identifier(resolved.column), items)

    @staticmethod
    def _text_checked(literal: str | list[str], build: Any) -> str | Refusal:
        """Refuse a text literal that cannot travel inside SQL text (NUL, lone surrogates)."""
        for text in [literal] if isinstance(literal, str) else literal:
            try:
                text.encode("utf-8")
            except UnicodeEncodeError:
                return Refusal("text literal cannot be sent to the store")
            if "\x00" in text:
                return Refusal("text literal contains U+0000")
        return build()


def _flatten_measure(
    expression: str, measures_norm: Mapping[str, str], depth: int = 0
) -> tuple[Any, list[Any]] | Refusal:
    """The base aggregate node and ALL filter predicates of an expression, measure references expanded."""
    if depth > 33:
        return Refusal("measure reference chain too deep")
    node = parse_expression(expression)
    if node[0] == "reference" and not node[1]:
        sub = measures_norm.get(node[2].casefold())
        if sub is None:
            return Refusal(f"unknown measure '{node[2]}'")
        return _flatten_measure(sub, measures_norm, depth + 1)
    if node[0] == "call" and node[1] == "CALCULATE" and node[2]:
        first, outer = node[2][0], list(node[2][1:])
        if isinstance(first, tuple) and first[0] == "reference" and not first[1]:
            sub = measures_norm.get(first[2].casefold())
            if sub is None:
                return Refusal(f"unknown measure '{first[2]}'")
            inner = _flatten_measure(sub, measures_norm, depth + 1)
            if isinstance(inner, Refusal):
                return inner
            return inner[0], inner[1] + outer
        return first, outer
    return node, []


@dataclass(frozen=True)
class _PlanParts:
    """What plan_measure and plan_group_by share: the checked measure, its WHERE clause and its guards."""

    table: str
    shape: str
    t_q: str
    agg: str
    col: str | None
    c_type: str | None
    scale: int
    where_clause: str
    in_guards: tuple[tuple[str, str], ...]
    value_type: str
    overrides: dict[str, Any]
    own_predicates: int = 0
    has_in: bool = False
    physical: str = ""
    date_guards: tuple[tuple[str, str], ...] = ()
    decimal_stamps: tuple[tuple[str, str, int, int], ...] = ()


def _plan_parts(
    expression: str,
    *,
    filter_context: tuple[str, ...],
    blocked_columns: tuple[tuple[str, str], ...],
    home_table: str,
    tables: Mapping[str, Mapping[str, str]],
    store_tables: Mapping[str, str],
    column_meta: Mapping[tuple[str, str], ColumnMeta],
    measures: Mapping[str, str] | None,
    source_kind: str,
    overrides: Mapping[str, Any] | None,
) -> _PlanParts | Refusal:
    overrides = dict(overrides or {})
    max_digits = {col: meta.digits for (_, col), meta in column_meta.items()}
    decision = classify_measure(
        expression,
        home_table=home_table,
        tables=tables,
        measures=measures,
        source_kind=source_kind,
        max_digits=max_digits or None,
    )
    if not decision.allowed:
        return Refusal("; ".join(decision.reasons) or "refused by the whitelist")
    if source_kind == "parquet":
        return Refusal(PARQUET_PLAN_REASON)
    if decision.table is None or decision.shape is None:
        return Refusal("the whitelist gave no table")
    physical = next((p for t, p in store_tables.items() if t.casefold() == decision.table.casefold()), None)
    if physical is None:
        return Refusal(f"no store table for '{decision.table}'")
    try:
        measures_norm = {name.casefold(): body for name, body in (measures or {}).items()}
        flat = _flatten_measure(expression, measures_norm)
        if isinstance(flat, Refusal):
            return flat
        base, predicates = flat
        planner = _Planner(home_table, tables, column_meta, overrides)
        predicate_nodes = list(predicates)
        own_columns: list[tuple[str, str]] = []
        for t_name, c_name in _collect_references(tuple(predicates)):
            resolved_own = planner.resolve(("reference", t_name, c_name))
            if not isinstance(resolved_own, Refusal):
                own_columns.append((resolved_own.table.casefold(), resolved_own.column.casefold()))
        if filter_context:
            f_decision = classify_filter_context(
                filter_context,
                home_table=decision.table,
                tables=tables,
                source_kind=source_kind,
                max_digits=max_digits or None,
                blocked_columns=[*own_columns, *blocked_columns],
            )
            if not f_decision.allowed:
                return Refusal("; ".join(f_decision.reasons) or "filter context refused by the whitelist")
            if len(predicates) + len(filter_context) > MAX_PREDICATES:
                return Refusal(REASON_CAP_PREDICATES)
            predicate_nodes.extend(parse_expression(text) for text in filter_context)
            mix = in_mix_reason(predicate_nodes, tables, home_table)
            if mix:
                return Refusal(mix)
        where_parts: list[str] = []
        for predicate in predicate_nodes:
            sql = planner.predicate(predicate)
            if isinstance(sql, Refusal):
                return sql
            where_parts.append(f"({sql})")
        def physical_of(table_name: str) -> str | None:
            return next((p for t, p in store_tables.items() if t.casefold() == table_name.casefold()), None)

        in_guards: list[tuple[str, str]] = []
        # A text IN also makes every text-equality column of the plan matter: the engine's behaviour for the
        # pair depends on the DATA of the equality column (Kelvin sign, ligatures, micro sign), not on the literal.
        for in_table, in_column in [*planner.in_columns, *(planner.eq_columns if planner.has_in else [])]:
            in_physical = physical_of(in_table)
            if in_physical is None:
                return Refusal(f"no store table for '{in_table}'")
            if (in_physical, in_column) not in in_guards:
                in_guards.append((in_physical, in_column))
        date_guards: list[tuple[str, str]] = []
        decimal_stamps: list[tuple[str, str, int, int]] = []
        date_refs = list(planner.date_columns)
        for dec_table, dec_column, dec_meta in planner.decimal_columns:
            dec_physical = physical_of(dec_table)
            if dec_physical is None:
                return Refusal(f"no store table for '{dec_table}'")
            stamp = (dec_physical, dec_column, dec_meta.scale, dec_meta.digits)
            if stamp not in decimal_stamps:
                decimal_stamps.append(stamp)
        where_clause = ("WHERE " + _AND_JOIN.join(where_parts)) if where_parts else ""
        if not (isinstance(base, tuple) and base and base[0] == "call"):
            return Refusal("unsupported base expression")
        agg = base[1]
        col: str | None = None
        c_type: str | None = None
        scale = 4
        if agg != "COUNTROWS":
            resolved = planner.resolve(base[2][0])
            if isinstance(resolved, Refusal):
                return resolved
            col, c_type = quote_identifier(resolved.column), resolved.col_type
            if c_type == "decimal_number":
                meta = planner.meta_for(resolved)
                if meta is None:
                    return Refusal(f"no decimal metadata for column '{resolved.column}'")
                scale = meta.scale
                agg_physical = physical_of(resolved.table)
                if agg_physical is None:
                    return Refusal(f"no store table for '{resolved.table}'")
                stamp = (agg_physical, resolved.column, meta.scale, meta.digits)
                if stamp not in decimal_stamps:
                    decimal_stamps.append(stamp)
            elif c_type == "date":
                date_refs.append((resolved.table, resolved.column))
        for date_table, date_column in date_refs:
            date_physical = physical_of(date_table)
            if date_physical is None:
                return Refusal(f"no store table for '{date_table}'")
            if (date_physical, date_column) not in date_guards:
                date_guards.append((date_physical, date_column))
    except MeasureError as exc:
        return Refusal(str(exc))
    return _PlanParts(
        table=decision.table,
        shape=decision.shape,
        t_q=quote_identifier(physical),
        agg=agg,
        col=col,
        c_type=c_type,
        scale=scale,
        where_clause=where_clause,
        in_guards=tuple(in_guards),
        value_type="date" if agg in ("MIN", "MAX") and c_type == "date" else "number",
        overrides=overrides,
        own_predicates=len(predicates),
        has_in=planner.has_in,
        physical=physical,
        date_guards=tuple(date_guards),
        decimal_stamps=tuple(decimal_stamps),
    )


def plan_measure(
    expression: str,
    *,
    home_table: str,
    tables: Mapping[str, Mapping[str, str]],
    store_tables: Mapping[str, str],
    column_meta: Mapping[tuple[str, str], ColumnMeta],
    measures: Mapping[str, str] | None = None,
    source_kind: str = "csv",
    overrides: Mapping[str, Any] | None = None,
    filter_context: tuple[str, ...] = (),
) -> MeasurePlan | Refusal:
    """Plan one measure expression on the store, or refuse. Never raises for a bad expression.

    `tables` is {table: {column: type}} as classify_measure takes it, `store_tables` {table: physical store
    table name}, `column_meta` {(table, column): ColumnMeta} from column_decimal_meta. Anything the whitelist
    refuses is a Refusal with the reasons joined; no SQL is built for it. `filter_context` is a tuple of DAX
    predicate strings (slicers): the value is that of CALCULATE(<measure>, <own predicates>, <context>), all ANDed;
    a context column that the measure itself filters is refused.
    """
    parts = _plan_parts(
        expression,
        filter_context=tuple(filter_context),
        blocked_columns=(),
        home_table=home_table,
        tables=tables,
        store_tables=store_tables,
        column_meta=column_meta,
        measures=measures,
        source_kind=source_kind,
        overrides=overrides,
    )
    if isinstance(parts, Refusal):
        return parts
    if parts.agg == "AVERAGE":
        cast_c = average_cast_sql(parts.col or "", parts.c_type, parts.scale, False, parts.overrides)
        sql_text = f"SELECT SUM({cast_c}), COUNT({cast_c}) FROM {parts.t_q} {parts.where_clause}"
        kind = "average"
    else:
        built = aggregate_sql(
            parts.agg, parts.col, parts.c_type, parts.where_clause, parts.scale,
            t_q=parts.t_q, is_parquet=False, overrides=parts.overrides,
        )
        if not isinstance(built, str):
            return built if isinstance(built, Refusal) else Refusal(f"no SQL for {parts.agg}")
        sql_text = built
        kind = "scalar"
    return MeasurePlan(
        kind=kind,
        sql=sql_text,
        table=parts.table,
        shape=parts.shape,
        value_type=parts.value_type,
        overrides=parts.overrides,
        in_guards=parts.in_guards,
        date_guards=parts.date_guards,
        decimal_stamps=parts.decimal_stamps,
    )


# ==============================================================================
# SECTION: GROUP-BY PLANNER (Stage C1b2): one visual axis column, the way a visual shows it
# ==============================================================================

REASON_GROUP_NON_ASCII_SPACE = (
    "the group-by column holds a non-ASCII whitespace cell; the engine treats it as blank in a key filter"
)
# Every BMP character that str.isspace accepts and that is not ASCII, as a regular expression class body
NON_ASCII_SPACE_CLASS = "".join(f"\\x{{{c:X}}}" for c in range(0x80, 0x10000) if chr(c).isspace())
REASON_GROUP_BY_SHAPE = "group_by must be one (table, column) pair"
REASON_GROUP_OWN_FILTER = (
    "the group-by column is also filtered by the measure: DAX replaces the outer filter, not checked yet"
)
REASON_GROUP_BY_TYPE = "group-by is only on text, date and boolean columns"
GROUP_BLANK_KEY = ""


@dataclass(frozen=True)
class GroupByPlan:
    """One GROUP BY SELECT and the rule that turns its rows into [(key text, value)] in SQL order.

    kind is "scalar" (rows are (key, value)) or "average" (rows are (key, sum, count)).
    """

    kind: str
    sql: str
    table: str
    shape: str
    group_column: str
    group_type: str
    value_type: str = "number"
    overrides: Mapping[str, Any] | None = field(default=None, compare=False, repr=False)
    in_guards: tuple[tuple[str, str], ...] = ()
    space_guards: tuple[tuple[str, str], ...] = ()
    refuse_fold_keys: bool = False
    date_guards: tuple[tuple[str, str], ...] = ()
    decimal_stamps: tuple[tuple[str, str, int, int], ...] = ()

    def execute(self, store: Any) -> list[tuple[str, Decimal | dax_dates.DaxDateTime | None]] | Refusal:
        """Run the guard queries on every execute, then the GROUP BY.

        Keys are the strings the engine shows for VALUES(). A text group column holding a non-ASCII whitespace
        cell is refused: the engine's key filter `col = ""` also selects those cells, the store keeps them apart.
        """
        for guard in self.space_guards:
            t_q, c_q = quote_identifier(guard[0]), quote_identifier(guard[1])
            rows = store.execute(
                f"SELECT EXISTS (SELECT 1 FROM {t_q} WHERE regexp_matches({c_q}, '[{NON_ASCII_SPACE_CLASS}]'))"
            )
            if rows and rows[0][0]:
                return Refusal(REASON_GROUP_NON_ASCII_SPACE)
        refused = run_plan_guards(
            store, in_guards=self.in_guards, date_guards=self.date_guards, decimal_stamps=self.decimal_stamps
        )
        if refused is not None:
            return refused
        out: list[tuple[str, Decimal | dax_dates.DaxDateTime | None]] = []
        for row in store.execute(self.sql):
            key = "" if row[0] is None else str(row[0])
            if self.kind == "average":
                divide = StoreResultLayer.divide_ratio if (self.overrides or {}).get("gb_avg_float") else StoreResultLayer.divide
                value: Any = divide(row[1], row[2], overrides=dict(self.overrides or {}))
            else:
                value = convert_result(row[1], self.value_type)
            out.append((key, value))
        if self.refuse_fold_keys and any(_in_item_folds_differently(key) for key, _ in out):
            return Refusal(REASON_IN_FOLD_EQ_MIX)
        return out


def _group_key_sql(g_col: str, g_type: str, order_col: str, overrides: Mapping[str, Any]) -> tuple[str, str, str, str]:
    """(group expression, key text expression, ORDER BY of the plain form, ORDER BY of the joined form).

    The joined form (used with a filter context) reads the group keys, their order and their spelling from a
    subquery `s` over the WHOLE table (the column dictionary does not change with a slicer) and the values from a
    subquery `v` over the filtered rows.
    """
    if g_type == "text":
        spelling_row = "rowid" if overrides.get("gb_order_rowid") else order_col
        group = g_col if overrides.get("gb_no_fold") else fold_sql(g_col)
        if overrides.get("gb_no_fold"):
            key = trim_sql(g_col)
        elif overrides.get("gb_last_spelling"):
            key = f"arg_max({trim_sql(g_col)}, {order_col})"
        else:
            key = first_spelling_expr_sql(g_col, spelling_row)
        first = f"MIN({spelling_row})"
        if overrides.get("gb_order_sorted"):
            return group, key, "1", "s.k"
        if overrides.get("gb_blank_last"):
            return group, key, f"({group} = '') , {first}", "(s.g = ''), s.o"
        return group, key, first, "s.o"
    if g_type == "date":
        cast = f"TRY_CAST(NULLIF({g_col}, '') AS DATE)"
        fmt = "%m/%d/%Y" if overrides.get("gb_date_zero_pad") else "%-m/%-d/%Y"
        nulls = "NULLS LAST" if overrides.get("gb_blank_last") else "NULLS FIRST"
        return cast, f"COALESCE(strftime({cast}, '{fmt}'), '')", f"{cast} {nulls}", f"s.g {nulls}"
    flag = f"(CASE WHEN UPPER(TRIM(COALESCE({g_col}, ''))) = 'TRUE' THEN 'TRUE' ELSE 'FALSE' END)"
    direction = "DESC" if overrides.get("gb_bool_true_first") else "ASC"
    return flag, flag, f"{flag} {direction}", f"s.g {direction}"


def plan_group_by(
    expression: str,
    *,
    group_by: tuple[str, str],
    filter_context: tuple[str, ...] = (),
    home_table: str,
    tables: Mapping[str, Mapping[str, str]],
    store_tables: Mapping[str, str],
    column_meta: Mapping[tuple[str, str], ColumnMeta],
    measures: Mapping[str, str] | None = None,
    source_kind: str = "csv",
    overrides: Mapping[str, Any] | None = None,
) -> GroupByPlan | Refusal:
    """Plan one measure grouped by ONE text, date or boolean column, or refuse. Never raises for bad input.

    The result is the visual-axis answer: one (key, value) per group in the order the engine shows
    TOCSV(VALUES(col)): text keys by first appearance after the VertiPaq fold (first-seen spelling, the blank
    key at its first-seen place), dates ascending with the blank first and `m/d/yyyy` text, booleans FALSE then
    TRUE. The value per key is that of CALCULATE(<measure>, <key filter>).
    """
    if not (isinstance(group_by, tuple) and len(group_by) == 2 and all(isinstance(x, str) for x in group_by)):
        return Refusal(REASON_GROUP_BY_SHAPE)
    overrides = dict(overrides or {})
    if overrides.get("gb_drop_filter"):
        filter_context = ()  # mutant hook, inert by default
    probe = _Planner(home_table, tables, column_meta, overrides)
    resolved_group = probe.resolve(("reference", group_by[0], group_by[1]))
    if isinstance(resolved_group, Refusal):
        return resolved_group
    if resolved_group.col_type not in ("text", "date", "boolean"):
        return Refusal(REASON_GROUP_BY_TYPE)
    parts = _plan_parts(
        expression,
        filter_context=tuple(filter_context),
        blocked_columns=((resolved_group.table, resolved_group.column),),
        home_table=home_table,
        tables=tables,
        store_tables=store_tables,
        column_meta=column_meta,
        measures=measures,
        source_kind=source_kind,
        overrides=overrides,
    )
    if isinstance(parts, Refusal):
        return parts
    if resolved_group.table.casefold() != parts.table.casefold():
        return Refusal(f"the group-by column is on table '{resolved_group.table}', the measure on '{parts.table}'")
    if parts.own_predicates:
        return Refusal(REASON_GROUP_OWN_FILTER)
    in_guards = list(parts.in_guards)
    date_guards = list(parts.date_guards)
    if resolved_group.col_type == "date" and (parts.physical, resolved_group.column) not in date_guards:
        date_guards.append((parts.physical, resolved_group.column))
    g_col = quote_identifier(resolved_group.column)
    group_sql, key_sql, order_plain, order_join = _group_key_sql(
        g_col, resolved_group.col_type, STORE_ORDER_COLUMN, overrides
    )
    if parts.agg == "AVERAGE":
        cast_c = average_cast_sql(parts.col or "", parts.c_type, parts.scale, False, parts.overrides)
        value_exprs = [f"SUM({cast_c})", f"COUNT({cast_c})"]
        kind = "average"
    else:
        built = aggregate_sql(
            parts.agg, parts.col, parts.c_type, parts.where_clause, parts.scale,
            t_q=parts.t_q, is_parquet=False, overrides=parts.overrides,
        )
        suffix = f" FROM {parts.t_q} {parts.where_clause}"
        if not isinstance(built, str):
            return built if isinstance(built, Refusal) else Refusal(f"no SQL for {parts.agg}")
        if not (built.startswith("SELECT ") and built.endswith(suffix)):
            return Refusal(f"no group-by SQL for {parts.agg}")
        value_exprs = [built[len("SELECT "):-len(suffix)]]
        kind = "scalar"
    if not parts.where_clause:
        sql_text = (
            f"SELECT {key_sql} AS k, {', '.join(value_exprs)} FROM {parts.t_q} GROUP BY {group_sql} ORDER BY {order_plain}"
        )
    else:
        order_col_sql = f"MIN({STORE_ORDER_COLUMN})"
        value_names = ", ".join(f"v.x{i}" for i in range(len(value_exprs)))
        value_cols = ", ".join(f"{expr} AS x{i}" for i, expr in enumerate(value_exprs))
        sql_text = (
            f"SELECT s.k, {value_names} FROM "
            f"(SELECT {group_sql} AS g, {key_sql} AS k, {order_col_sql} AS o FROM {parts.t_q} GROUP BY {group_sql}) s "
            f"JOIN (SELECT {group_sql} AS g, {value_cols} FROM {parts.t_q} {parts.where_clause} GROUP BY {group_sql}) v "
            f"ON s.g IS NOT DISTINCT FROM v.g ORDER BY {order_join}"
        )
    return GroupByPlan(
        kind=kind,
        sql=sql_text,
        table=parts.table,
        shape=f"{parts.shape}_by_{resolved_group.col_type}",
        group_column=resolved_group.column,
        group_type=resolved_group.col_type,
        value_type=parts.value_type,
        overrides=parts.overrides,
        in_guards=tuple(in_guards),
        space_guards=((parts.physical, resolved_group.column),) if resolved_group.col_type == "text" else (),
        refuse_fold_keys=parts.has_in and resolved_group.col_type == "text",
        date_guards=tuple(date_guards),
        decimal_stamps=parts.decimal_stamps,
    )
