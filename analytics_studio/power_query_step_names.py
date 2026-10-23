"""Power BI style applied-step names for generated Power Query M.

Power BI names each generated step after what it did ("Removed Columns",
"Filtered Rows", "Changed Type") and appends a number to repeats
("Removed Columns1", "Removed Columns2"). This module is the single place that
maps the local step operations to those names.
"""

from __future__ import annotations

from typing import Any, Iterable

_STEP_NAMES: dict[str, str] = {
    "count_rows": "Counted Rows",
    "count_distinct_rows": "Counted Rows",
    "remove_blank_rows": "Removed Blank Rows",
    "remove_rows_with_errors": "Removed Errors",
    "remove_column": "Removed Columns",
    "keep_columns": "Removed Other Columns",
    "rename_column": "Renamed Columns",
    "filter_rows": "Filtered Rows",
    "filter_rows_advanced": "Filtered Rows",
    "add_custom_column": "Added Custom",
    "conditional_column": "Added Conditional Column",
    "convert_type": "Changed Type",
    "convert_type_using_locale": "Changed Type with Locale",
    "sort_rows": "Sorted Rows",
    "sort_rows_by_columns": "Sorted Rows",
    "remove_duplicates": "Removed Duplicates",
    "keep_duplicates": "Kept Duplicates",
    "keep_top_rows": "Kept First Rows",
    "keep_bottom_rows": "Kept Last Rows",
    "keep_range_rows": "Kept Range of Rows",
    "remove_top_rows": "Removed Top Rows",
    "remove_bottom_rows": "Removed Bottom Rows",
    "remove_sparse_top_rows": "Removed Top Rows",
    "remove_sparse_bottom_rows": "Removed Bottom Rows",
    "remove_alternate_rows": "Removed Alternate Rows",
    "group_by": "Grouped Rows",
    "unpivot_columns": "Unpivoted Columns",
    "unpivot_other_columns": "Unpivoted Other Columns",
    "pivot_column": "Pivoted Column",
    "replace_value": "Replaced Value",
    "extract_text_by_delimiter": "Extracted Text Delimiter",
    "extract_text_between_delimiters": "Extracted Text Between Delimiters",
    "split_column": "Split Column by Delimiter",
    "split_column_by_each_delimiter": "Split Column by Delimiter",
    "split_column_to_rows": "Split Column by Delimiter",
    "split_column_by_positions": "Split Column by Position",
    "merge_columns": "Merged Columns",
    "trim_text": "Trimmed Text",
    "clean_text": "Cleaned Text",
    "lowercase_text": "Lowercased Text",
    "uppercase_text": "Uppercased Text",
    "proper_case_text": "Capitalized Each Word",
    "reverse_text": "Reversed Text",
    "reorder_columns": "Reordered Columns",
    "promote_headers": "Promoted Headers",
    "demote_headers": "Demoted Headers",
    "transpose_table": "Transposed Table",
    "add_index_column": "Added Index",
    "duplicate_column": "Duplicated Column",
    "fill_down": "Filled Down",
    "fill_up": "Filled Up",
}


def power_bi_step_name(step: dict[str, Any]) -> str:
    """Return the base Power BI name for one applied step."""
    op = str(step.get("op", ""))
    if op == "extract_text_by_delimiter":
        side = str(step.get("side", "")).casefold()
        if side == "before":
            return "Extracted Text Before Delimiter"
        if side == "after":
            return "Extracted Text After Delimiter"
    return _STEP_NAMES.get(op, "Changed Step")


def assign_step_names(
    steps: list[dict[str, Any]],
    *,
    custom_names: Iterable[str | None] | None = None,
    reserved: Iterable[str] = (),
) -> list[str]:
    """Return one unique M binding name per step.

    ``custom_names`` carries names the user typed in the Applied Steps pane;
    an empty entry falls back to the Power BI style name. Repeated names get a
    numeric suffix ("Removed Columns1"). Names are compared case-insensitively
    and never collide with ``reserved`` bindings such as ``Source``.
    """
    custom = list(custom_names or [])
    taken = {str(name).casefold() for name in reserved}
    used_bases: dict[str, int] = {}
    names: list[str] = []
    for index, step in enumerate(steps):
        wanted = ""
        if index < len(custom) and isinstance(custom[index], str):
            wanted = custom[index].strip()
        base = wanted or power_bi_step_name(step)
        candidate = base
        suffix = used_bases.get(base.casefold(), 0)
        while candidate.casefold() in taken:
            suffix += 1
            candidate = f"{base}{suffix}"
        used_bases[base.casefold()] = suffix
        taken.add(candidate.casefold())
        names.append(candidate)
    return names
