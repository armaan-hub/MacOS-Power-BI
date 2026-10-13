"""Cell values shared by the bounded Power Query import and transform pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class PowerQueryCellError:
    """A cell-level M error, including the step-input row that produced it."""

    reason: str
    message: str
    value: Any = None
    target_type: str | None = None
    culture: str | None = None
    row: int | None = None

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
