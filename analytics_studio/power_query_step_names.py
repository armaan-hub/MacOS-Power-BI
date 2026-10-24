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
    "split_column_by_positions": "Split Column by Positions",
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


def is_known_power_bi_step(step: dict[str, Any]) -> bool:
    """Whether Power BI has a default step name for this operation."""
    return str(step.get("op", "")) in _STEP_NAMES


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


def carry_step_metadata(
    old_bindings: list[str],
    old_ops: list[str],
    old_metadata: list[dict[str, str]],
    new_bindings: list[str],
    new_ops: list[str],
) -> list[dict[str, str]]:
    """Follow custom step names/descriptions through a text edit by step identity.

    ``*_bindings`` hold the let-binding name each step had (one per step).  A step keeps its
    metadata when its binding name is unchanged; a binding renamed in place (the surrounding
    steps are unchanged) keeps the description and takes the new name.  A step whose operation
    changed, or that is new, starts empty.  Nothing is ever carried by position alone.
    """
    from copy import deepcopy
    from difflib import SequenceMatcher

    result: list[dict[str, str]] = [{} for _ in new_ops]
    if (
        len(old_bindings) != len(old_ops)
        or len(new_bindings) != len(new_ops)
        or len(old_metadata) < len(old_ops)
    ):
        if old_ops == new_ops and len(old_metadata) >= len(new_ops):
            return [deepcopy(item) for item in old_metadata[:len(new_ops)]]  # nothing moved
        return result
    matcher = SequenceMatcher(
        None,
        [name.casefold() for name in old_bindings],
        [name.casefold() for name in new_bindings],
        autojunk=False,
    )
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            pairs = [(i1 + k, j1 + k, False) for k in range(i2 - i1)]
        elif tag == "replace" and i2 - i1 == j2 - j1:
            pairs = [(i1 + k, j1 + k, True) for k in range(i2 - i1)]
        else:
            continue
        for old_index, new_index, renamed in pairs:
            if old_ops[old_index] != new_ops[new_index]:
                continue
            item = deepcopy(old_metadata[old_index])
            if renamed:
                item.pop("name", None)
                new_name = new_bindings[new_index]
                if sum(1 for name in new_bindings if name.casefold() == new_name.casefold()) == 1:
                    item["name"] = new_name
            if item:
                result[new_index] = item
    return result
