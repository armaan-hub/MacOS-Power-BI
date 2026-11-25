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


# The store's own load-order column (hidden); DuckStore.read_page orders by it, never by the physical rowid.
_RN = '"__rn"'


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

        # Plant deterministic shapes per brief D0e:
        # non-ASCII letters in text_col, numeric variations in num_col, trailing space ties in cat_col
        if i == 11:
            t_str = "café"
        elif i == 12:
            t_str = "İSTANBUL"
        elif i == 13:
            t_str = "Σ"
        elif i == 14:
            t_str = "straße"
        elif i == 15:
            n_str = "+123"
        elif i == 16:
            n_str = "1e3"
        elif i == 17:
            n_str = "-0.50"
        elif i == 18:
            n_str = "1,234.56"
        elif i == 19:
            c_str = "cat "
        elif i == 20:
            c_str = "cat"

        if rnd.random() < 0.05 and i > 20:
            t_str = rnd.choice(WHITESPACE_CELLS)
        if rnd.random() < 0.05 and i > 20:
            c_str = rnd.choice(WHITESPACE_CELLS)
        if rnd.random() < 0.03 and i > 20:
            b_str = rnd.choice(WHITESPACE_CELLS)

        if i == 1 or i == rows:
            b_str = ""

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

    # Slice 2 steps:
    # 16. sort_rows
    catalog.append({
        "id": "sort_rows_cat_asc",
        "step": {"op": "sort_rows", "column": "cat_col" if "cat_col" in headers else headers[0], "direction": "asc"},
    })
    catalog.append({
        "id": "sort_rows_cat_desc",
        "step": {"op": "sort_rows", "column": "cat_col" if "cat_col" in headers else headers[0], "direction": "desc"},
    })
    if "num_col" in headers:
        catalog.append({
            "id": "sort_rows_num_col_asc",
            "step": {"op": "sort_rows", "column": "num_col", "direction": "asc"},
        })
    if "text_col" in headers:
        catalog.append({
            "id": "sort_rows_text_col_non_ascii",
            "step": {"op": "sort_rows", "column": "text_col", "direction": "asc"},
        })
    catalog.append({
        "id": "sort_rows_missing_col",
        "step": {"op": "sort_rows", "column": "missing_xyz", "direction": "asc"},
    })

    # 17. sort_rows_by_columns
    if n_cols >= 2:
        c1 = "cat_col" if "cat_col" in headers else headers[0]
        c2 = headers[1] if headers[1] != c1 and headers[1] != "text_col" else headers[0]
        catalog.append({
            "id": "sort_rows_by_columns_two_cols",
            "step": {"op": "sort_rows_by_columns", "sorts": [{"column": c1, "direction": "asc"}, {"column": c2, "direction": "desc"}]},
        })
    catalog.append({
        "id": "sort_rows_by_columns_missing_col",
        "step": {"op": "sort_rows_by_columns", "sorts": [{"column": "missing_xyz", "direction": "asc"}]},
    })

    # 18. filter_rows
    target_text_col = "cat_col" if "cat_col" in headers else headers[0]
    catalog.append({
        "id": "filter_rows_equals",
        "step": {"op": "filter_rows", "column": target_text_col, "operator": "equals", "value": "A"},
    })
    catalog.append({
        "id": "filter_rows_not_equals",
        "step": {"op": "filter_rows", "column": target_text_col, "operator": "not_equals", "value": "A"},
    })
    catalog.append({
        "id": "filter_rows_is_null",
        "step": {"op": "filter_rows", "column": target_text_col, "operator": "is_null", "value": ""},
    })
    catalog.append({
        "id": "filter_rows_is_not_null",
        "step": {"op": "filter_rows", "column": target_text_col, "operator": "is_not_null", "value": ""},
    })
    catalog.append({
        "id": "filter_rows_is_blank",
        "step": {"op": "filter_rows", "column": target_text_col, "operator": "is_blank", "value": ""},
    })
    catalog.append({
        "id": "filter_rows_is_not_blank",
        "step": {"op": "filter_rows", "column": target_text_col, "operator": "is_not_blank", "value": ""},
    })
    catalog.append({
        "id": "filter_rows_contains",
        "step": {"op": "filter_rows", "column": target_text_col, "operator": "contains", "value": "B"},
    })
    catalog.append({
        "id": "filter_rows_does_not_contain",
        "step": {"op": "filter_rows", "column": target_text_col, "operator": "does_not_contain", "value": "B"},
    })
    catalog.append({
        "id": "filter_rows_begins_with",
        "step": {"op": "filter_rows", "column": target_text_col, "operator": "begins_with", "value": "A"},
    })
    catalog.append({
        "id": "filter_rows_does_not_begin_with",
        "step": {"op": "filter_rows", "column": target_text_col, "operator": "does_not_begin_with", "value": "A"},
    })
    catalog.append({
        "id": "filter_rows_ends_with",
        "step": {"op": "filter_rows", "column": target_text_col, "operator": "ends_with", "value": "C"},
    })
    catalog.append({
        "id": "filter_rows_does_not_end_with",
        "step": {"op": "filter_rows", "column": target_text_col, "operator": "does_not_end_with", "value": "C"},
    })
    if "date_col" in headers:
        catalog.append({
            "id": "filter_rows_date_before",
            "step": {"op": "filter_rows", "column": "date_col", "operator": "date_before", "value": "2026-06-15"},
        })
        catalog.append({
            "id": "filter_rows_date_after",
            "step": {"op": "filter_rows", "column": "date_col", "operator": "date_after", "value": "2026-06-15"},
        })
        catalog.append({
            "id": "filter_rows_date_on_or_before",
            "step": {"op": "filter_rows", "column": "date_col", "operator": "date_on_or_before", "value": "2026-06-15"},
        })
        catalog.append({
            "id": "filter_rows_date_on_or_after",
            "step": {"op": "filter_rows", "column": "date_col", "operator": "date_on_or_after", "value": "2026-06-15"},
        })
        catalog.append({
            "id": "filter_rows_is_earliest",
            "step": {"op": "filter_rows", "column": "date_col", "operator": "is_earliest", "value": ""},
        })
        catalog.append({
            "id": "filter_rows_is_latest",
            "step": {"op": "filter_rows", "column": "date_col", "operator": "is_latest", "value": ""},
        })
    if "num_col" in headers:
        catalog.append({
            "id": "filter_rows_numeric_greater_than",
            "step": {"op": "filter_rows", "column": "num_col", "operator": "greater_than", "value": "10"},
        })
        catalog.append({
            "id": "filter_rows_numeric_less_than",
            "step": {"op": "filter_rows", "column": "num_col", "operator": "less_than", "value": "100"},
        })
        catalog.append({
            "id": "filter_rows_numeric_greater_than_or_equal",
            "step": {"op": "filter_rows", "column": "num_col", "operator": "greater_than_or_equal", "value": "0"},
        })
        catalog.append({
            "id": "filter_rows_numeric_less_than_or_equal",
            "step": {"op": "filter_rows", "column": "num_col", "operator": "less_than_or_equal", "value": "50"},
        })
    catalog.append({
        "id": "filter_rows_missing_col",
        "step": {"op": "filter_rows", "column": "missing_xyz", "operator": "equals", "value": "test"},
    })

    # 19. filter_rows_advanced
    clauses = [
        {"column": target_text_col, "operator": "equals", "value": "A", "join": "and"},
    ]
    if "date_col" in headers:
        clauses.append({"column": "date_col", "operator": "date_before", "value": "2026-06-15", "join": "and"})
    clauses.append({"column": target_text_col, "operator": "equals", "value": "B", "join": "or"})
    catalog.append({
        "id": "filter_rows_advanced_combo",
        "step": {"op": "filter_rows_advanced", "clauses": clauses},
    })
    catalog.append({
        "id": "filter_rows_advanced_missing_col",
        "step": {"op": "filter_rows_advanced", "clauses": [{"column": "missing_xyz", "operator": "equals", "value": "val", "join": "and"}]},
    })

    # 20. remove_duplicates
    catalog.append({
        "id": "remove_duplicates_single_col",
        "step": {"op": "remove_duplicates", "columns": [target_text_col]},
    })
    if n_cols >= 2:
        c_sec = headers[1] if headers[0] == target_text_col else headers[0]
        catalog.append({
            "id": "remove_duplicates_two_cols",
            "step": {"op": "remove_duplicates", "columns": [target_text_col, c_sec]},
        })
    catalog.append({
        "id": "remove_duplicates_missing_col",
        "step": {"op": "remove_duplicates", "columns": ["missing_xyz"]},
    })

    # 21. keep_duplicates
    catalog.append({
        "id": "keep_duplicates_single_col",
        "step": {"op": "keep_duplicates", "columns": [target_text_col]},
    })
    if n_cols >= 2:
        c_sec = headers[1] if headers[0] == target_text_col else headers[0]
        catalog.append({
            "id": "keep_duplicates_two_cols",
            "step": {"op": "keep_duplicates", "columns": [target_text_col, c_sec]},
        })
    catalog.append({
        "id": "keep_duplicates_missing_col",
        "step": {"op": "keep_duplicates", "columns": ["missing_xyz"]},
    })

    # 22. fill_down & fill_up
    catalog.append({
        "id": "fill_down_single_col",
        "step": {"op": "fill_down", "columns": [target_text_col]},
    })
    if n_cols >= 2:
        c_sec = headers[1] if headers[0] == target_text_col else headers[0]
        catalog.append({
            "id": "fill_down_two_cols",
            "step": {"op": "fill_down", "columns": [target_text_col, c_sec]},
        })
    catalog.append({
        "id": "fill_down_missing_col",
        "step": {"op": "fill_down", "columns": ["missing_xyz"]},
    })
    catalog.append({
        "id": "fill_up_single_col",
        "step": {"op": "fill_up", "columns": [target_text_col]},
    })
    if n_cols >= 2:
        c_sec = headers[1] if headers[0] == target_text_col else headers[0]
        catalog.append({
            "id": "fill_up_two_cols",
            "step": {"op": "fill_up", "columns": [target_text_col, c_sec]},
        })
    catalog.append({
        "id": "fill_up_missing_col",
        "step": {"op": "fill_up", "columns": ["missing_xyz"]},
    })

    return catalog


