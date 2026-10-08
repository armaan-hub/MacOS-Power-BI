"""Validation helpers for date tables used by classic time intelligence."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any


class DateTableError(ValueError):
    """A selected model column does not satisfy the date-table rules."""


def validate_date_table_rows(
    rows: list[dict[str, Any]], column: str, column_type: str
) -> int:
    """Validate date values and return their count.

    This local marking subset follows the core Power BI checks: a typed date or
    datetime column with no blanks, unique calendar dates, and no gaps. DateTime
    columns must also use one consistent time of day.
    """
    if column_type not in {"date", "datetime"}:
        raise DateTableError("Choose a column whose model type is date or datetime.")
    if not isinstance(column, str) or not column.strip():
        raise DateTableError("Choose a date column.")
    if not rows:
        raise DateTableError("A date table must contain at least one date.")

    dates: list[date] = []
    times: set[tuple[int, int, int, int]] = set()
    for row_number, row in enumerate(rows, start=1):
        raw_value = row.get(column)
        value = "" if raw_value is None else str(raw_value).strip()
        if not value:
            raise DateTableError(
                f"Date row {row_number} in {column!r} is blank. Date tables cannot contain blank dates."
            )
        try:
            if column_type == "date":
                parsed_date = date.fromisoformat(value)
                if parsed_date.isoformat() != value:
                    raise ValueError
            else:
                parsed_datetime = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed_datetime.utcoffset() is not None:
                    raise DateTableError(
                        f"DateTime values in {column!r} must not include timezone offsets."
                    )
                parsed_date = parsed_datetime.date()
                times.add((
                    parsed_datetime.hour,
                    parsed_datetime.minute,
                    parsed_datetime.second,
                    parsed_datetime.microsecond,
                ))
        except DateTableError:
            raise
        except (TypeError, ValueError, OverflowError) as exc:
            raise DateTableError(
                f"Date row {row_number} in {column!r} is not a valid {column_type} value."
            ) from exc
        dates.append(parsed_date)

    if column_type == "datetime" and len(times) != 1:
        raise DateTableError(
            f"DateTime values in {column!r} must all use the same time of day."
        )

    ordered = sorted(dates)
    if len(set(ordered)) != len(ordered):
        raise DateTableError(f"Date column {column!r} contains duplicate dates.")
    for previous, current in zip(ordered, ordered[1:]):
        if current != previous + timedelta(days=1):
            raise DateTableError(
                f"Date column {column!r} has a missing date between "
                f"{previous.isoformat()} and {current.isoformat()}."
            )
    return len(dates)
