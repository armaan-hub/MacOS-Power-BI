"""Small, bounded query operations over loaded project tables."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Sequence

from analytics_studio.file_import import MAX_CELLS, MAX_COLUMNS, MAX_DATA_ROWS, ImportCandidate


class QueryError(ValueError):
    """A saved local query cannot be evaluated against its source tables."""


JOIN_KINDS = {
    "inner",
    "left_outer",
    "right_outer",
    "full_outer",
    "left_anti",
    "right_anti",
}


def append_candidates(candidates: Sequence[ImportCandidate]) -> ImportCandidate:
    """Append two or more tables with identical ordered schemas."""
    if len(candidates) < 2:
        raise QueryError("Append queries needs at least two source tables.")
    first = candidates[0]
    if not isinstance(first, ImportCandidate) or not first.headers:
        raise QueryError("The first append source is not a loaded table.")
    headers = list(first.headers)
    rows = []
    for index, candidate in enumerate(candidates, 1):
        if not isinstance(candidate, ImportCandidate):
            raise QueryError(f"Append source {index} is not a loaded table.")
        if candidate.headers != headers:
            raise QueryError(
                f"Append source {index} has a different ordered column schema. "
                "Rename or reorder its columns before appending."
            )
        if len(rows) + len(candidate.rows) > MAX_DATA_ROWS:
            raise QueryError(f"The appended table exceeds the {MAX_DATA_ROWS:,}-row limit.")
        rows.extend(deepcopy(candidate.rows))
    if len(headers) > MAX_COLUMNS:
        raise QueryError(f"The appended table exceeds the {MAX_COLUMNS:,}-column limit.")
    if len(rows) * len(headers) > MAX_CELLS:
        raise QueryError(f"The appended table exceeds the {MAX_CELLS:,}-cell limit.")
    return ImportCandidate(
        kind="query",
        headers=headers,
        rows=rows,
        options={"operation": "append"},
        notices=[],
    )


def merge_candidates(
    left: ImportCandidate,
    right: ImportCandidate,
    *,
    left_keys: Sequence[str],
    right_keys: Sequence[str],
    join_kind: str,
    right_name: str = "Right",
) -> ImportCandidate:
    """Join two tables by exact key values and flatten both sides into columns."""
    if not isinstance(left, ImportCandidate) or not left.headers:
        raise QueryError("The left merge source is not a loaded table.")
    if not isinstance(right, ImportCandidate) or not right.headers:
        raise QueryError("The right merge source is not a loaded table.")
    left_keys = list(left_keys)
    right_keys = list(right_keys)
    if not left_keys or len(left_keys) != len(right_keys):
        raise QueryError("Choose the same number of key columns from both tables.")
    if len(set(left_keys)) != len(left_keys) or len(set(right_keys)) != len(right_keys):
        raise QueryError("A key column can only be selected once per table.")
    if join_kind not in JOIN_KINDS:
        raise QueryError(f"Unsupported merge join kind: {join_kind!r}.")
    for side, keys, headers in (
        ("left", left_keys, left.headers),
        ("right", right_keys, right.headers),
    ):
        missing = next((key for key in keys if key not in headers), None)
        if missing is not None:
            raise QueryError(f"The {side} merge table has no key column {missing!r}.")

    output_headers = list(left.headers)
    column_sources: dict[str, dict[str, str]] = {
        header: {"side": "left", "column": header} for header in left.headers
    }
    used_headers = set(output_headers)
    right_name = right_name.strip() or "Right"
    for header in right.headers:
        output_header = header
        if output_header in used_headers:
            output_header = f"{right_name}.{header}"
        base_name = output_header
        suffix = 2
        while output_header in used_headers:
            output_header = f"{base_name}.{suffix}"
            suffix += 1
        used_headers.add(output_header)
        output_headers.append(output_header)
        column_sources[output_header] = {"side": "right", "column": header}

    if len(output_headers) > MAX_COLUMNS:
        raise QueryError(f"The merged table exceeds the {MAX_COLUMNS:,}-column limit.")

    right_index: dict[tuple[str, ...], list[int]] = defaultdict(list)
    right_keys_by_row: list[tuple[str, ...] | None] = []
    for row_index, row in enumerate(right.rows):
        key = _merge_key(row, right_keys)
        right_keys_by_row.append(key)
        if key is not None:
            right_index[key].append(row_index)
    left_keys_present = {
        key for row in left.rows
        if (key := _merge_key(row, left_keys)) is not None
    }

    output_rows: list[dict[str, str]] = []
    matched_right: set[int] = set()

    def add_row(left_index: int | None, right_index_value: int | None) -> None:
        if len(output_rows) >= MAX_DATA_ROWS:
            raise QueryError(f"The merged table exceeds the {MAX_DATA_ROWS:,}-row limit.")
        if (len(output_rows) + 1) * len(output_headers) > MAX_CELLS:
            raise QueryError(f"The merged table exceeds the {MAX_CELLS:,}-cell limit.")
        left_row = left.rows[left_index] if left_index is not None else None
        right_row = right.rows[right_index_value] if right_index_value is not None else None
        output: dict[str, str] = {}
        for header in left.headers:
            value = left_row.get(header, "") if left_row is not None else ""
            output[header] = "" if value is None else str(value)
        for output_header in output_headers[len(left.headers):]:
            source_column = column_sources[output_header]["column"]
            value = right_row.get(source_column, "") if right_row is not None else ""
            output[output_header] = "" if value is None else str(value)
        output_rows.append(output)

    for left_index, row in enumerate(left.rows):
        key = _merge_key(row, left_keys)
        matches = right_index.get(key, []) if key is not None else []
        if join_kind == "left_anti":
            if not matches:
                add_row(left_index, None)
            continue
        if join_kind == "right_anti":
            continue
        if matches:
            for right_index_value in matches:
                matched_right.add(right_index_value)
                add_row(left_index, right_index_value)
        elif join_kind in {"left_outer", "full_outer"}:
            add_row(left_index, None)

    if join_kind == "right_anti":
        for right_index_value, key in enumerate(right_keys_by_row):
            if key is None or key not in left_keys_present:
                add_row(None, right_index_value)
    elif join_kind in {"right_outer", "full_outer"}:
        for right_index_value in range(len(right.rows)):
            if right_index_value not in matched_right:
                add_row(None, right_index_value)

    return ImportCandidate(
        kind="query",
        headers=output_headers,
        rows=output_rows,
        options={"operation": "merge", "column_sources": column_sources},
        notices=[],
    )


def _merge_key(row: dict[str, str], columns: Sequence[str]) -> tuple[str, ...] | None:
    values = tuple(row.get(column, "") for column in columns)
    if any(value is None or str(value) == "" for value in values):
        return None
    return tuple(str(value) for value in values)