def inspect_store_columns(
    store: DuckStore | None,
    table_name: str,
    headers: list[str],
) -> dict[str, dict[str, bool]]:
    """Inspect columns in DuckStore to discover if they are purely numeric or contain non-ASCII letters.

    Returns dict mapping column name to {'is_num': bool, 'has_non_ascii': bool}.
    Uses public store.execute() with a single batched aggregation query.
    """
    meta: dict[str, dict[str, bool]] = {}
    if not headers or store is None:
        return meta
    selects: list[str] = []
    for h in headers:
        num_rx = r'^[+-]?((\d+(\.\d*)?)|(\.\d+))([eE][+-]?\d+)?$'
        non_ascii_rx = r'[^\x00-\x7F]'
        letter_rx = r'\p{L}'
        selects.append(
            f'COUNT(CASE WHEN "{h}" IS NOT NULL AND "{h}" != \'\' THEN 1 END), '
            f'COUNT(CASE WHEN "{h}" IS NOT NULL AND "{h}" != \'\' AND regexp_matches("{h}", \'{num_rx}\') = false THEN 1 END), '
            f'COUNT(CASE WHEN "{h}" IS NOT NULL AND "{h}" != \'\' AND regexp_matches("{h}", \'{non_ascii_rx}\') AND regexp_matches("{h}", \'{letter_rx}\') THEN 1 END)'
        )
    sql = "SELECT " + ", ".join(selects) + f' FROM "{table_name}"'
    records = store.execute(sql)
    row = records[0] if isinstance(records, list) else records.fetchall()[0]
    idx = 0
    for h in headers:
        cnt, non_num, non_ascii = row[idx], row[idx + 1], row[idx + 2]
        meta[h] = {
            "is_num": (cnt > 0 and non_num == 0),
            "has_non_ascii": (cnt > 0 and non_ascii > 0),
        }
        idx += 3
    return meta


