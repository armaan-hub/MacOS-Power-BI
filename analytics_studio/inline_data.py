"""Bounded helpers for editable, project-embedded tabular data."""

from __future__ import annotations

import csv
import io
import json
import math
import threading
from typing import Any

from analytics_studio.file_import import ImportCandidate


MAX_INLINE_ROWS = 100_000
MAX_INLINE_COLUMNS = 512
MAX_INLINE_CELLS = 500_000
MAX_INLINE_SERIALIZED_BYTES = 10 * 1024 * 1024
_CSV_FIELD_LIMIT_LOCK = threading.RLock()


class InlineDataError(ValueError):
    """An inline table is malformed or exceeds a supported limit."""


def normalize_inline_data(
    headers: Any,
    rows: Any,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Validate and copy a path-independent table payload for an inline source."""
    if not isinstance(headers, list) or not headers:
        raise InlineDataError("Inline data must have at least one column.")
    if len(headers) > MAX_INLINE_COLUMNS:
        raise InlineDataError(f"Inline data exceeds the {MAX_INLINE_COLUMNS:,}-column limit.")

    normalized_headers: list[str] = []
    seen_headers: set[str] = set()
    for header in headers:
        if not isinstance(header, str) or not header.strip() or "\x00" in header:
            raise InlineDataError("Each inline column needs a non-empty text name.")
        if header != header.strip():
            raise InlineDataError("Inline column names must not have surrounding whitespace.")
        if header in seen_headers:
            raise InlineDataError(f"Inline column name {header!r} is duplicated.")
        seen_headers.add(header)
        normalized_headers.append(header)

    if not isinstance(rows, list):
        raise InlineDataError("Inline data rows must be a list.")
    if len(rows) > MAX_INLINE_ROWS:
        raise InlineDataError(f"Inline data exceeds the {MAX_INLINE_ROWS:,}-row limit.")
    if len(rows) * len(normalized_headers) > MAX_INLINE_CELLS:
        raise InlineDataError(f"Inline data exceeds the {MAX_INLINE_CELLS:,}-cell limit.")

    normalized_rows: list[dict[str, Any]] = []
    expected_keys = set(normalized_headers)
    for row_index, row in enumerate(rows, start=1):
        if not isinstance(row, dict) or set(row) != expected_keys:
            raise InlineDataError(
                f"Inline row {row_index} must contain exactly the declared columns."
            )
        normalized_row: dict[str, Any] = {}
        for header in normalized_headers:
            cell = row[header]
            if not _is_json_scalar(cell):
                raise InlineDataError(
                    f"Inline row {row_index}, column {header!r} must contain a scalar or null."
                )
            normalized_row[header] = cell
        normalized_rows.append(normalized_row)

    try:
        encoded = json.dumps(
            {"headers": normalized_headers, "rows": normalized_rows},
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise InlineDataError("Inline data cannot be serialized as UTF-8 JSON.") from exc
    if len(encoded) > MAX_INLINE_SERIALIZED_BYTES:
        raise InlineDataError(
            "Inline data exceeds the "
            f"{MAX_INLINE_SERIALIZED_BYTES // (1024 * 1024)} MiB serialized-data limit."
        )

    return normalized_headers, normalized_rows


def parse_pasted_table(
    text: str,
    name: str = "Pasted data",
    delimiter: str | None = None,
) -> ImportCandidate:
    """Parse pasted CSV or TSV with a header row into an uncommitted candidate."""
    if not isinstance(text, str):
        raise InlineDataError("Pasted table contents must be text.")
    if not isinstance(name, str) or not name.strip() or "\x00" in name:
        raise InlineDataError("Inline data needs a non-empty name.")

    if delimiter is None:
        first_line = next((line for line in text.splitlines() if line.strip()), "")
        delimiter = "\t" if "\t" in first_line else ","
    if delimiter not in {",", "\t"}:
        raise InlineDataError("Choose comma or tab as the pasted-table delimiter.")

    try:
        text_size = len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise InlineDataError("Pasted table contains text that cannot be encoded as UTF-8.") from exc
    if text_size > MAX_INLINE_SERIALIZED_BYTES:
        raise InlineDataError(
            "Pasted table exceeds the "
            f"{MAX_INLINE_SERIALIZED_BYTES // (1024 * 1024)} MiB input limit."
        )

    raw_rows: list[list[str]] = []
    with _CSV_FIELD_LIMIT_LOCK:
        old_field_limit = csv.field_size_limit()
        csv.field_size_limit(MAX_INLINE_SERIALIZED_BYTES)
        try:
            reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
            widest_record = 0
            for record in reader:
                is_blank_header = not raw_rows and len(record) > 1
                if not record or (all(value == "" for value in record) and not is_blank_header):
                    continue
                if len(record) > MAX_INLINE_COLUMNS:
                    raise InlineDataError(
                        f"Inline data exceeds the {MAX_INLINE_COLUMNS:,}-column limit."
                    )
                raw_rows.append(record)
                if len(raw_rows) > MAX_INLINE_ROWS + 1:
                    raise InlineDataError(f"Inline data exceeds the {MAX_INLINE_ROWS:,}-row limit.")
                widest_record = max(widest_record, len(record))
                data_count = len(raw_rows) - 1
                if data_count * max(widest_record, len(raw_rows[0])) > MAX_INLINE_CELLS:
                    raise InlineDataError(f"Inline data exceeds the {MAX_INLINE_CELLS:,}-cell limit.")
        except csv.Error as exc:
            raise InlineDataError(f"Could not parse pasted table: {exc}.") from exc
        finally:
            csv.field_size_limit(old_field_limit)

    if not raw_rows:
        raise InlineDataError("Pasted table is empty and has no header row.")

    raw_headers = raw_rows[0]
    records = raw_rows[1:]
    width = max(len(raw_headers), widest_record)
    if width > MAX_INLINE_COLUMNS:
        raise InlineDataError(f"Inline data exceeds the {MAX_INLINE_COLUMNS:,}-column limit.")
    if len(records) * width > MAX_INLINE_CELLS:
        raise InlineDataError(f"Inline data exceeds the {MAX_INLINE_CELLS:,}-cell limit.")

    headers = _normalize_headers(raw_headers, width)
    normalized_rows = [
        dict(zip(headers, record + [""] * (width - len(record))))
        for record in records
    ]
    headers, normalized_rows = normalize_inline_data(headers, normalized_rows)

    return ImportCandidate(
        "inline",
        headers,
        normalized_rows,
        {"name": name.strip(), "delimiter": delimiter},
        [],
    )


def sample_candidate() -> ImportCandidate:
    """Return a deterministic small table that exercises the report's known fields."""
    headers = ["Order Date", "Region", "Revenue", "Cost", "Margin", "Units"]
    rows = [
        {
            "Order Date": "2025-01-15", "Region": "East", "Revenue": "125000",
            "Cost": "72000", "Margin": "53000", "Units": "125",
        },
        {
            "Order Date": "2025-01-22", "Region": "West", "Revenue": "98000",
            "Cost": "61000", "Margin": "37000", "Units": "98",
        },
        {
            "Order Date": "2025-02-12", "Region": "East", "Revenue": "141000",
            "Cost": "81000", "Margin": "60000", "Units": "141",
        },
        {
            "Order Date": "2025-02-20", "Region": "North", "Revenue": "87000",
            "Cost": "54000", "Margin": "33000", "Units": "87",
        },
        {
            "Order Date": "2025-03-09", "Region": "West", "Revenue": "116000",
            "Cost": "69000", "Margin": "47000", "Units": "116",
        },
    ]
    return ImportCandidate("inline", headers, rows, {"name": "Sample data"}, [])


def source_from_candidate(
    candidate: ImportCandidate,
    source_id: str,
    name: str | None = None,
) -> dict[str, Any]:
    """Build the pathless project source record for an inline candidate."""
    if not isinstance(candidate, ImportCandidate) or candidate.kind != "inline":
        raise InlineDataError("Only inline candidates can become inline project sources.")
    if not isinstance(source_id, str) or not source_id.strip() or "\x00" in source_id:
        raise InlineDataError("An inline source needs a non-empty ID.")
    source_name = name if name is not None else candidate.options.get("name", "Pasted data")
    if not isinstance(source_name, str) or not source_name.strip() or "\x00" in source_name:
        raise InlineDataError("An inline source needs a non-empty name.")
    headers, rows = normalize_inline_data(candidate.headers, candidate.rows)
    return {
        "id": source_id,
        "name": source_name.strip(),
        "kind": "inline",
        "headers": headers,
        "rows": rows,
    }


def _normalize_headers(raw_headers: list[str], width: int) -> list[str]:
    headers: list[str] = []
    used: set[str] = set()
    for index in range(width):
        raw = raw_headers[index] if index < len(raw_headers) else ""
        base = raw.strip() or f"Column {index + 1}"
        header = base
        suffix = 2
        while header in used:
            header = f"{base}_{suffix}"
            suffix += 1
        used.add(header)
        headers.append(header)
    return headers


def _is_json_scalar(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    return isinstance(value, float) and math.isfinite(value)
