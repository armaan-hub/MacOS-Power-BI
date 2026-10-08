"""Local CALENDAR and CALENDARAUTO table generation."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any

from analytics_studio.file_import import MAX_DATA_ROWS, ImportCandidate


class CalendarTableError(ValueError):
    """A generated calendar definition or its source dates are invalid."""


def parse_calendar_date(value: Any, *, label: str) -> date:
    """Parse one canonical ISO calendar date from a saved definition."""
    if not isinstance(value, str) or not value.strip():
        raise CalendarTableError(f"{label} must be an ISO date (YYYY-MM-DD).")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise CalendarTableError(f"{label} must be an ISO date (YYYY-MM-DD).") from exc
    if parsed.isoformat() != value:
        raise CalendarTableError(f"{label} must be an ISO date (YYYY-MM-DD).")
    return parsed


def _calendar_rows(start: date, end: date) -> list[dict[str, str]]:
    validate_calendar_range(start, end)
    day_count = (end - start).days + 1
    return [
        {"Date": (start + timedelta(days=offset)).isoformat()}
        for offset in range(day_count)
    ]


def validate_calendar_range(start: date, end: date) -> tuple[date, date]:
    """Check range order and the local generated-table row limit."""
    if start > end:
        raise CalendarTableError("The calendar start date must be on or before its end date.")
    day_count = (end - start).days + 1
    if day_count > MAX_DATA_ROWS:
        raise CalendarTableError(
            f"The calendar range has {day_count:,} days; the table limit is {MAX_DATA_ROWS:,} rows."
        )
    return start, end


def generate_calendar(start_value: Any, end_value: Any) -> ImportCandidate:
    """Generate CALENDAR's inclusive, one-column date range."""
    start = parse_calendar_date(start_value, label="The calendar start date")
    end = parse_calendar_date(end_value, label="The calendar end date")
    return ImportCandidate("query", ["Date"], _calendar_rows(start, end), {}, [])


def _parse_model_date(value: Any, column_type: str, *, label: str) -> date | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    try:
        if column_type == "date":
            parsed = date.fromisoformat(text)
            if parsed.isoformat() != text:
                raise ValueError
            return parsed
        if column_type == "datetime":
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except (TypeError, ValueError, OverflowError) as exc:
        raise CalendarTableError(
            f"{label} contains a value that is not a valid {column_type} date."
        ) from exc
    raise CalendarTableError(f"{label} must have the date or datetime model type.")


def _fiscal_year_start(value: date, fiscal_year_end_month: int) -> date:
    start_month = fiscal_year_end_month % 12 + 1
    year = value.year if value.month >= start_month else value.year - 1
    try:
        return date(year, start_month, 1)
    except ValueError as exc:
        raise CalendarTableError("The fiscal-year range is outside the supported date range.") from exc


def _fiscal_year_end(value: date, fiscal_year_end_month: int) -> date:
    year = value.year if value.month <= fiscal_year_end_month else value.year + 1
    last_day = monthrange(year, fiscal_year_end_month)[1]
    try:
        return date(year, fiscal_year_end_month, last_day)
    except ValueError as exc:
        raise CalendarTableError("The fiscal-year range is outside the supported date range.") from exc


def generate_calendar_auto(
    candidates: dict[str, ImportCandidate],
    date_columns: list[dict[str, str]],
    fiscal_year_end_month: Any = 12,
) -> ImportCandidate:
    """Generate full fiscal years around all saved model date-column values."""
    if (
        not isinstance(fiscal_year_end_month, int)
        or isinstance(fiscal_year_end_month, bool)
        or not 1 <= fiscal_year_end_month <= 12
    ):
        raise CalendarTableError("The fiscal year end month must be between 1 and 12.")
    if not isinstance(date_columns, list) or not date_columns:
        raise CalendarTableError("Choose at least one model date or datetime column.")

    dates: list[date] = []
    seen_columns: set[tuple[str, str]] = set()
    for definition in date_columns:
        if not isinstance(definition, dict):
            raise CalendarTableError("A CALENDARAUTO date-column definition is invalid.")
        source_id = definition.get("source_id")
        column = definition.get("column")
        column_type = definition.get("type")
        if (
            not isinstance(source_id, str) or not source_id
            or not isinstance(column, str) or not column
            or column_type not in {"date", "datetime"}
        ):
            raise CalendarTableError("A CALENDARAUTO date-column definition is invalid.")
        column_key = (source_id, column)
        if column_key in seen_columns:
            raise CalendarTableError("A CALENDARAUTO date column is listed more than once.")
        seen_columns.add(column_key)
        candidate = candidates.get(source_id)
        if candidate is None:
            raise CalendarTableError(f"The source table for {column!r} is not loaded.")
        if column not in candidate.headers:
            raise CalendarTableError(f"The model date column {column!r} is no longer available.")
        label = f"{source_id}[{column}]"
        for row in candidate.rows:
            value = row.get(column)
            parsed = _parse_model_date(value, column_type, label=label)
            if parsed is not None:
                dates.append(parsed)

    if not dates:
        raise CalendarTableError("No nonblank date or datetime values were found in the model.")
    start = _fiscal_year_start(min(dates), fiscal_year_end_month)
    end = _fiscal_year_end(max(dates), fiscal_year_end_month)
    return ImportCandidate("query", ["Date"], _calendar_rows(start, end), {}, [])


def calendar_expression(definition: dict[str, Any]) -> str:
    """Return the DAX-like expression shown for a saved calendar table."""
    operation = definition.get("operation")
    if operation == "calendar":
        start = parse_calendar_date(
            definition.get("start_date"), label="The calendar start date"
        )
        end = parse_calendar_date(
            definition.get("end_date"), label="The calendar end date"
        )
        return (
            f"CALENDAR(DATE({start.year}, {start.month}, {start.day}), "
            f"DATE({end.year}, {end.month}, {end.day}))"
        )
    if operation == "calendar_auto":
        month = definition.get("fiscal_year_end_month", 12)
        if month == 12:
            return "CALENDARAUTO()"
        return f"CALENDARAUTO({month})"
    return ""