def generate_step_sql(
    item: dict[str, Any],
    headers: list[str],
    table_name: str,
    total_rows: int,
    overrides: dict[str, Any] | None = None,
    col_meta: dict[str, dict[str, bool]] | None = None,
) -> tuple[str, list[str]] | Refusal:
    """Generate SQL query and expected output columns for a step item.

    Returns (sql_query, output_headers) or a Refusal object.
    `mutant_null_for_blank` (inert by default) wraps every selected column in
    NULLIF(col, '') so a blank cell comes back as NULL; the tool must flag it.
    """
    overrides = overrides or {}
    result = _mapped_sql(item, headers, table_name, total_rows, overrides, col_meta=col_meta)
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
    col_meta: dict[str, dict[str, bool]] | None = None,
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
        order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
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
        order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
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
        order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
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
        order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
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
        order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
        return (f"SELECT {col_list} FROM {t_q} {order_clause}", out_headers)

    # 6. keep_top_rows
    if op == "keep_top_rows":
        count = step["count"]
        if overrides.get("mutant_top_off_by_one"):
            count += 1
        col_list = ", ".join(f'"{c}"' for c in headers)
        order_clause = "" if overrides.get("mutant_no_order_by") else f"ORDER BY {_RN}"
        return (f"SELECT {col_list} FROM {t_q} {order_clause} LIMIT {count}", list(headers))

    # 7. remove_top_rows
    if op == "remove_top_rows":
        count = step["count"]
        col_list = ", ".join(f'"{c}"' for c in headers)
        order_clause = "" if overrides.get("mutant_no_order_by") else f"ORDER BY {_RN}"
        return (f"SELECT {col_list} FROM {t_q} {order_clause} OFFSET {count}", list(headers))

    # 8. keep_bottom_rows
    if op == "keep_bottom_rows":
        count = step["count"]
        offset = max(0, total_rows - count)
        col_list = ", ".join(f'"{c}"' for c in headers)
        order_clause = "" if overrides.get("mutant_no_order_by") else f"ORDER BY {_RN}"
        return (f"SELECT {col_list} FROM {t_q} {order_clause} OFFSET {offset} LIMIT {count}", list(headers))

    # 9. remove_bottom_rows
    if op == "remove_bottom_rows":
        count = step["count"]
        keep_count = max(0, total_rows - count)
        col_list = ", ".join(f'"{c}"' for c in headers)
        order_clause = "" if overrides.get("mutant_no_order_by") else f"ORDER BY {_RN}"
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
        order_clause = "" if overrides.get("mutant_no_order_by") else f"ORDER BY {_RN}"
        return (f"SELECT {col_list} FROM {t_q} {order_clause} OFFSET {offset} LIMIT {count}", list(headers))

    # 11. remove_alternate_rows
    if op == "remove_alternate_rows":
        first_to_remove = step["first_row_to_remove"]
        rem = step["remove_count"]
        kp = step["keep_count"]
        if overrides.get("mutant_alt_offset_wrong"):
            first_to_remove += 1
        window_order = f"ORDER BY {_RN} DESC" if overrides.get("mutant_window_order_desc") else f"ORDER BY {_RN}"

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
        window_order = f"ORDER BY {_RN} DESC" if overrides.get("mutant_window_order_desc") else f"ORDER BY {_RN}"
        idx_expr = f"{start} + (CAST(row_number() OVER ({window_order}) AS BIGINT) - 1) * {inc}"
        out_headers = [*headers, new_name]
        order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
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
        order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
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
            f"  SELECT {col_list}, 0 AS _src, {_RN} AS _rn FROM {t_q}"
            f"  UNION ALL"
            f"  SELECT {second_cols}, 1 AS _src, {_RN} AS _rn FROM \"{second_tbl}\""
            f") {order_clause}"
        )
        return (sql, list(headers))

    # Helper for sorting a single column
    def _build_sort_expr(col: str, direction: str) -> str | Refusal:
        m = (col_meta or {}).get(col, {})
        if overrides.get("mutant_sort_ignore_non_ascii"):
            has_non_ascii = False
        else:
            has_non_ascii = m.get("has_non_ascii", False)

        if has_non_ascii:
            return Refusal(
                f"Non-ASCII letters in column '{col}' sort differ between Python casefold and SQL lower.",
                expected_error=None,
            )

        if overrides.get("mutant_sort_numeric_as_text"):
            is_num = False
        else:
            is_num = m.get("is_num", False)

        dir_sql = direction.upper()

        if overrides.get("mutant_sort_nulls_first"):
            null_clause = f'CASE WHEN "{col}" IS NULL OR "{col}" = \'\' THEN 0 ELSE 1 END ASC'
        else:
            null_clause = f'CASE WHEN "{col}" IS NULL OR "{col}" = \'\' THEN 1 ELSE 0 END ASC'

        if is_num:
            val_clause = f'TRY_CAST("{col}" AS DOUBLE) {dir_sql}'
        else:
            val_clause = f'"{col}" {dir_sql}'

        return f"{null_clause}, {val_clause}"

    # 16. sort_rows
    if op == "sort_rows":
        col = step["column"]
        if col not in headers:
            return Refusal(
                f"Column {col!r} does not exist.",
                expected_error=f"Column {col!r} does not exist.",
            )
        direction = step["direction"]
        sort_expr = _build_sort_expr(col, direction)
        if isinstance(sort_expr, Refusal):
            return sort_expr
        col_list = ", ".join(f'"{c}"' for c in headers)
        if overrides.get("mutant_sort_no_rn_tiebreak"):
            rn_clause = ""
        else:
            rn_clause = f', {_RN} ASC' if not overrides.get("mutant_sort_reverse_ties") else f', {_RN} DESC'
        sql = f"SELECT {col_list} FROM {t_q} ORDER BY {sort_expr}{rn_clause}"
        return (sql, list(headers))

    # 17. sort_rows_by_columns
    if op == "sort_rows_by_columns":
        sorts = step["sorts"]
        sort_parts: list[str] = []
        for s in sorts:
            col = s["column"]
            if col not in headers:
                return Refusal(
                    f"Column {col!r} does not exist.",
                    expected_error=f"Column {col!r} does not exist.",
                )
            direction = s["direction"]
            sort_expr = _build_sort_expr(col, direction)
            if isinstance(sort_expr, Refusal):
                return sort_expr
            sort_parts.append(sort_expr)
        col_list = ", ".join(f'"{c}"' for c in headers)
        combined_sort = ", ".join(sort_parts)
        if overrides.get("mutant_sort_no_rn_tiebreak"):
            rn_clause = ""
        else:
            rn_clause = f', {_RN} ASC' if not overrides.get("mutant_sort_reverse_ties") else f', {_RN} DESC'
        sql = f"SELECT {col_list} FROM {t_q} ORDER BY {combined_sort}{rn_clause}"
        return (sql, list(headers))

    # 18. filter_rows
    def _build_filter_condition(col: str, operator: str, expected: str) -> str | Refusal:
        if col not in headers:
            return Refusal(
                f"Column {col!r} does not exist.",
                expected_error=f"Column {col!r} does not exist.",
            )
        m = (col_meta or {}).get(col, {})
        # Numeric operators
        if operator in {"greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"}:
            if not m.get("is_num", False):
                return Refusal(
                    f"Column {col!r} contains non-numeric values.",
                    expected_error=f"of column '{col}' is not a valid number.",
                )
            op_map = {
                "greater_than": ">",
                "greater_than_or_equal": ">=",
                "less_than": "<",
                "less_than_or_equal": "<=",
            }
            if overrides.get("mutant_filter_op_off_by_one"):
                # Mutant changes strict to inclusive or vice versa
                op_map = {
                    "greater_than": ">=",
                    "greater_than_or_equal": ">",
                    "less_than": "<=",
                    "less_than_or_equal": "<",
                }
            sql_op = op_map[operator]
            return f'("{col}" IS NOT NULL AND "{col}" != \'\' AND TRY_CAST("{col}" AS DOUBLE) {sql_op} {expected})'

        # Date operators
        if operator in {"date_before", "date_after", "date_on_or_before", "date_on_or_after"}:
            op_map = {
                "date_before": "<",
                "date_after": ">",
                "date_on_or_before": "<=",
                "date_on_or_after": ">=",
            }
            if overrides.get("mutant_filter_op_off_by_one"):
                op_map = {
                    "date_before": "<=",
                    "date_after": ">=",
                    "date_on_or_before": "<",
                    "date_on_or_after": ">",
                }
            sql_op = op_map[operator]
            return (
                f'("{col}" IS NOT NULL AND "{col}" != \'\' AND '
                f'TRY_CAST(trim("{col}") AS TIMESTAMP) IS NOT NULL AND '
                f'TRY_CAST(trim("{col}") AS TIMESTAMP) {sql_op} TIMESTAMP \'{expected} 00:00:00\')'
            )

        # Text and equality operators
        if operator == "equals":
            if overrides.get("mutant_filter_trim_trailing_spaces"):
                return f'rtrim(COALESCE("{col}", \'\')) = \'{expected}\''
            return f'"{col}" = \'{expected}\''
        if operator == "not_equals":
            return f'("{col}" IS NULL OR "{col}" != \'{expected}\')'
        if operator == "is_null":
            return f'"{col}" IS NULL'
        if operator == "is_not_null":
            return f'"{col}" IS NOT NULL'
        if operator == "is_blank":
            return f'("{col}" IS NULL OR "{col}" = \'\')'
        if operator == "is_not_blank":
            return f'("{col}" IS NOT NULL AND "{col}" != \'\')'
        if operator == "contains":
            return f'instr(COALESCE("{col}", \'\'), \'{expected}\') > 0'
        if operator == "does_not_contain":
            return f'instr(COALESCE("{col}", \'\'), \'{expected}\') = 0'
        if operator == "begins_with":
            return f'starts_with(COALESCE("{col}", \'\'), \'{expected}\')'
        if operator == "does_not_begin_with":
            return f'NOT starts_with(COALESCE("{col}", \'\'), \'{expected}\')'
        if operator == "ends_with":
            return f'ends_with(COALESCE("{col}", \'\'), \'{expected}\')'
        if operator == "does_not_end_with":
            return f'NOT ends_with(COALESCE("{col}", \'\'), \'{expected}\')'

        return Refusal(f"Unsupported filter operator {operator!r}")

    if op == "filter_rows":
        col = step["column"]
        operator = step["operator"]
        expected = step.get("value", "")
        if operator in {"is_earliest", "is_latest"}:
            if col not in headers:
                return Refusal(
                    f"Column {col!r} does not exist.",
                    expected_error=f"Column {col!r} does not exist.",
                )
            func = "MIN" if operator == "is_earliest" else "MAX"
            col_list = ", ".join(f'"{c}"' for c in headers)
            order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
            sql = (
                f"WITH _dstats AS ("
                f'  SELECT {func}(TRY_CAST(trim("{col}") AS TIMESTAMP)) AS _target_dt '
                f"  FROM {t_q} "
                f'  WHERE "{col}" IS NOT NULL AND "{col}" != \'\' AND TRY_CAST(trim("{col}") AS TIMESTAMP) IS NOT NULL'
                f") "
                f"SELECT {col_list} FROM {t_q}, _dstats "
                f'WHERE TRY_CAST(trim("{col}") AS TIMESTAMP) = _dstats._target_dt '
                f"{order_clause}"
            )
            return (sql, list(headers))

        cond = _build_filter_condition(col, operator, expected)
        if isinstance(cond, Refusal):
            return cond
        col_list = ", ".join(f'"{c}"' for c in headers)
        order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
        sql = f"SELECT {col_list} FROM {t_q} WHERE {cond} {order_clause}"
        return (sql, list(headers))

    # 19. filter_rows_advanced
    if op == "filter_rows_advanced":
        clauses = step["clauses"]
        or_groups: list[list[str]] = []
        curr_and_group: list[str] = []
        for c_idx, cl in enumerate(clauses):
            c_col = cl["column"]
            c_op = cl["operator"]
            c_val = cl.get("value", "")
            c_join = cl.get("join", "and")
            c_cond = _build_filter_condition(c_col, c_op, c_val)
            if isinstance(c_cond, Refusal):
                return c_cond
            if c_idx == 0 or c_join == "and":
                curr_and_group.append(c_cond)
            else:
                or_groups.append(curr_and_group)
                curr_and_group = [c_cond]
        or_groups.append(curr_and_group)

        group_sqls = ["(" + " AND ".join(grp) + ")" for grp in or_groups if grp]
        where_sql = " OR ".join(group_sqls)
        col_list = ", ".join(f'"{c}"' for c in headers)
        order_clause = f"ORDER BY {_RN} DESC" if overrides.get("mutant_reverse_order") else f"ORDER BY {_RN}"
        sql = f"SELECT {col_list} FROM {t_q} WHERE ({where_sql}) {order_clause}"
        return (sql, list(headers))

    # 20. remove_duplicates
    if op == "remove_duplicates":
        cols = step.get("columns", headers)
        for c in cols:
            if c not in headers:
                return Refusal(
                    f"Column {c!r} does not exist.",
                    expected_error=f"Column {c!r} does not exist.",
                )
        if overrides.get("mutant_duplicate_casefold"):
            part_exprs = [f'("{c}" IS NULL), lower("{c}")' for c in cols]
        else:
            part_exprs = [f'("{c}" IS NULL), "{c}"' for c in cols]
        part_clause = ", ".join(part_exprs)
        col_list = ", ".join(f'"{c}"' for c in headers)
        sql = (
            f"SELECT {col_list} FROM ("
            f"  SELECT {col_list}, "
            f"         row_number() OVER (PARTITION BY {part_clause} ORDER BY {_RN}) AS _dup_rn, "
            f"         {_RN} "
            f"  FROM {t_q}"
            f") WHERE _dup_rn = 1 ORDER BY {_RN}"
        )
        return (sql, list(headers))

    # 21. keep_duplicates
    if op == "keep_duplicates":
        cols = step.get("columns", headers)
        for c in cols:
            if c not in headers:
                return Refusal(
                    f"Column {c!r} does not exist.",
                    expected_error=f"Column {c!r} does not exist.",
                )
        if overrides.get("mutant_duplicate_casefold"):
            part_exprs = [f'("{c}" IS NULL), lower("{c}")' for c in cols]
        else:
            part_exprs = [f'("{c}" IS NULL), "{c}"' for c in cols]
        part_clause = ", ".join(part_exprs)
        col_list = ", ".join(f'"{c}"' for c in headers)
        sql = (
            f"SELECT {col_list} FROM ("
            f"  SELECT {col_list}, "
            f"         count(*) OVER (PARTITION BY {part_clause}) AS _dup_cnt, "
            f"         {_RN} "
            f"  FROM {t_q}"
            f") WHERE _dup_cnt > 1 ORDER BY {_RN}"
        )
        return (sql, list(headers))

    # 22. fill_down & fill_up
    if op in {"fill_down", "fill_up"}:
        cols = step["columns"]
        for c in cols:
            if c not in headers:
                return Refusal(
                    f"Column {c!r} does not exist.",
                    expected_error=f"Column {c!r} does not exist.",
                )
        fill_set = set(cols)
        c_exprs: list[str] = []
        for h in headers:
            if h in fill_set:
                if overrides.get("mutant_fill_across_whitespace"):
                    # Blank defined by trim(c) != '' so whitespace cell is overwritten
                    non_null_expr = f'CASE WHEN "{h}" IS NOT NULL AND trim("{h}") != \'\' THEN "{h}" END'
                else:
                    non_null_expr = f'CASE WHEN "{h}" IS NOT NULL THEN "{h}" END'

                if op == "fill_down":
                    c_exprs.append(
                        f'COALESCE(last_value({non_null_expr} IGNORE NULLS) '
                        f'OVER (ORDER BY {_RN} ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW), "{h}") AS "{h}"'
                    )
                else:
                    c_exprs.append(
                        f'COALESCE(first_value({non_null_expr} IGNORE NULLS) '
                        f'OVER (ORDER BY {_RN} ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING), "{h}") AS "{h}"'
                    )
            else:
                c_exprs.append(f'"{h}"')
        col_list = ", ".join(c_exprs)
        sql = f"SELECT {col_list} FROM {t_q} ORDER BY {_RN}"
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
        # Public guard path only: execute() is SELECT-only; DESCRIBE is wrapped in a SELECT.
        headers = [str(r[0]) for r in store.execute(f"SELECT column_name FROM (DESCRIBE {sql})")]
        records = store.execute(sql)
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
        col_meta = inspect_store_columns(store, "t_csv", headers)

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
            sql_or_ref = generate_step_sql(item, sql_headers, "t_csv", total_store_rows, overrides=overrides, col_meta=col_meta)
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
        "5. Does Power Query keep an all-blank CSV row (`,,`) as a row of nulls? The app's CSV loader (engine parser and store import) drops all-blank rows at load, so remove_blank_rows on an imported CSV is the identity.",
        "6. `sort_rows` on mixed columns: The engine sorts numerically only if every non-empty cell parses as a number; otherwise falls back to text casefold sort. Power BI Desktop behaviour on mixed columns needs checking.",
        "7. `sort_rows` Python casefold vs DuckDB lower: Non-ASCII characters (e.g. 'ß', 'İ', 'Σ') differ in casefold vs lower; column sort is refused when non-ASCII letters are present.",
        "8. `filter_rows` on dates: Dates parsed via ISO strings; Power BI culture-specific date parsing needs verification.",
        "9. Duplicate keys on numeric text: `cell_key` treats distinct string representations ('1' vs '1.0') distinctly for un-converted text columns, but equal if converted to Decimal.",
        "10. `fill_down` / `fill_up` whitespace: Whitespace-only cells are treated as non-blank and not overwritten.",
        "",
        "## Deferred Steps (Slice 2+)",
        "",
        "The following operations in `transformations.py` remain deferred:",
        "- Column manipulation: `merge_columns`, `split_column`, `split_column_by_each_delimiter`, `split_column_by_positions`, `split_column_to_rows`, `extract_text_by_delimiter`, `extract_text_between_delimiters`",
        "- Type conversions: `convert_type`, `convert_type_using_locale`",
        "- Value transformations: `replace_value`, `replace_error_values`, `trim_text`, `clean_text`, `lowercase_text`, `uppercase_text`, `proper_case_text`, `reverse_text`",
        "- Reshaping / Aggregation: `group_by`, `pivot_column`, `unpivot_columns`, `unpivot_other_columns`, `transpose_table`",
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
