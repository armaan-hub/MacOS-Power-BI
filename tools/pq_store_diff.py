"""Power Query step differential tool, first slice (Stage D0a, fixes D0b).

Proves on generated data that a SQL mapping of each Tier 1 Power Query step
gives the same result as the existing row-by-row step engine (transformations.py).

Cell rule (one place, `normalize_cell`): a cell is None or text. None is NOT the
same as ''. The store CSV import keeps a blank cell as '' and the step engine
returns '' for a blank CSV cell (measured: 0 None cells over 55 steps), so a SQL
mapping that returns NULL for a blank cell is a difference.

Known limit of the mutant tests: removing ORDER BY from the 5 row-slicing
operations (`mutant_no_order_by`) cannot be killed by behaviour, because DuckDB
returns insertion order for a plain scan (measured at 1,000,000 rows). That rule
is guarded by a SQL-text lint test, which is not a mutant kill.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from analytics_studio.file_import import ImportCandidate, parse_file
from analytics_studio.query_engine import append_candidates
from analytics_studio.store import DuckStore, import_csv_to_store
from analytics_studio.transformations import TransformationError, apply_transformations


class Refusal:
    """Explicit refusal object representing an intentionally unsupported or invalid shape."""

    def __init__(self, reason: str, expected_error: str | None = None):
        self.reason = reason
        self.expected_error = expected_error

    def __repr__(self) -> str:
        return f"Refusal({self.reason!r}, expected_error={self.expected_error!r})"

    def __str__(self) -> str:
        return f"REFUSED: {self.reason}"


def refusal_matches_engine_error(refusal: Refusal, engine_err: str) -> bool:
    """Check if refusal matches expected engine error substring."""
    return bool(refusal.expected_error) and refusal.expected_error in engine_err


def normalize_cell(val: Any) -> str | None:
    """Normalize a cell for comparison: None stays None, everything else becomes text.

    None and '' are different values on both sides. The step engine never returns
    None for a CSV-parsed table and the store holds '' for a blank CSV cell.
    """
    if val is None:
        return None
    return str(val)


WHITESPACE_CELLS = [" ", "\t", "\u00a0"]


def generate_pq_dataset(
    csv_file: Path,
    rows: int = 2000,
    seed: int = 42,
    include_blank_rows: bool = True,
) -> dict[str, Any]:
    """Generate a CSV dataset with mixed case, blanks, unicode, spaces, numbers, and dates.

    Planted shapes: an all-blank row every 250th row (measured: both the engine's CSV
    parser and the store import DROP all-blank rows on load, so they never reach a step), one whitespace-only entire row
    (row rows // 3, moved one down when that is a blank-row slot; spaces in every cell),
    whitespace-only cells (" ", tab, NBSP U+00A0), adjacent duplicate rows and non-adjacent duplicates.
    """
    rnd = random.Random(seed)

    text_options = [
        "east", "East", "EAST", "west", "West", "west ", "west\t",
        "north", "south", "ünïcode", "ÜNÏCODE", "straße", "STRASSE",
        "with'quote", 'with"doublequote', "multi\nline",
    ]
    categories = ["A", "B", "C", "D", "E"]
    num_options = ["0", "1", "-5", "100", "200", "999999", "123.45", "-0.50"]
    date_options = ["2026-01-01", "2026-06-15", "2026-12-31", "2025-05-20"]

    headers = ["id", "text_col", "num_col", "date_col", "cat_col", "blank_col"]

    ws_row = max(3, rows // 3)
    if include_blank_rows and ws_row % 250 == 0:
        ws_row += 1

    csv_rows: list[list[str]] = []

    for i in range(1, rows + 1):
        if include_blank_rows and (i % 250 == 0):
            # Pure blank row: every cell is empty
            csv_rows.append(["", "", "", "", "", ""])
            continue
        if i == ws_row:
            # Whitespace-only entire row: kept by Power Query (only null and '' are blank)
            csv_rows.append([" "] * 6)
            continue

        dup_kind = rnd.random()
        if csv_rows and dup_kind < 0.05:
            # Adjacent duplicate: identical to the previous row
            csv_rows.append(list(csv_rows[-1]))
            continue
        if csv_rows and dup_kind < 0.08:
            # Non-adjacent duplicate: identical to a random earlier row
            csv_rows.append(list(csv_rows[rnd.randrange(len(csv_rows))]))
            continue

        id_str = str(i)
        t_str = rnd.choice(text_options) if rnd.random() >= 0.08 else ""
        n_str = rnd.choice(num_options) if rnd.random() >= 0.08 else ""
        d_str = rnd.choice(date_options) if rnd.random() >= 0.08 else ""
        c_str = rnd.choice(categories) if rnd.random() >= 0.08 else ""
        b_str = "" if rnd.random() < 0.90 else "non_blank"
        if rnd.random() < 0.05:
            t_str = rnd.choice(WHITESPACE_CELLS)
        if rnd.random() < 0.05:
            c_str = rnd.choice(WHITESPACE_CELLS)
        if rnd.random() < 0.03:
            b_str = rnd.choice(WHITESPACE_CELLS)

        csv_rows.append([id_str, t_str, n_str, d_str, c_str, b_str])

    csv_file.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(csv_rows)

    return {"headers": headers, "rows": len(csv_rows)}


def build_step_catalog(headers: list[str]) -> list[dict[str, Any]]:
    """Build catalog of parameter sets for Tier 1 Power Query steps."""
    catalog: list[dict[str, Any]] = []
    n_cols = len(headers)

    # 1. keep_columns (parameter sets that need a 2nd or 3rd column are skipped on narrow tables)
    if n_cols >= 2:
        catalog.append({
            "id": "keep_columns_subset",
            "step": {"op": "keep_columns", "columns": [headers[0], headers[1]]},
        })
    catalog.append({
        "id": "keep_columns_single",
        "step": {"op": "keep_columns", "columns": [headers[0]]},
    })
    if n_cols >= 2:
        catalog.append({
            "id": "keep_columns_reordered_selection",
            "step": {"op": "keep_columns", "columns": [headers[2] if n_cols >= 3 else headers[1], headers[0]]},
        })
    catalog.append({
        "id": "keep_columns_all",
        "step": {"op": "keep_columns", "columns": list(headers)},
    })
    catalog.append({
        "id": "keep_columns_missing_col",
        "step": {"op": "keep_columns", "columns": [headers[0], "nonexistent_col_xyz"]},
    })

    # 2. remove_column
    remove_cols: list[str] = []
    for col in [headers[0], headers[1] if n_cols >= 2 else headers[0], headers[-1]]:
        if col not in remove_cols:
            remove_cols.append(col)
    for col in remove_cols:
        catalog.append({
            "id": f"remove_column_{col}",
            "step": {"op": "remove_column", "column": col},
        })
    catalog.append({
        "id": "remove_column_nonexistent_col",
        "step": {"op": "remove_column", "column": "nonexistent_col_xyz"},
    })
    catalog.append({
        "id": "remove_column_last_column",
        "step": {"op": "remove_column", "column": headers[0]},
        "single_column_context": True,
    })

    # 3. reorder_columns
    catalog.append({
        "id": "reorder_columns_first_only",
        "step": {"op": "reorder_columns", "columns": [headers[0]]},
    })
    if n_cols >= 2:
        catalog.append({
            "id": "reorder_columns_swap_first_two",
            "step": {"op": "reorder_columns", "columns": [headers[1], headers[0]]},
        })
        catalog.append({
            "id": "reorder_columns_reverse_all",
            "step": {"op": "reorder_columns", "columns": list(reversed(headers))},
        })
    if n_cols >= 3:
        catalog.append({
            "id": "reorder_columns_partial_middle",
            "step": {"op": "reorder_columns", "columns": [headers[2], headers[1]]},
        })
    catalog.append({
        "id": "reorder_columns_missing_col",
        "step": {"op": "reorder_columns", "columns": ["missing_xyz"]},
    })

    # 4. rename_column
    catalog.append({
        "id": "rename_column_simple",
        "step": {"op": "rename_column", "column": headers[0], "new_name": "renamed_id"},
    })
    catalog.append({
        "id": "rename_column_same_name",
        "step": {"op": "rename_column", "column": headers[0], "new_name": headers[0]},
    })
    catalog.append({
        "id": "rename_column_nonexistent_col",
        "step": {"op": "rename_column", "column": "missing_col_xyz", "new_name": "new_name"},
    })
    if n_cols >= 2:
        catalog.append({
            "id": "rename_column_existing_name",
            "step": {"op": "rename_column", "column": headers[0], "new_name": headers[1]},
        })

    # 5. duplicate_column
    catalog.append({
        "id": "duplicate_column_first",
        "step": {"op": "duplicate_column", "column": headers[0], "new_name": f"{headers[0]}_copy"},
    })
    catalog.append({
        "id": "duplicate_column_last",
        "step": {"op": "duplicate_column", "column": headers[-1], "new_name": f"{headers[-1]}_copy"},
    })
    if n_cols >= 2:
        catalog.append({
            "id": "duplicate_column_existing_name",
            "step": {"op": "duplicate_column", "column": headers[0], "new_name": headers[1]},
        })
    catalog.append({
        "id": "duplicate_column_nonexistent_col",
        "step": {"op": "duplicate_column", "column": "missing_xyz", "new_name": "dup_xyz"},
    })

    # 6. keep_top_rows
    for cnt in [0, 1, 10, 50, 100000]:
        catalog.append({
            "id": f"keep_top_rows_{cnt}",
            "step": {"op": "keep_top_rows", "count": cnt},
        })

    # 7. remove_top_rows
    for cnt in [0, 1, 10, 50, 100000]:
        catalog.append({
            "id": f"remove_top_rows_{cnt}",
            "step": {"op": "remove_top_rows", "count": cnt},
        })

    # 8. keep_bottom_rows
    for cnt in [0, 1, 10, 50, 100000]:
        catalog.append({
            "id": f"keep_bottom_rows_{cnt}",
            "step": {"op": "keep_bottom_rows", "count": cnt},
        })

    # 9. remove_bottom_rows
    for cnt in [0, 1, 10, 50, 100000]:
        catalog.append({
            "id": f"remove_bottom_rows_{cnt}",
            "step": {"op": "remove_bottom_rows", "count": cnt},
        })

    # 10. keep_range_rows
    range_params = [
        (1, 10),
        (1, 0),
        (5, 20),
        (50, 100),
        (100, 100000),
        (100000, 10),
    ]
    for first_row, count in range_params:
        catalog.append({
            "id": f"keep_range_rows_{first_row}_{count}",
            "step": {"op": "keep_range_rows", "first_row": first_row, "count": count},
        })

    # 11. remove_alternate_rows
    alt_params = [
        (1, 1, 1),
        (1, 1, 2),
        (2, 2, 3),
        (5, 1, 4),
        (1, 0, 5),
        (1, 5, 0),
        (100000, 1, 1),
    ]
    for first_row, rem, kp in alt_params:
        catalog.append({
            "id": f"remove_alternate_rows_{first_row}_{rem}_{kp}",
            "step": {
                "op": "remove_alternate_rows",
                "first_row_to_remove": first_row,
                "remove_count": rem,
                "keep_count": kp,
            },
        })

    # 12. count_rows
    catalog.append({
        "id": "count_rows",
        "step": {"op": "count_rows"},
    })

    # 13. add_index_column
    index_params = [
        ("Index", 0, 1),
        ("Index_1", 1, 1),
        ("CustomIndex", 100, 5),
        ("NegativeStart", -10, 2),
    ]
    for new_name, start, inc in index_params:
        catalog.append({
            "id": f"add_index_column_{new_name}_{start}_{inc}",
            "step": {
                "op": "add_index_column",
                "new_name": new_name,
                "start": start,
                "increment": inc,
            },
        })

    # 14. remove_blank_rows
    catalog.append({
        "id": "remove_blank_rows",
        "step": {"op": "remove_blank_rows"},
    })
    # Plain remove_blank_rows is the identity on imported CSV data (all-blank rows are dropped on
    # load). Keeping the last column(s) first makes rows blank for the step to remove.
    for tail in (1, 2):
        if n_cols >= tail:
            catalog.append({
                "id": f"remove_blank_rows_after_keep_last_{tail}",
                "pre_step": {"op": "keep_columns", "columns": list(headers[-tail:])},
                "step": {"op": "remove_blank_rows"},
            })

    # 15. append
    catalog.append({
        "id": "append_two_tables",
        "step": {"op": "append"},
        "second_table": "t_csv_2",
    })

    return catalog


def generate_step_sql(
    item: dict[str, Any],
    headers: list[str],
    table_name: str,
    total_rows: int,
    overrides: dict[str, Any] | None = None,
) -> tuple[str, list[str]] | Refusal:
    """Generate SQL query and expected output columns for a step item.

    Returns (sql_query, output_headers) or a Refusal object.
    `mutant_null_for_blank` (inert by default) wraps every selected column in
    NULLIF(col, '') so a blank cell comes back as NULL; the tool must flag it.
    """
    overrides = overrides or {}
    result = _mapped_sql(item, headers, table_name, total_rows, overrides)
    if isinstance(result, Refusal) or not overrides.get("mutant_null_for_blank"):
        return result
    sql, out_headers = result
    if overrides.get("forced_sql_syntax_error"):
        return result
    wrapped = ", ".join(f'NULLIF(CAST("{h}" AS VARCHAR), \'\') AS "{h}"' for h in out_headers)
    return (f"SELECT {wrapped} FROM ({sql})", out_headers)


def _mapped_sql(
    item: dict[str, Any],
    headers: list[str],
    table_name: str,
    total_rows: int,
    overrides: dict[str, Any],
) -> tuple[str, list[str]] | Refusal:
    """The SQL mapping of each step (see `generate_step_sql`)."""
    t_q = f'"{table_name}"'
    step = item["step"]
    op = step.get("op")

    if overrides.get("forced_sql_syntax_error"):
        return ("SELECT INVALID SYNTAX FROM " + t_q, headers)

    # 1. keep_columns
    if op == "keep_columns":
        cols = step["columns"]
        missing = [c for c in cols if c not in headers]
        if missing:
            return Refusal(
                f"Column {missing[0]!r} does not exist.",
                expected_error=f"Column {missing[0]!r} does not exist.",
            )
        # Power Query preserves original header order filtered by selected set
        selected_set = set(cols)
        out_headers = [h for h in headers if h in selected_set]
        col_list = ", ".join(f'"{c}"' for c in out_headers)
        order_clause = "ORDER BY rowid DESC" if overrides.get("mutant_reverse_order") else "ORDER BY rowid"
        return (f"SELECT {col_list} FROM {t_q} {order_clause}", out_headers)

    # 2. remove_column
    if op == "remove_column":
        col = step["column"]
        # The engine checks that the column exists before it checks for the last column.
        if col not in headers:
            return Refusal(
                f"Column {col!r} does not exist.",
                expected_error=f"Column {col!r} does not exist.",
            )
        if len(headers) == 1:
            return Refusal(
                "Cannot remove the last column from a table.",
                expected_error="Cannot remove the last column from a table.",
            )
        out_headers = [h for h in headers if h != col]
        col_list = ", ".join(f'"{c}"' for c in out_headers)
        order_clause = "ORDER BY rowid DESC" if overrides.get("mutant_reverse_order") else "ORDER BY rowid"
        return (f"SELECT {col_list} FROM {t_q} {order_clause}", out_headers)

    # 3. reorder_columns
    if op == "reorder_columns":
        cols = step["columns"]
        for c in cols:
            if c not in headers:
                return Refusal(
                    f"Column {c!r} does not exist.",
                    expected_error=f"Column {c!r} does not exist.",
                )
        # Apply Power Query partial reordering semantics
        selected_set = set(cols)
        slots = [idx for idx, h in enumerate(headers) if h in selected_set]
        out_headers = list(headers)
        for idx, c in zip(slots, cols):
            out_headers[idx] = c
        col_list = ", ".join(f'"{c}"' for c in out_headers)
        order_clause = "ORDER BY rowid DESC" if overrides.get("mutant_reverse_order") else "ORDER BY rowid"
        return (f"SELECT {col_list} FROM {t_q} {order_clause}", out_headers)

    # 4. rename_column
    if op == "rename_column":
        col = step["column"]
        new_name = step["new_name"].strip()
        if col not in headers:
            return Refusal(
                f"Column {col!r} does not exist.",
                expected_error=f"Column {col!r} does not exist.",
            )
        if new_name in headers and new_name != col:
            return Refusal(
                f"Column {new_name!r} already exists.",
                expected_error=f"Column {new_name!r} already exists.",
            )
        out_headers = [new_name if h == col else h for h in headers]
        select_items = [f'"{h}" AS "{new_name}"' if h == col else f'"{h}"' for h in headers]
        col_list = ", ".join(select_items)
        order_clause = "ORDER BY rowid DESC" if overrides.get("mutant_reverse_order") else "ORDER BY rowid"
        return (f"SELECT {col_list} FROM {t_q} {order_clause}", out_headers)

    # 5. duplicate_column
    if op == "duplicate_column":
        col = step["column"]
        new_name = step["new_name"].strip()
        if col not in headers:
            return Refusal(
                f"Column {col!r} does not exist.",
                expected_error=f"Column {col!r} does not exist.",
            )
        if new_name in headers:
            return Refusal(
                f"Cannot duplicate {col!r}: output column {new_name!r} already exists.",
                expected_error=f"Cannot duplicate {col!r}: output column {new_name!r} already exists.",
            )
        out_headers = [*headers, new_name]
        col_list = ", ".join(f'"{c}"' for c in headers) + f', "{col}" AS "{new_name}"'
        order_clause = "ORDER BY rowid DESC" if overrides.get("mutant_reverse_order") else "ORDER BY rowid"
        return (f"SELECT {col_list} FROM {t_q} {order_clause}", out_headers)

    # 6. keep_top_rows
    if op == "keep_top_rows":
        count = step["count"]
        if overrides.get("mutant_top_off_by_one"):
            count += 1
        col_list = ", ".join(f'"{c}"' for c in headers)
        order_clause = "" if overrides.get("mutant_no_order_by") else "ORDER BY rowid"
        return (f"SELECT {col_list} FROM {t_q} {order_clause} LIMIT {count}", list(headers))

    # 7. remove_top_rows
    if op == "remove_top_rows":
        count = step["count"]
        col_list = ", ".join(f'"{c}"' for c in headers)
        order_clause = "" if overrides.get("mutant_no_order_by") else "ORDER BY rowid"
        return (f"SELECT {col_list} FROM {t_q} {order_clause} OFFSET {count}", list(headers))

    # 8. keep_bottom_rows
    if op == "keep_bottom_rows":
        count = step["count"]
        offset = max(0, total_rows - count)
        col_list = ", ".join(f'"{c}"' for c in headers)
        order_clause = "" if overrides.get("mutant_no_order_by") else "ORDER BY rowid"
        return (f"SELECT {col_list} FROM {t_q} {order_clause} OFFSET {offset} LIMIT {count}", list(headers))

    # 9. remove_bottom_rows
    if op == "remove_bottom_rows":
        count = step["count"]
        keep_count = max(0, total_rows - count)
        col_list = ", ".join(f'"{c}"' for c in headers)
        order_clause = "" if overrides.get("mutant_no_order_by") else "ORDER BY rowid"
        return (f"SELECT {col_list} FROM {t_q} {order_clause} LIMIT {keep_count}", list(headers))

    # 10. keep_range_rows
    if op == "keep_range_rows":
        first_row = step["first_row"]
        count = step["count"]
        offset = max(0, first_row - 1)
        if overrides.get("mutant_range_start_off_by_one"):
            offset += 1
        if overrides.get("mutant_range_count_off_by_one"):
            count += 1
        col_list = ", ".join(f'"{c}"' for c in headers)
        order_clause = "" if overrides.get("mutant_no_order_by") else "ORDER BY rowid"
        return (f"SELECT {col_list} FROM {t_q} {order_clause} OFFSET {offset} LIMIT {count}", list(headers))

    # 11. remove_alternate_rows
    if op == "remove_alternate_rows":
        first_to_remove = step["first_row_to_remove"]
        rem = step["remove_count"]
        kp = step["keep_count"]
        if overrides.get("mutant_alt_offset_wrong"):
            first_to_remove += 1
        window_order = "ORDER BY rowid DESC" if overrides.get("mutant_window_order_desc") else "ORDER BY rowid"

        col_list = ", ".join(f'"{c}"' for c in headers)
        if rem == 0:
            cond = "1=1"
        elif kp == 0:
            cond = f"_rn < {first_to_remove}"
        else:
            cycle = rem + kp
            cond = f"(_rn < {first_to_remove} OR ((_rn - {first_to_remove}) % {cycle}) >= {rem})"

        sql = (
            f"SELECT {col_list} FROM ("
            f"  SELECT {col_list}, CAST(row_number() OVER ({window_order}) AS BIGINT) AS _rn FROM {t_q}"
            f") WHERE {cond} ORDER BY _rn"
        )
        return (sql, list(headers))

    # 12. count_rows
    if op == "count_rows":
        return (f"SELECT COUNT(*) AS \"Count\" FROM {t_q}", ["Count"])

    # 13. add_index_column
    if op == "add_index_column":
        new_name = step["new_name"]
        start = step["start"]
        inc = step["increment"]
        col_list = ", ".join(f'"{c}"' for c in headers)
        if overrides.get("mutant_index_start_off_by_one"):
            start += 1
        if overrides.get("mutant_index_increment_one"):
            inc = 1
        window_order = "ORDER BY rowid DESC" if overrides.get("mutant_window_order_desc") else "ORDER BY rowid"
        idx_expr = f"{start} + (CAST(row_number() OVER ({window_order}) AS BIGINT) - 1) * {inc}"
        out_headers = [*headers, new_name]
        order_clause = "ORDER BY rowid DESC" if overrides.get("mutant_reverse_order") else "ORDER BY rowid"
        sql = f"SELECT {col_list}, {idx_expr} AS \"{new_name}\" FROM {t_q} {order_clause}"
        return (sql, out_headers)

    # 14. remove_blank_rows
    if op == "remove_blank_rows":
        col_list = ", ".join(f'"{c}"' for c in headers)
        if overrides.get("mutant_blank_counts_whitespace"):
            # Whitespace counts as blank (differing from Power Query semantics)
            non_blank_preds = [f"trim(COALESCE(\"{c}\", '')) != ''" for c in headers]
        else:
            non_blank_preds = [f"COALESCE(\"{c}\", '') != ''" for c in headers]
        where_clause = " OR ".join(non_blank_preds)
        order_clause = "ORDER BY rowid DESC" if overrides.get("mutant_reverse_order") else "ORDER BY rowid"
        return (f"SELECT {col_list} FROM {t_q} WHERE ({where_clause}) {order_clause}", list(headers))

    # 15. append
    if op == "append":
        second_tbl = item.get("second_table", f"{table_name}_2")
        col_list = ", ".join(f'"{c}"' for c in headers)
        order_clause = "ORDER BY _src, _rn"
        if overrides.get("mutant_append_order_rn_src"):
            order_clause = "ORDER BY _rn, _src"
        if overrides.get("mutant_append_order_src_only"):
            order_clause = "ORDER BY _src"
        second_cols = ", ".join(f'"{c}"' for c in reversed(headers)) if overrides.get("mutant_append_column_order") else col_list
        sql = (
            f"SELECT {col_list} FROM ("
            f"  SELECT {col_list}, 0 AS _src, rowid AS _rn FROM {t_q}"
            f"  UNION ALL"
            f"  SELECT {second_cols}, 1 AS _src, rowid AS _rn FROM \"{second_tbl}\""
            f") {order_clause}"
        )
        return (sql, list(headers))

    return Refusal(f"Unknown or unsupported step operation: {op}")


def execute_engine_step(
    item: dict[str, Any],
    candidate: ImportCandidate,
    candidate_2: ImportCandidate | None = None,
) -> tuple[list[str], list[list[str | None]]] | str:
    """Execute step on row-by-row step engine.

    Returns (headers, rows_as_text_matrix) or error message string.
    """
    step = item["step"]
    op = step.get("op")

    try:
        if op == "append":
            if candidate_2 is None:
                raise TransformationError("Append requires two tables.")
            result = append_candidates([candidate, candidate_2])
        else:
            cand_input = candidate
            if item.get("single_column_context") and len(candidate.headers) > 1:
                # Candidate with only 1 column
                single_header = candidate.headers[0]
                cand_input = ImportCandidate(
                    kind=candidate.kind,
                    headers=[single_header],
                    rows=[{single_header: r[single_header]} for r in candidate.rows],
                    options=candidate.options,
                    notices=candidate.notices,
                )
            steps = [item["pre_step"], step] if item.get("pre_step") else [step]
            result = apply_transformations(cand_input, steps)

        out_headers = list(result.headers)
        out_rows: list[list[str | None]] = []
        for r in result.rows:
            row_vals = [normalize_cell(r.get(h)) for h in out_headers]
            out_rows.append(row_vals)
        return (out_headers, out_rows)
    except Exception as exc:
        return str(exc)


def execute_store_step(
    sql_or_refusal: tuple[str, list[str]] | Refusal,
    store: DuckStore,
) -> tuple[list[str], list[list[str | None]]] | Refusal | str:
    """Execute generated SQL against DuckStore.

    Returns (headers, rows_as_text_matrix), Refusal, or error message string.
    The headers come from the cursor description of the executed query, not from
    the generator's declared list (the declared list is only used for refusals).
    """
    if isinstance(sql_or_refusal, Refusal):
        return sql_or_refusal

    sql, _declared_headers = sql_or_refusal
    try:
        cursor = store._check_open().execute(sql)
        headers = [str(col[0]) for col in cursor.description]
        records = cursor.fetchall()
        out_rows: list[list[str | None]] = []
        for rec in records:
            row_vals = [normalize_cell(val) for val in rec]
            out_rows.append(row_vals)
        return (headers, out_rows)
    except Exception as exc:
        return str(exc)


def run_pq_step_diff(
    rows: int = 2000,
    seed: int = 42,
    overrides: dict[str, Any] | None = None,
    item_filter: list[str] | None = None,
    dataset: dict[str, Any] | None = None,
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run differential comparison between step engine and DuckStore SQL.

    `dataset` (optional, for small hand-checked tables) is
    {"headers": [...], "rows": [[...]], "rows_2": [[...]]}: it replaces the generated
    CSV files; `rows_2` is the second table for append (default: the first table reversed).
    `items` (optional) replaces the step catalog with explicit step items.
    """
    overrides = overrides or {}
    t_start = time.time()

    temp_dir = tempfile.mkdtemp(prefix="pq_store_diff_")
    t_path = Path(temp_dir)

    try:
        csv_file = t_path / "t.csv"
        csv_file_2 = t_path / "t2.csv"
        db_file = t_path / "store.db"

        if dataset is None:
            generate_pq_dataset(csv_file, rows=rows, seed=seed, include_blank_rows=True)
            generate_pq_dataset(csv_file_2, rows=min(rows, 100), seed=seed + 1, include_blank_rows=True)
        else:
            rows = len(dataset["rows"])
            rows_2 = dataset.get("rows_2", list(reversed(dataset["rows"])))
            for path, body in ((csv_file, dataset["rows"]), (csv_file_2, rows_2)):
                with open(path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(dataset["headers"])
                    writer.writerows(body)

        cand = parse_file(csv_file)
        cand_2 = parse_file(csv_file_2)
        headers = list(cand.headers)

        store = DuckStore(str(db_file))
        import_csv_to_store(store, "t_csv", csv_file, {})
        import_csv_to_store(store, "t_csv_2", csv_file_2, {})

        total_store_rows = store.execute('SELECT COUNT(*) FROM "t_csv"')[0][0]

        catalog = list(items) if items is not None else build_step_catalog(headers)
        if item_filter:
            catalog = [item for item in catalog if item["id"] in set(item_filter)]

        results: list[dict[str, Any]] = []

        for item in catalog:
            i_id = item["id"]
            step_op = item["step"]["op"]

            # 1. Reference side: step engine
            engine_res = execute_engine_step(item, cand, cand_2)

            # 2. SQL side: store
            # The 'remove the last column' item runs on a one-column table: the engine side is
            # cropped to one column, so the SQL side sees the same one-column header list and
            # refuses because of that, not because of a flag.
            sql_headers = headers
            if item.get("single_column_context"):
                sql_headers = headers[:1]
            elif item.get("pre_step"):
                kept = set(item["pre_step"]["columns"])
                sql_headers = [h for h in headers if h in kept]
            sql_or_ref = generate_step_sql(item, sql_headers, "t_csv", total_store_rows, overrides=overrides)
            store_res = execute_store_step(sql_or_ref, store)

            # 3. Compare
            diff_reason = ""
            diff_class = None
            status = "same"
            refusal_obj: Refusal | None = None

            if isinstance(store_res, Refusal):
                refusal_obj = store_res
                if isinstance(engine_res, str):
                    # Engine failed
                    if refusal_matches_engine_error(refusal_obj, engine_res):
                        status = "same"
                    else:
                        status = "refusal-reason-mismatch"
                        diff_reason = f"Refusal reason mismatch: expected {refusal_obj.expected_error!r} vs engine {engine_res!r}"
                else:
                    # SQL refused an operation where the engine succeeded
                    status = "refused"
                    diff_reason = f"SQL refused step: {refusal_obj.reason}"
            elif isinstance(store_res, str):
                # SQL execution threw an error
                status = "sql-error"
                diff_reason = f"SQL execution error: {store_res}"
            elif isinstance(engine_res, str):
                # Engine threw an error but SQL did not refuse
                status = "differs"
                diff_reason = f"Engine raised error but SQL succeeded: {engine_res}"
            else:
                # Both succeeded with (headers, rows)
                eng_headers, eng_rows = engine_res
                sql_headers, sql_rows = store_res

                if overrides.get("forced_wrong_value") and i_id == catalog[0]["id"]:
                    eng_rows = [["forced_diff_val"]]

                if eng_headers != sql_headers:
                    status = "differs"
                    diff_reason = f"Header mismatch: engine={eng_headers} vs sql={sql_headers}"
                elif len(eng_rows) != len(sql_rows):
                    status = "differs"
                    diff_reason = f"Row count mismatch: engine={len(eng_rows)} vs sql={len(sql_rows)}"
                else:
                    mismatch_sample = None
                    for r_idx, (e_row, s_row) in enumerate(zip(eng_rows, sql_rows)):
                        if e_row != s_row:
                            mismatch_sample = (r_idx, e_row, s_row)
                            break
                    if mismatch_sample is not None:
                        status = "differs"
                        r_idx, e_row, s_row = mismatch_sample
                        diff_reason = f"Row {r_idx} mismatch: engine={e_row[:3]} vs sql={s_row[:3]}"

            if status == "differs" and overrides.get("forced_diff_class"):
                diff_class = overrides["forced_diff_class"]

            results.append({
                "id": i_id,
                "step_op": step_op,
                "status": status,
                "diff_reason": diff_reason,
                "diff_class": diff_class,
                "refusal": str(refusal_obj) if refusal_obj else None,
                "refusal_reason": refusal_obj.reason if refusal_obj else None,
            })

        wall_sec = round(time.time() - t_start, 3)
        return {
            "version": 1,
            "rows": rows,
            "seed": seed,
            "wall_sec": wall_sec,
            "total_steps": len(catalog),
            "results": results,
        }
    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)


def evaluate_exit_policy(data: dict[str, Any], baseline: dict[str, Any]) -> tuple[int, list[str]]:
    """Exit policy: returns (exit code, failure messages).

    Exit 1 on:
      - Any sql-error
      - Any refusal-reason-mismatch
      - Any difference outside a named class in baseline
      - Any refusal not in the baseline refused list (if refused list provided)
    """
    results = data["results"]
    messages: list[str] = []

    sql_errors = [r for r in results if r["status"] == "sql-error"]
    if sql_errors:
        messages.append(f"FAILURE: {len(sql_errors)} SQL errors encountered: {[r['id'] for r in sql_errors]}")

    refusal_mismatches = [r for r in results if r["status"] == "refusal-reason-mismatch"]
    if refusal_mismatches:
        messages.append(f"FAILURE: {len(refusal_mismatches)} refusal reason mismatches: {[r['id'] for r in refusal_mismatches]}")

    expected_classes = set(baseline.get("classes", []))
    unclassified_diffs = [
        r["id"] for r in results
        if r["status"] == "differs" and r.get("diff_class") not in expected_classes
    ]
    if unclassified_diffs:
        messages.append(f"FAILURE: {len(unclassified_diffs)} unclassified differences: {unclassified_diffs}")

    expected_refusals = baseline.get("refused")
    if expected_refusals is not None:
        actual_refusals = {r["id"] for r in results if r.get("refusal")}
        if actual_refusals != set(expected_refusals):
            diff_set = actual_refusals.symmetric_difference(set(expected_refusals))
            messages.append(f"FAILURE: Refused step set changed vs baseline: {diff_set}")

    exit_code = 1 if messages else 0
    return exit_code, messages


def generate_markdown_report(data: dict[str, Any]) -> str:
    """Generate markdown summary report."""
    results = data["results"]
    total = len(results)
    same_cnt = sum(1 for r in results if r["status"] == "same")
    diff_cnt = sum(1 for r in results if r["status"] == "differs")
    ref_cnt = sum(1 for r in results if r["status"] == "refused" or r.get("refusal"))
    sql_err_cnt = sum(1 for r in results if r["status"] == "sql-error")
    ref_mismatch_cnt = sum(1 for r in results if r["status"] == "refusal-reason-mismatch")

    lines = [
        "# Power Query Step Differential Report (Stage D0a)",
        "",
        f"- **Rows:** {data['rows']:,}",
        f"- **Seed:** {data['seed']}",
        f"- **Execution Time:** {data['wall_sec']} s",
        f"- **Total Step Tests:** {total}",
        f"- **Same:** {same_cnt}",
        f"- **Differs:** {diff_cnt}",
        f"- **Refusals:** {ref_cnt}",
        f"- **SQL Errors:** {sql_err_cnt}",
        f"- **Refusal Reason Mismatches:** {ref_mismatch_cnt}",
        "",
        "## Counts by Step Operation",
        "",
        "| Operation | Total | Same | Differs | Refused |",
        "|---|---|---|---|---|",
    ]

    by_op: dict[str, dict[str, int]] = {}
    for r in results:
        op = r["step_op"]
        if op not in by_op:
            by_op[op] = {"total": 0, "same": 0, "differs": 0, "refused": 0}
        by_op[op]["total"] += 1
        if r["status"] == "same":
            by_op[op]["same"] += 1
        elif r["status"] == "differs":
            by_op[op]["differs"] += 1
        if r.get("refusal"):
            by_op[op]["refused"] += 1

    for op in sorted(by_op):
        st = by_op[op]
        lines.append(f"| `{op}` | {st['total']} | {st['same']} | {st['differs']} | {st['refused']} |")

    lines.extend([
        "",
        "## Power BI Answer Checks Needed",
        "",
        "Rules chosen where Power Query behavior must be checked against Power BI Desktop:",
        "1. `remove_blank_rows`: In Power Query, whitespace-only cells (spaces, tabs) are NOT considered blank (only NULL and empty string `''`). The SQL mapping uses `COALESCE(col, '') != ''` to preserve whitespace-only rows.",
        "2. `append`: In this slice, tables share identical ordered columns. In Power BI, appending tables with disparate or mismatched schemas unions columns by name; disparate schemas are deferred to Tier 2/3.",
        "3. `keep_range_rows` / `remove_top_rows`: When offset or count exceeds total table row count, Power Query yields an empty table without error. The SQL mapping uses `OFFSET` / `LIMIT` matching this behavior.",
        "4. `remove_alternate_rows`: Alternating row selection cycle logic is mapped to modular arithmetic over `row_number()`. Power Query 1-based indexing semantics verified against step engine.",
        "",
        "## Deferred Steps (Slice 2+)",
        "",
        "The following operations in `transformations.py` were deferred from Tier 1:",
        "- Row filtering & sorting: `filter_rows`, `filter_rows_advanced`, `sort_rows`, `sort_rows_by_columns`",
        "- Column manipulation: `merge_columns`, `split_column`, `split_column_by_each_delimiter`, `split_column_by_positions`, `split_column_to_rows`, `extract_text_by_delimiter`, `extract_text_between_delimiters`, `fill_down`, `fill_up`",
        "- Type conversions: `convert_type`, `convert_type_using_locale`",
        "- Value transformations: `replace_value`, `replace_error_values`, `trim_text`, `clean_text`, `lowercase_text`, `uppercase_text`, `proper_case_text`, `reverse_text`",
        "- Reshaping / Aggregation: `group_by`, `pivot_column`, `unpivot_columns`, `unpivot_other_columns`, `transpose_table`",
        "- Row deduplication: `remove_duplicates`, `keep_duplicates`",
        "- Header / Table structure: `promote_headers`, `demote_headers`, `table_pass_through`",
        "- Scripting & Custom: `m_script`, `add_custom_column`, `conditional_column`, `m_sparse_boundary_helper`",
        "- Error handling: `remove_rows_with_errors`, `keep_rows_with_errors`",
        "- Sparse row removal: `remove_sparse_top_rows`, `remove_sparse_bottom_rows`",
        "",
    ])

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Power Query step differential tool.")
    parser.add_argument("--rows", type=int, default=2000, help="Row count for generated data (default: 2000)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("--out", type=str, default="", help="Output markdown file path")
    parser.add_argument("--json", type=str, default="", help="Output JSON file path")
    parser.add_argument("--baseline", type=str, default="", help="Path to baseline JSON file")

    args = parser.parse_args()

    try:
        data = run_pq_step_diff(rows=args.rows, seed=args.seed)
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

    baseline_path = Path(args.baseline) if args.baseline else Path(__file__).parent / "pq_store_diff_baseline.json"
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
