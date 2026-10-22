"""Cell values shared by the bounded Power Query import and transform pipeline."""

from __future__ import annotations

import string
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any


MAX_SOURCE_LINEAGE_ROWS = 128


@dataclass(frozen=True)
class PowerQueryCellError:
    """A cell-level M error, including the step-input row that produced it."""

    reason: str
    message: str
    value: Any = None
    target_type: str | None = None
    culture: str | None = None
    row: int | None = None
    source_rows: tuple[tuple[str, int], ...] = ()
    source_rows_truncated: bool = False

    def __str__(self) -> str:
        return f"Error: {self.message}"


def is_cell_error(value: Any) -> bool:
    return isinstance(value, PowerQueryCellError)


def cell_to_text(value: Any, *, null_text: str = "") -> str:
    """Render a supported scalar at a text boundary without erasing its source value."""
    if value is None:
        return null_text
    if isinstance(value, PowerQueryCellError):
        return str(value)
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (date, datetime, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (str, int, float)):
        return str(value)
    raise TypeError(f"Unsupported table cell value: {type(value).__name__}.")


def is_supported_cell_value(value: Any) -> bool:
    """Return whether a cell uses the JSON-like scalar, temporal, or error contract."""
    if value is None or isinstance(value, (str, bool, int, date, datetime, time)):
        return True
    if isinstance(value, Decimal):
        return value.is_finite()
    if isinstance(value, float):
        return value == value and value not in {float("inf"), float("-inf")}
    if isinstance(value, PowerQueryCellError):
        return (
            isinstance(value.reason, str)
            and bool(value.reason)
            and isinstance(value.message, str)
            and bool(value.message)
            and (value.row is None or isinstance(value.row, int) and value.row >= 1)
            and (value.culture is None or isinstance(value.culture, str))
            and (value.target_type is None or isinstance(value.target_type, str))
            and isinstance(value.source_rows, tuple)
            and len(value.source_rows) <= MAX_SOURCE_LINEAGE_ROWS
            and all(
                isinstance(origin, tuple)
                and len(origin) == 2
                and isinstance(origin[0], str)
                and bool(origin[0])
                and isinstance(origin[1], int)
                and not isinstance(origin[1], bool)
                and origin[1] >= 1
                for origin in value.source_rows
            )
            and isinstance(value.source_rows_truncated, bool)
            and (
                value.value is None
                or isinstance(value.value, (str, bool, int, float, Decimal, date, datetime, time))
            )
        )
    return False


def cell_key(value: Any) -> tuple[Any, ...]:
    """Build a hashable key that keeps M scalar type, Null, empty text, and errors distinct."""
    if isinstance(value, PowerQueryCellError):
        return (
            "error", value.reason, value.message, cell_to_text(value.value),
            value.target_type, value.culture, value.row,
            value.source_rows, value.source_rows_truncated,
        )
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, (int, float, Decimal)):
        return ("number", Decimal(str(value)))
    if value is None:
        return ("null",)
    if isinstance(value, datetime):
        return ("datetime", value.isoformat())
    if isinstance(value, date):
        return ("date", value.isoformat())
    if isinstance(value, time):
        return ("time", value.isoformat())
    return ("text", value)


# Power BI's VertiPaq store (verified on 2.157.879.0) drops trailing characters U+0000-U+0020 from
# text it loads, compares and groups text case-insensitively for ASCII letters only, and keeps the
# first-seen spelling of every group. Calculated tables keep trailing spaces; Power Query keeps all of it.
_MODEL_TEXT_TRAILING = "".join(chr(code) for code in range(0x21))
_ASCII_FOLD = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)


def ascii_fold(text: str) -> str:
    """The key under which the model treats two text values as the same value."""
    return text.translate(_ASCII_FOLD)


def model_text_normalizer() -> Any:
    """Return a per-column function mapping loaded text to its model spelling.

    Each call to the returned function trims trailing control characters and spaces and then
    returns the first spelling seen for that ASCII-case-insensitive value, so call it in row order.
    """
    spellings: dict[str, str] = {}

    def normalize(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        trimmed = value.rstrip(_MODEL_TEXT_TRAILING)
        return spellings.setdefault(ascii_fold(trimmed), trimmed)

    return normalize
